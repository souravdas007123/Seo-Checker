import asyncio
import sys
import types

try:
    import httpx  # noqa: F401
except ImportError:
    stub = types.ModuleType("httpx")
    stub.AsyncClient = object
    stub.TimeoutException = stub.HTTPError = Exception
    sys.modules["httpx"] = stub

import pytest  # noqa: E402

from scanner.engine import crawl  # noqa: E402
from scanner.engine.context import Ctx  # noqa: E402
from scanner.engine.diff import diff_scans  # noqa: E402
from scanner.engine.page import Page  # noqa: E402
from scanner.engine.robots import allowed, parse_robots, rules_for  # noqa: E402
from scanner.engine.types import FetchResult  # noqa: E402

O = "https://site.test"


def page(title="A decent page title", desc="d" * 80, h1="Heading", links=(), words=200):
    head = f"<title>{title}</title>" if title else ""
    if desc:
        head += f'<meta name="description" content="{desc}">'
    body = (f"<h1>{h1}</h1>" if h1 else "") + "".join(f'<a href="{u}">link text</a>' for u in links)
    body += "<p>" + "word " * words + "</p>"
    return 200, f"<!doctype html><html><head>{head}</head><body>{body}</body></html>", "text/html"


class FakeSite:
    """spec[url] = (status, text, ctype[, final_url]) | callable(method) -> tuple | 'DNS' | 'TIMEOUT'"""

    def __init__(self, spec):
        self.spec = spec
        self.calls = []

    async def fetch(self, url, max_bytes=0, ua=None, method="GET"):
        self.calls.append((method, url))
        v = self.spec.get(url, (404, "not found", "text/html"))
        if callable(v):
            v = v(method)
        if v == "DNS":
            return FetchResult(url=url, error="dns", error_kind="dns")
        if v == "TIMEOUT":
            return FetchResult(url=url, error="timeout", error_kind="timeout")
        status, text, ctype, *rest = v
        final = rest[0] if rest else url
        chain = [(url, 301), (final, status)] if final != url else [(url, status)]
        return FetchResult(url=url, final_url=final, status=status, text=text, size=len(text),
                           headers={"content-type": ctype}, chain=chain, elapsed=0.1)


def make(spec, start=O + "/"):
    site = FakeSite(spec)
    status, text, ctype = spec[start][:3]
    res = FetchResult(url=start, final_url=start, status=status, text=text, size=len(text),
                      headers={"content-type": ctype}, chain=[(start, status)])
    return site, Ctx(Page(res), site)


def run_crawl(spec, **kw):
    site, ctx = make(spec)

    async def go():
        evs = [e async for e in crawl.crawl_site(ctx, **kw)]
        await ctx.close()
        return evs

    evs = asyncio.run(go())
    final = evs[-1]
    assert final["type"] == "site"
    return site, {f.check_id: f for f in final["findings"]}, final["pages"]


def big_site():
    return {
        O + "/": page("Home page title for the site", links=[
            "/a", "/b", "/missing", "/private/x", "/redir", "http://ext.test/ok", "http://ext.test/gone",
            "http://blocked.test/", "http://nodns.test/", "http://slow.test/", "/files/report.pdf"]),
        O + "/a": page("Same title here", desc="", words=50),
        O + "/b": page("Same title here"),
        O + "/missing": (404, "nf", "text/html"),
        O + "/private/x": page("secret page title here"),
        O + "/redir": (200, page("Redirected target page")[1], "text/html", O + "/b2"),
        O + "/files/report.pdf": (200, "%PDF", "application/pdf"),
        O + "/robots.txt": (200, "User-agent: *\nDisallow: /private/", "text/plain"),
        "http://ext.test/ok": (200, "ok", "text/html"),
        "http://ext.test/gone": (404, "gone", "text/html"),
        "http://blocked.test/": (403, "denied", "text/html"),
        "http://nodns.test/": "DNS",
        "http://slow.test/": "TIMEOUT",
    }


