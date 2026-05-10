"""Digest endpoint — cross-watch periodic summary."""

import logging
from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
logger = logging.getLogger(__name__)


def _safe_state(request: Request, attr: str) -> Any:
    """Return app.state.<attr> or None if not set."""
    try:
        return getattr(request.app.state, attr)
    except AttributeError:
        return None


@router.get("/digest")
async def get_digest(
    request: Request,
    period_days: int = Query(default=7, ge=1),
) -> dict[str, Any]:
    """Generate a cross-watch digest for the requested period."""
    watch_store = _safe_state(request, "watch_store")
    if watch_store is None:
        raise HTTPException(
            status_code=503,
            detail="Watch store not available — service is degraded",
        )

    change_detector = _safe_state(request, "change_detector")
    if change_detector is None:
        raise HTTPException(
            status_code=503,
            detail="Change detector not available — service is degraded",
        )

    result_reader = _safe_state(request, "result_reader")
    if result_reader is None:
        raise HTTPException(
            status_code=503,
            detail="Result reader not available — service is degraded",
        )

    # Import digest classes from ember-agents
    try:
        from ember_agents.synthesis import DigestGenerator, WatchDigestInput
    except ImportError as exc:
        logger.warning("DigestGenerator not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Digest generator not available — service is degraded",
        ) from exc

    # Load enabled watches
    watches = watch_store.list(enabled_only=True)

    # Build WatchDigestInput for each watch
    digest_inputs: list[WatchDigestInput] = []
    for watch in watches:
        # Get recent changes
        try:
            changes = change_detector.get_changes(watch.watch_id, 100)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to get changes for watch '%s': %s", watch.watch_id, exc)
            changes = []

        # Get latest results
        latest_results: list = []
        change_summary: str | None = None
        try:
            runs = result_reader.list_runs(watch.watch_id, 1)
            if runs:
                latest_run = runs[0]
                change_summary = getattr(latest_run, "change_summary", None)
                run_id = getattr(latest_run, "run_id", None)
                if run_id:
                    try:
                        latest_results = result_reader.get_run(run_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Failed to get results for run '%s': %s", run_id, exc
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to get runs for watch '%s': %s", watch.watch_id, exc
            )

        digest_inputs.append(
            WatchDigestInput(
                watch_name=watch.name,
                query=watch.query,
                changes=changes,
                change_summary=change_summary,
                latest_results=latest_results,
            )
        )

    # Generate digest
    generator = DigestGenerator()
    digest_output = await generator.generate_digest(digest_inputs, period_days)

    # Serialize to JSON-safe dict
    result = asdict(digest_output)
    # Convert date objects to ISO strings
    for key in ("period_start", "period_end"):
        val = result.get(key)
        if isinstance(val, date):
            result[key] = val.isoformat()

    return result
