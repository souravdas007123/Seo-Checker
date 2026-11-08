"""Engine tests. Django/httpx ki zaroorat nahi, sirf lxml + pytest."""
import asyncio

import pytest

from scanner.engine.checks import ALL_CHECKS
from scanner.engine.context import Ctx
from scanner.engine.metrics import title_px
from scanner.engine.page import Page
from scanner.engine.priority import assign_priority, compute_score, top_fixes
from scanner.engine.robots import parse_robots, root_blocked, rules_for
from scanner.engine.ssrf import UnsafeURL, assert_public_host, is_public_ip, normalize_url
from scanner.engine.types import FetchResult


# ---------- helpers ----------
class FakeFetcher:
    """Network ke bina: path -> (status, text, content_type)."""

    def __init__(self, files):
        self.files = files

    async def fetch(self, url, max_bytes=0, ua=None):
        path = "/" + url.split("//", 1)[1].split("/", 1)[-1] if url.count("/") > 2 else "/"
        status, text, ctype = self.files.get(path, (404, "<html><body>Not found</body></html>", "text/html"))
        return FetchResult(url=url, final_url=url, status=status, text=text, size=len(text),
                           headers={"content-type": ctype}, chain=[(url, status)], elapsed=0.2)


def make_ctx(html, files=None, url="https://www.example.com/", headers=None):
    res = FetchResult(url=url, final_url=url, status=200, text=html, size=len(html),
                      headers=headers or {}, chain=[(url, 200)], elapsed=0.4)
    return Ctx(Page(res), FakeFetcher(files or {}))


def run_all(ctx):
    async def go():
        out = []
        for c in ALL_CHECKS:
            out.extend(await c(ctx))
        await ctx.close()
        return {f.check_id: f for f in out}
    return asyncio.run(go())


BAD = "<html><head></head><body><h3>Hi</h3><img src='/img/hero-banner_800x600.jpg'><p>short</p></body></html>"

GOOD = """<!doctype html><html lang="en"><head>
<title>Best Handmade Soap Online in India | Example</title>
<meta name="description" content="Buy handmade natural soaps made in small batches in India, with free shipping on orders above 499 rupees and easy returns.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://www.example.com/">
<meta property="og:title" content="x"><meta property="og:description" content="y"><meta property="og:image" content="z">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Example"}</script>
</head><body><a href="/about">About us</a><h1>Handmade soap</h1><h2>How is our soap made?</h2>
<p>""" + ("word " * 320) + """</p><img src="a.jpg" alt="Soap bar"></body></html>"""

ROBOTS_OK = (200, "User-agent: *\nAllow: /\nSitemap: https://www.example.com/sitemap.xml", "text/plain")
SITEMAP_OK = (200, '<?xml version="1.0"?><urlset xmlns="x"><url><loc>https://www.example.com/</loc></url></urlset>', "application/xml")


# ---------- SSRF ----------
@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
                                "::1", "::ffff:127.0.0.1", "100.64.0.1", "0.0.0.0", "fe80::1"])
def test_private_ips_blocked(ip):
    assert not is_public_ip(ip)


def test_public_ip_allowed():
    assert is_public_ip("8.8.8.8")
    assert is_public_ip("2606:4700:4700::1111")


@pytest.mark.parametrize("raw", ["", "ftp://example.com", "file:///etc/passwd", "http://user:pw@example.com",
                                 "http://example.com:22", "http://example.com:8080", "javascript:alert(1)"])
def test_bad_urls_rejected(raw):
    with pytest.raises(UnsafeURL):
        normalize_url(raw)


def test_url_normalized():
    assert normalize_url("example.com/page#frag") == "https://example.com/page"
    assert normalize_url("  http://example.com ") == "http://example.com"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "169.254.169.254", "0x7f.1"])
def test_internal_hosts_rejected(host):
    with pytest.raises(UnsafeURL):
        asyncio.run(assert_public_host(host))


# ---------- robots ----------
def test_robots_parsing():
    groups, sitemaps = parse_robots(
        "User-agent: *\nDisallow: /private\n\nUser-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /\n"
        "Sitemap: https://e.com/s.xml # comment")
    assert sitemaps == ["https://e.com/s.xml"]
    assert not root_blocked(rules_for(groups, "PerplexityBot")[0])  # '*' group: sirf /private
    assert root_blocked(rules_for(groups, "gptbot")[0])
    assert root_blocked(rules_for(groups, "ClaudeBot")[0])  # do agents ek group mein


def test_robots_allow_root_wins():
    groups, _ = parse_robots("User-agent: *\nDisallow: /\nAllow: /")
    assert not root_blocked(rules_for(groups, "x")[0])


# ---------- title width ----------
def test_title_px_wide_vs_narrow():
    assert title_px("WWWWWWWWWW") > title_px("iiiiiiiiii") * 3
    assert 400 < title_px("Best Handmade Soap Online in India | Example") < 580