def test_full_crawl_findings():
    site, f, pages = run_crawl(big_site())
    fetched = [u for _, u in site.calls]

    assert O + "/private/x" not in fetched  # robots Disallow respect hua

    assert f["site_duplicate_titles"].status == "warn"
    assert "/a" in f["site_duplicate_titles"].evidence and "/b" in f["site_duplicate_titles"].evidence
    assert f["site_missing_descriptions"].status == "warn" and "/a" in f["site_missing_descriptions"].evidence
    assert f["site_thin_pages"].status == "warn" and "/a" in f["site_thin_pages"].evidence
    assert f["site_missing_titles"].status == "pass"

    bl = f["site_broken_links"]
    assert bl.status == "fail"  # internal broken hai
    assert O + "/missing" in bl.evidence and "ext.test/gone" in bl.evidence and "nodns.test" in bl.evidence
    assert "mila: " + O + "/" in bl.evidence  # kis page par mila
    assert "blocked.test" not in bl.evidence and "slow.test" not in bl.evidence  # bot-block/timeout != broken
    assert "ext.test/ok" not in bl.evidence

    un = f["site_unverified_links"]
    assert un.status == "unverified" and "blocked.test" in un.evidence and "slow.test" in un.evidence

    assert f["site_internal_redirects"].status == "warn" and "/redir" in f["site_internal_redirects"].evidence
    pdf = O + "/files/report.pdf"  # pdf page ki tarah crawl nahi hota, sirf HEAD se link-check
    assert ("HEAD", pdf) in site.calls and ("GET", pdf) not in site.calls

    by_url = {p["url"]: p for p in pages}
    assert "no description" in by_url[O + "/a"]["issues"] and "duplicate title" in by_url[O + "/a"]["issues"]
    assert "broken" in by_url[O + "/missing"]["issues"]
    assert f["site_summary"].status == "info" and "poori crawl nahi" not in f["site_summary"].message


def test_pdf_not_crawled_as_page():
    site, f, pages = run_crawl(big_site())
    assert O + "/files/report.pdf" not in {p["url"] for p in pages}


def test_truncation_is_reported_honestly():
    site, f, pages = run_crawl(big_site(), max_pages=2)
    assert len(pages) == 2
    assert "poori crawl nahi hui" in f["site_summary"].message and "2 pages ki limit" in f["site_summary"].message


def test_sitemap_seeds_unlinked_pages_and_flags_broken_entries():
    spec = {
        O + "/": page("Home page title for the site"),
        O + "/robots.txt": (200, f"User-agent: *\nAllow: /\nSitemap: {O}/sm.xml", "text/plain"),
        O + "/sm.xml": (200, f"<?xml version='1.0'?><urlset xmlns='x'><url><loc>{O}/s1</loc></url>"
                              f"<url><loc>{O}/s2</loc></url><url><loc>{O}/s3</loc></url>"
                              "<url><loc>https://other.test/zz</loc></url></urlset>", "application/xml"),
        O + "/s1": page("Seeded page one title"),
        O + "/s2": page("Seeded page two title"),
        O + "/s3": (404, "gone", "text/html"),
    }
    site, f, pages = run_crawl(spec)
    urls = {p["url"] for p in pages}
    assert {O + "/s1", O + "/s2"} <= urls
    assert "https://other.test/zz" not in urls  # doosre domain ka sitemap URL ignore
    assert f["site_broken_links"].status == "fail" and "mila: sitemap.xml" in f["site_broken_links"].evidence


def test_single_page_site_makes_no_duplicate_claims():
    _, f, _ = run_crawl({O + "/": page("Only page on this site here")})
    assert "site_duplicate_titles" not in f and "site_missing_titles" not in f
    assert f["site_broken_links"].status == "pass"


# ---------------------------------------------------------------- link checker
def test_check_link_head_405_falls_back_to_get():
    site = FakeSite({"http://x.test/": lambda m: (405, "", "text/html") if m == "HEAD" else (200, "ok", "text/html")})
    assert asyncio.run(crawl.check_link(site, "http://x.test/"))[0] == "ok"


def test_check_link_head_404_but_get_200_is_ok():
    site = FakeSite({"http://x.test/": lambda m: (404, "", "text/html") if m == "HEAD" else (200, "ok", "text/html")})
    assert asyncio.run(crawl.check_link(site, "http://x.test/"))[0] == "ok"


