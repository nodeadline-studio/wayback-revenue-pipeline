import logging
import os
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger(__name__)


def resolve_leadideal_base_url(handoff: Dict[str, Any]) -> str:
    env_value = (os.getenv("LEADIDEAL_BASE_URL") or "").strip()
    handoff_value = str(handoff.get("base_url") or "").strip()
    startup_geo = ((handoff.get("startup") or {}).get("geo") or "").strip().lower()

    base_url = env_value or handoff_value or "https://leadideal.com"
    if startup_geo == "il" and not env_value and not handoff_value:
        base_url = "https://leadideal.com"
    return base_url.rstrip("/")


def execute_leadideal_preview(handoff: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    base_url = resolve_leadideal_base_url(handoff)
    preview_requests = handoff.get("preview_requests") or []
    if not preview_requests:
        return {
            "schema_version": "leadideal-preview-artifact-v1",
            "executed": False,
            "status": "skipped",
            "reason": "No preview requests were generated from the handoff.",
            "base_url": base_url,
            "results": [],
        }

    endpoint = f"{base_url}/api/lead-finder/preview"
    artifact = {
        "schema_version": "leadideal-preview-artifact-v1",
        "executed": True,
        "status": "completed",
        "base_url": base_url,
        "endpoint": endpoint,
        "results": [],
    }

    for preview_request in preview_requests:
        result_entry: Dict[str, Any] = {
            "request": preview_request,
            "success": False,
        }
        try:
            response = requests.post(
                endpoint,
                json={
                    "industry": preview_request.get("industry", ""),
                    "location": preview_request.get("location", ""),
                    "job_title": preview_request.get("job_title", ""),
                },
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            result_entry["http_status"] = response.status_code

            try:
                data = response.json()
            except ValueError:
                data = {"success": False, "error": response.text[:500]}

            result_entry["response"] = {
                "success": bool(data.get("success", False)),
                "total_estimated": data.get("total_estimated"),
                "db_matches": data.get("db_matches"),
                "match_tier": data.get("match_tier"),
                "display_note": data.get("display_note"),
                "promo": data.get("promo"),
                "preview_count": len(data.get("previews") or []),
                "error": data.get("error"),
            }
            result_entry["success"] = bool(data.get("success", False)) and response.ok
            result_entry["preview_excerpt"] = (data.get("previews") or [])[:3]
            if not response.ok:
                artifact["status"] = "partial_failure"
        except Exception as exc:
            logger.warning("LeadIdeal preview execution failed for %s: %s", preview_request, exc)
            result_entry["error"] = str(exc)
            artifact["status"] = "partial_failure"

        artifact["results"].append(result_entry)

    if artifact["results"] and not any(item.get("success") for item in artifact["results"]):
        artifact["status"] = "failed"

    return artifact