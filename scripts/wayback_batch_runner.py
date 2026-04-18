#!/usr/bin/env python3
import json
import subprocess
import os
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH_FILE = os.path.join(PROJECT_ROOT, "beauty_founders_batch.json")
PRESET_ID = "beauty-parallels"

def run_batch():
    with open(BATCH_FILE, 'r') as f:
        targets = json.load(f)
    
    print(f"Starting batch process for {len(targets)} beauty founders...")
    results = []

    for target in targets:
        company = target['company']
        url = target['url']
        print(f"\n[{company}] Processing {url}...")
        
        cmd = [
            "python3",
            "scripts/run_startup_preset.py",
            "--preset-id", PRESET_ID,
            "--target-url", url
        ]
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Find the LAST valid JSON object in the output
            lines = res.stdout.strip().splitlines()
            output = None
            for line in reversed(lines):
                line = line.strip()
                if line.startswith('{') and line.endswith('}'):
                    try:
                        output = json.loads(line)
                        break
                    except:
                        continue
            
            if output:
                report_url = output.get("report_url")
                print(f"[{company}] DONE. Report: {report_url}")
                results.append({
                    "company": company,
                    "url": url,
                    "status": "success",
                    "report_url": report_url
                })
            else:
                raise ValueError("No valid JSON found in output")
        except Exception as e:
            print(f"[{company}] FAILED: {e}")
            results.append({
                "company": company,
                "url": url,
                "status": "failed",
                "error": str(e)
            })
        
        # small delay to prevent overwhelming the local worker if it's single-threaded
        time.sleep(1)

    # Save results summary
    output_file = os.path.join(PROJECT_ROOT, "beauty_batch_results.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nBatch complete! Results saved to {output_file}")

if __name__ == "__main__":
    run_batch()
