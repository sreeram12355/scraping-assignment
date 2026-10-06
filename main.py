"""CLI entry point:  python main.py [--max-pages N] [--no-details] [--duplicate-mode flag] ..."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import Config
from pipeline import SCRAPERS, run_pipeline


def setup_logging(log_dir: Path, level: str) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    return log_file


def parse_args(argv=None) -> argparse.Namespace:
    d = Config()
    p = argparse.ArgumentParser(description="Scrape, clean, validate, deduplicate and consolidate two practice sites.")
    p.add_argument("--sources", nargs="+", choices=sorted(SCRAPERS), default=sorted(SCRAPERS))
    p.add_argument("--max-pages", type=int, default=None, help="limit pages per source (default: all)")
    p.add_argument("--no-details", action="store_true", help="skip detail/author pages (faster; no category/description/author info)")
    p.add_argument("--duplicate-mode", choices=["remove", "flag"], default=d.duplicate_mode)
    p.add_argument("--delay", type=float, default=d.delay, help="seconds between requests")
    p.add_argument("--timeout", type=float, default=d.timeout)
    p.add_argument("--retries", type=int, default=d.max_retries)
    p.add_argument("--backoff", type=float, default=d.backoff_base)
    p.add_argument("--no-robots", action="store_true", help="do not consult robots.txt")
    p.add_argument("--books-url", default=d.books_url)
    p.add_argument("--quotes-url", default=d.quotes_url)
    p.add_argument("--output-dir", type=Path, default=d.output_dir)
    p.add_argument("--log-dir", type=Path, default=d.log_dir)
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    log_file = setup_logging(a.log_dir, a.log_level)
    cfg = Config(
        books_url=a.books_url, quotes_url=a.quotes_url, timeout=a.timeout, max_retries=a.retries,
        backoff_base=a.backoff, delay=a.delay, respect_robots=not a.no_robots, max_pages=a.max_pages,
        fetch_details=not a.no_details, duplicate_mode=a.duplicate_mode,
        output_dir=a.output_dir, log_dir=a.log_dir,
    )
    summary = run_pipeline(cfg, a.sources)
    logging.getLogger(__name__).info("Log written to %s", log_file)
    return 0 if summary["totals"]["final_records"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
