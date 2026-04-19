import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""

    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).strip().lower().strip("/")
    if host.startswith("www."):
        host = host[4:]
    return host


def humanize_domain(value: str) -> str:
    domain = normalize_domain(value)
    label = domain.split(".")[0].replace("-", " ").replace("_", " ").strip()
    if not label:
        return domain
    return " ".join(part.capitalize() for part in label.split())


def coerce_seeded_competitors(raw_value: Any) -> List[Dict[str, Any]]:
    if raw_value in (None, "", []):
        return []

    if isinstance(raw_value, str):
        candidates: List[Any] = [part.strip() for part in re.split(r"[\n,]+", raw_value) if part.strip()]
    elif isinstance(raw_value, list):
        candidates = raw_value
    else:
        return []

    seeded = []
    seen = set()
    for item in candidates:
        if isinstance(item, str):
            domain = normalize_domain(item)
            payload = {}
        elif isinstance(item, dict):
            domain = normalize_domain(
                item.get("domain")
                or item.get("url")
                or item.get("competitor")
                or item.get("name")
                or ""
            )
            payload = item
        else:
            continue

        if not domain or domain in seen:
            continue
        seen.add(domain)
        seeded.append(
            {
                "domain": domain,
                "label": payload.get("label") or payload.get("name") or humanize_domain(domain),
                "selection_reason": payload.get("selection_reason") or payload.get("reason") or "Founder-seeded competitor.",
                "similarity_score": payload.get("similarity_score"),
                "from_date": payload.get("from_date"),
                "to_date": payload.get("to_date"),
                "source": "seeded",
            }
        )
    return seeded


def build_sprint_context(payload: Optional[Dict[str, Any]], target_url: str) -> Dict[str, Any]:
    payload = payload or {}
    seeded_competitors = coerce_seeded_competitors(payload.get("seeded_competitors"))
    startup_name = (payload.get("startup_name") or "").strip() or humanize_domain(target_url)
    leadideal = dict(payload.get("leadideal") or {})
    creatorpacks = dict(payload.get("creatorpacks") or {})
    publishability = dict(payload.get("publishability") or {})

    if leadideal.get("base_url"):
        leadideal["base_url"] = str(leadideal.get("base_url") or "").strip().rstrip("/")

    publishability = {
        "internal_only": bool(publishability.get("internal_only", False)),
        "public_case_study_ready": bool(publishability.get("public_case_study_ready", False)),
        "redactions_needed": publishability.get("redactions_needed") or [],
    }

    return {
        "preset_id": (payload.get("preset_id") or "").strip(),
        "startup_name": startup_name,
        "variant_id": (payload.get("variant_id") or "default").strip() or "default",
        "language": (payload.get("language") or "en").strip() or "en",
        "geo": (payload.get("geo") or "global").strip() or "global",
        "offer": (payload.get("offer") or "").strip(),
        "audience": (payload.get("audience") or "").strip(),
        "objective": (payload.get("objective") or "Optimize positioning and generate downstream startup playbooks.").strip(),
        "message_pillars": payload.get("message_pillars") or [],
        "recommended_experiments": payload.get("recommended_experiments") or [],
        "publishability": publishability,
        "leadideal": leadideal,
        "creatorpacks": creatorpacks,
        "seeded_competitors": seeded_competitors,
        "selection_mode": "seeded" if seeded_competitors else "discovery",
    }


