"""Duplicate detection on normalised keys.

Key = (source, normalised title/quote text, normalised author)

Normalisation (applied to the key only - the stored values are untouched):
  Unicode NFKC -> casefold -> strip punctuation/symbols -> collapse whitespace
so " Example Book Title ", "EXAMPLE BOOK TITLE" and "Example  Book Title!" are equal.

source_url is deliberately NOT part of the key: all quotes from one page share the page URL,
and the same item can legitimately be reachable through several URLs.
Duplicates are only searched within one source; a book is never a duplicate of a quote.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Optional


def normalize_for_key(value: Optional[str]) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[^\w\s]|_", "", text)
    return re.sub(r"\s+", " ", text).strip()


def dedup_key(rec: dict) -> tuple[str, str, str]:
    return (
        rec.get("source") or "",
        normalize_for_key(rec.get("name_or_title")),
        normalize_for_key(rec.get("author")),
    )


def group_id(key: tuple) -> str:
    return hashlib.sha1("\x1f".join(key).encode("utf-8")).hexdigest()[:10]


def deduplicate(records: list[dict], mode: str = "remove"):
    """Keep the first occurrence of every key.

    mode='remove': later occurrences are dropped from the output.
    mode='flag'  : everything is kept; later occurrences get is_duplicate=True.
    In both modes every member of a multi-record group gets the same duplicate_group id.

    Returns (output_records, duplicates) - duplicates is the list of the later occurrences.
    """
    if mode not in ("remove", "flag"):
        raise ValueError(f"mode must be 'remove' or 'flag', got {mode!r}")

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        groups[dedup_key(rec)].append(rec)

    duplicates: list[dict] = []
    duplicate_ids = set()
    for key, members in groups.items():
        if len(members) < 2:
            continue
        gid = group_id(key)
        for i, rec in enumerate(members):
            rec["duplicate_group"] = gid
            if i > 0:
                rec["is_duplicate"] = True
                duplicates.append(rec)
                duplicate_ids.add(id(rec))

    output = records if mode == "flag" else [r for r in records if id(r) not in duplicate_ids]
    return output, duplicates
