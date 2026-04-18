"""Final quality checklist for the new report."""
html = open("/Users/tommykuznets/Downloads/My Projects/wayback-revenue-pipeline/output/free-report-leadideal-com-report.html").read()

checks = [
    ("Total HTML size", f"{len(html):,} bytes"),
    ("Executive Strategic Summary", "Executive Strategic Summary" in html),
    ("Key Findings", "Key Findings" in html),
    ("Market Impact Analysis", "Market Impact Analysis" in html),
    ("Winning Strategies", "Working in This Market" in html),
    ("Warning Signs", "Warning Signs" in html),
    ("Market Trends", "Market Trends" in html),
    ("Your Opportunity", "Your Opportunity" in html),
    ("Strategic Insight blocks", html.count("Strategic Insight")),
    ("Change Timeline sections", html.count("Change Timeline")),
    ("Locked competitors CTA", "Unlock the Full Strategy Report" in html),
    ("Tech Stack section", "Tech Stack Across" in html),
    ("Pricing section", "Pricing Signals" in html),
]

for name, value in checks:
    status = "PASS" if value else "FAIL"
    if isinstance(value, bool):
        print(f"  [{status}] {name}")
    else:
        print(f"  [INFO] {name}: {value}")
