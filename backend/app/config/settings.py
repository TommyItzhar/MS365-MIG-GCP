"""Pydantic-settings configuration — reads from config.yaml + env overrides.

Startup validation ensures fail-fast behaviour before any migration work begins.
All secrets are resolved from GCP Secret Manager at runtime, not stored here.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_yaml_config() -> dict[str, Any]:
    """Load config.yaml from the repo root config/ directory."""
    candidates = [
        Path(__file__).parent.parent.parent.parent / "config" / "config.yaml",
        Path("/app/config/config.yaml"),
        Path("config/config.yaml"),
    ]
    for path in candidates:
        if path.exists():
            with path.open() as fh:
                return yaml.safe_load(fh) or {}
    return {}


_YAML = _load_yaml_config()


def _yaml_val(key: str, default: Any = None) -> Any:
    """Traverse dot-separated key into the YAML dict."""
    parts = key.split(".")
    node: Any = _YAML
    for part in parts:
        if not isinstance(node, dict):
            return default
        node = node.get(part, default)
    return node if node is not None else default


class AzureTenantConfig(BaseSettings):
    """Source Microsoft 365 / Entra ID tenant identity (not a secret)."""

    model_config = SettingsConfigDict(env_prefix="AZURE_TENANT_", extra="ignore")

    tenant_id: str = Field(
        default_factory=lambda: _yaml_val("azure_tenant.tenant_id", "")
    )
    tenant_domain: str = Field(
        default_factory=lambda: _yaml_val("azure_tenant.tenant_domain", "")
    )
    tenant_name: str = Field(
        default_factory=lambda: _yaml_val("azure_tenant.tenant_name", "")
    )


class GCPTenantConfig(BaseSettings):
    """Destination GCP tenant / organisation identity (not a secret)."""

    model_config = SettingsConfigDict(env_prefix="GCP_TENANT_", extra="ignore")

    project_id: str = Field(
        default_factory=lambda: _yaml_val("gcp_tenant.project_id", "")
    )
    organization_id: str = Field(
        default_factory=lambda: _yaml_val("gcp_tenant.organization_id", "")
    )
    project_number: str = Field(
        default_factory=lambda: _yaml_val("gcp_tenant.project_number", "")
    )


class EnvironmentOverride(BaseSettings):
    """Per-environment Azure + GCP config loaded from the environments block."""

    model_config = SettingsConfigDict(extra="ignore")

    active: bool = False
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    gcp_project_id: str = ""
    gcp_gcs_bucket: str = ""
    gcp_firestore_database: str = "(default)"
    gcp_region: str = "us-central1"

    @classmethod
    def from_yaml(cls, env_name: str) -> "EnvironmentOverride":
        """Load an environment block from config.yaml by name."""
        block = _yaml_val(f"environments.{env_name}", {})
        if not isinstance(block, dict):
            return cls()
        azure = block.get("azure", {})
        gcp = block.get("gcp", {})
        return cls(
            active=block.get("active", False),
            azure_tenant_id=azure.get("tenant_id", ""),
            azure_client_id=azure.get("client_id", ""),
            gcp_project_id=gcp.get("project_id", ""),
            gcp_gcs_bucket=gcp.get("gcs_bucket", ""),
            gcp_firestore_database=gcp.get("firestore_database", "(default)"),
            gcp_region=gcp.get("region", "us-central1"),
        )


class M365Settings(BaseSettings):
    """Microsoft 365 / Entra ID credentials (resolved from Secret Manager)."""

    model_config = SettingsConfigDict(env_prefix="MS365_", extra="ignore")

    tenant_id: str = Field(default="")
    client_id: str = Field(default="")
    client_secret: str = Field(default="")
    authority_url: str = Field(
        default="https://login.microsoftonline.com/{tenant_id}"
    )


class GCPSettings(BaseSettings):
    """Google Cloud Platform configuration."""

    model_config = SettingsConfigDict(env_prefix="GCP_", extra="ignore")

    project_id: str = Field(
        default_factory=lambda: _yaml_val("gcp.project_id", "")
    )
    region: str = Field(
        default_factory=lambda: _yaml_val("gcp.region", "us-central1")
    )
    gcs_bucket: str = Field(
        default_factory=lambda: _yaml_val("gcp.gcs_bucket", "")
    )
    bigquery_dataset: str = Field(
        default_factory=lambda: _yaml_val("gcp.bigquery_dataset", "migration_data")
    )
    firestore_database: str = Field(
        default_factory=lambda: _yaml_val("gcp.firestore_database", "(default)")
    )
    pubsub_dlq_topic: str = Field(
        default_factory=lambda: _yaml_val("gcp.pubsub_dlq_topic", "migration-dlq")
    )
    cloud_tasks_queue: str = Field(
        default_factory=lambda: _yaml_val(
            "gcp.cloud_tasks_queue", "migration-jobs"
        )
    )
    service_account_key_path: Optional[str] = Field(default=None)


class WorkloadConfig(BaseSettings):
    """Per-workload enable/disable, concurrency, and batch size settings."""

    model_config = SettingsConfigDict(extra="ignore")

    exchange_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.exchange.enabled", True)
    )
    exchange_concurrency: int = Field(
        default_factory=lambda: _yaml_val("workloads.exchange.concurrency", 4)
    )
    exchange_batch_size: int = Field(
        default_factory=lambda: _yaml_val("workloads.exchange.batch_size", 50)
    )

    onedrive_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.onedrive.enabled", True)
    )
    onedrive_concurrency: int = Field(
        default_factory=lambda: _yaml_val("workloads.onedrive.concurrency", 8)
    )

    sharepoint_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.sharepoint.enabled", True)
    )
    sharepoint_concurrency: int = Field(
        default_factory=lambda: _yaml_val("workloads.sharepoint.concurrency", 6)
    )

    teams_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.teams.enabled", True)
    )
    teams_concurrency: int = Field(
        default_factory=lambda: _yaml_val("workloads.teams.concurrency", 2)
    )

    identity_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.identity.enabled", True)
    )
    intune_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.intune.enabled", True)
    )
    power_automate_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.power_automate.enabled", True)
    )
    forms_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.forms.enabled", True)
    )
    planner_enabled: bool = Field(
        default_factory=lambda: _yaml_val("workloads.planner.enabled", True)
    )


class Settings(BaseSettings):
    """Top-level application settings with startup validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────
    app_name: str = "ms365-gcp-migration-engine"
    environment: str = Field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "production")
    )
    log_level: str = Field(
        default_factory=lambda: _yaml_val("app.log_level", "INFO")
    )
    api_host: str = Field(
        default_factory=lambda: _yaml_val("app.api_host", "0.0.0.0")
    )
    api_port: int = Field(
        default_factory=lambda: _yaml_val("app.api_port", 8080)
    )

    # ── Tenant identities (non-secret, safe in config) ─────────────────────
    azure_tenant: AzureTenantConfig = Field(default_factory=AzureTenantConfig)
    gcp_tenant: GCPTenantConfig = Field(default_factory=GCPTenantConfig)

    # ── Sub-configurations ─────────────────────────────────────────────────
    m365: M365Settings = Field(default_factory=M365Settings)
    gcp: GCPSettings = Field(default_factory=GCPSettings)
    workloads: WorkloadConfig = Field(default_factory=WorkloadConfig)

    # ── Migration engine ───────────────────────────────────────────────────
    checkpoint_interval: int = Field(
        default_factory=lambda: _yaml_val("engine.checkpoint_interval", 100)
    )
    max_retry_attempts: int = Field(
        default_factory=lambda: _yaml_val("engine.max_retry_attempts", 5)
    )
    worker_concurrency: int = Field(
        default_factory=lambda: _yaml_val("engine.worker_concurrency", 8)
    )
    use_secret_manager: bool = Field(
        default_factory=lambda: _yaml_val("engine.use_secret_manager", True)
    )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v

    @model_validator(mode="after")
    def validate_gcp_bucket(self) -> "Settings":
        import logging as _logging
        active_env = self.get_active_environment()
        bucket = (
            self.gcp.gcs_bucket
            or (active_env.gcp_gcs_bucket if active_env else "")
        )
        if not bucket:
            _logging.getLogger(__name__).warning(
                "GCS bucket not configured — set it in the Tenants Connection UI "
                "or via GCP_GCS_BUCKET / gcp.gcs_bucket in config.yaml."
            )
        return self

    @model_validator(mode="after")
    def validate_gcp_project(self) -> "Settings":
        import logging as _logging
        active_env = self.get_active_environment()
        project = (
            self.gcp.project_id
            or (active_env.gcp_project_id if active_env else "")
            or self.gcp_tenant.project_id
        )
        if not project:
            _logging.getLogger(__name__).warning(
                "GCP project not configured — set it in the Tenants Connection UI "
                "or via GCP_PROJECT_ID / gcp.project_id in config.yaml."
            )
        return self

    # ── Environment helpers ────────────────────────────────────────────────

    def get_active_environment(self) -> Optional[EnvironmentOverride]:
        """Return the first active environment block from config.yaml, or None."""
        for env_name in ("dev", "test", "prod"):
            override = EnvironmentOverride.from_yaml(env_name)
            if override.active:
                return override
        return None

    def get_environment(self, name: str) -> EnvironmentOverride:
        """Return an environment block by name."""
        return EnvironmentOverride.from_yaml(name)

    def list_environments(self) -> dict[str, EnvironmentOverride]:
        """Return all configured environments."""
        return {
            name: EnvironmentOverride.from_yaml(name)
            for name in ("dev", "test", "prod")
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
