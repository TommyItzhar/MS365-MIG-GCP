"""FastAPI router — migration control, status, and setup endpoints."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Path as FPath, Query, status
from pydantic import BaseModel, Field

from app.models import (
    ErrorLogEntry,
    GWMigrationStatusResponse,
    GWWorkloadType,
    MigrationDirection,
    MigrationJob,
    MigrationJobStatus,
    MigrationStatusResponse,
    StartGWMigrationRequest,
    StartMigrationRequest,
    WorkloadProgress,
    WorkloadType,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

# Path to config.yaml — resolved once at import time
_CONFIG_YAML_PATH: Optional[Path] = None


def _get_config_path() -> Path:
    global _CONFIG_YAML_PATH
    if _CONFIG_YAML_PATH and _CONFIG_YAML_PATH.exists():
        return _CONFIG_YAML_PATH
    candidates = [
        Path(__file__).parent.parent.parent.parent.parent / "config" / "config.yaml",
        Path("/app/config/config.yaml"),
        Path("config/config.yaml"),
    ]
    for p in candidates:
        if p.exists():
            _CONFIG_YAML_PATH = p
            return p
    raise FileNotFoundError("config.yaml not found")


# ── Dependency injection helpers ───────────────────────────────────────────

def get_orchestrator():
    from app.main import app_state
    if "orchestrator" not in app_state:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M365→GCP orchestrator not initialised",
        )
    return app_state["orchestrator"]


def get_gw_orchestrator():
    from app.main import app_state
    if "gw_orchestrator" not in app_state:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GW→M365 orchestrator not initialised. "
                "Configure GW service account credentials in Tenants Connection first."
            ),
        )
    return app_state["gw_orchestrator"]


def get_state():
    from app.main import app_state
    return app_state["state"]


def get_errors():
    from app.main import app_state
    return app_state["errors"]


# ── Migration control ──────────────────────────────────────────────────────

@router.post("/migrate/start", status_code=status.HTTP_202_ACCEPTED)
async def start_migration(
    request: StartMigrationRequest,
    orchestrator=Depends(get_orchestrator),
) -> dict[str, str]:
    """Start a new migration job for the specified scope."""
    from app.models import MigrationScope
    scope = MigrationScope(
        tenant_id=request.tenant_id,
        workloads=request.workloads,
        user_filter=request.user_filter,
        site_filter=request.site_filter,
        start_date=request.start_date,
        end_date=request.end_date,
        include_versions=request.include_versions,
        include_permissions=request.include_permissions,
        wave=request.wave,
    )
    job_id = await orchestrator.start(scope)
    return {"job_id": job_id, "status": "started"}


@router.post("/migrate/pause")
async def pause_migration(
    job_id: str = Query(...),
    orchestrator=Depends(get_orchestrator),
) -> dict[str, str]:
    """Pause a running migration job."""
    await orchestrator.pause(job_id)
    return {"job_id": job_id, "status": "paused"}


@router.post("/migrate/resume")
async def resume_migration(
    job_id: str = Query(...),
    orchestrator=Depends(get_orchestrator),
) -> dict[str, str]:
    """Resume a paused migration job."""
    await orchestrator.resume(job_id)
    return {"job_id": job_id, "status": "resumed"}


@router.post("/migrate/cancel")
async def cancel_migration(
    job_id: str = Query(...),
    orchestrator=Depends(get_orchestrator),
) -> dict[str, str]:
    """Cancel a migration job."""
    await orchestrator.cancel(job_id)
    return {"job_id": job_id, "status": "cancelled"}


# ── Status and progress ────────────────────────────────────────────────────

@router.get("/status")
async def get_status(
    job_id: str = Query(...),
    state=Depends(get_state),
) -> MigrationStatusResponse:
    """Get the current overall status and ETC for a job."""
    job: Optional[MigrationJob] = await state.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    total = sum(
        p.total_items for p in job.workload_progress.values()
    )
    completed = sum(
        p.completed_items for p in job.workload_progress.values()
    )
    overall_pct = round(completed / total * 100, 2) if total > 0 else 0.0

    # Estimate ETC from per-workload estimates
    etc_values = [
        p.estimated_completion_seconds
        for p in job.workload_progress.values()
        if p.estimated_completion_seconds is not None
    ]
    etc = max(etc_values) if etc_values else None

    elapsed: Optional[float] = None
    if job.started_at:
        from datetime import datetime
        elapsed = (datetime.utcnow() - job.started_at).total_seconds()

    return MigrationStatusResponse(
        job_id=job_id,
        status=job.status,
        overall_progress_pct=overall_pct,
        workload_progress=job.workload_progress,
        total_bytes_transferred=job.total_bytes_transferred,
        estimated_completion_seconds=etc,
        started_at=job.started_at,
        elapsed_seconds=elapsed,
    )


@router.get("/progress")
async def get_progress(
    job_id: str = Query(...),
    state=Depends(get_state),
) -> dict[str, Any]:
    """Per-workload progress breakdown."""
    job: Optional[MigrationJob] = await state.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "workloads": {
            k: v.model_dump(mode="json")
            for k, v in job.workload_progress.items()
        },
    }


@router.get("/report")
async def get_report(
    job_id: str = Query(...),
    state=Depends(get_state),
) -> dict[str, Any]:
    """Full migration report (JSON)."""
    job: Optional[MigrationJob] = await state.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Pull verification report from GCS if available
    from app.main import app_state
    gcs = app_state.get("gcs")
    manifest = await state.get_manifest(job_id)

    return {
        "job": job.model_dump(mode="json"),
        "manifest_summary": {
            "total_items": manifest.get("total_items", 0) if manifest else 0,
            "total_bytes": manifest.get("total_bytes", 0) if manifest else 0,
        } if manifest else None,
    }


@router.get("/errors")
async def get_errors(
    job_id: str = Query(...),
    workload: Optional[WorkloadType] = Query(default=None),
    dlq_only: bool = Query(default=False),
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=50, ge=1, le=500),
    errors=Depends(get_errors),
) -> dict[str, Any]:
    """Paginated error log for a job."""
    error_list = errors.get_errors(
        workload=workload, dlq_only=dlq_only, page=page, page_size=page_size
    )
    return {
        "job_id": job_id,
        "page": page,
        "page_size": page_size,
        "errors": [e.model_dump(mode="json") for e in error_list],
        "summary": errors.summary(),
    }


@router.get("/manifest")
async def get_manifest(
    job_id: str = Query(...),
    state=Depends(get_state),
) -> dict[str, Any]:
    """Return the discovery manifest for a job."""
    manifest = await state.get_manifest(job_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return manifest


# ── Health ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness() -> dict[str, Any]:
    from app.main import app_state
    return {
        "status": "ready",
        "auth": "initialised" if "auth" in app_state else "pending",
        "orchestrator": "ready" if "orchestrator" in app_state else "pending",
    }


# ── Setup — environments ───────────────────────────────────────────────────


class EnvironmentConfigUpdate(BaseModel):
    """Fields that can be updated for a named environment."""

    active: Optional[bool] = None
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    gcp_project_id: Optional[str] = None
    gcp_gcs_bucket: Optional[str] = None
    gcp_firestore_database: Optional[str] = None
    gcp_region: Optional[str] = None


@router.get("/setup/environments")
async def list_environments() -> dict[str, Any]:
    """Return all configured environments and their non-secret settings."""
    from app.config.settings import get_settings
    settings = get_settings()
    envs = settings.list_environments()
    return {
        name: {
            "active": env.active,
            "azure_tenant_id": env.azure_tenant_id or "(not set)",
            "azure_client_id": env.azure_client_id or "(not set)",
            "gcp_project_id": env.gcp_project_id or "(not set)",
            "gcp_gcs_bucket": env.gcp_gcs_bucket or "(not set)",
            "gcp_firestore_database": env.gcp_firestore_database,
            "gcp_region": env.gcp_region,
        }
        for name, env in envs.items()
    }


@router.put("/setup/environments/{env_name}")
async def update_environment(
    env_name: str = FPath(..., pattern="^(dev|test|prod)$"),
    update: EnvironmentConfigUpdate = Body(...),
) -> dict[str, Any]:
    """Update non-secret fields for a named environment in config.yaml.

    Only fields explicitly provided in the request body are changed;
    omitted fields remain unchanged. Secrets (client_secret, SA key) must
    be stored in GCP Secret Manager or .env — never in config.yaml.
    """
    try:
        config_path = _get_config_path()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    with config_path.open() as fh:
        config: dict[str, Any] = yaml.safe_load(fh) or {}

    environments: dict[str, Any] = config.setdefault("environments", {})
    env_block: dict[str, Any] = environments.setdefault(env_name, {})
    azure_block: dict[str, Any] = env_block.setdefault("azure", {})
    gcp_block: dict[str, Any] = env_block.setdefault("gcp", {})

    changed: list[str] = []

    if update.active is not None:
        # Deactivate all others when activating one
        if update.active:
            for other_name, other_block in environments.items():
                if other_name != env_name and isinstance(other_block, dict):
                    other_block["active"] = False
        env_block["active"] = update.active
        changed.append("active")

    if update.azure_tenant_id is not None:
        azure_block["tenant_id"] = update.azure_tenant_id
        changed.append("azure.tenant_id")

    if update.azure_client_id is not None:
        azure_block["client_id"] = update.azure_client_id
        changed.append("azure.client_id")

    if update.gcp_project_id is not None:
        gcp_block["project_id"] = update.gcp_project_id
        changed.append("gcp.project_id")

    if update.gcp_gcs_bucket is not None:
        gcp_block["gcs_bucket"] = update.gcp_gcs_bucket
        changed.append("gcp.gcs_bucket")

    if update.gcp_firestore_database is not None:
        gcp_block["firestore_database"] = update.gcp_firestore_database
        changed.append("gcp.firestore_database")

    if update.gcp_region is not None:
        gcp_block["region"] = update.gcp_region
        changed.append("gcp.region")

    with config_path.open("w") as fh:
        yaml.dump(config, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Bust the settings cache so next call reloads from disk
    from app.config.settings import get_settings
    get_settings.cache_clear()

    return {"environment": env_name, "updated_fields": changed}


# ── Setup — Azure App Registration ────────────────────────────────────────


class RegisterAzureAppRequest(BaseModel):
    """Request body for the automatic Azure App Registration endpoint."""

    admin_token: str = Field(
        ...,
        description=(
            "Delegated Microsoft Graph access token from a Global Admin. "
            "Required scopes: Application.ReadWrite.All  AppRoleAssignment.ReadWrite.All. "
            "Obtain via MSAL device-code flow or the Entra admin center."
        ),
    )
    display_name: str = Field(
        default="MS365-GCP-Migration-Engine",
        description="Display name shown in Entra ID → App Registrations",
    )
    secret_display_name: str = Field(
        default="migration-engine-secret",
        description="Label for the client secret credential",
    )
    secret_years: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Client secret lifetime in years (max 5, Entra ID hard limit)",
    )
    grant_admin_consent: bool = Field(
        default=True,
        description="Immediately grant admin consent for all application permissions",
    )
    update_environment: Optional[str] = Field(
        default=None,
        pattern="^(dev|test|prod)$",
        description=(
            "If set, writes client_id and tenant_id into the named environment "
            "block in config.yaml after successful registration."
        ),
    )


@router.post("/setup/register-azure-app", status_code=status.HTTP_201_CREATED)
async def register_azure_app(
    request: RegisterAzureAppRequest,
) -> dict[str, Any]:
    """Create an Azure App Registration with all migration-engine permissions.

    **What this does:**
    1. Creates an App Registration in your Entra ID tenant
    2. Adds all 15 required application permissions (Graph API)
    3. Creates a client secret (returned once — store it immediately)
    4. Creates the service principal
    5. Grants admin consent for every permission (if `grant_admin_consent=true`)
    6. Optionally updates `config.yaml` with the new `client_id`

    **Prerequisites:**
    - The `admin_token` must come from an account that is a **Global Admin**
      or **Application Administrator** in the tenant.
    - To obtain a token interactively, use the MSAL device-code flow or the
      Microsoft identity platform browser flow.

    **After registration:**
    - Add `MS365_CLIENT_SECRET=<returned secret>` to your `.env` file
    - Set `MS365_TENANT_ID` and `MS365_CLIENT_ID` (or let `update_environment`
      write them to `config.yaml` automatically)
    """
    from app.setup.app_registrar import AzureAppRegistrar, RegistrationStepError

    registrar = AzureAppRegistrar(admin_token=request.admin_token)
    try:
        result = await registrar.register(
            display_name=request.display_name,
            secret_display_name=request.secret_display_name,
            secret_years=request.secret_years,
            grant_admin_consent=request.grant_admin_consent,
        )
    except RegistrationStepError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": str(exc),
                "step": exc.step,
                "graph_http_status": exc.http_status,
            },
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during app registration")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Optionally back-fill config.yaml with the new client_id + tenant_id
    if request.update_environment:
        try:
            config_path = _get_config_path()
            with config_path.open() as fh:
                config: dict[str, Any] = yaml.safe_load(fh) or {}

            env_block = (
                config.setdefault("environments", {})
                .setdefault(request.update_environment, {})
            )
            azure_block = env_block.setdefault("azure", {})
            azure_block["client_id"] = result.client_id
            if result.tenant_id:
                azure_block["tenant_id"] = result.tenant_id

            with config_path.open("w") as fh:
                yaml.dump(
                    config, fh, default_flow_style=False,
                    allow_unicode=True, sort_keys=False,
                )
            from app.config.settings import get_settings
            get_settings.cache_clear()
        except Exception as exc:
            logger.warning("Could not update config.yaml: %s", exc)

    response = result.model_dump()
    response["next_steps"] = [
        f"Add to .env:  MS365_CLIENT_SECRET={result.client_secret}",
        f"Add to .env:  MS365_CLIENT_ID={result.client_id}",
        f"Add to .env:  MS365_TENANT_ID={result.tenant_id}",
        "Never commit .env — secrets must stay out of version control.",
    ]
    if result.permissions_failed:
        response["warning"] = (
            f"{len(result.permissions_failed)} permission(s) could not be granted "
            "automatically. Grant them manually in Entra ID → App Registrations → "
            f"{result.display_name} → API permissions → Grant admin consent."
        )
    return response


# ── Setup — validate credentials ──────────────────────────────────────────


class ValidateRequest(BaseModel):
    """Specify which credentials to test.  All fields are optional — omit to
    test the currently configured (settings.py) values."""

    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    gcp_project_id: Optional[str] = None


class TenantConfigPayload(BaseModel):
    """All tenant connection fields saved from the UI."""

    # Microsoft 365 / Azure (destination for M365→GCP; source+destination for GW→M365)
    azure_tenant_id: str = ""
    azure_tenant_domain: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    # Google Cloud Platform (destination for M365→GCP)
    gcp_project_id: str = ""
    gcp_gcs_bucket: str = ""
    gcp_region: str = "us-central1"
    gcp_firestore_database: str = "(default)"
    gcp_service_account_json: str = ""
    # Google Workspace (source for GW→M365 reverse migration)
    gw_domain: str = ""
    gw_admin_email: str = ""
    gw_customer_id: str = ""
    gw_service_account_json: str = ""
    # Active environment
    active_environment: str = "dev"


@router.get("/setup/tenant-config")
async def get_tenant_config() -> dict[str, Any]:
    """Return the current tenant config with secrets masked."""
    from app.setup.tenant_store import get_tenant_store
    return get_tenant_store().masked()


@router.post("/setup/tenant-config")
async def save_tenant_config(payload: TenantConfigPayload) -> dict[str, Any]:
    """Save tenant config to local store and propagate non-secrets to config.yaml."""
    from app.setup.tenant_store import get_tenant_store

    get_tenant_store().save(payload.model_dump())

    # Propagate non-secret fields to config.yaml so the rest of the app sees them
    try:
        config_path = _get_config_path()
        with config_path.open() as fh:
            config: dict[str, Any] = yaml.safe_load(fh) or {}

        if payload.azure_tenant_id:
            config.setdefault("azure_tenant", {})["tenant_id"] = payload.azure_tenant_id
        if payload.azure_tenant_domain:
            config.setdefault("azure_tenant", {})["tenant_domain"] = payload.azure_tenant_domain
        if payload.gcp_project_id:
            config.setdefault("gcp", {})["project_id"] = payload.gcp_project_id
            config.setdefault("gcp_tenant", {})["project_id"] = payload.gcp_project_id
        if payload.gcp_gcs_bucket:
            config.setdefault("gcp", {})["gcs_bucket"] = payload.gcp_gcs_bucket
        if payload.gcp_region:
            config.setdefault("gcp", {})["region"] = payload.gcp_region
        if payload.gcp_firestore_database:
            config.setdefault("gcp", {})["firestore_database"] = payload.gcp_firestore_database

        # GW non-secret fields
        if payload.gw_domain:
            config.setdefault("google_workspace", {})["domain"] = payload.gw_domain
        if payload.gw_admin_email:
            config.setdefault("google_workspace", {})["admin_email"] = payload.gw_admin_email
        if payload.gw_customer_id:
            config.setdefault("google_workspace", {})["customer_id"] = payload.gw_customer_id

        # Update the active environment block
        if payload.active_environment in ("dev", "test", "prod"):
            envs = config.setdefault("environments", {})
            for name in ("dev", "test", "prod"):
                envs.setdefault(name, {})["active"] = (name == payload.active_environment)
            active = envs.setdefault(payload.active_environment, {})
            if payload.azure_tenant_id:
                active.setdefault("azure", {})["tenant_id"] = payload.azure_tenant_id
            if payload.azure_client_id:
                active.setdefault("azure", {})["client_id"] = payload.azure_client_id
            if payload.gcp_project_id:
                active.setdefault("gcp", {})["project_id"] = payload.gcp_project_id
            if payload.gcp_gcs_bucket:
                active.setdefault("gcp", {})["gcs_bucket"] = payload.gcp_gcs_bucket
            if payload.gcp_region:
                active.setdefault("gcp", {})["region"] = payload.gcp_region

        with config_path.open("w") as fh:
            yaml.dump(config, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

        from app.config.settings import get_settings
        get_settings.cache_clear()
    except Exception as exc:
        logger.warning("Could not update config.yaml after tenant save: %s", exc)

    return {"ok": True, "message": "Configuration saved successfully"}


@router.post("/setup/validate")
async def validate_credentials(
    request: ValidateRequest = Body(default_factory=ValidateRequest),
) -> dict[str, Any]:
    """Test whether the Microsoft 365 and GCP credentials are valid.

    If no values are provided, the currently configured settings are used.
    Returns a per-service result with any error details.
    """
    from app.config.settings import get_settings
    from app.setup.app_registrar import CredentialValidator

    settings = get_settings()

    tenant_id = request.tenant_id or settings.m365.tenant_id
    client_id = request.client_id or settings.m365.client_id
    client_secret = request.client_secret or settings.m365.client_secret
    gcp_project_id = request.gcp_project_id or settings.gcp.project_id

    results: dict[str, Any] = {}

    # Microsoft 365 / Graph
    if tenant_id and client_id and client_secret:
        m365_ok, org_name, m365_err = await CredentialValidator.validate_m365(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        results["m365"] = {
            "ok": m365_ok,
            "organization": org_name,
            "error": m365_err,
        }
    else:
        missing = [
            f for f, v in [
                ("tenant_id", tenant_id),
                ("client_id", client_id),
                ("client_secret", client_secret),
            ]
            if not v
        ]
        results["m365"] = {
            "ok": False,
            "error": f"Missing required fields: {', '.join(missing)}",
        }

    # GCP
    if gcp_project_id:
        gcp_ok, gcp_err = await CredentialValidator.validate_gcp(gcp_project_id)
        results["gcp"] = {"ok": gcp_ok, "project_id": gcp_project_id, "error": gcp_err}
    else:
        results["gcp"] = {"ok": False, "error": "gcp_project_id not configured"}

    overall_ok = all(r.get("ok", False) for r in results.values())
    return {"ok": overall_ok, "services": results}


# ── GW → M365 migration (reverse direction) ────────────────────────────────


@router.post("/gw-migrate/start", status_code=status.HTTP_202_ACCEPTED)
async def start_gw_migration(
    request: StartGWMigrationRequest,
    gw_orchestrator=Depends(get_gw_orchestrator),
) -> dict[str, str]:
    """Start a Google Workspace → Microsoft 365 migration job.

    **Prerequisites:**
    - GW service account JSON with domain-wide delegation must be configured
      in the Tenants Connection UI (field: GW Service Account JSON).
    - The service account must be granted DWD in the Google Admin Console:
      Admin Console → Security → API Controls → Domain-wide Delegation.
    - The M365 app registration must have write permissions granted:
      Mail.ReadWrite, Files.ReadWrite.All, Calendars.ReadWrite,
      Contacts.ReadWrite, User.ReadWrite.All, Channel.Create,
      ChannelMessage.Send, Directory.ReadWrite.All.

    **Workloads:** gmail, drive, calendar, contacts, chat, identity

    **user_mappings:** Maps GW email → M365 UPN.
    If empty, the same address is assumed for both sides.
    """
    from app.models import GWMigrationScope
    scope = GWMigrationScope(
        gw_domain=request.gw_domain,
        m365_tenant_id=request.m365_tenant_id,
        workloads=request.workloads,
        user_mappings=request.user_mappings,
        start_date=request.start_date,
        end_date=request.end_date,
        include_shared_drives=request.include_shared_drives,
    )
    job_id = await gw_orchestrator.start(scope)
    return {
        "job_id": job_id,
        "status": "started",
        "direction": MigrationDirection.GW_TO_M365.value,
    }


@router.post("/gw-migrate/pause")
async def pause_gw_migration(
    job_id: str = Query(...),
    gw_orchestrator=Depends(get_gw_orchestrator),
) -> dict[str, str]:
    """Pause a running GW→M365 migration job."""
    await gw_orchestrator.pause(job_id)
    return {"job_id": job_id, "status": "paused"}


@router.post("/gw-migrate/resume")
async def resume_gw_migration(
    job_id: str = Query(...),
    gw_orchestrator=Depends(get_gw_orchestrator),
) -> dict[str, str]:
    """Resume a paused GW→M365 migration job."""
    await gw_orchestrator.resume(job_id)
    return {"job_id": job_id, "status": "resumed"}


@router.post("/gw-migrate/cancel")
async def cancel_gw_migration(
    job_id: str = Query(...),
    gw_orchestrator=Depends(get_gw_orchestrator),
) -> dict[str, str]:
    """Cancel a GW→M365 migration job."""
    await gw_orchestrator.cancel(job_id)
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/gw-migrate/status")
async def get_gw_migration_status(
    job_id: str = Query(...),
    state=Depends(get_state),
) -> dict[str, Any]:
    """Get current status of a GW→M365 migration job."""
    job = await state.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"GW job {job_id} not found")
    return {
        "job_id": job_id,
        "direction": MigrationDirection.GW_TO_M365.value,
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "workload_progress": {
            k: v.model_dump(mode="json")
            for k, v in job.workload_progress.items()
        },
    }


@router.get("/gw-migrate/workloads")
async def list_gw_workloads() -> dict[str, Any]:
    """List all supported GW→M365 workloads with their descriptions."""
    return {
        "direction": MigrationDirection.GW_TO_M365.value,
        "workloads": {
            GWWorkloadType.GMAIL.value: {
                "label": "Gmail → Exchange Online",
                "description": "Migrates all Gmail messages preserving folder structure and read state.",
                "requires_permissions": ["gmail.readonly"],
            },
            GWWorkloadType.DRIVE.value: {
                "label": "Google Drive → OneDrive",
                "description": "Migrates Drive files; Google Workspace formats are converted to Office formats.",
                "requires_permissions": ["drive.readonly"],
            },
            GWWorkloadType.CALENDAR.value: {
                "label": "Google Calendar → Outlook Calendar",
                "description": "Migrates calendar events including attendees and recurrence rules.",
                "requires_permissions": ["calendar.readonly"],
            },
            GWWorkloadType.CONTACTS.value: {
                "label": "Google Contacts → Outlook Contacts",
                "description": "Migrates contacts with phone numbers, addresses, and job information.",
                "requires_permissions": ["contacts.readonly"],
            },
            GWWorkloadType.CHAT.value: {
                "label": "Google Chat → Microsoft Teams",
                "description": "Migrates Chat spaces to Teams channels. DMs are not migrated.",
                "requires_permissions": ["chat.messages.readonly", "chat.spaces.readonly"],
            },
            GWWorkloadType.IDENTITY.value: {
                "label": "Google Directory → Entra ID",
                "description": "Creates/updates users in Entra ID. Requires Admin SDK delegation.",
                "requires_permissions": [
                    "admin.directory.user.readonly",
                    "admin.directory.group.readonly",
                ],
            },
        },
    }


@router.post("/setup/validate-gw")
async def validate_gw_credentials() -> dict[str, Any]:
    """Validate the configured Google Workspace service account credentials.

    Tests domain-wide delegation by attempting to list users via the Admin SDK.
    Requires a GW service account JSON in the Tenants Connection UI.
    """
    from app.setup.tenant_store import get_tenant_store
    store = get_tenant_store()
    config = store.load()

    if not config.get("gw_service_account_json"):
        return {
            "ok": False,
            "error": "No GW service account JSON configured. Add it in Tenants Connection.",
        }
    if not config.get("gw_admin_email"):
        return {
            "ok": False,
            "error": "No GW admin email configured. Set it in Tenants Connection.",
        }

    try:
        from app.auth.gw_auth_manager import GWAuthManager
        gw_auth = await GWAuthManager.create()
        users = await gw_auth.list_workspace_users(
            admin_email=config["gw_admin_email"]
        )
        return {
            "ok": True,
            "user_count": len(users),
            "message": f"Domain-wide delegation validated — {len(users)} active users found.",
        }
    except Exception as exc:
        logger.warning("gw_credential_validation_failed", extra={"error": str(exc)})
        return {"ok": False, "error": str(exc)}
