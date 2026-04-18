from copy import deepcopy
from typing import Any, Dict, List, Optional


STARTUP_PRESETS: Dict[str, Dict[str, Any]] = {
    "leadideal-en": {
        "preset_id": "leadideal-en",
        "label": "LeadIdeal EN",
        "target_url": "leadideal.com",
        "startup_name": "LeadIdeal EN",
        "variant_id": "en",
        "language": "en",
        "geo": "us",
        "offer": "AI Lead Research",
        "audience": "Founders, agency owners, and heads of growth",
        "objective": "Sharpen positioning and generate an actionable B2B outreach playbook.",
        "message_pillars": [
            "Done-for-you verified lead research",
            "Proof-of-work before full commitment",
            "Higher-intent agency and B2B growth buyers",
        ],
        "recommended_experiments": [
            "Move the homepage promise closer to measurable revenue outcomes rather than generic lead volume.",
            "Use one primary CTA path for pilot engagement before presenting broader package options.",
        ],
        "publishability": {
            "internal_only": False,
            "public_case_study_ready": True,
            "redactions_needed": ["customer names", "internal buyer lists"],
        },
        "leadideal": {
            "industry": "lead generation",
            "roles": ["Founder", "Owner", "Head of Growth", "VP Sales"],
            "locations": ["United States"],
            "job_title": "",
            "base_url": "https://leadideal.com",
            "segment_label": "startup-intel-leadideal-en",
        },
        "seeded_competitors": [
            {"domain": "apollo.io", "selection_reason": "Direct lead intelligence and pipeline benchmark.", "similarity_score": 0.93},
            {"domain": "zoominfo.com", "selection_reason": "Enterprise data and enrichment benchmark.", "similarity_score": 0.82},
            {"domain": "hunter.io", "selection_reason": "Email discovery and lighter-weight lead research benchmark.", "similarity_score": 0.74},
            {"domain": "lusha.com", "selection_reason": "B2B contact-data benchmark with strong outbound positioning.", "similarity_score": 0.79},
        ],
    },
    "leadideal-he": {
        "preset_id": "leadideal-he",
        "label": "LeadIdeal HE",
        "target_url": "leadideal.com/he",
        "startup_name": "LeadIdeal HE",
        "variant_id": "he",
        "language": "he",
        "geo": "il",
        "offer": "AI Lead Research",
        "audience": "Israeli operators, founders, and local-service growth teams",
        "objective": "Evaluate the Hebrew market variant and build a localized acquisition playbook.",
        "message_pillars": [
            "Localized acquisition help for Israeli buyers",
            "Higher-trust positioning for local outreach",
            "Clear pilot-first entry path",
        ],
        "recommended_experiments": [
            "Test a more explicitly localized Hebrew proof block above the fold.",
            "Reduce offer complexity on Hebrew surfaces to one dominant pilot CTA.",
        ],
        "publishability": {
            "internal_only": False,
            "public_case_study_ready": False,
            "redactions_needed": ["Hebrew customer references", "local outreach lists"],
        },
        "leadideal": {
            "industry": "lead generation",
            "roles": ["Founder", "Owner", "Marketing Manager", "Business Development"],
            "locations": ["Israel"],
            "job_title": "",
            "base_url": "https://leadideal.com",
            "segment_label": "startup-intel-leadideal-he",
        },
        "seeded_competitors": [
            {"domain": "apollo.io", "selection_reason": "Reference benchmark for English-first lead intelligence.", "similarity_score": 0.75},
            {"domain": "zoominfo.com", "selection_reason": "Enterprise benchmark for positioning contrast.", "similarity_score": 0.69},
            {"domain": "lusha.com", "selection_reason": "Israeli-rooted B2B data benchmark relevant for localization contrast.", "similarity_score": 0.88},
        ],
    },
    "creatorpacks": {
        "preset_id": "creatorpacks",
        "label": "CreatorPacks",
        "target_url": "creatorpacks.store",
        "startup_name": "CreatorPacks",
        "variant_id": "default",
        "language": "en",
        "geo": "global",
        "offer": "Creator outreach packs",
        "audience": "Brand operators, agencies, and founder-led teams buying micro-influencer lists",
        "objective": "Turn CreatorPacks into a stronger proof-driven storefront and promotion engine.",
        "message_pillars": [
            "Email on file and fit over vanity inventory claims",
            "On-demand custom sourcing for serious buyers",
            "Creator discovery as a trustable workflow, not a black box",
        ],
        "recommended_experiments": [
            "Increase proof density around real creator coverage and fulfillment mode.",
            "Push Custom 25 harder as the safe generic CTA instead of spreading attention across hidden products.",
        ],
        "publishability": {
            "internal_only": False,
            "public_case_study_ready": True,
            "redactions_needed": ["buyer emails", "internal inventory files"],
        },
        "leadideal": {
            "industry": "marketing agencies",
            "roles": ["Founder", "Owner", "Influencer Marketing Manager", "Brand Partnerships"],
            "locations": ["United States"],
            "job_title": "",
            "base_url": "https://leadideal.com",
            "segment_label": "startup-intel-creatorpacks",
        },
        "creatorpacks": {
            "niche": "beauty",
            "persona": "micro creators and niche promotion partners",
            "cta": "Custom 25",
        },
        "seeded_competitors": [
            {"domain": "modash.io", "selection_reason": "Creator discovery and outreach software benchmark.", "similarity_score": 0.8},
            {"domain": "upfluence.com", "selection_reason": "Influencer discovery and campaign workflow benchmark.", "similarity_score": 0.77},
            {"domain": "inbeat.co", "selection_reason": "Micro-influencer and creator sourcing benchmark.", "similarity_score": 0.85},
            {"domain": "hypeauditor.com", "selection_reason": "Analytics-heavy influencer intelligence benchmark.", "similarity_score": 0.7},
        ],
    },
    "beauty-parallels": {
        "preset_id": "beauty-parallels",
        "label": "Beauty Parallels (Historical)",
        "target_url": "vibebrand-beauty.com",
        "startup_name": "Sample Fresh Beauty",
        "variant_id": "default",
        "language": "en",
        "geo": "us",
        "offer": "Historical GTM Analysis",
        "audience": "Fresh beauty brand founders",
        "objective": "Show how established giants looked at the same stage and prove the value of micro-influencer outreach.",
        "message_pillars": [
            "Historical parallel analysis of market leaders",
            "Proof that early wins came from creator-first strategies",
            "Actionable path to replicate Glossier-style growth",
        ],
        "recommended_experiments": [
            "Use historical competitor snapshots (2014-2016) to show the 'early days' playbook.",
            "Map CreatorPacks segments to the specific creator archetypes discovered in matured brands' history.",
        ],
        "publishability": {
            "internal_only": False,
            "public_case_study_ready": True,
            "redactions_needed": ["internal pilot metrics"],
        },
        "leadideal": {
            "industry": "beauty and skincare",
            "roles": ["Founder", "CEO", "Brand Manager"],
            "locations": ["United States"],
            "job_title": "",
            "base_url": "https://leadideal.com",
            "segment_label": "startup-intel-beauty-parallels",
        },
        "seeded_competitors": [
            {
                "domain": "glossier.com",
                "label": "Glossier (Historical: 2014-2016)",
                "selection_reason": "Benchmark for community-led and creator-first beauty growth.",
                "similarity_score": 0.95,
                "to_date": "20161231"
            },
            {
                "domain": "theordinary.com",
                "label": "The Ordinary (Historical: 2016-2018)",
                "selection_reason": "Benchmark for ingredient-transparency and education-led growth.",
                "similarity_score": 0.88,
                "to_date": "20181231"
            },
            {
                "domain": "herocosmetics.us",
                "label": "Hero Cosmetics (Historical: 2017-2019)",
                "selection_reason": "Benchmark for niche-first (pimple patch) and micro-influencer validation.",
                "similarity_score": 0.9,
                "to_date": "20191231"
            },
        ],
    },
}


