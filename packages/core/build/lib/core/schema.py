"""Catalog schema and migration entry point."""

from __future__ import annotations

import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mime TEXT NOT NULL,
  taken_at TEXT,
  gps_lat REAL,
  gps_lon REAL,
  place_city TEXT,
  place_country TEXT,
  thumbnail_id INTEGER,
  stripped INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  extra TEXT
);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  bytes BLOB,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persons (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  prototype_face_id INTEGER,
  status TEXT NOT NULL DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS faces (
  id INTEGER PRIMARY KEY,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  crop_path TEXT,
  bbox TEXT NOT NULL,
  cluster_id INTEGER REFERENCES persons(id)
);

CREATE TABLE IF NOT EXISTS content_embeds (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  model_version TEXT NOT NULL,
  embed BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS face_embeds (
  face_id INTEGER PRIMARY KEY REFERENCES faces(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  embed BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (asset_id, tag)
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  progress REAL NOT NULL DEFAULT 0,
  error TEXT,
  params TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS assets_taken_at_idx ON assets(taken_at);
CREATE INDEX IF NOT EXISTS assets_place_idx ON assets(place_city, place_country);
CREATE VIRTUAL TABLE IF NOT EXISTS vec0_content USING vec0(
  content_embed float[512]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec0_face USING vec0(
  face_embed float[512]
);
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '1')"
    )
    conn.commit()
