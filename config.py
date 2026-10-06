"""Central configuration. Every field can be overridden from the CLI (see main.py)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    books_url: str = "https://books.toscrape.com/"
    quotes_url: str = "https://quotes.toscrape.com/"

    # HTTP behaviour
    timeout: float = 15.0            # seconds per request
    max_retries: int = 3             # retries after the first attempt
    backoff_base: float = 1.0        # sleep = backoff_base * 2**attempt
    delay: float = 0.25              # minimum seconds between requests (rate limit)
    respect_robots: bool = True
    user_agent: str = "scraping-assignment/1.0 (educational practice scraper)"

    # Scope
    max_pages: Optional[int] = None  # None = follow pagination to the end
    fetch_details: bool = True       # books: detail page (category, description); quotes: author page

    # Processing
    duplicate_mode: str = "remove"   # "remove" or "flag"

    # Output
    output_dir: Path = Path("output")
    log_dir: Path = Path("logs")
