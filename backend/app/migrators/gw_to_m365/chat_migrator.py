"""Google Chat → Microsoft Teams migrator.

Migrates Google Chat spaces and their messages to Microsoft Teams channels.
Each Chat space becomes a Teams channel in a designated migration team.

Limitations:
- Google Chat API allows read access to spaces the service account is a member of
- Message threading is approximated (no 1:1 reply thread mapping in Graph)
- Direct messages (DMs) are skipped — Teams DMs require per-user license
"""
from __future__ import annotations

import logging
from typing import Optional

from googleapiclient.discovery import build

from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    MigrationResult,
)

logger = logging.getLogger(__name__)

_MIGRATION_TEAM_NAME = "Google Chat Migration"


class ChatMigrator(BaseGWMigrator):
    """Migrates Google Chat spaces → Microsoft Teams channels."""

    workload = GWWorkloadType.CHAT

    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        dest_user = scope.user_mappings.get(source_user, source_user)
        creds = await self._gw_auth.get_credentials(source_user, "chat")
        service = build("chat", "v1", credentials=creds, cache_discovery=False)

        items: list[GWMigrationItem] = []
        page_token: Optional[str] = None

        while True:
            kwargs: dict = {"pageSize": 100}
            if page_token:
                kwargs["pageToken"] = page_token

            result = service.spaces().list(**kwargs).execute()
            spaces = result.get("spaces", [])

            for space in spaces:
                space_type = space.get("spaceType", space.get("type", ""))
                if space_type in ("DIRECT_MESSAGE", "DM"):
                    continue

                items.append(
                    GWMigrationItem(
                        id=f"{self._job_id}-chat-{space['name'].replace('/', '_')}",
                        job_id=self._job_id,
                        workload=GWWorkloadType.CHAT,
                        source_user=source_user,
                        destination_user=dest_user,
                        source_id=space["name"],
                        tenant_id=scope.gw_domain,
                        metadata={
                            "display_name": space.get("displayName", space["name"]),
                        },
                    )
                )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(
            "chat_discovery_done",
            extra={"count": len(items), "job_id": self._job_id},
        )
        return items

    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        """Migrate a Chat space: create Teams channel, import recent messages."""
        creds = await self._gw_auth.get_credentials(item.source_user, "chat")
        service = build("chat", "v1", credentials=creds, cache_discovery=False)

        space_name = item.source_id
        channel_name = item.metadata.get("display_name", space_name)

        # Get or create the migration team
        team_id = await self._writer.get_or_create_team(
            display_name=_MIGRATION_TEAM_NAME,
            description="Migrated from Google Chat",
            owner_upn=item.destination_user,
        )

        # Get messages from the space
        messages: list[dict] = []
        page_token: Optional[str] = None
        while True:
            kwargs: dict = {"parent": space_name, "pageSize": 250}
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.spaces().messages().list(**kwargs).execute()
            messages.extend(result.get("messages", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        # Get or create Teams channel
        channel_data = await self._writer._request(
            "POST",
            f"/teams/{team_id}/channels",
            json={
                "displayName": channel_name[:50],
                "description": f"Migrated from Google Chat space: {space_name}",
                "membershipType": "standard",
            },
            expected_status=201,
        )
        channel_id = channel_data.get("id", "")

        # Post messages into the channel
        message_count = 0
        for msg in messages:
            sender = msg.get("sender", {}).get("displayName", "Unknown")
            text = msg.get("text", "")
            if not text:
                continue
            await self._writer.post_channel_message(
                team_id,
                channel_id,
                {
                    "body": {
                        "contentType": "html",
                        "content": f"<b>[{sender}]</b> {text}",
                    }
                },
            )
            message_count += 1

        logger.info(
            "chat_space_migrated",
            extra={"messages": message_count, "job_id": self._job_id},
        )
        return MigrationResult(
            item_id=item.id,
            success=True,
            bytes_transferred=0,
            gcs_uri=f"m365://teams/{team_id}/channels/{channel_id}",
        )
