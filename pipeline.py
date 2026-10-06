"""Orchestration: scrape -> clean -> validate -> deduplicate -> consolidate -> write."""
from __future__ import annotations

import csv
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from config import Config
from models import FIELDS
from processing.cleaning import CleaningError, clean_record
from processing.deduplication import deduplicate
from processing.validation import rejection_reasons, validate_records
from scrapers.books_scraper import BooksScraper
from scrapers.http_client import HttpClient
from scrapers.quotes_scraper import QuotesScraper

log = logging.getLogger(__name__)

SCRAPERS = {"books": (BooksScraper, "books_url"), "quotes": (QuotesScraper, "quotes_url")}


def _csv_value(field: str, value):
    if value is None:
        return ""
    if field == "tags":
        return "|".join(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(records: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow({f: _csv_value(f, rec.get(f)) for f in FIELDS})


def _completeness(records: list[dict]) -> dict:
    """Share of non-empty values per field - a small data-quality report."""
    if not records:
        return {}
    n = len(records)
    return {f: round(sum(1 for r in records if r.get(f) not in (None, "", [])) / n, 3) for f in FIELDS}


def run_pipeline(cfg: Config, sources=("books", "quotes")) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    client = HttpClient(cfg)

    per_source: dict[str, dict] = {}
    cleaned: list[dict] = []
    cleaning_rejected: list[dict] = []

    for key in sources:
        scraper_cls, url_attr = SCRAPERS[key]
        scraper = scraper_cls(client, cfg, getattr(cfg, url_attr))
        fatal = None
        try:
            scraper.scrape()
        except Exception as exc:  # one source must never take down the other
            fatal = f"{type(exc).__name__}: {exc}"
            log.exception("[%s] scraper crashed - continuing with %d partial records",
                          scraper.source_name, len(scraper.items))

        n_clean = 0
        for raw in scraper.items:
            try:
                cleaned.append(clean_record(raw))
                n_clean += 1
            except CleaningError as exc:
                cleaning_rejected.append({"raw": raw, "error": str(exc)})
                log.warning("[%s] dropped during cleaning (%s): %s", scraper.source_name, exc, raw.get("source_url"))

        s = scraper.stats
        per_source[scraper.source_name] = {
            "collected": len(scraper.items),
            "after_cleaning": n_clean,
            "dropped_in_cleaning": len(scraper.items) - n_clean,
            "pages_attempted": s.pages_attempted,
            "pages_ok": s.pages_ok,
            "pages_failed": s.pages_failed,
            "item_parse_errors": s.item_parse_errors,
            "detail_fetch_failures": s.detail_fetch_failures,
            "scraper_crash": fatal,
            "errors": s.errors[:50],
        }

    valid, rejected = validate_records(cleaned)
    for item in rejected:
        log.warning("Rejected by validation: %s | %s", item["errors"], item["record"].get("source_url"))

    final, duplicates = deduplicate(valid, cfg.duplicate_mode)

    # per-source counts
    val_rej = Counter(i["record"].get("source") for i in rejected)
    dup = Counter(r.get("source") for r in duplicates)
    final_count = Counter(r.get("source") for r in final)
    for name, stats in per_source.items():
        stats["rejected_in_validation"] = val_rej.get(name, 0)
        stats["duplicates_detected"] = dup.get(name, 0)
        stats["final_records"] = final_count.get(name, 0)
        stats["field_completeness"] = _completeness([r for r in final if r.get("source") == name])

    elapsed = time.perf_counter() - t0
    removed = len(duplicates) if cfg.duplicate_mode == "remove" else 0
    flagged = len(duplicates) if cfg.duplicate_mode == "flag" else 0
    summary = {
        "run": {
            "started_at": started.replace(microsecond=0).isoformat(),
            "execution_time_seconds": round(elapsed, 2),
            "sources": list(sources),
            "duplicate_mode": cfg.duplicate_mode,
            "max_pages": cfg.max_pages,
            "fetch_details": cfg.fetch_details,
        },
        "totals": {
            "collected": sum(s["collected"] for s in per_source.values()),
            "after_cleaning": len(cleaned),
            "dropped_in_cleaning": len(cleaning_rejected),
            "rejected_in_validation": len(rejected),
            "duplicates_detected": len(duplicates),
            "duplicates_removed": removed,
            "duplicates_flagged": flagged,
            "final_records": len(final),
            "unique_records": len(final) - flagged,
        },
        "validation_rejection_reasons": rejection_reasons(rejected),
        "per_source": per_source,
        "http": {"requests_made": client.requests_made, "retries": client.retries,
                 "failed_urls": client.failures},
    }

    write_csv(final, cfg.output_dir / "final_dataset.csv")
    (cfg.output_dir / "summary_report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    # Extra transparency artefacts (not required, but make the counts auditable)
    (cfg.output_dir / "rejected_records.json").write_text(json.dumps(
        [{"errors": i["errors"], "record": {k: v for k, v in i["record"].items() if k != "_issues"}} for i in rejected]
        + [{"errors": [i["error"]], "record": i["raw"]} for i in cleaning_rejected],
        indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("Done in %.1fs: %s", elapsed, summary["totals"])
    return summary
