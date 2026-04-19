"""
Pipeline orchestrator.
Connects Wayback client -> page analyzer -> report generator into a single flow.
"""

import os
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from .live_site_analyzer import LiveSiteAnalyzer
from .wayback_client import WaybackClient
from .page_analyzer import PageAnalyzer, diff_analyses
from .report_generator import ReportGenerator
from .narrator import StrategicNarrator
from .leadideal_bridge import execute_leadideal_preview
from .startup_intel import build_approval_state, build_leadideal_handoff, build_sprint_manifest

logger = logging.getLogger(__name__)

# Load environment variables from .env if present
load_dotenv()


class Pipeline:
    """
    Full pipeline: for each niche, pull snapshots, analyze pages,
    diff changes, and generate a sellable report.
    """

    def __init__(
        self,
        max_snapshots_per_url: int = 8,
        enable_narrative: bool = True,
        analyze_live_target: bool = False,
        live_max_pages: int = 75,
    ):
        self.client = WaybackClient()
        self.analyzer = PageAnalyzer()
        self.reporter = ReportGenerator()
        self.narrator = StrategicNarrator()
        self.live_site_analyzer = LiveSiteAnalyzer(max_pages=live_max_pages)
        self.max_snapshots = max_snapshots_per_url
        self.enable_narrative = enable_narrative
        self.analyze_live_target = analyze_live_target

    def process_niche(
        self,
        niche_name: str,
        urls: List[Dict],
        from_date: str = "20180101",
        to_date: str = None,
        output_path: str = "report.html",
        status_callback: Optional[Callable[[Dict], None]] = None,
        is_public: bool = False,
        is_paid: bool = True,
    ) -> Dict:
        """
        Process an entire niche: pull data, analyze, and generate reports.
        """
        logger.info("Processing niche: %s (%d competitors)", niche_name, len(urls))
        competitors = []
        competitors_total = len(urls)

        self._notify(
            status_callback,
            "starting_analysis",
            f"Preparing archive analysis for {niche_name}.",
            competitors_total=competitors_total,
            competitors_completed=0,
            narrator_enabled=self.narrator.enabled and self.enable_narrative,
            current_action="planning",
            max_snapshots_per_url=self.max_snapshots,
        )

        for index, entry in enumerate(urls, start=1):
            comp_name = entry["name"]
            comp_url = entry["url"]
            
            # Allow per-competitor date overrides for historical parallel analysis
            comp_from = entry.get("from_date") or from_date
            comp_to = entry.get("to_date") or to_date
            
            logger.info("  Analyzing: %s (%s) | Dates: %s to %s", comp_name, comp_url, comp_from, comp_to)

            comp_data = self._process_competitor(
                comp_name,
                comp_url,
                comp_from,
                comp_to,
                is_target=index == 1,
                status_callback=status_callback,
                competitor_index=index,
                competitors_total=competitors_total,
                competitors_completed=index - 1,
            )

            self._notify(
                status_callback,
                f"analyzing_{index}",
                f"Completed archive analysis for {comp_name}.",
                current_competitor=comp_name,
                current_competitor_index=index,
                competitors_total=competitors_total,
                competitors_completed=index,
                snapshots_total=comp_data.get("selected_snapshot_count", 0),
                snapshots_completed=comp_data.get("analyzed_snapshot_count", 0),
                narrator_enabled=self.narrator.enabled and self.enable_narrative,
                current_action="analysis_complete",
            )

            # Generate AI insight for this competitor
            if self.narrator.enabled and self.enable_narrative:
                logger.info("    Generating AI strategic insight...")
                self._notify(
                    status_callback,
                    f"narrating_{index}",
                    f"Generating competitive insight for {comp_name}.",
                    current_competitor=comp_name,
                    current_competitor_index=index,
                    competitors_total=competitors_total,
                    competitors_completed=index,
                    narrator_enabled=True,
                    current_action="generating_insight",
                )
                comp_data["ai_insight"] = self.narrator.generate_competitor_insight(
                    comp_name, 
                    comp_data.get("changes", []),
                    current_analysis=comp_data.get("current_analysis") or comp_data.get("live_site_summary")
                )

            competitors.append(comp_data)

        # Generate niche-wide AI summary
        niche_narrative = ""
        if self.narrator.enabled and self.enable_narrative:
            logger.info("Generating niche-wide strategic summary...")
            self._notify(
                status_callback,
                "summarizing",
                f"Synthesizing market summary for {niche_name}.",
                competitors_total=competitors_total,
                competitors_completed=competitors_total,
                narrator_enabled=True,
                current_action="summarizing_market",
            )
            niche_narrative = self.narrator.generate_niche_summary(niche_name, competitors)

        # Generate key findings
        key_findings = []
        if self.narrator.enabled and self.enable_narrative:
            logger.info("Generating key findings...")
            key_findings = self.narrator.generate_key_findings(niche_name, competitors)

        # Generate ROI / market impact analysis
        roi_analysis = {}
        if self.narrator.enabled and self.enable_narrative:
            logger.info("Generating market impact analysis...")
            target_url = urls[0]["url"] if urls else ""
            roi_analysis = self.narrator.generate_roi_analysis(niche_name, competitors, target_url)

        # Generate agent tasks
        agent_tasks = []
        if self.narrator.enabled and self.enable_narrative:
            logger.info("Generating agent handoff tasks...")
            self._notify(
                status_callback,
                "agent_handoff",
                f"Generating machine-readable agent tasks for {niche_name}.",
                competitors_total=competitors_total,
                competitors_completed=competitors_total,
                current_action="generating_agent_tasks",
            )
            agent_tasks = self.narrator.generate_agent_tasks(niche_name, competitors)

        # Generate video script
        video_script = {}
        if self.narrator.enabled and self.enable_narrative:
            logger.info("Generating video generation script...")
            # We use the breakthrough story if available, otherwise generic
            # Note: breakthrough_story is loaded below if publishing is enabled, 
            # so we check if stories exist here too for the video
            story_for_video = None
            story_path = os.path.join("stories", f"{self._slugify(niche_name)}_breakout.md")
            if os.path.exists(story_path):
                with open(story_path, "r") as f:
                    story_for_video = f.read()
            video_script = self.narrator.generate_video_script(niche_name, competitors, breakthrough_story=story_for_video)

        # Generate reports
        total_snapshots = sum(c.get("snapshot_count", 0) for c in competitors)
        total_changes = sum(len(c.get("changes", [])) for c in competitors)

        safe_name = self._slugify(niche_name)
        # Use relative paths for the Storage abstraction (target_dir/filename)
        html_rel = f"{safe_name}/report.html"
        json_rel = f"{safe_name}/data.json"
        manifest_rel = f"{safe_name}/manifest.json"
        brief_rel = f"{safe_name}/internal-brief.md"
        leadideal_handoff_rel = f"{safe_name}/leadideal-handoff.json"
        leadideal_preview_rel = f"{safe_name}/leadideal-preview.json"
        approval_state_rel = f"{safe_name}/approval-state.json"
        agent_handoff_rel = f"{safe_name}/agent-handoff.json"

        sprint_manifest = build_sprint_manifest(
            niche_name,
            urls[0]["url"] if urls else "",
            competitors,
            sprint_context=sprint_context,
            locked_competitors=locked_competitors,
            key_findings=key_findings,
            total_snapshots=total_snapshots,
            total_changes=total_changes,
            competitor_source=competitor_source,
            niche_narrative=niche_narrative,
        )

        self._notify(
            status_callback,
            "rendering_report",
            f"Rendering report for {niche_name}.",
            competitors_total=competitors_total,
            competitors_completed=competitors_total,
            narrator_enabled=self.narrator.enabled and self.enable_narrative,
            current_action="rendering_html",
        )

        html_out = self.reporter.generate(
            niche_name, competitors, html_rel,
            niche_narrative=niche_narrative,
            locked_competitors=locked_competitors,
            key_findings=key_findings,
            roi_analysis=roi_analysis,
            agent_tasks=agent_tasks,
            video_script=video_script,
            is_paid=is_paid,
        )

        # PUBLIC CASE STUDY / OUTREACH GENERATION
        # We always generate a redacted version for acquisition & sharing
        public_html_rel = f"{safe_name}/public-demo.html"
        redactions = {
            r"[A-Z][a-z]+ [A-Z][a-z]+": "[NAME REDACTED]",
            r"[\w\.-]+@[\w\.-]+\.\w+": "[EMAIL REDACTED]",
            r"\$\d+(?:\.\d+)?(?:[KMB])?": "$[REDACTED]" # Redact specific revenue numbers for demo
        }
        
        # Public case study with optional breakthrough story
        breakthrough_story = None
        story_path = os.path.join("stories", f"{safe_name}_breakout.md")
        if os.path.exists(story_path):
            with open(story_path, "r") as f:
                breakthrough_story = f.read()
        
        public_html_out = self.reporter.generate(
            niche_name, competitors, public_html_rel,
            niche_narrative=niche_narrative,
            locked_competitors=locked_competitors,
            key_findings=key_findings,
            roi_analysis=roi_analysis,
            is_public=True,
            redactions=redactions,
            agent_tasks=agent_tasks,
            breakthrough_story=breakthrough_story,
            video_script=video_script,
        )
        # Multi-artifact output tracking
        html_out = result_path
        # public_html_out was already generated above

        json_out = self.reporter.generate_json(niche_name, competitors, json_rel, niche_narrative=niche_narrative)
        manifest_out = self.reporter.generate_manifest(sprint_manifest, manifest_rel)
        brief_out = self.reporter.generate_internal_brief(
            sprint_manifest,
            competitors,
            brief_rel,
            key_findings=key_findings,
            roi_analysis=roi_analysis,
        )
        leadideal_handoff_out = self.reporter.generate_leadideal_handoff(sprint_manifest, leadideal_handoff_rel)
        leadideal_handoff_payload = build_leadideal_handoff(sprint_manifest)
        self._notify(
            status_callback,
            "leadideal_preview",
            f"Running LeadIdeal preview follow-up for {niche_name}.",
            competitors_total=competitors_total,
            competitors_completed=competitors_total,
            current_action="leadideal_preview",
        )
        leadideal_preview = execute_leadideal_preview(leadideal_handoff_payload)
        leadideal_preview_out = self.reporter.generate_json_blob(
            leadideal_preview,
            leadideal_preview_rel,
            "LeadIdeal preview artifact",
        )
        approval_state = build_approval_state(sprint_manifest, leadideal_preview)
        approval_state_out = self.reporter.generate_json_blob(
            approval_state,
            approval_state_rel,
            "Approval state artifact",
        )
        agent_handoff_out = self.reporter.generate_json_blob(
            {
                "tasks": agent_tasks, 
                "video_script": video_script,
                "metadata": {"niche": niche_name, "generated_at": os.path.basename(html_out)}
            },
            agent_handoff_rel,
            "Agent handoff artifact",
        )

        self._notify(
            status_callback,
            "report_written",
            f"Saved report to {os.path.basename(html_out)}.",
            competitors_total=competitors_total,
            competitors_completed=competitors_total,
            narrator_enabled=self.narrator.enabled and self.enable_narrative,
            current_action="writing_output",
        )

        logger.info("Niche '%s' complete. Reports at:\n  HTML: %s\n  Public: %s\n  JSON: %s",
                     niche_name, html_out, public_html_out, json_out)

        return {
            "html": html_out,
            "public_html": public_html_out,
            "json": json_out,
            "manifest": manifest_out,
            "brief": brief_out,
            "leadideal_handoff": leadideal_handoff_out,
            "leadideal_preview": leadideal_preview_out,
            "leadideal_preview_status": leadideal_preview.get("status"),
            "approval_state": approval_state_out,
            "approval_status": approval_state.get("status"),
            "agent_handoff": agent_handoff_out,
        }

    def _process_competitor(
        self, name: str, url: str,
        from_date: Optional[str], to_date: Optional[str],
        is_target: bool = False,
        status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        competitor_index: int = 1,
        competitors_total: int = 1,
        competitors_completed: int = 0,
    ) -> Dict:
        """Pull snapshots, analyze, and diff a single competitor."""

        live_site_summary = None
        if is_target and self.analyze_live_target:
            self._notify(
                status_callback,
                f"analyzing_{competitor_index}",
                f"Crawling the current live site for {name}.",
                current_competitor=name,
                current_competitor_index=competitor_index,
                competitors_total=competitors_total,
                competitors_completed=competitors_completed,
                snapshots_total=0,
                snapshots_completed=0,
                current_action="crawling_live_site",
            )
            live_site_summary = self.live_site_analyzer.analyze_site(url)

        self._notify(
            status_callback,
            f"analyzing_{competitor_index}",
            f"Querying archive history for {name}.",
            current_competitor=name,
            current_competitor_index=competitor_index,
            competitors_total=competitors_total,
            competitors_completed=competitors_completed,
            snapshots_total=0,
            snapshots_completed=0,
            current_action="querying_archive_history",
        )

        # Get snapshots once, then sample from that candidate pool.
        all_snapshots = self.client.get_snapshot_candidates(
            url,
            from_date=from_date,
            to_date=to_date,
            minimum_count=self.max_snapshots,
        )
        if len(all_snapshots) <= self.max_snapshots:
            key_snapshots = list(all_snapshots)
        else:
            key_snapshots = self.client._select_temporal_samples(all_snapshots, self.max_snapshots)
        snapshot_total = len(key_snapshots)

        self._notify(
            status_callback,
            f"analyzing_{competitor_index}",
            f"Found {snapshot_total or 0} representative snapshots for {name}.",
            current_competitor=name,
            current_competitor_index=competitor_index,
            competitors_total=competitors_total,
            competitors_completed=competitors_completed,
            snapshots_total=snapshot_total,
            snapshots_completed=0,
            current_action="selecting_snapshots",
        )

        analyses = []
        for snapshot_index, snap in enumerate(key_snapshots, start=1):
            ts = snap["timestamp"]
            snapshot_url = self.client.get_snapshot_url(ts, url)

            logger.info("    Fetching snapshot %s ...", ts)
            self._notify(
                status_callback,
                f"analyzing_{competitor_index}",
                f"Fetching {name} snapshot {snapshot_index}/{snapshot_total}.",
                current_competitor=name,
                current_competitor_index=competitor_index,
                competitors_total=competitors_total,
                competitors_completed=competitors_completed,
                snapshots_total=snapshot_total,
                snapshots_completed=snapshot_index - 1,
                current_snapshot_index=snapshot_index,
                current_snapshot_timestamp=ts,
                current_action="fetching_snapshot",
            )
            html = self.client.fetch_snapshot_html(ts, url)
            if not html:
                continue

            analysis = self.analyzer.analyze(html, url, ts, snapshot_url)
            analyses.append(analysis)
            self._notify(
                status_callback,
                f"analyzing_{competitor_index}",
                f"Extracted signals from {name} snapshot {snapshot_index}/{snapshot_total}.",
                current_competitor=name,
                current_competitor_index=competitor_index,
                competitors_total=competitors_total,
                competitors_completed=competitors_completed,
                snapshots_total=snapshot_total,
                snapshots_completed=snapshot_index,
                current_snapshot_index=snapshot_index,
                current_snapshot_timestamp=ts,
                current_action="extracting_signals",
            )

        # Compute diffs between consecutive snapshots
        changes = []
        for i in range(1, len(analyses)):
            diffs = diff_analyses(analyses[i - 1], analyses[i])
            if diffs:
                changes.append({
                    "from_ts": self._format_ts(analyses[i - 1].timestamp),
                    "to_ts": self._format_ts(analyses[i].timestamp),
                    "snapshot_url": analyses[i].snapshot_url,
                    "diffs": diffs,
                })

        # Use the larger of the two counts (CDX may return different totals)
        snap_count = max(len(all_snapshots), len(key_snapshots))

        if not analyses:
            logger.warning("No analyzable snapshots found for %s (%s)", name, url)

        current_analysis = None
        current_analysis_source = "archive"
        if live_site_summary and live_site_summary.get("homepage"):
            current_analysis = live_site_summary["homepage"]
            current_analysis_source = "live_crawl"
        elif analyses:
            current_analysis = analyses[-1].to_dict()

        return {
            "name": name,
            "url": url,
            "snapshot_count": snap_count,
            "selected_snapshot_count": snapshot_total,
            "analyzed_snapshot_count": len(analyses),
            "analyses": [a.to_dict() for a in analyses],
            "changes": changes,
            "current_analysis": current_analysis,
            "current_analysis_source": current_analysis_source,
            "live_site_summary": live_site_summary,
        }

    @staticmethod
    def _format_ts(ts: str) -> str:
        """Format '20240315120000' -> '2024-03-15'"""
        if len(ts) >= 8:
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        return ts

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "report"

    @staticmethod
    def _notify(
        status_callback: Optional[Callable[[Dict[str, Any]], None]],
        stage: str,
        detail: str,
        **metadata: Any,
    ) -> None:
        if status_callback:
            payload = {"stage": stage, "status_detail": detail}
            payload.update(metadata)
            status_callback(payload)
