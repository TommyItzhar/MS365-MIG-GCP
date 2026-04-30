"""Shared pytest fixtures for the migration engine test suite."""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from app.models import (
    MigrationItem,
    MigrationScope,
    WorkloadType,
    ItemState,
)


@pytest.fixture
def mock_settings(monkeypatch):
    """Patch settings to use test values without requiring real GCP/M365."""
    from app.config.settings import Settings, GCPSettings, M365Settings, WorkloadConfig

    settings = MagicMock(spec=Settings)
    settings.gcp = MagicMock(spec=GCPSettings)
    settings.gcp.project_id = "test-project"
    settings.gcp.gcs_bucket = "test-bucket"
    settings.gcp.bigquery_dataset = "test_dataset"
    settings.gcp.firestore_database = "(default)"
    settings.gcp.pubsub_dlq_topic = "test-dlq"
    settings.gcp.region = "us-central1"
    settings.m365 = MagicMock(spec=M365Settings)
    settings.m365.tenant_id = "test-tenant-id"
    settings.m365.client_id = "test-client-id"
    settings.m365.client_secret = "test-client-secret"
    settings.workloads = MagicMock(spec=WorkloadConfig)
    settings.log_level = "DEBUG"
    settings.use_secret_manager = False
    settings.worker_concurrency = 2
    settings.environment = "development"
    settings.checkpoint_interval = 10

    with patch("app.config.settings.get_settings", return_value=settings):
        yield settings


@pytest.fixture
def mock_auth():
    """Mock AuthManager that returns test tokens without calling MSAL or Secret Manager."""
    auth = AsyncMock()
    auth.get_graph_token.return_value = "test-graph-token"
    auth.get_graph_headers.return_value = {
        "Authorization": "Bearer test-graph-token",
        "Content-Type": "application/json",
        "ConsistencyLevel": "eventual",
    }
    auth.get_tenant_id.return_value = "test-tenant-id"
    return auth


@pytest.fixture
def mock_throttle():
    """ThrottleManager that passes through calls without rate limiting in tests."""
    from app.throttle.throttle_manager import ThrottleManager
    throttle = MagicMock(spec=ThrottleManager)

    async def _passthrough(workload, fn, *args, **kwargs):
        return await fn(*args, **kwargs)

    throttle.execute = _passthrough
    return throttle


@pytest.fixture
def mock_state():
    """Fully mocked StateManager backed by an in-memory dict."""
    state = AsyncMock()
    _store = {}

    async def _upsert(item):
        _store[item.id] = item

    async def _get(item_id):
        return _store.get(item_id)

    async def _is_migrated(item_id):
        item = _store.get(item_id)
        return item is not None and item.state == ItemState.COMPLETED

    state.upsert_item = _upsert
    state.get_item = _get
    state.is_already_migrated = _is_migrated
    state.mark_in_progress = AsyncMock()
    state.mark_completed = AsyncMock()
    state.mark_failed = AsyncMock()
    state.mark_skipped = AsyncMock()
    state.save_checkpoint = AsyncMock()
    state.get_checkpoint = AsyncMock(return_value=None)
    state.get_delta_token = AsyncMock(return_value=None)
    state.save_delta_token = AsyncMock()
    state.find_by_content_hash = AsyncMock(return_value=None)
    state.update_workload_progress = AsyncMock()
    return state


@pytest.fixture
def mock_gcs():
    """Mocked GCSWriter that returns predictable URIs without touching GCS."""
    gcs = AsyncMock()
    gcs._bucket_name = "test-bucket"

    async def _upload_bytes(data, blob_path, *args, **kwargs):
        return f"gs://test-bucket/{blob_path}"

    async def _upload_stream(stream, blob_path, *args, **kwargs):
        return f"gs://test-bucket/{blob_path}"

    async def _upload_attachment_dedup(data, tenant_id, filename, *args, **kwargs):
        import hashlib
        digest = hashlib.sha256(data).hexdigest()
        return f"gs://test-bucket/{tenant_id}/attachments/{digest}", False

    async def _write_permissions_sidecar(blob_path, perms):
        return f"gs://test-bucket/{blob_path}.permissions.json"

    async def _write_metadata_sidecar(blob_path, meta):
        return f"gs://test-bucket/{blob_path}.metadata.json"

    gcs.upload_bytes = _upload_bytes
    gcs.upload_stream = _upload_stream
    gcs.upload_attachment_dedup = _upload_attachment_dedup
    gcs.write_permissions_sidecar = _write_permissions_sidecar
    gcs.write_metadata_sidecar = _write_metadata_sidecar
    gcs.exists = MagicMock(return_value=True)
    gcs.get_crc32c = MagicMock(return_value="AAAA")
    return gcs


@pytest.fixture
def mock_metrics():
    from app.monitoring.monitoring import MetricsReporter
    metrics = MagicMock(spec=MetricsReporter)
    return metrics


@pytest.fixture
def mock_errors():
    from app.errors.error_handler import ErrorAggregator
    errors = MagicMock(spec=ErrorAggregator)
    return errors


@pytest.fixture
def mock_dlq():
    from app.errors.error_handler import DLQPublisher
    dlq = MagicMock(spec=DLQPublisher)
    return dlq


@pytest.fixture
def sample_migration_item():
    return MigrationItem(
        id="item-001",
        job_id="job-001",
        workload=WorkloadType.EXCHANGE,
        source_id="user@example.com",
        source_path="user@example.com",
        tenant_id="test-tenant-id",
        estimated_bytes=1024,
        metadata={"user_id": "aad-user-001"},
    )


@pytest.fixture
def sample_scope():
    return MigrationScope(
        tenant_id="test-tenant-id",
        workloads=[WorkloadType.EXCHANGE, WorkloadType.ONEDRIVE],
    )


@pytest.fixture
def migrator_kwargs(mock_auth, mock_throttle, mock_state, mock_gcs, mock_metrics, mock_errors, mock_dlq):
    return dict(
        auth=mock_auth,
        throttle=mock_throttle,
        state=mock_state,
        gcs=mock_gcs,
        metrics=mock_metrics,
        errors=mock_errors,
        dlq=mock_dlq,
        job_id="job-001",
    )
