"""Pub/Sub Writer — publishes migration events with ordering keys."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from google.cloud import pubsub_v1

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class PubSubWriter:
    """Publishes structured migration events to Pub/Sub topics.

    Ordering keys are set per-job to ensure sequential processing per job.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._publisher: Optional[pubsub_v1.PublisherClient] = None

    def _get_publisher(self) -> pubsub_v1.PublisherClient:
        if self._publisher is None:
            batch_settings = pubsub_v1.types.BatchSettings(
                max_messages=100,
                max_bytes=1_000_000,
                max_latency=0.1,
            )
            self._publisher = pubsub_v1.PublisherClient(
                batch_settings=batch_settings
            )
        return self._publisher

    def _topic_path(self, topic_id: str) -> str:
        project = self._settings.gcp.project_id
        return self._get_publisher().topic_path(project, topic_id)

    def publish(
        self,
        topic_id: str,
        data: dict[str, Any],
        ordering_key: str = "",
        attributes: Optional[dict[str, str]] = None,
    ) -> str:
        """Publish a JSON message. Returns the server-assigned message ID."""
        publisher = self._get_publisher()
        topic_path = self._topic_path(topic_id)

        payload = json.dumps(
            {**data, "published_at": datetime.utcnow().isoformat()},
            default=str,
        ).encode("utf-8")

        attrs = attributes or {}
        future = publisher.publish(
            topic_path,
            payload,
            ordering_key=ordering_key,
            **attrs,
        )
        message_id = future.result(timeout=30)
        logger.debug(
            "pubsub_message_published",
            extra={
                "topic": topic_id,
                "message_id": message_id,
                "ordering_key": ordering_key,
            },
        )
        return message_id

    def publish_job_event(
        self,
        job_id: str,
        event_type: str,
        workload: str,
        payload: dict[str, Any],
    ) -> str:
        """Convenience method for migration job lifecycle events."""
        data = {
            "event_type": event_type,
            "job_id": job_id,
            "workload": workload,
            **payload,
        }
        return self.publish(
            topic_id="migration-events",
            data=data,
            ordering_key=job_id,
            attributes={"event_type": event_type, "workload": workload},
        )
