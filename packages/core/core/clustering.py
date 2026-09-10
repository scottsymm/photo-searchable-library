"""Conservative, reproducible clustering of face embeddings."""

from __future__ import annotations

import array
import sqlite3
from collections import defaultdict

import numpy as np
from sklearn.cluster import DBSCAN


def _vector(blob: bytes) -> np.ndarray:
    return np.asarray(array.array("f", blob), dtype=np.float32)


def _centroid(vectors: np.ndarray) -> np.ndarray:
    center = vectors.mean(axis=0)
    norm = np.linalg.norm(center)
    return center / norm if norm else center


def run_clustering(
    conn: sqlite3.Connection,
    *,
    model: str,
    model_version: str,
    eps: float = 0.30,
    min_samples: int = 3,
) -> int:
    """Persist one DBSCAN suggestion run and return its ID."""
    if eps <= 0 or min_samples < 2:
        raise ValueError("eps must be positive and min_samples must be at least 2")

    cur = conn.execute(
        """INSERT INTO clustering_runs
        (model, model_version, algorithm, metric, eps, min_samples)
        VALUES (?, ?, 'dbscan', 'cosine', ?, ?)""",
        (model, model_version, eps, min_samples),
    )
    run_id = int(cur.lastrowid)
    rows = conn.execute(
        "SELECT face_id, embed FROM face_embeds ORDER BY face_id"
    ).fetchall()
    if not rows:
        conn.execute(
            "UPDATE clustering_runs SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (run_id,),
        )
        conn.commit()
        return run_id

    face_ids = [int(row["face_id"]) for row in rows]
    embeddings = np.asarray([_vector(row["embed"]) for row in rows], dtype=np.float32)
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine").fit_predict(embeddings)
    groups: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        if int(label) >= 0:
            groups[int(label)].append(index)

    suggestion_ids: dict[int, int] = {}
    for label, indices in sorted(groups.items()):
        center = _centroid(embeddings[indices])
        distances = 1 - np.dot(embeddings[indices], center)
        representative_index = indices[int(np.argmin(distances))]
        confidence = "high" if min_samples >= 3 else "candidate"
        suggestion = conn.execute(
            """INSERT INTO cluster_suggestions
            (run_id, cluster_key, representative_face_id, face_count, confidence)
            VALUES (?, ?, ?, ?, ?)""",
            (run_id, label, face_ids[representative_index], len(indices), confidence),
        )
        suggestion_ids[label] = int(suggestion.lastrowid)
        for index in indices:
            distance = float(1 - np.dot(embeddings[index], center))
            conn.execute(
                """INSERT INTO face_assignments
                (run_id, face_id, suggestion_id, distance, status)
                VALUES (?, ?, ?, ?, 'suggested')""",
                (run_id, face_ids[index], suggestion_ids[label], distance),
            )

    for index, label in enumerate(labels):
        if int(label) == -1:
            conn.execute(
                """INSERT INTO face_assignments
                (run_id, face_id, distance, status) VALUES (?, ?, NULL, 'noise')""",
                (run_id, face_ids[index]),
            )

    conn.execute(
        """UPDATE clustering_runs
        SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?""",
        (run_id,),
    )
    conn.commit()
    return run_id


def latest_suggestions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT suggestions.*, runs.created_at AS run_created_at
        FROM cluster_suggestions suggestions
        JOIN clustering_runs runs ON runs.id = suggestions.run_id
        WHERE runs.id = (SELECT MAX(id) FROM clustering_runs)
        ORDER BY suggestions.face_count DESC, suggestions.id"""
    ).fetchall()
