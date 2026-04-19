#!/usr/bin/env python3
"""Sequentially process a batch of beauty founders through the Wayback Revenue Pipeline."""

import json
import os
import time
import logging
from typing import List, Dict
from run_startup_preset import http_json, poll_job

# Config
BASE_URL = "http://127.0.0.1:8889"
BATCH_FILE = "beauty_founders_batch.json"
RESULTS_FILE = "beauty_batch_results.json"
PRESET_ID = "beauty-parallels"
COOLDOWN_SECONDS = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def run_batch():
    if not os.path.exists(BATCH_FILE):
        logger.error(f"Batch file not found: {BATCH_FILE}")
        return

    with open(BATCH_FILE, "r") as f:
        targets = json.load(f)

    results = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            try:
                results = json.load(f)
            except:
                results = []

    processed_urls = {r["url"] for r in results if r.get("status") == "completed"}
    
    logger.info(f"Starting batch run for {len(targets)} targets. {len(processed_urls)} already completed.")

    for i, target in enumerate(targets):
        url = target["url"]
        company = target["company"]
        
        if url in processed_urls:
            logger.info(f"[{i+1}/{len(targets)}] Skipping already completed: {company} ({url})")
            continue

        logger.info(f"[{i+1}/{len(targets)}] Processing {company} ({url})...")
        
        try:
            # Prepare payload override
            # We override the target_url but use the beauty-parallels preset
            payload = {
                "preset_id": PRESET_ID,
                "target_url": url,
                "startup_name": company,
                "variant_id": f"pilot-{company.lower().replace(' ', '-')}",
                "is_paid": True
            }

            # Start job
            _, start_data = http_json(f"{BASE_URL}/api/demo", method="POST", payload=payload)
            job_id = start_data["job_id"]
            
            # Poll for completion 
            final_data = poll_job(BASE_URL, job_id, timeout_seconds=600, interval_seconds=10.0)
            
            result = {
                "company": company,
                "url": url,
                "job_id": job_id,
                "status": final_data.get("status"),
                "report_url": final_data.get("report_url"),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            results.append(result)
            
            # Save progress incrementally
            with open(RESULTS_FILE, "w") as f:
                json.dump(results, f, indent=2)

            if final_data.get("status") == "completed":
                logger.info(f"✅ Completed: {company}. Report: {result['report_url']}")
            else:
                logger.warning(f"❌ Failed: {company}. Status: {final_data.get('status')}")

        except Exception as e:
            logger.error(f"💥 Error processing {company}: {e}")
            results.append({
                "company": company,
                "url": url,
                "status": "error",
                "error": str(e),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            with open(RESULTS_FILE, "w") as f:
                json.dump(results, f, indent=2)

        # Cooldown to keep CPU happy
        if i < len(targets) - 1:
            logger.info(f"Waiting {COOLDOWN_SECONDS}s before next target...")
            time.sleep(COOLDOWN_SECONDS)

    logger.info("Batch run finished.")
    completed = len([r for r in results if r.get("status") == "completed"])
    logger.info(f"Summary: {completed}/{len(targets)} completed successfully.")

if __name__ == "__main__":
    run_batch()
