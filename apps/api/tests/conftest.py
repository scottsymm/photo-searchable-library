import pytest
from fastapi.testclient import TestClient

from core.conn import connect
from core.schema import migrate


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "catalog.db")
    monkeypatch.setattr("api.deps.DB_PATH", db_path)
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    from api.deps import get_conn
    from api.main import app

    def dependency():
        current = connect(db_path)
        try:
            yield current
        finally:
            current.close()

    app.dependency_overrides[get_conn] = dependency
    yield TestClient(app)
    app.dependency_overrides.clear()
