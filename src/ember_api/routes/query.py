import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    response: str
    run_id: str
    cached: bool
    synthesis_overview: str | None = None


def _is_failed_gate_cache(markdown: str) -> bool:
    """Return True for cached gate failures that should be re-executed."""
    return "**Gate outcome:** missing_core_fields" in markdown


@router.post("/query", response_model=QueryResponse)
async def query(request: Request, body: QueryRequest):
    agent = request.app.state.ember_agent
    if agent is None:
        raise HTTPException(
            status_code=503, detail="Agent not available — service is degraded"
        )

    # Check cache first
    try:
        result_reader = request.app.state.result_reader
    except AttributeError:
        result_reader = None

    if result_reader is not None:
        try:
            cached_run = result_reader.get_cached(body.query)
            if cached_run is not None:
                if _is_failed_gate_cache(cached_run.markdown):
                    logger.info(
                        "Skipping cached gate failure for query; proceeding live"
                    )
                else:
                    return QueryResponse(
                        response=cached_run.markdown,
                        run_id=cached_run.run_id,
                        cached=True,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache lookup failed — proceeding to live query: %s", exc)

    # Execute agent
    output = await agent.execute(body.query)

    # Write result to store (best-effort, non-blocking)
    try:
        result_writer = request.app.state.result_writer
    except AttributeError:
        result_writer = None

    if result_writer is not None:
        try:
            result_writer.write_run(
                run_id=output.run_id,
                query=body.query,
                query_type=output.query_type,
                results=output.results,
                trace=output.trace,
                markdown=output.markdown,
                watch_id=None,
                bytes_scanned=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Result write failed — result not persisted: %s", exc)

    return QueryResponse(
        response=output.markdown,
        run_id=output.run_id,
        cached=False,
        synthesis_overview=getattr(output, "synthesis_overview", None),
    )
