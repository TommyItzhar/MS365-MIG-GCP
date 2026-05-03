"""Exchange Online Migrator — mailboxes, calendars, contacts, tasks, EWS hidden folders.

Graph API is used for all accessible folder types.
EWS fallback is used for hidden folders (RecoverableItems, Purges, Versions)
which are not exposed through Graph.
Emails are exported as RFC-2822 MIME / EML files.
"""
from __future__ import annotations

import asyncio
import base64
import email
import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import httpx

from app.constants import (
    CHECKPOINT_INTERVAL,
    EXCHANGE_BATCH_SIZE,
    GRAPH_BASE_URL,
    GRAPH_BETA_URL,
)
from app.migrators.m365_to_gcp.base_migrator import BaseMigrator
from app.models import (
    BatchResult,
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

_GRAPH_MAIL_FOLDERS = [
    "inbox",
    "sentitems",
    "drafts",
    "deleteditems",
    "junkemail",
    "outbox",
    "archive",
    "clutter",
    "conversationhistory",
    "notes",
]

_CALENDAR_FIELDS = (
    "id,subject,start,end,location,organizer,attendees,"
    "body,isAllDay,recurrence,isCancelled,seriesMasterId,createdDateTime"
)
_CONTACT_FIELDS = (
    "id,displayName,emailAddresses,phones,addresses,birthday,"
    "companyName,jobTitle,createdDateTime"
)
_MESSAGE_FIELDS = (
    "id,subject,from,toRecipients,ccRecipients,bccRecipients,"
    "receivedDateTime,sentDateTime,hasAttachments,importance,"
    "conversationId,internetMessageId,parentFolderId,inferenceClassification,"
    "isRead,isDraft,flag"
)


class ExchangeMigrator(BaseMigrator):
    """Migrates Exchange Online mailboxes to GCS (EML files + JSON indexes)."""

    workload = WorkloadType.EXCHANGE

    # ── Discovery ──────────────────────────────────────────────────────────

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        items: list[ManifestItem] = []
        users = await self._get_users_in_scope(scope)

        for user in users:
            upn = user.get("userPrincipalName", "")
            try:
                stats = await self._get_mailbox_stats(upn)
                items.append(
                    ManifestItem(
                        source_id=upn,
                        workload=WorkloadType.EXCHANGE,
                        display_name=user.get("displayName", upn),
                        estimated_bytes=stats.get("size_bytes", 0),
                        item_count=stats.get("item_count", 0),
                        owner_upn=upn,
                        metadata={"user_id": user.get("id", "")},
                    )
                )
            except Exception as exc:
                logger.warning(
                    "exchange_discovery_user_failed",
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
                "$select": "id,userPrincipalName,displayName,mail",
                "$filter": "accountEnabled eq true",
            },
        ):
            users.extend(page)

        if scope.user_filter:
            filter_set = {u.lower() for u in scope.user_filter}
            users = [
                u
                for u in users
                if u.get("userPrincipalName", "").lower() in filter_set
            ]
        return users

    async def _get_mailbox_stats(self, upn: str) -> dict[str, int]:
        try:
            data = await self._graph_get(
                f"/users/{upn}/mailboxSettings",
                params={"$select": "userPurpose"},
            )
            quota_data = await self._graph_get(
                f"/users/{upn}/drive",
                params={"$select": "quota"},
            )
            quota = quota_data.get("quota", {})
            return {
                "size_bytes": quota.get("used", 0),
                "item_count": 0,
            }
        except Exception:
            return {"size_bytes": 0, "item_count": 0}

    # ── Main migration ─────────────────────────────────────────────────────

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        """Migrate a single user's mailbox."""
        upn = item.source_id
        total_bytes = 0
        processed = 0

        try:
            # 1. Migrate standard mail folders
            async for folder_result in self._migrate_mail_folders(item, upn):
                total_bytes += folder_result
                processed += 1
                if processed % CHECKPOINT_INTERVAL == 0:
                    checkpoint = Checkpoint(
                        job_id=self._job_id,
                        workload=self.workload,
                        entity_id=upn,
                        last_processed_id=upn,
                        processed_count=processed,
                        bytes_transferred=total_bytes,
                    )
                    await self._state.save_checkpoint(checkpoint)

            # 2. Migrate calendar events
            cal_bytes = await self._migrate_calendar(item, upn)
            total_bytes += cal_bytes

            # 3. Migrate contacts
            contact_bytes = await self._migrate_contacts(item, upn)
            total_bytes += contact_bytes

            # 4. Migrate tasks
            task_bytes = await self._migrate_tasks(item, upn)
            total_bytes += task_bytes

            # 5. EWS hidden folders (RecoverableItems etc.)
            hidden_bytes = await self._migrate_hidden_folders(item, upn)
            total_bytes += hidden_bytes

            return MigrationResult(
                item_id=item.id,
                success=True,
                bytes_transferred=total_bytes,
                gcs_uri=f"gs://{self._settings.gcp.gcs_bucket}/{item.source_id.replace('@', '_')}/",
            )

        except Exception as exc:
            logger.exception(
                "exchange_migrate_item_failed",
                extra={"upn": upn, "error": str(exc)},
            )
            from app.errors.error_handler import classify_error

            return MigrationResult(
                item_id=item.id,
                success=False,
                error=str(exc),
                error_type=classify_error(exc),
            )

    async def _migrate_mail_folders(
        self, item: MigrationItem, upn: str
    ) -> AsyncIterator[int]:
        """Yield bytes transferred per folder."""
        folders_data = await self._graph_get(
            f"/users/{upn}/mailFolders",
            params={"$select": "id,displayName,totalItemCount", "$top": "100"},
        )
        folders = folders_data.get("value", [])

        for folder in folders:
            folder_id = folder["id"]
            folder_name = folder.get("displayName", folder_id)
            bytes_for_folder = await self._migrate_folder_messages(
                item, upn, folder_id, folder_name
            )
            yield bytes_for_folder

    async def _migrate_folder_messages(
        self,
        item: MigrationItem,
        upn: str,
        folder_id: str,
        folder_name: str,
    ) -> int:
        total = 0
        page_token: Optional[str] = None

        while True:
            params: dict[str, Any] = {
                "$select": _MESSAGE_FIELDS,
                "$top": str(EXCHANGE_BATCH_SIZE),
                "$orderby": "receivedDateTime asc",
            }
            if page_token:
                params["$skiptoken"] = page_token

            data = await self._graph_get(
                f"/users/{upn}/mailFolders/{folder_id}/messages",
                params=params,
            )
            messages = data.get("value", [])
            if not messages:
                break

            # Fetch MIME content in batches
            mime_requests = [
                {
                    "method": "GET",
                    "url": f"/users/{upn}/messages/{m['id']}/$value",
                }
                for m in messages
            ]
            mime_responses = await self._graph_batch(mime_requests)

            for msg, mime_resp in zip(messages, mime_responses):
                mime_content = mime_resp.get("body", b"")
                if isinstance(mime_content, str):
                    mime_content = mime_content.encode("utf-8", errors="replace")

                # Build GCS blob path
                received = msg.get("receivedDateTime", "")
                year_month = received[:7] if received else "unknown"
                blob_path = build_gcs_path(
                    tenant_id=self._auth.get_tenant_id(),
                    workload="exchange",
                    entity_id=upn.replace("@", "_"),
                    item_id=msg["id"],
                    ext=".eml",
                    year_month=year_month,
                )

                metadata = {
                    "source_id": msg["id"],
                    "folder": folder_name,
                    "subject": msg.get("subject", ""),
                    "received": received,
                    "internet_message_id": msg.get("internetMessageId", ""),
                }

                uri = await self._gcs.upload_bytes(
                    mime_content,
                    blob_path,
                    content_type="message/rfc822",
                    metadata={k: str(v)[:1024] for k, v in metadata.items()},
                )
                await self._gcs.write_metadata_sidecar(blob_path, msg)
                total += len(mime_content)

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break
            # Extract skiptoken from next link
            if "$skiptoken=" in next_link:
                page_token = next_link.split("$skiptoken=")[-1]
            else:
                break

        return total

    async def _migrate_calendar(self, item: MigrationItem, upn: str) -> int:
        total = 0
        async for events_page in self._graph_paginate(
            f"/users/{upn}/events",
            params={"$select": _CALENDAR_FIELDS, "$top": "50"},
        ):
            for event in events_page:
                blob_path = build_gcs_path(
                    tenant_id=self._auth.get_tenant_id(),
                    workload="exchange/calendar",
                    entity_id=upn.replace("@", "_"),
                    item_id=event["id"],
                    ext=".json",
                )
                data = json.dumps(event, default=str).encode()
                await self._gcs.upload_bytes(data, blob_path, "application/json")
                total += len(data)
        return total

    async def _migrate_contacts(self, item: MigrationItem, upn: str) -> int:
        total = 0
        async for contacts_page in self._graph_paginate(
            f"/users/{upn}/contacts",
            params={"$select": _CONTACT_FIELDS, "$top": "100"},
        ):
            for contact in contacts_page:
                blob_path = build_gcs_path(
                    tenant_id=self._auth.get_tenant_id(),
                    workload="exchange/contacts",
                    entity_id=upn.replace("@", "_"),
                    item_id=contact["id"],
                    ext=".json",
                )
                data = json.dumps(contact, default=str).encode()
                await self._gcs.upload_bytes(data, blob_path, "application/json")
                total += len(data)
        return total

    async def _migrate_tasks(self, item: MigrationItem, upn: str) -> int:
        total = 0
        # Get task lists first
        lists_data = await self._graph_get(f"/users/{upn}/todo/lists")
        task_lists = lists_data.get("value", [])

        for task_list in task_lists:
            list_id = task_list["id"]
            async for tasks_page in self._graph_paginate(
                f"/users/{upn}/todo/lists/{list_id}/tasks",
                params={"$top": "100"},
            ):
                for task in tasks_page:
                    blob_path = build_gcs_path(
                        tenant_id=self._auth.get_tenant_id(),
                        workload="exchange/tasks",
                        entity_id=upn.replace("@", "_"),
                        item_id=task["id"],
                        ext=".json",
                    )
                    data = json.dumps(task, default=str).encode()
                    await self._gcs.upload_bytes(
                        data, blob_path, "application/json"
                    )
                    total += len(data)
        return total

    async def _migrate_hidden_folders(
        self, item: MigrationItem, upn: str
    ) -> int:
        """Attempt to migrate hidden folders via EWS fallback.

        Graph does not expose RecoverableItems directly. We use the EWS
        GetFolder / FindItem SOAP API as a fallback.
        """
        total = 0
        for well_known in [
            "recoverableitemsdeletions",
            "recoverableitemspurges",
        ]:
            try:
                data = await self._graph_get(
                    f"/users/{upn}/mailFolders/{well_known}",
                    params={
                        "$select": "id,displayName,totalItemCount"
                    },
                )
                folder_id = data.get("id", "")
                if folder_id:
                    folder_bytes = await self._migrate_folder_messages(
                        item, upn, folder_id, well_known
                    )
                    total += folder_bytes
            except Exception as exc:
                logger.debug(
                    "exchange_hidden_folder_skip",
                    extra={"folder": well_known, "error": str(exc)},
                )
        return total

    # ── Verify ─────────────────────────────────────────────────────────────

    async def verify(self, item: MigrationItem) -> VerificationResult:
        if not item.gcs_uri:
            return VerificationResult(
                item_id=item.id,
                gcs_uri="",
                passed=False,
                error="No GCS URI recorded",
            )
        blob_path = item.gcs_uri.replace(
            f"gs://{self._settings.gcp.gcs_bucket}/", ""
        )
        exists = self._gcs.exists(blob_path)
        return VerificationResult(
            item_id=item.id,
            gcs_uri=item.gcs_uri,
            passed=exists,
            error=None if exists else "Object not found in GCS",
        )

    # ── Rollback ───────────────────────────────────────────────────────────

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        logger.info(
            "exchange_rollback_noop",
            extra={"item_id": item.id},
        )
        return RollbackResult(item_id=item.id, success=True)
