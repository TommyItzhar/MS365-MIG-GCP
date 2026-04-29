"""Authentication Manager — Microsoft Graph (MSAL) + GCP (ADC / SA key).

Design principles:
- Proactive token refresh 5 minutes before expiry to prevent mid-migration failures
- All secrets resolved from GCP Secret Manager; zero hardcoded credentials
- Per-workload scoped token cache so revocation of one scope doesn't block others
- GCP Workload Identity supported; explicit SA key is optional fallback
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import google.auth
import google.auth.transport.requests
import msal
from google.cloud import secretmanager
from google.oauth2 import service_account

from app.constants import (
    GRAPH_APP_SCOPES,
    GCP_AUTH_SCOPES,
    TOKEN_REFRESH_BUFFER_SECONDS,
    SECRET_MS365_TENANT_ID,
    SECRET_MS365_CLIENT_ID,
    SECRET_MS365_CLIENT_SECRET,
    SECRET_GCP_SA_KEY,
)
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # Unix timestamp

    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - TOKEN_REFRESH_BUFFER_SECONDS)


@dataclass
class _M365Credentials:
    tenant_id: str
    client_id: str
    client_secret: str


class AuthManager:
    """Singleton authentication manager.

    Usage::

        auth = await AuthManager.create()
        graph_token = await auth.get_graph_token()
        gcp_creds   = await auth.get_gcp_credentials()
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._m365_creds: Optional[_M365Credentials] = None
        self._msal_app: Optional[msal.ConfidentialClientApplication] = None
        self._graph_token_cache: dict[str, _CachedToken] = {}
        self._gcp_credentials: Optional[google.auth.credentials.Credentials] = None
        self._secret_client: Optional[secretmanager.SecretManagerServiceClient] = None
        self._lock = asyncio.Lock()

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    async def create(cls) -> "AuthManager":
        """Async factory — loads all credentials before returning."""
        instance = cls()
        await instance._initialise()
        return instance

    # ── Internal initialisation ────────────────────────────────────────────

    async def _initialise(self) -> None:
        await self._load_m365_credentials()
        await self._load_gcp_credentials()

    async def _get_secret(self, secret_name: str) -> str:
        """Fetch a secret value from GCP Secret Manager."""
        if not self._secret_client:
            self._secret_client = secretmanager.SecretManagerServiceClient()

        project_id = self._settings.gcp.project_id
        name = (
            f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        )
        try:
            response = self._secret_client.access_secret_version(
                request={"name": name}
            )
            value = response.payload.data.decode("utf-8").strip()
            logger.info(
                "secret_fetched",
                extra={"secret": secret_name, "project": project_id},
            )
            return value
        except Exception as exc:
            logger.error(
                "secret_fetch_failed",
                extra={"secret": secret_name, "error": str(exc)},
            )
            raise

    async def _load_m365_credentials(self) -> None:
        """Load M365 credentials from Secret Manager or env vars (dev fallback)."""
        settings = self._settings

        if settings.use_secret_manager:
            tenant_id = await self._get_secret(SECRET_MS365_TENANT_ID)
            client_id = await self._get_secret(SECRET_MS365_CLIENT_ID)
            client_secret = await self._get_secret(SECRET_MS365_CLIENT_SECRET)
        else:
            # Development fallback — env vars only, never in production
            tenant_id = settings.m365.tenant_id
            client_id = settings.m365.client_id
            client_secret = settings.m365.client_secret

        if not all([tenant_id, client_id, client_secret]):
            raise ValueError(
                "M365 credentials incomplete. Check Secret Manager or env vars."
            )

        self._m365_creds = _M365Credentials(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        self._msal_app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority,
        )
        logger.info("m365_auth_initialised", extra={"tenant_id": tenant_id})

    async def _load_gcp_credentials(self) -> None:
        """Initialise GCP credentials via Workload Identity or explicit SA key."""
        settings = self._settings

        if settings.gcp.service_account_key_path:
            with open(settings.gcp.service_account_key_path) as fh:
                sa_info = json.load(fh)
            self._gcp_credentials = (
                service_account.Credentials.from_service_account_info(
                    sa_info, scopes=GCP_AUTH_SCOPES
                )
            )
            logger.info("gcp_auth_sa_key_loaded")
        elif settings.use_secret_manager:
            try:
                sa_json = await self._get_secret(SECRET_GCP_SA_KEY)
                sa_info = json.loads(sa_json)
                self._gcp_credentials = (
                    service_account.Credentials.from_service_account_info(
                        sa_info, scopes=GCP_AUTH_SCOPES
                    )
                )
                logger.info("gcp_auth_sa_from_secret_manager")
            except Exception:
                # Fall through to ADC
                self._gcp_credentials, _ = google.auth.default(
                    scopes=GCP_AUTH_SCOPES
                )
                logger.info("gcp_auth_adc_fallback")
        else:
            # Workload Identity / Application Default Credentials
            self._gcp_credentials, _ = google.auth.default(
                scopes=GCP_AUTH_SCOPES
            )
            logger.info("gcp_auth_adc")

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_graph_token(
        self, scopes: Optional[list[str]] = None
    ) -> str:
        """Return a valid Microsoft Graph bearer token, refreshing if needed."""
        resolved_scopes = scopes or GRAPH_APP_SCOPES
        cache_key = "|".join(sorted(resolved_scopes))

        async with self._lock:
            cached = self._graph_token_cache.get(cache_key)
            if cached and not cached.is_expired():
                return cached.access_token

            return await self._acquire_graph_token(resolved_scopes, cache_key)

    async def _acquire_graph_token(
        self, scopes: list[str], cache_key: str
    ) -> str:
        if not self._msal_app:
            raise RuntimeError("MSAL application not initialised")

        result = self._msal_app.acquire_token_for_client(scopes=scopes)

        if "error" in result:
            logger.error(
                "graph_token_acquisition_failed",
                extra={
                    "error": result.get("error"),
                    "description": result.get("error_description"),
                },
            )
            raise RuntimeError(
                f"Graph token acquisition failed: {result.get('error_description')}"
            )

        token = result["access_token"]
        expires_in = result.get("expires_in", 3600)
        self._graph_token_cache[cache_key] = _CachedToken(
            access_token=token,
            expires_at=time.time() + expires_in,
        )
        logger.debug("graph_token_acquired", extra={"expires_in": expires_in})
        return token

    async def get_gcp_credentials(
        self,
    ) -> google.auth.credentials.Credentials:
        """Return refreshed GCP credentials."""
        if not self._gcp_credentials:
            raise RuntimeError("GCP credentials not initialised")

        if self._gcp_credentials.expired or not self._gcp_credentials.token:
            request = google.auth.transport.requests.Request()
            self._gcp_credentials.refresh(request)
            logger.debug("gcp_credentials_refreshed")

        return self._gcp_credentials

    def get_tenant_id(self) -> str:
        """Return the M365 tenant ID (safe to log — not a secret)."""
        if not self._m365_creds:
            raise RuntimeError("M365 credentials not initialised")
        return self._m365_creds.tenant_id

    async def get_graph_headers(
        self, scopes: Optional[list[str]] = None
    ) -> dict[str, str]:
        """Convenience method returning authorization headers for Graph API."""
        token = await self.get_graph_token(scopes)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "ConsistencyLevel": "eventual",
        }
