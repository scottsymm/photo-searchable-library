"""Worker configuration from environment variables."""

from __future__ import annotations

import os

DB_PATH = os.environ.get("PICS_DB", "catalog.db")
LIBRARY_ROOT = os.environ.get("PICS_LIBRARY", "library")
MODEL_NAME = os.environ.get("PICS_MODEL", "openai/clip-vit-base-patch32")
MODEL_VERSION = os.environ.get("PICS_MODEL_VERSION", "clip-vit-base-patch32-v1")
FACE_MODEL = os.environ.get("PICS_FACE_MODEL", "buffalo_l")
EMBED_PORT = int(os.environ.get("PICS_EMBED_PORT", "9090"))
