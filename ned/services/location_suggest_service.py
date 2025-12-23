import json
from difflib import get_close_matches


def _load_locations(locations_path: str) -> list[dict]:
    with open(locations_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # suport 3 formate:
    if isinstance(data, dict) and "locations" in data and isinstance(data["locations"], list):
        return data["locations"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # dict name -> {lat,lon}
        out = []
        for name, val in data.items():
            if isinstance(val, dict) and "lat" in val and "lon" in val:
                out.append({"name": name, "lat": val["lat"], "lon": val["lon"]})
        return out
    return []


def suggest_locations(q: str, locations_path: str, limit: int = 10) -> list[str]:
    q = (q or "").strip().lower()
    if not q:
        return []

    locations = _load_locations(locations_path)
    names = [str(x.get("name", "")).strip() for x in locations if str(x.get("name", "")).strip()]

    # sugestii simple: contains match
    contains = [n for n in names if q in n.lower()]
    contains = contains[:limit]

    if len(contains) >= limit:
        return contains

    # completează cu fuzzy (difflib)
    rest = get_close_matches(q, names, n=limit - len(contains), cutoff=0.6)
    # evită duplicate
    out = contains + [x for x in rest if x not in contains]
    return out[:limit]
