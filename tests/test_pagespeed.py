import asyncio
import sys
import types

try:
    import httpx  # noqa: F401
except ImportError:
    stub = types.ModuleType("httpx")
    stub.AsyncClient = object
    stub.TimeoutException = stub.HTTPError = Exception
    sys.modules["httpx"] = stub

from scanner.engine import pagespeed, runner  # noqa: E402
from scanner.engine.types import FetchResult  # noqa: E402


def psi(lcp=2000, cls=0.05, tbt=100, score=0.92, field=None, opps=None, origin_fallback=False):
    audits = {
        "largest-contentful-paint": {"numericValue": lcp},
        "cumulative-layout-shift": {"numericValue": cls},
        "total-blocking-time": {"numericValue": tbt},
    }
    for i, (title, ms) in enumerate(opps or []):
        audits[f"opp{i}"] = {"title": title, "details": {"type": "opportunity", "overallSavingsMs": ms}}
    data = {"lighthouseResult": {"audits": audits, "categories": {"performance": {"score": score}}}}
    if field is not None:
        data["loadingExperience"] = {"metrics": field, "origin_fallback": origin_fallback}
    return data


FIELD_GOOD = {
    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2100, "category": "FAST"},
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"},  # API: 0.05 * 100
    "INTERACTION_TO_NEXT_PAINT": {"percentile": 180, "category": "FAST"},
}


def by_id(fs):
    return {f.check_id: f for f in fs}


def test_good_site_passes_both():
    f = by_id(pagespeed.findings_from_psi(psi(field=FIELD_GOOD)))
    assert f["cwv_lab"].status == "pass" and f["cwv_lab"].label == "estimated"
    assert f["cwv_field"].status == "pass" and f["cwv_field"].label == "measured"
    assert "CLS: 0.05" in f["cwv_field"].evidence  # percentile 5 => 0.05, '5.00' nahi
    assert "Performance score: 92/100" in f["cwv_lab"].evidence


def test_lab_thresholds_and_tips():
    f = by_id(pagespeed.findings_from_psi(psi(lcp=3000, cls=0.3, tbt=100)))
    assert f["cwv_lab"].status == "fail"  # CLS 0.3 poor
    assert "LCP" in f["cwv_lab"].fix_note and "CLS" in f["cwv_lab"].fix_note and "TBT" not in f["cwv_lab"].fix_note
    assert by_id(pagespeed.findings_from_psi(psi(lcp=2500, cls=0.1, tbt=200)))["cwv_lab"].status == "pass"  # boundary good
    assert by_id(pagespeed.findings_from_psi(psi(lcp=4001)))["cwv_lab"].status == "fail"
    assert by_id(pagespeed.findings_from_psi(psi(lcp=3500)))["cwv_lab"].status == "warn"


def test_field_worst_metric_wins_and_mismatch_is_explained():
    field = dict(FIELD_GOOD)
    field["LARGEST_CONTENTFUL_PAINT_MS"] = {"percentile": 5200, "category": "SLOW"}
    f = by_id(pagespeed.findings_from_psi(psi(field=field)))  # lab good, field bad
    assert f["cwv_field"].status == "fail" and f["cwv_lab"].status == "pass"
    assert "alag hain" in f["cwv_field"].message


def test_origin_fallback_is_disclosed_and_missing_field_is_info():
    f = by_id(pagespeed.findings_from_psi(psi(field=FIELD_GOOD, origin_fallback=True)))
    assert "poore domain" in f["cwv_field"].message
    f = by_id(pagespeed.findings_from_psi(psi(field={})))
    assert f["cwv_field"].status == "info"  # data nahi => pass/fail ka dawa nahi
    f = by_id(pagespeed.findings_from_psi(psi()))
    assert f["cwv_field"].status == "info"


def test_opportunities_sorted_and_small_ones_ignored():
    f = by_id(pagespeed.findings_from_psi(psi(opps=[("Small", 100), ("Compress images", 2500), ("Remove unused JS", 900)])))
    lines = f["perf_opportunities"].evidence.splitlines()
    assert lines[0].startswith("Compress images") and "Small" not in f["perf_opportunities"].evidence
    assert "perf_opportunities" not in by_id(pagespeed.findings_from_psi(psi()))


