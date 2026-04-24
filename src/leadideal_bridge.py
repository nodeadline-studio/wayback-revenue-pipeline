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
                    "forensic_context": handoff.get("forensic_context", ""),
                    "bizspy_report_url": handoff.get("bizspy_report_url", ""),
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


def execute_leadideal_bulk(industry: str, location: str = "United States",
                          job_title: Optional[str] = None,
                          company_size: Optional[str] = None,
                          timeout: int = 60) -> Dict[str, Any]:
    """Execute bulk mining for SlopRadar super tier via LeadIdeal internal API.

    Calls LeadIdeal's /api/internal/mine endpoint to get 20 ICP leads + QA + POW dry-run.

    Args:
        industry: Target industry for mining
        location: Target location (default: "United States")
        job_title: Optional job title filter
        company_size: Optional company size filter
        timeout: Request timeout in seconds

    Returns:
        Dict with mining results, QA stats, and outreach email samples
    """
    base_url = os.getenv("LEADIDEAL_BASE_URL", "https://leadideal.com").rstrip("/")
    api_key = os.getenv("LEADIDEAL_API_KEY", "").strip()

    if not api_key:
        return {
            "schema_version": "leadideal-bulk-artifact-v1",
            "executed": False,
            "status": "failed",
            "error": "LEADIDEAL_API_KEY environment variable not set",
            "base_url": base_url,
        }

    endpoint = f"{base_url}/api/internal/mine"
    artifact = {
        "schema_version": "leadideal-bulk-artifact-v1",
        "executed": True,
        "status": "pending",
        "base_url": base_url,
        "endpoint": endpoint,
        "request": {
            "industry": industry,
            "location": location,
            "job_title": job_title,
            "company_size": company_size,
        },
    }

    try:
        response = requests.post(
            endpoint,
            json={
                "industry": industry,
                "location": location,
                "job_title": job_title,
                "company_size": company_size,
            },
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            timeout=timeout,
        )

        artifact["http_status"] = response.status_code

        try:
            data = response.json()
        except ValueError:
            data = {"success": False, "error": response.text[:500]}

        if response.ok and data.get("success"):
            artifact["status"] = "completed"
            artifact["results"] = {
                "leads_mined": data.get("leads_mined", 0),
                "qa_results": data.get("qa_results", {}),
                "outreach_emails_generated": data.get("outreach_emails_generated", 0),
                "sample_emails": data.get("sample_emails", []),
                "leads": data.get("leads", []),
            }
        else:
            artifact["status"] = "failed"
            artifact["error"] = data.get("error", f"HTTP {response.status_code}: {response.text[:200]}")

    except requests.exceptions.Timeout:
        artifact["status"] = "failed"
        artifact["error"] = f"Request timed out after {timeout} seconds"
    except Exception as exc:
        logger.error("LeadIdeal bulk mining execution failed: %s", exc)
        artifact["status"] = "failed"
        artifact["error"] = str(exc)

    return artifact
