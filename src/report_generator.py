"""
Report generator.
Renders competitive intelligence reports as sellable HTML files.
"""

import os
import re
import json
import logging
import copy
from typing import List, Dict, Optional
from datetime import datetime

from markupsafe import Markup, escape
from jinja2 import Environment, FileSystemLoader

from .startup_intel import build_leadideal_handoff, render_internal_brief
from .storage import Storage

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
    def __init__(self, templates_dir: str = TEMPLATES_DIR):
        self.storage = Storage()
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=True,
        )
        self.env.filters['md'] = _md_to_html
        self.video_engine_url = os.getenv("VIDEO_ENGINE_URL", "")

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
        video_script: Optional[Dict] = None,
        is_paid: bool = False,
        is_share_preview: bool = False,
    ) -> str:
        """
        Generate an HTML competitive intelligence report.

        is_share_preview: render with share-mode light redaction and a banner.
        """
        is_paid = bool(is_paid)
        if is_share_preview and not is_paid:
            redaction_mode = 'share'
        elif is_paid:
            redaction_mode = 'full'
        else:
            redaction_mode = 'free'

        template = self.env.get_template("report.html")

        # Update environment filters for this run if redactions present
        if redactions:
            self.env.filters['md'] = lambda t: _md_to_html(t, redact_rules=redactions)
        else:
            self.env.filters['md'] = _md_to_html

        # Build summary stats
        total_snapshots = sum(c.get("snapshot_count", 0) for c in competitors)
        total_changes = sum(len(c.get("changes", [])) for c in competitors)

        # Apply redaction
        if redaction_mode != 'full':
            competitors, roi_analysis, agent_tasks, breakthrough_story, video_script = self._apply_redaction(
                redaction_mode,
                list(competitors),
                roi_analysis,
                list(agent_tasks) if agent_tasks else [],
                breakthrough_story,
                video_script,
            )

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

        # Build target snapshot card (from competitors[0]) and a flat evidence list.
        target_snapshot = None
        evidence_quotes: List[Dict] = []
        if competitors:
            target = competitors[0]
            t_current = target.get("current_analysis") or {}
            target_snapshot = {
                "name": target.get("name", ""),
                "url": target.get("url", ""),
                "h1": (t_current.get("h1") or "").strip(),
                "meta_description": (t_current.get("meta_description") or "").strip(),
                "ctas": (t_current.get("cta_buttons") or [])[:5],
                "tech_stack": (t_current.get("tech_stack") or [])[:8],
                "pricing_signal": str(t_current.get("pricing", "") or ""),
                "title": (t_current.get("title") or "").strip(),
            }
            for comp in competitors[1:]:
                for q in (comp.get("evidence_quotes") or [])[:4]:
                    evidence_quotes.append({
                        "competitor": comp.get("name", ""),
                        "quote": q.get("quote", ""),
                        "url": q.get("url", ""),
                        "section": q.get("section", ""),
                    })

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
            video_script=video_script or {},
            video_script_json=json.dumps(video_script or {}, indent=2),
            is_paid=is_paid,
            is_share_preview=is_share_preview,
            video_engine_url=self.video_engine_url or os.getenv("VIDEO_ENGINE_URL", ""),
            target_snapshot=target_snapshot,
            evidence_quotes=evidence_quotes,
        )

        # Save via Storage abstraction
        return self.storage.save(html, output_path)

    def generate_json(self, niche_name: str, competitors: List[Dict], output_path: str, niche_narrative: str = "") -> str:
        """Also dump raw JSON data for programmatic use or API resale."""
        data = {
            "niche": niche_name,
            "niche_narrative": niche_narrative,
            "generated_at": datetime.utcnow().isoformat(),
            "competitor_count": len(competitors),
            "competitors": competitors,
        }
        return self.storage.save(json.dumps(data, indent=2, default=str), output_path, content_type='application/json')

    def generate_agent_report(
        self,
        output_path: str,
        *,
        target_url: str,
        niche_name: str,
        competitors: List[Dict],
        is_paid: bool,
        redaction_mode: str = "",
        niche_narrative: str = "",
        key_findings: Optional[List[str]] = None,
        roi_analysis: Optional[Dict] = None,
        agent_tasks: Optional[List[Dict]] = None,
        video_script: Optional[Dict] = None,
        breakthrough_story: Optional[str] = None,
        sprint_manifest: Optional[Dict] = None,
        leadideal_preview: Optional[Dict] = None,
        approval_state: Optional[Dict] = None,
        related_links: Optional[Dict[str, str]] = None,
        competitor_source: str = "",
    ) -> str:
        """Emit a stable, agent-friendly JSON contract.

        redaction_mode: 'full' | 'share' | 'free'. Defaults to 'full' when
        is_paid=True, 'free' otherwise.
        """
        is_paid = bool(is_paid)
        if not redaction_mode:
            redaction_mode = 'full' if is_paid else 'free'

        rendered_competitors, rendered_roi, rendered_tasks, rendered_story, rendered_video = \
            self._apply_redaction(
                redaction_mode,
                list(competitors),
                roi_analysis,
                list(agent_tasks) if agent_tasks else [],
                breakthrough_story,
                video_script,
            )

        # Flatten competitors to the minimum agents need without losing detail.
        flat_competitors = []
        for c in rendered_competitors:
            tech = set()
            prices = set()
            for analysis in c.get("analyses", []) or []:
                for t in analysis.get("tech_stack", []) or []:
                    tech.add(t)
                for p in analysis.get("prices_found", []) or []:
                    prices.add(p)
            flat_competitors.append({
                "name": c.get("name"),
                "url": c.get("url"),
                "snapshot_count": c.get("snapshot_count", 0),
                "tech_stack": sorted(tech),
                "prices_found": sorted(prices),
                "changes": c.get("changes", []) or [],
                "analyses_count": len(c.get("analyses", []) or []),
            })

        manifest_meta = {}
        if sprint_manifest:
            manifest_meta = {
                "schema_version": sprint_manifest.get("schema_version"),
                "startup_name": sprint_manifest.get("startup_name"),
                "preset_id": sprint_manifest.get("preset_id"),
                "selection_mode": sprint_manifest.get("selection_mode"),
            }

        payload = {
            "schema_version": "bizspy.report.agent.v1",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "target_url": target_url,
            "niche": niche_name,
            "is_paid": is_paid,
            "competitor_source": competitor_source,
            "summary": {
                "competitor_count": len(flat_competitors),
                "total_snapshots": sum(c["snapshot_count"] for c in flat_competitors),
                "total_changes": sum(len(c["changes"]) for c in flat_competitors),
            },
            "narrative": niche_narrative or "",
            "key_findings": list(key_findings or []),
            "roi_analysis": rendered_roi or {},
            "competitors": flat_competitors,
            "agent_tasks": rendered_tasks or [],
            "video_script": rendered_video or {},
            "breakthrough_story": rendered_story,
            "leadideal_preview": {
                "status": (leadideal_preview or {}).get("status"),
                "preview_url": (leadideal_preview or {}).get("preview_url"),
            },
            "approval": {
                "status": (approval_state or {}).get("status"),
                "dispatch_blocked": (approval_state or {}).get("dispatch_blocked"),
            },
            "manifest": manifest_meta,
            "links": dict(related_links or {}),
            "consumer_hints": {
                "primary_html": (related_links or {}).get("html", ""),
                "raw_data": (related_links or {}).get("raw_data", ""),
                "intended_use": "Read this JSON to understand competitor signals, redacted when is_paid=false. Fetch links.html for the human-readable report.",
            },
        }
        return self.storage.save(
            json.dumps(payload, indent=2, default=str),
            output_path,
            content_type='application/json',
        )

    def generate_manifest(self, manifest: Dict, output_path: str) -> str:
        return self.storage.save(json.dumps(manifest, indent=2, default=str), output_path, content_type='application/json')

    def generate_leadideal_handoff(self, manifest: Dict, output_path: str) -> str:
        handoff = build_leadideal_handoff(manifest)
        return self.storage.save(json.dumps(handoff, indent=2, default=str), output_path, content_type='application/json')

    def generate_json_blob(self, payload: Dict, output_path: str, label: str) -> str:
        return self.storage.save(json.dumps(payload, indent=2, default=str), output_path, content_type='application/json')

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
        return self.storage.save(content, output_path, content_type='text/markdown')

    def _redact_competitors(self, competitors: List[Dict]) -> List[Dict]:
        """Strip sensitive historical data from competitors."""
        redacted = []
        for comp in competitors:
            c = copy.deepcopy(comp)
            # Strip historical changes detail
            if "changes" in c:
                redacted_changes = []
                for change in c["changes"]:
                    ch = copy.deepcopy(change)
                    redacted_diffs = {}
                    for k, v in ch.get("diffs", {}).items():
                        if k == "word_count":
                            redacted_diffs[k] = {"from": 0, "to": 0, "delta": 0}
                        elif k in ["tech_stack", "cta_buttons", "pricing"]:
                            redacted_diffs[k] = {"added": ["[LOCKED]"], "removed": ["[LOCKED]"]}
                        else:
                            redacted_diffs[k] = {"from": "[LOCKED]", "to": "[LOCKED]"}
                    ch["diffs"] = redacted_diffs
                    redacted_changes.append(ch)
                c["changes"] = redacted_changes
            # Limit tech stack visibility
            if "analyses" in c:
                for analysis in c["analyses"]:
                    if "tech_stack" in analysis:
                        analysis["tech_stack"] = (analysis["tech_stack"] or [])[:5] + ["... [LOCKED]"]
            redacted.append(c)
        return redacted

    def _redact_roi(self, roi: Dict) -> Dict:
        """Strip specific details from ROI analysis."""
        r = dict(roi)
        for key in ["winning_strategies", "failing_signals"]:
            if key in r:
                r[key] = [
                    {"signal": item.get("signal"), "detail": "[PREMIUM REDACTION] Upgrade to unlock tactical details."}
                    for item in r[key]
                ]
        return r

    def _redact_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """Strip machine-readable prompts from agent tasks."""
        return [
            {
                "category": t.get("category"),
                "priority": t.get("priority"),
                "task": t.get("task"),
                "rationale": t.get("rationale"),
                "agent_prompt_snippet": "[LOCKED] Purchase Forensic Unlock to access AI Agent Playbooks."
            }
            for t in tasks
        ]

    # ------------------------------------------------------------------
    # Share-mode helpers: lighter redaction than free, heavier than paid.
    # Keeps competitor identities + narrative, hides specifics + prompts.
    # ------------------------------------------------------------------

    def _share_competitors(self, competitors: List[Dict]) -> List[Dict]:
        """Light redaction: keep names/URLs, hide price specifics, show top-3 tech."""
        shared = []
        for comp in competitors:
            c = copy.deepcopy(comp)
            if "analyses" in c:
                for analysis in c["analyses"]:
                    ts = analysis.get("tech_stack") or []
                    analysis["tech_stack"] = ts[:3] + (["... and more"] if len(ts) > 3 else [])
                    analysis["prices_found"] = []  # hide exact pricing
            # Keep changes dates but strip diff text
            if "changes" in c:
                for change in c["changes"]:
                    for k in list(change.get("diffs", {}).keys()):
                        d = change["diffs"][k]
                        if isinstance(d, dict) and "from" in d and "to" in d:
                            change["diffs"][k] = {
                                "from": "[preview]",
                                "to": "[preview]",
                                "delta": d.get("delta", 0),
                            }
            shared.append(c)
        return shared

    def _share_roi(self, roi: Dict) -> Dict:
        """Keep signal names, replace detail with a short teaser."""
        r = dict(roi)
        for key in ["winning_strategies", "failing_signals"]:
            if key in r:
                r[key] = [
                    {
                        "signal": item.get("signal"),
                        "detail": "Full tactical detail available in your unlocked report.",
                    }
                    for item in r[key]
                ]
        return r

    def _share_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """Keep task description and rationale; hide machine-readable prompt snippets."""
        return [
            {
                "category": t.get("category"),
                "priority": t.get("priority"),
                "task": t.get("task"),
                "rationale": t.get("rationale"),
                "agent_prompt_snippet": "[Available in your private unlocked report]",
            }
            for t in tasks
        ]

    def _share_story(self, story: Optional[str]) -> Optional[str]:
        """Show first two sentences, then a teaser."""
        if not story:
            return None
        sentences = story.replace("\n", " ").split(". ")
        preview = ". ".join(sentences[:2]).strip()
        if not preview.endswith("."):
            preview += "."
        return preview + " (Continued in your unlocked full report.)"

    def _apply_redaction(self, mode: str, competitors, roi_analysis, agent_tasks, breakthrough_story, video_script):
        """Apply the requested redaction mode and return tuple of processed values.

        mode: 'full' (paid), 'share' (light), 'free' (heavy)
        """
        if mode == 'full':
            return competitors, roi_analysis, agent_tasks, breakthrough_story, video_script
        if mode == 'share':
            return (
                self._share_competitors(competitors),
                self._share_roi(roi_analysis) if roi_analysis else {},
                self._share_tasks(agent_tasks) if agent_tasks else [],
                self._share_story(breakthrough_story),
                {"full_voiceover": "Forensic video available in your unlocked report."} if video_script else {},
            )
        # default: 'free' heavy redaction
        return (
            self._redact_competitors(competitors),
            self._redact_roi(roi_analysis) if roi_analysis else {},
            self._redact_tasks(agent_tasks) if agent_tasks else [],
            "[PREMIUM CONTENT LOCKED] Upgrade to unlock the full breakthrough narrative." if breakthrough_story else None,
            {"full_voiceover": "Forensic Studio analysis locked. Upgrade to generate your cinematic strategy trailer."} if video_script else {},
        )

    # ------------------------------------------------------------------
    # Share-mode helpers: lighter redaction than free, heavier than paid.
    # Keeps competitor identities + narrative, hides specifics + prompts.
    # ------------------------------------------------------------------

    def _share_competitors(self, competitors: List[Dict]) -> List[Dict]:
        """Light redaction: keep names/URLs, hide price specifics, show top-3 tech."""
        shared = []
        for comp in competitors:
            c = copy.deepcopy(comp)
            if "analyses" in c:
                for analysis in c["analyses"]:
                    ts = analysis.get("tech_stack") or []
                    analysis["tech_stack"] = ts[:3] + (["... and more"] if len(ts) > 3 else [])
                    analysis["prices_found"] = []  # hide exact pricing
            # Keep changes dates but strip diff text
            if "changes" in c:
                for change in c["changes"]:
                    for k in list(change.get("diffs", {}).keys()):
                        d = change["diffs"][k]
                        if isinstance(d, dict) and "from" in d and "to" in d:
                            change["diffs"][k] = {
                                "from": "[preview]",
                                "to": "[preview]",
                                "delta": d.get("delta", 0),
                            }
            shared.append(c)
        return shared

    def _share_roi(self, roi: Dict) -> Dict:
        """Keep signal names, replace detail with a short teaser."""
        r = dict(roi)
        for key in ["winning_strategies", "failing_signals"]:
            if key in r:
                r[key] = [
                    {
                        "signal": item.get("signal"),
                        "detail": "Full tactical detail available in your unlocked report.",
                    }
                    for item in r[key]
                ]
        return r

    def _share_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """Keep task description and rationale; hide machine-readable prompt snippets."""
        return [
            {
                "category": t.get("category"),
                "priority": t.get("priority"),
                "task": t.get("task"),
                "rationale": t.get("rationale"),
                "agent_prompt_snippet": "[Available in your private unlocked report]",
            }
            for t in tasks
        ]

    def _share_story(self, story: Optional[str]) -> Optional[str]:
        """Show first two sentences, then a teaser."""
        if not story:
            return None
        sentences = story.replace("\n", " ").split(". ")
        preview = ". ".join(sentences[:2]).strip()
        if not preview.endswith("."):
            preview += "."
        return preview + " (Continued in your unlocked full report.)"

    def _apply_redaction(self, mode: str, competitors, roi_analysis, agent_tasks, breakthrough_story, video_script):
        """Apply the requested redaction mode and return tuple of processed values.

        mode: 'full' (paid), 'share' (light), 'free' (heavy)
        """
        if mode == 'full':
            return competitors, roi_analysis, agent_tasks, breakthrough_story, video_script
        if mode == 'share':
            return (
                self._share_competitors(competitors),
                self._share_roi(roi_analysis) if roi_analysis else {},
                self._share_tasks(agent_tasks) if agent_tasks else [],
                self._share_story(breakthrough_story),
                {"full_voiceover": "Forensic video available in your unlocked report."} if video_script else {},
            )
        # default: 'free' heavy redaction
        return (
            self._redact_competitors(competitors),
            self._redact_roi(roi_analysis) if roi_analysis else {},
            self._redact_tasks(agent_tasks) if agent_tasks else [],
            "[PREMIUM CONTENT LOCKED] Upgrade to unlock the full breakthrough narrative." if breakthrough_story else None,
            {"full_voiceover": "Forensic Studio analysis locked. Upgrade to generate your cinematic strategy trailer."} if video_script else {},
        )
