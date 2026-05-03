"""Google Workspace Authentication Manager.

Uses a GCP service account with Domain-Wide Delegation (DWD) to impersonate
Workspace users. Credentials are loaded from TenantConfigStore (local JSON,
base64-obfuscated) or from GCP Secret Manager — never hardcoded.

Security notes:
- The service account JSON is decoded in memory only; never written to disk again
- Each user impersonation token is cached and refreshed proactively
- User email addresses are NEVER logged at INFO or above — only at DEBUG
- The DWD service account must be granted delegation in the Google Admin Console
  BEFORE this manager will function (Workspace Admin → Security → API Controls)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

logger = logging.getLogger(__name__)

# GW scopes required for read access to each workload
_GW_SCOPES: dict[str, list[str]] = {
    "gmail": [
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "drive": [
        "https://www.googleapis.com/auth/drive.readonly",
    ],
    "calendar": [
        "https://www.googleapis.com/auth/calendar.readonly",
    ],
    "contacts": [
        "https://www.googleapis.com/auth/contacts.readonly",
    ],
    "chat": [
        "https://www.googleapis.com/auth/chat.messages.readonly",
        "https://www.googleapis.com/auth/chat.spaces.readonly",
    ],
    "admin": [
        "https://www.googleapis.com/auth/admin.directory.user.readonly",
        "https://www.googleapis.com/auth/admin.directory.group.readonly",
    ],
}

_TOKEN_REFRESH_BUFFER = 300  # seconds before expiry to refresh


@dataclass
class _CachedToken:
    credentials: service_account.Credentials
    expires_at: float

    def is_stale(self) -> bool:
        return time.time() >= (self.expires_at - _TOKEN_REFRESH_BUFFER)


class GWAuthManager:
    """Provides impersonated Google Workspace credentials per user + scope.

    Usage::

        gw_auth = await GWAuthManager.create()
        creds = await gw_auth.get_credentials("user@company.com", "gmail")
    """

    def __init__(self, sa_info: dict) -> None:
        # sa_info is the parsed service account JSON — held in memory only
        self._sa_info = sa_info
        # Cache: (subject_email, workload) → _CachedToken
        self._cache: dict[tuple[str, str], _CachedToken] = {}

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    async def create(cls) -> "GWAuthManager":
        """Load SA key from TenantConfigStore or Secret Manager and return instance."""
        sa_info = await cls._load_sa_info()
        instance = cls(sa_info)
        await instance._validate()
        return instance

    @classmethod
    async def _load_sa_info(cls) -> dict:
        """Load service account JSON from TenantConfigStore (preferred) or Secret Manager."""
        from app.setup.tenant_store import get_tenant_store
        from app.config.settings import get_settings

        settings = get_settings()
        store = get_tenant_store()
        config = store.load()

        raw_key = config.get("gw_service_account_json", "")
        if raw_key:
            try:
                sa_info = json.loads(raw_key)
                if "client_email" in sa_info:
                    logger.info("gw_auth_sa_loaded_from_tenant_store")
                    return sa_info
            except (json.JSONDecodeError, KeyError):
                pass

        if settings.use_secret_manager:
            from google.cloud import secretmanager
            from app.constants import SECRET_GW_SA_KEY
            client = secretmanager.SecretManagerServiceClient()
            project_id = settings.gcp.project_id
            name = f"projects/{project_id}/secrets/{SECRET_GW_SA_KEY}/versions/latest"
            try:
                response = client.access_secret_version(request={"name": name})
                raw = response.payload.data.decode("utf-8").strip()
                sa_info = json.loads(raw)
                logger.info("gw_auth_sa_loaded_from_secret_manager")
                return sa_info
            except Exception as exc:
                logger.error("gw_auth_sa_secret_manager_failed", extra={"error": str(exc)})
                raise RuntimeError(
                    "GW service account key not found in TenantConfigStore or Secret Manager. "
                    "Upload the SA JSON in the Tenants Connection UI."
                ) from exc

        raise RuntimeError(
            "No Google Workspace service account configured. "
            "Add the service account JSON in the Tenants Connection UI."
        )

    async def _validate(self) -> None:
        """Verify the service account JSON has the required fields."""
        required = {"type", "project_id", "private_key", "client_email"}
        missing = required - set(self._sa_info.keys())
        if missing:
            raise ValueError(
                f"Invalid service account JSON — missing fields: {missing}"
            )
        if self._sa_info.get("type") != "service_account":
            raise ValueError(
                "Credential type must be 'service_account', "
                f"got '{self._sa_info.get('type')}'"
            )
        logger.info(
            "gw_auth_validated",
            extra={"sa_client_email": self._sa_info["client_email"]},
        )

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_credentials(
        self,
        subject_email: str,
        workload: str,
    ) -> service_account.Credentials:
        """Return refreshed, impersonated credentials for (user, workload).

        :param subject_email: The Google Workspace user to impersonate.
        :param workload: One of gmail / drive / calendar / contacts / chat / admin.
        """
        cache_key = (subject_email, workload)
        cached = self._cache.get(cache_key)
        if cached and not cached.is_stale():
            return cached.credentials

        scopes = _GW_SCOPES.get(workload)
        if not scopes:
            raise ValueError(f"Unknown GW workload '{workload}'")

        creds = service_account.Credentials.from_service_account_info(
            self._sa_info,
            scopes=scopes,
            subject=subject_email,
        )
        request = GoogleAuthRequest()
        creds.refresh(request)

        expires_at = time.time() + (creds.expiry.timestamp() - time.time()
                                    if creds.expiry else 3600)
        self._cache[cache_key] = _CachedToken(
            credentials=creds,
            expires_at=expires_at,
        )
        logger.debug(
            "gw_credentials_refreshed",
            extra={"workload": workload},
            # subject_email intentionally omitted at non-debug levels
        )
        return creds

    async def list_workspace_users(self, admin_email: str) -> list[dict]:
        """Return all active Workspace users via the Admin SDK Directory API.

        Requires: admin scope + DWD configured for admin_email.
        """
        from googleapiclient.discovery import build

        creds = await self.get_credentials(admin_email, "admin")
        service = build("admin", "directory_v1", credentials=creds, cache_discovery=False)

        users: list[dict] = []
        page_token: Optional[str] = None
        domain = self._sa_info.get("project_id", "")

        # Extract customer/domain from client_email if possible
        client_email: str = self._sa_info.get("client_email", "")
        if "@" in client_email:
            domain = client_email.split("@")[1]

        while True:
            result = (
                service.users()
                .list(
                    customer="my_customer",
                    maxResults=500,
                    pageToken=page_token,
                    query="isSuspended=false",
                    projection="basic",
                )
                .execute()
            )
            batch = result.get("users", [])
            users.extend(batch)
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info("gw_users_listed", extra={"count": len(users)})
        return users
