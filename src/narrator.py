"""
Strategic Narrator.
Uses Gemini to interpret website changes and explain the underlying business strategy shifts.
"""

import json
import importlib
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import dotenv_values

try:
    modern_genai = importlib.import_module("google.genai")
except ImportError:
    modern_genai = None

try:
    legacy_genai = importlib.import_module("google.generativeai")
except ImportError:
    legacy_genai = None

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIDEO_GEN_CLEAN_ROOT = PROJECT_ROOT.parent / "video-gen-clean"
VIDEO_GEN_CREDENTIAL_PATHS = [
    VIDEO_GEN_CLEAN_ROOT / ".env",
    VIDEO_GEN_CLEAN_ROOT / ".env.production",
    VIDEO_GEN_CLEAN_ROOT / "remote.env",
]

# Default model
MODEL_NAME = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")

INDUSTRY_COMPETITOR_MAP = {
    "lead_generation": ["apollo.io", "lead411.com", "hunter.io", "clearbit.com", "zoominfo.com"],
    "lead_generation__low_self_serve": ["apollo.io", "uplead.com", "hunter.io", "snov.io", "instantly.ai"],
    "lead_generation__il_us_bridge": ["lusha.com", "uplead.com", "hunter.io", "snov.io", "wiza.co"],
    "crm": ["hubspot.com", "salesforce.com", "zoho.com", "pipedrive.com", "close.com"],
    "email_marketing": ["mailchimp.com", "convertkit.com", "activecampaign.com", "brevo.com", "klaviyo.com"],
    "landing_pages": ["unbounce.com", "instapage.com", "leadpages.com", "carrd.co", "webflow.com"],
    "project_management": ["clickup.com", "monday.com", "asana.com", "notion.so", "linear.app"],
    "ai_writing": ["jasper.ai", "copy.ai", "writesonic.com", "writer.com", "rytr.me"],
    "video_generation": ["synthesia.io", "runwayml.com", "descript.com", "invideo.io", "veed.io"],
    "generic_saas": ["intercom.com", "zendesk.com", "stripe.com", "slack.com", "atlassian.com"],
}

CATEGORY_KEYWORDS = [
    ("landing_pages", {"landing", "unbounce", "instapage", "leadpage", "carrd", "webflow", "framer"}),
    ("lead_generation", {"lead", "prospect", "apollo", "zoominfo", "hunter", "outreach", "enrich", "list"}),
    ("crm", {"crm", "sales", "pipeline", "hubspot", "salesforce", "pipedrive", "close"}),
    ("email_marketing", {"email", "mail", "newsletter", "campaign", "klaviyo", "sendgrid", "brevo"}),
    ("project_management", {"project", "task", "kanban", "notion", "asana", "clickup", "monday", "linear"}),
    ("ai_writing", {"write", "writer", "writing", "copy", "content", "jasper", "writesonic", "rytr"}),
    ("video_generation", {"video", "short", "shorts", "clip", "movie", "runway", "synthesia", "descript", "veed"}),
]

SYSTEM_PROMPT = """
You are a competitive intelligence analyst. Your job is to summarize EVIDENCE that has been
retrieved from competitor websites. You are not a consultant or copywriter.

HARD RULES — VIOLATING ANY OF THESE INVALIDATES YOUR RESPONSE:
1. NEVER invent metrics, percentages, time estimates, conversion rates, or dollar amounts.
   Only cite numbers that appear verbatim in the data provided. If no number is in the data,
   describe the change qualitatively (e.g. "shifted from X to Y") instead of fabricating one.
2. NEVER use these words or phrases (they are filler that reduces credibility):
   "surgical", "surgical precision", "uncompromising", "white noise", "battleground",
   "laser focus", "laser-focused", "razor-sharp", "cutting-edge", "best-in-class",
   "game-changer", "game-changing", "next-level", "supercharge", "unlock", "unleash",
   "revolutionary", "disruptive", "synergy", "leverage" (as verb), "world-class",
   "ninja", "guru", "rockstar", "10x" (unless quoting the source).
3. Every claim about a specific competitor must reference an observable signal from the
   supplied data — quote a real H1, CTA, tech stack item, pricing line, or change diff.
4. Be concise. Prefer plain English. No jargon padding for length.
5. If evidence is thin or absent, SAY SO ("no significant change observed") rather than
   filling with speculation.
"""

# Banned phrases used by the post-generation linter. Lowercase substring match.
BANNED_PHRASES = [
    "surgical precision", "surgical", "uncompromising", "white noise",
    "battleground", "laser focus", "laser-focused", "laser sharp",
    "razor-sharp", "razor sharp", "cutting-edge", "best-in-class",
    "game-changer", "game-changing", "game changer", "next-level",
    "supercharge", "supercharging", "unleash", "revolutionary",
    "disruptive", "synergy", "world-class", "world class",
    "rockstar", "ninja", "guru",
]

# Pattern for invented metrics (numbers + units) we must verify.
# We allow numbers if they appear in the same sentence as a quoted source word
# like "from", "to", "changed", or appear inside the data we passed in.
SUSPECT_METRIC_RE = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:x|%|days?|weeks?|months?|hours?|minutes?|seconds?|"
    r"k|m|million|billion|percent))\b",
    re.IGNORECASE,
)


