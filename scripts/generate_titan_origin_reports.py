import sys
import os
import json
import logging
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.pipeline import Pipeline
from src.startup_intel import build_sprint_context

logging.basicConfig(level=logging.INFO)

def generate_titan_reports():
    pipeline = Pipeline(max_snapshots_per_url=6, enable_narrative=True)
    targets = [
        {"name": "Visualping", "url": "visualping.io", "path": "case-study-visualping-io.html"},
        {"name": "Klue", "url": "klue.com", "path": "case-study-klue-com.html"},
        {"name": "Crayon", "url": "crayon.co", "path": "case-study-crayon-co.html"}
    ]
    
    output_dir = "output" # Reports are linked from /reports/ which points to output/
    
    for target in targets:
        print(f"🚀 Generating Titan Origin Report for {target['name']}...")
        
        payload = {
            "startup_name": target["name"],
            "objective": f"De-risk positioning by analyzing {target['name']}'s early pivots.",
            "audience": "Founders",
            "publishability": {
                "public_case_study_ready": True,
                "redactions_needed": []
            }
        }
        
        context = build_sprint_context(payload, target["url"])
        
        # We manually trigger process_niche for each
        # Using the Titan's own URL as the target
        pipeline.process_niche(
            target["name"],
            [{"name": target["name"], "url": target["url"]}],
            output_dir,
            sprint_context=context,
            competitor_source="titan_origin_mining"
        )
        
        # Note: Pipeline saves it as {slug}-report.html and case-study-{slug}.html
        # We need to make sure the links in index.html match or we rename them.
        # index.html currently has: /reports/case-study-visualping-io.html
        
    print("✅ Titan reports generated.")

if __name__ == "__main__":
    generate_titan_reports()
