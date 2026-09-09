"""Job progress endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from .deps import get_conn

router = APIRouter()


@router.get("")
def list_jobs(conn=Depends(get_conn)):
    rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
    return {"jobs": [dict(row) for row in rows]}


@router.get("/{job_id}")
def get_job(job_id: int, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(row)
