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


def test_admin_status_shape(client):
    response = client.get("/admin/status")
    assert response.status_code == 200
    assert {"watch_root", "root_available", "models_ready", "counts", "settings"} <= response.json().keys()


def test_admin_scan_rejects_missing_root(client):
    response = client.post("/admin/scan", json={"root": "/does/not/exist"})
    assert response.status_code == 400