def _dedupe_strings(values: List[str]) -> List[str]:
    seen = set()
    output = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def build_leadideal_handoff(manifest: Dict[str, Any]) -> Dict[str, Any]:
    startup = manifest.get("startup") or {}
    distribution = manifest.get("distribution") or {}
    leadideal = distribution.get("leadideal") or {}
    segment_label = leadideal.get("segment_label") or f"startup-intel-{startup.get('variant_id') or 'default'}"
    base_url = str(leadideal.get("base_url") or "").strip()

    locations = _dedupe_strings(leadideal.get("locations") or [startup.get("geo") or "United States"])
    roles = _dedupe_strings(leadideal.get("roles") or [])
    industry = str(leadideal.get("industry") or startup.get("offer") or startup.get("name") or "").strip()
    job_title = str(leadideal.get("job_title") or "").strip()

    preview_requests = []
    if locations:
        for location in locations:
            preview_requests.append(
                {
                    "industry": industry,
                    "location": location,
                    "job_title": job_title,
                    "suggested_endpoint": "/api/lead-finder/preview",
                }
            )
    else:
        preview_requests.append(
            {
                "industry": industry,
                "location": "",
                "job_title": job_title,
                "suggested_endpoint": "/api/lead-finder/preview",
            }
        )

    return {
        "schema_version": "leadideal-handoff-v1",
        "generated_at": manifest.get("generated_at") or utc_now_iso(),
        "startup": {
            "name": startup.get("name") or "",
            "variant_id": startup.get("variant_id") or "default",
            "target_url": startup.get("target_url") or "",
            "language": startup.get("language") or "en",
            "geo": startup.get("geo") or "global",
        },
        "segment_label": segment_label,
        "base_url": base_url,
        "industry": industry,
        "roles": roles,
        "locations": locations,
        "job_title": job_title,
        "suggested_next_step": "Run Lead Finder preview for the first location, then escalate to fresh mining if preview depth is weak.",
        "preview_requests": preview_requests,
        "notes": {
            "selection_mode": (manifest.get("selection") or {}).get("mode"),
            "competitor_source": (manifest.get("selection") or {}).get("competitor_source"),
            "key_findings": manifest.get("key_findings") or [],
        },
    }


def build_sprint_manifest(
    niche_name: str,
    target_url: str,
    competitors: List[Dict[str, Any]],
    sprint_context: Optional[Dict[str, Any]] = None,
    locked_competitors: Optional[List[str]] = None,
    key_findings: Optional[List[str]] = None,
    total_snapshots: int = 0,
    total_changes: int = 0,
    competitor_source: str = "discovery",
    niche_narrative: str = "",
) -> Dict[str, Any]:
    sprint_context = sprint_context or {}
    key_findings = key_findings or []
    locked_competitors = locked_competitors or []
    seed_lookup = {
        normalize_domain(item.get("domain", "")): item
        for item in sprint_context.get("seeded_competitors", [])
    }

    all_tech = set()
    competitor_entries = []
    for index, competitor in enumerate(competitors):
        current_analysis = competitor.get("current_analysis") or {}
        tech_stack = set(current_analysis.get("tech_stack") or [])
        all_tech.update(tech_stack)
        prices_found = current_analysis.get("prices_found") or []
        competitor_domain = normalize_domain(competitor.get("url", ""))
        seed_meta = seed_lookup.get(competitor_domain, {})
        is_target = index == 0

        competitor_entries.append(
            {
                "name": competitor.get("name") or humanize_domain(competitor.get("url", "")),
                "domain": competitor_domain,
                "url": competitor.get("url"),
                "role": "target" if is_target else "competitor",
                "source": "target" if is_target else seed_meta.get("source") or competitor_source,
                "selection_reason": (
                    "Target startup being analyzed."
                    if is_target
                    else seed_meta.get("selection_reason") or f"Selected via {competitor_source.replace('_', ' ')} competitor discovery."
                ),
                "similarity_score": seed_meta.get("similarity_score"),
                "snapshot_count": competitor.get("snapshot_count", 0),
                "selected_snapshot_count": competitor.get("selected_snapshot_count", 0),
                "analyzed_snapshot_count": competitor.get("analyzed_snapshot_count", 0),
                "change_count": len(competitor.get("changes", [])),
                "current_analysis_source": competitor.get("current_analysis_source"),
                "headline": current_analysis.get("h1") or current_analysis.get("title") or "",
                "primary_ctas": (current_analysis.get("cta_buttons") or [])[:5],
                "prices_found": prices_found[:8],
                "tech_stack": sorted(tech_stack),
                "ai_insight": competitor.get("ai_insight") or "",
            }
        )

    return {
        "schema_version": "startup-intel-v1",
        "generated_at": utc_now_iso(),
        "niche_name": niche_name,
        "niche_narrative": niche_narrative,
        "startup": {
            "name": sprint_context.get("startup_name") or humanize_domain(target_url),
            "target_url": target_url,
            "variant_id": sprint_context.get("variant_id") or "default",
            "language": sprint_context.get("language") or "en",
            "geo": sprint_context.get("geo") or "global",
            "offer": sprint_context.get("offer") or "",
            "audience": sprint_context.get("audience") or "",
            "objective": sprint_context.get("objective") or "",
        },
        "selection": {
            "mode": sprint_context.get("selection_mode") or ("seeded" if sprint_context.get("seeded_competitors") else "discovery"),
            "competitor_source": competitor_source,
            "seeded_count": len(sprint_context.get("seeded_competitors") or []),
            "locked_competitors": locked_competitors,
        },
        "summary": {
            "competitors_analyzed": len(competitors),
            "competitors_locked": len(locked_competitors),
            "total_snapshots": total_snapshots,
            "total_changes": total_changes,
            "tech_tools_found": len(all_tech),
            "key_findings_count": len(key_findings),
        },
        "recommendations": {
            "message_pillars": sprint_context.get("message_pillars") or [],
            "recommended_experiments": sprint_context.get("recommended_experiments") or [],
        },
        "distribution": {
            "leadideal": sprint_context.get("leadideal") or {},
            "creatorpacks": sprint_context.get("creatorpacks") or {},
        },
        "publishability": sprint_context.get("publishability") or {},
        "key_findings": key_findings,
        "competitors": competitor_entries,
    }


