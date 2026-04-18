"""Live site crawler and aggregator for current-state analysis."""

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .page_analyzer import PageAnalyzer

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20
DEFAULT_MAX_PAGES = 75


class LiveSiteAnalyzer:
    """Crawls a live website via sitemap and internal links and aggregates the current state."""

    def __init__(self, max_pages: int = DEFAULT_MAX_PAGES, timeout: int = DEFAULT_TIMEOUT):
        self.max_pages = max_pages
        self.timeout = timeout
        self.analyzer = PageAnalyzer()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "WaybackRevenuePipeline/1.0 (live site analyzer)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def analyze_site(self, raw_url: str) -> Optional[Dict]:
        base_url = self._normalize_base_url(raw_url)
        if not base_url:
            return None

        discovered_urls = self._discover_urls(base_url)
        if not discovered_urls:
            discovered_urls = [base_url]

        page_results = []
        crawled_urls = []

        for page_url in discovered_urls[: self.max_pages]:
            html, final_url = self._fetch_html(page_url)
            if not html:
                continue

            analysis = self.analyzer.analyze(
                html,
                final_url,
                "live",
                final_url,
            ).to_dict()
            analysis["is_live"] = True
            page_results.append(analysis)
            crawled_urls.append(final_url)

        if not page_results:
            return None

        homepage = self._pick_homepage_result(base_url, page_results)
        return {
            "base_url": base_url,
            "page_count": len(page_results),
            "crawled_urls": crawled_urls,
            "pages": page_results,
            "homepage": homepage,
            "aggregate_ctas": self._aggregate_lists(page_results, "cta_buttons", limit=20),
            "aggregate_tech_stack": self._aggregate_lists(page_results, "tech_stack", limit=20),
            "sample_pages": self._build_sample_pages(page_results, base_url),
            "page_titles": [page.get("title") for page in page_results if page.get("title")][:15],
        }

    def _discover_urls(self, base_url: str) -> List[str]:
        sitemap_urls = self._discover_sitemap_urls(base_url)
        sitemap_pages = self._collect_sitemap_pages(base_url, sitemap_urls)
        crawl_pages = self._crawl_internal_pages(base_url, seeded_urls=sitemap_pages)

        ordered = []
        seen = set()
        for url in [base_url] + sitemap_pages + crawl_pages:
            canonical = self._canonicalize_url(url)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            ordered.append(canonical)
        return ordered

    def _discover_sitemap_urls(self, base_url: str) -> List[str]:
        sitemap_urls = []
        robots_url = urljoin(base_url, "/robots.txt")
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.ok and response.text:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url:
                            sitemap_urls.append(sitemap_url)
        except requests.RequestException:
            logger.debug("robots.txt unavailable for %s", base_url)

        sitemap_urls.extend([
            urljoin(base_url, "/sitemap.xml"),
            urljoin(base_url, "/sitemap_index.xml"),
        ])

        deduped = []
        seen = set()
        for sitemap_url in sitemap_urls:
            if sitemap_url not in seen:
                seen.add(sitemap_url)
                deduped.append(sitemap_url)
        return deduped

    def _collect_sitemap_pages(self, base_url: str, sitemap_urls: List[str]) -> List[str]:
        pages = []
        queue = deque(sitemap_urls)
        seen_sitemaps = set()

        while queue and len(pages) < self.max_pages:
            sitemap_url = queue.popleft()
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)

            xml_text, final_url = self._fetch_html(sitemap_url, allow_xml=True)
            if not xml_text:
                continue

            soup = BeautifulSoup(xml_text, "xml")
            if soup.find("sitemapindex"):
                for loc in soup.find_all("loc"):
                    nested = loc.get_text(strip=True)
                    if nested:
                        queue.append(nested)
                continue

            if soup.find("urlset"):
                for loc in soup.find_all("loc"):
                    page_url = self._canonicalize_url(loc.get_text(strip=True))
                    if page_url and self._is_same_site(base_url, page_url):
                        pages.append(page_url)
                        if len(pages) >= self.max_pages:
                            break
                continue

            # Some sites expose HTML sitemap pages instead of XML.
            html_soup = BeautifulSoup(xml_text, "html.parser")
            for anchor in html_soup.find_all("a", href=True):
                page_url = self._canonicalize_url(urljoin(final_url or sitemap_url, anchor["href"]))
                if page_url and self._is_same_site(base_url, page_url):
                    pages.append(page_url)
                    if len(pages) >= self.max_pages:
                        break

        return pages

    def _crawl_internal_pages(self, base_url: str, seeded_urls: List[str]) -> List[str]:
        queue = deque([base_url] + list(seeded_urls))
        visited: Set[str] = set()
        discovered: List[str] = []

        while queue and len(discovered) < self.max_pages:
            current_url = self._canonicalize_url(queue.popleft())
            if not current_url or current_url in visited:
                continue
            visited.add(current_url)

            html, final_url = self._fetch_html(current_url)
            if not html:
                continue

            canonical_url = self._canonicalize_url(final_url or current_url)
            if canonical_url and canonical_url not in discovered:
                discovered.append(canonical_url)

            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                next_url = self._canonicalize_url(urljoin(final_url or current_url, anchor["href"]))
                if not next_url or next_url in visited:
                    continue
                if self._is_same_site(base_url, next_url):
                    queue.append(next_url)

        return discovered

    def _fetch_html(self, url: str, allow_xml: bool = False) -> Tuple[Optional[str], Optional[str]]:
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Live fetch failed for %s: %s", url, exc)
            return None, None

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and not (allow_xml and ("xml" in content_type or response.text.lstrip().startswith("<"))):
            return None, response.url

        return response.text, response.url

    @staticmethod
    def _pick_homepage_result(base_url: str, page_results: List[Dict]) -> Dict:
        normalized_base = LiveSiteAnalyzer._canonicalize_url(base_url)
        for page in page_results:
            if LiveSiteAnalyzer._canonicalize_url(page.get("url", "")) == normalized_base:
                return page
        return page_results[0]

    @staticmethod
    def _aggregate_lists(page_results: List[Dict], key: str, limit: int) -> List[str]:
        seen = []
        seen_lower = set()
        for page in page_results:
            for value in page.get(key, []) or []:
                lowered = value.lower()
                if lowered in seen_lower:
                    continue
                seen_lower.add(lowered)
                seen.append(value)
                if len(seen) >= limit:
                    return seen
        return seen

    @staticmethod
    def _build_sample_pages(page_results: List[Dict], base_url: str) -> List[Dict]:
        homepage_url = LiveSiteAnalyzer._canonicalize_url(base_url)
        samples = []
        for page in page_results:
            page_url = LiveSiteAnalyzer._canonicalize_url(page.get("url", ""))
            if not page_url or page_url == homepage_url:
                continue
            samples.append({
                "url": page.get("url", ""),
                "title": page.get("title", ""),
                "h1": page.get("h1", ""),
            })
            if len(samples) >= 8:
                break
        return samples

    @staticmethod
    def _normalize_base_url(raw_url: str) -> str:
        value = (raw_url or "").strip()
        if not value:
            return ""
        if "://" not in value:
            value = f"https://{value}"
        parsed = urlparse(value)
        host = (parsed.netloc or parsed.path).strip().lower()
        if not host:
            return ""
        return f"https://{host}"

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        if parsed.scheme not in {"http", "https"}:
            return ""
        cleaned_path = parsed.path.rstrip("/")
        if not cleaned_path:
            cleaned_path = ""
        return f"{parsed.scheme}://{parsed.netloc.lower()}{cleaned_path}"

    @staticmethod
    def _is_same_site(base_url: str, candidate_url: str) -> bool:
        base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
        candidate_host = urlparse(candidate_url).netloc.lower().removeprefix("www.")
        return bool(base_host and candidate_host and base_host == candidate_host)