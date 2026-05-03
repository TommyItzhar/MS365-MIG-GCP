"""Base Migrator — abstract interface every workload migrator must implement.

All async code; no blocking I/O on the event loop.
Inheritors get: Graph HTTP client, throttle manager, state manager, GCS writer,
structured logger, and error handler wired in automatically.
"""
from __future__ import annotations

import asyncio
import time
import uuid
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from app.auth.auth_manager import AuthManager
from app.config.settings import get_settings
from app.constants import GRAPH_BASE_URL, GRAPH_BATCH_MAX_REQUESTS
from app.errors.error_handler import (
    DLQPublisher,
    ErrorAggregator,
    classify_error,
    should_retry,
)
from app.models import (
    BatchResult,
    Checkpoint,
    MigrationItem,
    MigrationManifest,
    MigrationResult,
    MigrationScope,
    RollbackResult,
    VerificationResult,
    WorkloadType,
)
from app.monitoring.monitoring import MetricsReporter, MigrationLogger
from app.state.state_manager import StateManager
from app.throttle.throttle_manager import ThrottleManager
from app.writers.gcs_writer import GCSWriter

logger = logging.getLogger(__name__)


class BaseMigrator(ABC):
    """Abstract base class for all M365 workload migrators.

    Subclasses must implement: discover, migrate_item, verify, rollback.
    migrate_batch has a default implementation built on migrate_item.
    resume has a default implementation that calls migrate_batch.
    """

    workload: WorkloadType  # Must be set on each concrete class

    def __init__(
        self,
        auth: AuthManager,
        throttle: ThrottleManager,
        state: StateManager,
        gcs: GCSWriter,
        metrics: MetricsReporter,
        errors: ErrorAggregator,
        dlq: DLQPublisher,
        job_id: str,
    ) -> None:
        self._auth = auth
        self._throttle = throttle
        self._state = state
        self._gcs = gcs
        self._metrics = metrics
        self._errors = errors
        self._dlq = dlq
        self._job_id = job_id
        self._settings = get_settings()
        self._mlog = MigrationLogger(job_id, self.workload)
        self._http_client: Optional[httpx.AsyncClient] = None

    # ── HTTP client lifecycle ──────────────────────────────────────────────

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=GRAPH_BASE_URL,
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                ),
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ── Graph API helpers ──────────────────────────────────────────────────

    async def _graph_get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET a Graph API endpoint with throttle-aware retry."""
        client = await self._get_http_client()
        headers = await self._auth.get_graph_headers()

        async def _do_get() -> httpx.Response:
            resp = await client.get(path, headers=headers, params=params or {})
            resp.raise_for_status()
            return resp

        response = await self._throttle.execute(self.workload, _do_get)
        return response.json()  # type: ignore[union-attr]

    async def _graph_paginate(
        self, path: str, params: Optional[dict] = None
    ):
        """Yield all pages of a Graph list endpoint, following @odata.nextLink."""
        url: Optional[str] = path
        all_params = dict(params or {})
        if "$top" not in all_params:
            all_params["$top"] = 999

        while url:
            data = await self._graph_get(url, all_params if url == path else None)
            items = data.get("value", [])
            yield items
            url = data.get("@odata.nextLink")

    async def _graph_batch(
        self, requests: list[dict]
    ) -> list[dict]:
        """Execute up to 20 Graph requests in a single $batch call."""
        client = await self._get_http_client()
        headers = await self._auth.get_graph_headers()
        results: list[dict] = []

        for i in range(0, len(requests), GRAPH_BATCH_MAX_REQUESTS):
            chunk = requests[i : i + GRAPH_BATCH_MAX_REQUESTS]
            body = {
                "requests": [
                    {
                        "id": str(idx + 1),
                        "method": r.get("method", "GET"),
                        "url": r["url"],
                        **(
                            {"headers": r["headers"]}
                            if "headers" in r
                            else {}
                        ),
                        **(
                            {"body": r["body"]}
                            if "body" in r
                            else {}
                        ),
                    }
                    for idx, r in enumerate(chunk)
                ]
            }

            async def _do_batch() -> httpx.Response:
                resp = await client.post(
                    "/$batch", headers=headers, json=body
                )
                resp.raise_for_status()
                return resp

            response = await self._throttle.execute(self.workload, _do_batch)
            batch_data = response.json()  # type: ignore[union-attr]
            results.extend(batch_data.get("responses", []))

        return results

    # ── Abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        """Discover all items for this workload and return a manifest."""
        ...

    @abstractmethod
    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        """Migrate a single item. Must be idempotent."""
        ...

    @abstractmethod
    async def verify(self, item: MigrationItem) -> VerificationResult:
        """Verify a migrated item against the source."""
        ...

    @abstractmethod
    async def rollback(self, item: MigrationItem) -> RollbackResult:
        """Remove a migrated item from GCS (used on job cancel)."""
        ...

    # ── Default batch / resume implementations ─────────────────────────────

    async def migrate_batch(
        self, items: list[MigrationItem]
    ) -> BatchResult:
        """Migrate a batch of items concurrently under the workload semaphore."""
        result = BatchResult(job_id=self._job_id, workload=self.workload)
        tasks = [self._safe_migrate(item) for item in items]
        outcomes = await asyncio.gather(*tasks, return_exceptions=False)

        for outcome in outcomes:
            if outcome.success:
                result.successful.append(outcome)
                result.total_bytes += outcome.bytes_transferred
            else:
                result.failed.append(outcome)

        return result

    async def _safe_migrate(self, item: MigrationItem) -> MigrationResult:
        """Wrap migrate_item with state tracking, DLQ escalation, and metrics."""
        # Idempotency check — skip if already completed
        if await self._state.is_already_migrated(item.id):
            self._mlog.item_skipped(item.id, "already_completed")
            return MigrationResult(
                item_id=item.id, success=True, bytes_transferred=0
            )

        await self._state.mark_in_progress(item.id)
        self._mlog.item_started(item.id, item.source_id)
        start = time.monotonic()

        try:
            result = await self.migrate_item(item)
            duration = time.monotonic() - start

            if result.success:
                await self._state.mark_completed(
                    item.id,
                    result.gcs_uri or "",
                    result.bytes_transferred,
                )
                self._metrics.record_item_migrated(
                    self.workload, result.bytes_transferred
                )
                self._mlog.item_completed(
                    item.id,
                    result.gcs_uri or "",
                    result.bytes_transferred,
                    duration,
                )
            else:
                error_type = result.error_type or classify_error(
                    Exception(result.error or "unknown")
                )
                await self._state.mark_failed(
                    item.id,
                    result.error or "unknown",
                    error_type.value,
                    item.retry_count,
                )
                self._metrics.record_item_failed(self.workload, error_type)
                self._mlog.item_failed(
                    item.id, result.error or "", error_type, item.retry_count
                )
                if not should_retry(error_type, item.retry_count):
                    self._dlq.publish(item, result.error or "", error_type)
                    self._errors.record(
                        self._job_id, item.id, self.workload,
                        error_type, result.error or "", item.retry_count,
                        is_dlq=True, source_id=item.source_id,
                    )

            return result
        except Exception as exc:
            duration = time.monotonic() - start
            error_type = classify_error(exc)
            error_msg = str(exc)
            await self._state.mark_failed(
                item.id, error_msg, error_type.value, item.retry_count
            )
            self._metrics.record_item_failed(self.workload, error_type)
            self._mlog.item_failed(
                item.id, error_msg, error_type, item.retry_count
            )
            if not should_retry(error_type, item.retry_count):
                self._dlq.publish(item, error_msg, error_type)
            logger.exception(
                "migrate_item_exception",
                extra={"item_id": item.id, "workload": self.workload.value},
            )
            return MigrationResult(
                item_id=item.id,
                success=False,
                error=error_msg,
                error_type=error_type,
                duration_seconds=duration,
            )

    async def resume(self, checkpoint: Checkpoint) -> None:
        """Resume migration from a checkpoint (after crash/pause).

        Subclasses may override to use delta tokens or cursor-based pagination.
        """
        logger.info(
            "migrator_resuming",
            extra={
                "job_id": self._job_id,
                "workload": self.workload.value,
                "entity_id": checkpoint.entity_id,
                "last_processed": checkpoint.last_processed_id,
                "count": checkpoint.processed_count,
            },
        )
