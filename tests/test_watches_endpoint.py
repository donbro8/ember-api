import dataclasses
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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


# ---------------------------------------------------------------------------
# POST /watches/{watch_id}/run
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_with_agent():
    mock_store = MagicMock()
    mock_reader = MagicMock()
    mock_writer = MagicMock()
    mock_agent = MagicMock()

    watch = _make_watch()
    mock_store.get.return_value = watch
    mock_store.record_run.return_value = None

    # No recent runs by default
    mock_reader.list_runs.return_value = []

    # PipelineOutput mock
    output = MagicMock()
    output.run_id = "run-new-001"
    output.query_type = "search"
    output.results = []
    output.trace = {}
    output.markdown = "# Result"
    mock_agent.execute = AsyncMock(return_value=output)

    with TestClient(app) as c:
        app.state.watch_store = mock_store
        app.state.result_reader = mock_reader
        app.state.result_writer = mock_writer
        app.state.ember_agent = mock_agent
        app.state.change_detector = None
        yield c, mock_store, mock_reader, mock_writer, mock_agent


def test_run_watch_returns_200(client_with_agent):
    client, _, _, _, _ = client_with_agent
    response = client.post("/watches/watch-001/run")
    assert response.status_code == 200


def test_run_watch_returns_run_id_and_cached(client_with_agent):
    client, _, _, _, _ = client_with_agent
    response = client.post("/watches/watch-001/run")
    data = response.json()
    assert "run_id" in data
    assert data["run_id"] == "run-new-001"
    assert data["cached"] is False


def test_run_watch_calls_agent_execute(client_with_agent):
    client, _, _, _, mock_agent = client_with_agent
    client.post("/watches/watch-001/run")
    mock_agent.execute.assert_called_once_with("SELECT 1")


def test_run_watch_writes_result(client_with_agent):
    client, _, _, mock_writer, _ = client_with_agent
    client.post("/watches/watch-001/run")
    mock_writer.write_run.assert_called_once()


def test_run_watch_records_run_on_store(client_with_agent):
    client, mock_store, _, _, _ = client_with_agent
    client.post("/watches/watch-001/run")
    mock_store.record_run.assert_called_once_with("watch-001", "run-new-001")


def test_run_watch_not_found_returns_404(client_with_agent):
    client, mock_store, _, _, _ = client_with_agent
    mock_store.get.return_value = None
    response = client.post("/watches/nonexistent/run")
    assert response.status_code == 404


def test_run_watch_no_agent_returns_503(client_with_store):
    client, _, _ = client_with_store
    app.state.ember_agent = None
    app.state.result_writer = MagicMock()
    response = client.post("/watches/watch-001/run")
    assert response.status_code == 503


def test_run_watch_no_writer_returns_503(client_with_store):
    client, _, _ = client_with_store
    app.state.ember_agent = MagicMock()
    app.state.result_writer = None
    response = client.post("/watches/watch-001/run")
    assert response.status_code == 503


def test_run_watch_rate_limit_429(client_with_agent):
    client, _, mock_reader, _, _ = client_with_agent
    now = datetime.now(tz=timezone.utc)
    # Return 3 runs all within the last 24h
    runs = []
    for i in range(3):
        r = MagicMock()
        r.created_at = now
        runs.append(r)
    mock_reader.list_runs.return_value = runs
    response = client.post("/watches/watch-001/run")
    assert response.status_code == 429


def test_run_watch_rate_limit_allows_old_runs(client_with_agent):
    """Runs older than 24h should not count toward the rate limit."""
    from datetime import timedelta
    client, _, mock_reader, _, _ = client_with_agent
    now = datetime.now(tz=timezone.utc)
    # 3 runs but all older than 24h
    runs = []
    for i in range(3):
        r = MagicMock()
        r.created_at = now - timedelta(hours=25)
        runs.append(r)
    mock_reader.list_runs.return_value = runs
    response = client.post("/watches/watch-001/run")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /watches/{watch_id}/changes
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _FakeChangeEntry:
    change_id: str
    watch_id: str
    run_id: str
    previous_run_id: str | None
    change_type: str
    canonical_id: str
    display_label: str
    detail: str
    created_at: datetime


@pytest.fixture()
def client_with_changes():
    mock_store = MagicMock()
    mock_detector = MagicMock()

    watch = _make_watch()
    mock_store.get.return_value = watch

    entry = _FakeChangeEntry(
        change_id="chg-001",
        watch_id="watch-001",
        run_id="run-aaa",
        previous_run_id=None,
        change_type="added",
        canonical_id="canonical-001",
        display_label="Drug A",
        detail="New trial found",
        created_at=datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    mock_detector.get_changes.return_value = [entry]

    with TestClient(app) as c:
        app.state.watch_store = mock_store
        app.state.change_detector = mock_detector
        app.state.result_reader = None
        app.state.result_writer = None
        app.state.ember_agent = None
        yield c, mock_store, mock_detector


def test_get_changes_returns_200(client_with_changes):
    client, _, _ = client_with_changes
    response = client.get("/watches/watch-001/changes")
    assert response.status_code == 200


def test_get_changes_returns_changes_list(client_with_changes):
    client, _, _ = client_with_changes
    response = client.get("/watches/watch-001/changes")
    data = response.json()
    assert "changes" in data
    assert isinstance(data["changes"], list)
    assert len(data["changes"]) == 1
    assert data["changes"][0]["change_id"] == "chg-001"


def test_get_changes_respects_limit(client_with_changes):
    client, _, mock_detector = client_with_changes
    client.get("/watches/watch-001/changes?limit=25")
    mock_detector.get_changes.assert_called_once_with("watch-001", 25)


def test_get_changes_default_limit(client_with_changes):
    client, _, mock_detector = client_with_changes
    client.get("/watches/watch-001/changes")
    mock_detector.get_changes.assert_called_once_with("watch-001", 50)


def test_get_changes_not_found_returns_404(client_with_changes):
    client, mock_store, _ = client_with_changes
    mock_store.get.return_value = None
    response = client.get("/watches/nonexistent/changes")
    assert response.status_code == 404


def test_get_changes_no_detector_returns_503(client_with_store):
    client, _, _ = client_with_store
    app.state.change_detector = None
    response = client.get("/watches/watch-001/changes")
    assert response.status_code == 503


def test_get_changes_includes_change_summary(client_with_changes):
    """changes response includes change_summary from latest run."""
    client, _, _ = client_with_changes

    # Wire a result_reader that returns a run with change_summary
    mock_reader = MagicMock()
    latest_run = MagicMock()
    latest_run.change_summary = "2 new drugs added, 1 removed"
    mock_reader.list_runs.return_value = [latest_run]
    app.state.result_reader = mock_reader

    response = client.get("/watches/watch-001/changes")
    data = response.json()
    assert "change_summary" in data
    assert data["change_summary"] == "2 new drugs added, 1 removed"


def test_get_changes_change_summary_null_when_no_reader(client_with_changes):
    """change_summary is null when result_reader is not available."""
    client, _, _ = client_with_changes
    app.state.result_reader = None

    response = client.get("/watches/watch-001/changes")
    data = response.json()
    assert "change_summary" in data
    assert data["change_summary"] is None
