"""Health check and Prometheus metrics endpoint."""
from flask import Blueprint, jsonify, Response

from app import db

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    db_status = "ok"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
    return jsonify({"status": "ok", "db": db_status, "version": "1.0.0"})


@bp.get("/metrics")
def metrics():
    """Prometheus text-format metrics."""
    from app.models.models import Device, DeviceStatus, MigrationTask, TaskStatus

    total_devices = Device.query.count()
    enrolled_google = Device.query.filter_by(status=DeviceStatus.GOOGLE_ENROLLED).count()
    offboarded_intune = Device.query.filter(Device.status.in_([
        DeviceStatus.INTUNE_OFFBOARDED,
        DeviceStatus.GOOGLE_PENDING,
        DeviceStatus.GOOGLE_ENROLLED,
    ])).count()
    devices_in_error = Device.query.filter_by(status=DeviceStatus.ERROR).count()

    tasks_total = MigrationTask.query.count()
    tasks_completed = MigrationTask.query.filter_by(status=TaskStatus.COMPLETED).count()
    tasks_failed = MigrationTask.query.filter_by(status=TaskStatus.FAILED).count()
    tasks_in_progress = MigrationTask.query.filter_by(status=TaskStatus.IN_PROGRESS).count()

    body = (
        f"# HELP migration_devices_total Total devices discovered\n"
        f"# TYPE migration_devices_total gauge\n"
        f"migration_devices_total {total_devices}\n"
        f"# HELP migration_devices_google_enrolled Devices enrolled in Google MDM\n"
        f"# TYPE migration_devices_google_enrolled gauge\n"
        f"migration_devices_google_enrolled {enrolled_google}\n"
        f"# HELP migration_devices_intune_offboarded Devices offboarded from Intune\n"
        f"# TYPE migration_devices_intune_offboarded gauge\n"
        f"migration_devices_intune_offboarded {offboarded_intune}\n"
        f"# HELP migration_devices_error Devices in error state\n"
        f"# TYPE migration_devices_error gauge\n"
        f"migration_devices_error {devices_in_error}\n"
        f"# HELP migration_tasks_total Total migration tasks\n"
        f"# TYPE migration_tasks_total gauge\n"
        f"migration_tasks_total {tasks_total}\n"
        f"# HELP migration_tasks_completed Completed migration tasks\n"
        f"# TYPE migration_tasks_completed gauge\n"
        f"migration_tasks_completed {tasks_completed}\n"
        f"# HELP migration_tasks_failed Failed migration tasks\n"
        f"# TYPE migration_tasks_failed gauge\n"
        f"migration_tasks_failed {tasks_failed}\n"
        f"# HELP migration_tasks_in_progress In-progress migration tasks\n"
        f"# TYPE migration_tasks_in_progress gauge\n"
        f"migration_tasks_in_progress {tasks_in_progress}\n"
    )
    return Response(body, mimetype="text/plain; version=0.0.4")
