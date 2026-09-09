"""People cluster review endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .deps import get_conn

router = APIRouter()


@router.get("")
def list_persons(conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT persons.id, persons.name, persons.status, COUNT(faces.id) AS face_count
        FROM persons LEFT JOIN faces ON faces.cluster_id = persons.id
        GROUP BY persons.id ORDER BY face_count DESC"""
    ).fetchall()
    return {"persons": [dict(row) for row in rows]}


class RenameRequest(BaseModel):
    name: str


@router.patch("/{person_id}")
def rename(person_id: int, request: RenameRequest, conn=Depends(get_conn)):
    conn.execute("UPDATE persons SET name = ?, status = 'named' WHERE id = ?", (request.name, person_id))
    conn.commit()
    return {"ok": True}


@router.post("/{keep_id}/merge/{remove_id}")
def merge(keep_id: int, remove_id: int, conn=Depends(get_conn)):
    conn.execute("UPDATE faces SET cluster_id = ? WHERE cluster_id = ?", (keep_id, remove_id))
    conn.execute("DELETE FROM persons WHERE id = ?", (remove_id,))
    conn.commit()
    return {"ok": True}
