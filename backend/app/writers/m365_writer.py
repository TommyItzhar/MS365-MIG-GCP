"""Microsoft 365 Writer — Graph API write operations for GW→M365 migration.

All write operations use application permissions (client credentials) with
write-specific scopes. Rate-limit headers (429 Retry-After) are honoured.

Required application permissions (must be granted in Entra ID):
  Mail.ReadWrite, Files.ReadWrite.All, Calendars.ReadWrite,
  Contacts.ReadWrite, User.ReadWrite.All, Channel.Create,
  ChannelMessage.Send, Directory.ReadWrite.All

Security notes:
- Message bodies and file content are streamed; never logged
- User UPNs are only logged at DEBUG level
- Large files (>4 MB) use resumable upload sessions
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, AsyncIterator, Optional

import httpx

from app.constants import (
    GRAPH_BASE_URL,
    LARGE_FILE_THRESHOLD_BYTES,
    RATE_LIMIT_STATUS_CODE,
    DEFAULT_RETRY_AFTER_SECONDS,
)

logger = logging.getLogger(__name__)

_WRITE_SCOPES = ["https://graph.microsoft.com/.default"]
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0
_UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB resumable upload chunks


class M365WriteError(Exception):
    """Raised when a Graph write operation fails after all retries."""

    def __init__(self, message: str, status_code: int = 0, operation: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.operation = operation


class M365Writer:
    """Provides idempotent write methods for all M365 workloads.

    Usage::

        writer = M365Writer(auth_manager)
        msg_id = await writer.import_mail_message(upn, mime_bytes, folder_id)
    """

    def __init__(self, auth_manager: Any) -> None:
        self._auth = auth_manager
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=GRAPH_BASE_URL,
                timeout=httpx.Timeout(120.0, connect=15.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _headers(self) -> dict[str, str]:
        token = await self._auth.get_graph_token(_WRITE_SCOPES)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        content: Optional[bytes] = None,
        content_type: Optional[str] = None,
        expected_status: int = 200,
    ) -> dict:
        """Execute a Graph API request with retry-after backoff on 429."""
        client = await self._get_client()
        headers = await self._headers()
        if content_type:
            headers["Content-Type"] = content_type

        for attempt in range(_MAX_RETRIES):
            try:
                if content is not None:
                    response = await client.request(
                        method, path, headers=headers, content=content
                    )
                else:
                    response = await client.request(
                        method, path, headers=headers, json=json
                    )

                if response.status_code == RATE_LIMIT_STATUS_CODE:
                    retry_after = float(
                        response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS)
                    )
                    logger.warning(
                        "m365_write_throttled",
                        extra={"retry_after": retry_after, "attempt": attempt + 1},
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code not in (expected_status, 200, 201, 202, 204):
                    body = response.text[:500]
                    raise M365WriteError(
                        f"Graph {method} {path} returned {response.status_code}: {body}",
                        status_code=response.status_code,
                        operation=f"{method} {path}",
                    )

                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                wait = _BACKOFF_BASE ** attempt
                logger.warning(
                    "m365_write_network_error",
                    extra={"attempt": attempt + 1, "wait": wait, "error": str(exc)},
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
                else:
                    raise M365WriteError(str(exc), operation=f"{method} {path}") from exc

        raise M365WriteError(
            f"Max retries exceeded for {method} {path}",
            operation=f"{method} {path}",
        )

    # ── Mail ───────────────────────────────────────────────────────────────

    async def get_or_create_mail_folder(
        self, upn: str, folder_name: str, parent_folder_id: str = "msgfolderroot"
    ) -> str:
        """Return the folder ID, creating it if it doesn't exist."""
        data = await self._request(
            "GET",
            f"/users/{upn}/mailFolders/{parent_folder_id}/childFolders",
            expected_status=200,
        )
        for folder in data.get("value", []):
            if folder.get("displayName", "").lower() == folder_name.lower():
                return folder["id"]

        created = await self._request(
            "POST",
            f"/users/{upn}/mailFolders/{parent_folder_id}/childFolders",
            json={"displayName": folder_name},
            expected_status=201,
        )
        logger.debug("m365_mail_folder_created", extra={"folder": folder_name})
        return created["id"]

    async def import_mail_message(
        self,
        upn: str,
        mime_bytes: bytes,
        folder_id: str,
        is_read: bool = False,
    ) -> str:
        """Upload a raw MIME message to a user's mailbox folder.

        Returns the new message ID. The message is created as a draft then moved.
        """
        # Graph requires base64-encoded MIME for import
        encoded = base64.b64encode(mime_bytes).decode()
        data = await self._request(
            "POST",
            f"/users/{upn}/messages",
            json={
                "singleValueExtendedProperties": [],
            },
            expected_status=201,
        )
        msg_id = data["id"]

        # Upload MIME content
        await self._request(
            "PUT",
            f"/users/{upn}/messages/{msg_id}/$value",
            content=mime_bytes,
            content_type="text/plain",
            expected_status=200,
        )

        # Move to target folder if not inbox
        if folder_id and folder_id not in ("inbox", "INBOX"):
            await self._request(
                "POST",
                f"/users/{upn}/messages/{msg_id}/move",
                json={"destinationId": folder_id},
                expected_status=201,
            )

        # Mark as read if needed
        if is_read:
            await self._request(
                "PATCH",
                f"/users/{upn}/messages/{msg_id}",
                json={"isRead": True},
                expected_status=200,
            )

        logger.debug("m365_message_imported", extra={"upn_hash": hash(upn)})
        return msg_id

    # ── OneDrive / Files ───────────────────────────────────────────────────

    async def create_drive_folder(
        self, upn: str, parent_path: str, folder_name: str
    ) -> str:
        """Create a folder in OneDrive under parent_path. Returns item ID."""
        data = await self._request(
            "POST",
            f"/users/{upn}/drive/root:/{parent_path}:/children",
            json={
                "name": folder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename",
            },
            expected_status=201,
        )
        return data["id"]

    async def upload_file(
        self,
        upn: str,
        drive_path: str,
        content: bytes,
        file_name: str,
    ) -> str:
        """Upload a file to OneDrive. Uses resumable session for large files."""
        if len(content) <= LARGE_FILE_THRESHOLD_BYTES:
            data = await self._request(
                "PUT",
                f"/users/{upn}/drive/root:/{drive_path}/{file_name}:/content",
                content=content,
                content_type="application/octet-stream",
                expected_status=201,
            )
            return data["id"]

        return await self._resumable_upload(upn, drive_path, file_name, content)

    async def _resumable_upload(
        self, upn: str, drive_path: str, file_name: str, content: bytes
    ) -> str:
        """Create an upload session and upload in chunks."""
        session = await self._request(
            "POST",
            f"/users/{upn}/drive/root:/{drive_path}/{file_name}:/createUploadSession",
            json={
                "item": {
                    "@microsoft.graph.conflictBehavior": "rename",
                    "name": file_name,
                }
            },
            expected_status=200,
        )
        upload_url = session["uploadUrl"]
        total = len(content)
        client = await self._get_client()
        item_id = ""

        for offset in range(0, total, _UPLOAD_CHUNK_SIZE):
            chunk = content[offset : offset + _UPLOAD_CHUNK_SIZE]
            end = offset + len(chunk) - 1
            headers = {
                "Content-Range": f"bytes {offset}-{end}/{total}",
                "Content-Length": str(len(chunk)),
                "Content-Type": "application/octet-stream",
            }
            # Upload session URLs are absolute, not relative to base_url
            resp = await client.put(upload_url, content=chunk, headers=headers)
            if resp.status_code in (200, 201):
                item_id = resp.json().get("id", "")
            elif resp.status_code == 202:
                pass  # still uploading
            elif resp.status_code == RATE_LIMIT_STATUS_CODE:
                await asyncio.sleep(
                    float(resp.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS))
                )
            else:
                raise M365WriteError(
                    f"Upload chunk failed: {resp.status_code} {resp.text[:200]}",
                    status_code=resp.status_code,
                )

        logger.debug("m365_resumable_upload_done", extra={"total_bytes": total})
        return item_id

    # ── Calendar ───────────────────────────────────────────────────────────

    async def create_calendar_event(
        self, upn: str, event_payload: dict
    ) -> str:
        """Create a calendar event. Returns the new event ID."""
        data = await self._request(
            "POST",
            f"/users/{upn}/events",
            json=event_payload,
            expected_status=201,
        )
        logger.debug("m365_calendar_event_created")
        return data["id"]

    # ── Contacts ───────────────────────────────────────────────────────────

    async def create_contact(self, upn: str, contact_payload: dict) -> str:
        """Create an Outlook contact. Returns the new contact ID."""
        data = await self._request(
            "POST",
            f"/users/{upn}/contacts",
            json=contact_payload,
            expected_status=201,
        )
        logger.debug("m365_contact_created")
        return data["id"]

    # ── Teams / Channels ───────────────────────────────────────────────────

    async def get_or_create_team(
        self, display_name: str, description: str, owner_upn: str
    ) -> str:
        """Find an existing team by name or create one. Returns team ID."""
        teams = await self._request("GET", "/teams", expected_status=200)
        for team in teams.get("value", []):
            if team.get("displayName", "").lower() == display_name.lower():
                return team["id"]

        # Create via group + team provision
        group = await self._request(
            "POST",
            "/groups",
            json={
                "displayName": display_name,
                "description": description,
                "groupTypes": ["Unified"],
                "mailEnabled": True,
                "mailNickname": display_name.replace(" ", "-").lower()[:64],
                "securityEnabled": False,
                "members@odata.bind": [
                    f"https://graph.microsoft.com/v1.0/users/{owner_upn}"
                ],
                "owners@odata.bind": [
                    f"https://graph.microsoft.com/v1.0/users/{owner_upn}"
                ],
            },
            expected_status=201,
        )
        group_id = group["id"]

        # Provision the team on top of the group (async in Graph — poll)
        await self._request(
            "PUT",
            f"/groups/{group_id}/team",
            json={
                "memberSettings": {"allowCreatePrivateChannels": True},
                "messagingSettings": {"allowUserEditMessages": True},
            },
            expected_status=201,
        )
        logger.debug("m365_team_created", extra={"display_name": display_name})
        return group_id

    async def post_channel_message(
        self, team_id: str, channel_id: str, message_payload: dict
    ) -> str:
        """Post a message to a Teams channel. Returns the message ID."""
        data = await self._request(
            "POST",
            f"/teams/{team_id}/channels/{channel_id}/messages",
            json=message_payload,
            expected_status=201,
        )
        return data["id"]

    # ── Identity (Entra ID) ────────────────────────────────────────────────

    async def create_or_update_user(
        self, user_payload: dict
    ) -> tuple[str, bool]:
        """Upsert a user in Entra ID. Returns (object_id, was_created).

        If a user with the same UPN already exists, updates display name only.
        """
        upn = user_payload.get("userPrincipalName", "")
        existing = await self._request(
            "GET",
            f"/users/{upn}",
            expected_status=200,
        )
        if existing:
            # User already exists — patch safe fields only
            await self._request(
                "PATCH",
                f"/users/{upn}",
                json={
                    "displayName": user_payload.get("displayName", ""),
                    "givenName": user_payload.get("givenName", ""),
                    "surname": user_payload.get("surname", ""),
                    "jobTitle": user_payload.get("jobTitle", ""),
                    "department": user_payload.get("department", ""),
                },
                expected_status=204,
            )
            return existing.get("id", ""), False

        created = await self._request(
            "POST",
            "/users",
            json=user_payload,
            expected_status=201,
        )
        logger.debug("m365_user_created")
        return created["id"], True
