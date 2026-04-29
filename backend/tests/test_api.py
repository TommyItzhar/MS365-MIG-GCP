"""
Backend smoke tests
© Itzhar Olivera Solutions & Strategy — Tom Yair Tommy Itzhar Olivera
"""
import pytest
from app import create_app, db


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"


def test_metrics_exposed(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"migration_devices_total" in resp.data
    assert b"migration_tasks_total" in resp.data


def test_seed_workplan(client):
    resp = client.post("/api/v1/migration/seed")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["seeded"] >= 50  # 54 tasks total

    # Calling seed twice should be idempotent
    resp2 = client.post("/api/v1/migration/seed")
    assert resp2.status_code == 201
    assert resp2.get_json()["seeded"] == 0


def test_list_tasks_after_seed(client):
    client.post("/api/v1/migration/seed")
    resp = client.get("/api/v1/migration/tasks")
    assert resp.status_code == 200
    tasks = resp.get_json()
    assert len(tasks) >= 50
    # Verify all 7 phases present
    phases = {t["phase"] for t in tasks}
    expected = {
        "pre_migration", "env_preparation", "intune_offboarding",
        "google_mdm_onboarding", "migration_execution", "cutover", "post_migration"
    }
    assert expected.issubset(phases)


def test_overall_progress(client):
    client.post("/api/v1/migration/seed")
    resp = client.get("/api/v1/migration/progress")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "overall" in data
    assert "by_phase" in data
    assert data["completed"] == 0


def test_filter_tasks_by_phase(client):
    client.post("/api/v1/migration/seed")
    resp = client.get("/api/v1/migration/tasks?phase=intune_offboarding")
    assert resp.status_code == 200
    tasks = resp.get_json()
    assert len(tasks) == 7  # phase 3 has tasks 3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
    assert all(t["phase"] == "intune_offboarding" for t in tasks)
