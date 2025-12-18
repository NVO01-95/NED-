import json
import os
from typing import Any, Dict
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_PATH = os.path.join(DATA_DIR, "ned_data.json")

DEFAULT_DATA: Dict[str, Any] = {
    "voyages": [],
    "routes": [],
    "log_entries": [],
    "contacts": [],
    "personal_contacts": [],
    "weather_notes": [],
    "users": [],
    "chat_messages": []
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def route_tokens(route: dict) -> set[str]:
    tokens = set()

    dep = _norm(route.get("departure"))
    dst = _norm(route.get("destination"))
    if dep:
        tokens.add(dep)
    if dst:
        tokens.add(dst)

    # waypoint-urile tale sunt text; pentru MVP extragem “cuvinte/fragmente” utile
    wp = _norm(route.get("waypoints_raw") or route.get("waypoints") or "")
    # split simplu pe delimitatori frecvenți
    for part in re.split(r"[;,\n\-–→]+", wp):
        part = _norm(part)
        if part and len(part) >= 3:
            tokens.add(part)

    return tokens

def routes_overlap(a: dict, b: dict) -> bool:
    return len(route_tokens(a) & route_tokens(b)) > 0

def _ensure_data_file_exists() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_PATH):
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, ensure_ascii=False, indent=2)


def load_data() -> Dict[str, Any]:
    _ensure_data_file_exists()
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return dict(DEFAULT_DATA)
    except Exception:
        return dict(DEFAULT_DATA)

    for k, v in DEFAULT_DATA.items():
        if k not in data:
            data[k] = v

    return data


def save_data(data: Dict[str, Any]) -> None:
    _ensure_data_file_exists()

    for k, v in DEFAULT_DATA.items():
        if k not in data:
            data[k] = v

    # backup before write
    backup_path = DATA_PATH + ".bak"
    try:
        if os.path.exists(DATA_PATH):
            with open(DATA_PATH, "r", encoding="utf-8") as src:
                old = src.read()
            with open(backup_path, "w", encoding="utf-8") as b:
                b.write(old)
    except Exception:
        pass

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_route_ids(data: dict) -> dict:
    routes = data.get("routes", [])
    changed = False

    max_id = 0
    for r in routes:
        rid = r.get("id")
        if isinstance(rid, int) and rid > max_id:
            max_id = rid

    for r in routes:
        if not isinstance(r.get("id"), int):
            max_id += 1
            r["id"] = max_id
            changed = True

    if changed:
        data["routes"] = routes
        save_data(data)

    return data
