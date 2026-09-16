import json

import pytest

import api.admin
from core.conn import connect


@pytest.fixture(autouse=True)
def _clear_inventory_cache():
    api.admin._clear_inventory_cache()


def _db(client):
    from api.deps import get_conn
    generator = client.app.dependency_overrides[get_conn]()
    return generator, next(generator)


def _source_id(conn, kind):
    return conn.execute("SELECT id FROM sources WHERE kind = ?", (kind,)).fetchone()["id"]


def _add_asset(conn, kind, path, sha, embedded=False, created_at=None, gps=False):
    conn.execute(
        """INSERT INTO assets(source_id, path, sha256, size_bytes, mime, created_at, gps_lat, gps_lon)
        VALUES (?, ?, ?, 1, 'image/jpeg', ?, ?, ?)""",
        (_source_id(conn, kind), path, sha, created_at, 1.0 if gps else None, 2.0 if gps else None),
    )
    asset_id = conn.execute("SELECT id FROM assets WHERE path = ?", (path,)).fetchone()["id"]
    if embedded:
        conn.execute("INSERT INTO content_embeds(asset_id, model, model_version, embed) VALUES (?, 'm', 'v', ?)", (asset_id, b"x"))
    conn.commit()
    return asset_id


def _get(client):
    response = client.get("/catalog/overview")
    assert response.status_code == 200
    return response.json()


def _source(data, kind):
    return next(s for s in data["sources"] if s["kind"] == kind)


