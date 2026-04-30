"""FastAPI endpoint smoke tests.

Uses a minimal in-process TestClient — no external services required.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient


# ── Minimal isolated app (no lifespan, no GCP, no MSAL) ──────────────────

def _health_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1")

    @r.get("/health")
    def health():
        return {"status": "ok"}

    @r.get("/ready")
    def ready():
        return {"status": "ready", "auth": "pending", "orchestrator": "pending"}

    return r


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(_health_router())
    return TestClient(app)


# ── Health / readiness ─────────────────────────────────────────────────────

def test_health(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready(client: TestClient):
    resp = client.get("/api/v1/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ready"


def test_unknown_route_is_404(client: TestClient):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404


# ── Core module importability ──────────────────────────────────────────────

def test_models_importable():
    from app.models import MigrationItem, WorkloadType, ItemState, MigrationScope
    assert WorkloadType.EXCHANGE is not None
    assert ItemState.PENDING is not None


def test_constants_importable():
    from app.constants import (
        GRAPH_BATCH_MAX_REQUESTS,
        TOKEN_REFRESH_BUFFER_SECONDS,
        CHECKPOINT_INTERVAL,
    )
    assert GRAPH_BATCH_MAX_REQUESTS == 20
    assert TOKEN_REFRESH_BUFFER_SECONDS == 300
    assert CHECKPOINT_INTERVAL > 0


def test_settings_loads_without_credentials():
    """Settings should initialise with empty GCP/M365 values (warns, not raises)."""
    import importlib
    import app.config.settings as settings_mod
    # Clear the lru_cache so we get a fresh load
    settings_mod.get_settings.cache_clear()
    settings = settings_mod.get_settings()
    assert settings is not None
    assert settings.environment in ("development", "staging", "production")
