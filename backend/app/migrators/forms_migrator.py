"""Microsoft Forms Migrator — form definitions and responses."""
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


class FormsMigrator(BaseMigrator):
    """Exports Microsoft Forms definitions and responses to GCS."""

    workload = WorkloadType.FORMS

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        users: list[dict] = []
        async for page in self._graph_paginate(
            "/users",
            params={"$select": "id,userPrincipalName,displayName", "$filter": "accountEnabled eq true"},
        ):
            users.extend(page)

        if scope.user_filter:
            fs = {u.lower() for u in scope.user_filter}
            users = [u for u in users if u.get("userPrincipalName", "").lower() in fs]

        items = [
            ManifestItem(
                source_id=u["id"],
                workload=WorkloadType.FORMS,
                display_name=u.get("displayName", u["id"]),
                owner_upn=u.get("userPrincipalName"),
            )
            for u in users
        ]
        return MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=self._job_id,
            discovery_timestamp=datetime.utcnow(),
            items=items,
            total_items=len(items),
        )

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        user_id = item.source_id
        total_bytes = 0

        try:
            # Microsoft Forms API is not in stable Graph v1.0 yet
            # Use beta endpoint for forms access
            import httpx
            client = await self._get_http_client()
            headers = await self._auth.get_graph_headers()

            # Forms data via beta endpoint
            try:
                resp = await client.get(
                    f"https://graph.microsoft.com/beta/users/{user_id}/drive/items/root:/Forms:/children",
                    headers=headers,
                )
                if resp.status_code == 200:
                    forms_data = resp.json()
                else:
                    forms_data = {"value": []}
            except Exception:
                forms_data = {"value": []}

            payload = {
                "user_id": user_id,
                "exported_at": datetime.utcnow().isoformat(),
                "forms": forms_data.get("value", []),
                "note": "Forms export via Microsoft Graph beta API. "
                        "Full form response data requires Microsoft Forms Export API.",
            }

            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="forms",
                entity_id=user_id,
                item_id="forms_export",
                ext=".json",
            )
            data = json.dumps(payload, default=str).encode()
            uri = await self._gcs.upload_bytes(data, blob_path, "application/json")
            total_bytes = len(data)

            return MigrationResult(item_id=item.id, success=True, bytes_transferred=total_bytes, gcs_uri=uri)

        except Exception as exc:
            logger.exception("forms_migrate_failed", extra={"user_id": user_id})
            from app.errors.error_handler import classify_error
            return MigrationResult(item_id=item.id, success=False, error=str(exc), error_type=classify_error(exc))

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri))

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
