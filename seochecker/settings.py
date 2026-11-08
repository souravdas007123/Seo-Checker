import os
from pathlib import Path

from .envutils import env_bool, env_list, parse_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- core
# Dev ki aasaani ke liye default DEBUG=1 hai. LIVE par DJANGO_DEBUG=0 zaroor set karo (DEPLOY.md dekho).
DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
if not DEBUG and SECRET_KEY == "dev-only-change-me":
    raise RuntimeError("Production mein DJANGO_SECRET_KEY set karo.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")  # jaise https://seo.example.com

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "scanner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "seochecker.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "seochecker.wsgi.application"
ASGI_APPLICATION = "seochecker.asgi.application"

# ---------------------------------------------------------------- database
# DATABASE_URL=postgres://user:pass@host:5432/dbname (live) ya khaali chhodo (local SQLite).
if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": parse_database_url(os.environ["DATABASE_URL"], BASE_DIR)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# ---------------------------------------------------------------- auth
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

# ---------------------------------------------------------------- i18n / static
LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

try:  # whitenoise (requirements-prod.txt) ho to live par static files wahi serve karta hai
    import whitenoise  # noqa: F401

    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    if not DEBUG:
        STORAGES = {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
        }
except ImportError:
    pass

# ---------------------------------------------------------------- production security
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]  # load balancer ka health check http par bhi chale
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))  # pehle chhota; sab theek ho to badhao
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMAINS", False)
    # Sirf tab on karo jab app nginx/Cloudflare jaise trusted proxy ke peeche ho, warna header fake ho sakta hai.
    if env_bool("DJANGO_BEHIND_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}

# ---------------------------------------------------------------- SEO checker settings
# Anonymous (login ke bina): ek IP se 24 ghante mein kitne scans. Dev mein badha do: SCAN_DAILY_LIMIT=1000
SCAN_DAILY_LIMIT = int(os.environ.get("SCAN_DAILY_LIMIT", "3"))
# Login kiye user ke liye (account par count hota hai, IP par nahi)
SCAN_DAILY_LIMIT_USER = int(os.environ.get("SCAN_DAILY_LIMIT_USER", "15"))
# Poori site crawl bhaari hai, isliye default mein sirf login user ke liye
DEEP_SCAN_REQUIRES_LOGIN = env_bool("DEEP_SCAN_REQUIRES_LOGIN", True)
# Sirf tab True karo jab app trusted reverse proxy (nginx/Cloudflare) ke peeche ho,
# warna koi bhi X-Forwarded-For fake karke limit bypass kar sakta hai.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", False)
# Running scan agar itne seconds se zyada purana ho to stale maano (client disconnect ho gaya hoga).
SCAN_STALE_SECONDS = 180  # deep scan (crawl) 2 minute tak chal sakta hai
# Deep scan (site crawl) mein max kitne pages. Hard cap engine mein 100 hai.
CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "25"))

# Core Web Vitals (Google PageSpeed Insights API). Key: https://developers.google.com/speed/docs/insights/v5/get-started
PAGESPEED_API_KEY = os.environ.get("PAGESPEED_API_KEY", "")
# Key ke bina Google ki quota bahut kam hai, isliye default mein sirf key ho tab on.
PAGESPEED_ENABLED = env_bool("PAGESPEED_ENABLED", bool(PAGESPEED_API_KEY))

# Purane scans ka auto-delete (python manage.py purge_old_scans). Report link public hota hai, isliye retention zaroori hai.
ANON_RETENTION_DAYS = int(os.environ.get("ANON_RETENTION_DAYS", "30"))
USER_RETENTION_DAYS = int(os.environ.get("USER_RETENTION_DAYS", "365"))
