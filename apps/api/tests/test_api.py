from core import jobs
from core.conn import connect
from core.schema import migrate


def test_health(client):
    assert client.get("/").json() == {"ok": True}


def test_jobs(client, tmp_path):
    db_path = str(tmp_path / "catalog.db")
    conn = connect(db_path)
    migrate(conn)
    jobs.push(conn, "scan", {"paths": []})
    conn.close()
    response = client.get("/jobs")
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1


def test_empty_search(client):
    response = client.get("/search")
    assert response.status_code == 200
    assert response.json() == {"results": []}
