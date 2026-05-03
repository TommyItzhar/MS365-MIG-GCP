"""Base class for all Google Workspace → Microsoft 365 migrators.

Provides: GW auth (DWD), M365 writer, throttle management, state tracking,
structured logging, and error aggregation. All concrete migrators extend this.

Security:
- GW credentials impersonate each user via DWD; subject email only at DEBUG
- M365 write tokens acquired with minimum required scopes
- Content (email bodies, file bytes) never logged
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.auth.gw_auth_manager import GWAuthManager
from app.errors.error_handler import (
    DLQPublisher,
    ErrorAggregator,
    classify_error,
    should_retry,
)
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    ItemState,
    MigrationResult,
)
from app.monitoring.monitoring import MetricsReporter
from app.state.state_manager import StateManager
from app.throttle.throttle_manager import ThrottleManager
from app.writers.m365_writer import M365Writer

logger = logging.getLogger(__name__)


class BaseGWMigrator(ABC):
    """Abstract base for GW→M365 workload migrators.

    Subclasses implement: discover_items, migrate_item.
    """

    workload: GWWorkloadType

    def __init__(
        self,
        gw_auth: GWAuthManager,
        m365_writer: M365Writer,
        m365_auth: Any,
        throttle: ThrottleManager,
        state: StateManager,
        metrics: MetricsReporter,
        errors: ErrorAggregator,
        dlq: DLQPublisher,
        job_id: str,
    ) -> None:
        self._gw_auth = gw_auth
        self._writer = m365_writer
        self._m365_auth = m365_auth
        self._throttle = throttle
        self._state = state
        self._metrics = metrics
        self._errors = errors
        self._dlq = dlq
        self._job_id = job_id

    # ── Abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        """Return all items to migrate for this workload and user."""
        ...

    @abstractmethod
    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        """Migrate a single item from GW to M365. Must be idempotent."""
        ...

    # ── Default batch implementation ───────────────────────────────────────

    async def migrate_batch(
        self, items: list[GWMigrationItem]
    ) -> list[MigrationResult]:
        """Migrate items concurrently with error isolation."""
        tasks = [self._safe_migrate(item) for item in items]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _safe_migrate(self, item: GWMigrationItem) -> MigrationResult:
        """Wrap migrate_item with state tracking, retries, and DLQ escalation."""
        if await self._state.is_already_migrated(item.id):
            logger.debug("gw_item_skipped_already_done", extra={"item_id": item.id})
            return MigrationResult(item_id=item.id, success=True)

        await self._state.mark_in_progress(item.id)
        start = time.monotonic()

        try:
            result = await self.migrate_item(item)
            duration = time.monotonic() - start

            if result.success:
                await self._state.mark_completed(
                    item.id, result.gcs_uri or "", result.bytes_transferred
                )
                logger.debug(
                    "gw_item_migrated",
                    extra={
                        "workload": self.workload.value,
                        "bytes": result.bytes_transferred,
                        "duration": round(duration, 2),
                    },
                )
            else:
                error_type = result.error_type or classify_error(
                    Exception(result.error or "unknown")
                )
                await self._state.mark_failed(
                    item.id, result.error or "unknown", error_type.value, item.retry_count
                )
                if not should_retry(error_type, item.retry_count):
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
            if not should_retry(error_type, item.retry_count):
                self._errors.record(
                    self._job_id, item.id, self.workload,
                    error_type, error_msg, item.retry_count,
                    is_dlq=True, source_id=item.source_id,
                )
            logger.exception(
                "gw_migrate_item_error",
                extra={"workload": self.workload.value},
            )
            return MigrationResult(
                item_id=item.id,
                success=False,
                error=error_msg,
                error_type=error_type,
                duration_seconds=duration,
            )
