#!/usr/bin/env python3
import json
import os
import re
from typing import List, Dict

# Config
OUTREACH_DIR = "output/creatorpacks-outreach"
FOUNDERS_FILE = "beauty_founders_batch.json"
RESULTS_FILE = "beauty_batch_results.json"
TEMPLATE_A_PATH = "/Users/tommykuznets/.gemini/antigravity/brain/4e07ac22-6470-4672-9896-a41db055216c/beauty_outreach_template.md"
TEMPLATE_B_PATH = "/Users/tommykuznets/.gemini/antigravity/brain/4e07ac22-6470-4672-9896-a41db055216c/outreach_variant_b.md"
OUTPUT_DRAFTS_FILE = os.path.join(OUTREACH_DIR, "beauty_outreach_drafts.md")

def slugify(text: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]', '-', text.lower()).strip('-')
    return re.sub(r'-+', '-', slug)

def load_template(path: str) -> str:
    if not os.path.exists(path):
        # Fallback if path is different in execution env
        alt_path = os.path.basename(path)
        if os.path.exists(alt_path):
            with open(alt_path, 'r') as f:
                return f.read()
        return ""
    with open(path, 'r') as f:
        return f.read()

def generate_drafts():
    if not os.path.exists(FOUNDERS_FILE):
        print(f"Error: {FOUNDERS_FILE} not found")
        return

    with open(FOUNDERS_FILE, 'r') as f:
        founders = json.load(f)

    # Load templates
    template_a = load_template(TEMPLATE_A_PATH)
    template_b = load_template(TEMPLATE_B_PATH)

    if not template_a:
        print("Error: Could not load outreach template A")
        return

    drafts = []
    drafts.append("# CreatorPacks Beauty Outreach Drafts\n")
    drafts.append(f"Generated from Business Spy insights in `{OUTREACH_DIR}`\n")
    drafts.append("---\n")

    found_count = 0
    all_files = os.listdir(OUTREACH_DIR)
    
    for entry in founders:
        company = entry['company']
        founder = entry['founder']
        target_url = entry['url']
        
        target_slug = slugify(target_url)
        manifest_path = None
        
        # Search for any manifest file containing the slug
        for f in all_files:
            if target_slug in f and f.endswith("-manifest.json"):
                manifest_path = os.path.join(OUTREACH_DIR, f)
                break

        if manifest_path and os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            # Extract insights
            findings = manifest.get('key_findings', [])
            ai_insight = ""
            for comp in manifest.get('competitors', []):
                if comp.get('role') == 'target':
                    ai_insight = comp.get('ai_insight', "No specific insight found.")
                    break
            
            # Determine which template to use (A for deep parallels, B for aggressive SaaS check)
            # For now, we'll generate BOTH for each target
            
            # Variant A Draft
            draft_a = template_a.replace("[Founder Name]", founder)
            draft_a = draft_a.replace("[Company]", company)
            draft_a = draft_a.replace("[Link to Business Spy Report]", f"https://reports.bizspy.ai/creatorpacks-outreach/free-report-{slugify(target_url)}-report.html")
            draft_a = draft_a.replace("[Link to CreatorPacks]", "https://creatorpacks.store/checkout?packageId=beauty-25")
            draft_a = draft_a.replace("[Your Name]", "Tommy") # Founder persona
            
            # Variant B Draft
            draft_b = template_b.replace("[Founder Name]", founder)
            draft_b = draft_b.replace("[Company]", company)
            draft_b = draft_b.replace("[Competitor_Name]", "Modash")
            draft_b = draft_b.replace("[Link to CreatorPacks]", "https://creatorpacks.store/checkout?packageId=beauty-25")
            draft_b = draft_b.replace("[Your Name]", "Tommy")

            drafts.append(f"## Target: {company} ({founder})\n")
            drafts.append(f"### Variant A: Historical Parallel\n")
            drafts.append(draft_a + "\n")
            drafts.append(f"### Variant B: SaaS Bloat Check\n")
            drafts.append(draft_b + "\n")
            drafts.append("---\n")
            found_count += 1
        else:
            # Skip if manifest not found yet
            continue

    with open(OUTPUT_DRAFTS_FILE, 'w') as f:
        f.write("\n".join(drafts))

    print(f"Generated {found_count} outreach drafts in {OUTPUT_DRAFTS_FILE}")

if __name__ == "__main__":
    generate_drafts()
