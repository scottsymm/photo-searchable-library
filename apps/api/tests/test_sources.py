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
