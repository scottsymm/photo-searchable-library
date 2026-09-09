import pytest
from fastapi.testclient import TestClient

from core import jobs
from core.conn import connect
from core.schema import migrate


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "catalog.db")
    monkeypatch.setattr("api.deps.DB_PATH", db_path)
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    from api.main import app
    from api.deps import get_conn

    def dependency():
        current = connect(db_path)
        try:
            yield current
        finally:
            current.close()

    app.dependency_overrides[get_conn] = dependency
    yield TestClient(app)
    app.dependency_overrides.clear()


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
