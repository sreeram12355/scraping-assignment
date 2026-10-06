"""HTTP layer: rate limiting, retries with exponential backoff, robots.txt check."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from config import Config

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """A URL could not be fetched (after retries where retrying makes sense)."""


class HttpClient:
    def __init__(self, cfg: Config, session=None, sleep=time.sleep, clock=time.monotonic):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": cfg.user_agent})
        self._sleep = sleep
        self._clock = clock
        self._last_request = float("-inf")
        self._robots: dict[str, RobotFileParser] = {}
        # counters reported in the summary
        self.requests_made = 0
        self.retries = 0
        self.failures = 0

    # -- rate limiting ---------------------------------------------------
    def _throttle(self) -> None:
        wait = self.cfg.delay - (self._clock() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    # -- robots.txt ------------------------------------------------------
    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            parser = RobotFileParser()
            lines: list[str] = []
            try:
                resp = self.session.get(root + "/robots.txt", timeout=self.cfg.timeout)
                if resp.status_code == 200:
                    lines = resp.text.splitlines()
                else:
                    log.info("No usable robots.txt at %s (HTTP %s) - treating as allow-all", root, resp.status_code)
            except requests.RequestException as exc:
                log.warning("Could not read robots.txt at %s (%s) - treating as allow-all", root, exc)
            parser.parse(lines)  # empty rules == allow everything
            self._robots[root] = parser
        return self._robots[root].can_fetch(self.cfg.user_agent, url)

    # -- fetching --------------------------------------------------------
    def get(self, url: str) -> requests.Response:
        if self.cfg.respect_robots and not self._robots_allows(url):
            self.failures += 1
            raise FetchError(f"blocked by robots.txt: {url}")

        reason = "unknown"
        attempts = self.cfg.max_retries + 1
        for attempt in range(attempts):
            self._throttle()
            self.requests_made += 1
            try:
                resp = self.session.get(url, timeout=self.cfg.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                reason = f"{type(exc).__name__}: {exc}"
            except requests.RequestException as exc:  # invalid URL etc. - retrying will not help
                self.failures += 1
                raise FetchError(f"request error for {url}: {exc}") from exc
            else:
                if resp.status_code in RETRY_STATUS:
                    reason = f"HTTP {resp.status_code}"
                elif resp.status_code >= 400:
                    self.failures += 1
                    raise FetchError(f"HTTP {resp.status_code} for {url}")
                else:
                    return resp

            if attempt < attempts - 1:
                delay = self.cfg.backoff_base * (2 ** attempt)
                self.retries += 1
                log.warning("Fetch failed for %s (%s); retry %d/%d in %.1fs",
                            url, reason, attempt + 1, self.cfg.max_retries, delay)
                self._sleep(delay)

        self.failures += 1
        raise FetchError(f"giving up on {url} after {attempts} attempts ({reason})")

    def get_soup(self, url: str) -> BeautifulSoup:
        # Parse from bytes so BeautifulSoup can use the page's own <meta charset>.
        # (resp.text would guess ISO-8859-1 for these sites and turn "£" into "Â£".)
        return BeautifulSoup(self.get(url).content, "html.parser")
