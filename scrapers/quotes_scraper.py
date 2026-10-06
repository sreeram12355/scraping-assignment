"""Quotes to Scrape: quote/author/tags on listing pages; author facts on /author/<slug> pages
(fetched once per author and cached)."""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import QUOTES
from scrapers.base import BaseScraper, text_of
from scrapers.http_client import FetchError

log = logging.getLogger(__name__)


class QuotesScraper(BaseScraper):
    source_name = QUOTES

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._author_cache: dict[str, dict] = {}

    def parse_listing(self, soup: BeautifulSoup, url: str):
        items = []
        for block in soup.select("div.quote"):
            try:
                items.append(self._parse_quote(block, url))
            except Exception as exc:
                self.stats.item_parse_errors += 1
                self._record_error(f"[{self.source_name}] unparseable quote on {url}: {exc}")
        nxt = soup.select_one("li.next > a")
        next_url = urljoin(url, nxt["href"]) if nxt is not None and nxt.get("href") else None
        return items, next_url

    @staticmethod
    def _parse_quote(block, page_url: str) -> dict:
        about = block.select_one("a[href^='/author/']")
        return {
            "name_or_title": text_of(block.select_one("span.text")),
            # Quotes have no URL of their own, so the page they were found on is the source URL.
            "source_url": page_url,
            "author": text_of(block.select_one("small.author")),
            "tags": [t.get_text(strip=True) for t in block.select("div.tags a.tag")],
            "_author_url": urljoin(page_url, about["href"]) if about is not None else None,
        }

    def enrich(self, item: dict) -> None:
        author_url = item.pop("_author_url", None)
        if not author_url:
            return
        if author_url not in self._author_cache:
            soup = self.client.get_soup(author_url)   # FetchError propagates -> handled in base
            self._author_cache[author_url] = {
                "author_born_date": text_of(soup.select_one(".author-born-date")),
                "author_born_location": text_of(soup.select_one(".author-born-location")),
                "author_bio": text_of(soup.select_one(".author-description")),
            }
        item.update(self._author_cache[author_url])

    def scrape(self):
        # _author_url is only meaningful during enrichment; make sure it never leaks if details are off.
        items = super().scrape()
        for it in items:
            it.pop("_author_url", None)
        return items

    def fallback_next_url(self, url: str) -> Optional[str]:
        m = re.search(r"/page/(\d+)/?$", url)
        if m:
            return re.sub(r"/page/\d+/?$", f"/page/{int(m.group(1)) + 1}/", url)
        return urljoin(url, "/page/2/") if url.rstrip("/").count("/") <= 2 else None
