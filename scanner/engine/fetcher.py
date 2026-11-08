"""Async, SSRF-safe page fetcher.

Safety:
- har redirect hop par URL + DNS dobara validate hota hai
- response size cap (MAX_BYTES), timeout, max redirects
- sirf port 80/443

Known limitation (V1): DNS validation aur asli connection ke beech chhota gap (DNS rebinding) rehta hai.
Production mein is service ko aise network mein chalao jahan internal ranges par egress firewall ho.
"""
from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit

import httpx

from .ssrf import DNSFailure, UnsafeURL, assert_public_host, normalize_url
from .types import FetchResult

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5

BOT_UA = "Mozilla/5.0 (compatible; SEOCheckerBot/1.0; +https://example.com/bot)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class Fetcher:
    def __init__(self, timeout: float = 10.0):
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={
                "User-Agent": BOT_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en,hi;q=0.8",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def fetch(self, url: str, max_bytes: int = MAX_BYTES, ua: str | None = None,
                    method: str = "GET") -> FetchResult:
        res = FetchResult(url=url)
        headers = {"User-Agent": ua} if ua else None
        current = url
        start = time.perf_counter()
        try:
            for _ in range(MAX_REDIRECTS + 1):
                current = normalize_url(current)
                await assert_public_host(urlsplit(current).hostname or "")
                async with self._client.stream(method, current, headers=headers) as r:
                    res.chain.append((current, r.status_code))
                    if r.is_redirect and r.headers.get("location"):
                        current = urljoin(current, r.headers["location"])
                        continue
                    res.status = r.status_code
                    res.headers = {k.lower(): v for k, v in r.headers.items()}
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            res.truncated = True
                            break
                    res.size = len(body)
                    res.text = bytes(body).decode(r.encoding or "utf-8", errors="replace")
                    res.final_url = current
                    break
            else:
                res.error = "Bahut zyada redirects (loop ho sakta hai)."
                res.error_kind = "redirects"
        except DNSFailure as e:
            res.error, res.error_kind = str(e), "dns"
        except UnsafeURL as e:
            res.error, res.error_kind = str(e), "unsafe"
        except httpx.TimeoutException:
            res.error, res.error_kind = "Site ne time par jawab nahi diya (timeout).", "timeout"
        except httpx.HTTPError as e:
            res.error, res.error_kind = f"Connection error: {type(e).__name__}", "conn"
        res.elapsed = time.perf_counter() - start
        return res
