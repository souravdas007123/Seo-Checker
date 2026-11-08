import json
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .engine.diff import diff_scans
from .engine.runner import run_scan
from .engine.ssrf import UnsafeURL, normalize_url
from .models import CheckResult, Scan

# CheckResult ke wahi fields jo engine ke Finding.to_dict() mein hain
RESULT_FIELDS = ("check_id", "category", "title", "status", "label", "message",
                 "evidence", "fix", "fix_note", "impact", "effort", "priority")
EFFORT_LABELS = {1: "~5 min", 2: "~20 min", 3: "1-2 hours", 4: "half a day", 5: "multiple days"}
HISTORY_LIMIT = 20


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def recent_scans(request, limit=8):
    """History browser session ke hisaab se hai (login nahi, isliye doosre ka scan nahi dikhta)."""
    ids = request.session.get("scan_ids", [])
    if not ids:
        return []
    found = {str(s.pk): s for s in Scan.objects.filter(pk__in=ids)}
    return [found[i] for i in ids if i in found][:limit]


# ---------- pages ----------
def home(request):
    error = ""
    if request.method == "POST":
        try:
            url = normalize_url(request.POST.get("url", ""))
        except UnsafeURL as e:
            error = str(e)
        else:
            ip = client_ip(request)
            since = timezone.now() - timedelta(days=1)
            used = Scan.objects.filter(client_ip=ip, created_at__gte=since).count()
            if used >= settings.SCAN_DAILY_LIMIT:
                error = f"Aaj ki free limit ({settings.SCAN_DAILY_LIMIT} scans) khatam ho gayi. Kal dobara try karo."
            else:
                scan = Scan.objects.create(url=url, client_ip=ip, deep=request.POST.get("deep") == "on")
                ids = request.session.get("scan_ids", [])
                request.session["scan_ids"] = ([str(scan.id)] + ids)[:HISTORY_LIMIT]
                return redirect("report", scan_id=scan.id)
    return render(request, "scanner/home.html", {
        "error": error, "limit": settings.SCAN_DAILY_LIMIT,
        "max_pages": settings.CRAWL_MAX_PAGES, "recent": recent_scans(request),
    })


def report(request, scan_id):
    scan = get_object_or_404(Scan, pk=scan_id)
    return render(request, "scanner/report.html", {"scan": scan})


def diff(request, scan_id):
    """Isi browser session ke pichhle (same URL) scan se tulna."""
    scan = get_object_or_404(Scan, pk=scan_id)
    ids = request.session.get("scan_ids", [])
    if scan.status != Scan.DONE or str(scan.pk) not in ids:
        return JsonResponse({"prev": None})
    prev = (Scan.objects.filter(pk__in=ids, url=scan.url, status=Scan.DONE, created_at__lt=scan.created_at)
            .order_by("-created_at").first())
    if not prev:
        return JsonResponse({"prev": None})

    def as_map(s):
        return {r.check_id: (r.status, r.title) for r in s.results.all()}

    d = diff_scans(as_map(prev), as_map(scan), include_new=(prev.deep == scan.deep))
    return JsonResponse({
        "prev": {"score": prev.score or 0, "date": timezone.localtime(prev.created_at).strftime("%d %b %Y, %H:%M")},
        "score_delta": (scan.score or 0) - (prev.score or 0),
        "same_mode": prev.deep == scan.deep,
        **d,
    })


# ---------- SSE stream ----------
async def stream(request, scan_id):
    try:
        scan = await Scan.objects.aget(pk=scan_id)
    except Scan.DoesNotExist:
        raise Http404

    if scan.status in (Scan.DONE, Scan.FAILED):
        events = _replay(scan)
    else:
        # Atomic claim: do tabs ek saath khulein to scan sirf ek baar chalega.
        # Purana 'running' scan (client disconnect ho gaya) dobara claim ho sakta hai.
        stale = timezone.now() - timedelta(seconds=settings.SCAN_STALE_SECONDS)
        claimed = await Scan.objects.filter(
            Q(pk=scan.pk) & (Q(status=Scan.QUEUED) | Q(status=Scan.RUNNING, started_at__lt=stale))
        ).aupdate(status=Scan.RUNNING, started_at=timezone.now())
        events = _live(scan) if claimed else _busy()

    resp = StreamingHttpResponse(events, content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # nginx buffering band, warna stream ruk-ruk ke aayegi
    return resp


async def _busy():
    yield sse({"type": "busy", "message": "Ye scan doosre tab mein chal raha hai. Thodi der baad page refresh karo."})


async def _live(scan):
    meta = {}
    async for ev in run_scan(scan.url, deep=scan.deep, max_pages=settings.CRAWL_MAX_PAGES):
        if ev["type"] == "meta":
            meta = ev
        elif ev["type"] == "error":
            await Scan.objects.filter(pk=scan.pk).aupdate(
                status=Scan.FAILED, error=ev["message"][:300], finished_at=timezone.now())
        elif ev["type"] == "done":
            await scan.results.all().adelete()  # reclaim hua scan ho to purane rows saaf
            await CheckResult.objects.abulk_create(
                [CheckResult(scan=scan, **{k: f[k] for k in RESULT_FIELDS}) for f in ev["findings"]])
            await Scan.objects.filter(pk=scan.pk).aupdate(
                status=Scan.DONE, score=ev["score"], final_url=meta.get("final_url", ""),
                http_status=meta.get("status"), elapsed_ms=meta.get("elapsed_ms"),
                pages_json=json.dumps(ev.get("pages", []), ensure_ascii=False),
                finished_at=timezone.now())
        yield sse(ev)


async def _replay(scan):
    if scan.status == Scan.FAILED:
        yield sse({"type": "error", "message": scan.error or "Scan fail ho gaya."})
        return
    findings = []
    async for r in scan.results.all():
        d = {k: getattr(r, k) for k in RESULT_FIELDS}
        d["effort_label"] = EFFORT_LABELS.get(r.effort, "")
        findings.append(d)
    try:
        pages = json.loads(scan.pages_json) if scan.pages_json else []
    except ValueError:
        pages = []
    yield sse({"type": "meta", "final_url": scan.final_url, "status": scan.http_status, "elapsed_ms": scan.elapsed_ms})
    yield sse({"type": "done", "score": scan.score, "findings": findings, "pages": pages})
