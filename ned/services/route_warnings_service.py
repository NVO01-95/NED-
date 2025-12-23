

from typing import Callable



def compute_route_warnings(
    points: list[tuple[float, float]],
    haversine_nm: Callable[[float, float, float, float], float],
    max_segment_nm: float = 50.0,
) -> list[str]:
    """
    Returnează o listă de warnings (text), NU blochează ruta.
    """

    warnings: list[str] = []

    if len(points) < 2:
        return warnings

    for i in range(len(points) - 1):
        lat1, lon1 = points[i]
        lat2, lon2 = points[i + 1]

        dist_nm = haversine_nm(lat1, lon1, lat2, lon2)

        if dist_nm > max_segment_nm:
            warnings.append(
                f"Segment {i+1} is very long ({dist_nm:.1f} NM). "
                "Check waypoint spacing."
            )

        if dist_nm > max_segment_nm * 2:
            warnings.append(
                f"Segment {i+1} may indicate a navigation jump."
            )

    return warnings
