import csv
import json

from main import main
from pipeline import run_pipeline
from scrapers.books_scraper import BooksScraper
from scrapers.http_client import HttpClient


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_full_pipeline_against_mock_sites(mock_sites, make_cfg):
    books_url, quotes_url = mock_sites
    cfg = make_cfg(books_url + "index.html", quotes_url)
    s = run_pipeline(cfg)

    t = s["totals"]
    assert (t["collected"], t["after_cleaning"], t["rejected_in_validation"]) == (13, 13, 3)
    assert (t["duplicates_detected"], t["duplicates_removed"], t["final_records"]) == (2, 2, 8)

    b = s["per_source"]["Books to Scrape"]
    assert (b["collected"], b["pages_ok"], b["rejected_in_validation"], b["duplicates_detected"], b["final_records"]) == (8, 3, 2, 1, 5)
    assert b["detail_fetch_failures"] == 1          # badrating_7 detail 404
    assert s["http"]["retries"] >= 1                 # the flaky 500 was retried
    q = s["per_source"]["Quotes to Scrape"]
    assert (q["collected"], q["pages_ok"], q["rejected_in_validation"], q["duplicates_detected"], q["final_records"]) == (5, 2, 1, 1, 3)

    rows = read_csv(cfg.output_dir / "final_dataset.csv")
    assert len(rows) == 8
    book = next(r for r in rows if r["name_or_title"] == "A Light in the Attic")
    assert book["price"] == "51.77" and book["currency"] == "GBP" and book["rating"] == "3"
    assert book["category"] == "Poetry" and book["author"] == "" and book["source_url"].endswith("/catalogue/a-light_1/index.html")
    # pagination quirk: page-2 relative links resolved under /catalogue/
    assert any(r["source_url"].endswith("/catalogue/sharp_4/index.html") for r in rows)
    tipping = next(r for r in rows if r["name_or_title"] == "Tipping the Velvet")
    assert tipping["category"] == "Historical Fiction"          # recovered by retry
    einstein = next(r for r in rows if r["author"] == "Albert Einstein" and "world" in r["name_or_title"])
    assert einstein["tags"] == "change|deep-thoughts" and einstein["author_born_location"] == "in Ulm, Germany"
    assert not einstein["name_or_title"].startswith("“")
    austen = next(r for r in rows if r["author"] == "Jane Austen")
    assert austen["author_born_date"] == ""                       # author page 404 -> kept, empty
    assert json.loads((cfg.output_dir / "summary_report.json").read_text())["totals"]["final_records"] == 8


def test_flag_mode_keeps_duplicates(mock_sites, make_cfg):
    books_url, quotes_url = mock_sites
    cfg = make_cfg(books_url + "index.html", quotes_url, duplicate_mode="flag")
    s = run_pipeline(cfg)
    assert s["totals"]["final_records"] == 10 and s["totals"]["duplicates_flagged"] == 2 and s["totals"]["unique_records"] == 8
    rows = read_csv(cfg.output_dir / "final_dataset.csv")
    assert sum(r["is_duplicate"] == "true" for r in rows) == 2


def test_max_pages_and_no_details(mock_sites, make_cfg):
    books_url, quotes_url = mock_sites
    cfg = make_cfg(books_url + "index.html", quotes_url, max_pages=1, fetch_details=False)
    s = run_pipeline(cfg)
    assert s["per_source"]["Books to Scrape"]["collected"] == 3
    assert s["per_source"]["Quotes to Scrape"]["collected"] == 2
    rows = read_csv(cfg.output_dir / "final_dataset.csv")
    assert all(r["category"] == "" for r in rows)


def test_one_source_down_does_not_stop_the_other(mock_sites, make_cfg):
    _, quotes_url = mock_sites
    cfg = make_cfg("http://127.0.0.1:1/", quotes_url, max_retries=1)   # nothing listens on port 1
    s = run_pipeline(cfg)
    assert s["per_source"]["Books to Scrape"]["collected"] == 0
    assert s["per_source"]["Books to Scrape"]["pages_failed"] >= 1
    assert s["per_source"]["Quotes to Scrape"]["final_records"] == 3


def test_failed_page_is_skipped_via_fallback(mock_sites, make_cfg):
    books_url, _ = mock_sites
    from tests.mock_site import books_routes, serve
    routes = books_routes()
    del routes["/catalogue/page-2.html"]                         # page 2 vanishes
    server, url = serve(routes)
    try:
        cfg = make_cfg(url + "index.html", None, fetch_details=False)
        scraper = BooksScraper(HttpClient(cfg), cfg, url + "index.html")
        items = scraper.scrape()
    finally:
        server.shutdown()
    # page 1 (3) + page 3 (2) reached through the page-N+1 fallback
    assert len(items) == 5 and scraper.stats.pages_failed == 1


def test_cli_end_to_end(mock_sites, tmp_path):
    books_url, quotes_url = mock_sites
    rc = main(["--books-url", books_url + "index.html", "--quotes-url", quotes_url, "--delay", "0", "--backoff", "0",
               "--output-dir", str(tmp_path / "o"), "--log-dir", str(tmp_path / "l")])
    assert rc == 0 and (tmp_path / "o" / "final_dataset.csv").exists()
    assert list((tmp_path / "l").glob("run_*.log"))
