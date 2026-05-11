from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from ember_api.main import app


def _make_pipeline_output(
    run_id="run-123",
    markdown="Result data",
    cached=False,
    synthesis_overview="Overview of results",
):
    output = MagicMock()
    output.run_id = run_id
    output.markdown = markdown
    output.results = []
    output.trace = {}
    output.query_type = "search"
    output.synthesis_overview = synthesis_overview
    return output


def _mock_agent(run_id="run-123"):
    agent = MagicMock()

    async def async_execute(query):
        return _make_pipeline_output(run_id=run_id)

    agent.execute = async_execute
    return agent


@pytest.fixture()
def client():
    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent()
        app.state.result_writer = None
        app.state.result_reader = None
        yield c


def test_query_returns_response(client):
    response = client.post("/query", json={"query": "PD-1 inhibitors"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["response"] == "Result data"


def test_query_returns_run_id(client):
    response = client.post("/query", json={"query": "PD-1 inhibitors"})
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["run_id"] == "run-123"


def test_query_returns_cached_false_on_miss(client):
    response = client.post("/query", json={"query": "PD-1 inhibitors"})
    assert response.status_code == 200
    data = response.json()
    assert "cached" in data
    assert data["cached"] is False


def test_query_no_agent_field_accepted(client):
    """POST /query requires only 'query' — no agent parameter needed."""
    response = client.post("/query", json={"query": "mAb biosimilars"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "run_id" in data
    assert "cached" in data


def test_query_empty_body_returns_422(client):
    response = client.post("/query")
    assert response.status_code == 422


def test_query_missing_query_field_returns_422(client):
    response = client.post("/query", json={"message": "wrong field"})
    assert response.status_code == 422


def test_query_cache_hit_returns_cached_true():
    """When result_reader returns a cached run, response has cached=True."""
    cached_run = MagicMock()
    cached_run.markdown = "Cached response"
    cached_run.run_id = "cached-run-456"

    mock_reader = MagicMock()
    mock_reader.get_cached.return_value = cached_run

    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent()
        app.state.result_writer = None
        app.state.result_reader = mock_reader

        response = c.post("/query", json={"query": "PD-1 inhibitors"})

    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is True
    assert data["run_id"] == "cached-run-456"
    assert data["response"] == "Cached response"


def test_query_cache_miss_calls_agent():
    """When result_reader returns None (miss), the agent is called."""
    mock_reader = MagicMock()
    mock_reader.get_cached.return_value = None

    mock_writer = MagicMock()

    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent(run_id="fresh-run-789")
        app.state.result_writer = mock_writer
        app.state.result_reader = mock_reader

        response = c.post("/query", json={"query": "EGFR mutations"})

    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is False
    assert data["run_id"] == "fresh-run-789"
    # writer should have been called
    mock_writer.write_run.assert_called_once()


def test_query_failed_gate_cache_calls_agent():
    """Cached missing_core_fields responses are stale and should be re-executed."""
    cached_run = MagicMock()
    cached_run.markdown = "**Gate outcome:** missing_core_fields"
    cached_run.run_id = "stale-run-123"

    mock_reader = MagicMock()
    mock_reader.get_cached.return_value = cached_run

    mock_writer = MagicMock()

    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent(run_id="fresh-run-789")
        app.state.result_writer = mock_writer
        app.state.result_reader = mock_reader

        response = c.post("/query", json={"query": "biosimilar opportunities"})

    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is False
    assert data["run_id"] == "fresh-run-789"
    mock_writer.write_run.assert_called_once()


def test_query_write_failure_does_not_block():
    """A write_run exception should not cause the endpoint to fail."""
    mock_reader = MagicMock()
    mock_reader.get_cached.return_value = None

    mock_writer = MagicMock()
    mock_writer.write_run.side_effect = RuntimeError("BQ write error")

    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent()
        app.state.result_writer = mock_writer
        app.state.result_reader = mock_reader

        response = c.post("/query", json={"query": "BRCA2"})

    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is False


def test_query_returns_synthesis_overview(client):
    """POST /query response includes synthesis_overview from agent output."""
    response = client.post("/query", json={"query": "PD-1 inhibitors"})
    assert response.status_code == 200
    data = response.json()
    assert "synthesis_overview" in data
    assert data["synthesis_overview"] == "Overview of results"


def test_query_cached_response_has_null_synthesis_overview():
    """When response is served from cache, synthesis_overview should be None."""
    cached_run = MagicMock()
    cached_run.markdown = "Cached response"
    cached_run.run_id = "cached-run-456"

    mock_reader = MagicMock()
    mock_reader.get_cached.return_value = cached_run

    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent()
        app.state.result_writer = None
        app.state.result_reader = mock_reader

        response = c.post("/query", json={"query": "PD-1 inhibitors"})

    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is True
    assert data["synthesis_overview"] is None
