"""Celery worker entrypoint.

Run with: celery -A celery_worker.celery_app worker --loglevel=info
"""
from app import create_app

flask_app = create_app()
# After create_app(), the Celery instance is registered on flask_app.extensions["celery"]
celery_app = flask_app.extensions["celery"]

# Importing the tasks module registers the @shared_task decorated tasks
from app.services import tasks  # noqa: E402,F401
