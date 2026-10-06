import pytest

from processing.cleaning import (CleaningError, clean_record, clean_tags, clean_whitespace, fix_mojibake,
                                 none_if_missing, normalize_url, parse_price, parse_rating)


def test_whitespace():
    assert clean_whitespace("  a \n\t b\u00a0c  ") == "a b c"
    assert clean_whitespace(None) == ""


@pytest.mark.parametrize("v", ["", "  ", "N/A", "null", "-", None])
def test_missing_tokens(v):
    assert none_if_missing(v) is None


def test_mojibake():
    assert fix_mojibake("Â£51.77") == "£51.77"
    assert fix_mojibake("plain £5") == "plain £5"


@pytest.mark.parametrize("raw,expected", [
    ("£51.77", (51.77, "GBP")), ("Â£51.77", (51.77, "GBP")), ("$1,234.50", (1234.5, "USD")),
    ("12", (12.0, None)), (None, (None, None)), ("  ", (None, None)),
])
def test_price(raw, expected):
    assert parse_price(raw) == expected


def test_price_garbage():
    with pytest.raises(ValueError):
        parse_price("free!")


@pytest.mark.parametrize("raw,expected", [("Three", 3), ("five", 5), ("4", 4), ("3.0", 3), ("2 out of 5", 2), (None, None), ("7", 7)])
def test_rating(raw, expected):
    assert parse_rating(raw) == expected


def test_rating_garbage():
    with pytest.raises(ValueError):
        parse_rating("excellent")


def test_url():
    assert normalize_url("HTTPS://Books.ToScrape.com/a/b.html#frag") == "https://books.toscrape.com/a/b.html"
    assert normalize_url("a/b.html", base="https://x.com/c/") == "https://x.com/c/a/b.html"
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("not a url") is None
    assert normalize_url(None) is None


def test_tags():
    assert clean_tags([" Love ", "love", "", "Life  Style"]) == ["love", "life style"]
    assert clean_tags(None) == []


def test_clean_record_book_and_quote():
    book = clean_record({"source": "Books to Scrape", "source_url": "https://x.com/b", "name_or_title": "  A   Title ",
                         "price": "Â£5.00", "rating": "Four", "category": " ", "scraped_at": "t"})
    assert book["name_or_title"] == "A Title" and book["price"] == 5.0 and book["rating"] == 4
    assert book["category"] is None and book["author"] is None and book["_issues"] == []

    quote = clean_record({"source": "Quotes to Scrape", "source_url": "https://x.com/", "name_or_title": "“Hi there”",
                          "author": " Bob ", "tags": ["A", "a"]})
    assert quote["name_or_title"] == "Hi there" and quote["tags"] == ["a"] and quote["price"] is None


def test_clean_record_issues_and_drop():
    rec = clean_record({"source": "Books to Scrape", "source_url": "ftp://x", "name_or_title": "T", "price": "free", "rating": "wow"})
    assert len(rec["_issues"]) == 3 and rec["source_url"] is None
    with pytest.raises(CleaningError):
        clean_record({"source": "Books to Scrape", "name_or_title": "   "})
    with pytest.raises(CleaningError):
        clean_record("nonsense")
