"""
Evidence collector: extracts verbatim quotes (with source URLs) from competitor pages
that have already been crawled by LiveSiteAnalyzer. No additional HTTP fetches.

Used by the narrator to ground LLM output in real source data.
"""

from typing import Dict, List, Optional
from urllib.parse import urlparse


def _classify_section(url: str) -> str:
    """Heuristic: classify a competitor page URL into a section bucket."""
    if not url:
        return "page"
    path = (urlparse(url).path or "/").lower().rstrip("/")
    if path in ("", "/"):
        return "homepage"
    if "pricing" in path or "/plans" in path:
        return "pricing"
    if "/blog" in path or "/news" in path or "/insights" in path:
        return "blog"
    if "/about" in path or "/company" in path:
        return "about"
    if "/customers" in path or "/case-studies" in path or "/case-study" in path:
        return "case_study"
    if "/features" in path or "/product" in path:
        return "product"
    return "page"


def _shorten(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "..."
    return text


def collect_evidence(live_site_summary: Optional[Dict], max_quotes: int = 8) -> List[Dict]:
    """
    Build a list of {quote, url, section} records from a competitor's live_site_summary.

    Strategy:
      - homepage h1 + meta + first h2
      - pricing page h1 + first 2 h2s
      - blog page h1 + first h2
      - dedupe near-identical quotes
      - cap at `max_quotes`
    """
    if not live_site_summary:
        return []

    pages = live_site_summary.get("pages") or []
    if not pages:
        return []

    quotes: List[Dict] = []
    seen_quotes = set()

    def _push(text: str, url: str, section: str):
        clean = _shorten(text)
        if not clean or len(clean) < 12:
            return
        key = clean.lower()
        if key in seen_quotes:
            return
        seen_quotes.add(key)
        quotes.append({"quote": clean, "url": url, "section": section})

    # Order pages so homepage > pricing > blog > others
    section_priority = {"homepage": 0, "pricing": 1, "blog": 2, "case_study": 3,
                        "product": 4, "about": 5, "page": 9}
    decorated = []
    for p in pages:
        url = p.get("url") or p.get("snapshot_url") or ""
        section = _classify_section(url)
        decorated.append((section_priority.get(section, 9), section, url, p))
    decorated.sort(key=lambda t: t[0])

    for _, section, url, page in decorated:
        if len(quotes) >= max_quotes:
            break
        h1 = page.get("h1") or ""
        meta = page.get("meta_description") or ""
        h2s = page.get("h2_list") or []
        title = page.get("title") or ""

        if section == "homepage":
            _push(h1, url, "homepage_h1")
            _push(meta, url, "homepage_meta")
            if h2s:
                _push(h2s[0], url, "homepage_h2")
        elif section == "pricing":
            _push(h1 or title, url, "pricing_h1")
            for h2 in h2s[:2]:
                _push(h2, url, "pricing_h2")
        elif section in ("blog", "case_study"):
            _push(h1 or title, url, f"{section}_title")
            if h2s:
                _push(h2s[0], url, f"{section}_h2")
        else:
            _push(h1 or title, url, f"{section}_title")

    return quotes[:max_quotes]
