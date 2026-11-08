"""Ready-to-paste fixes. V1 mein ye page ke asli content se bane TEMPLATE-based drafts hain.

LLM se polish karne ka hook neeche `polish_with_llm` hai (abhi no-op).
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import unquote, urlsplit

from .page import Page


def _cut(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-")


def brand(page: Page) -> str:
    og = page.meta("og:site_name")
    if og:
        return og
    name = page.host.removeprefix("www.").split(".")[0] if page.host else "Site"
    return name.replace("-", " ").title()


def suggest_title(page: Page) -> str:
    b = brand(page)
    base = page.h1 or page.title
    if not base:
        return _cut(f"{b} - Official Website", 60)
    if b.lower() in base.lower():
        return _cut(base, 60)
    room = 60 - len(" | ") - len(b)
    return f"{_cut(base, max(room, 20))} | {b}"


def suggest_meta_description(page: Page) -> str:
    src = page.first_paragraph or page.text[:400]
    if not src:
        return f"{brand(page)}: {page.title}".strip(": ")
    return _cut(src, 155)


def title_tag(page: Page) -> str:
    return f"<title>{html.escape(suggest_title(page), quote=False)}</title>"


def meta_description_tag(page: Page) -> str:
    return f'<meta name="description" content="{html.escape(suggest_meta_description(page))}">'


def alt_from_src(src: str) -> str:
    path = unquote(urlsplit(src).path)
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = re.sub(r"(?<!\d)\d{2,4}x\d{2,4}(?!\d)", " ", stem)  # "_800x600" (underscore word-char hai, \b kaam nahi karta)
    stem = re.sub(r"[-_]+", " ", stem).strip()
    letters = sum(c.isalpha() for c in stem)
    if letters < 3 or letters < len(stem) * 0.5:
        return "Describe what this image shows"
    return stem.capitalize()


def alt_fix(images: list[dict], page: Page, limit: int = 5) -> str:
    lines = []
    for img in images[:limit]:
        src = img["src"] or "image.jpg"
        lines.append(f'<img src="{html.escape(src)}" alt="{html.escape(alt_from_src(src))}">')
    return "\n".join(lines)


def og_tags(page: Page, missing: list[str]) -> str:
    imgs = [i["src"] for i in page.images if i["src"]]
    values = {
        "og:title": page.title or suggest_title(page),
        "og:description": page.meta("description") or suggest_meta_description(page),
        "og:image": page.abs(imgs[0]) if imgs else f"{page.origin}/path/to/share-image.jpg",
    }
    lines = [f'<meta property="{k}" content="{html.escape(values[k])}">' for k in missing if k in values]
    if "og:title" in missing or "og:description" in missing:
        lines.append(f'<meta property="og:url" content="{html.escape(page.url)}">')
    return "\n".join(lines)


def _script_safe(s: str) -> str:
    return s.replace("</", "<\\/")


def jsonld_organization(page: Page) -> str:
    data = [
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": brand(page),
            "url": f"{page.origin}/",
            "logo": f"{page.origin}/path/to/logo.png",
        },
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": brand(page),
            "url": f"{page.origin}/",
        },
    ]
    body = _script_safe(json.dumps(data, indent=2, ensure_ascii=False))
    return f'<script type="application/ld+json">\n{body}\n</script>'


def robots_ai_allow() -> str:
    from .checks.ai import SEARCH_BOTS

    return "\n\n".join(f"User-agent: {b}\nAllow: /" for b in SEARCH_BOTS)


def robots_basic(page: Page) -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {page.origin}/sitemap.xml"


def _internal_links(page: Page, limit: int) -> list[tuple[str, str]]:
    seen, out = set(), []
    for href, text in page.anchors:
        href = href.split("#", 1)[0]
        if not text or href in seen or not page.is_internal(href):
            continue
        seen.add(href)
        out.append((href, text))
        if len(out) >= limit:
            break
    return out


def llms_txt(page: Page) -> str:
    desc = page.meta("description") or suggest_meta_description(page)
    lines = [f"# {brand(page)}", "", f"> {desc}", "", "## Main pages", f"- [Home]({page.origin}/)"]
    for href, text in _internal_links(page, 8):
        lines.append(f"- [{_cut(text, 60)}]({href})")
    return "\n".join(lines)


def sitemap_xml(page: Page) -> str:
    urls = [f"{page.origin}/"] + [h for h, _ in _internal_links(page, 10)]
    urls = list(dict.fromkeys(urls))
    body = "\n".join(f"  <url><loc>{html.escape(u)}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>"
    )


def faq_section(page: Page) -> str:
    b = html.escape(brand(page))
    return (
        "<section>\n  <h2>Frequently asked questions</h2>\n"
        f"  <h3>What is {b}?</h3>\n  <p>Answer in 1-2 clear sentences.</p>\n"
        f"  <h3>Who is {b} for?</h3>\n  <p>Answer in 1-2 clear sentences.</p>\n"
        f"  <h3>How do I get started with {b}?</h3>\n  <p>Answer in 1-2 clear sentences.</p>\n"
        "</section>"
    )


def polish_with_llm(kind: str, draft: str, page: Page) -> str | None:
    """Hook: baad mein LLM se draft behtar karwao (free plan mein limit ke saath). Abhi None."""
    return None
