"""
HTML page analyzer.
Extracts headlines, CTAs, pricing signals, meta tags, and tech stack from snapshot HTML.
"""

import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common CTA button patterns
CTA_PATTERNS = re.compile(
    r"(get started|sign up|buy now|start free|try free|book a demo|schedule|download"
    r"|subscribe|join|order now|add to cart|claim|request|learn more|contact us"
    r"|start trial|free trial|get access|unlock|register)",
    re.IGNORECASE,
)

# Price detection
PRICE_PATTERN = re.compile(r"\$\d[\d,]*(?:\.\d{2})?(?:\s*/\s*(?:mo|month|yr|year|week))?", re.IGNORECASE)

# Tech stack signals in script src / meta tags
TECH_SIGNATURES = {
    "Google Analytics": ["google-analytics.com", "gtag/js", "ga.js", "analytics.js"],
    "Google Tag Manager": ["googletagmanager.com"],
    "Facebook Pixel": ["connect.facebook.net", "fbevents.js", "fbq("],
    "Hotjar": ["hotjar.com", "static.hotjar.com"],
    "Intercom": ["intercom.io", "widget.intercom.io"],
    "Drift": ["drift.com", "js.driftt.com"],
    "HubSpot": ["hubspot.com", "hs-scripts.com", "js.hs-analytics.net"],
    "Stripe": ["js.stripe.com", "stripe.com/v3"],
    "PayPal": ["paypal.com/sdk", "paypalobjects.com"],
    "Mixpanel": ["mixpanel.com", "cdn.mxpnl.com"],
    "Segment": ["cdn.segment.com", "analytics.js"],
    "Shopify": ["cdn.shopify.com", "myshopify.com"],
    "WordPress": ["wp-content", "wp-includes"],
    "Webflow": ["webflow.com", "assets.website-files.com"],
    "Wix": ["static.wixstatic.com", "parastorage.com"],
    "Squarespace": ["squarespace.com", "sqsp.com"],
    "Next.js": ["_next/static", "__NEXT_DATA__"],
    "React": ["react.production.min", "react-dom"],
    "Vue.js": ["vue.min.js", "vue.global", "vue.runtime"],
    "TikTok Pixel": ["analytics.tiktok.com"],
    "Crisp": ["client.crisp.chat"],
    "Zendesk": ["zdassets.com", "zendesk.com"],
    "Calendly": ["calendly.com"],
    "Typeform": ["typeform.com"],
}


@dataclass
class PageAnalysis:
    """Analysis results for a single page snapshot."""
    url: str
    timestamp: str
    snapshot_url: str = ""

    title: str = ""
    meta_description: str = ""
    h1: str = ""
    h2_list: List[str] = field(default_factory=list)

    cta_buttons: List[str] = field(default_factory=list)
    prices_found: List[str] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)

    word_count: int = 0
    image_count: int = 0
    link_count: int = 0
    form_count: int = 0

    og_image: str = ""
    canonical: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class PageAnalyzer:
    """Extracts structured data from raw HTML."""

    def analyze(self, html: str, url: str, timestamp: str, snapshot_url: str = "") -> PageAnalysis:
        result = PageAnalysis(url=url, timestamp=timestamp, snapshot_url=snapshot_url)

        if not html:
            return result

        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.find("title")
        if title_tag:
            result.title = title_tag.get_text(strip=True)

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            result.meta_description = meta_desc.get("content", "")

        # OG image
        og_img = soup.find("meta", attrs={"property": "og:image"})
        if og_img:
            result.og_image = og_img.get("content", "")

        # Canonical
        canonical = soup.find("link", attrs={"rel": "canonical"})
        if canonical:
            result.canonical = canonical.get("href", "")

        # Headings
        h1 = soup.find("h1")
        if h1:
            result.h1 = h1.get_text(strip=True)

        result.h2_list = [h2.get_text(strip=True) for h2 in soup.find_all("h2")][:10]

        # CTA buttons - look in <a> and <button> elements
        seen_ctas_lower = set()
        for el in soup.find_all(["a", "button"]):
            # Use separator to avoid concatenated text from nested elements
            text = el.get_text(separator=" ", strip=True)
            if text and CTA_PATTERNS.search(text):
                cta = text[:80].strip()
                if cta.lower() not in seen_ctas_lower:
                    seen_ctas_lower.add(cta.lower())
                    result.cta_buttons.append(cta)

        # Prices
        page_text = soup.get_text()
        result.prices_found = list(set(PRICE_PATTERN.findall(page_text)))[:20]

        # Tech stack
        full_html_lower = html.lower()
        for tech, signatures in TECH_SIGNATURES.items():
            for sig in signatures:
                if sig.lower() in full_html_lower:
                    if tech not in result.tech_stack:
                        result.tech_stack.append(tech)
                    break

        # Counts
        result.word_count = len(page_text.split())
        result.image_count = len(soup.find_all("img"))
        result.link_count = len(soup.find_all("a"))
        result.form_count = len(soup.find_all("form"))

        return result


def diff_analyses(old: PageAnalysis, new: PageAnalysis) -> Dict:
    """Compare two snapshots and return what changed."""
    changes = {}

    if old.title != new.title:
        changes["title"] = {"from": old.title, "to": new.title}
    if old.h1 != new.h1:
        changes["h1"] = {"from": old.h1, "to": new.h1}
    if old.meta_description != new.meta_description:
        changes["meta_description"] = {"from": old.meta_description, "to": new.meta_description}

    old_ctas = set(old.cta_buttons)
    new_ctas = set(new.cta_buttons)
    if old_ctas != new_ctas:
        changes["cta_buttons"] = {
            "added": list(new_ctas - old_ctas),
            "removed": list(old_ctas - new_ctas),
        }

    old_prices = set(old.prices_found)
    new_prices = set(new.prices_found)
    if old_prices != new_prices:
        changes["pricing"] = {
            "added": list(new_prices - old_prices),
            "removed": list(old_prices - new_prices),
        }

    old_tech = set(old.tech_stack)
    new_tech = set(new.tech_stack)
    if old_tech != new_tech:
        changes["tech_stack"] = {
            "added": list(new_tech - old_tech),
            "removed": list(old_tech - new_tech),
        }

    wc_delta = new.word_count - old.word_count
    if abs(wc_delta) > 50:
        changes["word_count"] = {"delta": wc_delta, "from": old.word_count, "to": new.word_count}

    return changes
