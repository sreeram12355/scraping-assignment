# Scraping, cleaning & consolidation pipeline

Collects data from two public practice sites ([Books to Scrape](https://books.toscrape.com/),
[Quotes to Scrape](https://quotes.toscrape.com/)), maps both into one schema, cleans, validates and
de-duplicates it, and writes `output/final_dataset.csv` + `output/summary_report.json`.

```
Books ─┐
       ├─> scrape ─> clean ─> validate ─> deduplicate ─> consolidate ─> CSV + JSON summary
Quotes ┘
```

## Setup
- **Python 3.10+** (developed/tested on 3.12)
- Dependencies (`requirements.txt`): `requests`, `beautifulsoup4`, `pytest` (tests only)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run
```bash
python main.py                          # full run, both sources (~5-6 min because of rate limiting + detail pages)
python main.py --max-pages 2            # quick smoke test
python main.py --no-details             # skip detail/author pages (fast; no category/description/author info)
python main.py --sources quotes         # one source only
python main.py --duplicate-mode flag    # keep duplicates, mark them instead of removing
python main.py --help                   # all options (delay, retries, backoff, timeout, output/log dirs, ...)
python -m pytest                        # run tests (no internet needed)
```
Outputs go to `output/` (`final_dataset.csv`, `summary_report.json`, plus `rejected_records.json` for
auditing) and a timestamped log to `logs/`.

## Layout
```
main.py            CLI + logging setup          pipeline.py   orchestration, CSV/JSON writing
config.py          all settings (dataclass)     models.py     common schema + constants
scrapers/          http_client.py (retry/backoff/rate-limit/robots), base.py (pagination loop),
                   books_scraper.py, quotes_scraper.py   <- the ONLY place with CSS selectors
processing/        cleaning.py, validation.py, deduplication.py   <- no HTML/network knowledge
tests/             unit tests + integration tests against a local mock of both sites
```

## Step 1 - Source observations
| | Books to Scrape | Quotes to Scrape |
|---|---|---|
| Listing | 20 books/page, 50 pages, `article.product_pod` | 10 quotes/page, `div.quote` |
| Pagination | `li.next > a`; href is **relative and inconsistent** (`catalogue/page-2.html` on page 1, `page-3.html` afterwards) | `li.next > a`, root-relative `/page/2/` |
| On listing | title (visible text is truncated - the `title` attribute is complete), price, rating (CSS class `star-rating Three`), availability, URL | quote text, author, tags, link to author page |
| Only on detail page | category (breadcrumb), description | author birth date/location/bio |
| No own URL? | every book has one | **quotes have none** - the page URL is used |
| Encoding | UTF-8 but served without a charset -> `requests.text` yields `Â£`; parsing from bytes avoids it (and `fix_mojibake` is a safety net) | |

## Pagination
`BaseScraper.scrape()` starts at the source's start URL, parses the page, reads the "next" link and
resolves it with `urljoin` against the *current* page URL (this handles the relative-link quirk). It stops
when there is no next link, on a repeated URL (loop guard) or at `--max-pages`. No page URLs are listed
manually. If a page fails after retries, the scraper tries a *guessed* next page (`page-N+1`) so one bad
page doesn't hide everything after it; after 2 consecutive failures it gives up on that source.

## Data model
One flat schema for both sources (`models.FIELDS`): `source, source_url, name_or_title, category, price,
currency, rating, author, tags, description, availability, author_born_date, author_born_location,
author_bio, scraped_at, is_duplicate, duplicate_group`.
- `name_or_title` = book title or quote text. Fields that don't apply stay **empty/null** (e.g. books
  have no author, quotes no price) - nothing is invented or defaulted.
- I added `currency`, `availability` and the three `author_*` fields beyond the suggested list so that
  information on the sites isn't thrown away. Quote's author biography is kept in `author_bio`, not in
  `description`, so `description` means one thing only.
- `tags` is a list internally and `a|b|c` in the CSV. `scraped_at` is UTC ISO-8601 per record.

## Cleaning (`processing/cleaning.py`)
Whitespace collapse (incl. non-breaking/zero-width spaces), Unicode NFC, mojibake repair, placeholder
tokens (`""`, `N/A`, `null`, `-` ...) -> `None`, price -> `float` + ISO currency from the symbol, rating
(`"Three"`/`"3"`/`"3 out of 5"`) -> number, URLs made absolute/lower-case host/no fragment (invalid -> `None`),
tags lower-cased and de-duplicated, wrapping quote marks removed from quote text. A record with no
title/text at all is dropped during cleaning ("clearly invalid"). Values that are present but unusable
(price "free", rating "Nine") are recorded as `_issues` and cause a validation rejection - they are never
silently turned into a guess.

## Validation (`processing/validation.py`)
Rejected (and counted per reason in the summary; details in `rejected_records.json`) if: source not
recognised; `source_url` missing/not http(s); title missing; `scraped_at` missing; price present but not
numeric or negative; rating outside 1-5; unparseable price/rating; book without price; quote without author.
Category/description/tags are optional (a book may have no description).

## Deduplication (`processing/deduplication.py`)
Key = `(source, normalised title/quote text, normalised author)`. Normalisation (key only - stored data
is untouched): Unicode NFKC -> casefold -> remove punctuation -> collapse whitespace, so
`"Example Book Title"`, `" Example Book Title "`, `"EXAMPLE BOOK TITLE"`, `"Example  Book Title!"` match.
- The first occurrence is kept. Default `remove` drops later ones; `--duplicate-mode flag` keeps all rows and
  sets `is_duplicate=true` on the later ones. Both modes set the same `duplicate_group` hash on all members.
  I chose *remove* as default because the task asks for one consolidated dataset, and *flag* exists because
  deletion is irreversible - use it when you want to review before dropping.
- `source_url` is **not** in the key: all quotes on a page share its URL.
- Duplicates are searched within a source only. Author is part of the key so the same quote text by two
  different people is kept.
- Limitation: matching is exact after normalisation, not fuzzy (a typo variant would not match), and two
  genuinely different books that share a title would be treated as duplicates.

## Error handling & logging
- `HttpClient`: timeout on every request, **retries with exponential backoff** (`backoff_base * 2^attempt`)
  for connection errors, timeouts and HTTP 429/5xx; other 4xx fail immediately (retrying a 404 is pointless);
  minimum delay between requests (rate limit); `robots.txt` is read and honoured (unreachable/missing = allow).
- Missing HTML elements give `None`, not exceptions. A card/quote that can't be parsed is logged and skipped.
- Failure isolation: detail/author-page failure -> keep the record with those fields empty; a failed listing
  page -> skipped (see Pagination); one source crashing never stops the other and partial results are kept.
- Logging goes to console and `logs/run_<timestamp>.log`; the summary contains pages ok/failed, retries, failures.

## Output
- `final_dataset.csv` - schema above (UTF-8, header row).
- `summary_report.json` - totals (collected, after cleaning, dropped in cleaning, rejected in validation,
  duplicates detected/removed/flagged, final & unique records, execution time), validation rejection
  reasons, per-source stats incl. field completeness (a small data-quality report), HTTP counters.
- `rejected_records.json` - every rejected record with the reasons.

## Assumptions
Prices are in the symbol shown (GBP on the real site); a rating must be 1-5; a book needs a price and a quote
needs an author; the page URL is an acceptable `source_url` for quotes; detail pages are fetched by default
because the category is only available there.

## Known limitations
- Sequential (no async/parallel) - deliberate, to stay polite; full run takes several minutes.
- No incremental scraping or checkpoint/resume; every run starts from scratch.
- Exact-after-normalisation de-duplication (no fuzzy matching).
- Selectors target these two practice sites' current HTML; a redesign would need changes in `scrapers/` only.
- **Verification note:** the automated tests run against a local mock that copies the sites' HTML structure.
  `logs/sample_run_MOCK_SITE_not_live.log` is from that mock - replace it with the log of your own live run.

## Possible production changes
Scheduler + checkpoints/incremental runs, async fetching with per-host limits, a database with upserts
instead of CSV, alerting on rejection/duplicate-rate changes, selector-health checks, fuzzy matching.

## AI usage summary
See `AI_USAGE.md`.
