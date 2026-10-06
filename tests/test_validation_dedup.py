import pytest

from processing.cleaning import clean_record
from processing.deduplication import deduplicate, normalize_for_key
from processing.validation import rejection_reasons, validate_record, validate_records


def book(**kw):
    raw = {"source": "Books to Scrape", "source_url": "https://x.com/b1", "name_or_title": "Title", "price": "£5.00",
           "rating": "Three", "scraped_at": "2026-01-01T00:00:00+00:00"}
    raw.update(kw)
    return clean_record(raw)


def quote(**kw):
    raw = {"source": "Quotes to Scrape", "source_url": "https://x.com/", "name_or_title": "“Q”", "author": "A",
           "scraped_at": "2026-01-01T00:00:00+00:00"}
    raw.update(kw)
    return clean_record(raw)


def test_valid_records():
    assert validate_record(book()) == []
    assert validate_record(quote()) == []


@pytest.mark.parametrize("rec,needle", [
    (book(source="Mystery Shop"), "unrecognised source"),
    (book(source_url=None), "missing source_url"),
    (book(price=None), "missing price"),
    (book(price="-3"), "negative price"),
    (book(rating="9"), "outside 1-5"),
    (book(rating="0"), "outside 1-5"),
    (book(price="free"), "no numeric value"),
    (book(scraped_at=None), "missing scraped_at"),
    (quote(author=None), "missing author"),
])
def test_invalid_records(rec, needle):
    assert any(needle in e for e in validate_record(rec)), validate_record(rec)


def test_validate_records_split_and_reasons():
    valid, rejected = validate_records([book(), book(price=None), book(rating="9"), quote(author=None)])
    assert len(valid) == 1 and len(rejected) == 3
    assert sum(rejection_reasons(rejected).values()) == 3


def test_normalize_for_key():
    variants = ["Example Book Title", " Example Book Title ", "EXAMPLE BOOK TITLE", "Example  Book Title!"]
    assert len({normalize_for_key(v) for v in variants}) == 1
    assert normalize_for_key(None) == ""


def test_dedup_remove_and_flag():
    recs = [book(name_or_title="Example Book Title", source_url="https://x.com/1"),
            book(name_or_title=" EXAMPLE   BOOK TITLE ", source_url="https://x.com/2"),
            book(name_or_title="Other"),
            # same text but different source => NOT a duplicate
            quote(name_or_title="Example Book Title", author=None) | {"author": "Z"}]
    out, dups = deduplicate([dict(r) for r in recs], "remove")
    assert len(out) == 3 and len(dups) == 1 and dups[0]["source_url"] == "https://x.com/2"

    out, dups = deduplicate([dict(r) for r in recs], "flag")
    assert len(out) == 4 and len(dups) == 1
    flagged = [r for r in out if r["is_duplicate"]]
    assert len(flagged) == 1 and flagged[0]["duplicate_group"] == out[0]["duplicate_group"]


def test_same_quote_different_authors_not_duplicates():
    out, dups = deduplicate([quote(author="A"), quote(author="B")])
    assert len(out) == 2 and not dups


def test_dedup_bad_mode():
    with pytest.raises(ValueError):
        deduplicate([], "delete")
