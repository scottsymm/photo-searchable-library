"""Single worker process that drains the SQLite jobs table."""

from __future__ import annotations

import json
import time

from core import jobs
from core.conn import connect
from core.schema import migrate

from .config import DB_PATH, FACE_MODEL, MODEL_NAME
from .faces import FaceEngine
from .models import ClipEmbedder
from .pipeline import import_one
from core.clustering import run_clustering


def drain_once(clip, face_engine) -> bool:
    conn = connect(DB_PATH)
    migrate(conn)
    job = jobs.claim(conn)
    if job is None:
        conn.close()
        return False
    try:
        params = json.loads(job["params"] or "{}")
        if job["kind"] in {"import", "scan"}:
            paths = params.get("paths", [])
            for index, path in enumerate(paths):
                import_one(clip, face_engine, path)
                jobs.set_progress(conn, job["id"], (index + 1) / max(1, len(paths)))
        elif job["kind"] == "cluster_faces":
            params = json.loads(job["params"] or "{}")
            run_clustering(
                conn,
                model=params.get("model", "buffalo_l"),
                model_version=params.get("model_version", "buffalo_l-v1"),
                eps=float(params.get("eps", 0.30)),
                min_samples=int(params.get("min_samples", 3)),
            )
        jobs.complete(conn, job["id"])
    except Exception as error:
        jobs.fail(conn, job["id"], str(error))
    finally:
        conn.close()
    return True


def main() -> None:
    clip = ClipEmbedder(MODEL_NAME)
    face_engine = FaceEngine(FACE_MODEL)
    while True:
        if not drain_once(clip, face_engine):
            time.sleep(2)


if __name__ == "__main__":
    main()
