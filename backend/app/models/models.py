"""Database models."""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from app import db


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class DeviceOS(PyEnum):
    WINDOWS = "windows"
    MACOS = "macos"
    IOS = "ios"
    ANDROID = "android"
    CHROMEOS = "chromeos"
    UNKNOWN = "unknown"


class DeviceStatus(PyEnum):
    DISCOVERED = "discovered"
    INTUNE_OFFBOARDING = "intune_offboarding"
    INTUNE_OFFBOARDED = "intune_offboarded"
    GOOGLE_PENDING = "google_pending"
    GOOGLE_ENROLLED = "google_enrolled"
    ERROR = "error"


class MigrationPhase(PyEnum):
    PRE_MIGRATION = "pre_migration"
    ENV_PREPARATION = "env_preparation"
    INTUNE_OFFBOARDING = "intune_offboarding"
    GOOGLE_MDM_ONBOARDING = "google_mdm_onboarding"
    MIGRATION_EXECUTION = "migration_execution"
    CUTOVER = "cutover"
    POST_MIGRATION = "post_migration"


class TaskStatus(PyEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    intune_device_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    display_name = db.Column(db.String(255), nullable=False)
    serial_number = db.Column(db.String(255), nullable=True)
    hardware_hash = db.Column(db.Text, nullable=True)
    os_type = db.Column(db.Enum(DeviceOS, name="device_os"), default=DeviceOS.UNKNOWN, nullable=False)
    os_version = db.Column(db.String(100), nullable=True)
    assigned_user = db.Column(db.String(255), nullable=True)
    assigned_user_email = db.Column(db.String(255), nullable=True, index=True)
    compliance_state = db.Column(db.String(50), nullable=True)
    last_sync = db.Column(db.DateTime, nullable=True)
    enrollment_type = db.Column(db.String(100), nullable=True)
    aad_device_id = db.Column(db.String(255), nullable=True)
    autopilot_id = db.Column(db.String(255), nullable=True)
    is_byod = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.Enum(DeviceStatus, name="device_status"), default=DeviceStatus.DISCOVERED, nullable=False)
    google_device_id = db.Column(db.String(255), nullable=True)
    discovered_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "intune_device_id": self.intune_device_id,
            "display_name": self.display_name,
            "serial_number": self.serial_number,
            "os_type": self.os_type.value if self.os_type else None,
            "os_version": self.os_version,
            "assigned_user": self.assigned_user,
            "assigned_user_email": self.assigned_user_email,
            "compliance_state": self.compliance_state,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "enrollment_type": self.enrollment_type,
            "autopilot_enrolled": bool(self.autopilot_id),
            "is_byod": self.is_byod,
            "status": self.status.value if self.status else None,
            "google_device_id": self.google_device_id,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "notes": self.notes,
        }


class MigrationTask(db.Model):
    __tablename__ = "migration_tasks"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    task_number = db.Column(db.String(20), nullable=False, index=True)
    phase = db.Column(db.Enum(MigrationPhase, name="migration_phase"), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    scope = db.Column(db.String(255), nullable=True)
    owner = db.Column(db.String(100), nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    status = db.Column(db.Enum(TaskStatus, name="task_status"), default=TaskStatus.NOT_STARTED, nullable=False)
    progress = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    celery_task_id = db.Column(db.String(255), nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "task_number": self.task_number,
            "phase": self.phase.value if self.phase else None,
            "title": self.title,
            "scope": self.scope,
            "owner": self.owner,
            "priority": self.priority,
            "status": self.status.value if self.status else None,
            "progress": self.progress,
            "notes": self.notes,
            "celery_task_id": self.celery_task_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
        }


class TaskLog(db.Model):
    __tablename__ = "task_logs"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    migration_task_id = db.Column(db.String(36), db.ForeignKey("migration_tasks.id"), nullable=True, index=True)
    device_id = db.Column(db.String(36), db.ForeignKey("devices.id"), nullable=True, index=True)
    level = db.Column(db.String(20), default="INFO", nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=_utcnow, nullable=False, index=True)
    # NOTE: 'metadata' is a reserved attribute on db.Model -> use 'extra_data'
    extra_data = db.Column(db.JSON, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "migration_task_id": self.migration_task_id,
            "device_id": self.device_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "extra_data": self.extra_data,
        }
