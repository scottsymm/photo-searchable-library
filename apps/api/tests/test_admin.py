from pathlib import Path

import pytest

import api.admin


@pytest.fixture(autouse=True)
def _clear_inventory_cache():
    api.admin._clear_inventory_cache()


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
    assert data["media_files"] == 1
    assert data["extensions"] == {".jpg": 1}
    assert data["photos_libraries"][0]["name"] == "Photos Library.photoslibrary"
    assert data["catalog"] == {"assets": 0, "mounted_assets": 0, "faces": 0}


def test_library_inventory_reuses_cached_scan(client, monkeypatch):
    original = api.admin._library_inventory
    calls = []

    def tracking():
        calls.append(1)
        return original()

    monkeypatch.setattr(api.admin, "_library_inventory", tracking)

    r1 = client.get("/admin/library")
    assert r1.status_code == 200
    r2 = client.get("/admin/library")
    assert r2.status_code == 200

    assert len(calls) == 1
    assert r1.json() == r2.json()


def test_library_inventory_escapes_like_wildcards(client, monkeypatch):
    from api.deps import get_conn

    monkeypatch.setattr(api.admin, "WATCH_ROOT", Path("/media/Photos_2026"))
    generator = client.app.dependency_overrides[get_conn]()
    conn = next(generator)
    try:
        conn.executemany(
            "INSERT INTO assets(path, sha256, size_bytes, mime) VALUES (?, ?, 1, 'image/jpeg')",
            [
                ("/media/Photos_2026/inside.jpg", "a" * 64),
                ("/media/PhotosX2026/outside_match.jpg", "b" * 64),
            ],
        )
        conn.commit()
    finally:
        generator.close()

    response = client.get("/admin/library")
    assert response.status_code == 200
    assert response.json()["catalog"]["mounted_assets"] == 1


def test_library_inventory_cache_resets_when_root_changes(client, monkeypatch, tmp_path_factory):
    root1 = tmp_path_factory.mktemp("root1")
    root2 = tmp_path_factory.mktemp("root2")
    original = api.admin._library_inventory
    calls = []

    def tracking():
        calls.append(1)
        return original()

    monkeypatch.setattr(api.admin, "_library_inventory", tracking)

    monkeypatch.setattr(api.admin, "WATCH_ROOT", root1)
    r1 = client.get("/admin/library")
    assert r1.status_code == 200

    monkeypatch.setattr(api.admin, "WATCH_ROOT", root2)
    r2 = client.get("/admin/library")
    assert r2.status_code == 200

    assert len(calls) == 2
