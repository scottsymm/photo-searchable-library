import io
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


def test_transparent_thumbnail_uses_light_background(tmp_path):
    image_path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.save(image_path)

    from worker.thumbnail import image_thumbnail

    with Image.open(io.BytesIO(image_thumbnail(str(image_path)))) as thumbnail:
        assert thumbnail.getpixel((7, 7))[0] > 220
        assert thumbnail.getpixel((7, 7))[1] > 220
        assert thumbnail.getpixel((7, 7))[2] > 210


def test_import_assigns_mounted_source(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    image_path = watch / "sample.jpg"
    Image.new("RGB", (64, 64), (0, 200, 0)).save(image_path, "JPEG")
    db_path = tmp_path / "catalog.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    monkeypatch.setattr(config, "LIBRARY_ROOT", str(tmp_path / "library"))
    os.makedirs(config.LIBRARY_ROOT)
    monkeypatch.setattr("core.sources.WATCH_ROOT", watch)
    monkeypatch.setattr("core.sources.LIBRARY", tmp_path / "library")

    conn = connect(str(db_path))
    migrate(conn)
    conn.close()

    asset_id = import_one(FakeClip(), NoFaces(), str(image_path))
    conn = connect(str(db_path))
    mounted_id = conn.execute("SELECT id FROM sources WHERE kind = 'mounted_folder'").fetchone()["id"]
    assert conn.execute("SELECT source_id FROM assets WHERE id = ?", (asset_id,)).fetchone()[0] == mounted_id
