"""Application-wide constants — no magic numbers in migrator code."""
from __future__ import annotations

from typing import Final

# ─────────────────────────────────────────────────────────────────────────── #
# Microsoft Graph API
# ─────────────────────────────────────────────────────────────────────────── #
GRAPH_BATCH_MAX_REQUESTS: Final[int] = 20
GRAPH_MAX_PAGE_SIZE: Final[int] = 999
GRAPH_DEFAULT_PAGE_SIZE: Final[int] = 100
GRAPH_BASE_URL: Final[str] = "https://graph.microsoft.com/v1.0"
GRAPH_BETA_URL: Final[str] = "https://graph.microsoft.com/beta"
EWS_ENDPOINT: Final[str] = "https://outlook.office365.com/EWS/Exchange.asmx"
GRAPH_APP_SCOPES: Final[list[str]] = ["https://graph.microsoft.com/.default"]

# ─────────────────────────────────────────────────────────────────────────── #
# Required Graph API application permissions
# ─────────────────────────────────────────────────────────────────────────── #
GRAPH_REQUIRED_PERMISSIONS: Final[list[str]] = [
    "Mail.Read",
    "Calendars.Read",
    "Contacts.Read",
    "Files.Read.All",
    "Sites.Read.All",
    "Team.ReadBasic.All",
    "ChannelMessage.Read.All",
    "TeamSettings.Read.All",
    "User.Read.All",
    "Group.Read.All",
    "Device.Read.All",
    "Reports.Read.All",
    "Tasks.Read",
    "Directory.Read.All",
    "Policy.Read.All",
    "DeviceManagementManagedDevices.Read.All",
]

# ─────────────────────────────────────────────────────────────────────────── #
# Per-workload concurrency limits (Graph throttle-aware)
# ─────────────────────────────────────────────────────────────────────────── #
EXCHANGE_MAX_CONCURRENT: Final[int] = 4
SHAREPOINT_MAX_CONCURRENT: Final[int] = 6
TEAMS_MAX_CONCURRENT: Final[int] = 2
ONEDRIVE_MAX_CONCURRENT: Final[int] = 8
GROUPS_MAX_CONCURRENT: Final[int] = 4
IDENTITY_MAX_CONCURRENT: Final[int] = 8
INTUNE_MAX_CONCURRENT: Final[int] = 4
DEFAULT_WORKER_CONCURRENCY: Final[int] = 8

# ─────────────────────────────────────────────────────────────────────────── #
# Retry / backoff (RFC 7231 exponential backoff with jitter)
# ─────────────────────────────────────────────────────────────────────────── #
MAX_RETRY_ATTEMPTS: Final[int] = 5
BACKOFF_MIN_SECONDS: Final[float] = 1.0
BACKOFF_MAX_SECONDS: Final[float] = 120.0
BACKOFF_JITTER_FACTOR: Final[float] = 0.20
RATE_LIMIT_STATUS_CODE: Final[int] = 429
DEFAULT_RETRY_AFTER_SECONDS: Final[float] = 30.0
HTTP_TRANSIENT_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})

# ─────────────────────────────────────────────────────────────────────────── #
# Checkpointing
# ─────────────────────────────────────────────────────────────────────────── #
CHECKPOINT_INTERVAL: Final[int] = 100
DELTA_TOKEN_MAX_AGE_DAYS: Final[int] = 25  # renew before Graph's 30-day TTL

# ─────────────────────────────────────────────────────────────────────────── #
# File sizes
# ─────────────────────────────────────────────────────────────────────────── #
LARGE_FILE_THRESHOLD_BYTES: Final[int] = 4 * 1_024 * 1_024   # 4 MB
RESUMABLE_UPLOAD_THRESHOLD: Final[int] = 5 * 1_024 * 1_024   # 5 MB
DEFAULT_CHUNK_SIZE_BYTES: Final[int] = 8 * 1_024 * 1_024     # 8 MB

# ─────────────────────────────────────────────────────────────────────────── #
# GCS object naming
# ─────────────────────────────────────────────────────────────────────────── #
GCS_MAX_OBJECT_NAME_BYTES: Final[int] = 1_024
GCS_PATH_TEMPLATE: Final[str] = (
    "{tenant_id}/{workload}/{entity_id}/{year_month}/{item_id}{ext}"
)
GCS_ATTACHMENT_PREFIX: Final[str] = "attachments"
GCS_PERMISSIONS_SUFFIX: Final[str] = ".permissions.json"
GCS_METADATA_SUFFIX: Final[str] = ".metadata.json"

# ─────────────────────────────────────────────────────────────────────────── #
# Token / credential management
# ─────────────────────────────────────────────────────────────────────────── #
TOKEN_REFRESH_BUFFER_SECONDS: Final[int] = 300  # refresh 5 min before expiry

