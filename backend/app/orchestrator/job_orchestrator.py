"""Job Orchestrator — wave-based scheduling, dependency ordering, pause/resume/cancel.

Dependency execution order (enforced):
  Wave 0: identity (must complete before any other workload)
  Wave 1: exchange, onedrive, intune (parallel)
  Wave 2: sharepoint, groups (parallel)
  Wave 3: teams, teams_chat (parallel)
  Wave 4: power_automate, forms, planner (parallel)

Each wave waits for all workloads in the previous wave to complete.
Cloud Tasks queue integration is used for worker dispatch.
Global job state is tracked in Firestore.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from app.auth.auth_manager import AuthManager
from app.config.settings import get_settings
from app.discovery.discovery_engine import DiscoveryEngine, _build_migrator
from app.errors.error_handler import DLQPublisher, ErrorAggregator
from app.migrators.base_migrator import BaseMigrator
from app.models import (
    MigrationItem,
    MigrationJob,
    MigrationJobStatus,
    MigrationManifest,
    MigrationScope,
    WorkloadProgress,
    WorkloadType,
    ItemState,
)
from app.monitoring.monitoring import MetricsReporter
from app.state.state_manager import StateManager
from app.throttle.throttle_manager import ThrottleManager
from app.verification.verification_engine import VerificationEngine
from app.writers.gcs_writer import GCSWriter

logger = logging.getLogger(__name__)

# Dependency waves: each list runs in parallel; waves run sequentially
WORKLOAD_WAVES: list[list[WorkloadType]] = [
    [WorkloadType.IDENTITY],                                            # Wave 0 (prerequisite)
    [WorkloadType.EXCHANGE, WorkloadType.ONEDRIVE, WorkloadType.INTUNE], # Wave 1
    [WorkloadType.SHAREPOINT, WorkloadType.GROUPS],                     # Wave 2
    [WorkloadType.TEAMS, WorkloadType.TEAMS_CHAT],                      # Wave 3
    [WorkloadType.POWER_AUTOMATE, WorkloadType.FORMS, WorkloadType.PLANNER],  # Wave 4
]


class JobOrchestrator:
    """Orchestrates the full migration lifecycle for a job.

    Usage::

        orchestrator = JobOrchestrator(auth, throttle, state, gcs, metrics, errors, dlq)
        job_id = await orchestrator.start(scope)
        await orchestrator.pause(job_id)
        await orchestrator.resume(job_id)
        await orchestrator.cancel(job_id)
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
        self._active_jobs: dict[str, asyncio.Task] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._verifier = VerificationEngine(gcs=gcs, state=state)

    # ── Job lifecycle ──────────────────────────────────────────────────────

    async def start(self, scope: MigrationScope) -> str:
        """Start a new migration job. Returns the job ID."""
        job_id = str(uuid.uuid4())

        job = MigrationJob(
            id=job_id,
            tenant_id=scope.tenant_id,
            scope=scope,
            status=MigrationJobStatus.PENDING,
        )
        await self._state.create_job(job)

        self._pause_events[job_id] = asyncio.Event()
        self._pause_events[job_id].set()  # Not paused initially
        self._cancel_events[job_id] = asyncio.Event()

        task = asyncio.create_task(self._run_job(job_id, scope))
        self._active_jobs[job_id] = task

        logger.info("job_started", extra={"job_id": job_id, "tenant_id": scope.tenant_id})
        return job_id

    async def pause(self, job_id: str) -> None:
        """Pause a running job (workers finish current item then wait)."""
        event = self._pause_events.get(job_id)
        if event:
            event.clear()
            await self._state.update_job_status(job_id, MigrationJobStatus.PAUSED)
            logger.info("job_paused", extra={"job_id": job_id})

    async def resume(self, job_id: str) -> None:
        """Resume a paused job."""
        event = self._pause_events.get(job_id)
        if event:
            event.set()
            await self._state.update_job_status(job_id, MigrationJobStatus.RUNNING)
            logger.info("job_resumed", extra={"job_id": job_id})

    async def cancel(self, job_id: str) -> None:
        """Cancel a job (stops after current batch completes)."""
        cancel = self._cancel_events.get(job_id)
        if cancel:
            cancel.set()
        task = self._active_jobs.get(job_id)
        if task:
            task.cancel()
        await self._state.update_job_status(job_id, MigrationJobStatus.CANCELLED)
        logger.info("job_cancelled", extra={"job_id": job_id})

    # ── Internal execution ─────────────────────────────────────────────────

    async def _run_job(self, job_id: str, scope: MigrationScope) -> None:
        try:
            await self._state.update_job_status(job_id, MigrationJobStatus.RUNNING)

            # Phase 1: Discovery
            discovery = DiscoveryEngine(
                auth=self._auth,
                throttle=self._throttle,
                state=self._state,
                gcs=self._gcs,
                metrics=self._metrics,
                errors=self._errors,
                dlq=self._dlq,
            )
            manifest = await discovery.discover(scope, job_id)

            # Phase 2: Wave-based migration
            requested = set(scope.workloads)
            for wave_idx, wave in enumerate(WORKLOAD_WAVES):
                workloads_in_wave = [w for w in wave if w in requested]
                if not workloads_in_wave:
                    continue

                logger.info(
                    "wave_started",
                    extra={
                        "job_id": job_id,
                        "wave": wave_idx,
                        "workloads": [w.value for w in workloads_in_wave],
                    },
                )

                wave_tasks = [
                    self._run_workload(job_id, workload, manifest, scope)
                    for workload in workloads_in_wave
                ]
                await asyncio.gather(*wave_tasks, return_exceptions=True)

                logger.info("wave_completed", extra={"job_id": job_id, "wave": wave_idx})

            # Phase 3: Verification
            await self._run_verification(job_id, manifest)

            await self._state.update_job_status(job_id, MigrationJobStatus.COMPLETED)
            logger.info("job_completed", extra={"job_id": job_id})

        except asyncio.CancelledError:
            logger.info("job_cancelled_during_run", extra={"job_id": job_id})
        except Exception as exc:
            logger.exception("job_failed", extra={"job_id": job_id, "error": str(exc)})
            await self._state.update_job_status(
                job_id,
                MigrationJobStatus.FAILED,
                extra={"error_message": str(exc)},
            )

    async def _run_workload(
        self,
        job_id: str,
        workload: WorkloadType,
        manifest: MigrationManifest,
        scope: MigrationScope,
    ) -> None:
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

        workload_items = [i for i in manifest.items if i.workload == workload]
        if not workload_items:
            logger.info(
                "workload_no_items",
                extra={"job_id": job_id, "workload": workload.value},
            )
            return

        progress = WorkloadProgress(
            workload=workload,
            total_items=len(workload_items),
            status=MigrationJobStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        await self._state.update_workload_progress(job_id, workload, progress)

        start_time = time.monotonic()
        completed = 0
        failed = 0
        bytes_transferred = 0

        concurrency = self._settings.worker_concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def _process_item(manifest_item) -> None:
            nonlocal completed, failed, bytes_transferred

            # Check pause / cancel
            pause = self._pause_events.get(job_id)
            if pause:
                await pause.wait()
            cancel = self._cancel_events.get(job_id)
            if cancel and cancel.is_set():
                return

            # Create MigrationItem in Firestore
            import uuid as _uuid
            migration_item = MigrationItem(
                id=str(_uuid.uuid4()),
                job_id=job_id,
                workload=workload,
                source_id=manifest_item.source_id,
                source_path=manifest_item.url or manifest_item.source_id,
                tenant_id=manifest.tenant_id,
                estimated_bytes=manifest_item.estimated_bytes,
                metadata=manifest_item.metadata,
            )
            await self._state.upsert_item(migration_item)

            async with semaphore:
                result = await migrator._safe_migrate(migration_item)  # type: ignore[union-attr]

            if result.success:
                completed += 1
                bytes_transferred += result.bytes_transferred
            else:
                failed += 1

            # Update workload progress snapshot
            elapsed = time.monotonic() - start_time
            throughput = completed / elapsed if elapsed > 0 else 0
            remaining = (len(workload_items) - completed - failed)
            etc = remaining / throughput if throughput > 0 else None

            current_progress = WorkloadProgress(
                workload=workload,
                total_items=len(workload_items),
                completed_items=completed,
                failed_items=failed,
                bytes_transferred=bytes_transferred,
                status=MigrationJobStatus.RUNNING,
                started_at=progress.started_at,
                throughput_items_per_second=round(throughput, 3),
                estimated_completion_seconds=etc,
            )
            await self._state.update_workload_progress(job_id, workload, current_progress)

            if etc is not None:
                self._metrics.record_etc(etc)
            self._metrics.record_throughput(throughput)

        await asyncio.gather(
            *[_process_item(mi) for mi in workload_items],
            return_exceptions=True,
        )

        final_progress = WorkloadProgress(
            workload=workload,
            total_items=len(workload_items),
            completed_items=completed,
            failed_items=failed,
            bytes_transferred=bytes_transferred,
            status=(
                MigrationJobStatus.COMPLETED
                if failed == 0
                else MigrationJobStatus.FAILED
            ),
            started_at=progress.started_at,
            completed_at=datetime.utcnow(),
        )
        await self._state.update_workload_progress(job_id, workload, final_progress)
        await migrator.close()  # type: ignore[union-attr]

    async def _run_verification(
        self, job_id: str, manifest: MigrationManifest
    ) -> None:
        logger.info("verification_started", extra={"job_id": job_id})
        results = await self._verifier.verify_job(job_id, manifest)
        failed = [r for r in results if not r.passed]
        logger.info(
            "verification_completed",
            extra={
                "job_id": job_id,
                "total": len(results),
                "passed": len(results) - len(failed),
                "failed": len(failed),
            },
        )
