"""State Manager — Firestore-backed per-item state, checkpointing, delta tokens.

State machine: PENDING → IN_PROGRESS → COMPLETED | FAILED | SKIPPED
Checkpoints are written every N items so crash recovery resumes from last good point.
Delta tokens are persisted and age-checked (Graph tokens expire after 30 days).
Duplicate detection via content hash prevents re-upload on idempotent re-runs.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from google.cloud.firestore import SERVER_TIMESTAMP

from app.constants import (
    CHECKPOINT_INTERVAL,
    DELTA_TOKEN_MAX_AGE_DAYS,
    FS_CHECKPOINTS,
    FS_DELTA_TOKENS,
    FS_ERRORS,
    FS_ITEMS,
    FS_JOBS,
    FS_MANIFESTS,
)
from app.models import (
    Checkpoint,
    ItemState,
    MigrationItem,
    MigrationJob,
    MigrationJobStatus,
    WorkloadProgress,
    WorkloadType,
)
from app.writers.firestore_writer import FirestoreWriter

logger = logging.getLogger(__name__)


class StateManager:
    """Central state repository for the migration engine.

    All state is durable in Firestore. The engine can crash and restart
    at any point and resume from the last checkpoint.
    """

    def __init__(self) -> None:
        self._fs = FirestoreWriter()
        self._item_counter: dict[str, int] = {}

    # ── Job lifecycle ──────────────────────────────────────────────────────

    async def create_job(self, job: MigrationJob) -> None:
        await self._fs.set(FS_JOBS, job.id, job.model_dump(mode="json"))
        logger.info("job_created", extra={"job_id": job.id})

    async def get_job(self, job_id: str) -> Optional[MigrationJob]:
        data = await self._fs.get(FS_JOBS, job_id)
        if data is None:
            return None
        return MigrationJob.model_validate(data)

    async def update_job_status(
        self,
        job_id: str,
        status: MigrationJobStatus,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        fields: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if status == MigrationJobStatus.RUNNING:
            fields["started_at"] = datetime.utcnow().isoformat()
        if status in (
            MigrationJobStatus.COMPLETED,
            MigrationJobStatus.FAILED,
            MigrationJobStatus.CANCELLED,
        ):
            fields["completed_at"] = datetime.utcnow().isoformat()
        if extra:
            fields.update(extra)
        await self._fs.update(FS_JOBS, job_id, fields)

    async def update_workload_progress(
        self,
        job_id: str,
        workload: WorkloadType,
        progress: WorkloadProgress,
    ) -> None:
        key = f"workload_progress.{workload.value}"
        await self._fs.update(
            FS_JOBS,
            job_id,
            {key: progress.model_dump(mode="json")},
        )

    # ── Item state ─────────────────────────────────────────────────────────

    async def upsert_item(self, item: MigrationItem) -> None:
        await self._fs.set(
            FS_ITEMS, item.id, item.model_dump(mode="json"), merge=True
        )

    async def get_item(self, item_id: str) -> Optional[MigrationItem]:
        data = await self._fs.get(FS_ITEMS, item_id)
        if data is None:
            return None
        return MigrationItem.model_validate(data)

    async def mark_in_progress(self, item_id: str) -> None:
        await self._fs.update(
            FS_ITEMS,
            item_id,
            {
                "state": ItemState.IN_PROGRESS.value,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    async def mark_completed(
        self,
        item_id: str,
        gcs_uri: str,
        bytes_transferred: int,
    ) -> None:
        await self._fs.update(
            FS_ITEMS,
            item_id,
            {
                "state": ItemState.COMPLETED.value,
                "gcs_uri": gcs_uri,
                "bytes_transferred": bytes_transferred,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    async def mark_failed(
        self,
        item_id: str,
        error: str,
        error_type: str,
        retry_count: int,
    ) -> None:
        await self._fs.update(
            FS_ITEMS,
            item_id,
            {
                "state": ItemState.FAILED.value,
                "error_message": error,
                "error_type": error_type,
                "retry_count": retry_count,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    async def mark_skipped(self, item_id: str, reason: str) -> None:
        await self._fs.update(
            FS_ITEMS,
            item_id,
            {
                "state": ItemState.SKIPPED.value,
                "error_message": reason,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    # ── Duplicate detection ────────────────────────────────────────────────

    async def is_already_migrated(self, item_id: str) -> bool:
        """Return True if this item completed successfully in a prior run."""
        data = await self._fs.get(FS_ITEMS, item_id)
        if data is None:
            return False
        return data.get("state") == ItemState.COMPLETED.value

    async def find_by_content_hash(
        self, job_id: str, content_hash: str
    ) -> Optional[str]:
        """Return GCS URI if an identical file was already uploaded in this job."""
        results = await self._fs.query(
            FS_ITEMS,
            filters=[
                ("job_id", "==", job_id),
                ("content_hash", "==", content_hash),
                ("state", "==", ItemState.COMPLETED.value),
            ],
            limit=1,
        )
        if results:
            return results[0].get("gcs_uri")
        return None

    # ── Checkpointing ──────────────────────────────────────────────────────

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        doc_id = f"{checkpoint.job_id}_{checkpoint.workload.value}_{checkpoint.entity_id}"
        await self._fs.set(
            FS_CHECKPOINTS,
            doc_id,
            checkpoint.model_dump(mode="json"),
        )
        logger.debug(
            "checkpoint_saved",
            extra={
                "job_id": checkpoint.job_id,
                "workload": checkpoint.workload.value,
                "entity_id": checkpoint.entity_id,
                "count": checkpoint.processed_count,
            },
        )

    async def get_checkpoint(
        self, job_id: str, workload: WorkloadType, entity_id: str
    ) -> Optional[Checkpoint]:
        doc_id = f"{job_id}_{workload.value}_{entity_id}"
        data = await self._fs.get(FS_CHECKPOINTS, doc_id)
        if data is None:
            return None
        return Checkpoint.model_validate(data)

    def should_checkpoint(self, counter_key: str) -> bool:
        """Return True every CHECKPOINT_INTERVAL items."""
        count = self._item_counter.get(counter_key, 0) + 1
        self._item_counter[counter_key] = count
        return count % CHECKPOINT_INTERVAL == 0

    # ── Delta tokens ───────────────────────────────────────────────────────

    async def save_delta_token(
        self, job_id: str, workload: WorkloadType, entity_id: str, token: str
    ) -> None:
        doc_id = f"{job_id}_{workload.value}_{entity_id}"
        await self._fs.set(
            FS_DELTA_TOKENS,
            doc_id,
            {
                "token": token,
                "workload": workload.value,
                "entity_id": entity_id,
                "created_at": datetime.utcnow().isoformat(),
            },
        )

    async def get_delta_token(
        self, job_id: str, workload: WorkloadType, entity_id: str
    ) -> Optional[str]:
        """Return a delta token only if it's within the safe age window."""
        doc_id = f"{job_id}_{workload.value}_{entity_id}"
        data = await self._fs.get(FS_DELTA_TOKENS, doc_id)
        if data is None:
            return None

        created_at_str = data.get("created_at")
        if created_at_str:
            created_at = datetime.fromisoformat(created_at_str)
            age = datetime.utcnow() - created_at
            if age > timedelta(days=DELTA_TOKEN_MAX_AGE_DAYS):
                logger.warning(
                    "delta_token_expired",
                    extra={
                        "entity_id": entity_id,
                        "age_days": age.days,
                    },
                )
                return None

        return data.get("token")

    # ── Manifest ───────────────────────────────────────────────────────────

    async def save_manifest(self, manifest_data: dict[str, Any]) -> None:
        job_id = manifest_data.get("job_id", str(uuid.uuid4()))
        await self._fs.set(FS_MANIFESTS, job_id, manifest_data)

    async def get_manifest(self, job_id: str) -> Optional[dict[str, Any]]:
        return await self._fs.get(FS_MANIFESTS, job_id)
