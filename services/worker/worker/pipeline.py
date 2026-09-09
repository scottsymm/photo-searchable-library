"""Process one media file into the catalog."""

from __future__ import annotations

import io
import json
import os
import uuid

import numpy as np
from PIL import Image

from core.assets import sha256_file, upsert_asset
from core.conn import connect
from core.embeds import add_content, add_face
from core.geo import reverse as reverse_geocode

from . import config
from .exif import extract
from .thumbnail import thumbnail


def import_one(clip, face_engine, source_path: str) -> int:
    metadata = extract(source_path)
    mime = metadata.get("mime", "application/octet-stream")
    thumb = thumbnail(source_path, mime)
    gps_lat = metadata.get("gps_lat")
    gps_lon = metadata.get("gps_lon")
    city, country = (
        reverse_geocode(gps_lat, gps_lon)
        if gps_lat is not None and gps_lon is not None
        else (None, None)
    )

    with connect(config.DB_PATH) as conn:
        image = Image.open(io.BytesIO(thumb)).convert("RGB")
        asset_id = upsert_asset(
            conn,
            path=os.path.abspath(source_path),
            sha256=sha256_file(source_path),
            size_bytes=os.path.getsize(source_path),
            mime=mime,
            taken_at=metadata.get("taken_at"),
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            place_city=city,
            place_country=country,
            thumbnail=thumb,
            extra=metadata,
        )
        add_content(conn, asset_id, clip.name, config.MODEL_VERSION, clip.embed_images([image])[0])

        if face_engine is not None:
            crop_dir = os.path.join(config.LIBRARY_ROOT, ".crops")
            os.makedirs(crop_dir, exist_ok=True)
            pixels = np.asarray(image)
            for detected in face_engine.detect_and_embed(pixels):
                x, y, width, height = detected["bbox"]
                crop = pixels[max(0, y):max(0, y) + height, max(0, x):max(0, x) + width]
                crop_path = os.path.join(crop_dir, f"{uuid.uuid4().hex}.jpg")
                if crop.size:
                    Image.fromarray(crop).save(crop_path, "JPEG", quality=90)
                cur = conn.execute(
                    "INSERT INTO faces(asset_id, crop_path, bbox) VALUES (?, ?, ?)",
                    (asset_id, crop_path if crop.size else None, json.dumps(detected["bbox"])),
                )
                add_face(conn, int(cur.lastrowid), "buffalo_l", detected["embedding"])
        conn.commit()
    return asset_id
