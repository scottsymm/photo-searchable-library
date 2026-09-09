import os

from PIL import Image

from core.conn import connect
from core.schema import migrate
from worker import config
from worker.pipeline import import_one


class FakeClip:
    name = "fake-clip"

    def embed_images(self, images):
        return [[0.1] * 512 for _ in images]


class NoFaces:
    def detect_and_embed(self, image):
        return []


def test_import_jpeg_without_model_download(tmp_path, monkeypatch):
    image_path = tmp_path / "sample.jpg"
    Image.new("RGB", (64, 64), (200, 0, 0)).save(image_path, "JPEG")
    db_path = tmp_path / "catalog.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    monkeypatch.setattr(config, "LIBRARY_ROOT", str(tmp_path / "library"))
    os.makedirs(config.LIBRARY_ROOT)

    conn = connect(str(db_path))
    migrate(conn)
    conn.close()

    asset_id = import_one(FakeClip(), NoFaces(), str(image_path))
    conn = connect(str(db_path))
    assert conn.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone()
    assert conn.execute("SELECT asset_id FROM content_embeds").fetchone()[0] == asset_id
