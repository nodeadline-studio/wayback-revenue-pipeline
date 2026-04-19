#!/usr/bin/env python3
import os
import shutil
import glob

OUTPUT_DIR = "output"
TARGET_DIR = os.path.join(OUTPUT_DIR, "creatorpacks-outreach")

def consolidate():
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)
        print(f"Created {TARGET_DIR}")

    moved_count = 0
    
    # 1. Handle flat files in output/ (existing logic)
    patterns = [
        "free-report-*.json",
        "free-report-*.html",
        "free-report-*.md",
        "case-study-free-report-*.html"
    ]
    for pattern in patterns:
        files = glob.glob(os.path.join(OUTPUT_DIR, pattern))
        for f in files:
            basename = os.path.basename(f)
            dest = os.path.join(TARGET_DIR, basename)
            if f == dest: continue # Skip if already in place
            try:
                shutil.move(f, dest)
                moved_count += 1
            except Exception as e:
                print(f"Error moving {basename}: {e}")

    # 2. Handle nested folders (new logic)
    # New pipeline saves to output/{safe_name}/...
    # We want to flatten these into output/creatorpacks-outreach/
    subdirs = [d for d in os.listdir(OUTPUT_DIR) if os.path.isdir(os.path.join(OUTPUT_DIR, d))]
    for d in subdirs:
        if d == "creatorpacks-outreach" or d == "public":
            continue
            
        subdir_path = os.path.join(OUTPUT_DIR, d)
        for f in os.listdir(subdir_path):
            # Rename file to include parent dir name for uniqueness if needed, 
            # but usually it's report.html, data.json etc.
            # Let's map them to {safe_name}-{filename}
            new_name = f"{d}-{f}"
            dest = os.path.join(TARGET_DIR, new_name)
            try:
                shutil.move(os.path.join(subdir_path, f), dest)
                moved_count += 1
            except Exception as e:
                print(f"Error moving {f} from {d}: {e}")
        
        # Clean up empty subdirectory
        try:
            os.rmdir(subdir_path)
        except:
            pass

    print(f"Moved {moved_count} total files to {TARGET_DIR}")

if __name__ == "__main__":
    consolidate()