def list_startup_presets() -> List[Dict[str, Any]]:
    presets = []
    for preset_id, preset in STARTUP_PRESETS.items():
        presets.append(
            {
                "preset_id": preset_id,
                "label": preset.get("label") or preset_id,
                "target_url": preset.get("target_url") or "",
                "language": preset.get("language") or "en",
                "geo": preset.get("geo") or "global",
                "offer": preset.get("offer") or "",
                "seeded_competitor_count": len(preset.get("seeded_competitors") or []),
            }
        )
    return presets


def get_startup_preset(preset_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not preset_id:
        return None
    preset = STARTUP_PRESETS.get(str(preset_id).strip().lower())
    if not preset:
        return None
    return deepcopy(preset)


def apply_startup_preset(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = deepcopy(payload or {})
    preset = get_startup_preset(payload.get("preset_id"))
    if not preset:
        return payload

    merged = deepcopy(preset)
    for key, value in payload.items():
        if key in {"leadideal", "creatorpacks", "publishability"} and isinstance(value, dict):
            existing = merged.get(key) or {}
            existing.update(value)
            merged[key] = existing
        elif key == "seeded_competitors" and value:
            merged[key] = value
        else:
            merged[key] = value

    if not merged.get("target_url") and preset.get("target_url"):
        merged["target_url"] = preset["target_url"]
    return merged