def _redact_banned_phrases(text: str) -> str:
    """Strip banned phrases. Returns cleaned text."""
    if not text:
        return text
    out = text
    for phrase in BANNED_PHRASES:
        # Case-insensitive replace with empty (then collapse spaces)
        out = re.sub(re.escape(phrase), "", out, flags=re.IGNORECASE)
    # Collapse multiple spaces and orphan punctuation
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return out.strip()


def _strip_unsourced_metrics(text: str, allowed_text: str = "") -> str:
    """
    Replace numeric-claim phrases that DO NOT appear in the source data with a
    qualitative placeholder. Conservative: only acts on patterns like '2x',
    '47%', '7 days', '60 seconds'.
    """
    if not text:
        return text
    allowed_lc = (allowed_text or "").lower()

    def _replace(match):
        token = match.group(0)
        if token.lower() in allowed_lc:
            return token
        return "[unverified metric removed]"

    return SUSPECT_METRIC_RE.sub(_replace, text)


def lint_output(text_or_hooks, allowed_data_blob=None):
    """Public helper: strip banned phrases and unsourced metrics from LLM output."""
    if isinstance(text_or_hooks, str):
        # Legacy string mode
        cleaned = _redact_banned_phrases(text_or_hooks or "")
        cleaned = _strip_unsourced_metrics(cleaned, allowed_data_blob or "")
        return cleaned
    elif isinstance(text_or_hooks, list):
        # New hooks mode
        hooks = text_or_hooks
        allowed_quotes = {q.get("quote", "").lower() for q in (allowed_data_blob or [])}

        for hook in hooks:
            opener = hook.get("opener", "")
            rationale = hook.get("rationale", "")

            # Remove banned phrases
            for banned in BANNED_PHRASES:
                opener = opener.replace(banned, "[REDACTED]")
                rationale = rationale.replace(banned, "[REDACTED]")

            # Check for unverified metrics
            for match in SUSPECT_METRIC_RE.finditer(opener + rationale):
                metric = match.group(0)
                # Allow if it appears in the evidence quotes
                if metric.lower() not in allowed_quotes:
                    opener = opener.replace(metric, "[UNVERIFIED]")
                    rationale = rationale.replace(metric, "[UNVERIFIED]")

            hook["opener"] = opener
            hook["rationale"] = rationale

        return hooks
    else:
        return text_or_hooks


def _build_target_snapshot_block(target: Optional[Dict]) -> str:
    """Format the target's live homepage data into a compact block for prompts."""
    if not target:
        return "TARGET SNAPSHOT: (not available)"
    current = target.get("current_analysis") or {}
    name = target.get("name", "(target)")
    url = target.get("url", "")
    h1 = (current.get("h1") or "").strip()[:200]
    meta = (current.get("meta_description") or "").strip()[:300]
    ctas = current.get("cta_buttons", []) or []
    tech = current.get("tech_stack", []) or []
    pricing = current.get("pricing", "") or ""
    return (
        f"TARGET SNAPSHOT — {name} ({url})\n"
        f"  H1: {h1 or '(none)'}\n"
        f"  Meta: {meta or '(none)'}\n"
        f"  CTAs: {ctas[:5]}\n"
        f"  Tech (top 8): {tech[:8]}\n"
        f"  Pricing signal: {str(pricing)[:200] or '(none)'}"
    )


def _build_evidence_block(competitors: List[Dict], max_per_comp: int = 4) -> str:
    """Format collected evidence quotes into a citation block for prompts."""
    lines = ["EVIDENCE QUOTES (verbatim from competitor sites):"]
    any_quote = False
    for comp in competitors:
        quotes = comp.get("evidence_quotes") or []
        if not quotes:
            continue
        for q in quotes[:max_per_comp]:
            any_quote = True
            text = (q.get("quote") or "").strip().replace("\n", " ")[:240]
            src = q.get("url", "")
            section = q.get("section", "")
            lines.append(f"  - [{comp['name']} / {section}] \"{text}\" -- {src}")
    if not any_quote:
        return ""
    return "\n".join(lines)





def _extract_first_google_key(raw_value: Optional[str]) -> Optional[str]:
    if not raw_value:
        return None

    value = raw_value.strip()
    if not value:
        return None

    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
        except json.JSONDecodeError:
            pass

    for chunk in value.split(","):
        candidate = chunk.strip()
        if candidate:
            return candidate
    return None


def hydrate_gemini_key_from_video_gen_clean(override: bool = True) -> Optional[str]:
    if not override and os.getenv("GEMINI_API_KEY"):
        return os.getenv("GEMINI_API_KEY")

    for env_path in VIDEO_GEN_CREDENTIAL_PATHS:
        if not env_path.exists():
            continue

        try:
            values = dotenv_values(env_path)
        except Exception as exc:
            logger.warning("Unable to parse video-gen-clean env source %s: %s", env_path.name, exc)
            continue

        candidate = (
            values.get("GEMINI_API_KEY")
            or _extract_first_google_key(values.get("GOOGLE_API_KEYS"))
            or values.get("GOOGLE_API_KEY")
        )
        if candidate:
            os.environ["GEMINI_API_KEY"] = candidate
            os.environ["WAYBACK_GEMINI_SOURCE"] = f"video-gen-clean:{env_path.name}"
            logger.info("Loaded Gemini credential from video-gen-clean env source.")
            return candidate

    return os.getenv("GEMINI_API_KEY")

