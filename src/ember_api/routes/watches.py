import logging
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
        raise HTTPException(status_code=503, detail="Watch store not available — service is degraded")
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
            logger.warning("Failed to fetch recent runs for watch '%s': %s", watch_id, exc)

    return {"watch": watch, "recent_runs": recent_runs}


@router.patch("/watches/{watch_id}")
def update_watch(request: Request, watch_id: str, body: UpdateWatchRequest) -> dict[str, Any]:
    """Partially update a watch config."""
    watch_store = _get_watch_store(request)

    existing = watch_store.get(watch_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")

    # Validate schedule_day if provided
    effective_schedule = body.schedule if body.schedule is not None else getattr(existing, "schedule", None)
    if body.schedule_day is not None and effective_schedule is not None:
        _validate_schedule_day(effective_schedule, body.schedule_day)

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
