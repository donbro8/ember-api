from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from ember_api.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watch(watch_id: str = "watch-001", name: str = "Test Watch") -> MagicMock:
    w = MagicMock()
    w.watch_id = watch_id
    w.name = name
    w.query = "SELECT 1"
    w.schedule = "weekly"
    w.schedule_day = 1
    w.enabled = True
    w.notify_on_change = False
    return w


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_with_store():
    mock_store = MagicMock()
    mock_reader = MagicMock()

    watch = _make_watch()
    mock_store.create.return_value = watch
    mock_store.list.return_value = [watch]
    mock_store.get.return_value = watch
    mock_store.update.return_value = watch
    mock_store.delete.return_value = True

    run1 = MagicMock()
    run1.run_id = "run-aaa"
    mock_reader.list_runs.return_value = [run1]

    with TestClient(app) as c:
        app.state.watch_store = mock_store
        app.state.result_reader = mock_reader
        app.state.result_writer = None
        yield c, mock_store, mock_reader


@pytest.fixture()
def client_no_store():
    with TestClient(app) as c:
        app.state.watch_store = None
        app.state.result_reader = None
        app.state.result_writer = None
        yield c


# ---------------------------------------------------------------------------
# POST /watches
# ---------------------------------------------------------------------------

def test_post_watch_returns_201(client_with_store):
    client, mock_store, _ = client_with_store
    response = client.post("/watches", json={
        "name": "My Watch",
        "query": "SELECT 1",
        "schedule": "weekly",
        "schedule_day": 1,
    })
    assert response.status_code == 201


def test_post_watch_calls_create(client_with_store):
    client, mock_store, _ = client_with_store
    client.post("/watches", json={
        "name": "My Watch",
        "query": "SELECT 1",
        "schedule": "weekly",
    })
    mock_store.create.assert_called_once()


def test_post_watch_returns_watch_key(client_with_store):
    client, mock_store, _ = client_with_store
    response = client.post("/watches", json={
        "name": "My Watch",
        "query": "SELECT 1",
        "schedule": "monthly",
        "schedule_day": 15,
    })
    data = response.json()
    assert "watch" in data


def test_post_watch_invalid_schedule_day_weekly_returns_422(client_with_store):
    client, _, _ = client_with_store
    # schedule_day=7 is out of range for weekly (0–6)
    response = client.post("/watches", json={
        "name": "Bad Watch",
        "query": "SELECT 1",
        "schedule": "weekly",
        "schedule_day": 7,
    })
    assert response.status_code == 422


def test_post_watch_invalid_schedule_day_monthly_returns_422(client_with_store):
    client, _, _ = client_with_store
    # schedule_day=0 is out of range for monthly (1–31)
    response = client.post("/watches", json={
        "name": "Bad Watch",
        "query": "SELECT 1",
        "schedule": "monthly",
        "schedule_day": 0,
    })
    assert response.status_code == 422


def test_post_watch_invalid_schedule_value_returns_422(client_with_store):
    client, _, _ = client_with_store
    response = client.post("/watches", json={
        "name": "Bad Watch",
        "query": "SELECT 1",
        "schedule": "daily",
    })
    assert response.status_code == 422


def test_post_watch_no_store_returns_503(client_no_store):
    response = client_no_store.post("/watches", json={
        "name": "My Watch",
        "query": "SELECT 1",
        "schedule": "weekly",
    })
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /watches
# ---------------------------------------------------------------------------

def test_get_watches_returns_200(client_with_store):
    client, _, _ = client_with_store
    response = client.get("/watches")
    assert response.status_code == 200


def test_get_watches_returns_watches_key(client_with_store):
    client, _, _ = client_with_store
    response = client.get("/watches")
    data = response.json()
    assert "watches" in data
    assert isinstance(data["watches"], list)


def test_get_watches_no_store_returns_503(client_no_store):
    response = client_no_store.get("/watches")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /watches/{watch_id}
# ---------------------------------------------------------------------------

def test_get_watch_returns_200(client_with_store):
    client, _, _ = client_with_store
    response = client.get("/watches/watch-001")
    assert response.status_code == 200


def test_get_watch_returns_watch_and_recent_runs(client_with_store):
    client, _, _ = client_with_store
    response = client.get("/watches/watch-001")
    data = response.json()
    assert "watch" in data
    assert "recent_runs" in data
    assert isinstance(data["recent_runs"], list)


def test_get_watch_calls_list_runs(client_with_store):
    client, _, mock_reader = client_with_store
    client.get("/watches/watch-001")
    mock_reader.list_runs.assert_called_once_with("watch-001", 10)


def test_get_watch_not_found_returns_404(client_with_store):
    client, mock_store, _ = client_with_store
    mock_store.get.return_value = None
    response = client.get("/watches/nonexistent")
    assert response.status_code == 404


def test_get_watch_no_store_returns_503(client_no_store):
    response = client_no_store.get("/watches/watch-001")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# PATCH /watches/{watch_id}
# ---------------------------------------------------------------------------

def test_patch_watch_returns_200(client_with_store):
    client, _, _ = client_with_store
    response = client.patch("/watches/watch-001", json={"name": "Updated"})
    assert response.status_code == 200


def test_patch_watch_calls_update(client_with_store):
    client, mock_store, _ = client_with_store
    client.patch("/watches/watch-001", json={"name": "Updated"})
    mock_store.update.assert_called_once()


def test_patch_watch_returns_watch_key(client_with_store):
    client, _, _ = client_with_store
    response = client.patch("/watches/watch-001", json={"enabled": False})
    data = response.json()
    assert "watch" in data


def test_patch_watch_not_found_returns_404(client_with_store):
    client, mock_store, _ = client_with_store
    mock_store.get.return_value = None
    response = client.patch("/watches/nonexistent", json={"name": "X"})
    assert response.status_code == 404


def test_patch_watch_no_store_returns_503(client_no_store):
    response = client_no_store.patch("/watches/watch-001", json={"name": "X"})
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# DELETE /watches/{watch_id}
# ---------------------------------------------------------------------------

def test_delete_watch_returns_204(client_with_store):
    client, _, _ = client_with_store
    response = client.delete("/watches/watch-001")
    assert response.status_code == 204


def test_delete_watch_not_found_returns_404(client_with_store):
    client, mock_store, _ = client_with_store
    mock_store.delete.return_value = False
    response = client.delete("/watches/nonexistent")
    assert response.status_code == 404


def test_delete_watch_no_store_returns_503(client_no_store):
    response = client_no_store.delete("/watches/watch-001")
    assert response.status_code == 503
