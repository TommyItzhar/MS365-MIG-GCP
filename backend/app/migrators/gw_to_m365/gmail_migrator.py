"""Gmail → Exchange Online migrator.

Reads emails via the Gmail API (MIME format) and imports them into
the user's Exchange Online mailbox via the Microsoft Graph API.

Security: raw message bytes are never logged. User email only at DEBUG.
Rate limits: Gmail allows 250 quota units/user/second; we batch reads.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from googleapiclient.discovery import build

from app.constants import GW_GMAIL_MAX_RESULTS
from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    MigrationResult,
    ItemState,
)

logger = logging.getLogger(__name__)


class GmailMigrator(BaseGWMigrator):
    """Migrates Gmail messages → Exchange Online mailbox."""

    workload = GWWorkloadType.GMAIL

    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        """Enumerate all Gmail message IDs for this user."""
        dest_user = scope.user_mappings.get(source_user, source_user)
        creds = await self._gw_auth.get_credentials(source_user, "gmail")
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        items: list[GWMigrationItem] = []
        page_token: Optional[str] = None
        query_parts: list[str] = []

        if scope.start_date:
            query_parts.append(f"after:{int(scope.start_date.timestamp())}")
        if scope.end_date:
            query_parts.append(f"before:{int(scope.end_date.timestamp())}")

        query = " ".join(query_parts) if query_parts else None

        while True:
            kwargs: dict = {"userId": "me", "maxResults": GW_GMAIL_MAX_RESULTS}
            if page_token:
                kwargs["pageToken"] = page_token
            if query:
                kwargs["q"] = query

            result = service.users().messages().list(**kwargs).execute()
            messages = result.get("messages", [])

            for msg in messages:
                items.append(
                    GWMigrationItem(
                        id=f"{self._job_id}-gmail-{msg['id']}",
                        job_id=self._job_id,
                        workload=GWWorkloadType.GMAIL,
                        source_user=source_user,
                        destination_user=dest_user,
                        source_id=msg["id"],
                        tenant_id=scope.gw_domain,
                    )
                )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(
            "gmail_discovery_done",
            extra={"count": len(items), "job_id": self._job_id},
        )
        return items

    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        """Fetch a Gmail message as MIME and import into Exchange Online."""
        creds = await self._gw_auth.get_credentials(item.source_user, "gmail")
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        # Fetch the raw MIME message
        raw_msg = (
            service.users()
            .messages()
            .get(userId="me", id=item.source_id, format="raw")
            .execute()
        )
        import base64 as _b64
        mime_bytes = _b64.urlsafe_b64decode(raw_msg["raw"] + "==")
        size = len(mime_bytes)

        # Determine if the message was read
        labels = raw_msg.get("labelIds", [])
        is_read = "UNREAD" not in labels

        # Map Gmail labels → Exchange folder
        folder_name = _gmail_labels_to_folder(labels)
        folder_id = await self._writer.get_or_create_mail_folder(
            item.destination_user, folder_name
        )

        # Import into Exchange
        msg_id = await self._writer.import_mail_message(
            item.destination_user, mime_bytes, folder_id, is_read=is_read
        )

        return MigrationResult(
            item_id=item.id,
            success=True,
            bytes_transferred=size,
            gcs_uri=f"m365://{item.destination_user}/messages/{msg_id}",
        )


def _gmail_labels_to_folder(labels: list[str]) -> str:
    """Map Gmail system labels to Exchange folder names."""
    if "SENT" in labels:
        return "Sent Items"
    if "DRAFT" in labels:
        return "Drafts"
    if "TRASH" in labels:
        return "Deleted Items"
    if "SPAM" in labels:
        return "Junk Email"
    if "STARRED" in labels:
        return "Starred"
    return "Inbox"
