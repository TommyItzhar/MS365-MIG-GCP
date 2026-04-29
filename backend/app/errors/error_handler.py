"""Error Handler & Dead Letter Queue.

Taxonomy-driven error classification determines retry strategy.
Permanently failed items are published to a Pub/Sub DLQ topic.
Error aggregation feeds Cloud Monitoring alerting.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from google.cloud import pubsub_v1

from app.constants import DLQ_ALERT_THRESHOLD, MAX_RETRY_ATTEMPTS
from app.config.settings import get_settings
from app.models import ErrorLogEntry, ErrorType, MigrationItem, WorkloadType

logger = logging.getLogger(__name__)


def classify_error(exc: Exception, status_code: Optional[int] = None) -> ErrorType:
    """Map an exception to a structured ErrorType for retry-strategy selection."""
    msg = str(exc).lower()

    if status_code == 429:
        return ErrorType.THROTTLE
    if status_code in (401, 403):
        return ErrorType.AUTH_FAILURE
    if status_code == 404:
        return ErrorType.ITEM_NOT_FOUND
    if status_code == 413 or "too large" in msg or "413" in msg:
        return ErrorType.ITEM_TOO_LARGE
    if status_code in (500, 502, 503, 504) or "unavailable" in msg:
        return ErrorType.API_UNAVAILABLE
    if "permission" in msg or "forbidden" in msg or "access denied" in msg:
        return ErrorType.PERMISSION_DENIED
    if "corrupt" in msg or "checksum" in msg or "crc" in msg:
        return ErrorType.DATA_CORRUPTION
    if "timeout" in msg or "network" in msg or "connection" in msg:
        return ErrorType.NETWORK_ERROR
    if "quota" in msg:
        return ErrorType.QUOTA_EXCEEDED
    return ErrorType.UNKNOWN


def should_retry(error_type: ErrorType, retry_count: int) -> bool:
    """Return True if the item should be retried based on error type and count."""
    if retry_count >= MAX_RETRY_ATTEMPTS:
        return False

    # Never retry these — escalate to DLQ immediately
    non_retryable = {
        ErrorType.AUTH_FAILURE,
        ErrorType.ITEM_TOO_LARGE,
        ErrorType.PERMISSION_DENIED,
        ErrorType.ITEM_NOT_FOUND,
    }
    return error_type not in non_retryable


class DLQPublisher:
    """Publishes permanently failed items to the Pub/Sub Dead Letter Queue."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._publisher: Optional[pubsub_v1.PublisherClient] = None
        self._topic_path: Optional[str] = None
        self._dlq_count = 0

    def _get_publisher(self) -> tuple[pubsub_v1.PublisherClient, str]:
        if self._publisher is None:
            self._publisher = pubsub_v1.PublisherClient()
            project = self._settings.gcp.project_id
            topic = self._settings.gcp.pubsub_dlq_topic
            self._topic_path = (
                self._publisher.topic_path(project, topic)
            )
        return self._publisher, self._topic_path  # type: ignore[return-value]

    def publish(self, item: MigrationItem, error: str, error_type: ErrorType) -> None:
        """Publish a failed item to the DLQ. Logs on publish failure."""
        try:
            publisher, topic_path = self._get_publisher()
            payload = {
                "id": str(uuid.uuid4()),
                "job_id": item.job_id,
                "item_id": item.id,
                "source_id": item.source_id,
                "workload": item.workload.value,
                "tenant_id": item.tenant_id,
                "error": error,
                "error_type": error_type.value,
                "retry_count": item.retry_count,
                "timestamp": datetime.utcnow().isoformat(),
            }
            data = json.dumps(payload).encode("utf-8")
            attributes = {
                "workload": item.workload.value,
                "error_type": error_type.value,
                "job_id": item.job_id,
            }
            future = publisher.publish(topic_path, data, **attributes)
            future.result(timeout=30)
            self._dlq_count += 1

            if self._dlq_count >= DLQ_ALERT_THRESHOLD:
                logger.error(
                    "dlq_threshold_breached",
                    extra={
                        "dlq_count": self._dlq_count,
                        "threshold": DLQ_ALERT_THRESHOLD,
                    },
                )

            logger.info(
                "item_sent_to_dlq",
                extra={
                    "item_id": item.id,
                    "workload": item.workload.value,
                    "error_type": error_type.value,
                },
            )
        except Exception as exc:
            logger.error(
                "dlq_publish_failed",
                extra={"item_id": item.id, "error": str(exc)},
            )

    @property
    def dlq_count(self) -> int:
        return self._dlq_count


class ErrorAggregator:
    """Collects and summarises errors per workload for reporting."""

    def __init__(self) -> None:
        self._errors: list[ErrorLogEntry] = []

    def record(
        self,
        job_id: str,
        item_id: Optional[str],
        workload: WorkloadType,
        error_type: ErrorType,
        message: str,
        retry_count: int = 0,
        is_dlq: bool = False,
        source_id: Optional[str] = None,
    ) -> ErrorLogEntry:
        entry = ErrorLogEntry(
            id=str(uuid.uuid4()),
            job_id=job_id,
            item_id=item_id,
            workload=workload,
            error_type=error_type,
            message=message,
            retry_count=retry_count,
            is_dlq=is_dlq,
            timestamp=datetime.utcnow(),
            source_id=source_id,
        )
        self._errors.append(entry)
        return entry

    def get_errors(
        self,
        workload: Optional[WorkloadType] = None,
        dlq_only: bool = False,
        page: int = 0,
        page_size: int = 50,
    ) -> list[ErrorLogEntry]:
        filtered = self._errors
        if workload:
            filtered = [e for e in filtered if e.workload == workload]
        if dlq_only:
            filtered = [e for e in filtered if e.is_dlq]
        start = page * page_size
        return filtered[start : start + page_size]

    def summary(self) -> dict[str, int]:
        by_type: dict[str, int] = {}
        for entry in self._errors:
            key = f"{entry.workload.value}.{entry.error_type.value}"
            by_type[key] = by_type.get(key, 0) + 1
        return by_type
