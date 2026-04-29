"""BigQuery Writer — streaming inserts and batch load jobs for indexed data."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from google.cloud import bigquery
from google.cloud.bigquery import SchemaField

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


# Pre-defined schemas for workload indexes
EMAIL_INDEX_SCHEMA: list[SchemaField] = [
    SchemaField("message_id", "STRING", mode="REQUIRED"),
    SchemaField("job_id", "STRING", mode="REQUIRED"),
    SchemaField("tenant_id", "STRING", mode="REQUIRED"),
    SchemaField("user_id_hash", "STRING", mode="REQUIRED"),
    SchemaField("folder_path", "STRING"),
    SchemaField("subject_hash", "STRING"),
    SchemaField("sender_hash", "STRING"),
    SchemaField("received_at", "TIMESTAMP"),
    SchemaField("size_bytes", "INTEGER"),
    SchemaField("has_attachments", "BOOLEAN"),
    SchemaField("gcs_uri", "STRING", mode="REQUIRED"),
    SchemaField("migrated_at", "TIMESTAMP", mode="REQUIRED"),
]

ITEM_AUDIT_SCHEMA: list[SchemaField] = [
    SchemaField("item_id", "STRING", mode="REQUIRED"),
    SchemaField("job_id", "STRING", mode="REQUIRED"),
    SchemaField("tenant_id", "STRING", mode="REQUIRED"),
    SchemaField("workload", "STRING", mode="REQUIRED"),
    SchemaField("source_id", "STRING", mode="REQUIRED"),
    SchemaField("source_path", "STRING"),
    SchemaField("gcs_uri", "STRING"),
    SchemaField("bytes_transferred", "INTEGER"),
    SchemaField("state", "STRING", mode="REQUIRED"),
    SchemaField("error_type", "STRING"),
    SchemaField("duration_seconds", "FLOAT"),
    SchemaField("migrated_at", "TIMESTAMP", mode="REQUIRED"),
]


class BigQueryWriter:
    """Writes migration audit records and email indexes to BigQuery.

    Uses streaming inserts for low-latency audit logging.
    Batch load jobs are used for large-volume data ingestion.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._dataset_id = self._settings.gcp.bigquery_dataset
        self._client: Optional[bigquery.Client] = None

    def _get_client(self) -> bigquery.Client:
        if self._client is None:
            self._client = bigquery.Client(
                project=self._settings.gcp.project_id
            )
        return self._client

    def _table_ref(self, table_id: str) -> str:
        project = self._settings.gcp.project_id
        return f"{project}.{self._dataset_id}.{table_id}"

    # ── Schema management ──────────────────────────────────────────────────

    def ensure_table(
        self, table_id: str, schema: list[SchemaField]
    ) -> None:
        """Create table if not exists (idempotent)."""
        client = self._get_client()
        full_ref = self._table_ref(table_id)
        table = bigquery.Table(full_ref, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="migrated_at",
        )
        try:
            client.create_table(table, exists_ok=True)
            logger.debug(
                "bigquery_table_ensured", extra={"table": full_ref}
            )
        except Exception as exc:
            logger.warning(
                "bigquery_table_create_warning",
                extra={"table": full_ref, "error": str(exc)},
            )

    # ── Streaming inserts ──────────────────────────────────────────────────

    async def stream_rows(
        self,
        table_id: str,
        rows: list[dict[str, Any]],
        skip_invalid: bool = False,
    ) -> None:
        """Stream rows into a BigQuery table using the insertAll API."""
        client = self._get_client()
        full_ref = self._table_ref(table_id)
        table = client.get_table(full_ref)

        errors = client.insert_rows_json(
            table,
            rows,
            row_ids=[str(uuid.uuid4()) for _ in rows],
            skip_invalid_rows=skip_invalid,
        )
        if errors:
            logger.error(
                "bigquery_streaming_insert_errors",
                extra={"table": full_ref, "errors": errors[:5]},
            )
            raise RuntimeError(
                f"BigQuery streaming insert failed: {errors[0]}"
            )

    # ── Batch load from GCS ────────────────────────────────────────────────

    async def load_from_gcs(
        self,
        table_id: str,
        gcs_uris: list[str],
        schema: list[SchemaField],
        source_format: bigquery.SourceFormat = bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    ) -> None:
        """Load data from GCS into BigQuery via a batch load job."""
        client = self._get_client()
        full_ref = self._table_ref(table_id)

        job_config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=source_format,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            ignore_unknown_values=True,
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="migrated_at",
            ),
        )
        load_job = client.load_table_from_uri(
            gcs_uris, full_ref, job_config=job_config
        )
        load_job.result(timeout=600)
        logger.info(
            "bigquery_load_job_complete",
            extra={
                "table": full_ref,
                "rows_loaded": load_job.output_rows,
                "uri_count": len(gcs_uris),
            },
        )

    # ── Convenience writers ────────────────────────────────────────────────

    async def write_audit_record(
        self,
        item_id: str,
        job_id: str,
        tenant_id: str,
        workload: str,
        source_id: str,
        gcs_uri: Optional[str],
        state: str,
        bytes_transferred: int = 0,
        error_type: Optional[str] = None,
        duration_seconds: float = 0.0,
        source_path: str = "",
    ) -> None:
        self.ensure_table("item_audit", ITEM_AUDIT_SCHEMA)
        row = {
            "item_id": item_id,
            "job_id": job_id,
            "tenant_id": tenant_id,
            "workload": workload,
            "source_id": source_id,
            "source_path": source_path,
            "gcs_uri": gcs_uri,
            "bytes_transferred": bytes_transferred,
            "state": state,
            "error_type": error_type,
            "duration_seconds": duration_seconds,
            "migrated_at": datetime.utcnow().isoformat(),
        }
        await self.stream_rows("item_audit", [row])
