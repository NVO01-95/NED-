import json
import os
import re
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PHRASES_PATH = os.path.join(DATA_DIR, "phrases.json")

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def load_phrases_data() -> Dict[str, Any]:
    if not os.path.exists(PHRASES_PATH):
        return {"version": "0.0", "languages": [], "categories": [], "phrases": []}
    with open(PHRASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": "0.0", "languages": [], "categories": [], "phrases": []}
    data.setdefault("languages", [])
    data.setdefault("categories", [])
    data.setdefault("phrases", [])
    return data

def filter_phrases(data: Dict[str, Any], category: str = "", q: str = "") -> List[Dict[str, Any]]:
    phrases = data.get("phrases", []) or []
    category = _norm(category)
    qn = _norm(q)

    out = []
    for p in phrases:
        if not isinstance(p, dict):
            continue
        if category and _norm(p.get("category", "")) != category:
            continue

        if qn:
            texts = p.get("texts", {}) or {}
            # căutăm în ro/en + ru_lat (ca să fie util)
            hay = " ".join([
                str(texts.get("ro", "")),
                str(texts.get("en", "")),
                str(texts.get("de", "")),
                str(texts.get("fr", "")),
                str(texts.get("ru", "")),
                str(texts.get("ru_lat", "")),
                " ".join(p.get("tags", []) or [])
            ])
            if qn not in _norm(hay):
                continue

        out.append(p)

    # sort by id
    out.sort(key=lambda x: int(x.get("id", 10**9)) if str(x.get("id", "")).isdigit() else 10**9)
    return out
