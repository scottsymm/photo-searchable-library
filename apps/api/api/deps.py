"""FastAPI dependencies."""

from __future__ import annotations

import os
from collections.abc import Generator

import httpx

from core.conn import connect

DB_PATH = os.environ.get("PICS_DB", "catalog.db")
WORKER_URL = os.environ.get("PICS_WORKER_URL", "http://localhost:9090")


def get_conn() -> Generator:
    conn = connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


async def embed_text(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{WORKER_URL}/v1/embed-text", json={"texts": [text]})
        response.raise_for_status()
    values = response.json().get("results", [])
    if not values:
        raise RuntimeError("worker returned no text embedding")
    return values[0]
