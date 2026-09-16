"""People identity and clustering-review endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from core import jobs
from .deps import get_conn

router = APIRouter()
LIBRARY_ROOT = Path(os.environ.get("PICS_LIBRARY", "library")).resolve()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ClusterRequest(BaseModel):
    eps: float = Field(default=0.30, gt=0, le=1)
    min_samples: int = Field(default=3, ge=2, le=20)


class ConfirmRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    person_id: int | None = None


class AliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=120)


class MergeRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    representative_face_id: int | None = None


class SplitRequest(BaseModel):
    face_ids: list[int] = Field(min_length=1)
    name: str | None = Field(default=None, max_length=120)


def _crop_url(face_id: int) -> str:
    return f"/persons/faces/{face_id}/crop"


def _repair_prototype(conn, person_id: int) -> None:
    person = conn.execute(
        "SELECT prototype_face_id FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    if person is None or person["prototype_face_id"] is None:
        return
    owned = conn.execute(
        "SELECT 1 FROM person_faces WHERE person_id = ? AND face_id = ?",
        (person_id, person["prototype_face_id"]),
    ).fetchone()
    if owned is None:
        replacement = conn.execute(
            "SELECT face_id FROM person_faces WHERE person_id = ? ORDER BY face_id LIMIT 1",
            (person_id,),
        ).fetchone()
        conn.execute(
            "UPDATE persons SET prototype_face_id = ? WHERE id = ?",
            (replacement["face_id"] if replacement else None, person_id),
        )


def _person_payload(conn, row):
    aliases = conn.execute(
        "SELECT id, alias FROM person_aliases WHERE person_id = ? ORDER BY id",
        (row["id"],),
    ).fetchall()
    payload = dict(row)
    payload["aliases"] = [dict(alias) for alias in aliases]
    payload["representative_url"] = (
        _crop_url(row["prototype_face_id"]) if row["prototype_face_id"] is not None else None
    )
    return payload


def _enrichment(conn):
    total = conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    ready = conn.execute("SELECT COUNT(*) FROM face_embeds").fetchone()[0]
    assets_processing = conn.execute(
        """SELECT COUNT(*) FROM assets a
        WHERE a.deleted = 0 AND NOT EXISTS (
          SELECT 1 FROM content_embeds e WHERE e.asset_id = a.id
        )"""
    ).fetchone()[0]
    job = conn.execute("SELECT status FROM jobs WHERE kind = 'cluster_faces' ORDER BY id DESC LIMIT 1").fetchone()
    run = conn.execute("SELECT id, status FROM clustering_runs ORDER BY id DESC LIMIT 1").fetchone()
    if job is not None and job["status"] in ("queued", "working"):
        status = "queued" if job["status"] == "queued" else "running"
    elif total == 0:
        status = "no_faces"
    elif ready < total:
        status = "indexing"
    elif run is not None and run["status"] == "running":
        status = "running"
    elif run is not None and run["status"] == "completed":
        status = "ready" if conn.execute("SELECT COUNT(*) FROM cluster_suggestions WHERE run_id = ?", (run["id"],)).fetchone()[0] > 0 else "completed_no_suggestions"
    else:
        status = "ready"
    return {"total": total, "embeddings_ready": ready, "embeddings_pending": max(0, total - ready), "assets_processing": assets_processing, "clustering_status": status}


def _suggestion(conn, suggestion_id: int):
    row = conn.execute(
        "SELECT * FROM cluster_suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="cluster suggestion not found")
    return row


@router.get("")
def list_persons(conn=Depends(get_conn)):
    people = conn.execute(
        """SELECT persons.id, persons.name, persons.status,
        persons.prototype_face_id, COUNT(person_faces.face_id) AS face_count
        FROM persons LEFT JOIN person_faces ON person_faces.person_id = persons.id
        GROUP BY persons.id ORDER BY face_count DESC, persons.id"""
    ).fetchall()
    suggestions = []
    suggestion_rows = conn.execute(
        """SELECT suggestions.*, runs.created_at AS run_created_at
        FROM cluster_suggestions suggestions
        JOIN clustering_runs runs ON runs.id = suggestions.run_id
        WHERE runs.id = (SELECT MAX(id) FROM clustering_runs)
        ORDER BY suggestions.face_count DESC, suggestions.id"""
    ).fetchall()
    for row in suggestion_rows:
        face_rows = conn.execute(
            """SELECT assignments.face_id, assignments.distance, faces.crop_path
            FROM face_assignments assignments
            JOIN faces ON faces.id = assignments.face_id
            WHERE assignments.suggestion_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM person_faces
                  WHERE person_faces.face_id = assignments.face_id
              )
            ORDER BY assignments.distance IS NULL, assignments.distance
            LIMIT 5""",
            (row["id"],),
        ).fetchall()
        if not face_rows:
            continue
        suggestions.append(
            {
                **dict(row),
                "representative_url": _crop_url(row["representative_face_id"]),
                "faces": [
                    {"face_id": face["face_id"], "distance": face["distance"], "crop_url": _crop_url(face["face_id"])}
                    for face in face_rows
                ],
            }
        )
    return {"persons": [_person_payload(conn, row) for row in people], "suggestions": suggestions, "enrichment": _enrichment(conn)}


@router.post("/cluster")
def queue_cluster(request: ClusterRequest | None = None, conn=Depends(get_conn)):
    request = request or ClusterRequest()
    job_id = jobs.push(
        conn,
        "cluster_faces",
        {"eps": request.eps, "min_samples": request.min_samples},
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/search")
def search_persons(q: str = "", conn=Depends(get_conn)):
    query = q.strip()
    if not query:
        return {"persons": []}
    pattern = f"%{_escape_like(query)}%"
    people = conn.execute(
        """SELECT persons.id, persons.name, persons.status,
        persons.prototype_face_id, COUNT(DISTINCT person_faces.face_id) AS face_count
        FROM persons
        LEFT JOIN person_faces ON person_faces.person_id = persons.id
        LEFT JOIN person_aliases ON person_aliases.person_id = persons.id
         WHERE persons.name LIKE ? COLLATE NOCASE ESCAPE '\\'
            OR person_aliases.alias LIKE ? COLLATE NOCASE ESCAPE '\\'
        GROUP BY persons.id
        ORDER BY face_count DESC, persons.id
        LIMIT 20""",
        (pattern, pattern),
    ).fetchall()
    return {"persons": [_person_payload(conn, row) for row in people]}


@router.post("/{person_id}/aliases")
def add_alias(person_id: int, request: AliasRequest, conn=Depends(get_conn)):
    if conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="person not found")
    alias = request.alias.strip()
    if not alias:
        raise HTTPException(status_code=422, detail="alias must not be blank")
    conn.execute(
        "INSERT OR IGNORE INTO person_aliases(person_id, alias) VALUES (?, ?)",
        (person_id, alias),
    )
    row = conn.execute(
        "SELECT id, person_id, alias FROM person_aliases WHERE person_id = ? AND alias = ?",
        (person_id, alias),
    ).fetchone()
    conn.commit()
    return dict(row)


@router.delete("/{person_id}/aliases/{alias_id}")
def remove_alias(person_id: int, alias_id: int, conn=Depends(get_conn)):
    cursor = conn.execute(
        "DELETE FROM person_aliases WHERE id = ? AND person_id = ?",
        (alias_id, person_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="alias not found")
    conn.commit()
    return {"ok": True}


@router.patch("/{person_id}")
def rename(person_id: int, request: RenameRequest, conn=Depends(get_conn)):
    cursor = conn.execute(
        "UPDATE persons SET name = ?, status = 'named' WHERE id = ?",
        (request.name, person_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="person not found")
    conn.commit()
    return {"ok": True}


@router.post("/suggestions/{suggestion_id}/confirm")
def confirm(suggestion_id: int, request: ConfirmRequest, conn=Depends(get_conn)):
    suggestion = _suggestion(conn, suggestion_id)
    if suggestion["status"] == "rejected":
        raise HTTPException(status_code=409, detail="suggestion was rejected")
    person_id = request.person_id
    if person_id is None:
        person = conn.execute(
            "INSERT INTO persons(name, status, prototype_face_id) VALUES (?, 'named', ?) RETURNING id",
            (request.name or "", suggestion["representative_face_id"]),
        ).fetchone()
        person_id = int(person["id"])
    elif conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="person not found")
    conn.execute(
        """INSERT OR IGNORE INTO person_faces(person_id, face_id, source)
        SELECT ?, face_id, 'cluster-confirmed' FROM face_assignments
        WHERE suggestion_id = ? AND status = 'suggested'""",
        (person_id, suggestion_id),
    )
    conn.execute(
        "UPDATE cluster_suggestions SET status = 'confirmed', person_id = ? WHERE id = ?",
        (person_id, suggestion_id),
    )
    conn.commit()
    return {"ok": True, "person_id": person_id}


@router.post("/suggestions/{suggestion_id}/reject")
def reject(suggestion_id: int, conn=Depends(get_conn)):
    _suggestion(conn, suggestion_id)
    conn.execute("UPDATE cluster_suggestions SET status = 'rejected' WHERE id = ?", (suggestion_id,))
    conn.execute("UPDATE face_assignments SET status = 'rejected' WHERE suggestion_id = ?", (suggestion_id,))
    conn.commit()
    return {"ok": True}


@router.post("/suggestions/{suggestion_id}/restore")
def restore(suggestion_id: int, conn=Depends(get_conn)):
    suggestion = _suggestion(conn, suggestion_id)
    if suggestion["status"] != "rejected":
        raise HTTPException(status_code=409, detail="only rejected suggestions can be restored")
    conn.execute("UPDATE cluster_suggestions SET status = 'unreviewed' WHERE id = ?", (suggestion_id,))
    conn.execute(
        "UPDATE face_assignments SET status = 'suggested' WHERE suggestion_id = ?",
        (suggestion_id,),
    )
    conn.commit()
    return {"ok": True}


@router.post("/{person_id}/faces/{face_id}")
def assign_face(person_id: int, face_id: int, conn=Depends(get_conn)):
    if conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="person not found")
    if conn.execute("SELECT id FROM faces WHERE id = ?", (face_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="face not found")
    previous_owner = conn.execute(
        "SELECT person_id FROM person_faces WHERE face_id = ?", (face_id,)
    ).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO person_faces(person_id, face_id, source) VALUES (?, ?, 'manual')",
        (person_id, face_id),
    )
    if previous_owner is not None and previous_owner["person_id"] != person_id:
        previous_prototype = conn.execute(
            "SELECT prototype_face_id FROM persons WHERE id = ?",
            (previous_owner["person_id"],),
        ).fetchone()
        target = conn.execute(
            "SELECT prototype_face_id FROM persons WHERE id = ?", (person_id,)
        ).fetchone()
        if previous_prototype["prototype_face_id"] == face_id and target["prototype_face_id"] is None:
            conn.execute(
                "UPDATE persons SET prototype_face_id = ? WHERE id = ?",
                (face_id, person_id),
            )
        _repair_prototype(conn, previous_owner["person_id"])
    conn.commit()
    return {"ok": True}


@router.post("/{person_id}/split")
def split(person_id: int, request: SplitRequest, conn=Depends(get_conn)):
    if conn.execute("SELECT id FROM persons WHERE id = ?", (person_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="person not found")
    source = conn.execute(
        "SELECT prototype_face_id FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    person = conn.execute(
        "INSERT INTO persons(name, status) VALUES (?, 'new') RETURNING id", (request.name or "",)
    ).fetchone()
    new_id = int(person["id"])
    for face_id in request.face_ids:
        conn.execute("DELETE FROM person_faces WHERE person_id = ? AND face_id = ?", (person_id, face_id))
        conn.execute(
            "INSERT OR IGNORE INTO person_faces(person_id, face_id, source) VALUES (?, ?, 'manual-split')",
            (new_id, face_id),
        )
    if source["prototype_face_id"] in request.face_ids:
        conn.execute(
            "UPDATE persons SET prototype_face_id = ? WHERE id = ?",
            (source["prototype_face_id"], new_id),
        )
    _repair_prototype(conn, person_id)
    conn.commit()
    return {"ok": True, "person_id": new_id}


@router.post("/{keep_id}/merge/{remove_id}")
def merge(keep_id: int, remove_id: int, request: MergeRequest | None = None, conn=Depends(get_conn)):
    if keep_id == remove_id:
        raise HTTPException(status_code=400, detail="cannot merge a person into itself")
    if conn.execute("SELECT id FROM persons WHERE id = ?", (keep_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="target person not found")
    if conn.execute("SELECT id FROM persons WHERE id = ?", (remove_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="source person not found")
    request = request or MergeRequest()
    final_name = request.name.strip() if request.name is not None else None
    if request.name is not None and not final_name:
        raise HTTPException(status_code=422, detail="name must not be blank")
    keep = conn.execute("SELECT name, prototype_face_id FROM persons WHERE id = ?", (keep_id,)).fetchone()
    remove = conn.execute("SELECT name FROM persons WHERE id = ?", (remove_id,)).fetchone()
    if request.representative_face_id is not None and conn.execute(
        "SELECT 1 FROM person_faces WHERE person_id IN (?, ?) AND face_id = ?",
        (keep_id, remove_id, request.representative_face_id),
    ).fetchone() is None:
        raise HTTPException(status_code=400, detail="representative face does not belong to merged people")

    conn.execute(
        """INSERT OR IGNORE INTO person_faces(person_id, face_id, source)
        SELECT ?, face_id, 'manual-merge' FROM person_faces WHERE person_id = ?""",
        (keep_id, remove_id),
    )
    conn.execute("DELETE FROM person_faces WHERE person_id = ?", (remove_id,))
    conn.execute("UPDATE cluster_suggestions SET person_id = ? WHERE person_id = ?", (keep_id, remove_id))
    names_to_preserve = [remove["name"], keep["name"] if final_name is not None else None]
    aliases = conn.execute("SELECT alias FROM person_aliases WHERE person_id = ?", (remove_id,)).fetchall()
    for alias in [*names_to_preserve, *(row["alias"] for row in aliases)]:
        if alias and alias != (final_name if final_name is not None else keep["name"]):
            conn.execute("INSERT OR IGNORE INTO person_aliases(person_id, alias) VALUES (?, ?)", (keep_id, alias))
    if final_name is not None:
        conn.execute("UPDATE persons SET name = ?, status = 'named' WHERE id = ?", (final_name, keep_id))
    if "representative_face_id" in request.model_fields_set:
        conn.execute(
            "UPDATE persons SET prototype_face_id = ? WHERE id = ?",
            (request.representative_face_id, keep_id),
        )
    conn.execute("DELETE FROM persons WHERE id = ?", (remove_id,))
    conn.commit()
    return {"ok": True}


@router.get("/faces/{face_id}/crop")
def face_crop(face_id: int, conn=Depends(get_conn)):
    row = conn.execute("SELECT crop_path FROM faces WHERE id = ?", (face_id,)).fetchone()
    if row is None or not row["crop_path"]:
        raise HTTPException(status_code=404, detail="face crop not found")
    crop_path = Path(row["crop_path"]).resolve()
    if LIBRARY_ROOT not in crop_path.parents:
        raise HTTPException(status_code=400, detail="invalid crop path")
    try:
        return Response(content=crop_path.read_bytes(), media_type="image/jpeg")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="face crop not found") from error
