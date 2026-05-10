import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
logger = logging.getLogger(__name__)


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
    return {"results": run}


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

    runs = result_reader.list_runs(watch_id, limit)
    return {"runs": runs}
