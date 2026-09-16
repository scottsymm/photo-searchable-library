import array
import sqlite3

from core.clustering import run_clustering
from core.conn import connect
from core.schema import migrate


def _db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrate(conn)
    return conn


def _add_face(conn: sqlite3.Connection, face_id: int, vector: list[float]) -> None:
    conn.execute(
        "INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (?, ?, ?, 1, 'image/jpeg')",
        (face_id, f"/tmp/{face_id}.jpg", str(face_id) * 64),
    )
    conn.execute(
        "INSERT INTO faces(id, asset_id, bbox) VALUES (?, ?, '[]')",
        (face_id, face_id),
    )
    conn.execute(
        "INSERT INTO face_embeds(face_id, model, embed) VALUES (?, 'test', ?)",
        (face_id, array.array("f", vector).tobytes()),
    )
    conn.commit()


def test_dbscan_persists_suggestion_and_noise():
    conn = _db()
    _add_face(conn, 1, [1.0] * 512)
    _add_face(conn, 2, [1.0] * 512)
    _add_face(conn, 3, [-1.0] * 512)
    run_id = run_clustering(conn, model="test", model_version="1", eps=0.1, min_samples=2)
    assert conn.execute("SELECT status FROM clustering_runs WHERE id=?", (run_id,)).fetchone()[0] == "completed"
    assert conn.execute("SELECT COUNT(*) FROM cluster_suggestions WHERE run_id=?", (run_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT status FROM face_assignments WHERE face_id=3").fetchone()[0] == "noise"


def test_dbscan_skips_faces_already_assigned_to_people():
    conn = _db()
    for face_id in (1, 2, 3, 4):
        _add_face(conn, face_id, [1.0] * 512)
    conn.execute("INSERT INTO persons(id, name) VALUES (1, 'Sam')")
    conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 1, 'cluster-confirmed')")
    conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 2, 'cluster-confirmed')")
    conn.commit()

    run_id = run_clustering(conn, model="test", model_version="1", eps=0.1, min_samples=2)

    suggestion = conn.execute(
        "SELECT face_count FROM cluster_suggestions WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert suggestion[0] == 2
    assert {row[0] for row in conn.execute(
        "SELECT face_id FROM face_assignments WHERE run_id = ? AND status = 'suggested'", (run_id,)
    )} == {3, 4}
