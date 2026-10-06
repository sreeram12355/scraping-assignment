"""Pure, source-agnostic cleaning helpers + clean_record() which maps a raw scraped dict to the
common schema. No network or HTML knowledge lives here."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from models import FIELDS, QUOTES

MISSING_TOKENS = {"", "n/a", "na", "none", "null", "nan", "-", "--", "—", "unknown", "undefined"}
CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}
RATING_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
QUOTE_CHARS = "\"'“”‘’«»"


class CleaningError(ValueError):
    """Record is unusable (e.g. no title at all) and is dropped during cleaning."""


def fix_mojibake(text: str) -> str:
    """'Â£51.77' (UTF-8 bytes decoded as Latin-1) -> '£51.77'. Leaves normal text untouched."""
    if "Â" in text or "Ã" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return text
    return text


def clean_whitespace(value: Any) -> str:
    """Collapse all runs of whitespace (incl. non-breaking/zero-width spaces) and strip."""
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def none_if_missing(value: Any) -> Optional[str]:
    """Whitespace-clean a value; map empty / placeholder tokens to None."""
    text = clean_whitespace(value)
    return None if text.lower() in MISSING_TOKENS else text


def normalize_text(value: Any) -> Optional[str]:
    """Mojibake fix + Unicode NFC + whitespace cleanup + missing-value mapping."""
    if value is None:
        return None
    text = unicodedata.normalize("NFC", fix_mojibake(str(value)))
    return none_if_missing(text)


def strip_wrapping_quotes(text: str) -> str:
    return text.strip().strip(QUOTE_CHARS).strip()


def parse_price(value: Any) -> tuple[Optional[float], Optional[str]]:
    """'£51.77' -> (51.77, 'GBP'). Returns (None, None) for missing input; ValueError if text
    is present but contains no number."""
    text = normalize_text(value)
    if text is None:
        return None, None
    currency = next((code for sym, code in CURRENCY_SYMBOLS.items() if sym in text), None)
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"no numeric value in price {text!r}")
    return float(match.group().replace(",", "")), currency


def parse_rating(value: Any) -> Optional[float]:
    """'Three' / '3' / '3 out of 5' -> 3. Out-of-range numbers are returned as-is so that
    validation can reject them; unrecognisable text raises ValueError."""
    text = normalize_text(value)
    if text is None:
        return None
    lowered = text.lower()
    for word, number in RATING_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return number
    match = re.search(r"-?\d+(?:\.\d+)?", lowered)
    if not match:
        raise ValueError(f"unrecognised rating {text!r}")
    number = float(match.group())
    return int(number) if number.is_integer() else number


def normalize_url(value: Any, base: Optional[str] = None) -> Optional[str]:
    """Absolute http(s) URL with lower-cased scheme/host and no fragment, else None."""
    text = none_if_missing(value)
    if text is None:
        return None
    if base:
        text = urljoin(base, text)
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def clean_tags(value: Any) -> list[str]:
    """Lower-case, whitespace-clean, de-duplicate (order preserved), drop empties."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split("|")
    seen, out = set(), []
    for tag in value:
        cleaned = normalize_text(tag)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned.lower())
    return out


def clean_record(raw: dict) -> dict:
    """Raw scraped dict -> cleaned dict with exactly the FIELDS keys (+ '_issues').

    '_issues' lists values that were present but unusable (e.g. unparseable price); the
    validation step turns them into rejections. Raises CleaningError if there is no title.
    """
    if not isinstance(raw, dict):
        raise CleaningError(f"record is not a mapping: {type(raw).__name__}")

    issues: list[str] = []
    rec: dict[str, Any] = {f: None for f in FIELDS}
    rec["is_duplicate"] = False

    rec["source"] = normalize_text(raw.get("source"))
    rec["source_url"] = normalize_url(raw.get("source_url"))
    if raw.get("source_url") and rec["source_url"] is None:
        issues.append(f"invalid source_url {raw.get('source_url')!r}")

    title = normalize_text(raw.get("name_or_title"))
    if title and rec["source"] == QUOTES:
        title = none_if_missing(strip_wrapping_quotes(title))
    if not title:
        raise CleaningError("missing name_or_title")
    rec["name_or_title"] = title

    rec["category"] = normalize_text(raw.get("category"))
    rec["author"] = normalize_text(raw.get("author"))
    rec["description"] = normalize_text(raw.get("description"))
    rec["availability"] = normalize_text(raw.get("availability"))
    rec["author_born_date"] = normalize_text(raw.get("author_born_date"))
    rec["author_born_location"] = normalize_text(raw.get("author_born_location"))
    rec["author_bio"] = normalize_text(raw.get("author_bio"))
    rec["tags"] = clean_tags(raw.get("tags"))
    rec["scraped_at"] = none_if_missing(raw.get("scraped_at"))

    try:
        rec["price"], rec["currency"] = parse_price(raw.get("price"))
    except ValueError as exc:
        issues.append(str(exc))
    try:
        rec["rating"] = parse_rating(raw.get("rating"))
    except ValueError as exc:
        issues.append(str(exc))

    rec["_issues"] = issues
    return rec
