"""Tests for ExchangeMigrator — discovery, mail folder migration, calendar, contacts."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from app.migrators.exchange_migrator import ExchangeMigrator
from app.models import MigrationItem, MigrationScope, WorkloadType


@pytest.fixture
def migrator(migrator_kwargs):
    return ExchangeMigrator(**migrator_kwargs)


MOCK_USERS_RESPONSE = {
    "value": [
        {
            "id": "user-001",
            "userPrincipalName": "alice@example.com",
            "displayName": "Alice Smith",
            "mail": "alice@example.com",
        }
    ]
}

MOCK_FOLDERS_RESPONSE = {
    "value": [
        {"id": "folder-inbox", "displayName": "Inbox", "totalItemCount": 5},
        {"id": "folder-sent", "displayName": "Sent Items", "totalItemCount": 3},
    ]
}

MOCK_MESSAGES_RESPONSE = {
    "value": [
        {
            "id": "msg-001",
            "subject": "Test email",
            "receivedDateTime": "2024-01-15T10:00:00Z",
            "hasAttachments": False,
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "internetMessageId": "<test@example.com>",
        }
    ]
}


@pytest.mark.asyncio
class TestExchangeDiscovery:
    async def test_discover_returns_manifest_with_users(
        self, migrator, sample_scope
    ):
        scope = MigrationScope(
            tenant_id="test-tenant-id",
            workloads=[WorkloadType.EXCHANGE],
        )

        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/users").mock(
                return_value=httpx.Response(200, json=MOCK_USERS_RESPONSE)
            )
            # Mailbox settings / drive for size estimation
            mock.get("/users/alice@example.com/mailboxSettings").mock(
                return_value=httpx.Response(200, json={})
            )
            mock.get("/users/alice@example.com/drive").mock(
                return_value=httpx.Response(
                    200, json={"quota": {"used": 1048576}}
                )
            )

            # Patch the http client to use respx
            migrator._http_client = httpx.AsyncClient(
                base_url="https://graph.microsoft.com/v1.0"
            )

            manifest = await migrator.discover(scope)

        assert manifest.total_items == 1
        assert manifest.items[0].source_id == "alice@example.com"
        assert manifest.items[0].workload == WorkloadType.EXCHANGE

    async def test_discover_with_user_filter(self, migrator):
        scope = MigrationScope(
            tenant_id="test-tenant-id",
            workloads=[WorkloadType.EXCHANGE],
            user_filter=["bob@example.com"],
        )

        # Alice is NOT in the filter — should be excluded
        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/users").mock(
                return_value=httpx.Response(200, json=MOCK_USERS_RESPONSE)
            )
            migrator._http_client = httpx.AsyncClient(
                base_url="https://graph.microsoft.com/v1.0"
            )
            manifest = await migrator.discover(scope)

        assert manifest.total_items == 0


@pytest.mark.asyncio
class TestExchangeMigrateItem:
    async def test_migrate_item_success(
        self, migrator, mock_gcs, mock_state
    ):
        mock_state.is_already_migrated = AsyncMock(return_value=False)

        item = MigrationItem(
            id="item-001",
            job_id="job-001",
            workload=WorkloadType.EXCHANGE,
            source_id="alice@example.com",
            source_path="alice@example.com",
            tenant_id="test-tenant-id",
            metadata={"user_id": "user-001"},
        )

        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/users/alice@example.com/mailFolders").mock(
                return_value=httpx.Response(200, json=MOCK_FOLDERS_RESPONSE)
            )
            mock.get(
                "/users/alice@example.com/mailFolders/folder-inbox/messages"
            ).mock(return_value=httpx.Response(200, json=MOCK_MESSAGES_RESPONSE))
            mock.get(
                "/users/alice@example.com/mailFolders/folder-sent/messages"
            ).mock(return_value=httpx.Response(200, json={"value": []}))
            mock.post("/$batch").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "responses": [
                            {
                                "id": "1",
                                "status": 200,
                                "body": "MIME-Version: 1.0\r\nSubject: Test\r\n\r\nBody",
                            }
                        ]
                    },
                )
            )
            mock.get("/users/alice@example.com/events").mock(
                return_value=httpx.Response(200, json={"value": []})
            )
            mock.get("/users/alice@example.com/contacts").mock(
                return_value=httpx.Response(200, json={"value": []})
            )
            mock.get("/users/alice@example.com/todo/lists").mock(
                return_value=httpx.Response(200, json={"value": []})
            )
            # Hidden folders
            mock.get(
                "/users/alice@example.com/mailFolders/recoverableitemsdeletions"
            ).mock(return_value=httpx.Response(404, json={"error": {"code": "NotFound"}}))
            mock.get(
                "/users/alice@example.com/mailFolders/recoverableitemspurges"
            ).mock(return_value=httpx.Response(404, json={"error": {"code": "NotFound"}}))

            migrator._http_client = httpx.AsyncClient(
                base_url="https://graph.microsoft.com/v1.0"
            )
            result = await migrator.migrate_item(item)

        assert result.success is True
        assert result.bytes_transferred >= 0

    async def test_migrate_item_returns_failure_on_exception(
        self, migrator, mock_state
    ):
        mock_state.is_already_migrated = AsyncMock(return_value=False)
        item = MigrationItem(
            id="item-fail",
            job_id="job-001",
            workload=WorkloadType.EXCHANGE,
            source_id="broken@example.com",
            source_path="broken@example.com",
            tenant_id="test-tenant-id",
        )

        with respx.mock(base_url="https://graph.microsoft.com/v1.0") as mock:
            mock.get("/users/broken@example.com/mailFolders").mock(
                return_value=httpx.Response(500, json={"error": {"code": "ServiceUnavailable"}})
            )
            migrator._http_client = httpx.AsyncClient(
                base_url="https://graph.microsoft.com/v1.0"
            )
            result = await migrator.migrate_item(item)

        assert result.success is False
        assert result.error is not None


@pytest.mark.asyncio
class TestExchangeVerify:
    async def test_verify_completed_item(self, migrator, mock_gcs):
        item = MigrationItem(
            id="item-001",
            job_id="job-001",
            workload=WorkloadType.EXCHANGE,
            source_id="alice@example.com",
            source_path="alice@example.com",
            tenant_id="test-tenant-id",
            gcs_uri="gs://test-bucket/test-tenant-id/exchange/alice_example.com/2024-01/item-001.eml",
        )
        mock_gcs.exists = MagicMock(return_value=True)
        result = await migrator.verify(item)
        assert result.passed is True

    async def test_verify_missing_gcs_uri(self, migrator):
        item = MigrationItem(
            id="item-002",
            job_id="job-001",
            workload=WorkloadType.EXCHANGE,
            source_id="alice@example.com",
            source_path="alice@example.com",
            tenant_id="test-tenant-id",
        )
        result = await migrator.verify(item)
        assert result.passed is False
