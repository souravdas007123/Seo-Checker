"""Runner ka event flow, fake fetcher ke saath. httpx install na ho to usse stub kar dete hain."""
import asyncio
import sys
import types

try:
    import httpx  # noqa: F401
except ImportError:  # sandbox jahan pip allowed nahi
    stub = types.ModuleType("httpx")
    stub.AsyncClient = object
    stub.TimeoutException = stub.HTTPError = Exception
    sys.modules["httpx"] = stub

from scanner.engine import runner  # noqa: E402
from scanner.engine.types import FetchResult  # noqa: E402

HTML = ("<!doctype html><html lang='en'><head><title>Handmade Soap Online | Example Store</title>"
        "<meta name='viewport' content='width=device-width'></head><body><h1>Soap</h1><a href='/about'>About us</a><p>" + "word " * 200 + "</p></body></html>")


class FakeFetcher:
    calls = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def fetch(self, url, max_bytes=0, ua=None, method="GET"):
        FakeFetcher.calls.append((url, ua))
        if url.endswith("/robots.txt") or url.endswith("/sitemap.xml") or url.endswith("/llms.txt"):
            return FetchResult(url=url, final_url=url, status=404, text="nf", chain=[(url, 404)])
        return FetchResult(url=url, final_url=url, status=200, text=HTML, size=len(HTML), chain=[(url, 200)], elapsed=0.3)


async def collect(url):
    return [ev async for ev in runner.run_scan(url)]


def test_event_order_and_final_payload(monkeypatch):
    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    events = asyncio.run(collect("example.com"))
    types_ = [e["type"] for e in events]
    assert types_[0] == "progress" and types_[1] == "meta" and types_[-1] == "done"
    n_checks = len(runner.ALL_CHECKS)
    assert types_.count("finding") == n_checks  # har check ne kam se kam ek finding di
    done = events[-1]
    assert 0 <= done["score"] <= 100 and len(done["findings"]) >= n_checks
    prios = [f["priority"] for f in done["findings"]]
    assert prios == sorted(prios, reverse=True)  # final list priority order mein
    assert all("effort_label" in f for f in done["findings"])


def test_one_crashing_check_does_not_break_scan(monkeypatch):
    async def boom(ctx):
        raise RuntimeError("bug")

    boom.__name__ = "check_boom"
    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    monkeypatch.setattr(runner, "ALL_CHECKS", [*runner.ALL_CHECKS, boom])
    events = asyncio.run(collect("https://example.com"))
    done = events[-1]
    assert done["type"] == "done"
    crashed = [f for f in done["findings"] if f["check_id"] == "boom"][0]
    assert crashed["status"] == "unverified"


def test_bad_scheme_errors_without_fetching(monkeypatch):
    # Private IP/DNS ka block fetcher layer par hota hai (tests/test_engine.py mein covered).
    # Runner level par bad scheme/port wale inputs bina fetch ke ruk jaate hain.
    FakeFetcher.calls = []
    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    events = asyncio.run(collect("ftp://example.com"))
    assert events == [{"type": "error", "message": "Sirf http:// ya https:// URL allowed hai."}]
    assert FakeFetcher.calls == []


def test_waf_block_reports_error_not_findings(monkeypatch):
    class Blocked(FakeFetcher):
        async def fetch(self, url, max_bytes=0, ua=None):
            FakeFetcher.calls.append((url, ua))
            return FetchResult(url=url, final_url=url, status=403, text="denied", chain=[(url, 403)])

    FakeFetcher.calls = []
    monkeypatch.setattr(runner, "Fetcher", Blocked)
    events = asyncio.run(collect("https://example.com"))
    assert events[-1]["type"] == "error" and "403" in events[-1]["message"]
    assert not any(e["type"] == "finding" for e in events)
    assert len(FakeFetcher.calls) == 2 and FakeFetcher.calls[1][1] == runner.BROWSER_UA  # retry hua


async def collect_deep(url):
    return [ev async for ev in runner.run_scan(url, deep=True, max_pages=5)]


def test_deep_scan_adds_site_findings_and_pages(monkeypatch):
    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    events = asyncio.run(collect_deep("https://example.com"))
    done = events[-1]
    assert done["type"] == "done"
    site = [f for f in done["findings"] if f["category"] == "site"]
    assert any(f["check_id"] == "site_summary" for f in site) and any(f["check_id"] == "site_broken_links" for f in site)
    assert {p["url"] for p in done["pages"]} >= {"https://example.com/", "https://example.com/about"}
    live_site = [e for e in events if e["type"] == "finding" and e["finding"]["category"] == "site"]
    assert len(live_site) == len(site)  # live stream aur final list barabar
    assert [e for e in events if e["type"] == "progress" and "crawl" in e["message"].lower()]


def test_normal_scan_has_no_site_findings_and_empty_pages(monkeypatch):
    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    done = asyncio.run(collect("https://example.com"))[-1]
    assert done["pages"] == [] and not [f for f in done["findings"] if f["category"] == "site"]


def test_crawl_crash_does_not_lose_single_page_report(monkeypatch):
    async def boom(ctx, max_pages=25):
        raise RuntimeError("bug")
        yield  # pragma: no cover

    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    monkeypatch.setattr(runner, "crawl_site", boom)
    done = asyncio.run(collect_deep("https://example.com"))[-1]
    assert done["type"] == "done"
    assert [f for f in done["findings"] if f["check_id"] == "site_crawl"][0]["status"] == "unverified"
