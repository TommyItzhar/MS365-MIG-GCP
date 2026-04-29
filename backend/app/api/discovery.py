"""Discovery API endpoints."""
from flask import Blueprint, jsonify
from sqlalchemy import func

from app import db
from app.models.models import Device, DeviceOS, DeviceStatus, MigrationPhase, MigrationTask, TaskStatus
from app.services.tasks import discover_devices

bp = Blueprint("discovery", __name__)


@bp.post("/run")
def run_discovery():
    task = MigrationTask.query.filter_by(task_number="1.3").first()
    if not task:
        task = MigrationTask(
            task_number="1.3",
            phase=MigrationPhase.PRE_MIGRATION,
            title="Run device discovery scan",
            owner="IT Admin",
            scope="All managed devices",
            priority="High",
        )
        db.session.add(task)
        db.session.commit()

    task.status = TaskStatus.IN_PROGRESS
    task.progress = 0
    task.error_message = None
    db.session.commit()

    async_result = discover_devices.delay(task.id)
    task.celery_task_id = async_result.id
    db.session.commit()

    return jsonify({"task_id": task.id, "celery_task_id": async_result.id}), 202


@bp.get("/summary")
def discovery_summary():
    total = Device.query.count()
    by_os = (
        db.session.query(Device.os_type, func.count(Device.id))
        .group_by(Device.os_type).all()
    )
    by_status = (
        db.session.query(Device.status, func.count(Device.id))
        .group_by(Device.status).all()
    )
    autopilot_count = Device.query.filter(Device.autopilot_id.isnot(None)).count()
    byod_count = Device.query.filter_by(is_byod=True).count()

    return jsonify({
        "total_devices": total,
        "autopilot_devices": autopilot_count,
        "byod_devices": byod_count,
        "by_os": {(k.value if k else "unknown"): v for k, v in by_os},
        "by_status": {(k.value if k else "unknown"): v for k, v in by_status},
    })
