"""Microsoft Graph API service for Intune device discovery and offboarding.

All endpoints used here are documented in Microsoft Graph v1.0:
https://learn.microsoft.com/en-us/graph/api/resources/intune-graph-overview
"""
from __future__ import annotations

import logging
import time
from typing import Any

import msal
import requests
from flask import current_app

logger = logging.getLogger(__name__)


class GraphAPIError(Exception):
    """Raised when Microsoft Graph returns an error."""


class GraphService:
    """Wrapper around Microsoft Graph endpoints for Intune + AAD."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires: float = 0.0

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> str:
        """Acquire app-only access token via client credentials flow."""
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        app_inst = msal.ConfidentialClientApplication(
            client_id=current_app.config["MS365_CLIENT_ID"],
            client_credential=current_app.config["MS365_CLIENT_SECRET"],
            authority=f"https://login.microsoftonline.com/{current_app.config['MS365_TENANT_ID']}",
        )
        result = app_inst.acquire_token_for_client(scopes=current_app.config["MS365_SCOPES"])
        if "access_token" not in result:
            raise GraphAPIError(
                f"MSAL token acquisition failed: {result.get('error')}: {result.get('error_description')}"
            )
        self._token = result["access_token"]
        self._token_expires = time.time() + int(result.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "ConsistencyLevel": "eventual",
        }

    def _request(self, method: str, path_or_url: str, **kwargs) -> requests.Response:
        if path_or_url.startswith("http"):
            url = path_or_url
        else:
            url = f"{current_app.config['MS365_GRAPH_URL']}{path_or_url}"
        resp = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning("Graph throttled, sleeping %ds", retry_after)
            time.sleep(retry_after)
            return self._request(method, path_or_url, **kwargs)
        if not resp.ok:
            raise GraphAPIError(f"{method} {url} -> {resp.status_code}: {resp.text[:500]}")
        return resp

    def _get_paginated(self, path: str, params: dict | None = None) -> list[dict]:
        results: list[dict] = []
        next_url: str | None = path
        while next_url:
            resp = self._request("GET", next_url, params=params if next_url == path else None)
            data = resp.json()
            results.extend(data.get("value", []))
            next_url = data.get("@odata.nextLink")
        return results

    # ----------------------------------------------------------- discovery
    def discover_managed_devices(self) -> list[dict]:
        """Return all Intune managed devices.

        NOTE: The 'autopilotEnrolled' field does NOT exist on managedDevice.
        Autopilot status is correlated separately via windowsAutopilotDeviceIdentities.
        """
        select = (
            "id,deviceName,serialNumber,operatingSystem,osVersion,"
            "userDisplayName,userPrincipalName,complianceState,"
            "lastSyncDateTime,deviceEnrollmentType,azureADDeviceId,"
            "managedDeviceOwnerType"
        )
        devices = self._get_paginated(
            "/deviceManagement/managedDevices",
            params={"$select": select, "$top": 999},
        )
        logger.info("Discovered %d Intune managed devices", len(devices))
        return devices

    def get_autopilot_devices(self) -> list[dict]:
        """Return all Windows Autopilot device identities."""
        return self._get_paginated(
            "/deviceManagement/windowsAutopilotDeviceIdentities",
            params={"$top": 999},
        )

    def get_users(self) -> list[dict]:
        return self._get_paginated(
            "/users",
            params={"$select": "id,displayName,userPrincipalName,mail,accountEnabled", "$top": 999},
        )

    def get_groups(self) -> list[dict]:
        return self._get_paginated(
            "/groups",
            params={"$select": "id,displayName,mail,mailEnabled,securityEnabled", "$top": 999},
        )

    # ----------------------------------------------------------- offboarding
    def retire_device(self, managed_device_id: str) -> None:
        """POST /deviceManagement/managedDevices/{id}/retire (selective wipe of corp data)."""
        self._request("POST", f"/deviceManagement/managedDevices/{managed_device_id}/retire")
        logger.info("Retire issued for managed device %s", managed_device_id)

    def wipe_device(self, managed_device_id: str, keep_enrollment: bool = False) -> None:
        """POST /deviceManagement/managedDevices/{id}/wipe (factory reset)."""
        body = {"keepEnrollmentData": keep_enrollment, "keepUserData": False}
        self._request("POST", f"/deviceManagement/managedDevices/{managed_device_id}/wipe", json=body)
        logger.info("Wipe issued for managed device %s", managed_device_id)

    def delete_managed_device(self, managed_device_id: str) -> None:
        self._request("DELETE", f"/deviceManagement/managedDevices/{managed_device_id}")
        logger.info("Managed device record %s deleted", managed_device_id)

    def delete_autopilot_device(self, autopilot_id: str) -> None:
        self._request(
            "DELETE",
            f"/deviceManagement/windowsAutopilotDeviceIdentities/{autopilot_id}",
        )
        logger.info("Autopilot device %s deregistered", autopilot_id)

    def delete_aad_device(self, aad_object_id: str) -> None:
        """Removes a device object from Azure AD/Entra.

        Note: pass the AAD device object id, not deviceId.
        """
        self._request("DELETE", f"/devices/{aad_object_id}")
        logger.info("AAD device %s removed", aad_object_id)

    def find_aad_device_by_device_id(self, device_id: str) -> dict | None:
        """Look up the AAD device object by its deviceId (UUID)."""
        try:
            resp = self._request("GET", f"/devices?$filter=deviceId eq '{device_id}'")
            results = resp.json().get("value", [])
            return results[0] if results else None
        except GraphAPIError:
            return None
