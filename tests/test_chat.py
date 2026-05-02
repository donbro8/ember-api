from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from ember_api.main import app


client = TestClient(app)


def _mock_agent():
    agent = MagicMock()

    async def async_run(message):
        for chunk in ["Hello", " ", "world"]:
            yield chunk

    agent.run = async_run
    return agent


@patch("ember_api.routes.chat.get_agent")
def test_chat_returns_response(mock_get_agent):
    mock_get_agent.return_value = _mock_agent()
    response = client.post("/chat", json={"message": "test"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["response"] == "Hello world"


def test_chat_empty_body_returns_422():
    response = client.post("/chat")
    assert response.status_code == 422
