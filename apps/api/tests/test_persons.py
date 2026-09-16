import json

from core.conn import connect
from core.schema import migrate


def test_cluster_job_can_be_queued(client, tmp_path):
    response = client.post("/persons/cluster", json={"eps": 0.3, "min_samples": 3})
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_cluster_job_uses_defaults_without_request_body(client):
    response = client.post("/persons/cluster")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_people_reports_face_enrichment_state(client):
    response = client.get("/persons")
    assert response.status_code == 200
    assert response.json()["enrichment"] == {
        "total": 0,
        "embeddings_ready": 0,
        "embeddings_pending": 0,
        "assets_processing": 0,
        "clustering_status": "no_faces",
    }


def test_confirm_suggestion_creates_durable_person_link(client, tmp_path):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (1, '/tmp/a.jpg', ?, 1, 'image/jpeg')", ("a" * 64,))
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (1, 1, '[]')")
        conn.execute("INSERT INTO clustering_runs(id, model, model_version, algorithm, metric, eps, min_samples, status) VALUES (1, 'test', '1', 'dbscan', 'cosine', .3, 3, 'completed')")
        conn.execute("INSERT INTO cluster_suggestions(id, run_id, cluster_key, representative_face_id, face_count, confidence) VALUES (1, 1, 0, 1, 1, 'high')")
        conn.execute("INSERT INTO face_assignments(run_id, face_id, suggestion_id, distance) VALUES (1, 1, 1, .1)")
        conn.commit()
    finally:
        connection_generator.close()

    response = client.post("/persons/suggestions/1/confirm", json={"name": "Sam"})
    assert response.status_code == 200
    person_id = response.json()["person_id"]
    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        row = conn.execute("SELECT name FROM persons WHERE id = ?", (person_id,)).fetchone()
        prototype = conn.execute("SELECT prototype_face_id FROM persons WHERE id = ?", (person_id,)).fetchone()
        link = conn.execute("SELECT source FROM person_faces WHERE person_id = ?", (person_id,)).fetchone()
    finally:
        connection_generator.close()
    assert row["name"] == "Sam"
    assert prototype["prototype_face_id"] == 1
    assert link["source"] == "cluster-confirmed"


def test_confirm_suggestion_can_link_to_existing_person(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (1, '/tmp/a.jpg', ?, 1, 'image/jpeg')", ("a" * 64,))
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (2, '/tmp/b.jpg', ?, 1, 'image/jpeg')", ("b" * 64,))
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (1, 1, '[]')")
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (2, 2, '[]')")
        conn.execute("INSERT INTO persons(id, name, prototype_face_id) VALUES (1, 'Sam', 1)")
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 1, 'manual')")
        conn.execute("INSERT INTO clustering_runs(id, model, model_version, algorithm, metric, eps, min_samples, status) VALUES (1, 'test', '1', 'dbscan', 'cosine', .3, 3, 'completed')")
        conn.execute("INSERT INTO cluster_suggestions(id, run_id, cluster_key, representative_face_id, face_count, confidence) VALUES (1, 1, 0, 2, 1, 'high')")
        conn.execute("INSERT INTO face_assignments(run_id, face_id, suggestion_id, distance) VALUES (1, 2, 1, .1)")
        conn.commit()
    finally:
        connection_generator.close()

    response = client.post("/persons/suggestions/1/confirm", json={"person_id": 1})

    assert response.status_code == 200
    assert response.json()["person_id"] == 1
    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        assert conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 1
        person = conn.execute("SELECT name, prototype_face_id FROM persons WHERE id = 1").fetchone()
        assert (person["name"], person["prototype_face_id"]) == ("Sam", 1)
        assert conn.execute("SELECT COUNT(*) FROM person_faces WHERE person_id = 1").fetchone()[0] == 2
    finally:
        connection_generator.close()