def test_empty_response_is_unverified_not_pass():
    f = pagespeed.findings_from_psi({})
    assert len(f) == 1 and f[0].status == "unverified"


# ---------------------------------------------------------------- network layer (fake getter)
def run_psi(getter, key=None):
    return asyncio.run(pagespeed.psi_findings("https://example.com/", key, getter=getter, timeout=1))


def test_psi_passes_key_and_mobile_strategy():
    seen = {}

    async def getter(url, params, timeout):
        seen["params"] = dict(params)
        return 200, psi()

    run_psi(getter, key="K123")
    assert seen["params"]["key"] == "K123" and seen["params"]["strategy"] == "mobile"
    run_psi(getter)
    assert "key" not in seen["params"]


def test_psi_failures_become_unverified():
    async def quota(url, params, timeout):
        return 429, {}

    async def bad(url, params, timeout):
        return 400, {"error": {"message": "Lighthouse returned error: FAILED_DOCUMENT_REQUEST"}}

    async def boom(url, params, timeout):
        raise RuntimeError("network")

    async def slow(url, params, timeout):
        await asyncio.sleep(10)

    for getter, text in ((quota, "quota"), (bad, "FAILED_DOCUMENT_REQUEST"), (boom, "connect"), (slow, "time par")):
        f = run_psi(getter)
        assert len(f) == 1 and f[0].status == "unverified" and text in f[0].message


# ---------------------------------------------------------------- runner integration
HTML = ("<!doctype html><html lang='en'><head><title>Handmade Soap Online | Example Store</title></head>"
        "<body><h1>Soap</h1><p>" + "word " * 200 + "</p></body></html>")


class FakeFetcher:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def fetch(self, url, max_bytes=0, ua=None, method="GET"):
        if url.endswith(("/robots.txt", "/sitemap.xml", "/llms.txt")):
            return FetchResult(url=url, final_url=url, status=404, text="nf", chain=[(url, 404)])
        return FetchResult(url=url, final_url=url, status=200, text=HTML, size=len(HTML), chain=[(url, 200)])


async def collect(**kw):
    return [e async for e in runner.run_scan("https://example.com", **kw)]


def test_runner_adds_performance_findings_and_passes_key(monkeypatch):
    calls = []

    async def fake_psi(url, key):
        calls.append((url, key))
        return pagespeed.findings_from_psi(psi(lcp=5000))

    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    monkeypatch.setattr(runner, "psi_findings", fake_psi)
    events = asyncio.run(collect(pagespeed=True, pagespeed_key="KEY"))
    done = events[-1]
    perf = [f for f in done["findings"] if f["category"] == "performance"]
    assert calls == [("https://example.com", "KEY")] and {f["check_id"] for f in perf} >= {"cwv_lab"}
    assert [e for e in events if e["type"] == "finding" and e["finding"]["category"] == "performance"]  # live bhi aaya
    assert done["type"] == "done"


def test_runner_without_pagespeed_makes_no_call(monkeypatch):
    async def fake_psi(url, key):
        raise AssertionError("PageSpeed nahi chalna chahiye")

    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    monkeypatch.setattr(runner, "psi_findings", fake_psi)
    done = asyncio.run(collect())[-1]
    assert not [f for f in done["findings"] if f["category"] == "performance"]


def test_runner_pagespeed_timeout_does_not_break_scan(monkeypatch):
    async def never(url, key):
        await asyncio.sleep(100)

    monkeypatch.setattr(runner, "Fetcher", FakeFetcher)
    monkeypatch.setattr(runner, "psi_findings", never)
    monkeypatch.setattr(runner, "PSI_WAIT", 0.2)
    done = asyncio.run(collect(pagespeed=True))[-1]
    assert done["type"] == "done"
    assert [f for f in done["findings"] if f["check_id"] == "pagespeed"][0]["status"] == "unverified"
