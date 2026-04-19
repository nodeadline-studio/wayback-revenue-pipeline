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
You are a CMO and Competitive Intelligence Expert. Your task is to analyze "diffs" (changes) in a competitor's website over time and explain the STRATEGIC NARRATIVE.

Focus on:
1. Pricing Shifts: Are they moving upmarket (enterprise) or downmarket (SMB)?
2. Messaging Pivots: Are they shifting from "Efficiency" to "Revenue"? From "Simple" to "Powerful"?
3. Feature Launches: What does the addition of a specific tool or section imply?
4. Growth Signals: Evidence of scaling (new CTAs, trust badges, complex tech stack).
5. Founder De-risking: Identify the EXACT moment they pivoted from a "No-name" startup to a "Category Leader"—uncover the messaging change that made it happen.

Tone: Professional, insightful, and aggressive (looking for gaps and revenue opportunities).
"""


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

    def get_fallback_competitors(self, target_domain: str, limit: int = 5) -> List[str]:
        category = self.infer_category(target_domain)
        return INDUSTRY_COMPETITOR_MAP.get(category, INDUSTRY_COMPETITOR_MAP["generic_saas"])[:limit]

    def _generate_text(self, prompt: str) -> str:
        if not self.enabled:
            return ""

        if self.mock_mode:
            # Provide high-quality mock data for testing
            if "Executive Strategic Summary" in prompt:
                return "The market landscape is shifting from complex legacy enterprise suites to lean, high-velocity signal engines. Dominant titans are slowed by feature bloat and enterprise oversight, leaving a massive gap for high-speed forensic intelligence. The target startup should counter-position as the agile alternative that prioritizes revenue signals over generic metrics."
            if "Strategic Comparison" in prompt or "Strategic Comparison" in prompt:
                return "This competitor is currently pivoting toward enterprise-level compliance, which has slowed their core innovation cycle. Their messaging is becoming increasingly generic, focusing on 'efficiency' while ignoring the high-intent forensic signals that modern growth teams require. A leaner competitor can disrupt them by owning the speed-to-insight narrative."
            if "Actionable Agent Tasks" in prompt:
                return json.dumps([
                    {
                        "category": "marketing",
                        "priority": "high",
                        "task": "Differentiate via Forensic Speed",
                        "rationale": "Competitors are slow. Use this as the hook.",
                        "agent_prompt_snippet": "Draft an outreach sequence focusing on 60s insight speed."
                    }
                ])
            return "Strategic insight generated via mock engine. The market signals indicate high-intent breakout potential."

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

    def generate_niche_summary(self, niche_name: str, competitors: List[Dict]) -> str:
        """Generate an executive summary for the entire niche."""
        if not self.enabled:
            return ""

        # Summarize key events across all competitors
        context = []
        for comp in competitors:
            latest = comp["analyses"][-1] if comp.get("analyses") else {}
            comp_summary = {
                "name": comp["name"],
                "total_changes": len(comp.get("changes", [])),
                "latest_h1": latest.get("h1", "N/A"),
                "latest_meta": latest.get("meta_description", "N/A"),
                "tech_count": len(latest.get("tech_stack", [])),
                "key_tech": latest.get("tech_stack", [])[:8],
                "ctas": latest.get("cta_buttons", [])[:5],
            }
            context.append(comp_summary)

        prompt = f"""
Analyze the '{niche_name}' market landscape.
Competitor Data (Current State & History): {json.dumps(context, indent=2)}

Write an Executive Strategic Summary (3-4 paragraphs) emphasizing COMPARATIVE POSITIONING.
Structure:
1. Market Evolution & Bloat: How has the industry shifted? Identify where competitors have become "bloated" with features or generic messaging.
2. Competitive Gaps: Specifically compare the target product's lean potential against the dominant titans. Where are they vulnerable or slow?
3. Strategic Counter-Positioning: Based on the gaps, how should the target startup message itself to clearly differentiate? (e.g. "While X focuses on enterprise scale, the target should own the speed-to-insight angle").

Be extremely specific. Cite competitor names and their specific data points. Avoid generic business consulting jargon. Return ONLY the text, no markdown.
"""
        return self._generate_text(prompt)

    def generate_competitor_insight(self, competitor_name: str, changes: List[Dict], current_analysis: Optional[Dict] = None) -> str:
        """Generate a strategic insight for a competitor's evolution or current posture."""
        if not self.enabled:
            return ""

        if not changes:
            if not current_analysis:
                return "No significant changes or live data to analyze."
            
            # Fallback to Current State Analysis
            prompt = f"""
Analyze the current strategic posture of '{competitor_name}'.
Live Site Signals: {json.dumps(current_analysis, indent=2)}

Write a concise Strategic Comparison (1-2 paragraphs).
Focus on:
1. Current Positioning: What is their dominant market promise right now?
2. Vulnerability: Based on their current tech stack and messaging, where are they vulnerable to a leaner, higher-utility competitor?
3. The Gap: How should the target product message AGAINST them today?

Return only the text, no markdown.
"""
            return self._generate_text(prompt)

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
Analyze the evolution and vulnerabilities of '{competitor_name}'.
Historical Signal Changes: {json.dumps(clean_changes, indent=2)}

Write a concise Strategic Insight (1-2 paragraphs) for the founder.

