"""Settings ke chhote helpers. Django import nahi karta, isliye alag se test ho jaata hai."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

_TRUE = {"1", "true", "yes", "on"}


def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    return default if val is None else val.strip().lower() in _TRUE


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def parse_database_url(url: str, base_dir: Path | None = None) -> dict:
    """postgres://user:pass@host:5432/dbname ya sqlite:///db.sqlite3 => Django DATABASES entry."""
    parts = urlsplit(url)
    scheme = parts.scheme.split("+")[0]
    if scheme in ("postgres", "postgresql"):
        name = unquote(parts.path.lstrip("/"))
        if not name:
            raise ValueError("DATABASE_URL mein database ka naam nahi hai.")
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": unquote(parts.username or ""),
            "PASSWORD": unquote(parts.password or ""),
            "HOST": parts.hostname or "",
            "PORT": str(parts.port or ""),
            "CONN_MAX_AGE": 60,
        }
    if scheme == "sqlite":
        raw = unquote(parts.path)
        if raw in ("", "/"):
            raise ValueError("DATABASE_URL mein sqlite file ka path nahi hai.")
        # sqlite:///rel.db => "/rel.db" (relative), sqlite:////abs/x.db => "//abs/x.db" (absolute)
        path = Path(raw[1:])  # pehla "/" separator hai; baaki "/" se shuru ho to absolute path
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(path)}
    raise ValueError(f"DATABASE_URL ka scheme support nahi hai: {parts.scheme!r}")