def test_rollup_is_sum_of_per_source_stages(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 10 WHERE kind = 'apple_photos'")
        _add_asset(conn, "apple_photos", "/library/apple-photos/1.heic", "a" * 64, embedded=True)
        _add_asset(conn, "apple_photos", "/library/apple-photos/2.heic", "b" * 64, embedded=True)
        _add_asset(conn, "apple_photos", "/library/apple-photos/3.heic", "c" * 64)
        _add_asset(conn, "mounted_folder", "/media/photos/x.jpg", "d" * 64, embedded=True)
    finally:
        generator.close()
    data = _get(client)
    apple = _source(data, "apple_photos")
    assert apple["stages"]["discovered"] == 10
    assert apple["stages"]["imported"] == 3
    assert apple["stages"]["ready_to_import"] == 7
    assert apple["stages"]["searchable"] == 2
    assert apple["stages"]["failed_or_blocked"] == 1
    for key, value in data["funnel"].items():
        assert value == sum(s["stages"][key] for s in data["sources"])


def test_importing_estimate_reflects_active_sync(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 10 WHERE kind = 'apple_photos'")
        conn.execute("INSERT INTO source_syncs(source_id, limit_count, full_sync) VALUES (?, 5, 0)", (_source_id(conn, "apple_photos"),))
        conn.commit()
    finally:
        generator.close()
    apple = _source(_get(client), "apple_photos")
    assert apple["stages"]["importing"] == 5
    assert apple["sync"]["status"] == "queued"


def test_importing_estimate_full_sync_uses_ready_count(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 10 WHERE kind = 'apple_photos'")
        _add_asset(conn, "apple_photos", "/library/apple-photos/1.heic", "a" * 64, embedded=True)
        conn.execute("INSERT INTO source_syncs(source_id, limit_count, full_sync) VALUES (?, 25, 1)", (_source_id(conn, "apple_photos"),))
        conn.commit()
    finally:
        generator.close()
    assert _source(_get(client), "apple_photos")["stages"]["importing"] == 9


def test_processing_counts_active_job_paths(client, tmp_path, monkeypatch):
    library = tmp_path / "library"
    (library / "apple-photos").mkdir(parents=True)
    monkeypatch.setattr("core.sources.LIBRARY", library)
    active_path = str((library / "apple-photos" / "active.heic").resolve())
    stuck_path = str((library / "apple-photos" / "stuck.heic").resolve())
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 2 WHERE kind = 'apple_photos'")
        _add_asset(conn, "apple_photos", active_path, "a" * 64)
        _add_asset(conn, "apple_photos", stuck_path, "b" * 64)
        conn.execute("INSERT INTO jobs(kind, params) VALUES ('import', ?)", (json.dumps({"paths": [active_path]}),))
        conn.commit()
    finally:
        generator.close()
    apple = _source(_get(client), "apple_photos")
    assert apple["stages"]["processing"] == 1
    assert apple["stages"]["failed_or_blocked"] == 1


def test_readiness_not_configured_by_default(client):
    assert _source(_get(client), "apple_photos")["readiness"] == "not_configured"


def test_readiness_authorization_required(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET authorization_state = 'denied' WHERE kind = 'apple_photos'")
        conn.commit()
    finally:
        generator.close()
    assert _source(_get(client), "apple_photos")["readiness"] == "authorization_required"


def test_readiness_failed_preserves_last_known_inventory(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 8105 WHERE kind = 'apple_photos'")
        conn.execute("INSERT INTO source_syncs(source_id, status, error) VALUES (?, 'error', 'bridge lease expired')", (_source_id(conn, "apple_photos"),))
        conn.commit()
    finally:
        generator.close()
    apple = _source(_get(client), "apple_photos")
    assert apple["readiness"] == "failed"
    assert apple["readiness_detail"] == "bridge lease expired"
    assert apple["stages"]["discovered"] == 8105


def test_readiness_inventory_pending(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 0 WHERE kind = 'apple_photos'")
        conn.commit()
    finally:
        generator.close()
    assert _source(_get(client), "apple_photos")["readiness"] == "inventory_pending"


def test_mounted_readiness_failed_when_root_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.admin.WATCH_ROOT", tmp_path / "missing")
    mounted = _source(_get(client), "mounted_folder")
    assert mounted["readiness"] == "failed"
    assert "not available" in mounted["readiness_detail"]


def test_mounted_discovered_uses_inventory_scan(client, tmp_path, monkeypatch):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("nope")
    monkeypatch.setattr("api.admin.WATCH_ROOT", tmp_path)
    mounted = _source(_get(client), "mounted_folder")
    assert mounted["readiness"] == "connected"
    assert mounted["stages"]["discovered"] == 2
    assert mounted["reported_at"] is not None


def test_context_reports_detected_photos_libraries(client, tmp_path, monkeypatch):
    library = tmp_path / "Photos Library.photoslibrary"
    library.mkdir()
    monkeypatch.setattr("api.admin.WATCH_ROOT", tmp_path)

    data = _get(client)

    assert data["context"]["photos_libraries"] == [{
        "name": library.name,
        "path": str(library),
    }]


def test_apple_entry_exposes_bridge_state(client):
    from datetime import datetime, timezone

    generator, conn = _db(client)
    try:
        conn.execute(
            """UPDATE sources SET bridge_status = 'connected', bridge_last_seen_at = ?,
            authorization_state = 'authorized', asset_count = 8105 WHERE kind = 'apple_photos'""",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["bridge_status"] == "connected"
    assert apple["bridge_last_seen_at"] is not None
    assert apple["authorization_state"] == "authorized"


def test_source_entries_explain_watch_and_manual_ingest(client):
    data = _get(client)
    mounted = _source(data, "mounted_folder")
    uploads = _source(data, "uploads")
    assert mounted["ingest_mode"] == "watch"
    assert mounted["watch_enabled"] is False
    assert uploads["ingest_mode"] == "manual"
    assert uploads["watch_enabled"] is False


def test_apple_reported_at_uses_last_sync_timestamp(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET last_sync_at = '2026-09-15T14:59:16+00:00' WHERE kind = 'apple_photos'")
        conn.commit()
    finally:
        generator.close()
    assert _source(_get(client), "apple_photos")["reported_at"] == "2026-09-15T14:59:16+00:00"


def test_context_blocks(client):
    generator, conn = _db(client)
    try:
        first = _add_asset(conn, "apple_photos", "/library/apple-photos/old.heic", "a" * 64, embedded=True, created_at="2026-09-14T10:00:00+00:00", gps=True)
        second = _add_asset(conn, "uploads", "/library/imports/new.jpg", "b" * 64, embedded=True, created_at="2026-09-15T10:00:00+00:00")
        conn.execute("INSERT INTO persons(name) VALUES ('Jane')")
        person_id = conn.execute("SELECT id FROM persons").fetchone()["id"]
        conn.execute("INSERT INTO faces(asset_id, bbox) VALUES (?, '[0,0,1,1]')", (first,))
        face_id = conn.execute("SELECT id FROM faces").fetchone()["id"]
        conn.execute("INSERT INTO faces(asset_id, bbox) VALUES (?, '[1,1,2,2]')", (second,))
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (?, ?, 'manual')", (person_id, face_id))
        conn.commit()
    finally:
        generator.close()
    data = _get(client)
    assert data["context"]["faces"] == {"total": 2, "assigned": 1, "unassigned": 1, "embeddings_ready": 0, "embeddings_pending": 2, "assets_processing": 0, "clustering_status": "indexing"}
    assert data["context"]["places"] == {"located": 1, "unlocated": 1}
    recent = data["context"]["recent_imports"]
    assert recent[0]["id"] == second
    assert recent[0]["source_kind"] == "uploads"
    assert recent[1]["id"] == first
