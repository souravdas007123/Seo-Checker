"""Core Web Vitals via Google PageSpeed Insights API.

Do alag cheezein aati hain, aur report mein alag dikhai jaati hain:
- FIELD data (CrUX): asli users ka pichhle 28 din ka data. Label "measured".
- LAB data (Lighthouse): ek simulated mobile device par test. Label "estimated".
Dono mein farak ho sakta hai; real-user data ko tarjeeh do.

Privacy: scan kiya gaya URL Google ko bheja jaata hai (PageSpeed API ke liye).
"""
from __future__ import annotations

import asyncio
import logging

from .types import ESTIMATED, FAIL, INFO, MEASURED, PASS, UNVERIFIED, WARN, Finding

log = logging.getLogger(__name__)

API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CAT = "performance"
TIMEOUT = 45.0

# (good_max, poor_min): good <= pehla, poor > doosra, beech ka "needs improvement"
LAB_LIMITS = {"lcp": (2500, 4000), "tbt": (200, 600), "cls": (0.1, 0.25)}
_FIELD_STATUS = {"FAST": PASS, "AVERAGE": WARN, "SLOW": FAIL}
_RANK = {PASS: 0, WARN: 1, FAIL: 2}

LAB_TIPS = {
    "lcp": "LCP: sabse bada image/heading jaldi aaye. Hero image compress karo (WebP), preload lagao, server response tez karo.",
    "cls": "CLS: har image/video par width aur height do, aur page load ke baad content upar-neeche na khiske (ads/banners ki jagah pehle se rakho).",
    "tbt": "TBT: kam JavaScript chalao. Bhaari scripts defer/async karo, unused JS aur third-party widgets hatao.",
}


# ---------------------------------------------------------------- helpers
def _lab_status(metric: str, value: float) -> str:
    good, poor = LAB_LIMITS[metric]
    return PASS if value <= good else FAIL if value > poor else WARN


def _worst(statuses: list[str]) -> str:
    known = [s for s in statuses if s in _RANK]
    return max(known, key=_RANK.get) if known else INFO


def _audit(data: dict, name: str):
    v = (data.get("lighthouseResult", {}).get("audits", {}).get(name) or {}).get("numericValue")
    return v if isinstance(v, (int, float)) else None


def _secs(ms: float) -> str:
    return f"{ms / 1000:.1f} s"


# ---------------------------------------------------------------- findings from API json
def findings_from_psi(data: dict) -> list[Finding]:
    out: list[Finding] = []
    lab = _lab_finding(data)
    field = _field_finding(data)
    if field and field.status == INFO and not lab:
        field = None  # na real-user data, na lab data: "lab test neeche hai" kehna galat hoga
    if field:
        out.append(field)
    if lab:
        out.append(lab)
    if field and lab and field.status in _RANK and lab.status in _RANK and field.status != lab.status:
        field.message += (" Lab test aur real-user data ke nateeje alag hain, isliye real-user wale ko zyada bharosemand maano.")
    opp = _opportunities(data)
    if opp:
        out.append(opp)
    if not out:
        out.append(Finding("pagespeed", CAT, "Core Web Vitals", UNVERIFIED,
                           "PageSpeed ka jawab mila lekin usme speed data nahi tha.",
                           label=UNVERIFIED, impact=1, effort=1))
    return out


def _lab_finding(data: dict) -> Finding | None:
    lcp, cls_, tbt = _audit(data, "largest-contentful-paint"), _audit(data, "cumulative-layout-shift"), _audit(data, "total-blocking-time")
    if lcp is None and cls_ is None and tbt is None:
        return None
    statuses, lines, tips = [], [], []
    for key, label, val, fmt in (("lcp", "LCP", lcp, _secs), ("cls", "CLS", cls_, lambda v: f"{v:.3f}"),
                                 ("tbt", "TBT", tbt, lambda v: f"{v:.0f} ms")):
        if val is None:
            continue
        st = _lab_status(key, val)
        statuses.append(st)
        lines.append(f"{label}: {fmt(val)}  ({'good' if st == PASS else 'needs improvement' if st == WARN else 'poor'})")
        if st != PASS:
            tips.append(LAB_TIPS[key])
    score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
    if isinstance(score, (int, float)):
        lines.insert(0, f"Performance score: {round(score * 100)}/100")
    status = _worst(statuses)
    msg = ("Mobile lab test (simulated device) mein speed theek hai." if status == PASS
           else "Mobile lab test mein speed ki dikkat mili.")
    return Finding("cwv_lab", CAT, "Speed: lab test (mobile)", status, msg, evidence="\n".join(lines),
                   fix_note=" ".join(tips), impact=4, effort=4, label=ESTIMATED)


