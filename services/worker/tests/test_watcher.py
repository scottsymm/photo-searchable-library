from core.conn import connect
from core.schema import migrate
from core.settings import set_value
from worker.watcher import PhotoWatcher


def _db(tmp_path) -> str:
    path = str(tmp_path / "catalog.db")
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


def test_disabled_watcher_does_not_enqueue(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    root = tmp_path / "photos"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"photo")
    monkeypatch.setattr("worker.watcher.DB_PATH", db_path)
    PhotoWatcher(root=str(root))._enqueue_new()
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_prompt_initializes_baseline_without_import(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    root = tmp_path / "photos"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"photo")
    monkeypatch.setattr("worker.watcher.DB_PATH", db_path)
    conn = connect(db_path)
    set_value(conn, "watch_enabled", "1")
    conn.close()
    PhotoWatcher(root=str(root))._enqueue_new()
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM settings WHERE key='watch_initialized'").fetchone()[0] == "1"


def test_new_file_enqueues_once_after_baseline(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    root = tmp_path / "photos"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"photo")
    monkeypatch.setattr("worker.watcher.DB_PATH", db_path)
    conn = connect(db_path)
    set_value(conn, "watch_enabled", "1")
    conn.close()
    watcher = PhotoWatcher(root=str(root))
    watcher._enqueue_new()
    (root / "b.jpg").write_bytes(b"new photo")
    watcher._enqueue_new()
    watcher._enqueue_new()
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
