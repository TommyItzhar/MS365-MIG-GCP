"""Monitoring & Observability — structured logging + Cloud Monitoring metrics.

Every migrated item is logged as a structured JSON record.
Custom Cloud Monitoring metrics are written via the Monitoring API.
PII (email addresses, user IDs) are SHA-256 hashed in all log entries.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import monitoring_v3

from app.constants import (
    METRIC_BYTES_TRANSFERRED,
    METRIC_ETC_SECONDS,
    METRIC_ITEMS_FAILED,
    METRIC_ITEMS_MIGRATED,
    METRIC_QUEUE_DEPTH,
    METRIC_THROUGHPUT,
)
from app.config.settings import get_settings
from app.models import ErrorType, WorkloadType

logger = logging.getLogger(__name__)


def _hash_pii(value: str) -> str:
    """One-way hash for PII fields (email, UPN, display name) in log records."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter compatible with Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "__dict__"):
            for key, val in record.__dict__.items():
                if key not in (
                    "name", "msg", "args", "levelname", "levelno",
                    "pathname", "filename", "module", "exc_info",
                    "exc_text", "stack_info", "lineno", "funcName",
                    "created", "msecs", "relativeCreated", "thread",
                    "threadName", "processName", "process", "message",
                    "taskName",
                ):
                    payload[key] = val
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON formatter for Cloud Logging."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)


class MetricsReporter:
    """Writes custom Cloud Monitoring metrics for the migration engine.

    Metrics are written using the Cloud Monitoring v3 API.
    Falls back to logging-only mode if Cloud Monitoring is unavailable.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._project_name = (
            f"projects/{self._settings.gcp.project_id}"
        )
        self._client: Optional[monitoring_v3.MetricServiceClient] = None
        self._enabled = self._settings.gcp.project_id != ""

    def _get_client(self) -> monitoring_v3.MetricServiceClient:
        if self._client is None:
            self._client = monitoring_v3.MetricServiceClient()
        return self._client

    def _make_time_series(
        self,
        metric_type: str,
        value: float,
        labels: dict[str, str],
        metric_kind: str = "CUMULATIVE",
        value_type: str = "DOUBLE",
    ) -> monitoring_v3.TimeSeries:
        series = monitoring_v3.TimeSeries()
        series.metric.type = metric_type
        series.metric.labels.update(labels)
        series.resource.type = "generic_task"
        series.resource.labels.update(
            {
                "project_id": self._settings.gcp.project_id,
                "location": self._settings.gcp.region,
                "namespace": "migration-engine",
                "job": "migrator",
                "task_id": "main",
            }
        )

        now = time.time()
        point = monitoring_v3.Point()

        if value_type == "DOUBLE":
            point.value.double_value = value
        elif value_type == "INT64":
            point.value.int64_value = int(value)

        interval = monitoring_v3.TimeInterval()
        interval.end_time.seconds = int(now)
        interval.end_time.nanos = int((now % 1) * 1e9)

        if metric_kind == "CUMULATIVE":
            interval.start_time.seconds = int(now) - 1
            interval.start_time.nanos = 0

        point.interval = interval
        series.points = [point]
        return series

    def _write(self, series: list[monitoring_v3.TimeSeries]) -> None:
        if not self._enabled:
            return
        try:
            client = self._get_client()
            client.create_time_series(
                name=self._project_name, time_series=series
            )
        except GoogleAPICallError as exc:
            logger.warning(
                "metrics_write_failed",
                extra={"error": str(exc)},
            )

    # ── Public metric methods ──────────────────────────────────────────────

    def record_item_migrated(
        self,
        workload: WorkloadType,
        bytes_transferred: int,
    ) -> None:
        series = [
            self._make_time_series(
                METRIC_ITEMS_MIGRATED,
                1.0,
                {"workload": workload.value},
            ),
            self._make_time_series(
                METRIC_BYTES_TRANSFERRED,
                float(bytes_transferred),
                {"workload": workload.value},
            ),
        ]
        self._write(series)

    def record_item_failed(
        self,
        workload: WorkloadType,
        error_type: ErrorType,
    ) -> None:
        series = [
            self._make_time_series(
                METRIC_ITEMS_FAILED,
                1.0,
                {
                    "workload": workload.value,
                    "error_type": error_type.value,
                },
            )
        ]
        self._write(series)

    def record_queue_depth(self, depth: int) -> None:
        series = [
            self._make_time_series(
                METRIC_QUEUE_DEPTH,
                float(depth),
                {},
                metric_kind="GAUGE",
            )
        ]
        self._write(series)

    def record_throughput(self, items_per_second: float) -> None:
        series = [
            self._make_time_series(
                METRIC_THROUGHPUT,
                items_per_second,
                {},
                metric_kind="GAUGE",
            )
        ]
        self._write(series)

    def record_etc(self, estimated_seconds: float) -> None:
        series = [
            self._make_time_series(
                METRIC_ETC_SECONDS,
                estimated_seconds,
                {},
                metric_kind="GAUGE",
            )
        ]
        self._write(series)


class MigrationLogger:
    """Structured per-item migration logger.

    Wraps Python logging to ensure every item event is a JSON record
    with consistent fields. PII is hashed before logging.
    """

    def __init__(self, job_id: str, workload: WorkloadType) -> None:
        self._job_id = job_id
        self._workload = workload
        self._log = logging.getLogger(f"migration.{workload.value}")

    def _base(self) -> dict[str, Any]:
        return {
            "job_id": self._job_id,
            "workload": self._workload.value,
        }

    def item_started(self, item_id: str, source_id: str) -> None:
        self._log.info(
            "item_migration_started",
            extra={
                **self._base(),
                "item_id": item_id,
                "source_id_hash": _hash_pii(source_id),
            },
        )

    def item_completed(
        self,
        item_id: str,
        gcs_uri: str,
        bytes_transferred: int,
        duration_seconds: float,
    ) -> None:
        self._log.info(
            "item_migration_completed",
            extra={
                **self._base(),
                "item_id": item_id,
                "gcs_uri": gcs_uri,
                "bytes_transferred": bytes_transferred,
                "duration_seconds": round(duration_seconds, 3),
            },
        )

    def item_failed(
        self,
        item_id: str,
        error: str,
        error_type: ErrorType,
        retry_count: int,
    ) -> None:
        self._log.error(
            "item_migration_failed",
            extra={
                **self._base(),
                "item_id": item_id,
                "error_type": error_type.value,
                "retry_count": retry_count,
                "error": error,
            },
        )

    def item_skipped(self, item_id: str, reason: str) -> None:
        self._log.info(
            "item_migration_skipped",
            extra={
                **self._base(),
                "item_id": item_id,
                "reason": reason,
            },
        )

    def checkpoint_saved(self, entity_id: str, count: int) -> None:
        self._log.info(
            "checkpoint_saved",
            extra={
                **self._base(),
                "entity_id": entity_id,
                "processed_count": count,
            },
        )
