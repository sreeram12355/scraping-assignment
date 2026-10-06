import pytest
import requests

from config import Config
from scrapers.http_client import FetchError, HttpClient


class Resp:
    def __init__(self, status=200, content=b"<html></html>", text=""):
        self.status_code, self.content, self.text = status, content, text


class FakeSession:
    def __init__(self, script):
        self.script, self.headers, self.calls = list(script), {}, 0

    def get(self, url, timeout=None):
        if url.endswith("/robots.txt"):
            return Resp(404)
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(script, **kw):
    sleeps = []
    cfg = Config(delay=0, backoff_base=1, max_retries=3, **kw)
    return HttpClient(cfg, session=FakeSession(script), sleep=sleeps.append), sleeps


def test_retry_then_success_with_exponential_backoff():
    c, sleeps = client([requests.Timeout("t"), requests.ConnectionError("c"), Resp(503), Resp(200)])
    assert c.get("http://x/a").status_code == 200
    assert [s for s in sleeps if s] == [1, 2, 4] and c.retries == 3


def test_gives_up_after_max_retries():
    c, _ = client([requests.Timeout("t")] * 4)
    with pytest.raises(FetchError, match="giving up"):
        c.get("http://x/a")
    assert c.failures == 1 and c.session.calls == 4


def test_404_not_retried():
    c, _ = client([Resp(404)])
    with pytest.raises(FetchError, match="HTTP 404"):
        c.get("http://x/a")
    assert c.session.calls == 1


def test_robots_disallow():
    class S(FakeSession):
        def get(self, url, timeout=None):
            if url.endswith("/robots.txt"):
                return Resp(200, text="User-agent: *\nDisallow: /private")
            return super().get(url, timeout)
    cfg = Config(delay=0)
    c = HttpClient(cfg, session=S([Resp(200)]), sleep=lambda s: None)
    assert c.get("http://x/public").status_code == 200
    with pytest.raises(FetchError, match="robots"):
        c.get("http://x/private/page")
