import pytest

from config import Config
from tests.mock_site import books_routes, quotes_routes, serve


@pytest.fixture
def mock_sites():
    s1, books_url = serve(books_routes())
    s2, quotes_url = serve(quotes_routes())
    yield books_url, quotes_url
    s1.shutdown()
    s2.shutdown()


@pytest.fixture
def make_cfg(tmp_path):
    def _make(books_url=None, quotes_url=None, **kw):
        base = dict(delay=0, backoff_base=0, max_retries=2, timeout=5, output_dir=tmp_path / "out", log_dir=tmp_path / "logs")
        base.update(kw)
        return Config(books_url=books_url or "http://127.0.0.1:1/", quotes_url=quotes_url or "http://127.0.0.1:1/", **base)
    return _make
