# Live (production) par chalana

> Ye files (Dockerfile, compose, settings) abhi **asli server par test nahi hui hain**. Pehle staging par chalake dekho.

## 1. Zaroori environment variables
`.env.example` ko `.env` mein copy karo. Sabse zaroori:

| Variable | Matlab |
|---|---|
| `DJANGO_DEBUG=0` | **Live par zaroor.** Default `1` hai (sirf local ke liye) |
| `DJANGO_SECRET_KEY` | Lambi random string (`python -c "import secrets;print(secrets.token_urlsafe(50))"`) |
| `DJANGO_ALLOWED_HOSTS` | Aapka domain, jaise `seo.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://seo.example.com` |
| `DATABASE_URL` | `postgres://user:pass@host:5432/dbname` |
| `DJANGO_BEHIND_PROXY=1` + `TRUST_X_FORWARDED_FOR=1` | **Sirf** nginx/Cloudflare ke peeche. Warna koi header fake karke HTTPS/IP limit bypass kar sakta hai |
| `PAGESPEED_API_KEY` | Core Web Vitals ke liye (Google Cloud Console > PageSpeed Insights API) |

## 2. Docker se
```bash
cp .env.example .env      # values badlo
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```
App `:8000` par chalta hai. Uske aage nginx/Caddy/Cloudflare se HTTPS lagao.

## 3. Bina Docker ke
```bash
pip install -r requirements-prod.txt
python manage.py migrate
python manage.py collectstatic --noinput
uvicorn seochecker.asgi:application --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers
```
SSE (live results) ke liye proxy ki buffering band honi chahiye. App `X-Accel-Buffering: no` bhejta hai; nginx par `proxy_buffering off;` bhi theek rahega.

## 4. Roz ka kaam
- **Purane scans hatana** (cron/scheduler se roz): `python manage.py purge_old_scans` (pehle `--dry-run`)
- **Health check:** `GET /healthz/` => `{"status":"ok"}` (DB bhi check karta hai)
- **Backup:** Postgres ka daily backup lo (`pg_dump`).

## 5. Live jaane se pehle checklist
- [ ] `DJANGO_DEBUG=0` aur nayi `DJANGO_SECRET_KEY`
- [ ] HTTPS chal raha hai, tabhi `DJANGO_HSTS_SECONDS` badhao (default 3600)
- [ ] Server ke network par private/internal IPs ke liye **egress firewall** (SSRF ka aakhri bachav; code mein DNS-rebinding ka chhota gap hai)
- [ ] Fetcher ke `BOT_UA` mein apni site ka bot-info page daalo
- [ ] Privacy policy / terms page (scanned URL Google PageSpeed ko bheja jaata hai, aur report link public-by-link hai)
- [ ] Email verification / password reset abhi **nahi** hai (email service chahiye). Jab tak nahi, signup open rakhne se pehle sochlo
