"""Polling watcher for explicitly enabled photo ingest."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict

from core import jobs
from core.assets import sha256_file
from core.conn import connect
from core.settings import get, set_value

from .config import DB_PATH, WATCH_POLL_SECONDS, WATCH_ROOT

logger = logging.getLogger(__name__)
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4", ".avif", ".dng"}
BATCH_SIZE = 50
LRU_SIZE = 5000


def _is_media(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in MEDIA_SUFFIXES


class PhotoWatcher(threading.Thread):
    def __init__(self, root: str = WATCH_ROOT, poll_seconds: int = WATCH_POLL_SECONDS):
        super().__init__(name="photo-watcher", daemon=True)
        self.root = root
        self.poll_seconds = poll_seconds
        self._stop_event = threading.Event()
        self._recent: OrderedDict[str, None] = OrderedDict()

    def stop(self) -> None:
        self._stop_event.set()

    def _known_hashes(self, conn) -> set[str]:
        rows = conn.execute("SELECT sha256 FROM assets WHERE deleted = 0").fetchall()
        return {row["sha256"] for row in rows}

    def _candidate_files(self) -> list[str]:
        if not os.path.isdir(self.root):
            return []
        return sorted(
            os.path.join(dirpath, name)
            for dirpath, _, filenames in os.walk(self.root)
            for name in filenames
            if _is_media(name)
        )

    def _hashes_and_paths(self) -> list[tuple[str, str]]:
        values = []
        for path in self._candidate_files():
            try:
                values.append((sha256_file(path), path))
            except OSError:
                continue
        return values

    def _enqueue(self, conn, paths: list[str]) -> int:
        for index in range(0, len(paths), BATCH_SIZE):
            jobs.push(conn, "scan", {"paths": paths[index:index + BATCH_SIZE]})
        return len(paths)

    def _enqueue_new(self) -> int:
        conn = connect(DB_PATH)
        try:
            if get(conn, "watch_enabled") != "1":
                return 0
            values = self._hashes_and_paths()
            known = self._known_hashes(conn)
            initialized = get(conn, "watch_initialized", "0") == "1"
            backfill = get(conn, "watch_backfill", "prompt")

            if not initialized:
                if backfill == "backfill":
                    paths = [path for digest, path in values if digest not in known]
                    count = self._enqueue(conn, paths)
                    set_value(conn, "watch_backfill", "done")
                else:
                    # Establish a baseline without reading/importing file contents
                    # beyond the hashes needed for future new-file detection.
                    count = 0
                for digest, _ in values:
                    self._recent[digest] = None
                set_value(conn, "watch_initialized", "1")
                return count

            paths = []
            for digest, path in values:
                if digest in known or digest in self._recent:
                    continue
                self._recent[digest] = None
                if len(self._recent) > LRU_SIZE:
                    self._recent.popitem(last=False)
                paths.append(path)
            return self._enqueue(conn, paths)
        finally:
            conn.close()

    def run(self) -> None:
        logger.info("photo watcher polling %s every %ss", self.root, self.poll_seconds)
        while not self._stop_event.wait(self.poll_seconds):
            try:
                self._enqueue_new()
            except Exception:
                logger.exception("watcher pass failed")
