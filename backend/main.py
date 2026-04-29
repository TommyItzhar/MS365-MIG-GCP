"""Application entry point for Cloud Run / local dev."""
from __future__ import annotations

import uvicorn

from app import create_app
from app.config.settings import get_settings

app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=1,  # Single worker; concurrency is handled within the async event loop
        log_level=settings.log_level.lower(),
        access_log=False,  # Structured logging handles request logging
    )
