def test_full_sync_request_and_known_asset_lookup(client):
    requested = client.post("/sources/apple-photos/sync", json={"full": True})
    assert requested.status_code == 200
    assert requested.json()["sync"]["full_sync"] == 1

    response = client.post(
        "/sources/apple-photos/assets/known",
        json={"source_asset_ids": ["missing", "also-missing"]},
    )
    assert response.status_code == 200
    assert response.json()["source_asset_ids"] == []
