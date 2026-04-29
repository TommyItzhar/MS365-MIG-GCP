"""Discovery Engine — full tenant inventory scan with dependency graph.

Produces a MigrationManifest stored in Firestore and GCS before migration
begins. Supports incremental re-discovery using Graph delta tokens.

Dependency order enforced:
  Identity → Exchange + OneDrive + SharePoint → Teams + Groups → everything else
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.auth.auth_manager import AuthManager
from app.config.settings import get_settings
from app.errors.error_handler import DLQPublisher, ErrorAggregator
from app.migrators.exchange_migrator import ExchangeMigrator
from app.migrators.forms_migrator import FormsMigrator
from app.migrators.groups_migrator import GroupsMigrator
from app.migrators.identity_migrator import IdentityMigrator
from app.migrators.intune_migrator import IntuneMigrator
from app.migrators.onedrive_migrator import OneDriveMigrator
from app.migrators.planner_migrator import PlannerMigrator
from app.migrators.powerautomate_migrator import PowerAutomateMigrator
from app.migrators.sharepoint_migrator import SharePointMigrator
from app.migrators.teams_migrator import TeamsMigrator
from app.migrators.chat_migrator import ChatMigrator
from app.models import (
    MigrationManifest,
    MigrationScope,
    WorkloadType,
)
from app.monitoring.monitoring import MetricsReporter
from app.state.state_manager import StateManager
from app.throttle.throttle_manager import ThrottleManager
from app.writers.gcs_writer import GCSWriter, build_gcs_path

logger = logging.getLogger(__name__)


def _build_migrator(
    workload: WorkloadType,
    auth: AuthManager,
    throttle: ThrottleManager,
    state: StateManager,
    gcs: GCSWriter,
    metrics: MetricsReporter,
    errors: ErrorAggregator,
    dlq: DLQPublisher,
    job_id: str,
):
    """Factory returning the correct migrator for each workload type."""
    kwargs = dict(
        auth=auth, throttle=throttle, state=state,
        gcs=gcs, metrics=metrics, errors=errors, dlq=dlq, job_id=job_id,
    )
    mapping = {
        WorkloadType.EXCHANGE: ExchangeMigrator,
        WorkloadType.ONEDRIVE: OneDriveMigrator,
        WorkloadType.SHAREPOINT: SharePointMigrator,
        WorkloadType.TEAMS: TeamsMigrator,
        WorkloadType.TEAMS_CHAT: ChatMigrator,
        WorkloadType.GROUPS: GroupsMigrator,
        WorkloadType.IDENTITY: IdentityMigrator,
        WorkloadType.INTUNE: IntuneMigrator,
        WorkloadType.POWER_AUTOMATE: PowerAutomateMigrator,
        WorkloadType.FORMS: FormsMigrator,
        WorkloadType.PLANNER: PlannerMigrator,
    }
    cls = mapping.get(workload)
    if cls is None:
        raise ValueError(f"Unknown workload: {workload}")
    return cls(**kwargs)


class DiscoveryEngine:
    """Runs full-tenant discovery across all requested workloads.

    Usage::

        engine = DiscoveryEngine(auth, throttle, state, gcs, metrics, errors, dlq)
        manifest = await engine.discover(scope, job_id)
    """

    def __init__(
        self,
        auth: AuthManager,
        throttle: ThrottleManager,
        state: StateManager,
        gcs: GCSWriter,
        metrics: MetricsReporter,
        errors: ErrorAggregator,
        dlq: DLQPublisher,
    ) -> None:
        self._auth = auth
        self._throttle = throttle
        self._state = state
        self._gcs = gcs
        self._metrics = metrics
        self._errors = errors
        self._dlq = dlq
        self._settings = get_settings()

    async def discover(
        self, scope: MigrationScope, job_id: str
    ) -> MigrationManifest:
        """Run discovery for all workloads in scope and return merged manifest."""
        logger.info(
            "discovery_started",
            extra={
                "job_id": job_id,
                "tenant_id": scope.tenant_id,
                "workloads": [w.value for w in scope.workloads],
            },
        )

        combined_items = []
        total_bytes = 0
        workload_summary: dict[str, dict[str, int]] = {}

        # Run discoveries concurrently (they're all read-only Graph calls)
        tasks = []
        for workload in scope.workloads:
            migrator = _build_migrator(
                workload=workload,
                auth=self._auth,
                throttle=self._throttle,
                state=self._state,
                gcs=self._gcs,
                metrics=self._metrics,
                errors=self._errors,
                dlq=self._dlq,
                job_id=job_id,
            )
            tasks.append(self._discover_workload(workload, migrator, scope))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for workload, result in zip(scope.workloads, results):
            if isinstance(result, Exception):
                logger.error(
                    "discovery_workload_failed",
                    extra={
                        "workload": workload.value,
                        "error": str(result),
                    },
                )
                continue
            manifest: MigrationManifest = result
            combined_items.extend(manifest.items)
            total_bytes += manifest.total_bytes
            workload_summary[workload.value] = {
                "item_count": manifest.total_items,
                "bytes": manifest.total_bytes,
            }

        full_manifest = MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=job_id,
            discovery_timestamp=datetime.utcnow(),
            items=combined_items,
            total_bytes=total_bytes,
            total_items=len(combined_items),
            workload_summary=workload_summary,
        )

        await self._persist_manifest(full_manifest, job_id)

        logger.info(
            "discovery_completed",
            extra={
                "job_id": job_id,
                "total_items": full_manifest.total_items,
                "total_bytes": total_bytes,
                "workloads": list(workload_summary.keys()),
            },
        )
        return full_manifest

    async def _discover_workload(
        self, workload: WorkloadType, migrator: object, scope: MigrationScope
    ) -> MigrationManifest:
        logger.info(
            "workload_discovery_started",
            extra={"workload": workload.value},
        )
        result = await migrator.discover(scope)  # type: ignore[union-attr]
        logger.info(
            "workload_discovery_completed",
            extra={
                "workload": workload.value,
                "item_count": result.total_items,
                "bytes": result.total_bytes,
            },
        )
        return result

    async def _persist_manifest(
        self, manifest: MigrationManifest, job_id: str
    ) -> None:
        """Save manifest to Firestore and GCS for durability."""
        manifest_data = manifest.model_dump(mode="json")

        await self._state.save_manifest(manifest_data)

        blob_path = build_gcs_path(
            tenant_id=manifest.tenant_id,
            workload="manifests",
            entity_id=job_id,
            item_id="discovery_manifest",
            ext=".json",
        )
        data = json.dumps(manifest_data, default=str).encode()
        await self._gcs.upload_bytes(data, blob_path, "application/json", overwrite=True)

        logger.info(
            "manifest_persisted",
            extra={"job_id": job_id, "gcs_path": blob_path},
        )
