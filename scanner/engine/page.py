"""Fetched HTML ka parsed view. Saare checks isi se data lete hain."""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as lhtml

from .types import FetchResult

_HEADING = re.compile(r"h[1-6]")

# (script, ranges) -> lang code. Regional language SEO ki neev.
_SCRIPTS = {
    "hi": (0x0900, 0x097F),  # Devanagari
    "bn": (0x0980, 0x09FF),  # Bengali
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
}


def _parse(text: str):
    if not text or not text.strip():
        return None
    try:
        return lhtml.document_fromstring(text)
    except ValueError:  # "Unicode strings with encoding declaration" case
        try:
            return lhtml.document_fromstring(text.encode("utf-8", "replace"))
        except (etree.ParserError, ValueError):
            return None
    except etree.ParserError:
        return None


def _clean(s: str | None) -> str:
    return " ".join((s or "").split())


class Page:
    def __init__(self, fetch: FetchResult):
        self.fetch = fetch
        self.url = fetch.final_url or fetch.url
        self.tree = _parse(fetch.text)
        parts = urlsplit(self.url)
        self.scheme = parts.scheme
        self.host = (parts.hostname or "").lower()
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.path = parts.path or "/"
        self._text = None
        self._meta = None

    # ---- basic tags ----
    @property
    def title(self) -> str:
        els = self.tree.xpath("//title")
        return _clean(els[0].text_content()) if els else ""

    def meta(self, key: str):
        if self._meta is None:
            self._meta = {}
            for m in self.tree.xpath("//meta"):
                k = (m.get("name") or m.get("property") or "").strip().lower()
                if k and k not in self._meta:
                    self._meta[k] = (m.get("content") or "").strip()
        return self._meta.get(key.lower())

    @property
    def canonical(self) -> str | None:
        for link in self.tree.xpath("//link[@rel]"):
            if "canonical" in (link.get("rel") or "").lower().split():
                return (link.get("href") or "").strip()
        return None

    @property
    def lang(self) -> str:
        return (self.tree.get("lang") or "").strip()

    @property
    def headings(self) -> list[tuple[int, str]]:
        out = []
        for el in self.tree.iter():
            if isinstance(el.tag, str) and _HEADING.fullmatch(el.tag):
                out.append((int(el.tag[1]), _clean(el.text_content())))
        return out

    @property
    def h1(self) -> str:
        for level, text in self.headings:
            if level == 1 and text:
                return text
        return ""

    @property
    def images(self) -> list[dict]:
        return [
            {"src": (i.get("src") or i.get("data-src") or "").strip(), "alt": i.get("alt")}
            for i in self.tree.xpath("//img")
        ]

    @property
    def anchors(self) -> list[tuple[str, str]]:
        out = []
        for a in self.tree.xpath("//a[@href]"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            out.append((urljoin(self.url, href), _clean(a.text_content())))
        return out

    def is_internal(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host.removeprefix("www.") == self.host.removeprefix("www.")

    def abs(self, url: str) -> str:
        return urljoin(self.url, url)

    # ---- text ----
    @property
    def text(self) -> str:
        if self._text is None:
            root = copy.deepcopy(self.tree)
            for el in root.xpath("//script|//style|//noscript|//template|//svg"):
                el.drop_tree()
            self._text = _clean(root.text_content())
        return self._text

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def first_paragraph(self) -> str:
        for p in self.tree.xpath("//p"):
            t = _clean(p.text_content())
            if len(t) >= 40 and len(t.split()) >= 8:
                return t
        return ""

    def detect_script_lang(self) -> str | None:
        letters = [c for c in self.text if c.isalpha()]
        if len(letters) < 30:
            return None
        for code, (lo, hi) in _SCRIPTS.items():
            n = sum(1 for c in letters if lo <= ord(c) <= hi)
            if n / len(letters) > 0.15:
                return code
        return None

    # ---- structured data ----
    def jsonld(self) -> tuple[list, int]:
        blocks, errors = [], 0
        for s in self.tree.xpath('//script[@type="application/ld+json"]'):
            try:
                blocks.append(json.loads(s.text or ""))
            except ValueError:
                errors += 1
        return blocks, errors

    def jsonld_types(self) -> set[str]:
        types: set[str] = set()

        def walk(node):
            if isinstance(node, list):
                for n in node:
                    walk(n)
            elif isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    types.add(t)
                elif isinstance(t, list):
                    types.update(x for x in t if isinstance(x, str))
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        walk(v)

        blocks, _ = self.jsonld()
        walk(blocks)
        return types
