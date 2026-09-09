"""ExifTool metadata extraction with numeric GPS support."""

from __future__ import annotations

from exiftool import ExifToolHelper


def _signed(value: object, reference: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    if str(reference) in {"S", "W", "South", "West"}:
        return -abs(number)
    return abs(number)


def extract(path: str) -> dict:
    with ExifToolHelper(common_args=["-n"]) as tool:
        metadata = tool.get_metadata(path)
    if not metadata:
        return {}
    raw = metadata[0]
    return {
        "taken_at": raw.get("DateTimeOriginal") or raw.get("CreateDate"),
        "gps_lat": _signed(raw.get("GPSLatitude"), raw.get("GPSLatitudeRef")),
        "gps_lon": _signed(raw.get("GPSLongitude"), raw.get("GPSLongitudeRef")),
        "mime": raw.get("MIMEType", "application/octet-stream"),
        "size_bytes": int(raw.get("FileSize", 0) or 0),
        "model": raw.get("Model"),
    }
