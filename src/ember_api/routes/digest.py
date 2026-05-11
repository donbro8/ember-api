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


def _extract_source_keys(result: Any) -> set[str]:
    """Extract source identifiers from a result object when present."""
    keys: set[str] = set()
    if isinstance(result, dict):
        source_value = result.get("source")
        sources_value = result.get("sources")
    else:
        source_value = getattr(result, "source", None)
        sources_value = getattr(result, "sources", None)

    if isinstance(source_value, str) and source_value:
        keys.add(source_value)
    if isinstance(sources_value, list):
        for item in sources_value:
            if isinstance(item, str) and item:
                keys.add(item)
            elif isinstance(item, dict):
                source_name = item.get("source") or item.get("name")
                if isinstance(source_name, str) and source_name:
                    keys.add(source_name)
    return keys


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
    recent_changes: list[dict[str, Any]] = []
    per_watch_latest_results: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    suppressed_count = 0
    for watch in watches:
        watch_id = getattr(watch, "watch_id", "")
        watch_name = getattr(watch, "name", "")
        # Get recent changes
        try:
            changes = change_detector.get_changes(watch_id, 100)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to get changes for watch '%s': %s", watch_id, exc)
            changes = []
        for change in changes:
            change_id = getattr(change, "change_id", None)
            summary = getattr(change, "summary", None) or getattr(
                change, "description", None
            )
            changed_at = getattr(change, "changed_at", None) or getattr(
                change, "timestamp", None
            )
            recent_changes.append(
                {
                    "watch_id": watch_id,
                    "watch_name": watch_name,
                    "change_id": change_id,
                    "summary": summary,
                    "changed_at": changed_at,
                    "link": f"/watches/{watch_id}/changes",
                }
            )

        # Get latest results
        latest_results: list = []
        change_summary: str | None = None
        latest_run_id: str | None = None
        latest_status: str | None = None
        try:
            runs = result_reader.list_runs(watch_id, 1)
            if runs:
                latest_run = runs[0]
                change_summary = getattr(latest_run, "change_summary", None)
                latest_run_id = getattr(latest_run, "run_id", None)
                latest_status = getattr(latest_run, "status", None)
                if isinstance(latest_status, str) and latest_status:
                    status_counts[latest_status] = (
                        status_counts.get(latest_status, 0) + 1
                    )
                if latest_run_id:
                    try:
                        latest_results = result_reader.get_run(latest_run_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Failed to get results for run '%s': %s", latest_run_id, exc
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to get runs for watch '%s': %s", watch_id, exc)

        normalized_results: list[Any]
        if latest_results is None:
            normalized_results = []
        elif isinstance(latest_results, list):
            normalized_results = latest_results
        else:
            normalized_results = [latest_results]

        watch_suppressed_count = 0
        for result in normalized_results:
            if isinstance(result, dict):
                suppression = result.get("suppression_metadata")
            else:
                suppression = getattr(result, "suppression_metadata", None)
            if isinstance(suppression, dict):
                if suppression.get("suppressed") is True:
                    watch_suppressed_count += 1
                count_value = suppression.get("suppressed_count")
                if isinstance(count_value, int):
                    watch_suppressed_count += count_value
            for source_key in _extract_source_keys(result):
                source_counts[source_key] = source_counts.get(source_key, 0) + 1

        suppressed_count += watch_suppressed_count
        per_watch_latest_results.append(
            {
                "watch_id": watch_id,
                "watch_name": watch_name,
                "latest_run_id": latest_run_id,
                "latest_status": latest_status,
                "result_count": len(normalized_results),
                "suppressed_count": watch_suppressed_count,
                "watch_link": f"/watches/{watch_id}",
                "run_link": f"/results?run_id={latest_run_id}"
                if latest_run_id
                else None,
            }
        )

        digest_inputs.append(
            WatchDigestInput(
                watch_name=watch_name,
                query=getattr(watch, "query", ""),
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

    # Additive aggregate dashboard payload (backward-compatible).
    result["dashboard"] = {
        "top_opportunities": result.get("top_opportunities", []),
        "recent_changes": recent_changes,
        "per_watch_latest_results": per_watch_latest_results,
        "source_counts": source_counts,
        "status_counts": status_counts,
        "suppressed_count": suppressed_count,
        "links": {
            "digest": "/digest",
            "watches": "/watches",
        },
    }

    return result
