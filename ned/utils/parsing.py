from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RawWaypoint:
    raw: str


# Acceptă:
# "45.123, 28.456"
# "45.123 28.456"
# "45.123;28.456"
_COORD_RE = re.compile(
    r"^\s*(?P<lat>-?\d+(?:\.\d+)?)\s*[,;\s]\s*(?P<lon>-?\d+(?:\.\d+)?)\s*$"
)


def split_waypoints(text: str) -> list[RawWaypoint]:
    """
    Input tip textarea: câte un waypoint pe linie.
    """
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return [RawWaypoint(raw=ln) for ln in lines]


def parse_lat_lon(raw: str) -> tuple[float, float] | None:
    """
    Dacă raw arată ca lat/lon, returnează (lat, lon). Altfel None.
    """
    m = _COORD_RE.match(raw)
    if not m:
        return None
    return float(m.group("lat")), float(m.group("lon"))
