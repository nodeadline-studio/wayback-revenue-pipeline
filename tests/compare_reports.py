"""Compare the hybrid benchmark report vs current free report structure/quality."""
from bs4 import BeautifulSoup
from pathlib import Path
import re

base = Path("/Users/tommykuznets/Downloads/My Projects/wayback-revenue-pipeline/output")

for name, label in [
    ("leadideal-hybrid-competitors-report.html", "HYBRID (benchmark)"),
    ("free-report-leadideal-com-report.html", "CURRENT"),
]:
    html = (base / name).read_text()
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    print(f"\n{'='*60}")
    print(f"  {label}: {name}")
    print(f"{'='*60}")
    print(f"  File size: {len(html):,} bytes")
    print(f"  Text content: {len(text):,} chars")

    headings = [h.get_text(strip=True) for h in soup.find_all(re.compile(r"^h[1-4]$"))]
    print(f"  Headings ({len(headings)}):")
    for h in headings:
        print(f"    - {h[:80]}")

    selectors = {
        "competitor cards": ".competitor-card",
        "AI insight blocks": ".ai-insight, .ai_insight, [class*=insight]",
        "change events": ".change-event, .timeline-event, [class*=change]",
        "tables": "table",
        "narrative blocks": ".narrative, [class*=narrative], [class*=summary]",
        "key findings items": ".key-finding, [class*=finding]",
        "CTA blocks": "[class*=cta], [class*=upgrade]",
    }
    for label2, sel in selectors.items():
        count = len(soup.select(sel))
        if count:
            print(f"  {label2}: {count}")

    keywords = [
        "AI Insight", "Strategic", "Key Finding", "Market Impact",
        "ROI", "Revenue", "Recommendation", "Trend", "Signal",
        "Winning", "Failing", "pricing", "snapshot", "archive",
    ]
    for kw in keywords:
        cnt = text.lower().count(kw.lower())
        if cnt:
            print(f"  mentions '{kw}': {cnt}")
