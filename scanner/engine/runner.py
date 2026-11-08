"""Scan orchestrator: checks parallel chalte hain, har result ek event ban ke turant stream hota hai.

Events (dict):
  {"type": "progress", "message": ...}
  {"type": "meta", "final_url": ..., "status": ..., "elapsed_ms": ...}
  {"type": "finding", "finding": {...}}      # live, priority abhi final nahi
  {"type": "done", "score": int, "findings": [...]}   # final, priority ke saath
  {"type": "error", "message": ...}
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from .checks import ALL_CHECKS
from .context import Ctx
from .crawl import crawl_site
from .fetcher import BROWSER_UA, Fetcher
from .page import Page
from .pagespeed import psi_findings
from .priority import assign_priority, compute_score
from .ssrf import UnsafeURL, normalize_url
from .types import UNVERIFIED, Finding

log = logging.getLogger(__name__)

CHECK_TIMEOUT = 25  # har check ke liye seconds
PSI_WAIT = 55  # PageSpeed ke jawab ka max intezaar (seconds)


async def _safe(check, ctx) -> list[Finding]:
    name = check.__name__.removeprefix("check_")
    try:
        return await asyncio.wait_for(check(ctx), CHECK_TIMEOUT)
    except asyncio.TimeoutError:
        msg = "Ye check time par khatam nahi hua."
    except Exception:  # ek check toote to poora scan na toote
        log.exception("check %s failed", name)
        msg = "Ye check chal nahi paya (internal error)."
    return [Finding(name, "technical", name.replace("_", " ").title(), UNVERIFIED, msg,
                    label=UNVERIFIED, impact=1, effort=1)]


async def run_scan(raw_url: str, deep: bool = False, max_pages: int = 25, pagespeed: bool = False,
                   pagespeed_key: str | None = None) -> AsyncIterator[dict]:
    try:
        url = normalize_url(raw_url)
    except UnsafeURL as e:
        yield {"type": "error", "message": str(e)}
        return

    tasks: list[asyncio.Task] = []
    ctx = None
    try:
        async with Fetcher() as fetcher:
            yield {"type": "progress", "message": "Page fetch ho raha hai…"}
            res = await fetcher.fetch(url)
            if res.status in (403, 429, 503) and not res.error:
                res = await fetcher.fetch(url, ua=BROWSER_UA)  # bot-block ho sakta hai, doosre UA se retry

            if res.error:
                yield {"type": "error", "message": res.error}
                return
            if res.status in (403, 429, 503):
                yield {"type": "error", "message": (
                    f"Server ne hamare bot ko roka (HTTP {res.status}). Site toota nahi hai, "
                    "lekin hum scan nahi kar paaye (Cloudflare/WAF ho sakta hai).")}
                return

            page = Page(res)
            if page.tree is None:
                yield {"type": "error", "message": "Page ka HTML parse nahi ho paya (khaali ya HTML nahi hai)."}
                return

            ctx = Ctx(page, fetcher)
            yield {"type": "meta", "final_url": page.url, "status": res.status, "elapsed_ms": round(res.elapsed * 1000)}

            tasks = [asyncio.create_task(_safe(c, ctx)) for c in ALL_CHECKS]
            ps_task = None
            if pagespeed:  # Google ka test saath-saath chalta hai, isliye scan ko zyada der nahi lagti
                ps_task = asyncio.create_task(psi_findings(page.url, pagespeed_key))
                tasks.append(ps_task)
            findings: list[Finding] = []
            for fut in asyncio.as_completed([t for t in tasks if t is not ps_task]):
                for f in await fut:
                    findings.append(f)
                    yield {"type": "finding", "finding": f.to_dict()}

            pages: list[dict] = []
            if deep:
                try:
                    async for ev in crawl_site(ctx, max_pages=max_pages):
                        if ev["type"] == "progress":
                            yield ev
                        elif ev["type"] == "site":
                            pages = ev["pages"]
                            for f in ev["findings"]:
                                findings.append(f)
                                yield {"type": "finding", "finding": f.to_dict()}
                except Exception:  # crawl toote to bhi single-page report mile
                    log.exception("site crawl failed")
                    f = Finding("site_crawl", "site", "Site crawl", UNVERIFIED,
                                "Site crawl poora nahi ho paya (internal error).",
                                label=UNVERIFIED, impact=1, effort=1)
                    findings.append(f)
                    yield {"type": "finding", "finding": f.to_dict()}

            if ps_task:
                try:
                    ps = await asyncio.wait_for(ps_task, PSI_WAIT)
                except asyncio.TimeoutError:
                    ps = [Finding("pagespeed", "performance", "Core Web Vitals", UNVERIFIED,
                                  "PageSpeed test time par khatam nahi hua.", label=UNVERIFIED, impact=1, effort=1)]
                for f in ps:
                    findings.append(f)
                    yield {"type": "finding", "finding": f.to_dict()}

            assign_priority(findings)
            findings.sort(key=lambda f: (-f.priority, f.check_id))
            yield {"type": "done", "score": compute_score(findings),
                   "findings": [f.to_dict() for f in findings], "pages": pages}
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        if ctx:
            await ctx.close()