class StrategicNarrator:
    """Interprets competitor evolution using LLMs."""

    def __init__(self, api_key: Optional[str] = None):
        hydrated_key = api_key or hydrate_gemini_key_from_video_gen_clean(override=True)
        self.api_key = hydrated_key or os.getenv("GEMINI_API_KEY")
        self.mock_mode = self.api_key in (None, "your_api_key_here", "")
        self.enabled = False
        self.client = None
        self.model = None
        self.backend = None
        self.discovery_source = "unavailable"
        self.env_source = os.getenv("WAYBACK_GEMINI_SOURCE", "local")

        if self.mock_mode:
            self.enabled = True
            self.backend = "mock"
            logger.info("StrategicNarrator: Running in MOCK mode (No valid API key found)")
        elif self.api_key and modern_genai is not None:
            try:
                self.client = modern_genai.Client(api_key=self.api_key)
                self.backend = "google.genai"
                self.enabled = True
                logger.info("StrategicNarrator initialized with Gemini via %s from %s.", self.backend, self.env_source)
            except Exception as e:
                logger.error("Failed to initialize Gemini via google.genai: %s", e)
        elif self.api_key and legacy_genai is not None:
            try:
                legacy_genai.configure(api_key=self.api_key)
                self.model = legacy_genai.GenerativeModel(
                    model_name=MODEL_NAME,
                    system_instruction=SYSTEM_PROMPT,
                )
                self.backend = "google.generativeai"
                self.enabled = True
                logger.info("StrategicNarrator initialized with Gemini via %s from %s.", self.backend, self.env_source)
            except Exception as e:
                logger.error("Failed to initialize Gemini via google.generativeai: %s", e)
        else:
            logger.warning("No Gemini SDK or valid key available. AI Narrator will use domain-aware fallback discovery.")

    @staticmethod
    def _normalize_domain(value: str) -> str:
        domain = (value or "").strip().lower()
        domain = re.sub(r"^https?://", "", domain)
        domain = domain.split("/")[0].strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def infer_category(self, target_domain: str) -> str:
        normalized = self._normalize_domain(target_domain)
        haystack = normalized.replace(".", " ").replace("-", " ").replace("_", " ")
        for category, keywords in CATEGORY_KEYWORDS:
            if any(keyword in haystack for keyword in keywords):
                return category
        return "generic_saas"

    def infer_wedge_cluster(self, category: str, wedge: Optional[Dict] = None) -> str:
        """Pick a sub-cluster key inside INDUSTRY_COMPETITOR_MAP based on wedge facets.

        Falls back to the bare category if no sub-cluster matches.
        """
        if not wedge or category != "lead_generation":
            return category
        geo_origin = (wedge.get("geo_origin") or "").lower()
        geo_target = (wedge.get("geo_target") or "").lower()
        price_tier = (wedge.get("price_tier") or "").lower()
        if geo_origin in {"il", "israel"} and geo_target in {"us", "united states"}:
            key = "lead_generation__il_us_bridge"
            if key in INDUSTRY_COMPETITOR_MAP:
                return key
        if price_tier == "low_self_serve":
            key = "lead_generation__low_self_serve"
            if key in INDUSTRY_COMPETITOR_MAP:
                return key
        return category

    def get_fallback_competitors(self, target_domain: str, limit: int = 5, wedge: Optional[Dict] = None) -> List[str]:
        category = self.infer_category(target_domain)
        cluster = self.infer_wedge_cluster(category, wedge)
        bucket = INDUSTRY_COMPETITOR_MAP.get(cluster) or INDUSTRY_COMPETITOR_MAP["generic_saas"]
        return bucket[:limit]

    def _generate_text(self, prompt: str) -> str:
        if not self.enabled:
            return ""

        if self.mock_mode:
            # Provide high-quality mock data for testing
            if "Executive Strategic Summary" in prompt:
                return "Market positioning has shifted: the largest competitors emphasise enterprise readiness in their current homepage copy, while the target's homepage frames the offer around speed of insight. The gap is in mid-market positioning where no observed competitor leads on time-to-first-result."
            if "Strategic Comparison" in prompt:
                return "This competitor's current homepage H1 emphasises enterprise scale; their pricing page lists tiered enterprise plans. Their recent change history shows a consistent move from self-serve to demo-first signup. The opening for the target is to keep self-serve signup visible and named."
            if "Actionable Agent Tasks" in prompt:
                return json.dumps([
                    {
                        "category": "marketing",
                        "priority": "high",
                        "task": "Differentiate by keeping self-serve signup above the fold",
                        "rationale": "Two of three competitors moved their primary CTA from 'Start free' to 'Book a demo'; the target still has 'Start free'.",
                        "agent_prompt_snippet": "Audit the homepage hero and confirm the primary CTA still routes to the self-serve flow."
                    }
                ])
            return "Mock narrative output. No invented metrics."

        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt.strip()}"

        try:
            if self.client is not None:
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    contents=full_prompt,
                )
            else:
                response = self.model.generate_content(full_prompt)
        except Exception as exc:
            logger.error("Gemini request failed. Disabling AI narrator for this run: %s", exc)
            self.enabled = False
            self.discovery_source = "fallback"
            return ""

        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        candidates = getattr(response, "candidates", None) or []
        parts = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(part_text)
        return "\n".join(parts).strip()

    def _normalize_competitor_domains(self, values: List[str], target_domain: str) -> List[str]:
        normalized_target = self._normalize_domain(target_domain)
        normalized = []
        seen = set()
        for value in values:
            if not isinstance(value, str):
                continue
            domain = self._normalize_domain(value)
            if not domain or domain == normalized_target or domain in seen:
                continue
            seen.add(domain)
            normalized.append(domain)
        return normalized

    def generate_niche_summary(
        self,
        niche_name: str,
        competitors: List[Dict],
        target: Optional[Dict] = None,
    ) -> str:
        """Generate a buyer-first executive summary grounded in the target's actual site."""
        if not self.enabled:
            return ""

        # Build context: target first, then non-target competitors
        target = target or (competitors[0] if competitors else None)
        non_target = [c for c in competitors if c is not target]

        comp_context = []
        for comp in non_target:
            latest = comp["analyses"][-1] if comp.get("analyses") else {}
            if hasattr(latest, "to_dict"):
                latest = latest.to_dict()
            comp_summary = {
                "name": comp["name"],
                "url": comp.get("url", ""),
                "total_changes": len(comp.get("changes", [])),
                "current_h1": (latest.get("h1") or "")[:200],
                "current_meta": (latest.get("meta_description") or "")[:300],
                "current_ctas": (latest.get("cta_buttons") or [])[:5],
                "current_tech": (latest.get("tech_stack") or [])[:8],
                "pricing_signal": str(latest.get("pricing", ""))[:200],
            }
            comp_context.append(comp_summary)

        target_block = _build_target_snapshot_block(target)
        evidence_block = _build_evidence_block(non_target)

        prompt = f"""
Niche: '{niche_name}'.

{target_block}

COMPETITORS (live homepage signals): {json.dumps(comp_context, indent=2)}

{evidence_block}

Write an Executive Strategic Summary that a buyer of the target product would find useful.
Use the EXACT structure below. Do not use markdown headers, just the labeled lines.

TARGET POSITION: One sentence describing what the target's homepage actually says today
(quote its H1 verbatim if useful). If the target snapshot is missing, say "(target not analyzed)".

COMPETITOR LANDSCAPE: 2-3 sentences contrasting the competitors' current positioning.
Reference specific competitor H1s, CTAs or pricing signals from the data above. Do NOT
invent positioning that is not visible in the supplied data.

GAPS THE TARGET CAN OWN: 2-3 sentences naming concrete openings (e.g. "no competitor's
visible homepage CTA mentions self-serve pricing"). Each opening must be supported by an
observable signal from the data.

Output ONLY the labeled lines. No markdown. No invented numbers. No filler superlatives.
"""
        # Build allowed-data blob so the linter knows which numbers came from the source
        allowed = json.dumps({"target": target_block, "comps": comp_context, "evidence": evidence_block})
        return lint_output(self._generate_text(prompt), allowed)

    def generate_competitor_insight(self, competitor_name: str, changes: List[Dict], current_analysis: Optional[Dict] = None) -> str:
        """Generate a strategic insight for a competitor's evolution or current posture."""
        if not self.enabled:
            return ""

        if not changes:
            if not current_analysis:
                return "No significant changes or live data to analyze."

            # Fallback to Current State Analysis
            prompt = f"""
Analyze the current homepage of '{competitor_name}'.
Live Site Signals: {json.dumps(current_analysis, indent=2)}

Output 3 short labeled lines, no markdown, no invented metrics:

POSITIONING (one sentence): What is the headline promise on their homepage right now?
Quote the H1 verbatim where possible.
VULNERABILITY (one sentence): What concrete signal in the data above suggests an opening
for a leaner competitor (e.g. enterprise-only CTAs, missing pricing page link, narrow ICP)?
COUNTER-MOVE (one sentence): How can the target's homepage differentiate against this?
Tie the recommendation to the specific signal cited in VULNERABILITY.
"""
            allowed = json.dumps(current_analysis)
            return lint_output(self._generate_text(prompt), allowed)

        # Simplify changes for the prompt to save tokens and focus on strategy
        clean_changes = []
        for c in changes[:12]: # Focus on last 12 changes for richer context
            diff = c.get("diffs", {})
            essential = {
                "date_range": f"{c['from_ts']} -> {c['to_ts']}",
                "highlights": []
            }
            if "h1" in diff: essential["highlights"].append(f"H1 changed: {diff['h1']}")
            if "meta_description" in diff: essential["highlights"].append(f"Meta description changed: {diff['meta_description']}")
            if "pricing" in diff: essential["highlights"].append(f"Pricing changed: {diff['pricing']}")
            if "cta_buttons" in diff: essential["highlights"].append(f"CTAs changed: {diff['cta_buttons']}")
            if "tech_stack" in diff:
                added = diff['tech_stack'].get('added', [])
                removed = diff['tech_stack'].get('removed', [])
                if added: essential["highlights"].append(f"Tech added: {added}")
                if removed: essential["highlights"].append(f"Tech removed: {removed}")
            if "word_count" in diff: essential["highlights"].append(f"Word count changed: {diff['word_count']}")

            if essential["highlights"]:
                clean_changes.append(essential)

        if not clean_changes:
            return "Stable strategy detected with no major pivots."

        prompt = f"""
Analyze the historical evolution of '{competitor_name}'.
Historical Signal Changes: {json.dumps(clean_changes, indent=2)}
Current Live State: {json.dumps(current_analysis or {}, indent=2)}

Output 3 short labeled lines, no markdown, no invented metrics, no superlatives:

PIVOT (one sentence): Their most significant historical messaging change. Quote the
"from -> to" of the H1 or CTA verbatim from the data.
SACRIFICE (one sentence): What did this pivot cost them — what is missing from their
current homepage that earlier versions had? Cite the observable signal.
COUNTER-MOVE (one sentence): A concrete homepage move the target can make right now to
exploit this gap. Tie it to the SACRIFICE.
"""
        allowed = json.dumps({"changes": clean_changes, "current": current_analysis or {}})
        return lint_output(self._generate_text(prompt), allowed)

    def find_competitors(self, target_domain: str, wedge: Optional[Dict] = None) -> List[str]:
        """Auto-discover competitors for a given domain using the LLM or domain-aware fallbacks.

        If a `wedge` dict is provided (geo_target/geo_origin/price_tier/business_model/
        audience_segment), the LLM prompt is constrained to only return competitors that
        match the wedge, and the fallback bucket switches to a wedge-aware sub-cluster.
        """
        fallback_competitors = self.get_fallback_competitors(target_domain, wedge=wedge)

        if not self.enabled:
            self.discovery_source = "fallback"
            logger.warning("Narrator disabled. Using domain-aware fallback competitors for %s.", target_domain)
            return fallback_competitors

        if wedge:
            constraint_lines = []
            if wedge.get("geo_origin") and wedge.get("geo_target"):
                constraint_lines.append(
                    f"- The TARGET is founded in '{wedge['geo_origin']}' and sells primarily to buyers in '{wedge['geo_target']}'."
                )
            elif wedge.get("geo_target"):
                constraint_lines.append(f"- The TARGET sells primarily to buyers in '{wedge['geo_target']}'.")
            if wedge.get("price_tier"):
                pt = wedge["price_tier"]
                pt_label = {
                    "low_self_serve": "low-cost self-serve tools (single-digit to low-double-digit USD/month)",
                    "mid_market": "mid-market SaaS (mid-hundreds to low-thousands USD/month)",
                    "enterprise": "enterprise platforms (5-figure-plus annual contracts)",
                    "agency_retainer": "agency / done-for-you retainers (4-figure-plus monthly retainers)",
                }.get(pt, pt)
                constraint_lines.append(f"- Only return competitors in the price tier: {pt_label}. Exclude competitors that are clearly more expensive or in a different buying motion.")
            if wedge.get("business_model"):
                bm = wedge["business_model"]
                bm_label = {
                    "self_serve": "self-serve product (signup + credit card, no sales call)",
                    "sales_led": "sales-led SaaS (book-a-demo gated entry)",
                    "agency_service": "agency or done-for-you service",
                    "managed_service": "managed service with humans in the loop",
                }.get(bm, bm)
                constraint_lines.append(f"- Only return competitors whose business model is: {bm_label}.")
            if wedge.get("audience_segment"):
                constraint_lines.append(f"- The audience the TARGET serves is: '{wedge['audience_segment']}'. Match competitors that sell to the same audience.")
            constraint_block = "\n".join(constraint_lines) if constraint_lines else ""
            prompt = f"""
Find the top 5 direct business competitors for the company represented by the domain: '{target_domain}'.

CONSTRAINTS (all must hold for every competitor you return):
{constraint_block}

DO NOT include large enterprise platforms, $50k+ annual contract vendors, or done-for-you
agencies if the constraints above ask for low-cost self-serve tools. The buyer reading this
report is choosing between alternatives in the same price band and buying motion as the
target; comparing them against vendors 100x more expensive is wrong.

Return ONLY a valid JSON array of their primary root domain strings
(e.g. ["competitor1.com", "competitor2.com"]). No other text, no markdown, no explanations.
"""
        else:
            prompt = f"""
Find the top 5 direct business competitors for the company represented by the domain: '{target_domain}'.
Return ONLY a valid JSON array of their primary root domain strings (e.g. ["competitor1.com", "competitor2.com"]).
Do not include any other text, markdown formatting, or explanations.
"""
        try:
            text = self._generate_text(prompt)
            if not text:
                self.discovery_source = "fallback"
                return fallback_competitors
            # Clean possible markdown format from LLM
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.startswith("```"):
                text = text.replace("```", "", 1)
            if text.endswith("```"):
                text = text[:-3]

            parsed = json.loads(text.strip())
            if isinstance(parsed, dict):
                parsed = parsed.get("competitors", [])

            ai_competitors = self._normalize_competitor_domains(parsed, target_domain)
            if not ai_competitors:
                self.discovery_source = "fallback"
                logger.warning("Gemini returned no usable competitors for %s. Using fallback set.", target_domain)
                return fallback_competitors

            merged = self._normalize_competitor_domains(ai_competitors + fallback_competitors, target_domain)
            if wedge:
                self.discovery_source = "ai_wedged" if len(ai_competitors) >= 3 else "ai_wedged_blended"
            else:
                self.discovery_source = "ai" if len(ai_competitors) >= 3 else "ai_blended"
            return merged[:5]
        except Exception as e:
            logger.error("Error discovering competitors for %s: %s", target_domain, e)
            self.discovery_source = "fallback"
            return fallback_competitors

    def generate_key_findings(self, niche_name: str, competitors: List[Dict]) -> List[str]:
        """Generate 3-5 bullet-point key findings from the competitor data."""
        if not self.enabled:
            return []

        context = []
        for comp in competitors:
            changes_summary = []
            for c in comp.get("changes", [])[:5]:
                diffs = c.get("diffs", {})
                parts = []
                if "h1" in diffs:
                    parts.append(f"H1: {diffs['h1'].get('from','')} -> {diffs['h1'].get('to','')}")
                if "cta_buttons" in diffs:
                    added = diffs["cta_buttons"].get("added", [])
                    removed = diffs["cta_buttons"].get("removed", [])
                    if added:
                        parts.append(f"Added CTAs: {added}")
                    if removed:
                        parts.append(f"Removed CTAs: {removed}")
                if "tech_stack" in diffs:
                    added = diffs["tech_stack"].get("added", [])
                    removed = diffs["tech_stack"].get("removed", [])
                    if added:
                        parts.append(f"Added tech: {added}")
                    if removed:
                        parts.append(f"Dropped tech: {removed}")
                if "pricing" in diffs:
                    parts.append(f"Pricing change: {diffs['pricing']}")
                if parts:
                    changes_summary.append({"period": f"{c['from_ts']} -> {c['to_ts']}", "changes": parts})

            context.append({"name": comp["name"], "changes": changes_summary})

        prompt = f"""
Analyze this competitive landscape: '{niche_name}'.
Competitor Changes: {json.dumps(context, indent=2)}

Return ONLY a valid JSON array of 3 to 5 key findings as short strings (each under 140 characters).
Each finding must reference an OBSERVED signal in the data above (a specific competitor name
plus a specific change). Do NOT invent percentages, multipliers or time-to-result metrics.
Do NOT use the words: surgical, uncompromising, white noise, battleground, laser focus,
game-changer, supercharge, revolutionary, world-class, leverage.
Good example: ["Apollo.io moved its primary CTA from 'Start free' to 'Get demo' in 2023", "Hunter.io added Stripe and removed Intercom in their tech stack"]
No markdown, no explanations, just the JSON array.
"""
        try:
            text = self._generate_text(prompt)
            if not text:
                return []
            text = text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.startswith("```"):
                text = text.replace("```", "", 1)
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
            if isinstance(parsed, list):
                allowed = json.dumps(context)
                return [lint_output(str(f), allowed) for f in parsed[:5] if f]
        except Exception as exc:
            logger.error("Failed to generate key findings: %s", exc)
        return []

    def generate_agent_tasks(
        self,
        niche_name: str,
        competitors: List[Dict],
        target: Optional[Dict] = None,
    ) -> List[Dict]:
        """Generate a machine-readable list of actionable tasks grounded in observed signals."""
        if not self.enabled:
            return []

        target = target or (competitors[0] if competitors else None)
        non_target = [c for c in competitors if c is not target]

        context = []
        for comp in non_target:
            comp_context = {
                "name": comp["name"],
                "key_shifts": []
            }
            # Latest state
            analyses = comp.get("analyses", [])
            if analyses:
                latest = analyses[-1] if isinstance(analyses[-1], dict) else analyses[-1].to_dict()
                comp_context["current_focus"] = latest.get("h1", "")
                comp_context["current_ctas"] = (latest.get("cta_buttons") or [])[:5]

            # Key historical changes
            for c in comp.get("changes", [])[:5]:
                diffs = c.get("diffs", {})
                if "h1" in diffs: comp_context["key_shifts"].append(f"H1: {diffs['h1']}")
                if "pricing" in diffs: comp_context["key_shifts"].append(f"Pricing: {diffs['pricing']}")
                if "cta_buttons" in diffs: comp_context["key_shifts"].append(f"CTAs: {diffs['cta_buttons']}")
                if "tech_stack" in diffs: comp_context["key_shifts"].append(f"Tech: {diffs['tech_stack']}")

            context.append(comp_context)

        target_block = _build_target_snapshot_block(target)

        prompt = f"""
Niche: '{niche_name}'.

{target_block}

COMPETITOR DATA: {json.dumps(context, indent=2)}

Generate 3-5 concrete tasks the target's team can execute on the target's homepage THIS WEEK.
Each task must:
- Reference a specific observed signal from the COMPETITOR DATA above (quote the H1, CTA,
  tech entry, or pricing change verbatim in the rationale).
- Describe a single, narrow homepage change (one section, one CTA, one copy block).
- NOT invent metrics ("2x", "47%", "in 7 days") that are not in the source data.
- NOT use the words: surgical, uncompromising, white noise, battleground, laser focus,
  game-changer, supercharge, revolutionary, world-class, leverage.

Return ONLY a valid JSON array with this structure:
[
  {{
    "category": "positioning | messaging | conversion | trust",
    "priority": "high | medium | low",
    "task": "One-sentence concrete change to make on the target's homepage",
    "rationale": "Cite the specific competitor signal that motivates this (verbatim quote where possible)",
    "agent_prompt_snippet": "A one-sentence instruction an AI coding agent can execute"
  }}
]

No markdown, no preamble.
"""
        try:
            text = self._generate_text(prompt)
            if not text:
                return []
            text = text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.startswith("```"):
                text = text.replace("```", "", 1)
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
            if isinstance(parsed, list):
                allowed = json.dumps({"target": target_block, "comps": context})
                cleaned = []
                for item in parsed[:8]:
                    if not isinstance(item, dict):
                        continue
                    for k in ("task", "rationale", "agent_prompt_snippet"):
                        if k in item and isinstance(item[k], str):
                            item[k] = lint_output(item[k], allowed)
                    cleaned.append(item)
                return cleaned
        except Exception as exc:
            logger.error("Failed to generate agent tasks: %s", exc)
        return []

    def generate_roi_analysis(
        self,
        niche_name: str,
        competitors: List[Dict],
        target_url: str = "",
        target: Optional[Dict] = None,
    ) -> Dict:
        """Generate market signal analysis grounded in observed competitor data."""
        if not self.enabled:
            return {}

        target = target or (competitors[0] if competitors else None)
        non_target = [c for c in competitors if c is not target]

        context = []
        for comp in non_target:
            comp_context = {
                "name": comp["name"],
                "url": comp.get("url", ""),
                "snapshot_count": comp.get("snapshot_count", 0),
                "change_count": len(comp.get("changes", [])),
            }

            # Latest state
            analyses = comp.get("analyses", [])
            if analyses:
                latest = analyses[-1] if isinstance(analyses[-1], dict) else analyses[-1].to_dict()
                comp_context["current_tech_count"] = len(latest.get("tech_stack", []))
                comp_context["current_tech"] = latest.get("tech_stack", [])[:10]
                comp_context["current_ctas"] = latest.get("cta_buttons", [])[:5]
                comp_context["current_h1"] = latest.get("h1", "")

            # Summarize key changes
            key_changes = []
            for c in comp.get("changes", [])[:8]:
                diffs = c.get("diffs", {})
                parts = []
                for field in ("h1", "pricing", "cta_buttons", "tech_stack"):
                    if field in diffs:
                        parts.append(f"{field}: {diffs[field]}")
                if parts:
                    key_changes.append({"period": f"{c['from_ts']} -> {c['to_ts']}", "shifts": parts})
            comp_context["key_changes"] = key_changes
            context.append(comp_context)

        target_block = _build_target_snapshot_block(target)

        prompt = f"""
Niche: '{niche_name}'.
Target URL: {target_url or 'unknown'}

{target_block}

COMPETITOR DATA: {json.dumps(context, indent=2)}

Read the competitor data and interpret using ONLY these observable proxy indicators:
- Tech stack added (Stripe, analytics, HubSpot) -> growth investment signal
- Tech stack removed (Intercom, live chat) -> cost-cutting or pivot
- CTA shift "Start free" -> "Book demo" -> moving upmarket
- CTA shift "Free" -> "Pricing" -> monetisation pressure
- Pricing shifts -> repositioning
- H1 shifts -> repositioning

HARD RULES:
- Cite real competitor names and quote their actual H1 / CTA / tech entries.
- Do NOT invent percentages, multipliers, time-to-result claims.
- Do NOT use the words: surgical, uncompromising, white noise, battleground, laser focus,
  game-changer, supercharge, revolutionary, world-class, leverage.
- The recommendation_for_target must reference the TARGET SNAPSHOT above (compare what the
  target's homepage actually says against what competitors are doing).

Return ONLY valid JSON with this exact structure:
{{
  "winning_strategies": [
    {{"signal": "Short title", "detail": "1-2 sentences citing a specific competitor and the verbatim signal"}}
  ],
  "failing_signals": [
    {{"signal": "Short title", "detail": "1-2 sentences citing the specific signal"}}
  ],
  "market_trends": ["Trend statement quoting at least one competitor signal", "..."],
  "recommendation_for_target": "2-3 sentences. Reference the target's actual H1 or CTA from the TARGET SNAPSHOT, contrast with at least one competitor signal, propose ONE concrete homepage change."
}}

Keep each array to 2-4 items max. No markdown wrapping.
"""
        try:
            text = self._generate_text(prompt)
            if not text:
                return {}
            text = text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.startswith("```"):
                text = text.replace("```", "", 1)
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict):
                allowed = json.dumps({"target": target_block, "comps": context})
                # Lint string fields throughout the structure
                for arr_key in ("winning_strategies", "failing_signals"):
                    items = parsed.get(arr_key) or []
                    for it in items:
                        if isinstance(it, dict):
                            for k in ("signal", "detail"):
                                if isinstance(it.get(k), str):
                                    it[k] = lint_output(it[k], allowed)
                if isinstance(parsed.get("market_trends"), list):
                    parsed["market_trends"] = [
                        lint_output(str(t), allowed) for t in parsed["market_trends"]
                    ]
                if isinstance(parsed.get("recommendation_for_target"), str):
                    parsed["recommendation_for_target"] = lint_output(
                        parsed["recommendation_for_target"], allowed
                    )
                return parsed
        except Exception as exc:
            logger.error("Failed to generate ROI analysis: %s", exc)
        return {}
    def generate_video_script(self, niche_name: str, competitors: List[Dict], breakthrough_story: Optional[str] = None) -> Dict:
        """Generate a 60-second cinematic video script for the video engine."""
        if not self.enabled:
            return {}

        context = {
            "niche": niche_name,
            "competitors": [c["name"] for c in competitors],
            "story": breakthrough_story or "Generic market analysis summary."
        }

        prompt = f"""
You are a Video Scriptwriter specializing in "High-Conviction Startup Vibe." Your goal is to write a 60-second video script for the '{niche_name}' space.

Context: {json.dumps(context, indent=2)}

Narrative Style: Imagine a "Forensic Documentary" - dramatic, data-driven, and high-stakes.
Script Structure:
1. Hook (0-10s): The problem/stagnation in the niche before the pivot.
2. Discovery (10-30s): Uncovering the "invisible" messaging pivot of a market titan.
3. Breakthrough (30-50s): Showcasing the real-world success of our project (e.g. LeadIdeal) using this insight.
4. CTA (50-60s): Invite to get their own forensic scan.

Return ONLY valid JSON with this structure:
{{
  "video_prompt": "Cinematic visual description for the entire video (used as a global style)",
  "vibe": "technological | futuristic | documentary",
  "recommended_visual_preset": "b2b | cinematic | modern",
  "script_stages": [
    {{"time": "0-10s", "text": "Voiceover line", "visual_prompt": "Specific visual for this scene"}},
    {{"time": "10-50s", "text": "Voiceover lines", "visual_prompt": "Visuals"}},
    {{"time": "50-60s", "text": "CTA line", "visual_prompt": "Visual"}}
  ],
  "full_voiceover": "The entire script text for TTS generation"
}}

No markdown, no explanations. Just the JSON.
"""
        try:
            text = self._generate_text(prompt)
            if not text:
                return {}
            text = text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.startswith("```"):
                text = text.replace("```", "", 1)
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            logger.error("Failed to generate video script: %s", exc)
        return {}

    def generate_outreach_hooks(
        self,
        target_name: str,
        evidence_quotes: List[Dict],
        wedge: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Generate personalized outreach hooks for a prospect based on their website evidence.

        Returns a list of hook objects with suggested openers, rationale, and red flags.
        """
        if not self.enabled:
            return []

        # Build evidence context
        evidence_text = ""
        for quote in evidence_quotes[:5]:  # Limit to top 5 quotes
            section = quote.get("section", "page")
            evidence_text += f"- {section}: \"{quote.get('quote', '')}\"\n"

        # Build wedge constraints for personalization
        wedge_context = ""
        if wedge:
            if wedge.get("geo_origin") or wedge.get("geo_target"):
                wedge_context += f" The prospect is based in {wedge.get('geo_origin', 'unknown')} and targets {wedge.get('geo_target', 'unknown')} markets."
            if wedge.get("price_tier"):
                tier_map = {
                    "low_self_serve": "budget-conscious self-serve buyers",
                    "mid_market": "mid-market companies",
                    "enterprise": "enterprise organizations",
                    "agency_retainer": "agencies and consultants"
                }
                wedge_context += f" They serve {tier_map.get(wedge['price_tier'], wedge['price_tier'])}."
            if wedge.get("business_model"):
                model_map = {
                    "self_serve": "self-serve SaaS",
                    "sales_led": "sales-led enterprise",
                    "agency_service": "agency services",
                    "managed_service": "managed services"
                }
                wedge_context += f" Their business model is {model_map.get(wedge['business_model'], wedge['business_model'])}."

        prompt = f"""
Analyze this prospect's website evidence and generate 3 personalized outreach hooks for B2B sales prospecting.

Prospect: {target_name}
Evidence from their website:
{evidence_text.strip()}
{wedge_context}

Generate 3 different personalized hook approaches. Each hook should:
1. Reference something specific from their website (not generic)
2. Show you've done research (mention recent changes if evident)
3. Create curiosity or provide value
4. Be concise (under 100 words)

Return ONLY valid JSON array with this structure:
[
  {{
    "hook_type": "curiosity_gap|value_prop|recent_change",
    "subject_line": "Email subject line",
    "opener": "First 2-3 sentences of email",
    "rationale": "Why this hook works based on their evidence",
    "red_flags": ["any concerns from their site", "like gated content", "enterprise focus"]
  }}
]

No markdown, no explanations. Just the JSON array.
"""

        try:
            text = self._generate_text(prompt)
            if not text:
                return []
            text = text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.startswith("```"):
                text = text.replace("```", "", 1)
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
            if isinstance(parsed, list):
                # Lint the output
                return self.lint_output(parsed, evidence_quotes)
        except Exception as exc:
            logger.error("Failed to generate outreach hooks: %s", exc)
        return []
