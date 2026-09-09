"""FastAPI application entry point."""

from fastapi import FastAPI

from core.schema import migrate

from . import jobs, persons, places, search, uploads
from .deps import DB_PATH
from core.conn import connect

app = FastAPI(title="Pics API", version="0.1.0")

with connect(DB_PATH) as _connection:
    migrate(_connection)

app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(uploads.router, prefix="/assets", tags=["assets"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(persons.router, prefix="/persons", tags=["persons"])
app.include_router(places.router, prefix="/places", tags=["places"])


@app.get("/")
def health():
    return {"ok": True}
