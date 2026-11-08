from __future__ import annotations

from .. import fixes
from ..metrics import TITLE_PX_LIMIT, title_px
from ..types import ESTIMATED, FAIL, INFO, MEASURED, PASS, WARN, Finding

CAT = "onpage"


def _ev(s: str, n: int = 300) -> str:
    return s if len(s) <= n else s[:n] + "…"


async def check_title(ctx):
    p = ctx.page
    t = p.title
    if not t:
        return [Finding(
            "title", CAT, "Page title", FAIL,
            "<title> tag nahi mila. Search results mein ye sabse important line hoti hai.",
            fix=fixes.title_tag(p),
            fix_note="<head> ke andar daalo. Ye draft page ke H1/domain se bana hai, apne topic ke hisaab se edit karo.",
            impact=5, effort=1,
        )]
    n, px = len(t), title_px(t)
    base = dict(evidence=f"{t}  ({n} chars, ~{px}px)", fix=fixes.title_tag(p),
                fix_note="Ye ek suggested draft hai. Main keyword shuru mein rakho.", impact=4, effort=1)
    if n < 25:
        return [Finding("title", CAT, "Page title", WARN,
                        f"Title bahut chhota hai ({n} chars). 30-60 chars ideal hain.", **base)]
    if n > 60:
        return [Finding("title", CAT, "Page title", WARN,
                        f"Title lamba hai ({n} chars), Google ise kaat sakta hai.", **base)]
    if px > TITLE_PX_LIMIT:
        return [Finding("title", CAT, "Page title", WARN,
                        f"Characters theek hain lekin width ~{px}px hai, Google ~{TITLE_PX_LIMIT}px par kaat sakta hai.",
                        label=ESTIMATED, **base)]
    return [Finding("title", CAT, "Page title", PASS, "Title ki length aur width theek hai.",
                    evidence=base["evidence"], impact=4, effort=1)]


async def check_meta_description(ctx):
    p = ctx.page
    d = p.meta("description")
    if not d:
        return [Finding(
            "meta_description", CAT, "Meta description", FAIL,
            "Meta description nahi mili. Google khud text chun leta hai, jo aksar kharab hota hai.",
            fix=fixes.meta_description_tag(p),
            fix_note="<head> mein daalo. Draft page ke pehle paragraph se bana hai.",
            impact=4, effort=1,
        )]
    n = len(d)
    ev = f"{_ev(d)}  ({n} chars)"
    if n < 70:
        return [Finding("meta_description", CAT, "Meta description", WARN,
                        f"Description chhoti hai ({n} chars). 70-160 chars ideal hain.", evidence=ev,
                        fix=fixes.meta_description_tag(p), impact=3, effort=1)]
    if n > 160:
        return [Finding("meta_description", CAT, "Meta description", WARN,
                        f"Description lambi hai ({n} chars), search result mein kat sakti hai.", evidence=ev,
                        fix=fixes.meta_description_tag(p), impact=3, effort=1, label=ESTIMATED)]
    return [Finding("meta_description", CAT, "Meta description", PASS, "Meta description ki length theek hai.",
                    evidence=ev, impact=3, effort=1)]


async def check_h1(ctx):
    h1s = [t for lvl, t in ctx.page.headings if lvl == 1]
    if not h1s:
        return [Finding("h1", CAT, "H1 heading", FAIL, "Page par H1 nahi mila.",
                        fix=f"<h1>{fixes.suggest_title(ctx.page).split(' | ')[0]}</h1>",
                        fix_note="Page ke main topic wala ek hi H1 rakho.", impact=4, effort=1)]
    if len(h1s) > 1:
        return [Finding("h1", CAT, "H1 heading", WARN, f"{len(h1s)} H1 mile. Ek hi hona chahiye.",
                        evidence="\n".join(_ev(h, 120) for h in h1s[:5]),
                        fix_note="Baaki H1 ko H2 mein badal do.", impact=3, effort=1)]
    if not h1s[0]:
        return [Finding("h1", CAT, "H1 heading", WARN, "H1 tag khaali hai.", impact=3, effort=1)]
    return [Finding("h1", CAT, "H1 heading", PASS, "Ek H1 mila.", evidence=_ev(h1s[0], 150), impact=3, effort=1)]


async def check_heading_order(ctx):
    heads = ctx.page.headings
    if not heads:
        return [Finding("heading_order", CAT, "Heading structure", WARN, "Page par koi heading nahi mili.",
                        fix_note="Content ko H2/H3 sections mein baanto.", impact=2, effort=2)]
    jumps, prev = [], 1  # prev=1: page ka pehla heading H3+ ho to bhi skip maana jaye
    for lvl, text in heads:
        if lvl > prev + 1:
            jumps.append(f"H{prev} → H{lvl}: {_ev(text, 80)}")
        prev = lvl
    if jumps:
        return [Finding("heading_order", CAT, "Heading structure", WARN,
                        f"{len(jumps)} jagah heading level skip hua.", evidence="\n".join(jumps[:5]),
                        fix_note="Levels ek ek karke badhao (H2 ke baad H3, seedha H4 nahi).", impact=2, effort=2)]
    return [Finding("heading_order", CAT, "Heading structure", PASS,
                    f"{len(heads)} headings, order theek hai.", impact=2, effort=2)]