def test_rejected_suggestion_can_be_restored(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (1, '/tmp/a.jpg', ?, 1, 'image/jpeg')", ("a" * 64,))
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (1, 1, '[]')")
        conn.execute("INSERT INTO clustering_runs(id, model, model_version, algorithm, metric, eps, min_samples, status) VALUES (1, 'test', '1', 'dbscan', 'cosine', .3, 3, 'completed')")
        conn.execute("INSERT INTO cluster_suggestions(id, run_id, cluster_key, representative_face_id, face_count, confidence, status) VALUES (1, 1, 0, 1, 1, 'high', 'rejected')")
        conn.execute("INSERT INTO face_assignments(run_id, face_id, suggestion_id, distance, status) VALUES (1, 1, 1, .1, 'rejected')")
        conn.commit()
    finally:
        connection_generator.close()

    response = client.post("/persons/suggestions/1/restore")

    assert response.status_code == 200
    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        assert conn.execute("SELECT status FROM cluster_suggestions WHERE id = 1").fetchone()[0] == "unreviewed"
        assert conn.execute("SELECT status FROM face_assignments WHERE suggestion_id = 1").fetchone()[0] == "suggested"
    finally:
        connection_generator.close()


def test_person_search_matches_aliases_and_is_case_insensitive(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO persons(id, name) VALUES (1, 'Robert')")
        conn.execute("INSERT INTO person_aliases(person_id, alias) VALUES (1, 'Dad')")
        conn.commit()
    finally:
        connection_generator.close()

    response = client.get("/persons/search", params={"q": "DA"})

    assert response.status_code == 200
    assert response.json()["persons"][0]["name"] == "Robert"
    assert response.json()["persons"][0]["aliases"][0]["alias"] == "Dad"
    assert client.get("/persons/search", params={"q": "   "}).json() == {"persons": []}


def test_people_response_includes_aliases_and_representative(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (1, '/tmp/a.jpg', ?, 1, 'image/jpeg')", ("a" * 64,))
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (1, 1, '[]')")
        conn.execute("INSERT INTO persons(id, name, prototype_face_id) VALUES (1, 'Sam', 1)")
        conn.execute("INSERT INTO person_aliases(person_id, alias) VALUES (1, 'Samuel')")
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 1, 'manual')")
        conn.execute("INSERT INTO persons(id, name) VALUES (2, 'Unknown')")
        conn.commit()
    finally:
        connection_generator.close()

    people = {person["id"]: person for person in client.get("/persons").json()["persons"]}

    assert people[1]["prototype_face_id"] == 1
    assert people[1]["representative_url"] == "/persons/faces/1/crop"
    assert people[1]["aliases"][0]["alias"] == "Samuel"
    assert people[2]["representative_url"] is None


def test_alias_crud(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO persons(id, name) VALUES (1, 'Robert')")
        conn.commit()
    finally:
        connection_generator.close()

    created = client.post("/persons/1/aliases", json={"alias": "  Dad  "})
    duplicate = client.post("/persons/1/aliases", json={"alias": "Dad"})

    assert created.status_code == 200
    assert duplicate.status_code == 200
    assert created.json()["id"] == duplicate.json()["id"]
    assert client.delete(f"/persons/1/aliases/{created.json()['id']}").json() == {"ok": True}
    assert client.delete(f"/persons/1/aliases/{created.json()['id']}").status_code == 404


def test_merge_preserves_aliases_and_applies_choices(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        for face_id in (1, 2):
            conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (?, ?, ?, 1, 'image/jpeg')", (face_id, f"/tmp/{face_id}.jpg", str(face_id) * 64))
            conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (?, ?, '[]')", (face_id, face_id))
        conn.execute("INSERT INTO persons(id, name, prototype_face_id) VALUES (1, 'Young Dad', 1)")
        conn.execute("INSERT INTO persons(id, name, prototype_face_id) VALUES (2, 'Dad', 2)")
        conn.execute("INSERT INTO person_aliases(person_id, alias) VALUES (2, 'Father')")
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 1, 'cluster-confirmed')")
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (2, 2, 'cluster-confirmed')")
        conn.commit()
    finally:
        connection_generator.close()

    response = client.post("/persons/1/merge/2", json={"name": "Dad", "representative_face_id": 2})

    assert response.status_code == 200
    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        person = conn.execute("SELECT name, prototype_face_id FROM persons WHERE id = 1").fetchone()
        aliases = {row["alias"] for row in conn.execute("SELECT alias FROM person_aliases WHERE person_id = 1")}
        faces = {row["face_id"] for row in conn.execute("SELECT face_id FROM person_faces WHERE person_id = 1")}
        assert conn.execute("SELECT id FROM persons WHERE id = 2").fetchone() is None
    finally:
        connection_generator.close()
    assert (person["name"], person["prototype_face_id"]) == ("Dad", 2)
    assert {"Young Dad", "Father"} <= aliases
    assert faces == {1, 2}


def test_merge_rejects_unowned_representative_and_self_merge(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO persons(id, name) VALUES (1, 'One')")
        conn.execute("INSERT INTO persons(id, name) VALUES (2, 'Two')")
        conn.commit()
    finally:
        connection_generator.close()

    assert client.post("/persons/1/merge/1", json={}).status_code == 400
    assert client.post("/persons/1/merge/2", json={"representative_face_id": 999}).status_code == 400


def test_merge_can_clear_representative(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (1, '/tmp/1.jpg', ?, 1, 'image/jpeg')", ("1" * 64,))
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (1, 1, '[]')")
        conn.execute("INSERT INTO persons(id, name, prototype_face_id) VALUES (1, 'One', 1)")
        conn.execute("INSERT INTO persons(id, name) VALUES (2, 'Two')")
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 1, 'manual')")
        conn.commit()
    finally:
        connection_generator.close()

    response = client.post("/persons/1/merge/2", json={"representative_face_id": None})

    assert response.status_code == 200
    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        assert conn.execute("SELECT prototype_face_id FROM persons WHERE id = 1").fetchone()[0] is None
    finally:
        connection_generator.close()
