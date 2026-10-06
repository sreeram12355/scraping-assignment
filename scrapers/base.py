"""Shared pagination / error-isolation loop. Subclasses only hold source-specific parsing."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from config import Config
from scrapers.http_client import FetchError, HttpClient

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_PAGE_FAILURES = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text_of(node) -> Optional[str]:
    """Text of a BeautifulSoup node, or None when the element is missing."""
    return node.get_text(" ", strip=True) if node is not None else None


@dataclass
class ScrapeStats:
    pages_attempted: int = 0
    pages_ok: int = 0
    pages_failed: int = 0
    items_parsed: int = 0
    item_parse_errors: int = 0
    detail_fetch_failures: int = 0
    errors: list = field(default_factory=list)


class BaseScraper(ABC):
    source_name: str = ""

    def __init__(self, client: HttpClient, cfg: Config, start_url: str):
        self.client = client
        self.cfg = cfg
        self.start_url = start_url
        self.stats = ScrapeStats()
        self.items: list[dict] = []   # kept on the instance so partial results survive a crash

    # -- to be implemented per source -------------------------------------
    @abstractmethod
    def parse_listing(self, soup: BeautifulSoup, url: str) -> tuple[list[dict], Optional[str]]:
        """Return (raw items on this page, absolute URL of the next page or None)."""

    def enrich(self, item: dict) -> None:
        """Optional: fetch extra data (detail page etc.) and update the item in place."""

    def fallback_next_url(self, url: str) -> Optional[str]:
        """Guess the next page URL when a page failed and its 'next' link is unknown."""
        return None

    # -- shared loop ------------------------------------------------------
    def _record_error(self, message: str) -> None:
        log.error(message)
        self.stats.errors.append(message)

    def scrape(self) -> list[dict]:
        url: Optional[str] = self.start_url
        seen: set[str] = set()
        consecutive_failures = 0
        log.info("[%s] starting at %s", self.source_name, url)

        while url and url not in seen:
            if self.cfg.max_pages is not None and self.stats.pages_attempted >= self.cfg.max_pages:
                log.info("[%s] max_pages=%d reached", self.source_name, self.cfg.max_pages)
                break
            seen.add(url)
            self.stats.pages_attempted += 1
            try:
                soup = self.client.get_soup(url)
                page_items, next_url = self.parse_listing(soup, url)
            except Exception as exc:  # FetchError or an unexpected parsing crash: isolate the page
                self.stats.pages_failed += 1
                consecutive_failures += 1
                self._record_error(f"[{self.source_name}] page failed: {url} ({type(exc).__name__}: {exc})")
                if consecutive_failures >= MAX_CONSECUTIVE_PAGE_FAILURES:
                    self._record_error(f"[{self.source_name}] {consecutive_failures} consecutive page failures - stopping this source")
                    break
                url = self.fallback_next_url(url)
                continue

            consecutive_failures = 0
            self.stats.pages_ok += 1
            if not page_items:
                log.warning("[%s] no items found on %s", self.source_name, url)
            for item in page_items:
                item["source"] = self.source_name
                item["scraped_at"] = utc_now_iso()
                if self.cfg.fetch_details:
                    try:
                        self.enrich(item)
                    except FetchError as exc:
                        self.stats.detail_fetch_failures += 1
                        log.warning("[%s] detail fetch failed, keeping partial record: %s", self.source_name, exc)
                    except Exception as exc:
                        self.stats.detail_fetch_failures += 1
                        log.warning("[%s] detail parsing failed (%s: %s), keeping partial record",
                                    self.source_name, type(exc).__name__, exc)
                self.items.append(item)
            self.stats.items_parsed += len(page_items)
            log.info("[%s] %s -> %d items (total %d)", self.source_name, url, len(page_items), len(self.items))
            url = next_url

        log.info("[%s] finished: %d items, %d/%d pages ok", self.source_name,
                 len(self.items), self.stats.pages_ok, self.stats.pages_attempted)
        return self.items
