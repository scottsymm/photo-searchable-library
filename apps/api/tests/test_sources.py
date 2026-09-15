from core.conn import connect


def test_apple_photos_status_defaults(client):
    response = client.get("/sources/apple-photos/status")
    assert response.status_code == 200
    assert response.json()["source"]["kind"] == "apple_photos"
    assert response.json()["source"]["status"] == "not_connected"


def test_apple_photos_ingest_queues_import(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.sources.LIBRARY", tmp_path)
    response = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0001.JPG", b"jpeg-bytes", "image/jpeg")},
        data={
            "source_asset_id": "ABC/L0/001",
            "original_filename": "IMG_0001.JPG",
            "media_type": "image",
            "authorization_state": "authorized",
            "asset_count": "1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["duplicate"] is False
    assert body["source_asset_id"] == "ABC/L0/001"

    duplicate = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0001.JPG", b"jpeg-bytes", "image/jpeg")},
        data={"source_asset_id": "ABC/L0/001", "original_filename": "IMG_0001.JPG"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True


def test_failed_source_import_is_requeued(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.sources.LIBRARY", tmp_path)
    first = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0002.JPG", b"jpeg-bytes", "image/jpeg")},
        data={"source_asset_id": "ABC/L0/002", "original_filename": "IMG_0002.JPG"},
    )
    assert first.status_code == 200

    from api.deps import DB_PATH

    conn = connect(DB_PATH)
    conn.execute("UPDATE jobs SET status = 'error', error = 'worker failed'")
    conn.commit()
    conn.close()

    retry = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0002.JPG", b"jpeg-bytes", "image/jpeg")},
        data={"source_asset_id": "ABC/L0/002", "original_filename": "IMG_0002.JPG"},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"
    assert retry.json()["duplicate"] is True
    assert retry.json()["retried"] is True

    status = client.get("/sources/apple-photos/status")
    assert status.json()["source"]["imported_count"] == 0


def test_apple_photos_ingest_sets_created_at(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.sources.LIBRARY", tmp_path)
    response = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0003.JPG", b"jpeg-bytes", "image/jpeg")},
        data={"source_asset_id": "ABC/L0/003", "original_filename": "IMG_0003.JPG"},
    )
    assert response.status_code == 200

    from api.deps import DB_PATH

    conn = connect(DB_PATH)
    row = conn.execute(
        "SELECT created_at FROM assets WHERE source_asset_id = 'ABC/L0/003'"
    ).fetchone()
    conn.close()
    assert row["created_at"] is not None


def test_bridge_heartbeat_reports_authorization_required(client):
    response = client.post(
        "/sources/apple-photos/bridge/heartbeat",
        json={"authorization_state": "notDetermined", "asset_count": 0},
    )
    assert response.status_code == 200
    assert response.json()["source"]["bridge_status"] == "authorization_required"


def test_bridge_heartbeat_reports_connected(client):
    response = client.post(
        "/sources/apple-photos/bridge/heartbeat",
        json={"authorization_state": "authorized", "asset_count": 8105},
    )
    assert response.status_code == 200
    source = response.json()["source"]
    assert source["bridge_status"] == "connected"
    assert source["asset_count"] == 8105
    assert source["bridge_last_seen_at"] is not None


def test_bridge_status_becomes_offline_after_lease(client, monkeypatch):
    from api import sources as source_api
    from api.deps import DB_PATH

    generator = client.app.dependency_overrides[source_api.get_conn]()
    conn = next(generator)
    try:
        conn.execute(
            "UPDATE sources SET bridge_status = 'connected', bridge_last_seen_at = '2020-01-01T00:00:00+00:00' WHERE kind = 'apple_photos'"
        )
        conn.commit()
    finally:
        generator.close()
    monkeypatch.setattr(source_api, "BRIDGE_LEASE_SECONDS", 15)
    response = client.get("/sources/apple-photos/status")
    assert response.status_code == 200
    assert response.json()["source"]["bridge_status"] == "offline"
