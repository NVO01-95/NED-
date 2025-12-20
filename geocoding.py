# geocoding.py
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import requests
import re


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Respect policy: max 1 request / second + identify app (User-Agent) :contentReference[oaicite:2]{index=2}
USER_AGENT = "NED-NauticalDashboard/0.1 (contact: you@example.com)"  # schimbă cu email-ul tău
FALLBACK = {
    "tulcea": (45.1775180, 28.8016348, "Tulcea, Romania"),
    "constanta": (44.1598013, 28.6348138, "Constanța, Romania"),
    "varna": (43.2072500, 27.9167000, "Varna, Bulgaria"),
    "istanbul": (41.0082376, 28.9783589, "Istanbul, Turkey"),
}


def _norm_key(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def cache_get(data: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    cache = data.get("geocode_cache") or {}
    key = _norm_key(query)
    val = cache.get(key)
    return val if isinstance(val, dict) else None


def cache_set(data: Dict[str, Any], query: str, lat: float, lon: float, display: str) -> None:
    cache = data.get("geocode_cache")
    if not isinstance(cache, dict):
        cache = {}
        data["geocode_cache"] = cache

    key = _norm_key(query)
    cache[key] = {
        "lat": lat,
        "lon": lon,
        "display": display,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def geocode_nominatim(query: str, *, country_codes: str = "", limit: int = 1) -> Optional[Tuple[float, float, str]]:
    """
    Returns (lat, lon, display_name) or None.

    Retries on timeouts/temporary network issues.
    """
    q = (query or "").strip()
    if not q:
        return None

    params = {
        "q": q,
        "format": "json",
        "limit": str(limit),
    }
    if country_codes:
        params["countrycodes"] = country_codes

    headers = {"User-Agent": USER_AGENT}

    # polite + stable: 1 req/sec and retry
    attempts = 2
    for i in range(attempts):
        try:
            time.sleep(1.05)  # keep under 1 req/sec policy
            r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
            print("Nominatim status:", r.status_code)
            print("Nominatim url:", r.url)
            print("Nominatim content-type:", r.headers.get("Content-Type"))
            print("Nominatim text head:", r.text[:200])

            if r.status_code != 200:
                return None

            arr = r.json()
            if not isinstance(arr, list) or not arr:
                return None

            top = arr[0]
            lat = float(top["lat"])
            lon = float(top["lon"])
            display = str(top.get("display_name", q))
            return lat, lon, display

        except requests.exceptions.ReadTimeout:
            # retry once
            if i == attempts - 1:
                return None
            time.sleep(1.5)
        except requests.exceptions.RequestException:
            # network/DNS/etc.
            return None
        except Exception:
            return None

    return None



def geocode_with_cache(data: Dict[str, Any], query: str, *, country_codes: str = "ro,bg,tr", save_fn=None) -> Optional[Tuple[float, float, str]]:
    
    key = _norm_key(query)
    cached = cache_get(data, key)
    if cached:
        try:
            return float(cached["lat"]), float(cached["lon"]), str(cached.get("display", query))
        except Exception:
            pass
    
    key = _norm_key(query)
    if key in FALLBACK:
        lat, lon, display = FALLBACK[key]
        cache_set(data, query, lat, lon, display)
        if callable(save_fn):
            save_fn(data)
        return lat, lon, display


    res = geocode_nominatim(query, country_codes=country_codes, limit=1)

    if not res and country_codes:
        res = geocode_nominatim(query, country_codes="", limit=1)

    if not res:
        return None

    lat, lon, display = res
    cache_set(data, query, lat, lon, display)
    if callable(save_fn):
        save_fn(data)
    return res
