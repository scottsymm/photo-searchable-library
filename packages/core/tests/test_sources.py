from core.conn import connect
from core.schema import migrate


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
