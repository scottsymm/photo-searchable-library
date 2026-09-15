from core.conn import connect
from core.schema import migrate
from core.sources import get_source, mark_source_status, upsert_source_asset


def db():
    conn = connect(":memory:")
    migrate(conn)
    return conn


def test_sources_table_seeds_apple_photos_source():
    conn = db()
    row = conn.execute(
        "SELECT kind, display_name, status FROM sources WHERE kind = 'apple_photos'"
    ).fetchone()
    assert row["kind"] == "apple_photos"
    assert row["display_name"] == "Apple Photos"
    assert row["status"] == "not_connected"


def test_assets_have_source_identity_columns():
    conn = db()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assets)")}
    assert {"source_id", "source_asset_id", "original_filename"} <= columns


def test_source_status_tracks_authorization_and_counts():
    conn = db()
    source = get_source(conn, "apple_photos")
    mark_source_status(
        conn,
        source_id=source["id"],
        status="connected",
        authorization_state="authorized",
        asset_count=10,
        imported_count=2,
    )
    updated = get_source(conn, "apple_photos")
    assert updated["status"] == "connected"
    assert updated["authorization_state"] == "authorized"
    assert updated["asset_count"] == 10
    assert updated["imported_count"] == 2


def test_upsert_source_asset_is_idempotent():
    conn = db()
    source = get_source(conn, "apple_photos")
    first = upsert_source_asset(
        conn,
        source_id=source["id"],
        source_asset_id="asset-1",
        path="/library/imports/one.jpg",
        original_filename="one.jpg",
    )
    second = upsert_source_asset(
        conn,
        source_id=source["id"],
        source_asset_id="asset-1",
        path="/library/imports/two.jpg",
        original_filename="one.jpg",
    )
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
