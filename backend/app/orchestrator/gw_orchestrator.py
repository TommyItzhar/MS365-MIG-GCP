"""GW → M365 Orchestrator — schedules and executes Google Workspace migrations.

Dependency execution order (GW→M365):
  Wave 0: identity  (users must exist in Entra ID first)
  Wave 1: gmail, drive, calendar, contacts  (parallel, per-user)
  Wave 2: chat  (spaces may reference users from wave 0)

Checkpoints are saved to Firestore so jobs can be resumed after interruption.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.auth.auth_manager import AuthManager
from app.auth.gw_auth_manager import GWAuthManager
from app.config.settings import get_settings
from app.constants import FS_GW_JOBS, FS_GW_ITEMS
from app.errors.error_handler import DLQPublisher, ErrorAggregator
from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.migrators.gw_to_m365.gmail_migrator import GmailMigrator
from app.migrators.gw_to_m365.drive_migrator import DriveMigrator
from app.migrators.gw_to_m365.calendar_migrator import CalendarMigrator
from app.migrators.gw_to_m365.contacts_migrator import ContactsMigrator
from app.migrators.gw_to_m365.chat_migrator import ChatMigrator
from app.migrators.gw_to_m365.identity_migrator import IdentityMigrator
from app.models import (
    GWMigrationScope,
    GWWorkloadType,
    MigrationJobStatus,
    WorkloadProgress,
)
from app.monitoring.monitoring import MetricsReporter
from app.state.state_manager import StateManager
from app.throttle.throttle_manager import ThrottleManager
from app.writers.m365_writer import M365Writer

logger = logging.getLogger(__name__)

# Wave definitions: each inner list runs in parallel; waves are sequential
GW_WORKLOAD_WAVES: list[list[GWWorkloadType]] = [
    [GWWorkloadType.IDENTITY],                                           # Wave 0
    [GWWorkloadType.GMAIL, GWWorkloadType.DRIVE,
     GWWorkloadType.CALENDAR, GWWorkloadType.CONTACTS],                  # Wave 1
    [GWWorkloadType.CHAT],                                               # Wave 2
]


def _build_gw_migrator(
    workload: GWWorkloadType,
    gw_auth: GWAuthManager,
    m365_writer: M365Writer,
    m365_auth: AuthManager,
    throttle: ThrottleManager,
    state: StateManager,
    metrics: MetricsReporter,
    errors: ErrorAggregator,
    dlq: DLQPublisher,
    job_id: str,
) -> BaseGWMigrator:
    """Factory: return the correct migrator for a GW workload."""
    kwargs = dict(
        gw_auth=gw_auth,
        m365_writer=m365_writer,
        m365_auth=m365_auth,
        throttle=throttle,
        state=state,
        metrics=metrics,
        errors=errors,
        dlq=dlq,
        job_id=job_id,
    )
    mapping: dict[GWWorkloadType, type] = {
        GWWorkloadType.GMAIL: GmailMigrator,
        GWWorkloadType.DRIVE: DriveMigrator,
        GWWorkloadType.CALENDAR: CalendarMigrator,
        GWWorkloadType.CONTACTS: ContactsMigrator,
        GWWorkloadType.CHAT: ChatMigrator,
        GWWorkloadType.IDENTITY: IdentityMigrator,
    }
    cls = mapping.get(workload)
    if cls is None:
        raise ValueError(f"No GW migrator registered for workload '{workload}'")
    return cls(**kwargs)  # type: ignore[arg-type]


class GWJobOrchestrator:
    """Orchestrates a full Google Workspace → Microsoft 365 migration job.

    Usage::

        orch = await GWJobOrchestrator.create()
        job_id = await orch.start(scope)
        await orch.pause(job_id)
        await orch.resume(job_id)
    """

    def __init__(
        self,
        gw_auth: GWAuthManager,
        m365_auth: AuthManager,
        m365_writer: M365Writer,
        throttle: ThrottleManager,
        state: StateManager,
        metrics: MetricsReporter,
        errors: ErrorAggregator,
        dlq: DLQPublisher,
    ) -> None:
        self._gw_auth = gw_auth
        self._m365_auth = m365_auth
        self._writer = m365_writer
        self._throttle = throttle
        self._state = state
        self._metrics = metrics
        self._errors = errors
        self._dlq = dlq
        self._settings = get_settings()
        self._active_jobs: dict[str, asyncio.Task] = {}
        self._pause_events: dict[str, asyncio.Event] = {}

    @classmethod
    async def create(cls) -> "GWJobOrchestrator":
        """Async factory — initialises all sub-components."""
        from app.auth.auth_manager import AuthManager
        from app.monitoring.monitoring import MetricsReporter
        from app.state.state_manager import StateManager
        from app.throttle.throttle_manager import ThrottleManager
        from app.errors.error_handler import DLQPublisher, ErrorAggregator

        gw_auth = await GWAuthManager.create()
        m365_auth = await AuthManager.create()
        writer = M365Writer(m365_auth)
        settings = get_settings()

        throttle = ThrottleManager()
        state = StateManager()
        metrics = MetricsReporter(settings.gcp.project_id)
        errors = ErrorAggregator()
        dlq = DLQPublisher(project_id=settings.gcp.project_id,
                           topic=settings.gcp.pubsub_dlq_topic)

        return cls(
            gw_auth=gw_auth,
            m365_auth=m365_auth,
            m365_writer=writer,
            throttle=throttle,
            state=state,
            metrics=metrics,
            errors=errors,
            dlq=dlq,
        )

    # ── Public control API ─────────────────────────────────────────────────

    async def start(self, scope: GWMigrationScope) -> str:
        """Start a new GW→M365 migration job. Returns the job ID."""
        job_id = str(uuid.uuid4())
        logger.info(
            "gw_job_started",
            extra={
                "job_id": job_id,
                "domain": scope.gw_domain,
                "workloads": [w.value for w in scope.workloads],
            },
        )
        pause_event = asyncio.Event()
        pause_event.set()  # not paused initially
        self._pause_events[job_id] = pause_event

        task = asyncio.create_task(
            self._run_job(job_id, scope, pause_event),
            name=f"gw-job-{job_id}",
        )
        self._active_jobs[job_id] = task
        return job_id

    async def pause(self, job_id: str) -> None:
        event = self._pause_events.get(job_id)
        if event:
            event.clear()
            logger.info("gw_job_paused", extra={"job_id": job_id})

    async def resume(self, job_id: str) -> None:
        event = self._pause_events.get(job_id)
        if event:
            event.set()
            logger.info("gw_job_resumed", extra={"job_id": job_id})

    async def cancel(self, job_id: str) -> None:
        task = self._active_jobs.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info("gw_job_cancelled", extra={"job_id": job_id})

    # ── Job execution ──────────────────────────────────────────────────────

    async def _run_job(
        self,
        job_id: str,
        scope: GWMigrationScope,
        pause_event: asyncio.Event,
    ) -> None:
        """Execute all migration waves in dependency order."""
        admin_user = next(iter(scope.user_mappings), None)
        if not admin_user:
            # Fall back to the first user in the domain (resolved via Admin SDK later)
            admin_user = f"admin@{scope.gw_domain}"

        for wave_idx, wave_workloads in enumerate(GW_WORKLOAD_WAVES):
            # Filter to only workloads requested in scope
            active = [w for w in wave_workloads if w in scope.workloads]
            if not active:
                continue

            logger.info(
                "gw_wave_started",
                extra={
                    "job_id": job_id,
                    "wave": wave_idx,
                    "workloads": [w.value for w in active],
                },
            )

            # Run the wave workloads in parallel
            wave_tasks = [
                self._run_workload(job_id, scope, workload, admin_user, pause_event)
                for workload in active
            ]
            await asyncio.gather(*wave_tasks, return_exceptions=True)

            logger.info(
                "gw_wave_completed",
                extra={"job_id": job_id, "wave": wave_idx},
            )

        logger.info("gw_job_completed", extra={"job_id": job_id})
        self._active_jobs.pop(job_id, None)
        self._pause_events.pop(job_id, None)

    async def _run_workload(
        self,
        job_id: str,
        scope: GWMigrationScope,
        workload: GWWorkloadType,
        admin_user: str,
        pause_event: asyncio.Event,
    ) -> None:
        """Discover items for a workload, then migrate each user's items."""
        migrator = _build_gw_migrator(
            workload=workload,
            gw_auth=self._gw_auth,
            m365_writer=self._writer,
            m365_auth=self._m365_auth,
            throttle=self._throttle,
            state=self._state,
            metrics=self._metrics,
            errors=self._errors,
            dlq=self._dlq,
            job_id=job_id,
        )

        # Determine user list
        if scope.user_mappings:
            users = list(scope.user_mappings.keys())
        else:
            # Discover all users via Admin SDK
            gw_users = await self._gw_auth.list_workspace_users(admin_email=admin_user)
            users = [u["primaryEmail"] for u in gw_users if u.get("primaryEmail")]

        for user in users:
            # Honour pause signal
            await pause_event.wait()

            items = await migrator.discover_items(scope, source_user=user)
            if not items:
                continue

            batch_size = self._settings.worker_concurrency
            for i in range(0, len(items), batch_size):
                await pause_event.wait()
                batch = items[i : i + batch_size]
                results = await migrator.migrate_batch(batch)

                ok = sum(1 for r in results if r.success)
                failed = sum(1 for r in results if not r.success)
                logger.info(
                    "gw_batch_done",
                    extra={
                        "job_id": job_id,
                        "workload": workload.value,
                        "ok": ok,
                        "failed": failed,
                    },
                )
