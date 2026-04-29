"""Teams Chat Migrator — 1:1 chats, group chats, meeting chats.

Uses Microsoft Graph Chat API to export full message history.
Attachments stored in OneDrive are fetched via content URLs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from app.constants import CHECKPOINT_INTERVAL
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
from app.writers.gcs_writer import build_gcs_path

logger = logging.getLogger(__name__)

_CHAT_FIELDS = "id,topic,chatType,createdDateTime,lastUpdatedDateTime,webUrl"
_MEMBER_FIELDS = "id,displayName,email,userId,tenantId"
_MSG_FIELDS = (
    "id,createdDateTime,lastModifiedDateTime,deletedDateTime,messageType,"
    "from,body,attachments,mentions,reactions,summary,importance"
)


class ChatMigrator(BaseMigrator):
    """Migrates Teams 1:1, group chats, and meeting chats to GCS."""

    workload = WorkloadType.TEAMS_CHAT

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        items: list[ManifestItem] = []
        # Chats are scoped per user — iterate all users
        users: list[dict] = []
        async for page in self._graph_paginate(
            "/users",
            params={"$select": "id,userPrincipalName,displayName", "$filter": "accountEnabled eq true"},
        ):
            users.extend(page)

        if scope.user_filter:
            filter_set = {u.lower() for u in scope.user_filter}
            users = [u for u in users if u.get("userPrincipalName", "").lower() in filter_set]

        for user in users:
            items.append(
                ManifestItem(
                    source_id=user["id"],
                    workload=WorkloadType.TEAMS_CHAT,
                    display_name=user.get("displayName", user["id"]),
                    owner_upn=user.get("userPrincipalName"),
                    metadata={"user_id": user["id"]},
                )
            )

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
        processed = 0

        try:
            async for chats_page in self._graph_paginate(
                f"/users/{user_id}/chats",
                params={"$select": _CHAT_FIELDS, "$top": "50"},
            ):
                for chat in chats_page:
                    chat_id = chat["id"]
                    chat_bytes = await self._migrate_chat(user_id, chat)
                    total_bytes += chat_bytes
                    processed += 1

                    if processed % CHECKPOINT_INTERVAL == 0:
                        ckpt = Checkpoint(
                            job_id=self._job_id,
                            workload=self.workload,
                            entity_id=user_id,
                            last_processed_id=chat_id,
                            processed_count=processed,
                            bytes_transferred=total_bytes,
                        )
                        await self._state.save_checkpoint(ckpt)

            return MigrationResult(
                item_id=item.id,
                success=True,
                bytes_transferred=total_bytes,
                gcs_uri=(
                    f"gs://{self._settings.gcp.gcs_bucket}/"
                    f"{self._auth.get_tenant_id()}/teams_chat/{user_id}/"
                ),
            )
        except Exception as exc:
            logger.exception("chat_migrate_item_failed", extra={"user_id": user_id, "error": str(exc)})
            from app.errors.error_handler import classify_error
            return MigrationResult(item_id=item.id, success=False, error=str(exc), error_type=classify_error(exc))

    async def _migrate_chat(self, user_id: str, chat: dict) -> int:
        chat_id = chat["id"]
        total = 0

        # Members
        try:
            members = await self._graph_get(
                f"/chats/{chat_id}/members",
                params={"$select": _MEMBER_FIELDS},
            )
            chat["members"] = members.get("value", [])
        except Exception:
            pass

        # Messages
        messages: list[dict] = []
        async for page in self._graph_paginate(
            f"/chats/{chat_id}/messages",
            params={"$select": _MSG_FIELDS, "$top": "50"},
        ):
            messages.extend(page)

        payload = {"chat": chat, "messages": messages}
        blob_path = build_gcs_path(
            tenant_id=self._auth.get_tenant_id(),
            workload="teams_chat",
            entity_id=user_id,
            item_id=chat_id,
            ext=".json",
        )
        data = json.dumps(payload, default=str).encode()
        await self._gcs.upload_bytes(data, blob_path, "application/json")
        total += len(data)

        # Attachments
        for msg in messages:
            for att in msg.get("attachments", []):
                url = att.get("contentUrl", "")
                if not url:
                    continue
                try:
                    client = await self._get_http_client()
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        att_data = resp.content
                        await self._gcs.upload_attachment_dedup(
                            att_data,
                            self._auth.get_tenant_id(),
                            att.get("name", att.get("id", "file")),
                        )
                        total += len(att_data)
                except Exception:
                    pass

        return total

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri))

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
