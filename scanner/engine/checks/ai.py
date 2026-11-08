"""AI Search Readiness: ChatGPT / Perplexity / Claude / Google AI ke liye site kitni taiyar hai."""
from __future__ import annotations

import re

from .. import fixes
from ..context import looks_like_html
from ..robots import root_blocked, rules_for
from ..types import ESTIMATED, FAIL, INFO, PASS, UNVERIFIED, WARN, Finding

CAT = "ai"

# Search / retrieval bots: inhe block karoge to AI answers mein citation nahi milega.
SEARCH_BOTS = ["OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Claude-SearchBot", "Claude-User"]
# Training bots: inhe block karna aapka apna faisla hai.
TRAINING_BOTS = ["GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "CCBot"]

ORG_TYPES = {"Organization", "LocalBusiness", "Corporation", "Person", "Store", "OnlineStore",
             "NGO", "EducationalOrganization", "ProfessionalService", "Restaurant"}

_Q_START = re.compile(
    r"^(what|how|why|when|where|who|which|can|does|do|is|are|should|"
    r"kya|kaise|kyun|kyon|kab|kahan|kaun|kitna|कैसे|क्या|क्यों|कब|कहाँ|कौन|कितना)\b", re.I)


def _blocked(info, bots):
    return [b for b in bots if root_blocked(rules_for(info.groups, b)[0])]


async def check_ai_bots(ctx):
    info = await ctx.robots()
    if info.state == "error":
        return [Finding("ai_bots", CAT, "AI crawler access", UNVERIFIED,
                        "robots.txt padh nahi paaye, isliye AI bots ka access confirm nahi hua.",
                        label=UNVERIFIED, impact=4, effort=1)]
    if info.state == "missing":
        return [Finding("ai_bots", CAT, "AI crawler access", INFO,
                        "robots.txt nahi hai, isliye saare AI bots by default allowed hain.", impact=4, effort=1)]
    blocked_search = _blocked(info, SEARCH_BOTS)
    blocked_train = _blocked(info, TRAINING_BOTS)
    if blocked_search:
        status = FAIL if len(blocked_search) == len(SEARCH_BOTS) else WARN
        return [Finding(
            "ai_bots", CAT, "AI crawler access", status,
            "AI search bots block hain, isliye ChatGPT/Perplexity/Claude ke answers mein aapki site cite nahi hogi.",
            evidence="Blocked: " + ", ".join(blocked_search),
            fix=fixes.robots_ai_allow(),
            fix_note=("robots.txt mein inke liye Allow rule jodo (ya purane Disallow hatao). Training bots "
                      "(GPTBot, ClaudeBot) alag hain, unhe block rakhna aapki marzi hai. Google AI Overviews "
                      "normal Googlebot se chalte hain, isliye Googlebot ko block mat karo."),
            impact=4, effort=1,
        )]
    if blocked_train:
        return [Finding("ai_bots", CAT, "AI crawler access", INFO,
                        "AI search bots allowed hain. Kuch training bots block hain (ye aapka choice ho sakta hai).",
                        evidence="Blocked training bots: " + ", ".join(blocked_train), impact=4, effort=1)]
    return [Finding("ai_bots", CAT, "AI crawler access", PASS, "AI search aur training bots allowed hain.", impact=4, effort=1)]


async def check_llms_txt(ctx):
    r = await ctx.aux("/llms.txt")
    if r.error or r.status in (401, 403, 429) or r.status >= 500:
        return [Finding("llms_txt", CAT, "llms.txt", UNVERIFIED, "llms.txt fetch nahi ho paya.", label=UNVERIFIED, impact=2, effort=1)]
    if r.status == 200 and not looks_like_html(r) and r.text.strip():
        return [Finding("llms_txt", CAT, "llms.txt", PASS, "llms.txt maujood hai.", evidence=r.text[:200], impact=2, effort=1)]
    return [Finding(
        "llms_txt", CAT, "llms.txt", WARN,
        "llms.txt nahi mila. Ye ek emerging convention hai jisme site ka summary AI tools ke liye diya jaata hai. "
        "Abhi koi badi search engine isse use karne ki guarantee nahi deti, isliye ise low priority maano.",
        fix=fixes.llms_txt(ctx.page), fix_note="Site ke root par /llms.txt naam se save karo.",
        impact=2, effort=1, label=ESTIMATED,
    )]


async def check_structured_data(ctx):
    p = ctx.page
    blocks, errors = p.jsonld()
    types = p.jsonld_types()
    is_home = p.path in ("", "/")
    if errors:
        return [Finding("structured_data", CAT, "Structured data (JSON-LD)", WARN,
                        f"{errors} JSON-LD block ka JSON invalid hai, parse nahi hoga.",
                        evidence=", ".join(sorted(types)) or "(koi valid type nahi)",
                        fix_note="JSON ke commas/quotes check karo (Google Rich Results Test se validate karo).",
                        impact=4, effort=2)]
    if not types:
        return [Finding("structured_data", CAT, "Structured data (JSON-LD)", WARN,
                        "Koi JSON-LD structured data nahi mila. Isse search/AI tools ko site ki pehchaan (kaun, kya) saaf milti hai.",
                        fix=fixes.jsonld_organization(p),
                        fix_note="<head> mein daalo. logo URL aur sameAs (social profile links) apne asli values se badlo.",
                        impact=4, effort=2)]
    if is_home and not (types & ORG_TYPES):
        return [Finding("structured_data", CAT, "Structured data (JSON-LD)", WARN,
                        "Homepage par Organization/LocalBusiness jaisa schema nahi hai.",
                        evidence="Mila: " + ", ".join(sorted(types)), fix=fixes.jsonld_organization(p),
                        impact=3, effort=2)]
    return [Finding("structured_data", CAT, "Structured data (JSON-LD)", PASS,
                    "Structured data mila.", evidence=", ".join(sorted(types)), impact=4, effort=2)]


async def check_answer_friendly(ctx):
    p = ctx.page
    heads = [t for lvl, t in p.headings if lvl >= 2 and t]
    qs = [t for t in heads if t.endswith("?") or _Q_START.match(t)]
    if p.word_count < 300:
        return [Finding("answer_friendly", CAT, "Answer-friendly content", INFO,
                        "Content kam hai, isliye structure ka andaza nahi laga.", label=ESTIMATED, impact=2, effort=3)]
    if not qs:
        return [Finding("answer_friendly", CAT, "Answer-friendly content", WARN,
                        "Koi sawaal-jawaab style heading nahi mili. AI tools aksar seedhe sawaalon ke chhote jawab uthate hain.",
                        fix=fixes.faq_section(p),
                        fix_note="Logon ke asli sawaal H2/H3 mein likho, neeche 1-2 line ka seedha jawab do.",
                        impact=2, effort=3, label=ESTIMATED)]
    return [Finding("answer_friendly", CAT, "Answer-friendly content", PASS,
                    f"{len(qs)} sawaal-style headings mile.", evidence="\n".join(qs[:5]),
                    impact=2, effort=3, label=ESTIMATED)]


async def check_entity_signals(ctx):
    p = ctx.page
    has_author = bool(p.meta("author")) or bool(p.tree.xpath('//*[@rel="author"]'))
    texts = " ".join(t.lower() for _, t in p.anchors)
    has_about = any(w in texts for w in ("about", "contact", "हमारे बारे", "संपर्क", "আমাদের সম্পর্কে", "যোগাযোগ"))
    has_org = bool(p.jsonld_types() & ORG_TYPES)
    found = [n for n, ok in (("author", has_author), ("about/contact link", has_about), ("organization schema", has_org)) if ok]
    if not found:
        return [Finding("entity_signals", CAT, "Brand / author signals", WARN,
                        "Author, About/Contact link ya Organization schema, kuch nahi mila. AI aur Google ko ye samajhna mushkil hota hai ki site kiski hai.",
                        fix_note="About aur Contact page banao, header/footer se link karo, aur author byline do.",
                        impact=3, effort=2, label=ESTIMATED)]
    return [Finding("entity_signals", CAT, "Brand / author signals", PASS,
                    "Mile: " + ", ".join(found), impact=3, effort=2, label=ESTIMATED)]


CHECKS = [check_ai_bots, check_llms_txt, check_structured_data, check_answer_friendly, check_entity_signals]
