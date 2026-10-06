"""Books to Scrape: listing pages hold title/price/rating/availability; category and
description only exist on each book's detail page."""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import BOOKS
from scrapers.base import BaseScraper, text_of

log = logging.getLogger(__name__)


class BooksScraper(BaseScraper):
    source_name = BOOKS

    def parse_listing(self, soup: BeautifulSoup, url: str):
        items = []
        for card in soup.select("article.product_pod"):
            try:
                items.append(self._parse_card(card, url))
            except Exception as exc:
                self.stats.item_parse_errors += 1
                self._record_error(f"[{self.source_name}] unparseable product card on {url}: {exc}")
        nxt = soup.select_one("li.next > a")
        next_url = urljoin(url, nxt["href"]) if nxt is not None and nxt.get("href") else None
        return items, next_url

    @staticmethod
    def _parse_card(card, page_url: str) -> dict:
        link = card.select_one("h3 a")
        # The visible text is truncated ("A Light in the ..."); the title attribute is complete.
        title = (link.get("title") if link is not None else None) or text_of(link)
        href = link.get("href") if link is not None else None
        rating_node = card.select_one("p.star-rating")
        rating_words = [c for c in (rating_node.get("class", []) if rating_node else []) if c != "star-rating"]
        return {
            "name_or_title": title,
            "source_url": urljoin(page_url, href) if href else None,
            "price": text_of(card.select_one("p.price_color")),
            "rating": rating_words[0] if rating_words else None,
            "availability": text_of(card.select_one("p.availability")),
        }

    def enrich(self, item: dict) -> None:
        url = item.get("source_url")
        if not url:
            return
        soup = self.client.get_soup(url)
        crumbs = soup.select("ul.breadcrumb li")      # Home > Books > <Category> > <Title>
        if len(crumbs) >= 3:
            item["category"] = text_of(crumbs[2].find("a")) or text_of(crumbs[2])
        desc_anchor = soup.select_one("#product_description")
        if desc_anchor is not None:
            item["description"] = text_of(desc_anchor.find_next_sibling("p"))

    def fallback_next_url(self, url: str) -> Optional[str]:
        # Real site: .../index.html -> .../catalogue/page-2.html -> page-3.html ...
        m = re.search(r"page-(\d+)\.html$", url)
        if m:
            return re.sub(r"page-\d+\.html$", f"page-{int(m.group(1)) + 1}.html", url)
        if url.rstrip("/").endswith(("index.html", "toscrape.com")) or url.endswith("/"):
            return urljoin(url, "catalogue/page-2.html")
        return None
