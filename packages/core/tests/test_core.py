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
