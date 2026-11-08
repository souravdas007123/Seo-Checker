from pathlib import Path

import pytest

from seochecker.envutils import env_bool, env_list, parse_database_url


def test_postgres_url_with_special_chars():
    d = parse_database_url("postgres://seo_user:p%40ss%2Fw%3Ard@db.internal:5433/seo_db")
    assert d["ENGINE"].endswith("postgresql") and d["NAME"] == "seo_db"
    assert d["USER"] == "seo_user" and d["PASSWORD"] == "p@ss/w:rd"  # URL-encoded password sahi decode hua
    assert d["HOST"] == "db.internal" and d["PORT"] == "5433"
    assert parse_database_url("postgresql+psycopg://u:p@h/db")["NAME"] == "db"
    assert parse_database_url("postgres://u:p@h/db")["PORT"] == ""  # default port Django chunega


def test_sqlite_urls():
    base = Path("/srv/app")
    assert parse_database_url("sqlite:///db.sqlite3", base)["NAME"] == str(base / "db.sqlite3")
    assert parse_database_url("sqlite:////var/data/x.db", base)["NAME"] == "/var/data/x.db"


@pytest.mark.parametrize("bad", ["mysql://u:p@h/db", "postgres://u:p@h/", "sqlite://", "nonsense"])
def test_bad_database_urls_rejected(bad):
    with pytest.raises(ValueError):
        parse_database_url(bad)


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("X_FLAG", "Yes")
    assert env_bool("X_FLAG") is True
    monkeypatch.setenv("X_FLAG", "0")
    assert env_bool("X_FLAG", True) is False
    monkeypatch.delenv("X_FLAG")
    assert env_bool("X_FLAG", True) is True and env_bool("X_FLAG") is False
    monkeypatch.setenv("X_LIST", " a.com, b.com ,, ")
    assert env_list("X_LIST") == ["a.com", "b.com"]
    assert env_list("X_MISSING", "x,y") == ["x", "y"] and env_list("X_MISSING") == []
