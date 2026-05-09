from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from ember_api.main import app


def _mock_agent():
    agent = MagicMock()

    async def async_run(query):
        for chunk in ["Result", " ", "data"]:
            yield chunk

    agent.run = async_run
    return agent


@pytest.fixture()
def client():
    with TestClient(app) as c:
        app.state.ember_agent = _mock_agent()
        yield c


def test_query_returns_response(client):
    response = client.post("/query", json={"query": "PD-1 inhibitors"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["response"] == "Result data"


def test_query_no_agent_field_accepted(client):
    """POST /query requires only 'query' — no agent parameter needed."""
    response = client.post("/query", json={"query": "mAb biosimilars"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data


def test_query_empty_body_returns_422(client):
    response = client.post("/query")
    assert response.status_code == 422


def test_query_missing_query_field_returns_422(client):
    response = client.post("/query", json={"message": "wrong field"})
    assert response.status_code == 422
