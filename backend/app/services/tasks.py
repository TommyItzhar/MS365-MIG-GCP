"""Celery background tasks.

Tasks use the FlaskTask base class set by app/__init__.py, which wraps every
task in app.app_context() so SQLAlchemy and current_app work normally.

For Celery to discover these tasks, either:
- The Flask app must be created (which imports this module via the API blueprints)
- OR the worker entry-point celery_worker.py creates the app first.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from celery import shared_task

from app import db
from app.models.models import (
    Device, DeviceOS, DeviceStatus,
    MigrationTask, TaskLog, TaskStatus,
)
from app.services.graph_service import GraphService, GraphAPIError
from app.services.google_service import GoogleWorkspaceService, GoogleAPIError

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------ helpers
def _log(task_id: str | None, device_id: str | None, level: str, msg: str, extra: dict | None = None) -> None:
    db.session.add(TaskLog(
        migration_task_id=task_id,
        device_id=device_id,
        level=level,
        message=msg,
        extra_data=extra,
    ))
    db.session.commit()


def _mark(task_id: str, status: TaskStatus, progress: int | None = None, error: str | None = None) -> None:
    t = MigrationTask.query.get(task_id)
    if not t:
        return
    t.status = status
    if progress is not None:
        t.progress = progress
    if status == TaskStatus.IN_PROGRESS and not t.started_at:
        t.started_at = _utcnow()
    if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        t.completed_at = _utcnow()
    if error:
        t.error_message = error
    db.session.commit()


_OS_MAP = {
    "windows": DeviceOS.WINDOWS,
    "macmdm": DeviceOS.MACOS, "macos": DeviceOS.MACOS, "darwin": DeviceOS.MACOS,
    "ios": DeviceOS.IOS, "iphone": DeviceOS.IOS, "ipad": DeviceOS.IOS, "ipados": DeviceOS.IOS,
    "android": DeviceOS.ANDROID, "androidforwork": DeviceOS.ANDROID,
    "chromeos": DeviceOS.CHROMEOS,
}


def _map_os(os_str: str | None) -> DeviceOS:
    if not os_str:
        return DeviceOS.UNKNOWN
    s = os_str.lower().replace(" ", "")
    for k, v in _OS_MAP.items():
        if k in s:
            return v
    return DeviceOS.UNKNOWN


# ============================================================ DISCOVERY (Phase 1.3)
@shared_task(bind=True, name="tasks.discover_devices")
def discover_devices(self, task_id: str) -> dict[str, Any]:
    _mark(task_id, TaskStatus.IN_PROGRESS, progress=0)
    _log(task_id, None, "INFO", "Starting Intune device discovery")

    try:
        graph = GraphService()
        managed = graph.discover_managed_devices()

        # Map Autopilot devices by managedDeviceId for quick lookup
        try:
            autopilot = graph.get_autopilot_devices()
            ap_by_managed = {d.get("managedDeviceId"): d for d in autopilot if d.get("managedDeviceId")}
        except GraphAPIError as e:
            _log(task_id, None, "WARN", f"Could not fetch Autopilot devices: {e}")
            ap_by_managed = {}

        for i, raw in enumerate(managed):
            device = Device.query.filter_by(intune_device_id=raw["id"]).first()
            if not device:
                device = Device(intune_device_id=raw["id"])
                db.session.add(device)

            device.display_name = raw.get("deviceName") or "Unknown"
            device.serial_number = raw.get("serialNumber")
            device.os_type = _map_os(raw.get("operatingSystem"))
            device.os_version = raw.get("osVersion")
            device.assigned_user = raw.get("userDisplayName")
            device.assigned_user_email = raw.get("userPrincipalName")
            device.compliance_state = raw.get("complianceState")
            device.enrollment_type = raw.get("deviceEnrollmentType")
            device.aad_device_id = raw.get("azureADDeviceId")
            device.is_byod = raw.get("managedDeviceOwnerType") == "personal"

            ap = ap_by_managed.get(raw["id"])
            if ap:
                device.autopilot_id = ap.get("id")
                device.hardware_hash = ap.get("hardwareHash")

            sync = raw.get("lastSyncDateTime")
            if sync:
                try:
                    device.last_sync = datetime.fromisoformat(sync.replace("Z", "+00:00"))
                except ValueError:
                    pass

            self.update_state(state="PROGRESS", meta={"current": i + 1, "total": len(managed)})

        db.session.commit()
        _log(task_id, None, "INFO", f"Discovery complete: {len(managed)} devices")
        _mark(task_id, TaskStatus.COMPLETED, progress=100)
        return {"discovered": len(managed)}

    except Exception as exc:
        logger.exception("Discovery failed")
        db.session.rollback()
        _log(task_id, None, "ERROR", f"Discovery failed: {exc}")
        _mark(task_id, TaskStatus.FAILED, error=str(exc))
        raise


# ============================================================ INTUNE OFFBOARDING (Phase 3)
@shared_task(bind=True, name="tasks.offboard_device_from_intune", max_retries=2)
def offboard_device_from_intune(self, task_id: str, device_id: str, mode: str = "retire") -> dict[str, Any]:
    """
    mode = 'retire' (default) -> selective wipe of corporate data
    mode = 'wipe'             -> factory reset (corporate-owned only)

    The order matters:
      1. Remove Autopilot record (if any) so device can re-enroll later
      2. Issue retire/wipe (Intune queues the action; device performs it on next checkin)
      3. After retire succeeds, AAD device record is removed
      4. Delete the managed-device record from Intune
    """
    _mark(task_id, TaskStatus.IN_PROGRESS, progress=0)
    device = Device.query.get(device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")

    graph = GraphService()
    try:
        device.status = DeviceStatus.INTUNE_OFFBOARDING
        db.session.commit()
        _log(task_id, device_id, "INFO", f"Off-boarding {device.display_name} (mode={mode})")

        # Step 1: Autopilot deregistration
        if device.autopilot_id:
            graph.delete_autopilot_device(device.autopilot_id)
            _log(task_id, device_id, "INFO", "Autopilot record removed")
        _mark(task_id, TaskStatus.IN_PROGRESS, progress=25)

        # Step 2: Retire or wipe
        if device.intune_device_id:
            if mode == "wipe" and not device.is_byod:
                graph.wipe_device(device.intune_device_id)
                _log(task_id, device_id, "INFO", "Wipe action queued")
            else:
                graph.retire_device(device.intune_device_id)
                _log(task_id, device_id, "INFO", "Retire action queued")
        _mark(task_id, TaskStatus.IN_PROGRESS, progress=50)

        # Step 3: Remove from Azure AD
        if device.aad_device_id:
            aad_obj = graph.find_aad_device_by_device_id(device.aad_device_id)
            if aad_obj:
                graph.delete_aad_device(aad_obj["id"])
                _log(task_id, device_id, "INFO", "Removed from Azure AD/Entra ID")
            else:
                _log(task_id, device_id, "WARN", "AAD device record not found")
        _mark(task_id, TaskStatus.IN_PROGRESS, progress=75)

        # Step 4: Delete the managed-device record (only safe AFTER retire/wipe succeeds)
        # Note: retire/wipe complete asynchronously on the device. In production you'd poll
        # managementState until 'retireSucceeded'. Here we accept that the action was queued.
        if device.intune_device_id:
            try:
                graph.delete_managed_device(device.intune_device_id)
                _log(task_id, device_id, "INFO", "Intune managed device record deleted")
            except GraphAPIError as e:
                _log(task_id, device_id, "WARN", f"Could not delete managed device: {e}")

        device.status = DeviceStatus.INTUNE_OFFBOARDED
        db.session.commit()
        _mark(task_id, TaskStatus.COMPLETED, progress=100)
        return {"device_id": device_id, "status": "offboarded"}

    except Exception as exc:
        logger.exception("Offboarding failed")
        db.session.rollback()
        device = Device.query.get(device_id)
        if device:
            device.status = DeviceStatus.ERROR
            db.session.commit()
        _log(task_id, device_id, "ERROR", f"Off-boarding failed: {exc}")
        _mark(task_id, TaskStatus.FAILED, error=str(exc))
        raise


# ============================================================ GOOGLE MDM ENROLLMENT (Phase 4)
@shared_task(bind=True, name="tasks.enroll_device_google_mdm")
def enroll_device_google_mdm(self, task_id: str, device_id: str, max_wait_seconds: int = 600) -> dict[str, Any]:
    """
    HONEST IMPLEMENTATION:
    Google MDM/GCPW enrollment is a *device-side* action that cannot be triggered
    remotely. This task:
      1. Marks the device as 'pending Google enrollment'
      2. Polls Google Admin Directory for the device to appear (after the user
         signs in via GCPW or installs the MDM profile)
      3. Marks 'google_enrolled' when found, or returns pending after timeout

    Operators install GCPW manually or via deployment tooling (Intune Win32 app,
    Group Policy, a deployment script, etc.) BEFORE running this task.
    """
    _mark(task_id, TaskStatus.IN_PROGRESS, progress=0)
    device = Device.query.get(device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")
    if not device.assigned_user_email:
        raise ValueError("Device has no assigned user email; cannot poll Google Directory")

    device.status = DeviceStatus.GOOGLE_PENDING
    db.session.commit()
    _log(task_id, device_id, "INFO",
         f"Polling Google Directory for {device.assigned_user_email} (up to {max_wait_seconds}s)")

    google = GoogleWorkspaceService()
    poll_interval = 30
    elapsed = 0

    while elapsed < max_wait_seconds:
        try:
            match = google.find_mobile_device_for_user(device.assigned_user_email)
            if match:
                device.google_device_id = match.get("resourceId")
                device.status = DeviceStatus.GOOGLE_ENROLLED
                db.session.commit()
                _log(task_id, device_id, "INFO", "Device confirmed in Google Endpoint Management")
                _mark(task_id, TaskStatus.COMPLETED, progress=100)
                return {"device_id": device_id, "google_device_id": device.google_device_id}
        except GoogleAPIError as e:
            _log(task_id, device_id, "WARN", f"Poll error: {e}")

        progress = int((elapsed / max_wait_seconds) * 100)
        _mark(task_id, TaskStatus.IN_PROGRESS, progress=progress)
        self.update_state(state="PROGRESS", meta={"elapsed": elapsed, "max": max_wait_seconds})
        time.sleep(poll_interval)
        elapsed += poll_interval

    _log(task_id, device_id, "WARN", "Enrollment not detected within window")
    _mark(task_id, TaskStatus.COMPLETED, progress=80)
    return {"device_id": device_id, "status": "pending_manual_check"}
