"""Site crawler + link checker.

Accuracy rules (false positive sabse bada dushman):
- "Broken" sirf tab jab confirm ho: HTTP 404/410, ya domain DNS se resolve hi na ho (do baar try ke baad).
- 401/403/429/999, timeout, 5xx, connection error => "unverified" (bot-block ya temporary ho sakta hai).
- Har non-OK link pehle HEAD se, phir GET se dobara confirm hota hai.
- robots.txt ke Disallow wale internal pages crawl/check nahi hote.
- Agar crawl limit ya time ki wajah se adhoora raha to report mein saaf likha hota hai.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import AsyncIterator
from urllib.parse import urldefrag, urlsplit

from lxml import etree

from .context import looks_like_html
from .page import Page
from .robots import allowed, rules_for
from .types import ESTIMATED, FAIL, INFO, PASS, UNVERIFIED, WARN, Finding

CAT = "site"
CRAWL_CONCURRENCY = 5
LINK_CONCURRENCY = 8
HARD_MAX_PAGES = 100
LINK_CAP = 100
THIN_WORDS = 150
MAX_LINES = 10  # evidence mein ek finding ki max lines

SKIP_EXT = {
    "jpg", "jpeg", "png", "gif", "webp", "svg", "ico", "bmp", "avif", "pdf", "zip", "rar", "gz", "7z",
    "mp3", "mp4", "mov", "avi", "webm", "css", "js", "json", "xml", "txt", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "woff", "woff2", "ttf", "eot", "apk", "exe", "dmg",
}
BOT_BLOCK_CODES = {401, 403, 429, 451, 999}


# ---------------------------------------------------------------- helpers
def _defrag(url: str) -> str:
    """Fragment hatao aur khaali path ko '/' banao, taaki 'https://x.com' aur 'https://x.com/' ek hi page maane jaayein."""
    parts = urlsplit(urldefrag(url)[0])
    if not parts.path:
        parts = parts._replace(path="/")
    return parts.geturl()


def _ext(url: str) -> str:
    last = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    return last.rsplit(".", 1)[-1] if "." in last else ""


def _req_path(url: str) -> str:
    p = urlsplit(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def _crawlable(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https") and _ext(url) not in SKIP_EXT


def parse_sitemap(text: str) -> tuple[bool, list[str]]:
    """(is_index, [loc,...]). XXE/network se safe parser."""
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                                 recover=True, huge_tree=False)
        root = etree.fromstring(text.encode("utf-8", "replace"), parser)
    except (etree.XMLSyntaxError, ValueError):
        return False, []
    if root is None:
        return False, []
    is_index = etree.QName(root).localname.lower() == "sitemapindex"
    locs = []
    for el in root.iter():
        if isinstance(el.tag, str) and etree.QName(el).localname == "loc":
            val = (el.text or "").strip()
            if val:
                locs.append(val)
    return is_index, locs


def classify_status(status: int) -> tuple[str, str]:
    if 0 < status < 400:
        return "ok", f"HTTP {status}"
    if status in (404, 410):
        return "broken", f"HTTP {status}"
    if status in BOT_BLOCK_CODES:
        return "unverified", f"HTTP {status} (bot-block ho sakta hai)"
    if status >= 500:
        return "unverified", f"HTTP {status} (server error)"
    return "unverified", f"HTTP {status}"


def classify(res) -> tuple[str, str]:
    if res.error:
        if res.error_kind == "dns":
            return "broken", "domain resolve nahi hota"
        return "unverified", res.error
    return classify_status(res.status)


async def check_link(fetcher, url: str) -> tuple[str, str]:
    """HEAD se jaldi check, fail ho to GET se confirm (kuch servers HEAD par galat jawab dete hain)."""
    r = await fetcher.fetch(url, max_bytes=1, method="HEAD")
    if not r.error and 0 < r.status < 400:
        return "ok", f"HTTP {r.status}"
    r = await fetcher.fetch(url, max_bytes=2048)
    if r.status >= 500 or r.error_kind in ("timeout", "conn", "dns"):
        await asyncio.sleep(0.5)
        r = await fetcher.fetch(url, max_bytes=2048)  # ek aur baar, temporary dikkat ho sakti hai
    return classify(r)


@dataclass
class PageRec:
    url: str
    final_url: str = ""
    status: int = 0
    verdict: str = "unverified"
    detail: str = ""
    html: bool = False
    title: str = ""
    description: str = ""
    h1_count: int = 0
    words: int = 0
    noindex: bool = False
    chain_len: int = 0
    links: list = field(default_factory=list)
    source: str = "link"  # start | link | sitemap


def rec_from_fetch(url: str, res, source: str, start_page: Page) -> PageRec:
    rec = PageRec(url=url, final_url=_defrag(res.final_url or url), status=res.status,
                  chain_len=max(len(res.chain) - 1, 0), source=source)
    rec.verdict, rec.detail = classify(res)
    if res.error or res.status != 200 or not looks_like_html(res):
        return rec
    page = Page(res)
    if page.tree is None:
        return rec
    rec.html = True
    rec.title = page.title
    rec.description = page.meta("description") or ""
    rec.h1_count = sum(1 for lvl, _ in page.headings if lvl == 1)
    rec.words = page.word_count
    robots_meta = ((page.meta("robots") or "") + "," + (page.meta("googlebot") or "")).lower()
    rec.noindex = "noindex" in robots_meta or "noindex" in res.headers.get("x-robots-tag", "").lower()
    if start_page.is_internal(rec.final_url):  # redirect se bahar gaye page ke links follow nahi karte
        rec.links = list(dict.fromkeys(
            _defrag(h) for h, _ in page.anchors if urlsplit(h).scheme in ("http", "https")))
    return rec


async def _fetch_rec(fetcher, url, source, start_page) -> PageRec:
    try:
        res = await fetcher.fetch(url, max_bytes=500_000)
    except Exception:  # ek page ki dikkat poore crawl ko na roke
        return PageRec(url=url, final_url=url, detail="crawl error", source=source)
    return rec_from_fetch(url, res, source, start_page)


async def _sitemap_urls(ctx, robots_info) -> list[str]:
    fetcher, origin = ctx.fetcher, ctx.page.origin
    first = robots_info.sitemaps[0] if robots_info.sitemaps else origin + "/sitemap.xml"
    r = await fetcher.fetch(first, max_bytes=1_000_000)
    if r.error or r.status != 200 or looks_like_html(r):
        return []
    is_index, locs = parse_sitemap(r.text)
    if is_index:
        urls = []
        for child in locs[:2]:  # bade sites par sirf pehle 2 child sitemaps
            cr = await fetcher.fetch(child, max_bytes=1_000_000)
            if not cr.error and cr.status == 200 and not looks_like_html(cr):
                urls.extend(parse_sitemap(cr.text)[1])
        locs = urls
    return [_defrag(u) for u in locs[:500] if ctx.page.is_internal(u)]


# ---------------------------------------------------------------- crawl
async def crawl_site(ctx, max_pages: int = 25, time_budget: float = 70.0,
                     link_cap: int = LINK_CAP) -> AsyncIterator[dict]:
    """Events: {"type":"progress",...} aur aakhir mein {"type":"site","findings":[...],"pages":[...]}"""
    max_pages = max(1, min(max_pages, HARD_MAX_PAGES))
    t0 = time.monotonic()

    def left() -> float:
        return time_budget - (time.monotonic() - t0)

    start, fetcher = ctx.page, ctx.fetcher
    info = await ctx.robots()
    rules = rules_for(info.groups, "seocheckerbot")[0] if info.state == "ok" else []

    recs: dict[str, PageRec] = {}
    link_src: dict[str, list[str]] = defaultdict(list)
    source_of: dict[str, str] = {}
    queue: deque[str] = deque()
    queued: set[str] = set()
    skipped_robots = 0

    def note_links(rec: PageRec):
        for link in rec.links:
            srcs = link_src[link]
            if len(srcs) < 3 and rec.url not in srcs:
                srcs.append(rec.url)
            if start.is_internal(link) and link not in queued and _crawlable(link):
                queued.add(link)
                source_of[link] = "link"
                queue.append(link)

    start_url = _defrag(start.url)
    recs[start_url] = rec_from_fetch(start_url, start.fetch, "start", start)
    queued.add(start_url)
    note_links(recs[start_url])

    sitemap_urls: list[str] = []
    try:
        sitemap_urls = await _sitemap_urls(ctx, info)
    except Exception:
        sitemap_urls = []
    for u in sitemap_urls:
        if "sitemap.xml" not in link_src[u]:
            link_src[u].insert(0, "sitemap.xml")
        if u not in queued and _crawlable(u):
            queued.add(u)
            source_of[u] = "sitemap"
            queue.append(u)

    yield {"type": "progress", "message": "Site crawl shuru…"}

    while queue and left() > 5 and len(recs) < max_pages:
        room = max_pages - len(recs)
        batch: list[str] = []
        while queue and len(batch) < min(CRAWL_CONCURRENCY, room):
            u = queue.popleft()
            if not allowed(rules, _req_path(u)):
                skipped_robots += 1
                continue
            batch.append(u)
        if not batch:
            continue
        results = await asyncio.gather(*(_fetch_rec(fetcher, u, source_of.get(u, "link"), start) for u in batch))
        for rec in results:
            recs[rec.url] = rec
            note_links(rec)
        yield {"type": "progress", "message": f"Site crawl: {len(recs)} pages dekhe…"}

    remaining = [u for u in queue if u not in recs and allowed(rules, _req_path(u))]
    truncated = bool(remaining)
    timed_out = truncated and left() <= 5

    # ---- links verify karo (jo crawl nahi hue: external aur limit se bahar ke internal)
    internal_t, external_t = [], []
    for rec in list(recs.values()):
        for link in rec.links:
            if link in recs or link in internal_t or link in external_t:
                continue
            if start.is_internal(link):
                if allowed(rules, _req_path(link)):
                    internal_t.append(link)
            else:
                external_t.append(link)
    targets = (internal_t + external_t)
    unchecked = max(len(targets) - link_cap, 0)
    targets = targets[:link_cap]

    verdicts: dict[str, tuple[str, str]] = {}
    if targets:
        yield {"type": "progress", "message": f"{len(targets)} links verify ho rahe hain…"}
        sem = asyncio.Semaphore(LINK_CONCURRENCY)

        async def one(u):
            async with sem:
                if left() <= 0:
                    return u, None
                try:
                    return u, await check_link(fetcher, u)
                except Exception:
                    return u, ("unverified", "check fail hua")

        for u, v in await asyncio.gather(*(one(u) for u in targets)):
            if v is None:
                unchecked += 1
            else:
                verdicts[u] = v

    stats = {
        "max_pages": max_pages, "sitemap_total": len(sitemap_urls), "truncated": truncated,
        "timed_out": timed_out, "skipped_robots": skipped_robots, "unchecked_links": unchecked,
        "links_checked": len(verdicts),
    }
    findings, rows = build_site_findings(recs, verdicts, link_src, stats, start.is_internal)
    yield {"type": "site", "findings": findings, "pages": rows}


# ---------------------------------------------------------------- findings
def _lines(items: list[str], n: int = MAX_LINES) -> str:
    out = items[:n]
    if len(items) > n:
        out.append(f"…aur {len(items) - n} aur")
    return "\n".join(out)


def _norm(s: str) -> str:
    return " ".join(s.casefold().split())


def _dups(recs: list[PageRec], attr: str) -> list[list[PageRec]]:
    groups: dict[str, list[PageRec]] = defaultdict(list)
    for r in recs:
        val = _norm(getattr(r, attr))
        if val:
            groups[val].append(r)
    return [g for g in groups.values() if len(g) > 1]


def build_site_findings(recs, verdicts, link_src, stats, is_internal):
    findings: list[Finding] = []
    rows: list[dict] = []

    # same final URL par pahunchne wale pages ek hi maane jaate hain
    seen_final, ok_pages = set(), []
    for r in recs.values():
        if r.html and r.final_url not in seen_final:
            seen_final.add(r.final_url)
            ok_pages.append(r)
    n_ok = len(ok_pages)
    judge = n_ok >= 2  # ek page se "duplicate" ya "kitne %" ka nateeja nahi nikalta

    # ---- summary
    ev = [f"Pages crawl hue: {len(recs)} (limit {stats['max_pages']})",
          f"Sitemap mein URLs: {stats['sitemap_total']}",
          f"Links verify hue: {stats['links_checked']}"]
    if stats["skipped_robots"]:
        ev.append(f"robots.txt ke Disallow ki wajah se skip: {stats['skipped_robots']}")
    if stats["unchecked_links"]:
        ev.append(f"Link check limit/time ki wajah se baaki: {stats['unchecked_links']}")
    if stats["truncated"]:
        why = "time khatam ho gaya" if stats["timed_out"] else f"{stats['max_pages']} pages ki limit aa gayi"
        msg = (f"Site poori crawl nahi hui ({why}). Neeche ke nateeje sirf in {len(recs)} pages ke hain, "
               "poori site ke nahi.")
    else:
        msg = f"{len(recs)} pages crawl hue, site ke saare reachable pages cover ho gaye."
    findings.append(Finding("site_summary", CAT, "Crawl summary", INFO, msg, evidence="\n".join(ev),
                            impact=1, effort=1))

    # ---- broken / unverified links
    allv: dict[str, tuple[str, str]] = {u: (r.verdict, r.detail) for u, r in recs.items()}
    for u, v in verdicts.items():
        allv.setdefault(u, v)
    broken = sorted(u for u, (k, _) in allv.items() if k == "broken")
    unverified = sorted(u for u, (k, _) in allv.items() if k == "unverified")
    # sirf wahi jo kisi page se linked ya sitemap mein hain (start page khud ko broken nahi maanta)
    broken = [u for u in broken if link_src.get(u) or recs.get(u, PageRec(u)).source == "sitemap"]
    b_int = [u for u in broken if is_internal(u)]
    b_ext = [u for u in broken if not is_internal(u)]

    def fmt(urls):
        out = []
        for u in urls:
            line = f"{u}  →  {allv[u][1]}"
            src = link_src.get(u)
            if src:
                line += f"\n    mila: {src[0]}"
            out.append(line)
        return _lines(out)

    if broken:
        status = FAIL if b_int else WARN
        findings.append(Finding(
            "site_broken_links", CAT, "Broken links", status,
            f"{len(b_int)} internal aur {len(b_ext)} external broken link mile (404/410 ya domain resolve nahi hua).",
            evidence=fmt(b_int + b_ext),
            fix_note="Link hata do ya sahi URL se badlo. Internal page hata hai to uske naye URL par 301 redirect lagao.",
            impact=4, effort=2))
    else:
        extra = f" ({stats['unchecked_links']} links limit ki wajah se check nahi hue)" if stats["unchecked_links"] else ""
        findings.append(Finding("site_broken_links", CAT, "Broken links", PASS,
                                f"{len(allv)} links dekhe, koi confirmed broken link nahi mila{extra}.",
                                impact=4, effort=2))
    if unverified:
        findings.append(Finding(
            "site_unverified_links", CAT, "Links jo confirm nahi ho paye", UNVERIFIED,
            f"{len(unverified)} links ka status pakka nahi pata (bot-block, timeout ya server error). Ye 'broken' nahi maane gaye.",
            evidence=fmt(unverified), label=UNVERIFIED, impact=1, effort=1))

    # ---- page-level site checks
    flagged: dict[str, list[str]] = defaultdict(list)
    for r in recs.values():
        if not r.html and r.verdict != "ok":
            flagged[r.url].append("error" if r.verdict == "unverified" else "broken")

    if judge:
        def frac_status(count):
            return FAIL if count / n_ok >= 0.5 else WARN

        missing_t = [r for r in ok_pages if not r.title.strip()]
        missing_d = [r for r in ok_pages if not r.description.strip()]
        missing_h = [r for r in ok_pages if r.h1_count == 0]
        for r in missing_t:
            flagged[r.url].append("no title")
        for r in missing_d:
            flagged[r.url].append("no description")
        for r in missing_h:
            flagged[r.url].append("no h1")

        def missing_finding(cid, title, pages, what, impact, note):
            if pages:
                findings.append(Finding(cid, CAT, title, frac_status(len(pages)),
                                        f"{len(pages)}/{n_ok} pages par {what} nahi hai.",
                                        evidence=_lines([p.final_url for p in pages]),
                                        fix_note=note, impact=impact, effort=3))
            else:
                findings.append(Finding(cid, CAT, title, PASS, f"Saare {n_ok} pages par {what} hai.",
                                        impact=impact, effort=3))

        missing_finding("site_missing_titles", "Pages par title", missing_t, "title", 4,
                        "Har page ka apna title rakho (CMS ke SEO plugin se bulk mein bhi bhar sakte ho).")
        missing_finding("site_missing_descriptions", "Pages par meta description", missing_d,
                        "meta description", 3, "Har page ke liye 70-160 characters ki unique description likho.")
        missing_finding("site_missing_h1", "Pages par H1", missing_h, "H1", 3,
                        "Har page par ek H1 rakho jo uska main topic bataye.")

        for cid, title, attr, label, impact in (
            ("site_duplicate_titles", "Duplicate titles", "title", "duplicate title", 3),
            ("site_duplicate_descriptions", "Duplicate meta descriptions", "description", "duplicate description", 2),
        ):
            groups = _dups(ok_pages, attr)
            if groups:
                ev_lines = []
                for g in groups:
                    ev_lines.append(f'"{getattr(g[0], attr)[:80]}"')
                    ev_lines.extend(f"    {p.final_url}" for p in g[:5])
                    for p in g:
                        flagged[p.url].append(label)
                findings.append(Finding(
                    cid, CAT, title, WARN, f"{len(groups)} jagah ek hi {attr} kai pages par repeat ho raha hai.",
                    evidence=_lines(ev_lines, 14),
                    fix_note=f"Har page ka {attr} alag aur us page ke topic ke hisaab se rakho.",
                    impact=impact, effort=3))
            else:
                findings.append(Finding(cid, CAT, title, PASS, f"Koi duplicate {attr} nahi mila.",
                                        impact=impact, effort=3))

        thin = [r for r in ok_pages if r.words < THIN_WORDS]
        for r in thin:
            flagged[r.url].append("thin content")
        if thin:
            findings.append(Finding(
                "site_thin_pages", CAT, "Thin pages", WARN,
                f"{len(thin)}/{n_ok} pages par {THIN_WORDS} se kam words hain.",
                evidence=_lines([f"{p.final_url}  ({p.words} words)" for p in thin]),
                fix_note="Kam content wale pages ko badhao, milao ya noindex karo. JS-rendered page ho to content hum dekh nahi paaye ho sakte.",
                impact=3, effort=4, label=ESTIMATED))
        else:
            findings.append(Finding("site_thin_pages", CAT, "Thin pages", PASS,
                                    f"Saare pages par {THIN_WORDS}+ words hain.", impact=3, effort=4, label=ESTIMATED))

    noindex = [r for r in ok_pages if r.noindex]
    for r in noindex:
        flagged[r.url].append("noindex")
    if noindex:
        findings.append(Finding(
            "site_noindex_pages", CAT, "Noindex pages", INFO,
            f"{len(noindex)} pages par noindex hai. Jaan-boojhkar hai to theek, warna Google inhe dikhayega nahi.",
            evidence=_lines([p.final_url for p in noindex]), impact=2, effort=1))

    redirected = [r for r in recs.values() if r.source != "start" and r.chain_len >= 1 and r.final_url != r.url]
    if redirected:
        lines = []
        for r in redirected:
            line = f"{r.url}  →  {r.final_url}"
            if link_src.get(r.url):
                line += f"\n    mila: {link_src[r.url][0]}"
            lines.append(line)
            flagged[r.url].append("redirect")
        findings.append(Finding(
            "site_internal_redirects", CAT, "Internal links jo redirect hote hain", WARN,
            f"{len(redirected)} internal links purane URL par point karte hain jo redirect hota hai.",
            evidence=_lines(lines),
            fix_note="Link ko seedha final URL par point karo, isse speed aur crawl dono behtar hote hain.",
            impact=2, effort=2))

    for r in recs.values():
        rows.append({
            "url": r.url, "status": r.status, "title": r.title[:80], "words": r.words,
            "issues": list(dict.fromkeys(flagged.get(r.url, []))),
        })
    return findings, rows
