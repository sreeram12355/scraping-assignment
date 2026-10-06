"""Common output schema shared by both sources.

Fields that do not apply to a source stay None (empty in the CSV) - nothing is invented.
"""
from __future__ import annotations

BOOKS = "Books to Scrape"
QUOTES = "Quotes to Scrape"
KNOWN_SOURCES = {BOOKS, QUOTES}

# Column order of final_dataset.csv
FIELDS = [
    "source",
    "source_url",
    "name_or_title",      # book title / quote text
    "category",           # books only
    "price",              # books only, float
    "currency",           # books only, ISO code derived from the symbol
    "rating",             # books only, int 1-5
    "author",             # quotes only
    "tags",               # quotes only, list -> "a|b|c" in CSV
    "description",        # books only (product description)
    "availability",       # books only
    "author_born_date",   # quotes only (from author page)
    "author_born_location",
    "author_bio",
    "scraped_at",         # ISO-8601 UTC
    "is_duplicate",       # True for rows flagged/removed as duplicates
    "duplicate_group",    # short hash shared by all members of a duplicate group
]

RATING_MIN, RATING_MAX = 1, 5
