# FixFirst SEO Checker (V1)

Django + async scanner. Sirf problems nahi, **ready-to-paste fixes**, **"pehle ye fix karo" priority**, **AI search readiness**, aur **live streaming results**.

## Run karna

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python manage.py makemigrations scanner
python manage.py migrate
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
│   ├── fixes.py         ready-to-paste fix generators (+ polish_with_llm hook)
│   ├── priority.py      score + impact x effort ranking
│   └── runner.py        parallel checks, event stream
```

## Naya check kaise jodein

`checks/*.py` mein `async def check_xyz(ctx) -> list[Finding]` likho, us file ki `CHECKS` list mein daalo. Bas.
Rules: `Finding` mein `evidence` do, bot-block par `UNVERIFIED` do (kabhi "broken/missing" mat bolo), aur jo andaza hai use `label=ESTIMATED` karo.

## Abhi ke known limits

- V1 sirf **ek URL** scan karta hai (site crawler V3).
- JS-rendered pages (React/Vue) ka content raw HTML mein nahi hota, isliye content/heading checks galat dikha sakte hain (Playwright fast/slow path V2).
- Fixes **template-based drafts** hain. LLM polish ke liye `fixes.polish_with_llm` hook ready hai, jisme abhi kuch nahi.
- Server response time hamare server se naapa jaata hai, isliye `estimated` label hai. Real-user data ke liye CrUX/PageSpeed API V2 mein.
- Fetcher mein DNS-rebinding ka chhota gap hai (docstring dekho). Production mein internal ranges par egress firewall lagao.
- Rate limit IP-based hai. Reverse proxy ke peeche ho to `TRUST_X_FORWARDED_FOR=1` set karo.
- Production: `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` set karo, SQLite ki jagah Postgres lo.