def _field_finding(data: dict) -> Finding | None:
    le = data.get("loadingExperience") or {}
    metrics = le.get("metrics") or {}
    spec = (("LARGEST_CONTENTFUL_PAINT_MS", "LCP", lambda p: _secs(p)),
            ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "CLS", lambda p: f"{p / 100:.2f}"),  # API CLS ko 100 se guna karke deta hai
            ("INTERACTION_TO_NEXT_PAINT", "INP", lambda p: f"{p:.0f} ms"))
    statuses, lines = [], []
    for key, label, fmt in spec:
        m = metrics.get(key)
        if not m or not isinstance(m.get("percentile"), (int, float)):
            continue
        st = _FIELD_STATUS.get(m.get("category"), INFO)
        statuses.append(st)
        lines.append(f"{label}: {fmt(m['percentile'])}  ({str(m.get('category', '?')).lower()})")
    if not lines:
        return Finding("cwv_field", CAT, "Speed: real users ka data (CrUX)", INFO,
                       "Is page ke liye real-user data nahi hai (Google ke paas kaafi traffic ka data nahi). Lab test neeche hai.",
                       impact=4, effort=4)
    status = _worst(statuses)
    scope = "poore domain ka" if le.get("origin_fallback") else "is page ka"
    msg = (f"Asli users ka (pichhle 28 din, {scope}) data: " +
           ("Core Web Vitals theek hain." if status == PASS else "Core Web Vitals mein sudhaar chahiye."))
    tips = []
    if status != PASS:
        tips.append("Neeche ke metric ko sudharne ke liye lab test ke tips dekho.")
    return Finding("cwv_field", CAT, "Speed: real users ka data (CrUX)", status, msg, evidence="\n".join(lines),
                   fix_note=" ".join(tips), impact=5, effort=4, label=MEASURED)


def _opportunities(data: dict) -> Finding | None:
    audits = data.get("lighthouseResult", {}).get("audits", {}) or {}
    items = []
    for a in audits.values():
        d = a.get("details") or {}
        saving = d.get("overallSavingsMs")
        if d.get("type") == "opportunity" and isinstance(saving, (int, float)) and saving >= 300 and a.get("title"):
            items.append((saving, str(a["title"])[:120]))
    if not items:
        return None
    items.sort(reverse=True)
    lines = [f"{title}  (~{_secs(s)} bachat)" for s, title in items[:5]]
    return Finding("perf_opportunities", CAT, "Speed badhane ke sabse bade mauke", WARN,
                   f"Lighthouse ne {len(items)} aisi cheezein dhoondhi jinse page tez ho sakta hai.",
                   evidence="\n".join(lines), fix_note="Upar se shuru karo, wahi sabse zyada time bachayegi.",
                   impact=3, effort=3, label=ESTIMATED)


# ---------------------------------------------------------------- network
async def _http_get(url: str, params: list, timeout: float):
    import httpx  # lazy: tests mein httpx ki zaroorat nahi

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, params=params)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}


def _unverified(msg: str) -> list[Finding]:
    return [Finding("pagespeed", CAT, "Core Web Vitals", UNVERIFIED, msg, label=UNVERIFIED, impact=1, effort=1)]


async def psi_findings(url: str, api_key: str | None = None, getter=None, timeout: float = TIMEOUT) -> list[Finding]:
    """Kabhi raise nahi karta: koi bhi dikkat par 'unverified' finding deta hai, scan nahi rukta."""
    getter = getter or _http_get
    params = [("url", url), ("strategy", "mobile"), ("category", "performance")]
    if api_key:
        params.append(("key", api_key))
    try:
        status, data = await asyncio.wait_for(getter(API_URL, params, timeout), timeout + 1)
    except asyncio.TimeoutError:
        return _unverified("PageSpeed test time par khatam nahi hua. Baad mein dobara try karo.")
    except Exception:
        log.exception("pagespeed request failed")
        return _unverified("PageSpeed service se connect nahi ho paye.")
    if status == 429:
        return _unverified("PageSpeed API ki quota limit lag gayi. Thodi der baad dobara try karo (ya API key lagao).")
    if status != 200:
        detail = ""
        if isinstance(data, dict):
            detail = str((data.get("error") or {}).get("message", ""))[:160]
        return _unverified(f"Google ye URL test nahi kar paya (HTTP {status}). {detail}".strip())
    try:
        return findings_from_psi(data)
    except Exception:
        log.exception("pagespeed parse failed")
        return _unverified("PageSpeed ka jawab samajh nahi aaya.")
