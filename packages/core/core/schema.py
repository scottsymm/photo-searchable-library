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
  source_id INTEGER REFERENCES sources(id),
  source_asset_id TEXT,
  original_filename TEXT,
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

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'not_connected',
  authorization_state TEXT,
  last_sync_at TEXT,
  last_error TEXT,
  asset_count INTEGER NOT NULL DEFAULT 0,
  imported_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind)
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

CREATE TABLE IF NOT EXISTS clustering_runs (
  id INTEGER PRIMARY KEY,
  model TEXT NOT NULL,
  model_version TEXT NOT NULL,
  algorithm TEXT NOT NULL,
  metric TEXT NOT NULL,
  eps REAL NOT NULL,
  min_samples INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS cluster_suggestions (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES clustering_runs(id) ON DELETE CASCADE,
  cluster_key INTEGER NOT NULL,
  representative_face_id INTEGER REFERENCES faces(id),
  face_count INTEGER NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'candidate',
  status TEXT NOT NULL DEFAULT 'unreviewed',
  person_id INTEGER REFERENCES persons(id),
  UNIQUE(run_id, cluster_key)
);

CREATE TABLE IF NOT EXISTS face_assignments (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES clustering_runs(id) ON DELETE CASCADE,
  face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
  suggestion_id INTEGER REFERENCES cluster_suggestions(id) ON DELETE CASCADE,
  distance REAL,
  status TEXT NOT NULL DEFAULT 'suggested',
  UNIQUE(run_id, face_id)
);

CREATE TABLE IF NOT EXISTS person_faces (
  person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(person_id, face_id)
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE UNIQUE INDEX IF NOT EXISTS assets_source_asset_idx
ON assets(source_id, source_asset_id)
WHERE source_id IS NOT NULL AND source_asset_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS face_assignments_face_idx ON face_assignments(face_id);
CREATE INDEX IF NOT EXISTS person_faces_face_idx ON person_faces(face_id);
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
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '3')"
    )
    from .settings import seed
    seed(conn)
    conn.execute(
        """INSERT OR IGNORE INTO sources(kind, display_name, status)
        VALUES ('apple_photos', 'Apple Photos', 'not_connected')"""
    )
    conn.commit()
