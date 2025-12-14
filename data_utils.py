import json
import os
from typing import Any, Dict

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
