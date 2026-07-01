from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import TaskStore
from app.main import app
from app.worker.executor import TaskExecutor


def client(tmp_path):
    get_settings.cache_clear()
    settings = get_settings()
    settings.data_dir = tmp_path / "data"
    settings.work_dir = tmp_path / "work"
    settings.db_path = tmp_path / "data" / "tasks.sqlite"
    settings.auth_enabled = False
    settings.ensure_directories()
    return TestClient(app)


def test_health_and_discover(tmp_path):
    c = client(tmp_path)
    assert c.get("/health").json() == {"status": "ok"}
    body = c.get("/discover").json()
    assert body["name"] == "Android Unity Compare Service"
    assert "/api/v1/comparisons" in body["auth"]["api_key_endpoints"]


def test_create_and_get_batch_task(tmp_path):
    c = client(tmp_path)
    response = c.post(
        "/api/v1/batch-comparisons",
        json={
            "packageName": "com.example.game",
            "versions": [
                {"versionCode": "102", "versionName": "1.0.2"},
                {"versionCode": "100", "versionName": "1.0.0"},
                {"versionCode": "101", "versionName": "1.0.1"},
            ],
        },
    )
    assert response.status_code == 202
    task = c.get(f"/api/v1/tasks/{response.json()['taskId']}").json()
    assert task["status"] == "queued"
    assert task["progress"] == {
        "versionsTotal": 3,
        "versionsDownloaded": 0,
        "versionsDumped": 0,
        "comparisonsTotal": 2,
        "comparisonsCompleted": 0,
        "comparisonsFailed": 0,
    }
    assert task["comparisons"][0]["oldVersion"] == "1.0.0"
    assert task["comparisons"][1]["newVersion"] == "1.0.2"


def test_api_key_gate(tmp_path):
    c = client(tmp_path)
    settings = get_settings()
    settings.auth_enabled = True
    settings.api_keys = "secret"
    try:
        assert c.get("/api/v1/tasks/missing").status_code == 401
        assert c.get("/api/v1/tasks/missing", headers={"X-API-Key": "secret"}).status_code == 404
    finally:
        get_settings.cache_clear()


def test_worker_executor_marks_task_done(tmp_path):
    c = client(tmp_path)
    task_id = c.post(
        "/api/v1/comparisons",
        json={
            "packageName": "com.example.game",
            "oldVersion": {"versionCode": "100", "versionName": "1.0.0"},
            "newVersion": {"versionCode": "101", "versionName": "1.0.1"},
        },
    ).json()["taskId"]

    settings = get_settings()
    store = TaskStore(settings.task_db_path)
    assert store.claim_tasks(1) == [task_id]
    TaskExecutor(settings, store).run(task_id)

    task = c.get(f"/api/v1/tasks/{task_id}").json()
    assert task["status"] == "succeeded"
    assert task["progress"]["versionsDumped"] == 2
    assert task["progress"]["comparisonsCompleted"] == 1
