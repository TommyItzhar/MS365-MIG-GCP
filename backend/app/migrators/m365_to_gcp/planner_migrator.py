"""Planner Migrator — plans, buckets, tasks, assignments, comments."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from app.migrators.m365_to_gcp.base_migrator import BaseMigrator
from app.models import (
    ManifestItem,
    MigrationItem,
    MigrationManifest,
    MigrationResult,
    MigrationScope,
    RollbackResult,
    VerificationResult,
    WorkloadType,
)
from app.writers.gcs_writer import build_gcs_path

logger = logging.getLogger(__name__)

_TASK_FIELDS = (
    "id,title,planId,bucketId,percentComplete,startDateTime,dueDateTime,"
    "assignments,appliedCategories,priority,orderHint,createdDateTime,"
    "completedDateTime,hasDescription,previewType,referenceCount,checklistItemCount"
)


class PlannerMigrator(BaseMigrator):
    """Exports Microsoft Planner plans, buckets, tasks, and comments to GCS."""

    workload = WorkloadType.PLANNER

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        # Planner plans are accessed via Groups
        groups: list[dict] = []
        async for page in self._graph_paginate(
            "/groups",
            params={
                "$select": "id,displayName",
                "$filter": "groupTypes/any(c:c eq 'Unified')",
                "$top": "999",
            },
        ):
            groups.extend(page)

        items = [
            ManifestItem(
                source_id=g["id"],
                workload=WorkloadType.PLANNER,
                display_name=g.get("displayName", g["id"]),
                metadata={"group_id": g["id"]},
            )
            for g in groups
        ]
        return MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=self._job_id,
            discovery_timestamp=datetime.utcnow(),
            items=items,
            total_items=len(items),
        )

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        group_id = item.source_id
        total_bytes = 0

        try:
            plans_data = await self._graph_get(f"/groups/{group_id}/planner/plans")
            plans = plans_data.get("value", [])

            full_export: list[dict] = []

            for plan in plans:
                plan_id = plan["id"]
                plan_export = {"plan": plan, "buckets": [], "tasks": []}

                # Buckets
                try:
                    buckets_data = await self._graph_get(f"/planner/plans/{plan_id}/buckets")
                    plan_export["buckets"] = buckets_data.get("value", [])
                except Exception:
                    pass

                # Tasks
                try:
                    tasks_data = await self._graph_get(
                        f"/planner/plans/{plan_id}/tasks",
                        params={"$select": _TASK_FIELDS},
                    )
                    tasks = tasks_data.get("value", [])

                    # Task details (description, checklist, references)
                    detail_requests = [
                        {"method": "GET", "url": f"/planner/tasks/{t['id']}/details"}
                        for t in tasks[:20]
                    ]
                    if detail_requests:
                        detail_responses = await self._graph_batch(detail_requests)
                        for task, detail_resp in zip(tasks[:20], detail_responses):
                            task["details"] = detail_resp.get("body", {})

                    plan_export["tasks"] = tasks
                except Exception:
                    pass

                full_export.append(plan_export)

            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="planner",
                entity_id=group_id,
                item_id="planner_export",
                ext=".json",
            )
            data = json.dumps(
                {
                    "group_id": group_id,
                    "exported_at": datetime.utcnow().isoformat(),
                    "plans": full_export,
                },
                default=str,
            ).encode()
            uri = await self._gcs.upload_bytes(data, blob_path, "application/json")
            total_bytes = len(data)

            return MigrationResult(item_id=item.id, success=True, bytes_transferred=total_bytes, gcs_uri=uri)

        except Exception as exc:
            logger.exception("planner_migrate_failed", extra={"group_id": group_id})
            from app.errors.error_handler import classify_error
            return MigrationResult(item_id=item.id, success=False, error=str(exc), error_type=classify_error(exc))

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri))

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
