"""Verify markdown rendering in the new report."""
from bs4 import BeautifulSoup

html = open("/Users/tommykuznets/Downloads/My Projects/wayback-revenue-pipeline/output/free-report-leadideal-com-report.html").read()
soup = BeautifulSoup(html, "html.parser")

# Check AI insight blocks for raw markdown leaks
insights = soup.select(".ai-insight")
print(f"AI insight blocks: {len(insights)}")
for i, block in enumerate(insights):
    text = block.get_text()
    has_raw_md = "**" in text
    has_strong = bool(block.find("strong"))
    print(f"  Block {i+1}: raw_md={has_raw_md}, has_strong={has_strong}, length={len(text)} chars")
    if has_raw_md:
        idx = text.index("**")
        snippet = text[max(0, idx - 20):idx + 30]
        print(f"    RAW MD at char {idx}: ...{snippet}...")

# Check for <strong> tags (proof markdown was converted)
strongs = soup.find_all("strong")
print(f"\n<strong> tags in report: {len(strongs)}")
if strongs:
    for s in strongs[:5]:
        print(f"  - {s.get_text()[:60]}")

# Check Key Findings section
print(f"\nKey findings section exists: {'Key Findings' in html}")
print(f"Market Impact section exists: {'Market Impact Analysis' in html}")
print(f"Executive Summary section exists: {'Executive Strategic Summary' in html}")

# Check no raw bullets leaked
raw_bullets = html.count("- ")
ul_tags = len(soup.find_all("ul"))
li_tags = len(soup.find_all("li"))
print(f"\nRaw '- ' in HTML: {raw_bullets}")
print(f"<ul> tags: {ul_tags}")
print(f"<li> tags: {li_tags}")
