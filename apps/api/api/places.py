"""Place aggregation endpoint."""

from fastapi import APIRouter, Depends

from .deps import get_conn

router = APIRouter()


@router.get("")
def list_places(limit: int = 50, conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT place_city, place_country, COUNT(*) AS count
        FROM assets WHERE deleted = 0 AND place_city IS NOT NULL
        GROUP BY place_city, place_country ORDER BY count DESC LIMIT ?""",
        (max(1, min(limit, 200)),),
    ).fetchall()
    return {"places": [dict(row) for row in rows]}
