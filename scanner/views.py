import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.db import connection
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
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


def visible_q(request):
    """Is visitor ko kaun se scans 'apne' dikhte hain: login user ke, aur is browser session ke."""
    q = Q(pk__in=request.session.get("scan_ids", []))
    if request.user.is_authenticated:
        q |= Q(user=request.user)
    return q


def recent_scans(request, limit=8):
    return list(Scan.objects.filter(visible_q(request)).order_by("-created_at")[:limit])


def claim_session_scans(request, user):
    """Login/signup se pehle is browser mein jo scans kiye the, wo ab account ke ho jaate hain."""
    ids = request.session.get("scan_ids", [])
    if ids:
        Scan.objects.filter(pk__in=ids, user__isnull=True).update(user=user)


# ---------- pages ----------
def home(request):
    error, need_login = "", False
    user = request.user if request.user.is_authenticated else None
    limit = settings.SCAN_DAILY_LIMIT_USER if user else settings.SCAN_DAILY_LIMIT
    deep_locked = settings.DEEP_SCAN_REQUIRES_LOGIN and not user

    if request.method == "POST":
        deep = request.POST.get("deep") == "on"
        try:
            url = normalize_url(request.POST.get("url", ""))
        except UnsafeURL as e:
            error = str(e)
        else:
            ip = client_ip(request)
            since = timezone.now() - timedelta(days=1)
            if deep and deep_locked:
                error, need_login = "Poori site crawl ke liye login karo (free hai).", True
            else:
                if user:
                    used = Scan.objects.filter(user=user, created_at__gte=since).count()
                else:
                    used = Scan.objects.filter(user__isnull=True, client_ip=ip, created_at__gte=since).count()
                if used >= limit:
                    error = f"Aaj ki limit ({limit} scans) khatam ho gayi. Kal dobara try karo."
                    need_login = user is None and settings.SCAN_DAILY_LIMIT_USER > limit
                else:
                    scan = Scan.objects.create(url=url, client_ip=ip, deep=deep, user=user)
                    ids = request.session.get("scan_ids", [])
                    request.session["scan_ids"] = ([str(scan.id)] + ids)[:HISTORY_LIMIT]
                    return redirect("report", scan_id=scan.id)
    return render(request, "scanner/home.html", {
        "error": error, "need_login": need_login, "limit": limit, "deep_locked": deep_locked,
        "max_pages": settings.CRAWL_MAX_PAGES, "recent": recent_scans(request),
        "user_limit": settings.SCAN_DAILY_LIMIT_USER,
    })


def report(request, scan_id):
    scan = get_object_or_404(Scan, pk=scan_id)
    return render(request, "scanner/report.html", {"scan": scan})


def diff(request, scan_id):
    """Pichhle (same URL) scan se tulna. Sirf apne scans (login ya is browser session) ke beech."""
    scan = get_object_or_404(Scan, pk=scan_id)
    mine = visible_q(request)
    if scan.status != Scan.DONE or not Scan.objects.filter(mine, pk=scan.pk).exists():
        return JsonResponse({"prev": None})
    prev = (Scan.objects.filter(mine, url=scan.url, status=Scan.DONE, created_at__lt=scan.created_at)
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


# ---------- accounts ----------
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        claim_session_scans(request, user)
        return redirect("home")
    return render(request, "scanner/signup.html", {"form": form})


class LoginViewClaim(LoginView):
    template_name = "scanner/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        claim_session_scans(self.request, form.get_user())
        return response


@login_required
def history(request):
    scans = Scan.objects.filter(user=request.user).order_by("-created_at")[:100]
    return render(request, "scanner/history.html", {"scans": scans, "retention": settings.USER_RETENTION_DAYS})


# ---------- ops ----------
def healthz(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


def robots_txt(request):
    body = "User-agent: *\nAllow: /$\nDisallow: /scan/\nDisallow: /history/\nDisallow: /admin/\n"
    return HttpResponse(body, content_type="text/plain")


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
    async for ev in run_scan(
        scan.url, deep=scan.deep, max_pages=settings.CRAWL_MAX_PAGES,
        pagespeed=settings.PAGESPEED_ENABLED, pagespeed_key=settings.PAGESPEED_API_KEY or None,
    ):
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
