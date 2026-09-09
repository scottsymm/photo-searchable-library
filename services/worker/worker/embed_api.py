"""Internal HTTP service for query embeddings."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import MODEL_NAME, MODEL_VERSION
from .models import ClipEmbedder

app = FastAPI(title="pics-worker")
embedder: ClipEmbedder | None = None


class TextRequest(BaseModel):
    texts: list[str]


@app.on_event("startup")
    global embedder
    embedder = ClipEmbedder(MODEL_NAME)


@app.get("/v1/status")
    return {"ok": embedder is not None, "model": MODEL_NAME, "version": MODEL_VERSION}


@app.post("/v1/embed-text")
    if embedder is None:
        raise HTTPException(status_code=503, detail="models_pending")
    return {"model": MODEL_NAME, "version": MODEL_VERSION, "results": embedder.embed_text(request.texts)}
