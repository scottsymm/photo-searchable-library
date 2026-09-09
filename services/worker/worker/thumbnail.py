"""Image and video thumbnail extraction."""

from __future__ import annotations

import io
import subprocess

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()


def image_thumbnail(path: str, max_dim: int = 512) -> bytes:
    with Image.open(path) as image:
        image.thumbnail((max_dim, max_dim))
        output = io.BytesIO()
        image.convert("RGB").save(output, "JPEG", quality=82, optimize=True)
        return output.getvalue()


def video_frame(path: str, max_dim: int = 512) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-i", path, "-frames:v", "1",
            "-vf", f"scale='if(gt(iw,ih),{max_dim},-1)':'if(gt(iw,ih),-1,{max_dim})'",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ],
        check=True,
        capture_output=True,
    )
    if not result.stdout:
        raise ValueError(f"ffmpeg produced no frame for {path}")
    return result.stdout


def thumbnail(path: str, mime: str) -> bytes:
    return video_frame(path) if mime.startswith("video/") else image_thumbnail(path)
