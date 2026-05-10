import importlib.resources as pkg_resources
import logging
import os
import pathlib
from typing import Any

import httpx
from fastapi import APIRouter, Request

from ember_shared import settings

router = APIRouter()
logger = logging.getLogger(__name__)

CRITICAL_SERVICES = {"gemini"}

# Lightweight external endpoints to probe (HEAD request)
_EXTERNAL_PROBES: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/",
}


def _check_bigquery() -> str:
    """Return 'ok' if BigQuery project is accessible, else an error string."""
    project = getattr(settings, "GCP_PROJECT_ID", None)
    if not project:
        return "unavailable: GCP_PROJECT_ID not set"
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=project)
        # Lightweight: list datasets with max_results=1 to validate credentials
        next(iter(client.list_datasets(max_results=1)), None)
        return "ok"
    except ImportError:
        return "unavailable: google-cloud-bigquery not installed"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"


def _check_google_api_key() -> str:
    """Return 'ok' if GOOGLE_API_KEY is present, else 'unavailable'."""
    key = getattr(settings, "GOOGLE_API_KEY", None) or os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return "ok"
    return "unavailable: GOOGLE_API_KEY not set"


def _check_biologic_reference() -> str:
    """Return 'ok' if biologic_reference.json is loadable, else error string."""
    try:
        seed_ref = pkg_resources.files("ember_data.seed").joinpath("biologic_reference.json")
        seed_path = pathlib.Path(str(seed_ref))
        if seed_path.exists():
            return "ok"
        return "unavailable: file not found"
    except ImportError:
        return "unavailable: ember_data not installed"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"


def _check_external_endpoint(url: str) -> str:
    """Return 'ok' if the endpoint responds, else an error string."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.head(url)
        if response.status_code < 500:
            return "ok"
        return f"unavailable: HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"


@router.get("/health")
def health_check(request: Request) -> dict[str, Any]:
    services: dict[str, str] = {}

    # BigQuery
    services["bigquery"] = _check_bigquery()

    # Gemini API key presence
    services["google_api_key"] = _check_google_api_key()

    # biologic_reference.json
    services["biologic_reference"] = _check_biologic_reference()

    # External reachability probes
    for name, url in _EXTERNAL_PROBES.items():
        services[name] = _check_external_endpoint(url)

    # Determine agent_ready based on critical services
    failed_critical = [
        svc for svc in CRITICAL_SERVICES if services.get(svc, "unavailable") != "ok"
    ]

    # result_store availability (wired at startup)
    try:
        result_store_ok = request.app.state.result_writer is not None
    except AttributeError:
        result_store_ok = False
    services["result_store"] = "ok" if result_store_ok else "unavailable"

    # Watch store
    try:
        watch_store_status = "ok" if request.app.state.watch_store is not None else "unavailable"
    except AttributeError:
        watch_store_status = "unavailable"
    services["watch_store"] = watch_store_status

    # Change detector
    try:
        change_detector_ok = request.app.state.change_detector is not None
    except AttributeError:
        change_detector_ok = False
    services["change_detector"] = "ok" if change_detector_ok else "unavailable"

    # Synthesizer
    try:
        synthesizer_ok = request.app.state.synthesizer_available
    except AttributeError:
        synthesizer_ok = False
    services["synthesizer"] = "ok" if synthesizer_ok else "unavailable"

    # Also check app.state.ember_agent (wired at startup)
    agent_ready_from_state: bool = False
    try:
        agent_ready_from_state = request.app.state.ember_agent is not None
    except AttributeError:
        pass

    # Agent is ready only if all critical services pass AND agent was wired
    agent_ready = len(failed_critical) == 0 and agent_ready_from_state

    degraded_reason: str | None = None
    if failed_critical:
        degraded_reason = f"critical services unavailable: {', '.join(failed_critical)}"
    elif not agent_ready_from_state:
        degraded_reason = "EmberAgent not initialized"

    overall_status = "ok" if agent_ready else "degraded"

    result: dict[str, Any] = {
        "status": overall_status,
        "agent_ready": agent_ready,
        "services": services,
        "env": settings.ENV,
    }
    if degraded_reason:
        result["degraded_reason"] = degraded_reason

    return result
