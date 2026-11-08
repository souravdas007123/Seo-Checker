"""Checks ko milne wala shared context: page + extra files (robots.txt etc.) ek hi baar fetch hoke cache."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .page import Page
from .robots import parse_robots
from .types import FetchResult


@dataclass
class RobotsInfo:
    state: str  # ok | missing | error
    groups: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    raw: str = ""


def looks_like_html(res: FetchResult) -> bool:
    ctype = res.headers.get("content-type", "").lower()
    head = res.text.lstrip()[:200].lower()
    return "html" in ctype or head.startswith(("<!doctype html", "<html", "<head", "<body"))


class Ctx:
    def __init__(self, page: Page, fetcher):
        self.page = page
        self.fetcher = fetcher
        self._aux: dict[str, asyncio.Future] = {}
        self._robots: RobotsInfo | None = None

    def aux(self, path: str) -> asyncio.Future:
        """Same-origin extra file. Same path dobara maange to wahi task milta hai."""
        if path not in self._aux:
            self._aux[path] = asyncio.ensure_future(
                self.fetcher.fetch(self.page.origin + path, max_bytes=300_000)
            )
        return self._aux[path]

    async def robots(self) -> RobotsInfo:
        if self._robots is None:
            r = await self.aux("/robots.txt")
            if r.error or r.status == 0 or r.status >= 500 or r.status in (401, 403, 429):
                info = RobotsInfo("error")  # bot-block ya server dikkat: "missing" mat bolo
            elif r.status == 200 and not looks_like_html(r):
                groups, sitemaps = parse_robots(r.text)
                info = RobotsInfo("ok", groups, sitemaps, r.text)
            else:  # 404/410 ya soft-404 (HTML page jo 200 deta hai)
                info = RobotsInfo("missing")
            self._robots = info
        return self._robots

    async def close(self):
        for fut in self._aux.values():
            if not fut.done():
                fut.cancel()
        await asyncio.gather(*self._aux.values(), return_exceptions=True)
