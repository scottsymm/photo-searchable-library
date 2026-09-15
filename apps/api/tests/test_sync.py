def test_apple_photos_sync_request_can_be_claimed_and_completed(client):
    requested = client.post("/sources/apple-photos/sync", json={"limit": 3})
    assert requested.status_code == 200
    assert requested.json()["sync"]["status"] == "queued"

    claimed = client.post("/sources/apple-photos/sync/claim")
    assert claimed.status_code == 200
    assert claimed.json()["sync"]["status"] == "running"
    sync_id = claimed.json()["sync"]["id"]

    completed = client.post(
        f"/sources/apple-photos/sync/{sync_id}/complete",
        data={"imported_count": "3"},
    )
    assert completed.status_code == 200
    assert completed.json()["sync"]["status"] == "done"
    assert completed.json()["sync"]["imported_count"] == 3


def test_partial_apple_photos_sync_is_not_reported_as_done(client):
    requested = client.post("/sources/apple-photos/sync", json={"limit": 3})
    sync_id = requested.json()["sync"]["id"]
    client.post("/sources/apple-photos/sync/claim")
    completed = client.post(
        f"/sources/apple-photos/sync/{sync_id}/complete",
        data={"imported_count": "2", "failed_count": "1", "error": "one asset failed"},
    )
    assert completed.json()["sync"]["status"] == "partial"
    assert completed.json()["sync"]["failed_count"] == 1


def test_apple_photos_sync_does_not_queue_two_active_requests(client):
    first = client.post("/sources/apple-photos/sync", json={"limit": 2})
    second = client.post("/sources/apple-photos/sync", json={"limit": 4})
    assert first.json()["already_active"] is False
    assert second.json()["already_active"] is True
    assert second.json()["sync"]["id"] == first.json()["sync"]["id"]