def build_approval_state(manifest: Dict[str, Any], leadideal_preview: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    preview = leadideal_preview or {}
    startup = manifest.get("startup") or {}
    publishability = manifest.get("publishability") or {}
    preview_status = str(preview.get("status") or "not_run")
    preview_executed = bool(preview.get("executed"))

    blockers = [
        "Human review is required before mining escalation, public publication, outreach, or customer dispatch.",
        "No approval decision has been recorded yet.",
    ]
    if not preview_executed:
        blockers.append("LeadIdeal preview did not run, so downstream qualification is incomplete.")
    elif preview_status != "completed":
        blockers.append(f"LeadIdeal preview status is '{preview_status}', so operator review should resolve preview quality first.")

    return {
        "schema_version": "startup-intel-approval-v1",
        "generated_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "startup": {
            "name": startup.get("name") or manifest.get("niche_name") or "",
            "variant_id": startup.get("variant_id") or "default",
            "target_url": startup.get("target_url") or "",
        },
        "status": "pending_review",
        "review_stage": "operator_review_required",
        "dispatch_blocked": True,
        "leadideal_preview_status": preview_status,
        "publishability": {
            "internal_only": bool(publishability.get("internal_only", False)),
            "public_case_study_ready": bool(publishability.get("public_case_study_ready", False)),
            "redactions_needed": publishability.get("redactions_needed") or [],
        },
        "approvals": {
            "operator_review_completed": False,
            "mining_escalation_approved": False,
            "public_case_study_approved": False,
            "customer_dispatch_approved": False,
        },
        "review_notes": "",
        "review_history": [],
        "allowed_next_actions": {
            "review_internal_brief": True,
            "review_leadideal_preview": True,
            "escalate_to_mining": False,
            "publish_public_case_study": False,
            "dispatch_to_customer": False,
        },
        "blockers": blockers,
        "recommended_next_step": (
            "Review the LeadIdeal preview artifact and approve or reject the next escalation step."
            if preview_executed
            else "Review the handoff and resolve preview execution before any escalation."
        ),
    }


