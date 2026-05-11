"""Integration tests for POST /query using EmberAgent.

All external dependencies are mocked via app.state.ember_agent.
The tests exercise the /query endpoint end-to-end by mocking EmberAgent.execute()
returning a PipelineOutput-like object with the expected markdown output.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ember_api.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helper to create an async mock for EmberAgent.execute()
# ---------------------------------------------------------------------------


def _make_mock_agent(output_chunks: list[str]) -> MagicMock:
    """Return a mock EmberAgent whose execute() returns a PipelineOutput-like object."""
    markdown = "".join(output_chunks)

    output = MagicMock()
    output.run_id = "test-run-id"
    output.markdown = markdown
    output.results = []
    output.trace = {}
    output.query_type = "search"
    output.synthesis_overview = None

    agent = MagicMock()

    async def async_execute(query):
        return output

    agent.execute = async_execute
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_simple_query_end_to_end():
    """POST /query returns ranked candidates."""
    output = (
        "## Ranked Candidates (1)\n\n"
        "### 1. Osimertinib\n"
        "**Target:** EGFR\n\n"
        "| Score | Overall | Semantic | Structured | Evidence |\n"
        "|---|---|---|---|---|\n"
        "| Scores | 0.820 | 0.80 | 0.85 | 0.80 |\n\n"
        "**Overall:** 0.820\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post("/query", json={"query": "EGFR inhibitors for NSCLC"})

    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    body = data["response"]

    assert "Ranked Candidates" in body
    assert "Osimertinib" in body
    assert "Overall" in body
    assert "0.820" in body


def test_response_includes_source_provenance():
    """Response must include contributing sources with attribution."""
    output = (
        "## Ranked Candidates (1)\n\n"
        "### 1. DrugA\n\n"
        "**Contributing Sources:** ClinicalTrials.gov, PubMed\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post("/query", json={"query": "HER2 biosimilars"})

    assert response.status_code == 200
    body = response.json()["response"]

    assert "Contributing Sources" in body
    assert "ClinicalTrials.gov" in body
    assert "PubMed" in body


def test_disambiguation_flow():
    """When disambiguation is required, response surfaces options."""
    output = (
        "## Disambiguation required\n\n"
        "The term **VEGF** needs clarification.\n\n"
        "Did you mean VEGF-A (VEGFA) or VEGF-C (VEGFC)?\n"
        "1. VEGF-A\n"
        "2. VEGF-C\n\n"
        "Search is **paused** pending your selection.\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post("/query", json={"query": "VEGF inhibitors for oncology"})

    assert response.status_code == 200
    body = response.json()["response"]

    assert "Disambiguation required" in body
    assert "VEGF" in body
    assert "paused" in body.lower()


def test_gate_narrowing_too_broad():
    """When gate returns too_broad, response includes narrowing options."""
    output = (
        "## Search too broad\n\n"
        "Your query covers too many candidates. Please narrow your search.\n\n"
        "Which therapeutic area would you like to focus on?\n"
        "1. oncology — Oncology\n"
        "2. cardiology — Cardiology\n\n"
        "Search is **paused** pending your selection.\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post("/query", json={"query": "all biologic drugs"})

    assert response.status_code == 200
    body = response.json()["response"]

    assert "Search too broad" in body
    assert "oncology" in body.lower() or "Oncology" in body
    assert "paused" in body.lower()


def test_patent_not_yet_expired_window():
    """Query with 'not expired yet' semantics surfaces temporal signal and returns candidates."""
    output = (
        "## Extracted Signals\n\n"
        "- **Target:** VEGF\n"
        "- **Indication:** colorectal cancer\n"
        "- **Temporal:** not expired\n\n"
        "## Ranked Candidates (1)\n\n"
        "### 1. Bevacizumab\n"
        "**Target:** VEGF\n\n"
        "**Evidence:** 3 patents from USPTO.\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post(
        "/query",
        json={
            "query": "VEGF inhibitors for colorectal cancer with patents not expired yet"
        },
    )

    assert response.status_code == 200
    body = response.json()["response"]

    assert "not expired" in body
    assert "Bevacizumab" in body
    assert "3 patent" in body


def test_multiple_ranked_candidates_ordering():
    """Multiple candidates are returned in ranked order (rank 1 before rank 2)."""
    output = (
        "## Ranked Candidates (2)\n\n"
        "### 1. DrugHigh\n"
        "**Target:** PD-1\n"
        "**Overall score:** 0.90\n\n"
        "### 2. DrugLow\n"
        "**Target:** PD-1\n"
        "**Overall score:** 0.45\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post("/query", json={"query": "PD-1 antibodies"})

    assert response.status_code == 200
    body = response.json()["response"]

    assert "DrugHigh" in body
    assert "DrugLow" in body
    assert body.index("DrugHigh") < body.index("DrugLow")
    assert "2 candidate" in body or "Ranked Candidates (2" in body


def test_synthesis_summary_present():
    """Response includes synthesis summary section."""
    output = (
        "## Ranked Candidates (1)\n\n"
        "### 1. DrugS\n\n"
        "## Synthesis Summary\n\n"
        "Summary for DrugS.\n"
    )
    app.state.ember_agent = _make_mock_agent([output])
    app.state.result_reader = None
    app.state.result_writer = None
    response = client.post("/query", json={"query": "CD20 antibodies"})

    assert response.status_code == 200
    body = response.json()["response"]

    assert "Synthesis Summary" in body
