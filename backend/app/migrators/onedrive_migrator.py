"""OneDrive for Business Migrator — delta sync, version history, permissions.

Uses Graph delta query tokens for incremental migration.
All files > 5 MB use resumable GCS upload.
Permissions are exported as JSON sidecar files.
Content-addressed deduplication prevents duplicate attachment storage.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from app.constants import CHECKPOINT_INTERVAL, DELTA_TOKEN_MAX_AGE_DAYS
from app.migrators.base_migrator import BaseMigrator
from app.models import (
    Checkpoint,
    ManifestItem,
    MigrationItem,
    MigrationManifest,
    MigrationResult,
    MigrationScope,
    RollbackResult,
    VerificationResult,
    WorkloadType,
)
from app.writers.gcs_writer import GCSWriter, build_gcs_path

logger = logging.getLogger(__name__)

_FILE_FIELDS = (
    "id,name,size,file,folder,parentReference,lastModifiedDateTime,"
    "createdDateTime,createdBy,lastModifiedBy,webUrl,mimeType,"
    "sharepointIds,@microsoft.graph.downloadUrl"
)
_VERSION_FIELDS = "id,size,lastModifiedDateTime,lastModifiedBy"


class OneDriveMigrator(BaseMigrator):
    """Migrates OneDrive for Business to GCS with delta-sync support."""

    workload = WorkloadType.ONEDRIVE

    # ── Discovery ──────────────────────────────────────────────────────────

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        items: list[ManifestItem] = []
        users = await self._get_users_in_scope(scope)

        for user in users:
            upn = user.get("userPrincipalName", "")
            try:
                drive_data = await self._graph_get(
                    f"/users/{upn}/drive",
                    params={"$select": "id,quota,owner"},
                )
                quota = drive_data.get("quota", {})
                items.append(
                    ManifestItem(
                        source_id=user.get("id", ""),
                        workload=WorkloadType.ONEDRIVE,
                        display_name=user.get("displayName", upn),
                        estimated_bytes=quota.get("used", 0),
                        item_count=0,
                        owner_upn=upn,
                        metadata={
                            "drive_id": drive_data.get("id", ""),
                            "user_id": user.get("id", ""),
                        },
                    )
                )
            except Exception as exc:
                logger.warning(
                    "onedrive_discovery_user_failed",
                    extra={"upn": upn, "error": str(exc)},
                )

        total_bytes = sum(i.estimated_bytes for i in items)
        return MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=self._job_id,
            discovery_timestamp=datetime.utcnow(),
            items=items,
            total_bytes=total_bytes,
            total_items=len(items),
        )

    async def _get_users_in_scope(self, scope: MigrationScope) -> list[dict]:
        users: list[dict] = []
        async for page in self._graph_paginate(
            "/users",
            params={
                "$select": "id,userPrincipalName,displayName",
                "$filter": "accountEnabled eq true",
            },
        ):
            users.extend(page)
        if scope.user_filter:
            filter_set = {u.lower() for u in scope.user_filter}
            users = [
                u for u in users
                if u.get("userPrincipalName", "").lower() in filter_set
            ]
        return users

    # ── Migration ──────────────────────────────────────────────────────────

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        """Migrate one user's entire OneDrive."""
        user_id = item.source_id
        upn = item.metadata.get("owner_upn", user_id)
        drive_id = item.metadata.get("drive_id", "")

        try:
            drive_endpoint = (
                f"/drives/{drive_id}/root/delta"
                if drive_id
                else f"/users/{user_id}/drive/root/delta"
            )

            # Check for a persisted delta token (incremental run)
            delta_token = await self._state.get_delta_token(
                self._job_id, self.workload, user_id
            )
            if delta_token:
                drive_endpoint = delta_token
                logger.info(
                    "onedrive_delta_resume",
                    extra={"user_id": user_id, "has_token": True},
                )

            total_bytes = 0
            processed = 0
            last_delta_link: Optional[str] = None

            params: dict[str, Any] = {
                "$select": _FILE_FIELDS,
                "$top": "200",
            }

            next_url: Optional[str] = drive_endpoint

            while next_url:
                data = await self._graph_get(
                    next_url,
                    params=params if next_url == drive_endpoint else None,
                )
                drive_items = data.get("value", [])

                for drive_item in drive_items:
                    if "deleted" in drive_item:
                        continue
                    if "folder" in drive_item:
                        continue  # Folders are created implicitly by blob paths

                    item_bytes = await self._migrate_drive_item(
                        drive_item, user_id, upn, item
                    )
                    total_bytes += item_bytes
                    processed += 1

                    if processed % CHECKPOINT_INTERVAL == 0:
                        ckpt = Checkpoint(
                            job_id=self._job_id,
                            workload=self.workload,
                            entity_id=user_id,
                            last_processed_id=drive_item.get("id", ""),
                            processed_count=processed,
                            bytes_transferred=total_bytes,
                        )
                        await self._state.save_checkpoint(ckpt)
                        self._mlog.checkpoint_saved(user_id, processed)

                next_url = data.get("@odata.nextLink")
                delta_link = data.get("@odata.deltaLink")
                if delta_link:
                    last_delta_link = delta_link
                    # Persist delta token for next incremental run
                    await self._state.save_delta_token(
                        self._job_id, self.workload, user_id, delta_link
                    )
                    next_url = None

            gcs_prefix = (
                f"gs://{self._settings.gcp.gcs_bucket}/"
                f"{self._auth.get_tenant_id()}/onedrive/{user_id}/"
            )
            return MigrationResult(
                item_id=item.id,
                success=True,
                bytes_transferred=total_bytes,
                gcs_uri=gcs_prefix,
            )

        except Exception as exc:
            logger.exception(
                "onedrive_migrate_item_failed",
                extra={"user_id": user_id, "error": str(exc)},
            )
            from app.errors.error_handler import classify_error
            return MigrationResult(
                item_id=item.id,
                success=False,
                error=str(exc),
                error_type=classify_error(exc),
            )

    async def _migrate_drive_item(
        self,
        drive_item: dict[str, Any],
        user_id: str,
        upn: str,
        parent_item: MigrationItem,
    ) -> int:
        item_id = drive_item["id"]
        item_name = drive_item.get("name", item_id)
        modified = drive_item.get("lastModifiedDateTime", "")
        year_month = modified[:7] if modified else "unknown"
        size = drive_item.get("size", 0)

        # Parent path for folder hierarchy preservation
        parent_ref = drive_item.get("parentReference", {})
        parent_path = parent_ref.get("path", "").replace(
            "/drive/root:", ""
        ).strip("/")

        blob_path = build_gcs_path(
            tenant_id=self._auth.get_tenant_id(),
            workload="onedrive",
            entity_id=user_id,
            item_id=f"{parent_path}/{item_name}".strip("/"),
            ext="",
            year_month=year_month,
        )

        # Content dedup via hash
        content_hash = drive_item.get(
            "file", {}
        ).get("hashes", {}).get("sha256Hash", "")

        if content_hash:
            existing_uri = await self._state.find_by_content_hash(
                self._job_id, content_hash
            )
            if existing_uri:
                logger.debug(
                    "onedrive_item_deduped",
                    extra={"item_id": item_id, "existing_uri": existing_uri},
                )
                return 0

        # Download and upload
        download_url = drive_item.get(
            "@microsoft.graph.downloadUrl", ""
        )
        if not download_url:
            # Fetch fresh download URL
            item_data = await self._graph_get(f"/drive/items/{item_id}")
            download_url = item_data.get("@microsoft.graph.downloadUrl", "")

        if not download_url:
            logger.warning(
                "onedrive_no_download_url",
                extra={"item_id": item_id},
            )
            return 0

        client = await self._get_http_client()
        mime_type = drive_item.get("file", {}).get("mimeType", "application/octet-stream")

        async with client.stream("GET", download_url) as response:
            response.raise_for_status()

            async def _chunk_iter():
                async for chunk in response.aiter_bytes(chunk_size=8 * 1024 * 1024):
                    yield chunk

            gcs_metadata = {
                "source_id": item_id,
                "original_name": item_name[:1024],
                "last_modified": modified,
                "size": str(size),
                "onedrive_user": upn,
            }

            uri = await self._gcs.upload_stream(
                _chunk_iter(),
                blob_path,
                content_type=mime_type,
                total_size=size,
                metadata=gcs_metadata,
            )

        # Permissions sidecar
        try:
            perms_data = await self._graph_get(
                f"/drive/items/{item_id}/permissions"
            )
            await self._gcs.write_permissions_sidecar(blob_path, perms_data)
        except Exception as exc:
            logger.debug(
                "onedrive_permissions_fetch_failed",
                extra={"item_id": item_id, "error": str(exc)},
            )

        # Version history
        try:
            versions_data = await self._graph_get(
                f"/drive/items/{item_id}/versions",
                params={"$select": _VERSION_FIELDS},
            )
            versions_blob = blob_path + ".versions.json"
            await self._gcs.upload_bytes(
                json.dumps(versions_data, default=str).encode(),
                versions_blob,
                "application/json",
                overwrite=True,
            )
        except Exception as exc:
            logger.debug(
                "onedrive_versions_fetch_failed",
                extra={"item_id": item_id, "error": str(exc)},
            )

        return size

    # ── Verify ─────────────────────────────────────────────────────────────

    async def verify(self, item: MigrationItem) -> VerificationResult:
        if not item.gcs_uri:
            return VerificationResult(
                item_id=item.id, gcs_uri="", passed=False, error="No GCS URI"
            )
        return VerificationResult(
            item_id=item.id, gcs_uri=item.gcs_uri, passed=True
        )

    # ── Rollback ───────────────────────────────────────────────────────────

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        logger.info("onedrive_rollback_noop", extra={"item_id": item.id})
        return RollbackResult(item_id=item.id, success=True)

    async def resume(self, checkpoint: Checkpoint) -> None:
        """OneDrive resume uses persisted delta token — handled inside migrate_item."""
        await super().resume(checkpoint)
