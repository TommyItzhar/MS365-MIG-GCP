"""Azure App Registration automation via Microsoft Graph API.

Requires a delegated access token obtained from a Global Admin
(via device-code or browser interactive flow in the frontend).

Flow:
  1. POST /applications              — create the app registration
  2. POST /applications/{id}/addPassword — create client secret
  3. POST /servicePrincipals         — create service principal
  4. GET  /servicePrincipals?filter  — resolve Graph SP object ID
  5. POST /servicePrincipals/{id}/appRoleAssignments × N — grant each permission

The caller must hold these delegated scopes (granted by a Global Admin):
  Application.ReadWrite.All  AppRoleAssignment.ReadWrite.All
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Microsoft Graph resource app ID — constant across all tenants
_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"

# All application (Role-type) permissions required by the migration engine.
# GUIDs are stable across tenants; sourced from the Microsoft Graph permissions
# reference: https://learn.microsoft.com/graph/permissions-reference
REQUIRED_PERMISSIONS: dict[str, str] = {
    "Mail.Read":                               "810c84a8-4a9e-49e6-bf7d-12d183f40d01",
    "Calendars.Read":                          "798ee544-9d2d-430c-a058-570e29e34338",
    "Contacts.Read":                           "089fe4d0-434a-2a5c-90cb-2b57e6feac6e",
    "Files.Read.All":                          "01d4889c-1287-42c6-ac1f-5d1e02578ef6",
    "Sites.Read.All":                          "332a536c-c7ef-4017-ab91-336970924f0d",
    "Team.ReadBasic.All":                      "2280dda6-0bfd-44ee-a2f4-cb867cfc4c1e",
    "ChannelMessage.Read.All":                 "7b2449af-6ccd-4f98-a5ac-d6886e519ab9",
    "TeamSettings.Read.All":                   "242607bd-1d2c-432c-82eb-bdb27bef7b91",
    "User.Read.All":                           "df021288-bdef-4463-88db-98f22de89214",
    "Group.Read.All":                          "5b567255-7703-4780-807c-7be8301ae99b",
    "Device.Read.All":                         "7438b122-aefc-4978-80ed-43db9064d227",
    "Reports.Read.All":                        "230c1aed-a721-4c5d-9cb4-a90514e508ef",
    "Directory.Read.All":                      "7ab1d382-f21e-4acd-a863-ba3e13f7da61",
    "DeviceManagementManagedDevices.Read.All": "2f51be20-0bb4-4fed-bf7b-db946066c75e",
    "Tasks.ReadWrite.All":                     "f45671fb-e0fe-4b4b-be20-3d3ce43f1bcb",
}


# ── Response / error models ────────────────────────────────────────────────


class AppRegistrationResult(BaseModel):
    """Returned on successful registration."""

    client_id: str
    client_secret: str = Field(..., description="Store immediately — not retrievable later")
    client_secret_expires: str
    object_id: str = Field(..., description="Application object ID in Entra ID")
    service_principal_id: str
    display_name: str
    tenant_id: str
    permissions_granted: bool
    permissions_granted_count: int
    permissions_failed: list[str] = Field(default_factory=list)


class RegistrationStepError(Exception):
    """Raised when a Graph API call fails during registration."""

    def __init__(self, message: str, step: str, http_status: Optional[int] = None):
        super().__init__(message)
        self.step = step
        self.http_status = http_status


# ── Main registrar ─────────────────────────────────────────────────────────


class AzureAppRegistrar:
    """
    Creates an Azure App Registration with all permissions required by the
    migration engine, adds a client secret, creates the service principal,
    and optionally grants admin consent — all via Microsoft Graph.
    """

    def __init__(self, admin_token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        }

    async def register(
        self,
        display_name: str = "MS365-GCP-Migration-Engine",
        secret_display_name: str = "migration-engine-secret",
        secret_years: int = 2,
        grant_admin_consent: bool = True,
    ) -> AppRegistrationResult:
        """Execute the full registration flow and return credentials."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            app = await self._create_application(client, display_name)
            app_id: str = app["appId"]
            object_id: str = app["id"]
            logger.info("Created app registration appId=%s objectId=%s", app_id, object_id)

            secret, secret_expires = await self._add_password(
                client, object_id, secret_display_name, secret_years
            )
            logger.info("Created client secret for appId=%s", app_id)

            sp_id = await self._create_service_principal(client, app_id)
            logger.info("Created service principal id=%s", sp_id)

            granted_count = 0
            failed_perms: list[str] = []
            if grant_admin_consent:
                granted_count, failed_perms = await self._grant_admin_consent(
                    client, sp_id
                )
                logger.info(
                    "Admin consent: granted=%d failed=%d", granted_count, len(failed_perms)
                )

            tenant_id = await self._get_tenant_id(client)

        return AppRegistrationResult(
            client_id=app_id,
            client_secret=secret,
            client_secret_expires=secret_expires,
            object_id=object_id,
            service_principal_id=sp_id,
            display_name=display_name,
            tenant_id=tenant_id,
            permissions_granted=granted_count > 0,
            permissions_granted_count=granted_count,
            permissions_failed=failed_perms,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    async def _create_application(
        self, client: httpx.AsyncClient, display_name: str
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "displayName": display_name,
            "signInAudience": "AzureADMyOrg",
            "requiredResourceAccess": [
                {
                    "resourceAppId": _GRAPH_APP_ID,
                    "resourceAccess": [
                        {"id": guid, "type": "Role"}
                        for guid in REQUIRED_PERMISSIONS.values()
                    ],
                }
            ],
        }
        resp = await client.post(
            f"{_GRAPH_BASE}/applications",
            json=payload,
            headers=self._headers,
        )
        if resp.status_code != 201:
            raise RegistrationStepError(
                f"Failed to create application: {resp.text}",
                step="create_application",
                http_status=resp.status_code,
            )
        return resp.json()  # type: ignore[return-value]

    async def _add_password(
        self,
        client: httpx.AsyncClient,
        object_id: str,
        display_name: str,
        years: int,
    ) -> tuple[str, str]:
        end_dt = (datetime.utcnow() + timedelta(days=365 * years)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload = {
            "passwordCredential": {
                "displayName": display_name,
                "endDateTime": end_dt,
            }
        }
        resp = await client.post(
            f"{_GRAPH_BASE}/applications/{object_id}/addPassword",
            json=payload,
            headers=self._headers,
        )
        if resp.status_code != 200:
            raise RegistrationStepError(
                f"Failed to add password credential: {resp.text}",
                step="add_password",
                http_status=resp.status_code,
            )
        data = resp.json()
        return data["secretText"], data.get("endDateTime", end_dt)

    async def _create_service_principal(
        self, client: httpx.AsyncClient, app_id: str
    ) -> str:
        resp = await client.post(
            f"{_GRAPH_BASE}/servicePrincipals",
            json={"appId": app_id},
            headers=self._headers,
        )
        if resp.status_code not in (200, 201):
            raise RegistrationStepError(
                f"Failed to create service principal: {resp.text}",
                step="create_service_principal",
                http_status=resp.status_code,
            )
        return resp.json()["id"]  # type: ignore[return-value]

    async def _grant_admin_consent(
        self, client: httpx.AsyncClient, sp_id: str
    ) -> tuple[int, list[str]]:
        """Assign all app roles to the service principal (admin consent).

        Returns (granted_count, failed_permission_names).
        """
        # Resolve the Microsoft Graph service principal for this tenant
        resp = await client.get(
            f"{_GRAPH_BASE}/servicePrincipals",
            params={"$filter": f"appId eq '{_GRAPH_APP_ID}'", "$select": "id"},
            headers=self._headers,
        )
        if resp.status_code != 200:
            logger.warning("Cannot resolve Graph SP for admin consent: %s", resp.text)
            return 0, list(REQUIRED_PERMISSIONS.keys())

        results = resp.json().get("value", [])
        if not results:
            logger.warning("Microsoft Graph service principal not found in tenant")
            return 0, list(REQUIRED_PERMISSIONS.keys())

        graph_sp_id: str = results[0]["id"]
        granted = 0
        failed: list[str] = []

        for perm_name, role_id in REQUIRED_PERMISSIONS.items():
            assign_resp = await client.post(
                f"{_GRAPH_BASE}/servicePrincipals/{sp_id}/appRoleAssignments",
                json={
                    "principalId": sp_id,
                    "resourceId": graph_sp_id,
                    "appRoleId": role_id,
                },
                headers=self._headers,
            )
            if assign_resp.status_code in (200, 201):
                granted += 1
                logger.debug("Granted application permission: %s", perm_name)
            else:
                failed.append(perm_name)
                logger.warning(
                    "Could not grant %s (HTTP %s): %s",
                    perm_name,
                    assign_resp.status_code,
                    assign_resp.text,
                )

        return granted, failed

    async def _get_tenant_id(self, client: httpx.AsyncClient) -> str:
        resp = await client.get(
            f"{_GRAPH_BASE}/organization",
            params={"$select": "id,displayName"},
            headers=self._headers,
        )
        if resp.status_code == 200:
            orgs = resp.json().get("value", [])
            if orgs:
                return orgs[0].get("id", "")
        return ""


# ── Credential validation helper ───────────────────────────────────────────


class CredentialValidator:
    """Tests whether stored M365 + GCP credentials are functional."""

    @staticmethod
    async def validate_m365(
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Acquire an app-only token and call /organization.

        Returns (ok, org_display_name, error_message).
        """
        import msal

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "error" in result:
            error = result.get("error_description", result.get("error", "unknown"))
            return False, None, error

        token = result["access_token"]
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/organization",
                params={"$select": "id,displayName"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                return False, None, f"Graph /organization returned HTTP {resp.status_code}"
            orgs = resp.json().get("value", [])
            org_name = orgs[0].get("displayName") if orgs else None
            return True, org_name, None

    @staticmethod
    async def validate_gcp(project_id: str) -> tuple[bool, Optional[str]]:
        """Verify GCP credentials can reach the project.

        Returns (ok, error_message).
        """
        try:
            import google.auth
            import google.auth.transport.requests

            credentials, detected_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
            return True, None
        except Exception as exc:
            return False, str(exc)
