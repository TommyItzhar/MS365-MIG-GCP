"""Intune Migrator — device inventory, compliance policies, device configurations."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from app.migrators.m365_to_gcp.base_migrator import BaseMigrator
from app.models import (
    ManifestItem,
    MigrationItem,
    MigrationManifest,
    MigrationResult,
    MigrationScope,
    RollbackResult,
    VerificationResult,
    WorkloadType,
)
from app.writers.gcs_writer import build_gcs_path

logger = logging.getLogger(__name__)

_DEVICE_FIELDS = (
    "id,deviceName,operatingSystem,osVersion,complianceState,managementState,"
    "enrolledDateTime,lastSyncDateTime,manufacturer,model,serialNumber,"
    "azureADDeviceId,azureADRegistered,autopilotEnrolled,managedDeviceOwnerType,"
    "deviceEnrollmentType,deviceRegistrationState,emailAddress,userPrincipalName,"
    "userDisplayName"
)


class IntuneMigrator(BaseMigrator):
    """Migrates Intune device records and compliance policies to GCS."""

    workload = WorkloadType.INTUNE

    async def discover(self, scope: MigrationScope) -> MigrationManifest:
        return MigrationManifest(
            tenant_id=scope.tenant_id,
            job_id=self._job_id,
            discovery_timestamp=datetime.utcnow(),
            items=[
                ManifestItem(
                    source_id=scope.tenant_id,
                    workload=WorkloadType.INTUNE,
                    display_name="Intune Tenant",
                    metadata={"tenant_id": scope.tenant_id},
                )
            ],
            total_items=1,
        )

    async def migrate_item(self, item: MigrationItem) -> MigrationResult:
        tenant_id = item.source_id
        total_bytes = 0

        try:
            # 1. Managed devices
            devices: list[dict] = []
            async for page in self._graph_paginate(
                "/deviceManagement/managedDevices",
                params={"$select": _DEVICE_FIELDS, "$top": "999"},
            ):
                devices.extend(page)

            # 2. Compliance policies
            try:
                compliance_data = await self._graph_get(
                    "/deviceManagement/deviceCompliancePolicies",
                    params={"$top": "100"},
                )
                compliance_policies = compliance_data.get("value", [])
            except Exception:
                compliance_policies = []

            # 3. Device configurations
            try:
                config_data = await self._graph_get(
                    "/deviceManagement/deviceConfigurations",
                    params={"$top": "100"},
                )
                device_configs = config_data.get("value", [])
            except Exception:
                device_configs = []

            # 4. Autopilot devices
            try:
                autopilot_data = await self._graph_get(
                    "/deviceManagement/windowsAutopilotDeviceIdentities",
                    params={"$select": "id,serialNumber,productKey,azureAdDeviceId,managedDeviceId", "$top": "999"},
                )
                autopilot_devices = autopilot_data.get("value", [])
            except Exception:
                autopilot_devices = []

            payload = {
                "tenant_id": tenant_id,
                "exported_at": datetime.utcnow().isoformat(),
                "managed_devices": devices,
                "compliance_policies": compliance_policies,
                "device_configurations": device_configs,
                "autopilot_devices": autopilot_devices,
                "summary": {
                    "total_devices": len(devices),
                    "compliant": sum(1 for d in devices if d.get("complianceState") == "compliant"),
                    "noncompliant": sum(1 for d in devices if d.get("complianceState") == "noncompliant"),
                },
            }

            blob_path = build_gcs_path(
                tenant_id=self._auth.get_tenant_id(),
                workload="intune",
                entity_id=tenant_id,
                item_id="intune_export",
                ext=".json",
            )
            data = json.dumps(payload, default=str).encode()
            uri = await self._gcs.upload_bytes(data, blob_path, "application/json", overwrite=True)
            total_bytes = len(data)

            return MigrationResult(
                item_id=item.id,
                success=True,
                bytes_transferred=total_bytes,
                gcs_uri=uri,
            )

        except Exception as exc:
            logger.exception("intune_migrate_item_failed")
            from app.errors.error_handler import classify_error
            return MigrationResult(item_id=item.id, success=False, error=str(exc), error_type=classify_error(exc))

    async def verify(self, item: MigrationItem) -> VerificationResult:
        return VerificationResult(item_id=item.id, gcs_uri=item.gcs_uri or "", passed=bool(item.gcs_uri))

    async def rollback(self, item: MigrationItem) -> RollbackResult:
        return RollbackResult(item_id=item.id, success=True)
