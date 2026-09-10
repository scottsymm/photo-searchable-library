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
