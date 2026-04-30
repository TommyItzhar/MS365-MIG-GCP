"""Persistent tenant configuration store.

Before GCP Secret Manager is reachable, tenant settings are saved to
config/tenant_settings.json — a local file excluded from version control.
Secrets are base64-obfuscated at rest (not encrypted; the file must be
protected by OS-level permissions and never committed).
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CANDIDATES = [
    Path(__file__).parent.parent.parent.parent.parent / "config" / "tenant_settings.json",
    Path("/app/config/tenant_settings.json"),
    Path("config/tenant_settings.json"),
]

_SECRET_KEYS = {"azure_client_secret", "gcp_service_account_json"}
_MASK = "••••••••"


def _store_path() -> Path:
    for p in _CANDIDATES:
        if p.exists():
            return p
    return _CANDIDATES[0]


def _encode(value: str) -> str:
    return base64.b64encode(value.encode()).decode() if value else ""


def _decode(value: str) -> str:
    try:
        return base64.b64decode(value.encode()).decode() if value else ""
    except Exception:
        return value


class TenantConfigStore:
    def load(self) -> dict[str, Any]:
        """Return full config with secrets decoded."""
        path = _store_path()
        if not path.exists():
            return {}
        try:
            with path.open() as fh:
                raw: dict[str, Any] = json.load(fh)
            for k in _SECRET_KEYS:
                if raw.get(k):
                    raw[k] = _decode(raw[k])
            return raw
        except Exception as exc:
            logger.warning("Could not read tenant store at %s: %s", path, exc)
            return {}

    def save(self, config: dict[str, Any]) -> None:
        """Persist config, obfuscating secret fields."""
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in config.items() if v is not None}
        for k in _SECRET_KEYS:
            if data.get(k) and data[k] != _MASK:
                data[k] = _encode(data[k])
        with path.open("w") as fh:
            json.dump(data, fh, indent=2)
        logger.info("Tenant config saved to %s", path)

    def masked(self) -> dict[str, Any]:
        """Return config with secret values replaced by mask."""
        raw = self.load()
        for k in _SECRET_KEYS:
            if raw.get(k):
                raw[k] = _MASK
        return raw

    def has_azure(self) -> bool:
        cfg = self.load()
        return bool(cfg.get("azure_tenant_id") and cfg.get("azure_client_id"))

    def has_gcp(self) -> bool:
        cfg = self.load()
        return bool(cfg.get("gcp_project_id"))


_store = TenantConfigStore()


def get_tenant_store() -> TenantConfigStore:
    return _store
