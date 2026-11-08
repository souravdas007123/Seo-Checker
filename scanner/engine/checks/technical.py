from __future__ import annotations

from .. import fixes
from ..context import looks_like_html
from ..robots import root_blocked, rules_for
from ..types import ESTIMATED, FAIL, INFO, MEASURED, PASS, UNVERIFIED, WARN, Finding

CAT = "technical"


async def check_https(ctx):
    p = ctx.page
    if p.scheme == "https":
        return [Finding("https", CAT, "HTTPS", PASS, "Page HTTPS par serve ho raha hai.", impact=4, effort=2)]
    return [Finding("https", CAT, "HTTPS", FAIL,
                    "Site HTTP par hai. Browsers 'Not secure' dikhate hain aur Google HTTPS ko tarjeeh deta hai.",
                    evidence=p.url,
                    fix_note="Hosting panel se free SSL (Let's Encrypt) on karo aur http → https 301 redirect lagao.",
                    impact=4, effort=2)]


async def check_status_redirects(ctx):
    f = ctx.page.fetch
    hops = len(f.chain) - 1
    chain = "\n".join(f"{s}  {u}" for u, s in f.chain)
    if f.status >= 400:
        return [Finding("status", CAT, "HTTP status", FAIL, f"Page ne HTTP {f.status} diya.", evidence=chain, impact=5, effort=2)]
    if hops > 2:
        return [Finding("status", CAT, "Redirects", WARN, f"{hops} redirects ki chain hai. Crawl budget aur speed kharab hoti hai.",
                        evidence=chain, fix_note="Seedha final URL par ek hi redirect rakho.", impact=3, effort=2)]
    msg = "Page 200 OK deta hai." if hops == 0 else f"Page 200 OK hai ({hops} redirect ke baad)."
    return [Finding("status", CAT, "HTTP status & redirects", PASS, msg, evidence=chain if hops else "", impact=3, effort=2)]


async def check_indexability(ctx):
    p = ctx.page
    robots_meta = ((p.meta("robots") or "") + "," + (p.meta("googlebot") or "")).lower()
    header = p.fetch.headers.get("x-robots-tag", "").lower()
    if "noindex" in robots_meta or "noindex" in header:
        src = "meta robots" if "noindex" in robots_meta else "X-Robots-Tag header"
        return [Finding("indexability", CAT, "Indexability", FAIL,
                        f"Page par noindex laga hai ({src}). Google ise search mein nahi dikhayega.",
                        evidence=robots_meta.strip(",") or header,
                        fix_note="Agar ye jaan-boojhkar nahi hai to noindex hata do.", impact=5, effort=1)]
    return [Finding("indexability", CAT, "Indexability", PASS, "Page par noindex nahi hai.", impact=5, effort=1)]


async def check_robots_txt(ctx):
    info = await ctx.robots()
    if info.state == "error":
        return [Finding("robots_txt", CAT, "robots.txt", UNVERIFIED,
                        "robots.txt fetch nahi ho paya (server error ya bot-block). 'Missing' nahi keh sakte.",
                        label=UNVERIFIED, impact=3, effort=1)]
    if info.state == "missing":
        return [Finding("robots_txt", CAT, "robots.txt", WARN, "robots.txt nahi mila.",
                        fix=fixes.robots_basic(ctx.page),
                        fix_note="Site ke root par /robots.txt naam se save karo.", impact=3, effort=1)]
    rules, _ = rules_for(info.groups, "*")
    if root_blocked(rules):
        return [Finding("robots_txt", CAT, "robots.txt", FAIL,
                        "robots.txt poori site ko block kar raha hai (Disallow: /).",
                        evidence=info.raw[:300], fix_note="Agar site live hai to ye rule hatao.", impact=5, effort=1)]
    return [Finding("robots_txt", CAT, "robots.txt", PASS, "robots.txt maujood hai aur site block nahi kar raha.",
                    evidence=info.raw[:200], impact=3, effort=1)]


async def check_sitemap(ctx):
    p = ctx.page
    info = await ctx.robots()
    url = info.sitemaps[0] if info.sitemaps else p.origin + "/sitemap.xml"
    r = await ctx.fetcher.fetch(url, max_bytes=200_000)
    if r.error or r.status in (401, 403, 429) or r.status >= 500:
        return [Finding("sitemap", CAT, "XML sitemap", UNVERIFIED, "Sitemap fetch nahi ho paya, confirm nahi kar sakte.",
                        evidence=url, label=UNVERIFIED, impact=3, effort=1)]
    if r.status == 200 and url.endswith(".gz"):
        return [Finding("sitemap", CAT, "XML sitemap", PASS, "Compressed sitemap mila (content check nahi kiya).",
                        evidence=url, label=ESTIMATED, impact=3, effort=1)]
    head = r.text[:5000].lower()
    if r.status == 200 and not looks_like_html(r) and ("<urlset" in head or "<sitemapindex" in head):
        return [Finding("sitemap", CAT, "XML sitemap", PASS, "Valid XML sitemap mila.", evidence=url, impact=3, effort=1)]
    return [Finding("sitemap", CAT, "XML sitemap", WARN, "Sitemap nahi mila ya valid XML nahi hai.",
                    evidence=f"{url} → HTTP {r.status}", fix=fixes.sitemap_xml(p),
                    fix_note="/sitemap.xml par save karo (starter list hai, baaki pages add karo) aur robots.txt mein Sitemap: line daalo.",
                    impact=3, effort=2)]


async def check_speed(ctx):
    f = ctx.page.fetch
    kb = f.size / 1024
    s = f.elapsed
    status = PASS if s < 1.5 else WARN if s < 3.5 else FAIL
    msg = f"HTML {s:.2f}s mein aaya ({kb:.0f} KB). Hamare server se naapa gaya, aapke users ke liye alag ho sakta hai."
    if f.truncated:
        msg += " Page 2 MB se bada hai, aadha hi padha gaya."
        status = WARN if status == PASS else status
    return [Finding("speed", CAT, "Server response time", status, msg, label=ESTIMATED,
                    fix_note="Caching, CDN aur halka hosting plan check karo." if status != PASS else "",
                    impact=3, effort=4)]


async def check_compression(ctx):
    f = ctx.page.fetch
    enc = f.headers.get("content-encoding", "").lower()
    if enc in ("gzip", "br", "zstd", "deflate"):
        return [Finding("compression", CAT, "Compression", PASS, f"Response {enc} compressed hai.", impact=2, effort=1)]
    if f.size < 10_000:
        return [Finding("compression", CAT, "Compression", INFO, "Page chhota hai, compression ka farak kam padega.", impact=2, effort=1)]
    return [Finding("compression", CAT, "Compression", WARN,
                    f"Page {f.size/1024:.0f} KB hai aur compressed nahi hai.",
                    fix_note="Server par gzip/brotli on karo (hosting panel ya nginx/Apache config).", impact=2, effort=1)]


CHECKS = [check_https, check_status_redirects, check_indexability, check_robots_txt,
          check_sitemap, check_speed, check_compression]
