"""Identity Migrator — Entra ID users, groups, roles, app registrations.

Produces a canonical identity manifest to GCS that maps M365 users to
their post-migration GCP equivalents. This must run FIRST before any
other workload migrator (dependency order enforced by orchestrator).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from app.migrators.base_migrator import BaseMigrator
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

_USER_FIELDS = (
    "id,userPrincipalName,displayName,givenName,surname,mail,"
    "accountEnabled,usageLocation,department,jobTitle,companyName,"
    "mobilePhone,assignedLicenses,mfaMethods,createdDateTime,lastSignInDateTime"
)
_GROUP_FIELDS = (
    "id,displayName,description,groupTypes,securityEnabled,"
    "mailEnabled,mail,createdDateTime"
)
_ROLE_FIELDS = "id,displayName,description,roleTemplateId,isEnabled"
_APP_FIELDS = (
    "id,appId,displayName,signInAudience,createdDateTime,"
    "requiredResourceAccess,tags,publisherDomain"
)


class IdentityMigrator(BaseMigrator):
    """Migrates Entra ID identity objects to GCS as a structured manifest."""

    workload = WorkloadType.IDENTITY

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        return MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=self._job_id,
            discovery_timestamp=datetime.utcnow(),
            items=[
                ManifestItem(
                    source_id=scope.tenant_id,
                    workload=WorkloadType.IDENTITY,
                    display_name="Entra ID Tenant",
                    metadata={"tenant_id": scope.tenant_id},
                )
            ],
            total_items=1,
        )

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        tenant_id = item.source_id
        total_bytes = 0

        try:
            # 1. Export all users
            users: list[dict] = []
            async for page in self._graph_paginate(
                "/users",
                params={"$select": _USER_FIELDS, "$top": "999"},
            ):
                users.extend(page)

            # 2. Export all security and M365 groups
            groups: list[dict] = []
            async for page in self._graph_paginate(
                "/groups",
                params={"$select": _GROUP_FIELDS, "$top": "999"},
            ):
                groups.extend(page)

            # 3. Directory roles and assignments
            roles_data = await self._graph_get(
                "/directoryRoles",
                params={"$select": _ROLE_FIELDS},
            )
            roles = roles_data.get("value", [])

            # 4. App registrations
            apps: list[dict] = []
            async for page in self._graph_paginate(
                "/applications",
                params={"$select": _APP_FIELDS, "$top": "999"},
            ):
                apps.extend(page)

            # 5. Service principals
            sps: list[dict] = []
            async for page in self._graph_paginate(
                "/servicePrincipals",
                params={"$select": "id,appId,displayName,servicePrincipalType", "$top": "999"},
            ):
                sps.extend(page)

            # 6. Licensing
            sku_data = await self._graph_get(
                "/subscribedSkus",
                params={"$select": "skuId,skuPartNumber,consumedUnits,prepaidUnits"},
            )

            identity_manifest = {
                "tenant_id": tenant_id,
                "exported_at": datetime.utcnow().isoformat(),
                "users": users,
                "groups": groups,
                "directory_roles": roles,
                "app_registrations": apps,
                "service_principals": sps,
                "license_skus": sku_data.get("value", []),
            }

            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="identity",
                entity_id=tenant_id,
                item_id="identity_manifest",
                ext=".json",
            )
            data = json.dumps(identity_manifest, default=str).encode()
            uri = await self._gcs.upload_bytes(data, blob_path, "application/json", overwrite=True)
            total_bytes = len(data)

            # Write individual user records for cross-workload lookups
            user_index: list[dict] = []
            for user in users:
                upn = user.get("userPrincipalName", "")
                user_index.append({
                    "id": user.get("id"),
                    "upn": upn,
                    "display_name": user.get("displayName"),
                    "mail": user.get("mail"),
                    "enabled": user.get("accountEnabled", False),
                })

            index_blob = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="identity",
                entity_id=tenant_id,
                item_id="user_index",
                ext=".json",
            )
            index_data = json.dumps(user_index, default=str).encode()
            await self._gcs.upload_bytes(index_data, index_blob, "application/json", overwrite=True)
            total_bytes += len(index_data)

            return MigrationResult(
                item_id=item.id,
                success=True,
                bytes_transferred=total_bytes,
                gcs_uri=uri,
            )

        except Exception as exc:
            logger.exception("identity_migrate_item_failed", extra={"tenant_id": tenant_id})
            from app.errors.error_handler import classify_error
            return MigrationResult(item_id=item.id, success=False, error=str(exc), error_type=classify_error(exc))

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri))

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
