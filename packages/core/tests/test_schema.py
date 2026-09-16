from core.conn import connect
from core.schema import migrate


def test_migrate_seeds_all_sources(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    kinds = {row["kind"] for row in conn.execute("SELECT kind FROM sources")}
    conn.close()
    assert {"apple_photos", "mounted_folder", "uploads"} <= kinds


def test_migrate_adds_created_at_column(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assets)")}
    conn.close()
    assert "created_at" in columns


def test_migrate_backfills_source_ids(tmp_path, monkeypatch):
    library = tmp_path / "library"
    watch = tmp_path / "watch"
    (library / "apple-photos").mkdir(parents=True)
    (library / "imports").mkdir(parents=True)
    watch.mkdir()
    monkeypatch.setenv("PICS_LIBRARY", str(library))
    monkeypatch.setenv("PICS_WATCH_ROOT", str(watch))

    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    paths = {
        "apple": str((library / "apple-photos" / "a.heic").resolve()),
        "upload": str((library / "imports" / "b.jpg").resolve()),
        "mounted": str((watch / "c.jpg").resolve()),
        "other": "/somewhere/else/d.jpg",
    }
    conn.executemany(
        "INSERT INTO assets(path, sha256, size_bytes, mime) VALUES (?, ?, 1, 'image/jpeg')",
        [
            (paths["apple"], "a" * 64),
            (paths["upload"], "b" * 64),
            (paths["mounted"], "c" * 64),
            (paths["other"], "d" * 64),
        ],
    )
    conn.commit()

    migrate(conn)

    rows = {row["path"]: row["source_id"] for row in conn.execute("SELECT path, source_id FROM assets")}
    expected = {row["kind"]: row["id"] for row in conn.execute("SELECT id, kind FROM sources")}
    conn.close()
    assert rows[paths["apple"]] == expected["apple_photos"]
    assert rows[paths["upload"]] == expected["uploads"]
    assert rows[paths["mounted"]] == expected["mounted_folder"]
    assert rows[paths["other"]] is None


def test_migrate_adds_bridge_presence_columns(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
    conn.close()
    assert {"bridge_status", "bridge_last_seen_at"} <= columns


def test_migrate_creates_aliases_and_version_four(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(person_aliases)")}
    version = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()[0]
    conn.close()

    assert {"id", "person_id", "alias", "created_at"} <= columns
    assert version == "4"


def test_migrate_preserves_aliases_when_repeated(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    conn.execute("INSERT INTO persons(id, name) VALUES (1, 'Sam')")
    conn.execute("INSERT INTO person_aliases(person_id, alias) VALUES (1, 'Samuel')")
    conn.commit()

    migrate(conn)

    rows = conn.execute("SELECT person_id, alias FROM person_aliases").fetchall()
    conn.close()
    assert [(row["person_id"], row["alias"]) for row in rows] == [(1, "Samuel")]
