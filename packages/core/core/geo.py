"""Offline GPS reverse geocoding."""

from __future__ import annotations

import reverse_geocoder


def reverse(lat: float, lon: float) -> tuple[str | None, str | None]:
    try:
        result = reverse_geocoder.search([(lat, lon)], mode=1)[0]
        return result["name"], result["cc"]
    except Exception:
        return None, None
