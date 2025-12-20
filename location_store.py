import json
import os
import re
from typing import Dict, Optional, Tuple, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOCATIONS_PATH = os.path.join(DATA_DIR, "locations.json")

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def load_locations() -> Dict[str, Any]:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LOCATIONS_PATH):
        with open(LOCATIONS_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

    try:
        with open(LOCATIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_locations(locations: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(locations, f, ensure_ascii=False, indent=2)

def resolve_location(name: str) -> Optional[Tuple[float, float, str]]:
    locs = load_locations()
    key = _norm(name)
    rec = locs.get(key)
    if not isinstance(rec, dict):
        return None
    try:
        lat = float(rec["lat"])
        lon = float(rec["lon"])
        display = str(rec.get("display", name))
        return lat, lon, display
    except Exception:
        return None

def add_location(name: str, lat: float, lon: float, display: str = "") -> None:
    locs = load_locations()
    key = _norm(name)
    locs[key] = {"lat": float(lat), "lon": float(lon), "display": display or name}
    save_locations(locs)

def delete_location(name: str) -> bool:
    locs = load_locations()
    key = _norm(name)
    if key in locs:
        del locs[key]
        save_locations(locs)
        return True
    return False
