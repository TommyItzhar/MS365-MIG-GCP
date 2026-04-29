"""Tests for AuthManager — token acquisition, refresh, and Secret Manager integration."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.auth_manager import _CachedToken, AuthManager
from app.constants import TOKEN_REFRESH_BUFFER_SECONDS


class TestCachedToken:
    def test_not_expired_when_fresh(self):
        token = _CachedToken(
            access_token="abc",
            expires_at=time.time() + 3600,
        )
        assert not token.is_expired()

    def test_expired_when_past_expiry(self):
        token = _CachedToken(
            access_token="abc",
            expires_at=time.time() - 1,
        )
        assert token.is_expired()

    def test_expires_within_buffer_considered_expired(self):
        token = _CachedToken(
            access_token="abc",
            expires_at=time.time() + TOKEN_REFRESH_BUFFER_SECONDS - 10,
        )
        assert token.is_expired()

    def test_not_expired_just_outside_buffer(self):
        token = _CachedToken(
            access_token="abc",
            expires_at=time.time() + TOKEN_REFRESH_BUFFER_SECONDS + 60,
        )
        assert not token.is_expired()


@pytest.mark.asyncio
class TestAuthManagerTokenCaching:
    async def test_returns_cached_token_on_second_call(self, mock_settings):
        auth = AuthManager.__new__(AuthManager)
        auth._settings = mock_settings
        auth._m365_creds = MagicMock(
            tenant_id="t1", client_id="c1", client_secret="s1"
        )
        auth._lock = __import__("asyncio").Lock()
        auth._graph_token_cache = {}
        auth._gcp_credentials = None
        auth._secret_client = None
        auth._msal_app = MagicMock()
        auth._msal_app.acquire_token_for_client.return_value = {
            "access_token": "fresh-token",
            "expires_in": 3600,
        }

        token1 = await auth.get_graph_token()
        # Second call should NOT call acquire_token_for_client again
        auth._msal_app.acquire_token_for_client.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }
        token2 = await auth.get_graph_token()

        assert token1 == token2 == "fresh-token"
        assert auth._msal_app.acquire_token_for_client.call_count == 1

    async def test_refreshes_when_token_expired(self, mock_settings):
        import time

        auth = AuthManager.__new__(AuthManager)
        auth._settings = mock_settings
        auth._m365_creds = MagicMock()
        auth._lock = __import__("asyncio").Lock()
        auth._graph_token_cache = {
            "https://graph.microsoft.com/.default": _CachedToken(
                access_token="old-token",
                expires_at=time.time() - 1,  # expired
            )
        }
        auth._gcp_credentials = None
        auth._secret_client = None
        auth._msal_app = MagicMock()
        auth._msal_app.acquire_token_for_client.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 3600,
        }

        token = await auth.get_graph_token()
        assert token == "refreshed-token"

    async def test_raises_on_msal_error(self, mock_settings):
        auth = AuthManager.__new__(AuthManager)
        auth._settings = mock_settings
        auth._m365_creds = MagicMock()
        auth._lock = __import__("asyncio").Lock()
        auth._graph_token_cache = {}
        auth._gcp_credentials = None
        auth._secret_client = None
        auth._msal_app = MagicMock()
        auth._msal_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "AADSTS70011",
        }

        with pytest.raises(RuntimeError, match="AADSTS70011"):
            await auth.get_graph_token()
