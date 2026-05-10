from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from ember_api.main import app


@pytest.fixture()
def client_with_reader():
    mock_reader = MagicMock()

    run = MagicMock()
    run.results = [{"id": "r1", "title": "Result one"}, {"id": "r2", "title": "Result two"}]
    mock_reader.get_run.return_value = run

    run_summary_1 = MagicMock()
    run_summary_1.run_id = "run-aaa"
    run_summary_2 = MagicMock()
    run_summary_2.run_id = "run-bbb"
    mock_reader.list_runs.return_value = [run_summary_1, run_summary_2]

    with TestClient(app) as c:
        app.state.result_reader = mock_reader
        app.state.result_writer = None
        yield c, mock_reader


@pytest.fixture()
def client_no_reader():
    with TestClient(app) as c:
        app.state.result_reader = None
        app.state.result_writer = None
        yield c


# ---------------------------------------------------------------------------
# GET /results
# ---------------------------------------------------------------------------


def test_get_results_returns_200(client_with_reader):
    client, mock_reader = client_with_reader
    response = client.get("/results", params={"run_id": "run-abc"})
    assert response.status_code == 200


def test_get_results_calls_get_run(client_with_reader):
    client, mock_reader = client_with_reader
    client.get("/results", params={"run_id": "run-abc"})
    mock_reader.get_run.assert_called_once_with("run-abc")


def test_get_results_returns_results_key(client_with_reader):
    client, mock_reader = client_with_reader
    response = client.get("/results", params={"run_id": "run-abc"})
    data = response.json()
    assert "results" in data
    assert isinstance(data["results"], list)


def test_get_results_missing_run_id_returns_422(client_with_reader):
    client, _ = client_with_reader
    response = client.get("/results")
    assert response.status_code == 422


def test_get_results_no_reader_returns_503(client_no_reader):
    response = client_no_reader.get("/results", params={"run_id": "run-abc"})
    assert response.status_code == 503


def test_get_results_unknown_run_id_returns_404(client_with_reader):
    """If get_run returns None, endpoint should return 404."""
    client, mock_reader = client_with_reader
    mock_reader.get_run.return_value = None
    response = client.get("/results", params={"run_id": "nonexistent"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------


def test_get_runs_returns_200(client_with_reader):
    client, _ = client_with_reader
    response = client.get("/runs", params={"watch_id": "watch-xyz"})
    assert response.status_code == 200


def test_get_runs_calls_list_runs(client_with_reader):
    client, mock_reader = client_with_reader
    client.get("/runs", params={"watch_id": "watch-xyz", "limit": "5"})
    mock_reader.list_runs.assert_called_once_with("watch-xyz", 5)


def test_get_runs_returns_runs_key(client_with_reader):
    client, _ = client_with_reader
    response = client.get("/runs", params={"watch_id": "watch-xyz"})
    data = response.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)


def test_get_runs_missing_watch_id_returns_422(client_with_reader):
    client, _ = client_with_reader
    response = client.get("/runs")
    assert response.status_code == 422


def test_get_runs_no_reader_returns_503(client_no_reader):
    response = client_no_reader.get("/runs", params={"watch_id": "watch-xyz"})
    assert response.status_code == 503
