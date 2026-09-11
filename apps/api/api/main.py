"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.schema import migrate

from . import admin, jobs, persons, places, search, uploads
from .deps import DB_PATH
from core.conn import connect

app = FastAPI(title="Pics API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

with connect(DB_PATH) as _connection:
    migrate(_connection)

app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(uploads.router, prefix="/assets", tags=["assets"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(persons.router, prefix="/persons", tags=["persons"])
app.include_router(places.router, prefix="/places", tags=["places"])


@app.get("/")
def health():
    return {"ok": True}
