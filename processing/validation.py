"""Record-level validation. Returns human-readable reasons instead of raising, so every
rejection can be counted and reported."""
from __future__ import annotations

import math
from collections import Counter
from urllib.parse import urlsplit

from models import BOOKS, KNOWN_SOURCES, QUOTES, RATING_MAX, RATING_MIN


def validate_record(rec: dict) -> list[str]:
    errors: list[str] = list(rec.get("_issues") or [])

    source = rec.get("source")
    if source not in KNOWN_SOURCES:
        errors.append(f"unrecognised source {source!r}")

    url = rec.get("source_url")
    if not url:
        errors.append("missing source_url")
    else:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            errors.append(f"invalid source_url {url!r}")

    if not rec.get("name_or_title"):
        errors.append("missing name_or_title")
    if not rec.get("scraped_at"):
        errors.append("missing scraped_at")

    price = rec.get("price")
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or math.isnan(price):
            errors.append(f"price is not numeric: {price!r}")
        elif price < 0:
            errors.append(f"negative price: {price}")

    rating = rec.get("rating")
    if rating is not None and not (RATING_MIN <= rating <= RATING_MAX):
        errors.append(f"rating {rating} outside {RATING_MIN}-{RATING_MAX}")

    if source == BOOKS and price is None and not any("price" in e for e in errors):
        errors.append("missing price (required for books)")
    if source == QUOTES and not rec.get("author"):
        errors.append("missing author (required for quotes)")

    return errors


def validate_records(records: list[dict]):
    """Split into (valid, rejected). rejected items are {'record': ..., 'errors': [...]}."""
    valid, rejected = [], []
    for rec in records:
        errors = validate_record(rec)
        if errors:
            rejected.append({"record": rec, "errors": errors})
        else:
            valid.append(rec)
    return valid, rejected


def rejection_reasons(rejected: list[dict]) -> dict[str, int]:
    """Aggregate rejection reasons (numbers in messages are generalised)."""
    import re
    counts: Counter = Counter()
    for item in rejected:
        for err in item["errors"]:
            counts[re.sub(r"'[^']*'|-?\d+(\.\d+)?", "<value>", err)] += 1
    return dict(counts)