Focus on:
1. The Pivot: What was their most significant strategic messaging move? Identify the moment they shifted from X to Y.
2. The Gap: Based on this evolution, what have they SACRIFICED or neglected? (e.g. have they become too complex, too enterprise, abandoned the 'easy for pros' angle?)
3. The Counter-Move: How should the target product position AGAINST them right now? Recommend a specific messaging angle that exploits their current complexity or focus.

Be extremely specific. Cite their actual H1s and pricing shifts. Do not use markdown.
"""
        return self._generate_text(prompt)

    def find_competitors(self, target_domain: str) -> List[str]:
        """Auto-discover competitors for a given domain using the LLM or domain-aware fallbacks."""
        fallback_competitors = self.get_fallback_competitors(target_domain)

        if not self.enabled:
            self.discovery_source = "fallback"
            logger.warning("Narrator disabled. Using domain-aware fallback competitors for %s.", target_domain)
            return fallback_competitors

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

Return ONLY a valid JSON array of 3 to 5 key findings as short strings (each under 120 characters).
Each finding should be a specific, data-backed observation, not generic advice.
Example format: ["All competitors shifted from feature-focused to conversion-focused headlines", "Tech stack consolidation: 3 of 4 dropped live chat tools in favor of demo booking"]
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
                return [str(f) for f in parsed[:5] if f]
        except Exception as exc:
            logger.error("Failed to generate key findings: %s", exc)
        return []

    def generate_agent_tasks(self, niche_name: str, competitors: List[Dict]) -> List[Dict]:
        """Generate a machine-readable list of actionable tasks for an AI agent."""
        if not self.enabled:
            return []

        context = []
        for comp in competitors:
            comp_context = {
                "name": comp["name"],
                "key_shifts": []
            }
            # Latest state
            analyses = comp.get("analyses", [])
            if analyses:
                latest = analyses[-1] if isinstance(analyses[-1], dict) else analyses[-1].to_dict()
                comp_context["current_focus"] = latest.get("h1", "")
            
            # Key historical changes
            for c in comp.get("changes", [])[:5]:
                diffs = c.get("diffs", {})
                if "h1" in diffs: comp_context["key_shifts"].append(f"Headline pivot: {diffs['h1']}")
                if "pricing" in diffs: comp_context["key_shifts"].append(f"Pricing pivot: {diffs['pricing']}")
                if "cta_buttons" in diffs: comp_context["key_shifts"].append(f"CTA change: {diffs['cta_buttons']}")
                if "tech_stack" in diffs: comp_context["key_shifts"].append(f"Tech stack change: {diffs['tech_stack']}")
            
            context.append(comp_context)

        prompt = f"""
You are an AI Agent Orchestrator specializing in "Strategic Pivot Forensics." Your goal is to generate a list of 5-8 actionable tasks that will help a founder replicate the successful messaging trajectories of market titans in the '{niche_name}' space.

Market Data: {json.dumps(context, indent=2)}

Focus on:
- High-intent messaging pivots (e.g., "Mirror Competitor X's shift to 'Outcome-led' pricing").
- Technical de-risking (e.g., "Implement the specific trust blocks Competitor Y added before their Series A").
- Growth signals (e.g., "Deploy the exact CTA sequence that worked for Competitor Z").

Each task must be highly specific and technically actionable. 
Example Task: "Update the HERO component to use a 'Revenue Intelligence' hook, mirroring Klue's successful 2021 pivot away from generic monitoring."

Return ONLY valid JSON array of objects with this structure:
[
  {{
    "category": "technical | marketing | positioning",
    "priority": "high | medium | low",
    "task": "Specific task instruction",
    "rationale": "Brief reason tied to a specific competitor's historical pivot",
    "agent_prompt_snippet": "A 1-sentence prompt the user can give to an AI agent to execute this specific task"
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
                return parsed[:10]
        except Exception as exc:
            logger.error("Failed to generate agent tasks: %s", exc)
        return []

    def generate_roi_analysis(self, niche_name: str, competitors: List[Dict], target_url: str = "") -> Dict:
        """Generate market impact analysis by interpreting competitor signals as growth/decline indicators."""
        if not self.enabled:
            return {}

        context = []
        for comp in competitors:
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

        prompt = f"""
You are a competitive intelligence analyst. Analyze the strategic signals from these competitors in the '{niche_name}' market.
Target being analyzed: {target_url or 'unknown'}

Competitor Data: {json.dumps(context, indent=2)}

Interpret the data as market signals using these proxy indicators:
- Tech stack expansion (added HubSpot, Stripe, analytics) = growth investment
- Tech stack contraction (dropped Intercom, removed tools) = cost-cutting or pivoting
- CTA evolution ("Start Free Trial" -> "Book a Demo") = moving upmarket
- CTA evolution ("Get Started Free" -> "See Pricing") = monetization pressure
- Pricing changes = market positioning shifts
- Content/headline shifts = strategic repositioning

Return ONLY valid JSON with this exact structure:
{{
  "winning_strategies": [
    {{"signal": "Short title", "detail": "1-2 sentence explanation with specific competitor names and data"}}
  ],
  "failing_signals": [
    {{"signal": "Short title", "detail": "1-2 sentence explanation"}}
  ],
  "market_trends": ["Trend statement 1", "Trend statement 2"],
  "recommendation_for_target": "2-3 sentence specific recommendation for the target based on gaps identified"
}}

Keep each array to 2-4 items max. Be specific, cite competitor names. No markdown wrapping.
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
