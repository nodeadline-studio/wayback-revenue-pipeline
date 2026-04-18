#!/usr/bin/env python3
"""
Wayback Beauty Pilot: Historical Parallel Generator.
Generates a 'Proof of Growth' asset for fresh beauty founders by comparing them 
to the early historical stages of established giants like Glossier.
"""
import os
import sys
import json
import subprocess
from datetime import datetime

# Path setup
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

def run_pilot(target_url: str = None):
    print(f"\n{'='*60}")
    print(f"WAYBACK BEAUTY PILOT: Historical Parallel Generator")
    print(f"{'='*60}")
    
    preset_id = "beauty-parallels"
    
    # Use a real fresh beauty brand if provided, else use the preset default
    cmd = [
        "python3", 
        "scripts/run_startup_preset.py", 
        "--preset-id", preset_id
    ]
    
    if target_url:
        cmd.extend(["--target-url", target_url])
        
    print(f"Running historical analysis for: {target_url or 'Preset Default'}")
    print(f"Benchmark giants: Glossier (2014), The Ordinary (2016), Hero (2017)")
    print(f"Command: {' '.join(cmd)}\n")
    
    try:
        # Note: This assumes the local app is running on 8889
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        
        # Parse output for report URL
        lines = result.stdout.splitlines()
        report_url = None
        for line in lines:
            if '"report_url":' in line:
                report_url = line.split('"')[3]
                break
        
        if report_url:
            print(f"\nSUCCESS: Pilot Report Generated")
            print(f"URL: {report_url}")
            print(f"Step 2: Use LeadIdeal to find fresh founders of beauty firms.")
            print(f"Step 3: Send this report as the high-conversion 'Historical Parallel' hook.")
        else:
            print("\nWARNING: Run completed but report URL was not found in output.")
            
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Pilot run failed.")
        print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # Example target: A hypothetical new skincare brand
    target = sys.argv[1] if len(sys.argv) > 1 else "vibebrand-beauty.com"
    run_pilot(target)