def record_approval_decision(approval_state: Dict[str, Any], decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    decision = decision or {}
    approvals = dict(approval_state.get("approvals") or {})
    publishability = dict(approval_state.get("publishability") or {})
    preview_status = str(approval_state.get("leadideal_preview_status") or "not_run")
    rejected = bool(decision.get("rejected", False))

    for key in (
        "operator_review_completed",
        "mining_escalation_approved",
        "public_case_study_approved",
        "customer_dispatch_approved",
    ):
        if key in decision:
            approvals[key] = bool(decision.get(key))

    if any(
        approvals.get(key)
        for key in ("mining_escalation_approved", "public_case_study_approved", "customer_dispatch_approved")
    ):
        approvals["operator_review_completed"] = True

    review_notes = str(decision.get("review_notes") or approval_state.get("review_notes") or "").strip()
    history = list(approval_state.get("review_history") or [])
    if decision:
        history.append(
            {
                "timestamp": utc_now_iso(),
                "decision": {
                    key: decision.get(key)
                    for key in (
                        "operator_review_completed",
                        "mining_escalation_approved",
                        "public_case_study_approved",
                        "customer_dispatch_approved",
                        "rejected",
                    )
                    if key in decision
                },
                "review_notes": review_notes,
            }
        )

    if rejected:
        status = "rejected"
        dispatch_blocked = True
        blockers = ["Review was explicitly rejected. Resolve the notes before any downstream action."]
        recommended_next_step = "Revise the report or preview inputs, then submit for review again."
    else:
        status = "pending_review"
        dispatch_blocked = True
        blockers = []

        if not approvals.get("operator_review_completed"):
            blockers.append("Operator review is not complete.")
        if preview_status != "completed":
            blockers.append(f"LeadIdeal preview status is '{preview_status}', so downstream escalation should wait for review.")
        if approvals.get("public_case_study_approved") and not publishability.get("public_case_study_ready"):
            blockers.append("Public case study approval was requested, but publishability marks this run as not public-ready.")
        if approvals.get("customer_dispatch_approved"):
            status = "approved_customer_dispatch"
            dispatch_blocked = False
            blockers = []
        elif approvals.get("public_case_study_approved"):
            status = "approved_public_case_study"
        elif approvals.get("mining_escalation_approved"):
            status = "approved_for_mining"
        elif approvals.get("operator_review_completed"):
            status = "reviewed"

        if status == "approved_customer_dispatch":
            recommended_next_step = "Dispatch is approved. Use the approved delivery path for this customer."
        elif status == "approved_public_case_study":
            recommended_next_step = "Prepare the redacted public proof variant before publishing."
        elif status == "approved_for_mining":
            recommended_next_step = "Escalate from preview to mining using the approved downstream workflow."
        elif status == "reviewed":
            recommended_next_step = "Choose the next escalation explicitly: mining, public proof, or hold."
        else:
            recommended_next_step = "Review the LeadIdeal preview artifact and approve or reject the next escalation step."

    return {
        **approval_state,
        "updated_at": utc_now_iso(),
        "status": status,
        "dispatch_blocked": dispatch_blocked,
        "approvals": approvals,
        "review_notes": review_notes,
        "review_history": history,
        "allowed_next_actions": {
            "review_internal_brief": True,
            "review_leadideal_preview": True,
            "escalate_to_mining": status in {"approved_for_mining", "approved_public_case_study", "approved_customer_dispatch"},
            "publish_public_case_study": status in {"approved_public_case_study", "approved_customer_dispatch"} and bool(publishability.get("public_case_study_ready")),
            "dispatch_to_customer": status == "approved_customer_dispatch",
        },
        "blockers": blockers,
        "recommended_next_step": recommended_next_step,
    }


def _infer_recommended_experiments(manifest: Dict[str, Any]) -> List[str]:
    competitors = manifest.get("competitors") or []
    target = next((item for item in competitors if item.get("role") == "target"), {})
    others = [item for item in competitors if item.get("role") == "competitor"]

    experiments = []
    competitor_prices_visible = any(item.get("prices_found") for item in others)
    if competitor_prices_visible and not target.get("prices_found"):
        experiments.append("Test a pricing anchor or plan-range section if competitors make pricing more concrete than the target does.")

    competitor_cta_count = max((len(item.get("primary_ctas") or []) for item in others), default=0)
    target_cta_count = len(target.get("primary_ctas") or [])
    if competitor_cta_count > target_cta_count:
        experiments.append("Tighten the primary conversion path into one dominant CTA before adding more secondary actions.")

    if (target.get("change_count") or 0) == 0 and any((item.get("change_count") or 0) > 0 for item in others):
        experiments.append("Run a homepage iteration sprint because the benchmark set shows more visible experimentation than the target.")

    if not experiments:
        experiments.append("Rewrite the homepage around a sharper outcome-led promise with one clear next action.")
        experiments.append("Package the strongest proof point into a visible trust or evidence block above the fold.")

    return experiments[:3]


def render_internal_brief(
    manifest: Dict[str, Any],
    competitors: List[Dict[str, Any]],
    key_findings: Optional[List[str]] = None,
    roi_analysis: Optional[Dict[str, Any]] = None,
) -> str:
    key_findings = key_findings or []
    roi_analysis = roi_analysis or {}
    startup = manifest.get("startup") or {}
    selection = manifest.get("selection") or {}
    summary = manifest.get("summary") or {}
    recommendations = manifest.get("recommendations") or {}
    publishability = manifest.get("publishability") or {}

    if not recommendations.get("recommended_experiments"):
        recommendations["recommended_experiments"] = _infer_recommended_experiments(manifest)

    lines = [
        f"# Startup Intel Sprint: {startup.get('name') or manifest.get('niche_name')}",
        "",
        f"Generated: {manifest.get('generated_at', utc_now_iso())}",
        f"Target URL: {startup.get('target_url', '')}",
        f"Variant: {startup.get('variant_id', 'default')}",
        f"Language / Geo: {startup.get('language', 'en')} / {startup.get('geo', 'global')}",
        f"Objective: {startup.get('objective', '')}",
        "",
        "## Selection",
        "",
        f"- Mode: {selection.get('mode', 'discovery')}",
        f"- Competitor source: {selection.get('competitor_source', 'discovery')}",
        f"- Competitors analyzed: {summary.get('competitors_analyzed', 0)}",
        f"- Locked competitors: {summary.get('competitors_locked', 0)}",
        f"- Total snapshots: {summary.get('total_snapshots', 0)}",
        f"- Total changes: {summary.get('total_changes', 0)}",
        "",
        "## Competitor Set",
        "",
    ]

    for item in manifest.get("competitors", []):
        lines.append(
            f"- {item.get('name')} ({item.get('domain') or item.get('url')}) - {item.get('role')}: {item.get('selection_reason')}"
        )

    lines.extend(["", "## Key Findings", ""])
    if key_findings:
        for finding in key_findings:
            lines.append(f"- {finding}")
    else:
        lines.append("- No AI key findings were generated for this run.")

    lines.extend(["", "## Startup-Specific Recommendations", ""])
    for experiment in recommendations.get("recommended_experiments") or []:
        lines.append(f"- {experiment}")

    if recommendations.get("message_pillars"):
        lines.extend(["", "## Message Pillars", ""])
        for pillar in recommendations.get("message_pillars"):
            lines.append(f"- {pillar}")

    distribution = manifest.get("distribution") or {}
    if distribution.get("leadideal") or distribution.get("creatorpacks"):
        lines.extend(["", "## Distribution Handoffs", ""])
        leadideal = distribution.get("leadideal") or {}
        if leadideal:
            lines.append(
                f"- LeadIdeal: industry={leadideal.get('industry', '')}, roles={leadideal.get('roles', [])}, locations={leadideal.get('locations', [])}"
            )
        creatorpacks = distribution.get("creatorpacks") or {}
        if creatorpacks:
            lines.append(
                f"- CreatorPacks: niche={creatorpacks.get('niche', '')}, persona={creatorpacks.get('persona', '')}, CTA={creatorpacks.get('cta', '')}"
            )

    if roi_analysis:
        lines.extend(["", "## Market Impact", ""])
        for key, value in roi_analysis.items():
            if value in (None, "", [], {}):
                continue
            label = key.replace("_", " ").capitalize()
            lines.append(f"- {label}: {value}")

    lines.extend([
        "",
        "## Publishability",
        "",
        f"- Internal only: {bool(publishability.get('internal_only', False))}",
        f"- Public case study ready: {bool(publishability.get('public_case_study_ready', False))}",
    ])
    redactions = publishability.get("redactions_needed") or []
    if redactions:
        lines.append(f"- Redactions needed: {', '.join(str(item) for item in redactions)}")

    lines.extend(["", "## Evidence Snapshot", ""])
    for competitor in competitors[:4]:
        current = competitor.get("current_analysis") or {}
        headline = current.get("h1") or current.get("title") or "No current headline captured"
        ctas = ", ".join((current.get("cta_buttons") or [])[:3]) or "No CTA buttons captured"
        lines.append(
            f"- {competitor.get('name')}: headline='{headline}', CTAs={ctas}, changes={len(competitor.get('changes', []))}"
        )

    return "\n".join(lines).strip() + "\n"
