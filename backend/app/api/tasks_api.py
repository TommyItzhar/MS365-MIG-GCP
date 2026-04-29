"""Celery task status polling endpoints."""
from flask import Blueprint, current_app, jsonify

bp = Blueprint("tasks_api", __name__)


@bp.get("/<celery_task_id>")
def task_status(celery_task_id: str):
    from celery.result import AsyncResult
    celery_app = current_app.extensions.get("celery")
    if celery_app is None:
        return jsonify({"error": "Celery not configured"}), 500
    result = AsyncResult(celery_task_id, app=celery_app)
    info = result.info if isinstance(result.info, dict) else (str(result.info) if result.info else None)
    return jsonify({
        "id": celery_task_id,
        "state": result.state,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
        "info": info,
    })
