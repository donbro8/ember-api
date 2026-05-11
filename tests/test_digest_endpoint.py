"""Tests for the GET /digest endpoint."""

from dataclasses import dataclass
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

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


@dataclass
class _FakeDigestOutput:
    period_start: date
    period_end: date
    summary: str
    per_watch: list
    top_opportunities: list
    stable_watches: list


@dataclass
class _FakeWatchDigestSection:
    watch_name: str
    summary: str
    change_count: int
    highlight: str | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_with_stores():
    """Client with all three stores available and DigestGenerator mocked."""
    mock_store = MagicMock()
    mock_detector = MagicMock()
    mock_reader = MagicMock()

    watch = _make_watch()
    mock_store.list.return_value = [watch]

    # Changes for the watch
    change = MagicMock()
    change.change_id = "chg-001"
    mock_detector.get_changes.return_value = [change]

    # Latest run with results
    latest_run = MagicMock()
    latest_run.run_id = "run-aaa"
    latest_run.change_summary = "One new drug found"
    mock_reader.list_runs.return_value = [latest_run]

    result = MagicMock()
    result.drug_name = "Drug A"
    mock_reader.get_run.return_value = [result]

    fake_output = _FakeDigestOutput(
        period_start=date(2026, 5, 3),
        period_end=date(2026, 5, 10),
        summary="One watch had changes this week.",
        per_watch=[
            _FakeWatchDigestSection(
                watch_name="Test Watch",
                summary="One new drug found",
                change_count=1,
            )
        ],
        top_opportunities=[],
        stable_watches=[],
    )

    mock_generator = MagicMock()
    mock_generator.generate_digest = AsyncMock(return_value=fake_output)

    with TestClient(app) as c:
        app.state.watch_store = mock_store
        app.state.change_detector = mock_detector
        app.state.result_reader = mock_reader
        app.state.result_writer = None
        app.state.ember_agent = None
        yield c, mock_store, mock_detector, mock_reader, mock_generator


@pytest.fixture()
def client_no_stores():
    """Client with no stores available."""
    with TestClient(app) as c:
        app.state.watch_store = None
        app.state.change_detector = None
        app.state.result_reader = None
        app.state.result_writer = None
        app.state.ember_agent = None
        yield c


# ---------------------------------------------------------------------------
# Tests: structured output
# ---------------------------------------------------------------------------


def test_digest_returns_200(client_with_stores):
    client, _, _, _, mock_gen = client_with_stores
    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        response = client.get("/digest?period_days=7")
    assert response.status_code == 200


def test_digest_returns_structured_output(client_with_stores):
    client, _, _, _, mock_gen = client_with_stores
    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        response = client.get("/digest?period_days=7")
    data = response.json()
    assert "summary" in data
    assert "per_watch" in data
    assert "period_start" in data
    assert "period_end" in data
    assert "top_opportunities" in data
    assert "stable_watches" in data
    assert "dashboard" in data


def test_digest_period_dates_are_iso_strings(client_with_stores):
    client, _, _, _, mock_gen = client_with_stores
    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        response = client.get("/digest?period_days=7")
    data = response.json()
    assert data["period_start"] == "2026-05-03"
    assert data["period_end"] == "2026-05-10"


def test_digest_per_watch_section(client_with_stores):
    client, _, _, _, mock_gen = client_with_stores
    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        response = client.get("/digest?period_days=7")
    data = response.json()
    assert len(data["per_watch"]) == 1
    section = data["per_watch"][0]
    assert section["watch_name"] == "Test Watch"
    assert section["change_count"] == 1


def test_digest_includes_aggregate_dashboard_payload(client_with_stores):
    client, _, _, mock_reader, mock_gen = client_with_stores

    result = MagicMock()
    result.drug_name = "Drug A"
    result.source = "pubmed"
    result.suppression_metadata = {"suppressed": True}
    mock_reader.get_run.return_value = [result]

    latest_run = MagicMock()
    latest_run.run_id = "run-aaa"
    latest_run.change_summary = "One new drug found"
    latest_run.status = "completed"
    mock_reader.list_runs.return_value = [latest_run]

    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        response = client.get("/digest?period_days=7")
    data = response.json()

    dashboard = data["dashboard"]
    assert dashboard["top_opportunities"] == data["top_opportunities"]
    assert "recent_changes" in dashboard
    assert "per_watch_latest_results" in dashboard
    assert "source_counts" in dashboard
    assert "status_counts" in dashboard
    assert "suppressed_count" in dashboard
    assert "links" in dashboard
    assert dashboard["source_counts"]["pubmed"] == 1
    assert dashboard["status_counts"]["completed"] == 1
    assert dashboard["suppressed_count"] == 1

    latest = dashboard["per_watch_latest_results"][0]
    assert latest["watch_id"] == "watch-001"
    assert latest["latest_run_id"] == "run-aaa"
    assert latest["watch_link"] == "/watches/watch-001"
    assert latest["run_link"] == "/results?run_id=run-aaa"


def test_digest_calls_generator_with_period_days(client_with_stores):
    client, _, _, _, mock_gen = client_with_stores
    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        client.get("/digest?period_days=14")
    mock_gen.generate_digest.assert_called_once()
    _, kwargs = mock_gen.generate_digest.call_args
    assert kwargs.get("period_days", mock_gen.generate_digest.call_args[0][1] if len(mock_gen.generate_digest.call_args[0]) > 1 else None) == 14


def test_digest_default_period_days(client_with_stores):
    client, _, _, _, mock_gen = client_with_stores
    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        client.get("/digest")
    mock_gen.generate_digest.assert_called_once()
    args, _ = mock_gen.generate_digest.call_args
    assert args[1] == 7  # second positional arg is period_days


# ---------------------------------------------------------------------------
# Tests: 503 when stores unavailable
# ---------------------------------------------------------------------------


def test_digest_503_when_watch_store_unavailable(client_no_stores):
    response = client_no_stores.get("/digest")
    assert response.status_code == 503


def test_digest_503_when_change_detector_unavailable():
    with TestClient(app) as c:
        app.state.watch_store = MagicMock()
        app.state.change_detector = None
        app.state.result_reader = MagicMock()
        response = c.get("/digest")
    assert response.status_code == 503


def test_digest_503_when_result_reader_unavailable():
    with TestClient(app) as c:
        app.state.watch_store = MagicMock()
        app.state.change_detector = MagicMock()
        app.state.result_reader = None
        response = c.get("/digest")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Tests: empty watches
# ---------------------------------------------------------------------------


def test_digest_with_no_watches(client_with_stores):
    client, mock_store, _, _, mock_gen = client_with_stores
    mock_store.list.return_value = []

    empty_output = _FakeDigestOutput(
        period_start=date(2026, 5, 3),
        period_end=date(2026, 5, 10),
        summary="No changes across any watch.",
        per_watch=[],
        top_opportunities=[],
        stable_watches=[],
    )
    mock_gen.generate_digest = AsyncMock(return_value=empty_output)

    with patch("ember_agents.synthesis.DigestGenerator", return_value=mock_gen):
        response = client.get("/digest")

    assert response.status_code == 200
    data = response.json()
    assert data["per_watch"] == []
    assert data["summary"] == "No changes across any watch."
