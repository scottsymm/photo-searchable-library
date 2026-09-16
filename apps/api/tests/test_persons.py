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
        link = conn.execute("SELECT source FROM person_faces WHERE person_id = ?", (person_id,)).fetchone()
    finally:
        connection_generator.close()
    assert row["name"] == "Sam"
    assert link["source"] == "cluster-confirmed"
