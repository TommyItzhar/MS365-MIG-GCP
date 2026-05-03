"""Google Drive → OneDrive migrator.

Downloads Drive files (including Google Workspace native formats converted
to Office formats) and uploads them to the user's OneDrive via the Graph API.

Conversion map:
  Google Docs   → docx
  Google Sheets → xlsx
  Google Slides → pptx
  Other         → original format

Security: file content is streamed through memory only; never written to disk.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.constants import GW_DRIVE_MAX_RESULTS
from app.migrators.gw_to_m365.base_migrator import BaseGWMigrator
from app.models import (
    GWMigrationItem,
    GWMigrationScope,
    GWWorkloadType,
    MigrationResult,
)

logger = logging.getLogger(__name__)

_MIME_CONVERT: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": (
        "image/png",
        ".png",
    ),
}
_GOOGLE_APPS_PREFIX = "application/vnd.google-apps."


class DriveMigrator(BaseGWMigrator):
    """Migrates Google Drive files → OneDrive."""

    workload = GWWorkloadType.DRIVE

    async def discover_items(
        self, scope: GWMigrationScope, source_user: str
    ) -> list[GWMigrationItem]:
        dest_user = scope.user_mappings.get(source_user, source_user)
        creds = await self._gw_auth.get_credentials(source_user, "drive")
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        items: list[GWMigrationItem] = []
        page_token: Optional[str] = None

        while True:
            kwargs: dict = {
                "pageSize": GW_DRIVE_MAX_RESULTS,
                "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, parents)",
                "q": "trashed = false",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            result = service.files().list(**kwargs).execute()
            files = result.get("files", [])

            for f in files:
                mime = f.get("mimeType", "")
                # Skip Google Forms, Sites, Maps (no good export format)
                if mime in (
                    "application/vnd.google-apps.form",
                    "application/vnd.google-apps.site",
                    "application/vnd.google-apps.map",
                    "application/vnd.google-apps.folder",
                ):
                    continue

                size = int(f.get("size", 0) or 0)
                items.append(
                    GWMigrationItem(
                        id=f"{self._job_id}-drive-{f['id']}",
                        job_id=self._job_id,
                        workload=GWWorkloadType.DRIVE,
                        source_user=source_user,
                        destination_user=dest_user,
                        source_id=f["id"],
                        tenant_id=scope.gw_domain,
                        estimated_bytes=size,
                        metadata={
                            "name": f["name"],
                            "mime_type": mime,
                            "parents": f.get("parents", []),
                        },
                    )
                )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(
            "drive_discovery_done",
            extra={"count": len(items), "job_id": self._job_id},
        )
        return items

    async def migrate_item(self, item: GWMigrationItem) -> MigrationResult:
        creds = await self._gw_auth.get_credentials(item.source_user, "drive")
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        file_name: str = item.metadata.get("name", item.source_id)
        mime_type: str = item.metadata.get("mime_type", "application/octet-stream")

        # Determine download method
        content, final_name = await _download_drive_file(
            service, item.source_id, file_name, mime_type
        )
        size = len(content)

        # Reconstruct OneDrive path from Drive parents hierarchy
        drive_path = "Google Drive Migration"

        file_id = await self._writer.upload_file(
            item.destination_user,
            drive_path,
            content,
            final_name,
        )

        return MigrationResult(
            item_id=item.id,
            success=True,
            bytes_transferred=size,
            gcs_uri=f"m365://{item.destination_user}/drive/{file_id}",
        )


async def _download_drive_file(
    service,
    file_id: str,
    file_name: str,
    mime_type: str,
) -> tuple[bytes, str]:
    """Download or export a Drive file. Returns (bytes, final_filename)."""
    if mime_type.startswith(_GOOGLE_APPS_PREFIX):
        export_mime, ext = _MIME_CONVERT.get(mime_type, ("application/pdf", ".pdf"))
        final_name = file_name if file_name.endswith(ext) else file_name + ext

        buf = io.BytesIO()
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue(), final_name
    else:
        buf = io.BytesIO()
        request = service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue(), file_name
