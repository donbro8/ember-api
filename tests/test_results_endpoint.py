from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from ember_api.main import app


@pytest.fixture()
def client_with_reader():
    mock_reader = MagicMock()

    mock_reader.get_run.return_value = [
        {"id": "r1", "title": "Result one"},
        {"id": "r2", "title": "Result two"},
    ]

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


def test_get_results_exposes_explanation_fields_when_present(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.get_run.return_value = [
        {
            "id": "r1",
            "title": "Result one",
            "matched_dimensions": ["target"],
            "missed_dimensions": ["modality"],
            "concrete_labels": {"target": "PD-1"},
            "component_scores": {"target": 0.9, "modality": 0.4},
            "threshold_metadata": {"overall": 0.75},
            "suppression_metadata": {"suppressed": False},
            "evidence_summary": {"total": 3, "high_confidence": 1},
        }
    ]
    response = client.get("/results", params={"run_id": "run-abc"})
    data = response.json()
    result = data["results"][0]
    assert result["matched_dimensions"] == ["target"]
    assert result["missed_dimensions"] == ["modality"]
    assert result["concrete_labels"] == {"target": "PD-1"}
    assert result["component_scores"] == {"target": 0.9, "modality": 0.4}
    assert result["threshold_metadata"] == {"overall": 0.75}
    assert result["suppression_metadata"] == {"suppressed": False}
    assert result["evidence_summary"] == {"total": 3, "high_confidence": 1}


def test_get_results_exposes_patent_and_regulatory_context_fields(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.get_run.return_value = [
        {
            "id": "r1",
            "title": "Result one",
            "patent_expiry_derivation_method": "family_latest_priority_plus_term",
            "data_exclusivity": {"us_bla": "2036-01-20"},
            "framework_regulatory_context": {
                "scope": "framework-level",
                "verified_per_product_dates": False,
            },
            "jurisdictions": {"US": {"patent_expiry_date": "2035-12-14"}},
            "missing_jurisdictions": ["JP"],
            "unknown_jurisdictions": ["BR"],
        }
    ]
    response = client.get("/results", params={"run_id": "run-abc"})
    result = response.json()["results"][0]
    assert (
        result["patent_expiry_derivation_method"] == "family_latest_priority_plus_term"
    )
    assert result["data_exclusivity"] == {"us_bla": "2036-01-20"}
    assert result["framework_regulatory_context"] == {
        "scope": "framework-level",
        "verified_per_product_dates": False,
    }
    assert result["jurisdictions"] == {"US": {"patent_expiry_date": "2035-12-14"}}
    assert result["missing_jurisdictions"] == ["JP"]
    assert result["unknown_jurisdictions"] == ["BR"]


def test_get_results_preserves_canonical_task_148_fields(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.get_run.return_value = [
        {
            "id": "r1",
            "title": "Result one",
            "earliest_patent_expiry_derivation_method": "framework_inferred",
            "earliest_patent_expiry_verified_date": "2035-12-14",
            "data_exclusivity_expiry": "2036-01-20",
            "data_exclusivity_regime": "us_bla_12y",
            "framework_regulatory_context": {
                "scope": "framework-level",
                "verified_per_product_dates": False,
            },
        }
    ]
    response = client.get("/results", params={"run_id": "run-abc"})
    result = response.json()["results"][0]
    assert result["earliest_patent_expiry_derivation_method"] == "framework_inferred"
    assert result["earliest_patent_expiry_verified_date"] == "2035-12-14"
    assert result["data_exclusivity_expiry"] == "2036-01-20"
    assert result["data_exclusivity_regime"] == "us_bla_12y"
    assert result["framework_regulatory_context"] == {
        "scope": "framework-level",
        "verified_per_product_dates": False,
    }


def test_get_results_remains_compatible_when_explanations_absent(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.get_run.return_value = [{"id": "r1", "title": "Result one"}]
    response = client.get("/results", params={"run_id": "run-abc"})
    data = response.json()
    result = data["results"][0]
    assert result["id"] == "r1"
    assert "matched_dimensions" not in result
    assert "suppression_metadata" not in result
    assert "patent_expiry_derivation_method" not in result
    assert "framework_regulatory_context" not in result
    assert "missing_jurisdictions" not in result


def test_get_results_allows_missing_jurisdiction_indicators_without_absence_claim(
    client_with_reader,
):
    client, mock_reader = client_with_reader
    mock_reader.get_run.return_value = [
        {
            "id": "r1",
            "title": "Result one",
            "jurisdictions": {"US": {"patent_expiry_date": "2035-12-14"}},
            "missing_jurisdictions": ["CA", "MX"],
        }
    ]
    response = client.get("/results", params={"run_id": "run-abc"})
    result = response.json()["results"][0]
    assert result["jurisdictions"]["US"]["patent_expiry_date"] == "2035-12-14"
    assert result["missing_jurisdictions"] == ["CA", "MX"]


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


def test_get_runs_exposes_optional_explanation_fields(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.list_runs.return_value = [
        {
            "run_id": "run-aaa",
            "suppression_metadata": {"suppressed_count": 1},
            "threshold_metadata": {"overall": 0.75},
        }
    ]
    response = client.get("/runs", params={"watch_id": "watch-xyz"})
    data = response.json()
    run = data["runs"][0]
    assert run["run_id"] == "run-aaa"
    assert run["suppression_metadata"] == {"suppressed_count": 1}
    assert run["threshold_metadata"] == {"overall": 0.75}


def test_get_runs_exposes_patent_and_regulatory_context_fields(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.list_runs.return_value = [
        {
            "run_id": "run-aaa",
            "patent_expiry_derivation_method": "family_latest_priority_plus_term",
            "data_exclusivity": {"ema_8plus2plus1": "2034-08-01"},
            "framework_regulatory_context": {"scope": "framework-level"},
            "jurisdictions": {"EU": {"patent_expiry_date": "2033-07-31"}},
            "missing_jurisdictions": ["US"],
        }
    ]
    response = client.get("/runs", params={"watch_id": "watch-xyz"})
    run = response.json()["runs"][0]
    assert run["patent_expiry_derivation_method"] == "family_latest_priority_plus_term"
    assert run["data_exclusivity"] == {"ema_8plus2plus1": "2034-08-01"}
    assert run["framework_regulatory_context"] == {"scope": "framework-level"}
    assert run["jurisdictions"] == {"EU": {"patent_expiry_date": "2033-07-31"}}
    assert run["missing_jurisdictions"] == ["US"]


def test_get_runs_preserves_canonical_task_148_fields(client_with_reader):
    client, mock_reader = client_with_reader
    mock_reader.list_runs.return_value = [
        {
            "run_id": "run-aaa",
            "earliest_patent_expiry_derivation_method": "framework_inferred",
            "earliest_patent_expiry_verified_date": "2033-07-31",
            "data_exclusivity_expiry": "2034-08-01",
            "data_exclusivity_regime": "ema_8plus2plus1",
            "framework_regulatory_context": {
                "scope": "framework-level",
                "verified_per_product_dates": False,
            },
        }
    ]
    response = client.get("/runs", params={"watch_id": "watch-xyz"})
    run = response.json()["runs"][0]
    assert run["earliest_patent_expiry_derivation_method"] == "framework_inferred"
    assert run["earliest_patent_expiry_verified_date"] == "2033-07-31"
    assert run["data_exclusivity_expiry"] == "2034-08-01"
    assert run["data_exclusivity_regime"] == "ema_8plus2plus1"
    assert run["framework_regulatory_context"] == {
        "scope": "framework-level",
        "verified_per_product_dates": False,
    }


def test_get_runs_missing_watch_id_returns_422(client_with_reader):
    client, _ = client_with_reader
    response = client.get("/runs")
    assert response.status_code == 422


def test_get_runs_no_reader_returns_503(client_no_reader):
    response = client_no_reader.get("/runs", params={"watch_id": "watch-xyz"})
    assert response.status_code == 503
