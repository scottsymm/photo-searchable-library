import sqlite3

from core import settings
from core.conn import connect
from core.schema import migrate


def _db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrate(conn)
    return conn


def test_defaults_are_seeded():
    conn = _db()
    assert settings.get(conn, "watch_enabled") == "0"
    assert settings.get(conn, "watch_backfill") == "prompt"


def test_set_value_upserts():
    conn = _db()
    settings.set_value(conn, "watch_enabled", "1")
    assert settings.get(conn, "watch_enabled") == "1"
    settings.set_value(conn, "watch_enabled", "0")
    assert settings.get(conn, "watch_enabled") == "0"


def test_get_all_and_default():
    conn = _db()
    assert set(settings.get_all(conn)) == {"watch_enabled", "watch_backfill", "watch_initialized"}
    assert settings.get(conn, "missing", "fallback") == "fallback"
