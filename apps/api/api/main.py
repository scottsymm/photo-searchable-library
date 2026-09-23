"""FastAPI application entry point."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.schema import migrate

from . import admin, catalog, jobs, persons, places, search, sources, uploads
from .deps import DB_PATH
from core.conn import connect

app = FastAPI(title="Pics API", version="0.1.0")
web_port = os.environ.get("PICS_WEB_PORT", "3001")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        f"http://localhost:{web_port}",
        f"http://127.0.0.1:{web_port}",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

with connect(DB_PATH) as _connection:
    migrate(_connection)

app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
app.include_router(uploads.router, prefix="/assets", tags=["assets"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(persons.router, prefix="/persons", tags=["persons"])
app.include_router(places.router, prefix="/places", tags=["places"])
app.include_router(sources.router, prefix="/sources", tags=["sources"])


@app.get("/")
def health():
    return {"ok": True}
