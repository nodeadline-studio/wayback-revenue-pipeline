"""
Wayback Machine CDX + Availability API client.
Pulls snapshot history for any URL with rate limiting and deduplication.
"""

import time
import logging
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

CDX_API = "https://web.archive.org/cdx/search/cdx"
AVAILABILITY_API = "https://archive.org/wayback/available"
SNAPSHOT_BASE = "https://web.archive.org/web"

# Polite rate limit: ~1 request per second
REQUEST_DELAY = 1.2
MAX_RETRIES = 3
TIMEOUT_CDX = 60
TIMEOUT_SNAPSHOT = 60
FAST_CDX_LIMIT = 120
STANDARD_CDX_LIMIT = 500
EXPANDED_CDX_LIMIT = 1000


class WaybackClient:
    """Thin wrapper around the Wayback Machine CDX and Availability APIs."""

    def __init__(self, delay: float = REQUEST_DELAY):
        self.delay = delay
        self.session = requests.Session()

        # Configure retries
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retries = Retry(total=MAX_RETRIES, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        self.session.headers.update({
            "User-Agent": "WaybackRevenuePipeline/1.0 (research tool)"
        })
        self._last_request_time = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()

    def get_snapshots(
        self,
        url: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 500,
        collapse: str = "digest",
        status_filter: str = "200",
    ) -> List[Dict[str, str]]:
        """
        Pull snapshot list from CDX API.

        Args:
            url: Target URL (e.g. "example.com" or "example.com/pricing")
            from_date: Start date YYYYMMDD
            to_date: End date YYYYMMDD
            limit: Max results
            collapse: Dedup field ("digest" removes identical pages)
            status_filter: Only include snapshots with this HTTP status

        Returns:
            List of dicts with keys: timestamp, original, mimetype, statuscode, digest, length
        """
        self._throttle()

        params = {
            "url": url,
            "output": "json",
            "limit": limit,
            "fl": "timestamp,original,mimetype,statuscode,digest,length",
        }
        if collapse:
            params["collapse"] = collapse
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if status_filter:
            params["filter"] = f"statuscode:{status_filter}"

        try:
            resp = self.session.get(CDX_API, params=params, timeout=TIMEOUT_CDX)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("CDX API error for %s: %s", url, e)
            return []

        data = resp.json()
        if not data or len(data) < 2:
            return []

        headers = data[0]
        return [dict(zip(headers, row)) for row in data[1:]]

    def get_snapshot_candidates(
        self,
        url: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        minimum_count: int = 0,
    ) -> List[Dict[str, str]]:
        """Fetch a representative candidate pool once, widening only as needed for sparse histories."""
        target_count = max(minimum_count, 3)

        # Large sites can time out when asking CDX for thousands of digest-collapsed rows.
        # Start with a year-collapsed sample that is usually enough to pick a few temporal anchors.
        yearly = self.get_snapshots(
            url,
            from_date=from_date,
            to_date=to_date,
            limit=FAST_CDX_LIMIT,
            collapse="timestamp:4",
        )
        if len(yearly) >= target_count:
            return yearly

        collapsed = self.get_snapshots(
            url,
            from_date=from_date,
            to_date=to_date,
            limit=STANDARD_CDX_LIMIT,
            collapse="digest",
        )
        if not collapsed:
            return yearly

        if len(collapsed) >= target_count:
            return collapsed

        expanded = self.get_snapshots(
            url,
            from_date=from_date,
            to_date=to_date,
            limit=EXPANDED_CDX_LIMIT,
            collapse="",
        )
        return expanded if len(expanded) > len(collapsed) else collapsed

    def get_closest_snapshot(self, url: str, timestamp: Optional[str] = None) -> Optional[Dict]:
        """Get the closest available snapshot for a URL."""
        self._throttle()

        params = {"url": url}
        if timestamp:
            params["timestamp"] = timestamp

        try:
            resp = self.session.get(AVAILABILITY_API, params=params, timeout=15)
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            logger.error("Availability API error for %s: %s", url, e)
            return None

        snapshots = result.get("archived_snapshots", {})
        closest = snapshots.get("closest")
        if closest and closest.get("available"):
            return closest
        return None

    def fetch_snapshot_html(self, timestamp: str, url: str) -> Optional[str]:
        """
        Fetch the raw HTML of a specific snapshot.
        Uses the 'id_' flag to get the original page without Wayback toolbar.
        Tries both bare domain and https:// variant if first attempt returns non-HTML.
        """
        for url_variant in [url, f"https://{url}", f"https://{url}/"]:
            self._throttle()
            snapshot_url = f"{SNAPSHOT_BASE}/{timestamp}id_/{url_variant}"

            try:
                resp = self.session.get(snapshot_url, timeout=TIMEOUT_SNAPSHOT)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type and len(resp.text) > 200:
                    return resp.text
            except requests.RequestException as e:
                logger.debug("Snapshot fetch attempt for %s@%s: %s", url_variant, timestamp, e)
                continue

        logger.error("All fetch attempts failed for %s@%s", url, timestamp)
        return None

    def get_snapshot_url(self, timestamp: str, url: str) -> str:
        """Build a viewable snapshot URL."""
        return f"{SNAPSHOT_BASE}/{timestamp}/{url}"

    def get_key_snapshots(
        self,
        url: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        max_snapshots: int = 10,
    ) -> List[Dict[str, str]]:
        """
        Get a representative set of snapshots: first, last, and evenly spaced in between.
        This avoids fetching hundreds of pages while still capturing the evolution.
        """
        candidate_snaps = self.get_snapshot_candidates(
            url,
            from_date=from_date,
            to_date=to_date,
            minimum_count=max_snapshots,
        )
        if not candidate_snaps:
            return []

        if len(candidate_snaps) <= max_snapshots:
            return candidate_snaps

        return self._select_temporal_samples(candidate_snaps, max_snapshots)

    @staticmethod
    def _select_temporal_samples(snapshots: List[Dict[str, str]], max_snapshots: int) -> List[Dict[str, str]]:
        if not snapshots:
            return []

        if max_snapshots <= 1:
            return [snapshots[-1]]

        total = len(snapshots)
        selected = []
        chosen_indices = set()

        for i in range(max_snapshots):
            if max_snapshots == 1:
                target_index = total - 1
            else:
                target_index = round(i * (total - 1) / (max_snapshots - 1))

            while target_index < total and target_index in chosen_indices:
                target_index += 1
            while target_index >= total or target_index in chosen_indices:
                target_index -= 1
                if target_index < 0:
                    break

            if target_index < 0 or target_index in chosen_indices:
                continue

            chosen_indices.add(target_index)
            selected.append(snapshots[target_index])

        selected.sort(key=lambda snap: snap.get("timestamp", ""))
        return selected
