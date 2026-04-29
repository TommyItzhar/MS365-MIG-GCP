"""Google Workspace Admin SDK service.

Uses domain-wide delegation. Read endpoints used here are documented at:
https://developers.google.com/admin-sdk/directory/reference/rest

IMPORTANT: device-side enrollment (GCPW for Windows, MDM profiles for macOS/iOS,
Android Enterprise) cannot be triggered remotely via API alone. The platform
prepares enrollment tokens / installer scripts and tracks completion as
devices appear in Google Endpoint Management.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GoogleAPIError(Exception):
    pass


class GoogleWorkspaceService:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def _credentials(self, subject: str | None = None):
        sa_path = current_app.config["GOOGLE_SA_KEY_PATH"]
        creds = service_account.Credentials.from_service_account_file(
            sa_path, scopes=current_app.config["GOOGLE_SCOPES"],
        )
        impersonate = subject or current_app.config.get("GOOGLE_SUPER_ADMIN")
        if impersonate:
            creds = creds.with_subject(impersonate)
        return creds

    def _admin_directory(self):
        if "directory" not in self._cache:
            self._cache["directory"] = build(
                "admin", "directory_v1", credentials=self._credentials(), cache_discovery=False,
            )
        return self._cache["directory"]

    def _admin_reports(self):
        if "reports" not in self._cache:
            self._cache["reports"] = build(
                "admin", "reports_v1", credentials=self._credentials(), cache_discovery=False,
            )
        return self._cache["reports"]

    # ------------------------------------------------------------ users/groups
    def list_users(self) -> list[dict]:
        try:
            svc = self._admin_directory()
            users: list[dict] = []
            token: str | None = None
            while True:
                resp = svc.users().list(
                    domain=current_app.config["GOOGLE_DOMAIN"],
                    maxResults=500, orderBy="email", pageToken=token,
                ).execute()
                users.extend(resp.get("users", []))
                token = resp.get("nextPageToken")
                if not token:
                    break
            return users
        except HttpError as e:
            raise GoogleAPIError(f"list_users failed: {e}") from e

    def list_groups(self) -> list[dict]:
        try:
            svc = self._admin_directory()
            groups: list[dict] = []
            token: str | None = None
            while True:
                resp = svc.groups().list(
                    domain=current_app.config["GOOGLE_DOMAIN"],
                    maxResults=200, pageToken=token,
                ).execute()
                groups.extend(resp.get("groups", []))
                token = resp.get("nextPageToken")
                if not token:
                    break
            return groups
        except HttpError as e:
            raise GoogleAPIError(f"list_groups failed: {e}") from e

    # ------------------------------------------------------------ devices
    def list_mobile_devices(self) -> list[dict]:
        try:
            svc = self._admin_directory()
            out: list[dict] = []
            token: str | None = None
            while True:
                resp = svc.mobiledevices().list(
                    customerId="my_customer", maxResults=100, pageToken=token,
                ).execute()
                out.extend(resp.get("mobiledevices", []))
                token = resp.get("nextPageToken")
                if not token:
                    break
            return out
        except HttpError as e:
            raise GoogleAPIError(f"list_mobile_devices failed: {e}") from e

    def list_chrome_devices(self) -> list[dict]:
        try:
            svc = self._admin_directory()
            out: list[dict] = []
            token: str | None = None
            while True:
                resp = svc.chromeosdevices().list(
                    customerId="my_customer", maxResults=100, pageToken=token,
                ).execute()
                out.extend(resp.get("chromeosdevices", []))
                token = resp.get("nextPageToken")
                if not token:
                    break
            return out
        except HttpError as e:
            raise GoogleAPIError(f"list_chrome_devices failed: {e}") from e

    def find_mobile_device_for_user(self, user_email: str) -> dict | None:
        """Find a Google-managed mobile device matching this user."""
        for d in self.list_mobile_devices():
            emails = d.get("email", []) or []
            if any(e.lower() == user_email.lower() for e in emails):
                return d
        return None

    # ------------------------------------------------------------ healthcheck
    def validate_connectivity(self) -> dict:
        try:
            users = self.list_users()
            return {"status": "ok", "user_count": len(users)}
        except GoogleAPIError as e:
            return {"status": "error", "detail": str(e)}