async def check_images_alt(ctx):
    imgs = ctx.page.images
    if not imgs:
        return [Finding("images_alt", CAT, "Image alt text", INFO, "Page par koi image nahi mili.", impact=3, effort=2)]
    missing = [i for i in imgs if i["alt"] is None]  # alt="" decorative images ke liye valid hai
    if not missing:
        return [Finding("images_alt", CAT, "Image alt text", PASS,
                        f"Saari {len(imgs)} images par alt attribute hai.", impact=3, effort=2)]
    status = FAIL if len(missing) / len(imgs) >= 0.5 else WARN
    return [Finding(
        "images_alt", CAT, "Image alt text", status,
        f"{len(missing)}/{len(imgs)} images par alt attribute nahi hai.",
        evidence="\n".join(_ev(i["src"] or "(no src)", 120) for i in missing[:5]),
        fix=fixes.alt_fix(missing, ctx.page),
        fix_note="Alt filename se bana draft hai. Har image ko 1 line mein describe karo. Sirf decorative images par alt=\"\" rakho.",
        impact=3, effort=2,
    )]


async def check_canonical(ctx):
    p = ctx.page
    c = p.canonical
    if not c:
        return [Finding("canonical", CAT, "Canonical tag", WARN,
                        "Canonical tag nahi mila. Duplicate URLs (?utm=, www/non-www) se problem ho sakti hai.",
                        fix=f'<link rel="canonical" href="{p.url}">',
                        fix_note="<head> mein daalo. Har page par uska apna preferred URL do.", impact=3, effort=1)]
    target = p.abs(c)
    if not p.is_internal(target):
        return [Finding("canonical", CAT, "Canonical tag", WARN,
                        "Canonical doosre domain par point kar raha hai. Kya ye jaan-boojhkar hai?",
                        evidence=target, impact=4, effort=1)]
    return [Finding("canonical", CAT, "Canonical tag", PASS, "Canonical tag sahi domain par hai.",
                    evidence=target, impact=3, effort=1)]


async def check_viewport(ctx):
    v = ctx.page.meta("viewport")
    if not v:
        return [Finding("viewport", CAT, "Mobile viewport", FAIL,
                        "Viewport tag nahi hai, mobile par page chhota/zoomed dikhega.",
                        fix='<meta name="viewport" content="width=device-width, initial-scale=1">',
                        fix_note="<head> mein daalo.", impact=4, effort=1)]
    return [Finding("viewport", CAT, "Mobile viewport", PASS, "Viewport tag maujood hai.", evidence=v, impact=4, effort=1)]


async def check_lang(ctx):
    p = ctx.page
    detected = p.detect_script_lang()
    if not p.lang:
        guess = detected or "en"
        note = f"Content {guess} script mein lag raha hai." if detected else ""
        return [Finding("lang", CAT, "Language attribute", WARN,
                        f"<html> par lang attribute nahi hai. {note}".strip(),
                        fix=f'<html lang="{guess}">', fix_note="Apni <html> tag mein lang add karo.",
                        impact=2, effort=1, label=ESTIMATED if detected else MEASURED)]
    if detected and not p.lang.lower().startswith(detected):
        return [Finding("lang", CAT, "Language attribute", WARN,
                        f'lang="{p.lang}" hai lekin content {detected} script mein lag raha hai.',
                        fix=f'<html lang="{detected}">', impact=2, effort=1, label=ESTIMATED)]
    return [Finding("lang", CAT, "Language attribute", PASS, f'lang="{p.lang}" set hai.', impact=2, effort=1)]


async def check_open_graph(ctx):
    p = ctx.page
    need = ["og:title", "og:description", "og:image"]
    missing = [k for k in need if not p.meta(k)]
    if missing:
        return [Finding("open_graph", CAT, "Social share preview (Open Graph)", WARN,
                        f"Missing: {', '.join(missing)}. WhatsApp/Facebook par link ka preview kharab dikhega.",
                        fix=fixes.og_tags(p, missing),
                        fix_note="<head> mein daalo. og:image ke liye 1200x630 ki image use karo.", impact=3, effort=1)]
    return [Finding("open_graph", CAT, "Social share preview (Open Graph)", PASS,
                    "og:title, og:description aur og:image maujood hain.", impact=3, effort=1)]


async def check_content_length(ctx):
    n = ctx.page.word_count
    if n < 150:
        return [Finding("content_length", CAT, "Content length", WARN,
                        f"Sirf {n} words mile. Page 'thin content' lag sakta hai.",
                        fix_note="Page ke topic ko poori tarah explain karo. Ye JS-rendered site ho to content hum dekh hi nahi paaye ho sakte.",
                        impact=3, effort=4, label=ESTIMATED)]
    return [Finding("content_length", CAT, "Content length", PASS, f"{n} words mile.", impact=3, effort=4)]


CHECKS = [
    check_title, check_meta_description, check_h1, check_heading_order, check_images_alt,
    check_canonical, check_viewport, check_lang, check_open_graph, check_content_length,
]
