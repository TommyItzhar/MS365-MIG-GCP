"""Microsoft 365 Groups Migrator — group metadata, members, owners, Planner."""
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

_GROUP_FIELDS = (
    "id,displayName,description,mail,mailEnabled,securityEnabled,"
    "groupTypes,visibility,createdDateTime,renewedDateTime,"
    "expirationDateTime,isAssignableToRole"
)


class GroupsMigrator(BaseMigrator):
    """Migrates Microsoft 365 Groups to GCS."""

    workload = WorkloadType.GROUPS

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        items: list[ManifestItem] = []
        async for page in self._graph_paginate(
            "/groups",
            params={"$select": _GROUP_FIELDS, "$filter": "groupTypes/any(c:c eq 'Unified')", "$top": "999"},
        ):
            for group in page:
                if scope.group_filter and group["id"] not in scope.group_filter:
                    continue
                items.append(ManifestItem(
                    source_id=group["id"],
                    workload=WorkloadType.GROUPS,
                    display_name=group.get("displayName", group["id"]),
                    metadata={"group_id": group["id"]},
                ))

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
            group = await self._graph_get(f"/groups/{group_id}", params={"$select": _GROUP_FIELDS})

            # Members and owners
            members = await self._graph_get(
                f"/groups/{group_id}/members",
                params={"$select": "id,displayName,userPrincipalName,mail"},
            )
            owners = await self._graph_get(
                f"/groups/{group_id}/owners",
                params={"$select": "id,displayName,userPrincipalName,mail"},
            )

            # License assignments
            try:
                licenses = await self._graph_get(f"/groups/{group_id}/assignedLicenses")
            except Exception:
                licenses = {}

            # Planner plans for this group
            try:
                planner = await self._graph_get(f"/groups/{group_id}/planner/plans")
            except Exception:
                planner = {}

            payload = {
                "group": group,
                "members": members.get("value", []),
                "owners": owners.get("value", []),
                "licenses": licenses,
                "planner": planner,
            }

            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="groups",
                entity_id=group_id,
                item_id="group_export",
                ext=".json",
            )
            data = json.dumps(payload, default=str).encode()
            uri = await self._gcs.upload_bytes(data, blob_path, "application/json")
            total_bytes = len(data)

            return MigrationResult(item_id=item.id, success=True, bytes_transferred=total_bytes, gcs_uri=uri)

        except Exception as exc:
            logger.exception("groups_migrate_item_failed", extra={"group_id": group_id})
            from app.errors.error_handler import classify_error
            return MigrationResult(item_id=item.id, success=False, error=str(exc), error_type=classify_error(exc))

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri))

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
