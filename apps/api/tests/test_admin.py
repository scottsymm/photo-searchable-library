def test_admin_settings_defaults(client):
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert response.json()["settings"]["watch_enabled"] == "0"


def test_admin_settings_update(client):
    response = client.patch("/admin/settings", json={"watch_enabled": "1"})
    assert response.status_code == 200
    assert response.json()["settings"]["watch_enabled"] == "1"


def test_admin_settings_reject_invalid_value(client):
    response = client.patch("/admin/settings", json={"watch_enabled": "yes"})
    assert response.status_code == 422


def test_admin_status_returns_configured_mount_source(client, monkeypatch):
    monkeypatch.setenv("PICS_MOUNT_SOURCE", "/private/photos")
    response = client.get("/admin/status")
    assert response.status_code == 200
    assert response.json()["mount_source"] == "/private/photos"


def test_admin_status_shape(client):
    response = client.get("/admin/status")
    assert response.status_code == 200
    assert {"mount_source", "watch_root", "root_available", "models_ready", "counts", "settings"} <= response.json().keys()


def test_admin_scan_rejects_missing_root(client):
    response = client.post("/admin/scan", json={"root": "/does/not/exist"})
    assert response.status_code == 400


def test_library_inventory_reports_supported_files(tmp_path, client, monkeypatch):
    (tmp_path / "Photos Library.photoslibrary").mkdir()
    (tmp_path / "Photos Library.photoslibrary" / "original.heic").write_bytes(b"photo")
    (tmp_path / "cover.jpg").write_bytes(b"photo")
    monkeypatch.setattr("api.admin.WATCH_ROOT", tmp_path)

    response = client.get("/admin/library")

    assert response.status_code == 200
    data = response.json()
    assert data["media_files"] == 2
    assert data["extensions"] == {".heic": 1, ".jpg": 1}
    assert data["photos_libraries"][0]["name"] == "Photos Library.photoslibrary"
    assert data["catalog"] == {"assets": 0, "mounted_assets": 0, "faces": 0}
