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
