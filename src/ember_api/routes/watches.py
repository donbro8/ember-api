import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateWatchRequest(BaseModel):
    name: str
    query: str
    schedule: Literal["weekly", "monthly"]
    schedule_day: int | None = None
    notify_on_change: bool = False


class UpdateWatchRequest(BaseModel):
    name: str | None = None
    query: str | None = None
    schedule: Literal["weekly", "monthly"] | None = None
    schedule_day: int | None = None
    enabled: bool | None = None
    notify_on_change: bool | None = None


def _get_watch_store(request: Request):
    try:
        store = request.app.state.watch_store
    except AttributeError:
        store = None
    if store is None:
        raise HTTPException(
            status_code=503, detail="Watch store not available — service is degraded"
        )
    return store


def _validate_schedule_day(schedule: str, schedule_day: int | None) -> None:
    if schedule_day is None:
        return
    if schedule == "weekly":
        if schedule_day < 0 or schedule_day > 6:
            raise HTTPException(
                status_code=422,
                detail="schedule_day must be 0–6 for weekly schedule (0=Monday, 6=Sunday)",
            )
    elif schedule == "monthly":
        if schedule_day < 1 or schedule_day > 31:
            raise HTTPException(
                status_code=422,
                detail="schedule_day must be 1–31 for monthly schedule",
            )


@router.post("/watches", status_code=201)
def create_watch(request: Request, body: CreateWatchRequest) -> dict[str, Any]:
    """Create a new watch config."""
    watch_store = _get_watch_store(request)
    _validate_schedule_day(body.schedule, body.schedule_day)

    watch = watch_store.create(
        name=body.name,
        query=body.query,
        schedule=body.schedule,
        schedule_day=body.schedule_day,
        notify_on_change=body.notify_on_change,
    )
    return {"watch": watch}


@router.get("/watches")
def list_watches(request: Request) -> dict[str, Any]:
    """List all watch configs."""
    watch_store = _get_watch_store(request)
    watches = watch_store.list()
    return {"watches": watches}


@router.get("/watches/{watch_id}")
def get_watch(request: Request, watch_id: str) -> dict[str, Any]:
    """Get a single watch config with recent runs."""
    watch_store = _get_watch_store(request)

    watch = watch_store.get(watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")

    # Fetch recent runs (best-effort)
    recent_runs: list[Any] = []
    try:
        result_reader = request.app.state.result_reader
    except AttributeError:
        result_reader = None

    if result_reader is not None:
        try:
            recent_runs = result_reader.list_runs(watch_id, 10)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to fetch recent runs for watch '%s': %s", watch_id, exc
            )

    return {"watch": watch, "recent_runs": recent_runs}


@router.patch("/watches/{watch_id}")
def update_watch(
    request: Request, watch_id: str, body: UpdateWatchRequest
) -> dict[str, Any]:
    """Partially update a watch config."""
    watch_store = _get_watch_store(request)

    existing = watch_store.get(watch_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")

    # Validate schedule_day against effective schedule
    effective_schedule = (
        body.schedule
        if body.schedule is not None
        else getattr(existing, "schedule", None)
    )
    effective_schedule_day = (
        body.schedule_day
        if body.schedule_day is not None
        else getattr(existing, "schedule_day", None)
    )
    if effective_schedule_day is not None and effective_schedule is not None:
        _validate_schedule_day(effective_schedule, effective_schedule_day)

    # Build update kwargs from non-None fields
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    updated = watch_store.update(watch_id, **updates)
    return {"watch": updated}


@router.delete("/watches/{watch_id}", status_code=204)
def delete_watch(request: Request, watch_id: str) -> Response:
    """Delete a watch config."""
    watch_store = _get_watch_store(request)

    deleted = watch_store.delete(watch_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")
    return Response(status_code=204)


@router.post("/watches/{watch_id}/run")
async def run_watch(request: Request, watch_id: str) -> dict[str, Any]:
    """Manually trigger a watch run."""
    # 1. Get required state
    try:
        watch_store = request.app.state.watch_store
    except AttributeError:
        watch_store = None
    if watch_store is None:
        raise HTTPException(
            status_code=503, detail="Watch store not available — service is degraded"
        )

    try:
        agent = request.app.state.ember_agent
    except AttributeError:
        agent = None
    if agent is None:
        raise HTTPException(
            status_code=503, detail="Agent not available — service is degraded"
        )

    try:
        result_writer = request.app.state.result_writer
    except AttributeError:
        result_writer = None
    if result_writer is None:
        raise HTTPException(
            status_code=503, detail="Result writer not available — service is degraded"
        )

    # 2. Get watch config
    watch = watch_store.get(watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")

    # 3. Rate limit: max 3 runs per 24h
    try:
        result_reader = request.app.state.result_reader
    except AttributeError:
        result_reader = None

    if result_reader is not None:
        try:
            recent_runs = result_reader.list_runs(watch_id, 10)
            now = datetime.now(tz=timezone.utc)
            runs_in_24h = 0
            for run in recent_runs:
                created_at = getattr(run, "created_at", None) or (
                    run.get("created_at") if isinstance(run, dict) else None
                )
                if created_at is not None:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at)
                        except ValueError:
                            continue
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    if (now - created_at).total_seconds() < 86400:
                        runs_in_24h += 1
            if runs_in_24h >= 3:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded: maximum 3 manual runs per 24 hours",
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to check rate limit for watch '%s': %s", watch_id, exc
            )

    # 4. Execute the agent
    output = await agent.execute(watch.query)

    # 5. Best-effort write result
    try:
        result_writer.write_run(
            run_id=output.run_id,
            query=watch.query,
            query_type=output.query_type,
            results=output.results,
            trace=output.trace,
            markdown=output.markdown,
            watch_id=watch_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write run result for watch '%s': %s", watch_id, exc)

    # 6. Best-effort record run on watch store
    try:
        watch_store.record_run(watch_id, output.run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to record run on watch store for watch '%s': %s", watch_id, exc
        )

    return {"run_id": output.run_id, "cached": False}


@router.get("/watches/{watch_id}/changes")
def get_watch_changes(
    request: Request, watch_id: str, limit: int = 50
) -> dict[str, Any]:
    """Get change history for a watch."""
    # Check change_detector availability
    try:
        change_detector = request.app.state.change_detector
    except AttributeError:
        change_detector = None
    if change_detector is None:
        raise HTTPException(
            status_code=503,
            detail="Change detector not available — service is degraded",
        )

    # Check watch exists
    try:
        watch_store = request.app.state.watch_store
    except AttributeError:
        watch_store = None
    if watch_store is None:
        raise HTTPException(
            status_code=503, detail="Watch store not available — service is degraded"
        )

    watch = watch_store.get(watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")

    changes = change_detector.get_changes(watch_id, limit)

    def _serialize_change(c: Any) -> dict[str, Any]:
        d = asdict(c)
        # Convert datetime fields to ISO strings for JSON serialization
        for key, val in d.items():
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    # Best-effort: fetch change_summary from the latest run for this watch
    change_summary: str | None = None
    try:
        result_reader = request.app.state.result_reader
    except AttributeError:
        result_reader = None

    if result_reader is not None:
        try:
            recent_runs = result_reader.list_runs(watch_id, 1)
            if recent_runs:
                latest_run = recent_runs[0]
                change_summary = getattr(latest_run, "change_summary", None)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to fetch change_summary for watch '%s': %s", watch_id, exc
            )

    return {
        "changes": [_serialize_change(c) for c in changes],
        "change_summary": change_summary,
    }
