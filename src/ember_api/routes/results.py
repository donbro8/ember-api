import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

router = APIRouter()
logger = logging.getLogger(__name__)

_EXPLANATION_FIELDS = (
    "matched_dimensions",
    "missed_dimensions",
    "concrete_labels",
    "component_scores",
    "threshold_metadata",
    "suppression_metadata",
    "evidence_summary",
    "match_explanations",
    "score_explanation",
)

_PATENT_REGULATORY_FIELDS = (
    "patent_expiry_derivation_method",
    "earliest_patent_expiry_derivation_method",
    "earliest_patent_expiry_verified_date",
    "patent_expiry_derivation",
    "data_exclusivity",
    "data_exclusivity_expiry",
    "data_exclusivity_regime",
    "framework_regulatory_context",
    "regulatory_context",
    "jurisdictions",
    "missing_jurisdictions",
    "unknown_jurisdictions",
)


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion to JSON-serializable data."""
    try:
        return jsonable_encoder(value)
    except Exception:  # noqa: BLE001
        return value


def _serialize_with_optional_explanations(record: Any) -> Any:
    """Serialize records and include optional explanation metadata when present."""
    data = _to_jsonable(record)
    if isinstance(data, dict):
        base: dict[str, Any] = data
    else:
        return data

    for field in (*_EXPLANATION_FIELDS, *_PATENT_REGULATORY_FIELDS):
        if field in base:
            continue
        if isinstance(record, dict):
            value = record.get(field)
        else:
            value = getattr(record, field, None)
        if value is not None:
            base[field] = _to_jsonable(value)
    return base


@router.get("/results")
def get_results(
    request: Request,
    run_id: str = Query(..., description="Run identifier returned by POST /query"),
) -> dict[str, Any]:
    """Return structured results for a specific run."""
    try:
        result_reader = request.app.state.result_reader
    except AttributeError:
        result_reader = None

    if result_reader is None:
        raise HTTPException(status_code=503, detail="Result store not available — service is degraded")

    run = result_reader.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    raw_results = getattr(run, "results", run)
    if isinstance(raw_results, tuple):
        raw_results = list(raw_results)

    if isinstance(raw_results, list):
        serialized_results = [_serialize_with_optional_explanations(item) for item in raw_results]
    else:
        serialized_results = raw_results

    return {"results": serialized_results}


@router.get("/runs")
def get_runs(
    request: Request,
    watch_id: str = Query(..., description="Watch/subscription identifier"),
    limit: int | None = Query(None, description="Maximum number of runs to return"),
) -> dict[str, Any]:
    """List recent runs associated with a watch identifier."""
    try:
        result_reader = request.app.state.result_reader
    except AttributeError:
        result_reader = None

    if result_reader is None:
        raise HTTPException(status_code=503, detail="Result store not available — service is degraded")

    runs = result_reader.list_runs(watch_id, limit or 20)
    serialized_runs = [_serialize_with_optional_explanations(run) for run in runs]
    return {"runs": serialized_runs}
