from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ember_api.main import app


@pytest.fixture()
def client_with_agent():
    """TestClient with a mock EmberAgent wired in app.state."""
    with TestClient(app) as c:
        app.state.ember_agent = MagicMock()
        yield c


@pytest.fixture()
def client_no_agent():
    """TestClient with no EmberAgent (degraded mode)."""
    with TestClient(app) as c:
        app.state.ember_agent = None
        yield c


# ---------------------------------------------------------------------------
# Helpers to mock all service checks at once
# ---------------------------------------------------------------------------

_ALL_OK_SERVICES = {
    "bigquery": "ok",
    "google_api_key": "ok",
    "biologic_reference": "ok",
    "gemini": "ok",
}

_GEMINI_DOWN_SERVICES = {
    "bigquery": "ok",
    "google_api_key": "ok",
    "biologic_reference": "ok",
    "gemini": "unavailable: connection refused",
}


def _patch_checks(
    bigquery="ok", google_api_key="ok", biologic_reference="ok", gemini="ok"
):
    """Return a context-manager stack that patches all individual check functions."""
    return [
        patch("ember_api.routes.health._check_bigquery", return_value=bigquery),
        patch(
            "ember_api.routes.health._check_google_api_key", return_value=google_api_key
        ),
        patch(
            "ember_api.routes.health._check_biologic_reference",
            return_value=biologic_reference,
        ),
        patch(
            "ember_api.routes.health._check_external_endpoint",
            return_value=gemini,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: ok state
# ---------------------------------------------------------------------------


def test_health_returns_200():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_health_ok_state(client_with_agent):
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["agent_ready"] is True
    assert "services" in data
    assert data["services"]["gemini"] == "ok"
    assert data["services"]["bigquery"] == "ok"
    assert data["services"]["biologic_reference"] == "ok"
    assert "degraded_reason" not in data


def test_health_includes_env(client_with_agent):
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")

    data = response.json()
    assert "env" in data


# ---------------------------------------------------------------------------
# Tests: degraded state — critical service (gemini) down
# ---------------------------------------------------------------------------


def test_health_degraded_when_gemini_unavailable(client_with_agent):
    patches = _patch_checks(gemini="unavailable: connection refused")
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["agent_ready"] is False
    assert "degraded_reason" in data
    assert "gemini" in data["degraded_reason"]
    assert data["services"]["gemini"] != "ok"


def test_health_degraded_when_agent_not_initialized(client_no_agent):
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_no_agent.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["agent_ready"] is False
    assert "degraded_reason" in data


# ---------------------------------------------------------------------------
# Tests: non-critical service failures don't set agent_ready=false
# ---------------------------------------------------------------------------


def test_health_bigquery_unavailable_does_not_degrade_agent(client_with_agent):
    """BigQuery is not in CRITICAL_SERVICES — agent_ready should still be True."""
    patches = _patch_checks(bigquery="unavailable: permission denied")
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")

    data = response.json()
    # status may still be degraded due to non-ok services, but agent_ready depends only on
    # critical services + agent wired
    assert data["agent_ready"] is True
    assert data["services"]["bigquery"] == "unavailable: permission denied"


# ---------------------------------------------------------------------------
# Tests: services dict structure
# ---------------------------------------------------------------------------


def test_health_services_dict_has_expected_keys(client_with_agent):
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")

    data = response.json()
    services = data["services"]
    assert "bigquery" in services
    assert "google_api_key" in services
    assert "biologic_reference" in services
    assert "gemini" in services
    assert "result_store" in services


def test_health_result_store_ok_when_writer_available(client_with_agent):
    """result_store reports 'ok' when result_writer is wired."""
    app.state.result_writer = MagicMock()
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert data["services"]["result_store"] == "ok"
    app.state.result_writer = None


def test_health_result_store_unavailable_when_writer_none(client_with_agent):
    """result_store reports 'unavailable' when result_writer is None."""
    app.state.result_writer = None
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert data["services"]["result_store"] == "unavailable"


def test_health_services_includes_watch_store(client_with_agent):
    """watch_store key is present in services dict."""
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert "watch_store" in data["services"]


def test_health_watch_store_ok_when_wired(client_with_agent):
    """watch_store reports 'ok' when watch_store is wired."""
    from unittest.mock import MagicMock

    app.state.watch_store = MagicMock()
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert data["services"]["watch_store"] == "ok"
    app.state.watch_store = None


def test_health_watch_store_unavailable_when_none(client_with_agent):
    """watch_store reports 'unavailable' when watch_store is None."""
    app.state.watch_store = None
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert data["services"]["watch_store"] == "unavailable"


# ---------------------------------------------------------------------------
# Tests: synthesizer status
# ---------------------------------------------------------------------------


def test_health_services_includes_synthesizer(client_with_agent):
    """synthesizer key is present in services dict."""
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert "synthesizer" in data["services"]


def test_health_synthesizer_ok_when_available(client_with_agent):
    """synthesizer reports 'ok' when synthesizer_available is True."""
    app.state.synthesizer_available = True
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert data["services"]["synthesizer"] == "ok"
    app.state.synthesizer_available = False


def test_health_synthesizer_unavailable_when_false(client_with_agent):
    """synthesizer reports 'unavailable' when synthesizer_available is False."""
    app.state.synthesizer_available = False
    patches = _patch_checks()
    with patches[0], patches[1], patches[2], patches[3]:
        response = client_with_agent.get("/health")
    data = response.json()
    assert data["services"]["synthesizer"] == "unavailable"