# ─────────────────────────────────────────────────────────────────────────── #
# Monitoring / alerting thresholds
# ─────────────────────────────────────────────────────────────────────────── #
DLQ_ALERT_THRESHOLD: Final[int] = 100
AUTH_FAILURE_RATE_THRESHOLD: Final[float] = 0.05
THROUGHPUT_DROP_THRESHOLD: Final[float] = 0.50

# ─────────────────────────────────────────────────────────────────────────── #
# SharePoint
# ─────────────────────────────────────────────────────────────────────────── #
SHAREPOINT_LIST_VIEW_THRESHOLD: Final[int] = 5_000
SHAREPOINT_INDEXED_PAGE_SIZE: Final[int] = 100

# ─────────────────────────────────────────────────────────────────────────── #
# Exchange EWS hidden folder traversal paths
# ─────────────────────────────────────────────────────────────────────────── #
EXCHANGE_BATCH_SIZE: Final[int] = 50
EXCHANGE_EWS_HIDDEN_WELL_KNOWN: Final[list[str]] = [
    "recoverableitemsdeletions",
    "recoverableitemspurges",
    "recoverableitemsversions",
]

# ─────────────────────────────────────────────────────────────────────────── #
# Cloud Monitoring metric descriptors
# ─────────────────────────────────────────────────────────────────────────── #
METRIC_ITEMS_MIGRATED: Final[str] = (
    "custom.googleapis.com/migration/items_migrated_total"
)
METRIC_ITEMS_FAILED: Final[str] = (
    "custom.googleapis.com/migration/items_failed_total"
)
METRIC_BYTES_TRANSFERRED: Final[str] = (
    "custom.googleapis.com/migration/bytes_transferred_total"
)
METRIC_QUEUE_DEPTH: Final[str] = "custom.googleapis.com/migration/queue_depth"
METRIC_THROUGHPUT: Final[str] = (
    "custom.googleapis.com/migration/throughput_items_per_second"
)
METRIC_ETC_SECONDS: Final[str] = (
    "custom.googleapis.com/migration/estimated_completion_seconds"
)

# ─────────────────────────────────────────────────────────────────────────── #
# Firestore collection names
# ─────────────────────────────────────────────────────────────────────────── #
FS_JOBS: Final[str] = "migration_jobs"
FS_ITEMS: Final[str] = "migration_items"
FS_CHECKPOINTS: Final[str] = "migration_checkpoints"
FS_MANIFESTS: Final[str] = "migration_manifests"
FS_ERRORS: Final[str] = "migration_errors"
FS_DELTA_TOKENS: Final[str] = "migration_delta_tokens"

# ─────────────────────────────────────────────────────────────────────────── #
# GCP authentication
# ─────────────────────────────────────────────────────────────────────────── #
GCP_AUTH_SCOPES: Final[list[str]] = [
    "https://www.googleapis.com/auth/cloud-platform"
]

# ─────────────────────────────────────────────────────────────────────────── #
# Secret Manager secret names (values live in Secret Manager, not here)
# ─────────────────────────────────────────────────────────────────────────── #
SECRET_MS365_TENANT_ID: Final[str] = "ms365-tenant-id"
SECRET_MS365_CLIENT_ID: Final[str] = "ms365-client-id"
SECRET_MS365_CLIENT_SECRET: Final[str] = "ms365-client-secret"
SECRET_GCP_SA_KEY: Final[str] = "gcp-service-account-key"
SECRET_GW_SA_KEY: Final[str] = "gw-service-account-key"

# ─────────────────────────────────────────────────────────────────────────── #
# Google Workspace → M365 migration constants
# ─────────────────────────────────────────────────────────────────────────── #
GW_GMAIL_MAX_RESULTS: Final[int] = 500
GW_DRIVE_MAX_RESULTS: Final[int] = 1000
GW_CALENDAR_MAX_RESULTS: Final[int] = 2500
GW_CONTACTS_MAX_RESULTS: Final[int] = 2000

# M365 write permissions required for GW→M365 migration
GRAPH_WRITE_PERMISSIONS: Final[list[str]] = [
    "Mail.ReadWrite",
    "Files.ReadWrite.All",
    "Calendars.ReadWrite",
    "Contacts.ReadWrite",
    "User.ReadWrite.All",
    "Channel.Create",
    "ChannelMessage.Send",
    "Directory.ReadWrite.All",
]

# Firestore collection for GW migration jobs
FS_GW_JOBS: Final[str] = "gw_migration_jobs"
FS_GW_ITEMS: Final[str] = "gw_migration_items"
