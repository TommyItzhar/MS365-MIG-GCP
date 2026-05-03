"""Tests for OneDriveMigrator — delta sync, dedup, version history."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from app.migrators.m365_to_gcp.onedrive_migrator import OneDriveMigrator
from app.models import MigrationItem, MigrationScope, WorkloadType


@pytest.fixture
def migrator(migrator_kwargs):
    return OneDriveMigrator(**migrator_kwargs)


MOCK_USERS = {
    "value": [{"id": "u1", "userPrincipalName": "alice@example.com", "displayName": "Alice"}]
}
MOCK_DRIVE = {
    "id": "drive-001",
    "quota": {"used": 2097152, "total": 5368709120},
    "owner": {"user": {"id": "u1"}},
}
MOCK_DELTA_ITEMS = {
    "value": [
        {
            "id": "file-001",
            "name": "report.xlsx",
            "size": 1024,
            "file": {
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "hashes": {"sha256Hash": "abc123"},
            },
            "parentReference": {"path": "/drive/root:/Documents"},
            "lastModifiedDateTime": "2024-03-01T12:00:00Z",
            "@microsoft.graph.downloadUrl": "https://download.example.com/report.xlsx",
        }
    ],
    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/users/u1/drive/root/delta?$deltatoken=xyz",
}


@pytest.mark.asyncio
class TestOneDriveDiscovery:
    async def test_discover_returns_manifest(self, migrator):
        scope = MigrationScope(
            tenant_id="test-tenant-id",
            workloads=[WorkloadType.ONEDRIVE],
        )
        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/users").mock(return_value=httpx.Response(200, json=MOCK_USERS))
            mock.get("/users/alice@example.com/drive").mock(
                return_value=httpx.Response(200, json=MOCK_DRIVE)
            )
            migrator._http_client = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0")
            manifest = await migrator.discover(scope)

        assert manifest.total_items == 1
        assert manifest.items[0].estimated_bytes == 2097152

    async def test_user_filter_excludes_non_matching(self, migrator):
        scope = MigrationScope(
            tenant_id="test-tenant-id",
            workloads=[WorkloadType.ONEDRIVE],
            user_filter=["bob@example.com"],
        )
        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/users").mock(return_value=httpx.Response(200, json=MOCK_USERS))
            migrator._http_client = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0")
            manifest = await migrator.discover(scope)

        assert manifest.total_items == 0


@pytest.mark.asyncio
class TestOneDriveMigrateItem:
    async def test_migrate_item_stores_delta_token(
        self, migrator, mock_state, mock_gcs
    ):
        mock_state.is_already_migrated = AsyncMock(return_value=False)
        mock_state.get_delta_token = AsyncMock(return_value=None)

        item = MigrationItem(
            id="item-001",
            job_id="job-001",
            workload=WorkloadType.ONEDRIVE,
            source_id="u1",
            source_path="alice@example.com",
            tenant_id="test-tenant-id",
            metadata={"drive_id": "drive-001", "owner_upn": "alice@example.com"},
        )

        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/drives/drive-001/root/delta").mock(
                return_value=httpx.Response(200, json=MOCK_DELTA_ITEMS)
            )
            mock.get("/drives/drive-001/root/delta", params={"$select": True}).mock(
                return_value=httpx.Response(200, json=MOCK_DELTA_ITEMS)
            )
            # Permissions
            mock.get("/drive/items/file-001/permissions").mock(
                return_value=httpx.Response(200, json={"value": []})
            )
            # Versions
            mock.get("/drive/items/file-001/versions").mock(
                return_value=httpx.Response(200, json={"value": []})
            )
            # The download URL uses a full URL (not graph base)
            with respx.mock() as outer:
                outer.get("https://download.example.com/report.xlsx").mock(
                    return_value=httpx.Response(200, content=b"x" * 1024)
                )
                migrator._http_client = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0")
                result = await migrator.migrate_item(item)

        assert result.success is True
        mock_state.save_delta_token.assert_called_once()

    async def test_migrate_item_uses_existing_delta_token(
        self, migrator, mock_state, mock_gcs
    ):
        delta_url = "https://graph.microsoft.com/v1.0/drives/drive-001/root/delta?$deltatoken=existing"
        mock_state.get_delta_token = AsyncMock(return_value=delta_url)

        item = MigrationItem(
            id="item-002",
            job_id="job-001",
            workload=WorkloadType.ONEDRIVE,
            source_id="u1",
            source_path="alice@example.com",
            tenant_id="test-tenant-id",
            metadata={"drive_id": "drive-001", "owner_upn": "alice@example.com"},
        )

        with respx.mock() as mock:
            mock.get(delta_url).mock(
                return_value=httpx.Response(200, json={"value": [], "@odata.deltaLink": delta_url})
            )
            migrator._http_client = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0")
            result = await migrator.migrate_item(item)

        assert result.success is True
        # No files — 0 bytes transferred
        assert result.bytes_transferred == 0


@pytest.mark.asyncio
class TestOneDriveVerify:
    async def test_verify_with_gcs_uri(self, migrator):
        item = MigrationItem(
            id="i1",
            job_id="j1",
            workload=WorkloadType.ONEDRIVE,
            source_id="u1",
            source_path="",
            tenant_id="t1",
            gcs_uri="gs://test-bucket/test/onedrive/u1/",
        )
        result = await migrator.verify(item)
        assert result.passed is True

    async def test_verify_without_gcs_uri(self, migrator):
        item = MigrationItem(
            id="i2", job_id="j1", workload=WorkloadType.ONEDRIVE,
            source_id="u1", source_path="", tenant_id="t1",
        )
        result = await migrator.verify(item)
        assert result.passed is False
