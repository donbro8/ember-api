"""Integration tests for POST /chat with agent="search".

All external dependencies (LLM, BigQuery, ClinicalTrials.gov, PubMed, UniProt)
are mocked.  The tests exercise the SearchAgent pipeline end-to-end through the
FastAPI endpoint using a pre-configured SearchAgent injected via get_agent.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from ember_api.main import app
from ember_agents.search.agent import SearchAgent
from ember_agents.search.classify import DisambiguationRequest
from ember_agents.search.gate import GateResult, NarrowingRequest
from ember_agents.search.interpret import RawSignals, TemporalSignal

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers to build mock pipeline components
# ---------------------------------------------------------------------------


def _make_candidate(
    drug_name: str = "DrugX",
    target_label: str = "EGFR",
    matched_dimensions: list[str] | None = None,
    sources: list[tuple[str, str]] | None = None,
    n_trials: int = 2,
    n_patents: int = 1,
    n_articles: int = 3,
) -> MagicMock:
    """Build a mock Candidate object."""
    candidate = MagicMock()
    candidate.drug_name = drug_name
    target = MagicMock()
    target.label = target_label
    target.name = target_label
    target.identifier = target_label
    target.value = target_label
    candidate.target = target
    candidate.matched_dimensions = matched_dimensions or ["target", "indication"]

    # Source provenance mocks
    prov_list: list[MagicMock] = []
    for src_name, src_url in (sources or [("ClinicalTrials.gov", "https://clinicaltrials.gov")]):
        prov = MagicMock()
        prov.source_name = src_name
        prov.source_url = src_url
        prov_list.append(prov)
    candidate.contributing_sources = prov_list

    # Evidence counts
    candidate.trials = [MagicMock()] * n_trials
    candidate.patents = [MagicMock()] * n_patents
    candidate.articles = [MagicMock()] * n_articles
    candidate.synthesis_summary = f"Summary for {drug_name}."
    return candidate


def _make_scored_candidate(
    candidate: MagicMock | None = None,
    rank: int = 1,
    overall: float = 0.75,
    semantic: float = 0.70,
    structured: float = 0.80,
    evidence: float = 0.60,
) -> MagicMock:
    """Build a mock ScoredCandidate object."""
    sc = MagicMock()
    sc.candidate = candidate or _make_candidate()
    sc.rank = rank
    sc.overall_score = overall
    sc.semantic_score = semantic
    sc.structured_score = structured
    sc.evidence_score = evidence
    return sc


def _make_extractor(signals: RawSignals) -> AsyncMock:
    """Build a mock IntentExtractor that returns the given signals."""
    extractor = AsyncMock()
    extractor.extract = AsyncMock(return_value=signals)
    return extractor


def _make_fetcher(candidates: list[MagicMock]) -> AsyncMock:
    """Build a mock FetchOrchestrator that returns fixed candidates."""
    fetcher = AsyncMock()
    fetcher.fetch = AsyncMock(return_value=candidates)
    return fetcher


def _make_scorer(scored: list[MagicMock]) -> AsyncMock:
    """Build a mock MatchScorer that returns fixed scored candidates."""
    scorer = AsyncMock()
    scorer.score = AsyncMock(return_value=scored)
    return scorer


def _make_classifier(
    spec: MagicMock | None = None,
    disambiguations: list[DisambiguationRequest] | None = None,
) -> AsyncMock:
    """Build a mock ClassificationOrchestrator."""
    classifier = AsyncMock()
    result = MagicMock()
    result.spec = spec or MagicMock()
    result.disambiguations = disambiguations or []
    classifier.classify = AsyncMock(return_value=result)
    return classifier


def _make_gate(passed: bool = True, reason: str | None = None, narrowing: NarrowingRequest | None = None) -> AsyncMock:
    """Build a mock SearchGate."""
    gate = AsyncMock()
    gate.check = AsyncMock(return_value=GateResult(passed=passed, reason=reason, narrowing=narrowing))
    return gate


def _build_search_agent(
    signals: RawSignals | None = None,
    candidates: list[MagicMock] | None = None,
    scored: list[MagicMock] | None = None,
    classifier: AsyncMock | None = None,
    gate: AsyncMock | None = None,
) -> SearchAgent:
    """Build a SearchAgent with all external calls mocked."""
    _signals = signals or RawSignals(target=["EGFR"], indication=["NSCLC"])
    _candidates = candidates if candidates is not None else [_make_candidate()]
    _scored = scored if scored is not None else [_make_scored_candidate(candidate=_candidates[0])]

    return SearchAgent(
        intent_extractor=_make_extractor(_signals),
        classifier=classifier,
        gate=gate,
        fetcher=_make_fetcher(_candidates),
        scorer=_make_scorer(_scored),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("ember_api.routes.chat.get_agent")
def test_simple_query_end_to_end(mock_get_agent):
    """POST /chat with agent='search' returns ranked candidates."""
    candidate = _make_candidate(
        drug_name="Osimertinib",
        target_label="EGFR",
        sources=[("ClinicalTrials.gov", "https://clinicaltrials.gov")],
    )
    scored = [_make_scored_candidate(candidate=candidate, rank=1, overall=0.82)]
    agent = _build_search_agent(
        signals=RawSignals(target=["EGFR"], indication=["NSCLC"]),
        candidates=[candidate],
        scored=scored,
    )
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={"message": "EGFR inhibitors for NSCLC", "agent": "search"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    body = data["response"]

    # Should contain ranked candidate section
    assert "Ranked Candidates" in body
    assert "Osimertinib" in body
    # Scores table present
    assert "Overall" in body
    assert "0.820" in body


@patch("ember_api.routes.chat.get_agent")
def test_response_includes_source_provenance(mock_get_agent):
    """Response must include contributing sources with attribution."""
    candidate = _make_candidate(
        drug_name="DrugA",
        sources=[
            ("ClinicalTrials.gov", "https://clinicaltrials.gov"),
            ("PubMed", "https://pubmed.ncbi.nlm.nih.gov"),
        ],
    )
    scored = [_make_scored_candidate(candidate=candidate)]
    agent = _build_search_agent(candidates=[candidate], scored=scored)
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={"message": "HER2 biosimilars", "agent": "search"},
    )

    assert response.status_code == 200
    body = response.json()["response"]

    # Contributing sources section
    assert "Contributing Sources" in body
    assert "ClinicalTrials.gov" in body
    assert "PubMed" in body


@patch("ember_api.routes.chat.get_agent")
def test_disambiguation_flow(mock_get_agent):
    """When classifier returns disambiguation requests, response surfaces options."""
    disambig_request = DisambiguationRequest(
        dimension="target",
        raw_term="VEGF",
        question="Did you mean VEGF-A (VEGFA) or VEGF-C (VEGFC)?\n1. VEGF-A\n2. VEGF-C",
        options=[("VEGFA", "VEGF-A"), ("VEGFC", "VEGF-C")],
    )
    classifier = _make_classifier(disambiguations=[disambig_request])

    agent = _build_search_agent(classifier=classifier)
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={"message": "VEGF inhibitors for oncology", "agent": "search"},
    )

    assert response.status_code == 200
    body = response.json()["response"]

    # Disambiguation block must appear
    assert "Disambiguation required" in body
    assert "VEGF" in body
    # Should indicate search is paused
    assert "paused" in body.lower()


@patch("ember_api.routes.chat.get_agent")
def test_gate_narrowing_too_broad(mock_get_agent):
    """When gate returns too_broad, response includes narrowing options."""
    narrowing = NarrowingRequest(
        dimension="therapeutic_area",
        question=(
            "Your search is too broad. Which therapeutic area would you like to focus on?\n"
            "1. oncology — Oncology\n"
            "2. cardiology — Cardiology"
        ),
        options=[("oncology", "Oncology"), ("cardiology", "Cardiology")],
    )
    gate = _make_gate(passed=False, reason="too_broad", narrowing=narrowing)
    classifier = _make_classifier(spec=MagicMock())

    agent = _build_search_agent(classifier=classifier, gate=gate)
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={"message": "all biologic drugs", "agent": "search"},
    )

    assert response.status_code == 200
    body = response.json()["response"]

    # Gate narrowing block must appear
    assert "Search too broad" in body
    assert "oncology" in body.lower() or "Oncology" in body
    # Should indicate search is paused
    assert "paused" in body.lower()


@patch("ember_api.routes.chat.get_agent")
def test_patent_not_yet_expired_window(mock_get_agent):
    """Query with 'not expired yet' semantics surfaces temporal signal and returns candidates."""
    signals = RawSignals(
        target=["VEGF"],
        indication=["colorectal cancer"],
        temporal=TemporalSignal(not_expired=True),
    )
    candidate = _make_candidate(
        drug_name="Bevacizumab",
        target_label="VEGF",
        n_patents=3,
        sources=[("USPTO", "https://patents.google.com")],
    )
    scored = [_make_scored_candidate(candidate=candidate, overall=0.68)]
    agent = _build_search_agent(signals=signals, candidates=[candidate], scored=scored)
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={
            "message": "VEGF inhibitors for colorectal cancer with patents not expired yet",
            "agent": "search",
        },
    )

    assert response.status_code == 200
    body = response.json()["response"]

    # Temporal signal "not expired" should be reflected in extracted signals block
    assert "not expired" in body
    # Results should include the candidate
    assert "Bevacizumab" in body
    # Patent count in evidence
    assert "3 patent" in body


@patch("ember_api.routes.chat.get_agent")
def test_multiple_ranked_candidates_ordering(mock_get_agent):
    """Multiple candidates are returned in ranked order (rank 1 before rank 2)."""
    c1 = _make_candidate(drug_name="DrugHigh", target_label="PD-1", n_trials=5)
    c2 = _make_candidate(drug_name="DrugLow", target_label="PD-1", n_trials=1)
    scored = [
        _make_scored_candidate(candidate=c1, rank=1, overall=0.90),
        _make_scored_candidate(candidate=c2, rank=2, overall=0.45),
    ]
    agent = _build_search_agent(candidates=[c1, c2], scored=scored)
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={"message": "PD-1 antibodies", "agent": "search"},
    )

    assert response.status_code == 200
    body = response.json()["response"]

    assert "DrugHigh" in body
    assert "DrugLow" in body
    # Rank 1 appears before rank 2
    assert body.index("DrugHigh") < body.index("DrugLow")
    assert "2 candidate" in body or "Ranked Candidates (2" in body


@patch("ember_api.routes.chat.get_agent")
def test_synthesis_summary_present(mock_get_agent):
    """Response includes synthesis summary section."""
    candidate = _make_candidate(drug_name="DrugS")
    scored = [_make_scored_candidate(candidate=candidate, overall=0.65)]
    agent = _build_search_agent(candidates=[candidate], scored=scored)
    mock_get_agent.return_value = agent

    response = client.post(
        "/chat",
        json={"message": "CD20 antibodies", "agent": "search"},
    )

    assert response.status_code == 200
    body = response.json()["response"]

    assert "Synthesis Summary" in body
