from dataclasses import dataclass
from typing import Protocol

from ned.utils.parsing import split_waypoints, parse_lat_lon
from ned.utils.validation import validate_lat_lon, ValidationError


@dataclass(frozen=True)
class Waypoint:
    label: str   # "WP1" or location name
    lat: float
    lon: float


@dataclass(frozen=True)
class RouteBuildResult:
    waypoints: list[Waypoint]
    errors: list[str]
    warnings: list[str]


class LocationResolver(Protocol):
    """
    Local-only resolver interface:
    - resolve(name) -> (lat, lon) or None
    Optional:
    - suggest(q, limit=3) -> list[str]
    """
    def resolve(self, name: str):
        ...

    # optional, but supported if present
    def suggest(self, q: str, limit: int = 3):
        ...


def build_route_from_text(text: str, resolver: LocationResolver) -> RouteBuildResult:
    raw_points = split_waypoints(text)

    waypoints: list[Waypoint] = []
    errors: list[str] = []
    warnings: list[str] = []

    for idx, rp in enumerate(raw_points, start=1):
        raw = (rp.raw or "").strip()
        if not raw:
            continue

        # 1) Try coords
        ll = parse_lat_lon(raw)
        if ll is not None:
            lat, lon = ll
            v = validate_lat_lon(lat, lon)
            if v:
                errors.extend(_format_validation_errors(idx, raw, v))
                continue

            waypoints.append(Waypoint(label=f"WP{idx}", lat=lat, lon=lon))
            continue

        # 2) Try name (local)
        resolved = resolver.resolve(raw)
        if resolved is None:
            suggestions: list[str] = []
            if hasattr(resolver, "suggest"):
                try:
                    suggestions = resolver.suggest(raw, limit=3) or []
                except Exception:
                    suggestions = []

            if suggestions:
                errors.append(
                    f"[Line {idx}] Unknown location: '{raw}'. Did you mean: {', '.join(suggestions)}?"
                )
            else:
                errors.append(f"[Line {idx}] Unknown location or invalid coordinates: '{raw}'")
            continue

        lat, lon = resolved
        v = validate_lat_lon(lat, lon)
        if v:
            errors.extend(_format_validation_errors(idx, raw, v))
            continue

        waypoints.append(Waypoint(label=raw, lat=lat, lon=lon))

    if len(waypoints) < 2 and not errors:
        warnings.append("Add at least 2 waypoints to build a route.")

    return RouteBuildResult(waypoints=waypoints, errors=errors, warnings=warnings)


def _format_validation_errors(idx: int, raw: str, v: list[ValidationError]) -> list[str]:
    out: list[str] = []
    for e in v:
        out.append(f"[Line {idx}] {e.message} (input: '{raw}')")
    return out
