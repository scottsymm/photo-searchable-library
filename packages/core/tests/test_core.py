import sqlite3

from core import jobs
from core.assets import upsert_asset
from core.conn import connect
from core.embeds import add_content, content_knn
from core.schema import migrate


def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrate(conn)
    return conn


def test_schema_and_job_lifecycle():
    conn = db()
    job_id = jobs.push(conn, "scan", {"path": "/tmp/photos"})
    claimed = jobs.claim(conn)
    assert claimed["id"] == job_id
    jobs.complete(conn, job_id)
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == "done"


def test_content_vector_round_trip():
    conn = db()
    asset_id = upsert_asset(
        conn,
        path="/tmp/photo.jpg",
        sha256="a" * 64,
        size_bytes=3,
        mime="image/jpeg",
        taken_at=None,
        gps_lat=None,
        gps_lon=None,
        place_city=None,
        place_country=None,
        thumbnail=b"jpg",
        extra={},
    )
    add_content(conn, asset_id, "test", "1", [1.0] * 512)
    second_id = upsert_asset(
        conn,
        path="/tmp/photo-2.jpg",
        sha256="b" * 64,
        size_bytes=3,
        mime="image/jpeg",
        taken_at=None,
        gps_lat=None,
        gps_lon=None,
        place_city=None,
        place_country=None,
        thumbnail=None,
        extra={},
    )
    add_content(conn, second_id, "test", "1", [-1.0] * 512)
    results = content_knn(conn, [1.0] * 512, 2)
    assert results[0][0] == asset_id


def test_upsert_asset_assigns_source_and_created_at(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    monkeypatch.setattr("core.sources.WATCH_ROOT", watch)
    conn = db()
    path = str((watch / "photo.jpg").resolve())
    asset_id = upsert_asset(
        conn,
        path=path,
        sha256="e" * 64,
        size_bytes=3,
        mime="image/jpeg",
        taken_at=None,
        gps_lat=None,
        gps_lon=None,
        place_city=None,
        place_country=None,
        thumbnail=None,
        extra={},
    )
    row = conn.execute("SELECT source_id, created_at FROM assets WHERE id = ?", (asset_id,)).fetchone()
    mounted_id = conn.execute("SELECT id FROM sources WHERE kind = 'mounted_folder'").fetchone()["id"]
    assert row["source_id"] == mounted_id
    assert row["created_at"] is not None

    upsert_asset(
        conn,
        path=path,
        sha256="f" * 64,
        size_bytes=4,
        mime="image/jpeg",
        taken_at=None,
        gps_lat=None,
        gps_lon=None,
        place_city=None,
        place_country=None,
        thumbnail=None,
        extra={},
    )
    again = conn.execute("SELECT created_at FROM assets WHERE id = ?", (asset_id,)).fetchone()
    assert again["created_at"] == row["created_at"]