def test_check_link_real_404_is_broken():
    site = FakeSite({"http://x.test/": (404, "nf", "text/html")})
    assert asyncio.run(crawl.check_link(site, "http://x.test/"))[0] == "broken"


@pytest.mark.parametrize("status", [401, 403, 429, 999, 500, 503, 400])
def test_check_link_ambiguous_statuses_are_unverified(status):
    site = FakeSite({"http://x.test/": (status, "x", "text/html")})
    assert asyncio.run(crawl.check_link(site, "http://x.test/"))[0] == "unverified"


def test_check_link_transient_5xx_recovers():
    state = {"n": 0}

    def flaky(m):
        if m == "HEAD":
            return (500, "", "text/html")
        state["n"] += 1
        return (500, "", "text/html") if state["n"] == 1 else (200, "ok", "text/html")

    site = FakeSite({"http://x.test/": flaky})
    assert asyncio.run(crawl.check_link(site, "http://x.test/"))[0] == "ok"


# ---------------------------------------------------------------- misc
def test_sitemap_parser_index_and_xxe_safety():
    is_index, locs = crawl.parse_sitemap("<sitemapindex><sitemap><loc>https://a.test/s1.xml</loc></sitemap></sitemapindex>")
    assert is_index and locs == ["https://a.test/s1.xml"]
    evil = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            "<urlset><url><loc>&e;</loc></url><url><loc>https://a.test/ok</loc></url></urlset>")
    _, locs = crawl.parse_sitemap(evil)
    assert "root:" not in " ".join(locs) and "https://a.test/ok" in locs
    assert crawl.parse_sitemap("not xml at all")[1] == []
    assert crawl.parse_sitemap("")[1] == []


def test_robots_allowed_rules():
    groups, _ = parse_robots("User-agent: *\nDisallow: /private\nAllow: /private/public\nDisallow: /*.pdf$\nDisallow: /tmp?x=")
    rules = rules_for(groups, "anybot")[0]
    assert not allowed(rules, "/private/x")
    assert allowed(rules, "/private/public/page")  # lamba Allow jeetta hai
    assert not allowed(rules, "/docs/a.pdf") and allowed(rules, "/docs/a.pdf.html")
    assert allowed(rules, "/other") and not allowed(rules, "/tmp?x=1")
    assert allowed([("disallow", "")], "/anything")


def test_diff_scans():
    prev = {"title": ("fail", "Page title"), "h1": ("warn", "H1"), "viewport": ("pass", "Viewport"),
            "robots_txt": ("unverified", "robots.txt"), "canonical": ("fail", "Canonical")}
    cur = {"title": ("pass", "Page title"), "h1": ("fail", "H1"), "viewport": ("pass", "Viewport"),
           "robots_txt": ("fail", "robots.txt"), "canonical": ("warn", "Canonical"),
           "site_broken_links": ("fail", "Broken links")}
    d = diff_scans(prev, cur)
    assert d["fixed"] == ["Page title"] and d["improved"] == ["Canonical"]
    assert d["regressed"] == ["H1"]  # unverified -> fail ko 'bigda' nahi maana
    assert d["new_issues"] == ["Broken links"]
    assert diff_scans(prev, cur, include_new=False)["new_issues"] == []


def test_start_url_without_trailing_slash_is_not_crawled_twice():
    home = page("Home page title for the site", links=["/", "/about"])
    spec = {O: home, O + "/": home, O + "/about": page("About page title here")}
    site = FakeSite(spec)
    status, text, ctype = home
    res = FetchResult(url=O, final_url=O, status=status, text=text, size=len(text),
                      headers={"content-type": ctype}, chain=[(O, status)])
    ctx = Ctx(Page(res), site)

    async def go():
        evs = [e async for e in crawl.crawl_site(ctx)]
        await ctx.close()
        return evs[-1]

    final = asyncio.run(go())
    urls = [p["url"] for p in final["pages"]]
    assert urls.count(O + "/") == 1 and O not in urls
    assert not [f for f in final["findings"] if f.check_id == "site_duplicate_titles" and f.status == "warn"]
