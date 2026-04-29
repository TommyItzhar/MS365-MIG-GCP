"""Shared Pydantic data models for the migration engine."""
from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────── #
# Enumerations
# ─────────────────────────────────────────────────────────────────────────── #


class WorkloadType(str, Enum):
    EXCHANGE = "exchange"
    ONEDRIVE = "onedrive"
    SHAREPOINT = "sharepoint"
    TEAMS = "teams"
    TEAMS_CHAT = "teams_chat"
    GROUPS = "groups"
    IDENTITY = "identity"
    INTUNE = "intune"
    POWER_AUTOMATE = "power_automate"
    FORMS = "forms"
    PLANNER = "planner"


class ItemState(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class MigrationJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorType(str, Enum):
    THROTTLE = "throttle"
    AUTH_FAILURE = "auth_failure"
    ITEM_TOO_LARGE = "item_too_large"
    API_UNAVAILABLE = "api_unavailable"
    PERMISSION_DENIED = "permission_denied"
    DATA_CORRUPTION = "data_corruption"
    NETWORK_ERROR = "network_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    ITEM_NOT_FOUND = "item_not_found"
    UNKNOWN = "unknown"


class MigrationWave(str, Enum):
    PILOT = "pilot"
    WAVE_1 = "wave_1"
    WAVE_2 = "wave_2"
    FULL = "full"


# ─────────────────────────────────────────────────────────────────────────── #
# Core migration item models
# ─────────────────────────────────────────────────────────────────────────── #


class MigrationItem(BaseModel):
    """Represents a single migrateable object."""

    id: str
    job_id: str
    workload: WorkloadType
    source_id: str
    source_path: str
    tenant_id: str
    user_id: Optional[str] = None
    site_id: Optional[str] = None
    estimated_bytes: int = 0
    content_hash: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: ItemState = ItemState.PENDING
    retry_count: int = 0
    error_message: Optional[str] = None
    error_type: Optional[ErrorType] = None
    checkpoint_data: dict[str, Any] = Field(default_factory=dict)
    gcs_uri: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MigrationResult(BaseModel):
    """Result of migrating a single item."""

    item_id: str
    success: bool
    bytes_transferred: int = 0
    gcs_uri: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[ErrorType] = None
    duration_seconds: float = 0.0
    checksum_verified: bool = False


class BatchResult(BaseModel):
    """Aggregated result for a batch migration run."""

    job_id: str
    workload: WorkloadType
    successful: list[MigrationResult] = Field(default_factory=list)
    failed: list[MigrationResult] = Field(default_factory=list)
    total_bytes: int = 0

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed)


# ─────────────────────────────────────────────────────────────────────────── #
# Scoping, manifest, and checkpointing
# ─────────────────────────────────────────────────────────────────────────── #


class MigrationScope(BaseModel):
    """Defines the scope of a migration job."""

    tenant_id: str
    workloads: list[WorkloadType]
    user_filter: Optional[list[str]] = None
    site_filter: Optional[list[str]] = None
    group_filter: Optional[list[str]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    include_versions: bool = True
    include_permissions: bool = True
    wave: MigrationWave = MigrationWave.FULL


class ManifestItem(BaseModel):
    """Lightweight discovery item before full migration item is created."""

    source_id: str
    workload: WorkloadType
    display_name: str
    estimated_bytes: int = 0
    item_count: int = 0
    owner_upn: Optional[str] = None
    url: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MigrationManifest(BaseModel):
    """Full tenant discovery manifest produced before migration begins."""

    tenant_id: str
    job_id: str
    discovery_timestamp: datetime
    items: list[ManifestItem] = Field(default_factory=list)
    total_bytes: int = 0
    total_items: int = 0
    workload_summary: dict[str, dict[str, int]] = Field(default_factory=dict)


class Checkpoint(BaseModel):
    """Persisted state for resuming a workload after crash or pause."""

    job_id: str
    workload: WorkloadType
    entity_id: str
    last_processed_id: str
    delta_token: Optional[str] = None
    delta_token_created_at: Optional[datetime] = None
    processed_count: int = 0
    failed_count: int = 0
    bytes_transferred: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────── #
# Verification
# ─────────────────────────────────────────────────────────────────────────── #


class VerificationResult(BaseModel):
    """Result of post-migration checksum / count validation."""

    item_id: str
    gcs_uri: str
    passed: bool
    source_checksum: Optional[str] = None
    dest_checksum: Optional[str] = None
    source_size: Optional[int] = None
    dest_size: Optional[int] = None
    metadata_match: bool = True
    error: Optional[str] = None


class RollbackResult(BaseModel):
    """Result of rolling back a migrated item from GCS."""

    item_id: str
    gcs_uri: Optional[str] = None
    success: bool
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────── #
# Job-level models
# ─────────────────────────────────────────────────────────────────────────── #


class WorkloadProgress(BaseModel):
    """Per-workload progress snapshot."""

    workload: WorkloadType
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    bytes_transferred: int = 0
    status: MigrationJobStatus = MigrationJobStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    throughput_items_per_second: float = 0.0
    estimated_completion_seconds: Optional[float] = None

    @property
    def progress_pct(self) -> float:
        if self.total_items == 0:
            return 0.0
        return round(self.completed_items / self.total_items * 100, 2)


class MigrationJob(BaseModel):
    """Top-level migration job record stored in Firestore."""

    id: str
    tenant_id: str
    scope: MigrationScope
    status: MigrationJobStatus = MigrationJobStatus.PENDING
    workload_progress: dict[str, WorkloadProgress] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: Optional[str] = None
    error_message: Optional[str] = None
    total_bytes_transferred: int = 0
    total_items_completed: int = 0
    total_items_failed: int = 0


# ─────────────────────────────────────────────────────────────────────────── #
# API request / response shapes
# ─────────────────────────────────────────────────────────────────────────── #


class StartMigrationRequest(BaseModel):
    tenant_id: str
    workloads: list[WorkloadType]
    user_filter: Optional[list[str]] = None
    site_filter: Optional[list[str]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    include_versions: bool = True
    include_permissions: bool = True
    wave: MigrationWave = MigrationWave.FULL

    @field_validator("workloads")
    @classmethod
    def at_least_one_workload(cls, v: list[WorkloadType]) -> list[WorkloadType]:
        if not v:
            raise ValueError("At least one workload must be specified")
        return v


class MigrationStatusResponse(BaseModel):
    job_id: str
    status: MigrationJobStatus
    overall_progress_pct: float
    workload_progress: dict[str, WorkloadProgress]
    total_bytes_transferred: int
    estimated_completion_seconds: Optional[float]
    started_at: Optional[datetime]
    elapsed_seconds: Optional[float]


class ErrorLogEntry(BaseModel):
    id: str
    job_id: str
    item_id: Optional[str]
    workload: WorkloadType
    error_type: ErrorType
    message: str
    retry_count: int
    is_dlq: bool
    timestamp: datetime
    source_id: Optional[str] = None


class ContentHash(BaseModel):
    """Utility for content-addressed storage deduplication."""

    algorithm: str = "sha256"
    value: str

    @classmethod
    def from_bytes(cls, data: bytes) -> "ContentHash":
        digest = hashlib.sha256(data).hexdigest()
        return cls(algorithm="sha256", value=digest)
