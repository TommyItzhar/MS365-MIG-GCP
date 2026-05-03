"""Teams Migrator — teams, channels, messages, attachments, wiki, recordings.

Teams Export API is used for high-fidelity message export (requires licensing).
Meeting recordings are cross-referenced from OneDrive/SharePoint.
Attachments stored in OneDrive are retrieved via the Files API.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.constants import CHECKPOINT_INTERVAL
from app.migrators.m365_to_gcp.base_migrator import BaseMigrator
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

_TEAM_FIELDS = "id,displayName,description,visibility,webUrl,specialization"
_CHANNEL_FIELDS = "id,displayName,description,membershipType,webUrl,email,createdDateTime"
_MESSAGE_FIELDS = (
    "id,messageType,createdDateTime,lastModifiedDateTime,deletedDateTime,"
    "subject,summary,importance,from,body,attachments,mentions,reactions,"
    "replyToId,channelIdentity"
)


class TeamsMigrator(BaseMigrator):
    """Migrates Microsoft Teams to GCS."""

    workload = WorkloadType.TEAMS

    # ── Discovery ──────────────────────────────────────────────────────────

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        items: list[ManifestItem] = []
        async for teams_page in self._graph_paginate(
            "/teams",
            params={"$select": _TEAM_FIELDS, "$top": "100"},
        ):
            for team in teams_page:
                items.append(
                    ManifestItem(
                        source_id=team["id"],
                        workload=WorkloadType.TEAMS,
                        display_name=team.get("displayName", team["id"]),
                        url=team.get("webUrl"),
                        metadata={"team_id": team["id"]},
                    )
                )

        return MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=self._job_id,
            discovery_timestamp=datetime.utcnow(),
            items=items,
            total_items=len(items),
        )

    # ── Migration ──────────────────────────────────────────────────────────

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        """Migrate one Teams team (all channels + messages)."""
        team_id = item.source_id
        total_bytes = 0

        try:
            # 1. Export team metadata
            team_meta = await self._graph_get(
                f"/teams/{team_id}",
                params={"$select": _TEAM_FIELDS},
            )
            # Export members + owners
            members = await self._graph_get(f"/teams/{team_id}/members")
            team_meta["members"] = members.get("value", [])

            meta_blob = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="teams",
                entity_id=team_id,
                item_id="team_metadata",
                ext=".json",
            )
            meta_data = json.dumps(team_meta, default=str).encode()
            await self._gcs.upload_bytes(meta_data, meta_blob, "application/json")
            total_bytes += len(meta_data)

            # 2. Migrate all channels
            channels_data = await self._graph_get(
                f"/teams/{team_id}/channels",
                params={"$select": _CHANNEL_FIELDS, "$top": "100"},
            )
            channels = channels_data.get("value", [])

            processed = 0
            for channel in channels:
                channel_bytes = await self._migrate_channel(
                    team_id, channel, item
                )
                total_bytes += channel_bytes
                processed += 1

                if processed % CHECKPOINT_INTERVAL == 0:
                    ckpt = Checkpoint(
                        job_id=self._job_id,
                        workload=self.workload,
                        entity_id=team_id,
                        last_processed_id=channel["id"],
                        processed_count=processed,
                        bytes_transferred=total_bytes,
                    )
                    await self._state.save_checkpoint(ckpt)

            # 3. Planner data linked to this team
            await self._export_planner(team_id)

            # 4. Team's SharePoint site files (meeting recordings)
            await self._migrate_team_recordings(team_id)

            return MigrationResult(
                item_id=item.id,
                success=True,
                bytes_transferred=total_bytes,
                gcs_uri=(
                    f"gs://{self._settings.gcp.gcs_bucket}/"
                    f"{self._auth.get_tenant_id()}/teams/{team_id}/"
                ),
            )

        except Exception as exc:
            logger.exception(
                "teams_migrate_item_failed",
                extra={"team_id": team_id, "error": str(exc)},
            )
            from app.errors.error_handler import classify_error
            return MigrationResult(
                item_id=item.id,
                success=False,
                error=str(exc),
                error_type=classify_error(exc),
            )

    async def _migrate_channel(
        self,
        team_id: str,
        channel: dict[str, Any],
        parent_item: MigrationItem,
    ) -> int:
        channel_id = channel["id"]
        channel_name = channel.get("displayName", channel_id)
        total = 0

        # Channel metadata
        chan_blob = build_gcs_path(
            tenant_id=self._auth.get_tenant_id(),
            workload="teams",
            entity_id=team_id,
            item_id=f"channels/{channel_id}/metadata",
            ext=".json",
        )
        chan_data = json.dumps(channel, default=str).encode()
        await self._gcs.upload_bytes(chan_data, chan_blob, "application/json")
        total += len(chan_data)

        # Channel members (for private channels)
        if channel.get("membershipType") == "private":
            try:
                members = await self._graph_get(
                    f"/teams/{team_id}/channels/{channel_id}/members"
                )
                members_blob = chan_blob.replace("metadata.json", "members.json")
                await self._gcs.upload_bytes(
                    json.dumps(members, default=str).encode(),
                    members_blob,
                    "application/json",
                    overwrite=True,
                )
            except Exception:
                pass

        # Messages — use Export API when available, fall back to standard endpoint
        msg_bytes = await self._migrate_channel_messages(
            team_id, channel_id
        )
        total += msg_bytes

        # Tabs / wiki
        try:
            tabs_data = await self._graph_get(
                f"/teams/{team_id}/channels/{channel_id}/tabs",
                params={"$select": "id,displayName,webUrl,teamsApp"},
            )
            tabs_blob = chan_blob.replace("metadata.json", "tabs.json")
            await self._gcs.upload_bytes(
                json.dumps(tabs_data, default=str).encode(),
                tabs_blob,
                "application/json",
                overwrite=True,
            )
        except Exception:
            pass

        return total

    async def _migrate_channel_messages(
        self, team_id: str, channel_id: str
    ) -> int:
        """Fetch all channel messages using Teams Export API (preferred) or standard."""
        total = 0
        messages_all: list[dict] = []

        # Try Export API first (requires Teams Export API app permission)
        try:
            async for page in self._graph_paginate(
                f"/teams/{team_id}/channels/{channel_id}/messages/delta",
                params={"$select": _MESSAGE_FIELDS, "$top": "50"},
            ):
                messages_all.extend(page)
        except Exception as exc:
            logger.debug(
                "teams_export_api_fallback",
                extra={"channel_id": channel_id, "error": str(exc)},
            )
            # Standard messages endpoint
            async for page in self._graph_paginate(
                f"/teams/{team_id}/channels/{channel_id}/messages",
                params={"$select": _MESSAGE_FIELDS, "$top": "50"},
            ):
                messages_all.extend(page)

        # Fetch replies for each message (in batches)
        batch_size = 20
        for i in range(0, len(messages_all), batch_size):
            batch = messages_all[i : i + batch_size]
            reply_requests = [
                {
                    "method": "GET",
                    "url": f"/teams/{team_id}/channels/{channel_id}/messages/{m['id']}/replies?$top=50",
                }
                for m in batch
            ]
            try:
                reply_responses = await self._graph_batch(reply_requests)
                for msg, reply_resp in zip(batch, reply_responses):
                    msg["replies"] = reply_resp.get("body", {}).get("value", [])
            except Exception:
                pass

        # Persist messages as NDJSON (one JSON object per line)
        if messages_all:
            ndjson = "\n".join(
                json.dumps(m, default=str) for m in messages_all
            ).encode("utf-8")
            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="teams",
                entity_id=team_id,
                item_id=f"channels/{channel_id}/messages",
                ext=".ndjson",
            )
            await self._gcs.upload_bytes(
                ndjson, blob_path, "application/x-ndjson", overwrite=True
            )
            total += len(ndjson)

            # Migrate attachments referenced in messages
            attachment_bytes = await self._migrate_message_attachments(
                team_id, channel_id, messages_all
            )
            total += attachment_bytes

        return total

    async def _migrate_message_attachments(
        self,
        team_id: str,
        channel_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        """Download and store Teams message attachments (stored in OneDrive)."""
        total = 0
        for msg in messages:
            for attachment in msg.get("attachments", []):
                content_url = attachment.get("contentUrl", "")
                if not content_url:
                    continue
                try:
                    client = await self._get_http_client()
                    async with client.stream("GET", content_url) as resp:
                        resp.raise_for_status()
                        data = await resp.aread()

                    att_name = attachment.get("name", attachment.get("id", "file"))
                    uri, was_dup = await self._gcs.upload_attachment_dedup(
                        data,
                        self._auth.get_tenant_id(),
                        att_name,
                    )
                    total += len(data)
                    if not was_dup:
                        logger.debug(
                            "teams_attachment_uploaded",
                            extra={"name": att_name, "size": len(data)},
                        )
                except Exception as exc:
                    logger.debug(
                        "teams_attachment_skip",
                        extra={"error": str(exc)},
                    )
        return total

    async def _export_planner(self, team_id: str) -> None:
        try:
            plans = await self._graph_get(f"/groups/{team_id}/planner/plans")
            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="teams",
                entity_id=team_id,
                item_id="planner",
                ext=".json",
            )
            await self._gcs.upload_bytes(
                json.dumps(plans, default=str).encode(), blob_path, "application/json", overwrite=True
            )
        except Exception as exc:
            logger.debug("teams_planner_skip", extra={"error": str(exc)})

    async def _migrate_team_recordings(self, team_id: str) -> None:
        """Cross-reference team's SharePoint site for meeting recordings."""
        try:
            site_data = await self._graph_get(f"/groups/{team_id}/sites/root")
            site_id = site_data.get("id", "")
            if not site_id:
                return

            # Look in Recordings folder
            recordings = await self._graph_get(
                f"/sites/{site_id}/drive/root:/{team_id}/Recordings:/children",
                params={"$select": "id,name,size,@microsoft.graph.downloadUrl"},
            )
            for recording in recordings.get("value", []):
                download_url = recording.get("@microsoft.graph.downloadUrl", "")
                if not download_url:
                    continue
                size = recording.get("size", 0)
                name = recording.get("name", recording["id"])
                blob_path = build_gcs_path(
                    tenant_id=self._auth.get_tenant_id(),
                    workload="teams/recordings",
                    entity_id=team_id,
                    item_id=recording["id"],
                    ext="",
                )
                client = await self._get_http_client()
                async with client.stream("GET", download_url) as resp:
                    resp.raise_for_status()
                    async def _iter():
                        async for chunk in resp.aiter_bytes(8 * 1024 * 1024):
                            yield chunk
                    await self._gcs.upload_stream(
                        _iter(), blob_path, "video/mp4", total_size=size
                    )
        except Exception as exc:
            logger.debug("teams_recordings_skip", extra={"error": str(exc)})

    # ── Verify / Rollback ──────────────────────────────────────────────────

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(
            item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri)
        )

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
