"""Device management API."""
from flask import Blueprint, jsonify, request
from sqlalchemy import or_

from app import db
from app.models.models import (
    Device, DeviceOS, DeviceStatus,
    MigrationPhase, MigrationTask, TaskStatus,
)
from app.services.tasks import enroll_device_google_mdm, offboard_device_from_intune

bp = Blueprint("devices", __name__)


@bp.get("/")
def list_devices():
    os_filter = request.args.get("os")
    status_filter = request.args.get("status")
    search = request.args.get("q")
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 50)), 1), 200)

    q = Device.query
    if os_filter:
        try:
            q = q.filter(Device.os_type == DeviceOS(os_filter))
        except ValueError:
            return jsonify({"error": f"invalid os filter: {os_filter}"}), 400
    if status_filter:
        try:
            q = q.filter(Device.status == DeviceStatus(status_filter))
        except ValueError:
            return jsonify({"error": f"invalid status filter: {status_filter}"}), 400
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            Device.display_name.ilike(like),
            Device.assigned_user_email.ilike(like),
            Device.serial_number.ilike(like),
        ))

    pagination = q.order_by(Device.display_name).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "devices": [d.to_dict() for d in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages,
    })


@bp.get("/<device_id>")
def get_device(device_id: str):
    device = Device.query.get(device_id)
    if not device:
        return jsonify({"error": "Device not found"}), 404
    return jsonify(device.to_dict())


@bp.post("/offboard")
def offboard_devices():
    """Bulk offboard devices from Intune.

    Body: {"device_ids": [...], "all": false, "mode": "retire"|"wipe"}
    If all=true, all devices currently in 'discovered' status are offboarded.
    """
    data = request.get_json(silent=True) or {}
    device_ids = data.get("device_ids", [])
    do_all = bool(data.get("all", False))
    mode = data.get("mode", "retire")
    if mode not in ("retire", "wipe"):
        return jsonify({"error": "mode must be 'retire' or 'wipe'"}), 400

    if do_all:
        device_ids = [
            d.id for d in Device.query.filter_by(status=DeviceStatus.DISCOVERED).all()
        ]

    if not device_ids:
        return jsonify({"error": "No devices specified"}), 400

    launched = []
    for did in device_ids:
        device = Device.query.get(did)
        if not device:
            continue
        task = MigrationTask(
            task_number=f"3.x-{did[:8]}",
            phase=MigrationPhase.INTUNE_OFFBOARDING,
            title=f"Off-board {device.display_name}",
            owner="IT Admin",
            scope="Intune",
            priority="High",
        )
        db.session.add(task)
        db.session.commit()
        async_result = offboard_device_from_intune.delay(task.id, did, mode)
        task.celery_task_id = async_result.id
        db.session.commit()
        launched.append({"device_id": did, "task_id": task.id, "celery_id": async_result.id})

    return jsonify({"launched": launched, "count": len(launched)}), 202


@bp.post("/enroll-google")
def enroll_google():
    """Bulk Google MDM enrollment polling.

    Note: GCPW or MDM profile install must happen on the device itself.
    """
    data = request.get_json(silent=True) or {}
    device_ids = data.get("device_ids", [])
    do_all = bool(data.get("all", False))

    if do_all:
        device_ids = [
            d.id for d in Device.query.filter_by(status=DeviceStatus.INTUNE_OFFBOARDED).all()
        ]

    if not device_ids:
        return jsonify({"error": "No devices specified"}), 400

    launched = []
    for did in device_ids:
        device = Device.query.get(did)
        if not device:
            continue
        task = MigrationTask(
            task_number=f"4.x-{did[:8]}",
            phase=MigrationPhase.GOOGLE_MDM_ONBOARDING,
            title=f"Track Google MDM enrollment for {device.display_name}",
            owner="Cloud Admin",
            scope="Google Endpoint Management",
            priority="High",
        )
        db.session.add(task)
        db.session.commit()
        async_result = enroll_device_google_mdm.delay(task.id, did)
        task.celery_task_id = async_result.id
        db.session.commit()
        launched.append({"device_id": did, "task_id": task.id, "celery_id": async_result.id})

    return jsonify({"launched": launched, "count": len(launched)}), 202
