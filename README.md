# FixFirst SEO Checker (V1)

Django + async scanner. Sirf problems nahi, **ready-to-paste fixes**, **"pehle ye fix karo" priority**, **AI search readiness**, aur **live streaming results**.

## Run karna

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python manage.py makemigrations scanner
python manage.py migrate        # model badalne par (jaise deep/pages_json) dono dobara chalao
python manage.py createsuperuser        # optional, /admin ke liye

SCAN_DAILY_LIMIT=1000 uvicorn seochecker.asgi:application --reload   # dev
```

`http://127.0.0.1:8000` kholo. SSE streaming ke liye ASGI (uvicorn) use karo.

## Tests

```bash
pytest -q        # engine tests Django ke bina bhi chalte hain
```

## Structure

```
scanner/
├── models.py            Scan, CheckResult
├── views.py             home, report, stream (async SSE)
├── engine/              <- Django-free, alag se test hota hai
│   ├── ssrf.py          URL validation + private IP block
│   ├── fetcher.py       async httpx, redirect hop-by-hop validation, size cap
│   ├── page.py          lxml parsed page
│   ├── context.py       robots.txt/aux files ka shared cache
│   ├── checks/          onpage.py, technical.py, ai.py  (naya check = ek async function)
│   ├── crawl.py         site crawler + link checker + site-level findings
│   ├── diff.py          do scans ka tulna (fixed / bigda / naye issues)
│   ├── fixes.py         ready-to-paste fix generators (+ polish_with_llm hook)
│   ├── priority.py      score + impact x effort ranking
│   └── runner.py        parallel checks, event stream
```

## Naya check kaise jodein

`checks/*.py` mein `async def check_xyz(ctx) -> list[Finding]` likho, us file ki `CHECKS` list mein daalo. Bas.
Rules: `Finding` mein `evidence` do, bot-block par `UNVERIFIED` do (kabhi "broken/missing" mat bolo), aur jo andaza hai use `label=ESTIMATED` karo.

## Abhi ke known limits

- Normal scan ek URL ka hai. "Poori site crawl" checkbox par max `CRAWL_MAX_PAGES` (default 25, hard cap 100) pages crawl hote hain. Limit ya 70 sec time khatam ho to report mein saaf likha aata hai ki crawl adhoora tha.
- Crawler robots.txt ke Disallow respect karta hai, JS-rendered links nahi dekhta, aur orphan-page/click-depth check abhi nahi hain (adhoore crawl par ye jhoothe nateeje dete).
- Link checker: sirf 404/410 ya DNS fail "broken" hai. 403/429/timeout/5xx "unverified" hote hain. Ek scan mein max 100 non-crawled links check hote hain.
- History login ke bina browser session par based hai (doosre ke scan nahi dikhte). Sahi history ke liye accounts chahiye.
- Report ka link jisko mile wo dekh sakta hai (random UUID), lekin page `noindex` hai. PDF ke liye browser ka Print > Save as PDF use hota hai.
- `BOT_UA` (fetcher.py) mein placeholder URL hai, production mein apni site ka bot-info page daalo.
- JS-rendered pages (React/Vue) ka content raw HTML mein nahi hota, isliye content/heading checks galat dikha sakte hain (Playwright fast/slow path V2).
- Fixes **template-based drafts** hain. LLM polish ke liye `fixes.polish_with_llm` hook ready hai, jisme abhi kuch nahi.
- Server response time hamare server se naapa jaata hai, isliye `estimated` label hai. Real-user data ke liye CrUX/PageSpeed API V2 mein.
- Fetcher mein DNS-rebinding ka chhota gap hai (docstring dekho). Production mein internal ranges par egress firewall lagao.
- Rate limit IP-based hai. Reverse proxy ke peeche ho to `TRUST_X_FORWARDED_FOR=1` set karo.
- Production: `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` set karo, SQLite ki jagah Postgres lo.