# ---------- checks ----------
def test_bad_page_findings():
    r = run_all(make_ctx(BAD, {"/robots.txt": (404, "nope", "text/plain")}))
    assert r["title"].status == "fail" and "<title>" in r["title"].fix
    assert r["meta_description"].status == "fail" and 'name="description"' in r["meta_description"].fix
    assert r["h1"].status == "fail"
    assert r["viewport"].status == "fail"
    assert r["images_alt"].status == "fail" and 'alt="Hero banner"' in r["images_alt"].fix
    assert r["robots_txt"].status == "warn" and "Sitemap:" in r["robots_txt"].fix
    assert r["structured_data"].status == "warn" and "application/ld+json" in r["structured_data"].fix
    assert r["heading_order"].status == "warn"  # h3 se shuru


def test_good_page_passes_core_checks():
    r = run_all(make_ctx(GOOD, {"/robots.txt": ROBOTS_OK, "/sitemap.xml": SITEMAP_OK}))
    for cid in ("title", "meta_description", "h1", "canonical", "viewport", "lang", "open_graph",
                "images_alt", "robots_txt", "sitemap", "structured_data", "https", "indexability", "answer_friendly"):
        assert r[cid].status == "pass", (cid, r[cid].status, r[cid].message)


def test_soft_404_robots_is_missing_not_ok():
    html_page = (200, "<!doctype html><html><body>Welcome</body></html>", "text/html")
    r = run_all(make_ctx(GOOD, {"/robots.txt": html_page}))
    assert r["robots_txt"].status == "warn"  # HTML jo 200 deta hai robots.txt nahi hai


def test_bot_blocked_robots_is_unverified_not_missing():
    r = run_all(make_ctx(GOOD, {"/robots.txt": (403, "Forbidden", "text/html")}))
    assert r["robots_txt"].status == "unverified"
    assert r["ai_bots"].status == "unverified"


def test_noindex_detected_in_meta_and_header():
    r = run_all(make_ctx('<html><head><meta name="robots" content="noindex,follow"></head><body></body></html>'))
    assert r["indexability"].status == "fail"
    r = run_all(make_ctx(GOOD, headers={"x-robots-tag": "noindex"}))
    assert r["indexability"].status == "fail"


def test_ai_bots_search_vs_training():
    search_blocked = "User-agent: PerplexityBot\nDisallow: /\n\nUser-agent: *\nAllow: /"
    r = run_all(make_ctx(GOOD, {"/robots.txt": (200, search_blocked, "text/plain")}))
    assert r["ai_bots"].status == "warn" and "PerplexityBot" in r["ai_bots"].evidence

    train_only = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /"
    r = run_all(make_ctx(GOOD, {"/robots.txt": (200, train_only, "text/plain")}))
    assert r["ai_bots"].status == "info"  # training block karna valid choice hai

    block_all = "User-agent: *\nDisallow: /"
    r = run_all(make_ctx(GOOD, {"/robots.txt": (200, block_all, "text/plain")}))
    assert r["ai_bots"].status == "fail" and r["robots_txt"].status == "fail"


def test_llms_txt_generated_from_page():
    r = run_all(make_ctx(GOOD, {"/robots.txt": ROBOTS_OK}))
    assert r["llms_txt"].status == "warn"
    assert r["llms_txt"].fix.startswith("# Example") and "[About us](https://www.example.com/about)" in r["llms_txt"].fix


def test_hindi_page_lang_detection():
    hindi = "<html><head><title>x</title></head><body><p>" + ("यह एक हिंदी वेबसाइट है जो छोटे व्यापारियों की मदद करती है। " * 10) + "</p></body></html>"
    r = run_all(make_ctx(hindi))
    assert r["lang"].status == "warn" and 'lang="hi"' in r["lang"].fix


def test_encoding_declaration_html_does_not_crash():
    xmlish = '<?xml version="1.0" encoding="UTF-8"?><html><head><title>Ok title for the page here</title></head><body></body></html>'
    assert Page(FetchResult(url="https://e.com/", final_url="https://e.com/", text=xmlish)).tree is not None


def test_jsonld_invalid_json_flagged():
    bad = '<html><head><script type="application/ld+json">{oops</script></head><body></body></html>'
    r = run_all(make_ctx(bad))
    assert r["structured_data"].status == "warn" and "invalid" in r["structured_data"].message


def test_jsonld_fix_is_script_safe():
    from scanner.engine import fixes
    html = '<html><head><title>a</title><meta property="og:site_name" content="Evil</script><script>alert(1)"></head><body></body></html>'
    snippet = fixes.jsonld_organization(Page(FetchResult(url="https://e.com/", final_url="https://e.com/", text=html)))
    assert snippet.count("</script>") == 1  # sirf closing tag, injected nahi


# ---------- score & priority ----------
def test_score_and_priority_ordering():
    r = run_all(make_ctx(BAD, {"/robots.txt": (404, "", "text/plain")}))
    findings = assign_priority(list(r.values()))
    score = compute_score(findings)
    assert 0 <= score < 60
    top = top_fixes(findings, 3)
    assert top[0].priority >= top[1].priority >= top[2].priority
    # impact 5 + effort 1 (title) sabse upar aana chahiye
    assert top[0].check_id in {"title", "meta_description", "h1", "viewport"}
    assert compute_score([]) == 100


def test_perfect_score_when_all_pass():
    r = run_all(make_ctx(GOOD, {"/robots.txt": ROBOTS_OK, "/sitemap.xml": SITEMAP_OK, "/llms.txt": (200, "# x", "text/plain")}))
    assert compute_score(list(r.values())) >= 90
