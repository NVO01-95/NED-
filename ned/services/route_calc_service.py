

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Segment:
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    distance_nm: float
    bearing_deg: float
    eta_hours: float
    eta_hhmm: str


@dataclass(frozen=True)
class CalcResult:
    speed_kn: float
    total_nm: float
    total_eta_hours: float
    total_eta_hhmm: str
    segments: list[dict]


def compute_route_calculation(
    points: list[tuple[float, float]],
    speed_kn: float,
    haversine_nm: Callable[[float, float, float, float], float],
    bearing_deg: Callable[[float, float, float, float], float],
    hours_to_hhmm: Callable[[float], str],
) -> CalcResult:
    if speed_kn <= 0:
        raise ValueError("Speed must be > 0 knots.")
    if len(points) < 2:
        raise ValueError("Add at least 2 waypoints to compute a route.")

    segments_out: list[dict] = []
    total_nm = 0.0
    total_hours = 0.0

    for i in range(len(points) - 1):
        lat1, lon1 = points[i]
        lat2, lon2 = points[i + 1]

        dist_nm = float(haversine_nm(lat1, lon1, lat2, lon2))
        brng = float(bearing_deg(lat1, lon1, lat2, lon2))
        seg_hours = dist_nm / speed_kn

        segments_out.append({
            "from": {"lat": lat1, "lon": lon1},
            "to": {"lat": lat2, "lon": lon2},
            "distance_nm": round(dist_nm, 2),
            "bearing_deg": round(brng, 1),
            "eta_hours": round(seg_hours, 2),
            "eta_hhmm": hours_to_hhmm(seg_hours),
        })

        total_nm += dist_nm
        total_hours += seg_hours

    return CalcResult(
        speed_kn=speed_kn,
        total_nm=round(total_nm, 2),
        total_eta_hours=round(total_hours, 2),
        total_eta_hhmm=hours_to_hhmm(total_hours),
        segments=segments_out,
    )
