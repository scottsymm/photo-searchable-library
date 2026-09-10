"""Run the internal embed API and SQLite job worker in one container."""

from __future__ import annotations

import threading
import time

import uvicorn

from . import embed_api
from .config import EMBED_PORT, FACE_MODEL, MODEL_NAME, WATCHER_ENABLED
from .faces import FaceEngine
from .models import ClipEmbedder
from .run import drain_once
from .watcher import PhotoWatcher


def main() -> None:
    clip = ClipEmbedder(MODEL_NAME)
    face_engine = FaceEngine(FACE_MODEL)
    embed_api.embedder = clip
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(embed_api.app,),
        kwargs={"host": "0.0.0.0", "port": EMBED_PORT, "log_level": "info"},
        daemon=True,
    )
    server_thread.start()
    if WATCHER_ENABLED:
        PhotoWatcher().start()
    while True:
        if not drain_once(clip, face_engine):
            time.sleep(2)


if __name__ == "__main__":
    main()
