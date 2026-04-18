"""
Report generator.
Renders competitive intelligence reports as sellable HTML files.
"""

import os
import re
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime

from markupsafe import Markup, escape
from jinja2 import Environment, FileSystemLoader

from .startup_intel import build_leadideal_handoff, render_internal_brief

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def _md_to_html(text, redact_rules=None):
    """Convert basic markdown (bold, bullets, paragraphs) to HTML with optional redaction.

    Handles the subset of markdown that Gemini typically returns in
    strategic summaries: **bold**, bullet lists, and paragraph breaks.
    """
    if not text:
        return Markup("")
    
    # Apply redactions if present
    processed_text = str(text)
    if redact_rules:
        for pattern, replacement in redact_rules.items():
            processed_text = re.sub(pattern, replacement, processed_text, flags=re.IGNORECASE)

    text_escaped = str(escape(processed_text))
    # Bold: **text** -> <strong>text</strong>
    text_bold = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text_escaped)
    # Split into paragraphs on double newlines
    paragraphs = re.split(r'\n{2,}', text_bold.strip())
    rendered = []
    for para in paragraphs:
        lines = para.strip().split('\n')
        # Separate bullet lines from non-bullet lines
        pre_lines = []
        bullet_lines = []
        collecting_bullets = False
        for line in lines:
            stripped = line.strip()
            if re.match(r'^[\-\*]\s', stripped):
                collecting_bullets = True
                bullet_lines.append(re.sub(r'^[\-\*]\s+', '', stripped))
            else:
                if collecting_bullets:
                    # Flush accumulated bullets before this non-bullet line
                    rendered.append('<ul>' + ''.join(f'<li>{item}</li>' for item in bullet_lines) + '</ul>')
                    bullet_lines = []
                    collecting_bullets = False
                pre_lines.append(stripped)
        # Flush any remaining content
        if pre_lines:
            rendered.append(f'<p>{" ".join(pre_lines)}</p>')
        if bullet_lines:
            rendered.append('<ul>' + ''.join(f'<li>{item}</li>' for item in bullet_lines) + '</ul>')
    return Markup('\n'.join(rendered))


class ReportGenerator:
    """Generates HTML reports from analysis data."""

    def __init__(self, templates_dir: str = TEMPLATES_DIR):
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=True,
        )
        self.env.filters['md'] = _md_to_html

    def generate(
        self,
        niche_name: str,
        competitors: List[Dict],
        output_path: str,
        niche_narrative: str = "",
        locked_competitors: Optional[List[str]] = None,
        key_findings: Optional[List[str]] = None,
        roi_analysis: Optional[Dict] = None,
        is_public: bool = False,
        redactions: Optional[Dict[str, str]] = None,
        agent_tasks: Optional[List[Dict]] = None,
        breakthrough_story: Optional[str] = None,
    ) -> str:
        """
        Generate an HTML competitive intelligence report.

        Args:
            niche_name: Display name of the niche (e.g. "SaaS Project Management")
            competitors: List of competitor analysis dicts
            output_path: Where to write the HTML file
            niche_narrative: AI-generated strategic summary
            key_findings: List of key finding strings
            roi_analysis: Market impact analysis dict
            is_public: If True, renders as a public case study (redacted, no upgrade CTAs)
            redactions: Dict mapping regex patterns to replacement strings (e.g. {"@.+": "[REDACTED]"})
            agent_tasks: List of machine-readable tasks for AI agents
            breakthrough_story: Narrative describing a real-world success story powered by this report
        """
        template = self.env.get_template("report.html")

        # Update environment filters for this run if redactions present
        if redactions:
            self.env.filters['md'] = lambda t: _md_to_html(t, redact_rules=redactions)
        else:
            self.env.filters['md'] = _md_to_html

        # Build summary stats
        total_snapshots = sum(c.get("snapshot_count", 0) for c in competitors)
        total_changes = sum(len(c.get("changes", [])) for c in competitors)

        # Collect all tech stacks across all competitors and snapshots
        all_tech = set()
        for comp in competitors:
            for analysis in comp.get("analyses", []):
                all_tech.update(analysis.get("tech_stack", []))

        # Collect all pricing signals
        all_prices = {}
        for comp in competitors:
            comp_prices = set()
            for analysis in comp.get("analyses", []):
                comp_prices.update(analysis.get("prices_found", []))
            if comp_prices:
                all_prices[comp["name"]] = sorted(comp_prices)

        html = template.render(
            niche_name=niche_name,
            niche_narrative=niche_narrative,
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            competitors=competitors,
            total_snapshots=total_snapshots,
            total_changes=total_changes,
            all_tech=sorted(all_tech),
            all_prices=all_prices,
            competitor_count=len(competitors) + (len(locked_competitors) if locked_competitors else 0),
            locked_competitors=locked_competitors if not is_public else [],
            key_findings=key_findings or [],
            roi_analysis=roi_analysis or {},
            is_public=is_public,
            agent_tasks=agent_tasks or [],
            agent_json=json.dumps(agent_tasks or [], indent=2),
            breakthrough_story=breakthrough_story,
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info("Report written to %s (is_public=%s)", output_path, is_public)
        return os.path.abspath(output_path)

    def generate_json(self, niche_name: str, competitors: List[Dict], output_path: str) -> str:
        """Also dump raw JSON data for programmatic use or API resale."""
        data = {
            "niche": niche_name,
            "generated_at": datetime.utcnow().isoformat(),
            "competitor_count": len(competitors),
            "competitors": competitors,
        }
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("JSON data written to %s", output_path)
        return os.path.abspath(output_path)

    def generate_manifest(self, manifest: Dict, output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=str)
        logger.info("Sprint manifest written to %s", output_path)
        return os.path.abspath(output_path)

    def generate_leadideal_handoff(self, manifest: Dict, output_path: str) -> str:
        handoff = build_leadideal_handoff(manifest)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(handoff, f, indent=2, default=str)
        logger.info("LeadIdeal handoff written to %s", output_path)
        return os.path.abspath(output_path)

    def generate_json_blob(self, payload: Dict, output_path: str, label: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info("%s written to %s", label, output_path)
        return os.path.abspath(output_path)

    def generate_internal_brief(
        self,
        manifest: Dict,
        competitors: List[Dict],
        output_path: str,
        key_findings: Optional[List[str]] = None,
        roi_analysis: Optional[Dict] = None,
    ) -> str:
        content = render_internal_brief(
            manifest,
            competitors,
            key_findings=key_findings,
            roi_analysis=roi_analysis,
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Internal brief written to %s", output_path)
        return os.path.abspath(output_path)
