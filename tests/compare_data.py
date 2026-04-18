"""Compare data depth between hybrid and current reports."""
import json
from pathlib import Path

base = Path("/Users/tommykuznets/Downloads/My Projects/wayback-revenue-pipeline/output")

for name in ["leadideal-hybrid-competitors-data.json", "free-report-leadideal-com-data.json"]:
    d = json.loads((base / name).read_text())
    comps = d.get("competitors", [])
    print(f"\n=== {name} ===")
    print(f"  Competitors: {len(comps)}")
    for c in comps:
        ch = len(c.get("changes", []))
        an = len(c.get("analyses", []))
        ins = bool(c.get("ai_insight"))
        live = bool(c.get("live_site_summary"))
        snap = c.get("snapshot_count", 0)
        print(f"  {c['name']:25s} snap={snap:3d} anal={an} changes={ch} insight={ins} live={live}")
