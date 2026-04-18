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

def run_self_analysis():
    print("🚀 Starting Business Spy Self-Analysis (Positioning Sprint)...")
    
    pipeline = Pipeline(max_snapshots_per_url=6, enable_narrative=True)
    
    # Target and Competitors
    niche_name = "Competitive Intelligence Forensics"
    competitors = [
        {"name": "Visualping", "url": "visualping.io"},
        {"name": "Klue", "url": "klue.com"},
        {"name": "Crayon", "url": "crayon.co"},
        {"name": "Competitors.app", "url": "competitors.app"}
    ]
    
    output_dir = "output/self-analysis"
    os.makedirs(output_dir, exist_ok=True)
    
    payload = {
        "startup_name": "Business Spy",
        "objective": "Identify messaging gaps in incumbents to win the 'Founder De-risking' market.",
        "offer": "Strategic Pivot Forensics",
        "audience": "Pre-launch and Seed founders",
        "publishability": {
            "public_case_study_ready": True,
            "redactions_needed": []
        }
    }
    
    context = build_sprint_context(payload, "business-spy.ai")
    
    results = pipeline.process_niche(
        niche_name,
        competitors,
        output_dir,
        sprint_context=context,
        competitor_source="strategic_self_analysis"
    )
    
    print(f"✅ Self-analysis complete. Report: {results['html']}")

if __name__ == "__main__":
    run_self_analysis()
