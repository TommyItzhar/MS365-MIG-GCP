"""MS365 → GCP Migration Engine — FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# Global mutable state shared between the app lifecycle and route handlers.
# Populated during startup; never reassigned after that.
app_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise all singletons on startup; tear down cleanly on shutdown.

    In development the app starts even without GCP/M365 credentials so the
    Tenants Connection UI is accessible for initial configuration.
    Migration endpoints return 503 until credentials are provided.
    """
    logger.info("migration_engine_startup")

    from app.config.settings import get_settings
    from app.auth.auth_manager import AuthManager
    from app.errors.error_handler import DLQPublisher, ErrorAggregator
    from app.monitoring.monitoring import MetricsReporter
    from app.orchestrator.job_orchestrator import JobOrchestrator
    from app.state.state_manager import StateManager
    from app.throttle.throttle_manager import ThrottleManager
    from app.writers.gcs_writer import GCSWriter

    settings = get_settings()

    try:
        auth = await AuthManager.create()
        throttle = ThrottleManager()
        state = StateManager()
        gcs = GCSWriter()
        metrics = MetricsReporter()
        errors = ErrorAggregator()
        dlq = DLQPublisher()

        orchestrator = JobOrchestrator(
            auth=auth,
            throttle=throttle,
            state=state,
            gcs=gcs,
            metrics=metrics,
            errors=errors,
            dlq=dlq,
        )

        app_state.update(
            auth=auth, throttle=throttle, state=state,
            gcs=gcs, metrics=metrics, errors=errors,
            dlq=dlq, orchestrator=orchestrator,
        )
        logger.info("migration_engine_ready")

    except Exception as exc:
        if settings.environment == "development":
            # Degraded start — health + setup endpoints still work.
            # Admin uses Tenants Connection UI to add credentials.
            logger.warning(
                "migration_engine_degraded — credentials not configured: %s. "
                "Open http://localhost:3000 and go to Tenants Connection.", exc
            )
        else:
            raise  # Hard failure in staging / production

    yield
    logger.info("migration_engine_shutdown")


def create_app() -> FastAPI:
    from app.config.settings import get_settings
    from app.monitoring.monitoring import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="MS365 → GCP Migration Engine",
        version="2.0.0",
        description=(
            "Enterprise-grade Microsoft 365 to GCP full-tenant migration platform. "
            "AvePoint Fly / BitTitan MigrationWiz architectural parity."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.router import router
    app.include_router(router)

    return app
