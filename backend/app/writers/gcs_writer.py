"""GCS Writer — streaming, resumable, and parallel composite uploads.

Design decisions:
- Files ≤ 5 MB: single-shot upload
- Files > 5 MB: resumable upload with 8 MB chunks
- All uploads: CRC32c integrity verification
- Blob names: sanitised + truncated to 1,024 bytes
- if-generation-match: 0 prevents accidental overwrites (idempotency)
- Content-addressed deduplication for attachments
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import unicodedata
from datetime import datetime
from typing import AsyncIterator, Optional

from google.cloud import storage
from google.cloud.storage import retry as gcs_retry

from app.constants import (
    DEFAULT_CHUNK_SIZE_BYTES,
    GCS_MAX_OBJECT_NAME_BYTES,
    GCS_METADATA_SUFFIX,
    GCS_PATH_TEMPLATE,
    GCS_PERMISSIONS_SUFFIX,
    RESUMABLE_UPLOAD_THRESHOLD,
)
from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_ILLEGAL_GCS_RE = re.compile(r"[^\w\s\-./]")


def _sanitise_path_segment(segment: str) -> str:
    """Normalise and sanitise a path segment for GCS object names."""
    segment = unicodedata.normalize("NFC", segment)
    segment = segment.replace("\\", "/")
    segment = re.sub(r"[#\[\]*?'\"<>|]", "_", segment)
    segment = segment.strip("/. ")
    return segment or "_"


def _truncate_object_name(name: str) -> str:
    """Truncate an object name to the GCS 1,024-byte limit."""
    encoded = name.encode("utf-8")
    if len(encoded) <= GCS_MAX_OBJECT_NAME_BYTES:
        return name
    return encoded[: GCS_MAX_OBJECT_NAME_BYTES].decode("utf-8", errors="ignore")


def build_gcs_path(
    tenant_id: str,
    workload: str,
    entity_id: str,
    item_id: str,
    ext: str = "",
    year_month: Optional[str] = None,
) -> str:
    """Build the canonical GCS object path for a migration item."""
    if year_month is None:
        year_month = datetime.utcnow().strftime("%Y-%m")

    path = GCS_PATH_TEMPLATE.format(
        tenant_id=_sanitise_path_segment(tenant_id),
        workload=_sanitise_path_segment(workload),
        entity_id=_sanitise_path_segment(entity_id),
        year_month=year_month,
        item_id=_sanitise_path_segment(item_id),
        ext=ext,
    )
    return _truncate_object_name(path)


class GCSWriter:
    """Writes migration artefacts to Google Cloud Storage.

    Usage::

        writer = GCSWriter()

        # Upload bytes in memory
        uri = await writer.upload_bytes(data, blob_path, content_type)

        # Stream upload from an async iterator
        uri = await writer.upload_stream(stream_iter, blob_path, content_type, size)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._bucket_name = self._settings.gcp.gcs_bucket
        self._client: Optional[storage.Client] = None

    def _get_client(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client(
                project=self._settings.gcp.project_id
            )
        return self._client

    def _get_bucket(self) -> storage.Bucket:
        return self._get_client().bucket(self._bucket_name)

    # ── Single-shot upload ─────────────────────────────────────────────────

    async def upload_bytes(
        self,
        data: bytes,
        blob_path: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
        overwrite: bool = False,
    ) -> str:
        """Upload bytes to GCS. Returns gs:// URI."""
        bucket = self._get_bucket()
        blob = bucket.blob(blob_path)

        if metadata:
            blob.metadata = metadata

        upload_kwargs: dict = {
            "data": data,
            "content_type": content_type,
            "checksum": "crc32c",
            "retry": gcs_retry.DEFAULT_RETRY,
        }
        if not overwrite:
            upload_kwargs["if_generation_match"] = 0

        try:
            blob.upload_from_string(**upload_kwargs)
        except Exception as exc:
            if "conditionNotMet" in str(exc) or "412" in str(exc):
                logger.debug(
                    "gcs_object_already_exists_skipped",
                    extra={"blob_path": blob_path},
                )
                return f"gs://{self._bucket_name}/{blob_path}"
            raise

        uri = f"gs://{self._bucket_name}/{blob_path}"
        logger.debug(
            "gcs_upload_complete",
            extra={
                "blob_path": blob_path,
                "size_bytes": len(data),
                "uri": uri,
            },
        )
        return uri

    # ── Resumable upload for large files ───────────────────────────────────

    async def upload_stream(
        self,
        stream: AsyncIterator[bytes],
        blob_path: str,
        content_type: str = "application/octet-stream",
        total_size: Optional[int] = None,
        metadata: Optional[dict[str, str]] = None,
        overwrite: bool = False,
    ) -> str:
        """Stream upload to GCS using resumable upload for large files."""
        buffer = io.BytesIO()
        async for chunk in stream:
            buffer.write(chunk)
        data = buffer.getvalue()

        if len(data) <= RESUMABLE_UPLOAD_THRESHOLD:
            return await self.upload_bytes(
                data, blob_path, content_type, metadata, overwrite
            )

        bucket = self._get_bucket()
        blob = bucket.blob(blob_path)

        if metadata:
            blob.metadata = metadata

        file_obj = io.BytesIO(data)
        try:
            blob.upload_from_file(
                file_obj,
                content_type=content_type,
                checksum="crc32c",
                size=len(data),
                retry=gcs_retry.DEFAULT_RETRY,
                if_generation_match=None if overwrite else 0,
            )
        except Exception as exc:
            if "conditionNotMet" in str(exc) or "412" in str(exc):
                logger.debug(
                    "gcs_object_already_exists_skipped",
                    extra={"blob_path": blob_path},
                )
                return f"gs://{self._bucket_name}/{blob_path}"
            raise

        uri = f"gs://{self._bucket_name}/{blob_path}"
        logger.debug(
            "gcs_resumable_upload_complete",
            extra={"blob_path": blob_path, "size_bytes": len(data)},
        )
        return uri

    # ── Content-addressed storage for attachments ──────────────────────────

    async def upload_attachment_dedup(
        self,
        data: bytes,
        tenant_id: str,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> tuple[str, bool]:
        """Upload attachment using SHA-256 hash as object name for dedup.

        Returns (gcs_uri, was_already_present).
        """
        digest = hashlib.sha256(data).hexdigest()
        blob_path = f"{tenant_id}/attachments/{digest[:2]}/{digest}"

        bucket = self._get_bucket()
        blob = bucket.blob(blob_path)

        if blob.exists():
            return f"gs://{self._bucket_name}/{blob_path}", True

        await self.upload_bytes(
            data,
            blob_path,
            content_type=content_type,
            metadata={"original_filename": _sanitise_path_segment(filename)},
        )
        return f"gs://{self._bucket_name}/{blob_path}", False

    # ── Sidecar files (permissions, metadata) ─────────────────────────────

    async def write_permissions_sidecar(
        self,
        blob_path: str,
        permissions: dict,
    ) -> str:
        """Write a JSON permissions sidecar alongside a migrated object."""
        import json

        sidecar_path = blob_path + GCS_PERMISSIONS_SUFFIX
        data = json.dumps(permissions, default=str, indent=2).encode("utf-8")
        return await self.upload_bytes(
            data, sidecar_path, "application/json", overwrite=True
        )

    async def write_metadata_sidecar(
        self,
        blob_path: str,
        meta: dict,
    ) -> str:
        """Write a JSON metadata sidecar alongside a migrated object."""
        import json

        sidecar_path = blob_path + GCS_METADATA_SUFFIX
        data = json.dumps(meta, default=str, indent=2).encode("utf-8")
        return await self.upload_bytes(
            data, sidecar_path, "application/json", overwrite=True
        )

    # ── Existence / verification ───────────────────────────────────────────

    def exists(self, blob_path: str) -> bool:
        bucket = self._get_bucket()
        return bucket.blob(blob_path).exists()

    def get_crc32c(self, blob_path: str) -> Optional[str]:
        """Return the CRC32c checksum of an existing GCS object."""
        bucket = self._get_bucket()
        blob = bucket.blob(blob_path)
        blob.reload()
        return blob.crc32c
