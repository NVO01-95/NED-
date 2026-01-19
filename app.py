import csv
import io
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from collections import Counter
from difflib import get_close_matches

from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect, url_for,session, make_response, flash, g)
from werkzeug.security import generate_password_hash, check_password_hash

from data_utils import load_data, save_data, ensure_route_ids
from chat_logic import add_route_message, delete_route_message, can_user_post, related_routes_for
from location_store import load_locations, add_location, delete_location, resolve_location
from phrases_store import load_phrases_data, filter_phrases

from ned.services.route_service import build_route_from_text
from ned.services.route_warnings_service import compute_route_warnings
from ned.services.location_suggest_service import suggest_locations

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-in-production")


# ----------------------------------------
# Data models (results)
# ----------------------------------------

@dataclass(frozen=True)
class CalcResult:
    speed_kn: float
    total_nm: float
    total_eta_hours: float
    total_eta_hhmm: str
    segments: list[dict]


# ----------------------------------------
# Local resolver (JSON locations)
# ----------------------------------------

class LocalLocationsResolver:
    def __init__(self, locations_path: str):
        self.locations_path = locations_path
        self._locations = None

    def _load_locations(self):
        with open(self.locations_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and isinstance(data.get("locations"), list):
            return data["locations"]

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            out = []
            for name, val in data.items():
                if isinstance(val, dict) and "lat" in val and "lon" in val:
                    out.append({"name": name, "lat": val["lat"], "lon": val["lon"]})
            return out

        return []

    def _ensure_loaded(self):
        if self._locations is None:
            self._locations = self._load_locations()

    def resolve(self, name: str):
        self._ensure_loaded()
        q = (name or "").strip().lower()
        if not q:
            return None

        for item in self._locations:
            nm = str(item.get("name", "")).strip().lower()
            if nm == q:
                return float(item["lat"]), float(item["lon"])

        return None

    def suggest(self, q: str, limit: int = 3):
        self._ensure_loaded()
        q = (q or "").strip().lower()
        if not q:
            return []

        names = [
            str(x.get("name", "")).strip()
            for x in self._locations
            if str(x.get("name", "")).strip()
        ]

        contains = [n for n in names if q in n.lower()][:limit]
        if len(contains) >= limit:
            return contains

        rest = get_close_matches(q, names, n=limit - len(contains), cutoff=0.6)
        out = contains + [x for x in rest if x not in contains]
        return out[:limit]


# ----------------------------------------
# Navigation calc.
# ----------------------------------------

def haversine_nm(lat1, lon1, lat2, lon2):
    R_KM = 6371.0
    KM_TO_NM = 0.539956803

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = (math.sin(d_phi / 2) ** 2) + (math.cos(phi1) * math.cos(phi2) * (math.sin(d_lam / 2) ** 2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return (R_KM * c) * KM_TO_NM


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


# ----------------------------------------
# Auth helper
# ----------------------------------------

def require_login() -> bool:
    if not session.get("user_id"):
        flash("This feature is available for logged-in users.", "error")
        return False
    return True

# //doneee
def bearing_deg(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lam = math.radians(lon2 - lon1)

    y = math.sin(d_lam) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2)) - (math.sin(phi1) * math.cos(phi2) * math.cos(d_lam))

    brng = math.degrees(math.atan2(y, x))
    return (brng + 360) % 360


def _clean_coord_text(s: str) -> str:
    return (
        (s or "")
        .strip()
        .replace("º", "°")
        .replace("’", "'")
        .replace("′", "'")
        .replace("”", '"')
        .replace("″", '"')
    )


def dms_to_decimal(deg: float, minutes: float, seconds: float, hemi: str) -> float:
    value = abs(deg) + (minutes / 60.0) + (seconds / 3600.0)
    if (hemi or "").upper() in ("S", "W"):
        value *= -1
    return value


def _validate_coord_range(val: float, coord_type: str) -> None:
    if coord_type == "lat":
        if not (-90 <= val <= 90):
            raise ValueError(f"Latitude {val} out of range (-90..90).")
        return

    if coord_type == "lon":
        if not (-180 <= val <= 180):
            raise ValueError(f"Longitude {val} out of range (-180..180).")
        return


def parse_single_coord(token: str, coord_type: str) -> float:
    t = _clean_coord_text(token).upper()

    if re.fullmatch(r"[+-]?\d+(\.\d+)?", t):
        val = float(t)
        _validate_coord_range(val, coord_type)
        return val

    work = (
        t.replace("°", " ")
        .replace("'", " ")
        .replace('"', " ")
        .replace(",", " ")
    )
    parts = [p for p in work.split() if p]

    if len(parts) < 3:
        raise ValueError(
            f"Invalid coordinate '{token}'. Use decimal (44.16) or DM/DMS (44 10.2 N)."
        )

    hemi = parts[-1]
    if hemi not in ("N", "S", "E", "W"):
        raise ValueError(f"Missing hemisphere (N/S/E/W) in '{token}'.")

    nums = parts[:-1]

    if len(nums) == 2:
        deg = float(nums[0])
        minutes = float(nums[1])
        val = dms_to_decimal(deg, minutes, 0.0, hemi)
    elif len(nums) == 3:
        deg = float(nums[0])
        minutes = float(nums[1])
        seconds = float(nums[2])
        val = dms_to_decimal(deg, minutes, seconds, hemi)
    else:
        raise ValueError(
            f"Invalid coordinate '{token}'. Example: 44 10.2 N, 28 39.0 E"
        )

    _validate_coord_range(val, coord_type)
    return val

# //doneee
def parse_waypoints_mixed(waypoints_text: str):
    points: list[tuple[float, float]] = []
    lines = [ln.strip() for ln in (waypoints_text or "").splitlines() if ln.strip()]

    for ln in lines:
        if "," in ln:
            a, b = ln.split(",", 1)
            try:
                lat = float(a.strip())
                lon = float(b.strip())
                points.append((lat, lon))
                continue
            except ValueError:
                pass

        res = resolve_location(ln)
        if not res:
            raise ValueError(f"Location not found: {ln}. Use coordinates or ask admin to add it.")

        lat, lon, _display = res
        points.append((lat, lon))

    if len(points) < 2:
        raise ValueError("You need at least 2 waypoints (coords or saved locations).")

    return points


def parse_waypoints(text: str):
    if not (text or "").strip():
        raise ValueError("Waypoints are empty. Add at least 2 points (lat, lon).")

    raw_lines = [p.strip() for p in (text or "").replace(";", "\n").splitlines() if p.strip()]

    points: list[tuple[float, float]] = []
    for i, line in enumerate(raw_lines, start=1):
        if "," not in line:
            raise ValueError(
                f"Waypoint line {i} needs a comma between lat and lon. "
                f"Example: 44 10.2 N, 28 39.0 E"
            )

        lat_token, lon_token = (x.strip() for x in line.split(",", 1))

        try:
            lat = parse_single_coord(lat_token, "lat")
            lon = parse_single_coord(lon_token, "lon")
        except Exception as e:
            raise ValueError(f"Waypoint line {i}: {e}")

        points.append((lat, lon))

    if len(points) < 2:
        raise ValueError("You need at least 2 waypoints (start and end).")

    return points


def ensure_route_ids(data: dict) -> dict:
    routes = data.get("routes", [])
    max_id = 0

    for r in routes:
        rid = r.get("id")
        if isinstance(rid, int) and rid > max_id:
            max_id = rid

    changed = False
    for r in routes:
        if not isinstance(r.get("id"), int):
            max_id += 1
            r["id"] = max_id
            changed = True

    if changed:
        data["routes"] = routes
        save_data(data)

    return data
# //doneee
def get_current_user(data: dict):
    uid = session.get("user_id")
    return next((u for u in data.get("users", []) if u.get("id") == uid), None)


def is_admin_user(data: dict) -> bool:
    u = get_current_user(data)
    return bool(u and u.get("is_admin", False))


def hours_to_hhmm(hours_float) -> str:
    if hours_float is None:
        return "-"
    total_minutes = int(round(float(hours_float) * 60))
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}"


def compute_voyage_stats(voyages: list[dict]) -> dict:
    total_distance = 0.0
    distances: list[tuple[float, dict]] = []
    departures: list[str] = []
    destinations: list[str] = []

    for v in voyages:
        dist_raw = v.get("distance_nm")
        if dist_raw not in (None, ""):
            try:
                dist_val = float(dist_raw)
                total_distance += dist_val
                distances.append((dist_val, v))
            except ValueError:
                pass

        dep = (v.get("departure") or "").strip()
        dest = (v.get("destination") or "").strip()
        if dep:
            departures.append(dep)
        if dest:
            destinations.append(dest)

    longest_voyage = None
    if distances:
        dist_val, v = max(distances, key=lambda x: x[0])
        longest_voyage = {
            "distance_nm": dist_val,
            "departure": v.get("departure"),
            "destination": v.get("destination"),
        }

    return {
        "total_distance_nm": round(total_distance, 1),
        "longest_voyage": longest_voyage,
        "top_departures": Counter(departures).most_common(3),
        "top_destinations": Counter(destinations).most_common(3),
    }


def compute_contact_stats_for_port(
    official_contacts: list[dict],
    personal_contacts: list[dict],
    port_name: str,
) -> dict:
    port_name = (port_name or "").strip()

    official = [c for c in official_contacts if (c.get("port") or "").strip() == port_name]
    personal = [c for c in personal_contacts if (c.get("port") or "").strip() == port_name]

    roles: list[str] = []
    for c in official + personal:
        role = (c.get("role") or c.get("type") or "").strip()
        if role:
            roles.append(role)

    return {
        "official_count": len(official),
        "personal_count": len(personal),
        "total_count": len(official) + len(personal),
        "top_roles": Counter(roles).most_common(3),
    }
# //doneee
@app.before_request
def load_current_user_into_g():
    g.current_user = None
    uid = session.get("user_id")
    if not uid:
        return

    try:
        data = load_data()
        g.current_user = next((u for u in data.get("users", []) if u.get("id") == uid), None)
    except Exception:
        g.current_user = None


@app.context_processor
def inject_user_context():
    current_user = g.get("current_user")
    return {
        "current_user": current_user,
        "is_authenticated": bool(current_user),
        "is_admin": bool(current_user and current_user.get("is_admin", False)),
        "current_username": session.get("username"),
        "current_user_id": session.get("user_id"),
    }


@app.route("/")
def home():
    current_user = g.get("current_user")

    if current_user and current_user.get("is_admin", False):
        return redirect(url_for("admin_panel"))

    return render_template("index.html")


@app.route("/admin")
def admin_panel():
    data = load_data()

    users = data.get("users", [])
    voyages = data.get("voyages", [])
    routes = data.get("routes", [])
    log_entries = data.get("log_entries", [])
    contacts = data.get("contacts", [])
    personal_contacts = data.get("personal_contacts", [])
    weather_notes = data.get("weather_notes", [])

    current_user = g.get("current_user")
    if not current_user or not current_user.get("is_admin", False):
        return redirect(url_for("login"))

    summary = {
        "users": len(users),
        "voyages": len(voyages),
        "routes": len(routes),
        "log_entries": len(log_entries),
        "contacts": len(contacts),
        "personal_contacts": len(personal_contacts),
        "weather_notes": len(weather_notes),
    }

    return render_template(
        "admin.html",
        users=users,
        voyages=voyages,
        summary=summary,
        admin_message=None,
        admin_error=None,
    )


@app.route("/admin/locations", methods=["GET", "POST"])
def admin_locations():
    data = load_data()
    if not is_admin_user(data):
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        lat_str = request.form.get("lat", "").strip()
        lon_str = request.form.get("lon", "").strip()
        display = request.form.get("display", "").strip()

        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("admin_locations"))

        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            flash("Lat/Lon must be valid numbers.", "error")
            return redirect(url_for("admin_locations"))

        add_location(name, lat, lon, display)
        flash("Location added/updated.", "success")
        return redirect(url_for("admin_locations"))

    locations = load_locations()
    keys = sorted(locations.keys())
    return render_template("admin_locations.html", locations=locations, keys=keys)
# //doneee
@app.route("/admin/locations/delete", methods=["POST"])
def admin_delete_location():
    data = load_data()
    if not is_admin_user(data):
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("Missing location name.", "error")
        return redirect(url_for("admin_locations"))

    if delete_location(name):
        flash("Location deleted.", "success")
    else:
        flash("Location not found.", "error")

    return redirect(url_for("admin_locations"))


@app.route("/admin/reset_password", methods=["POST"])
def admin_reset_password():
    data = load_data()
    users = data.get("users", [])

    current_user = g.get("current_user")
    if not current_user or not current_user.get("is_admin", False):
        return redirect(url_for("login"))

    user_id_str = request.form.get("user_id", "").strip()
    new_password = request.form.get("new_password", "").strip()

    admin_message = None
    admin_error = None

    if not user_id_str or not new_password:
        admin_error = "User and new password are required."
    elif len(new_password) < 4:
        admin_error = "New password should have at least 4 characters."
    else:
        try:
            target_id = int(user_id_str)
        except ValueError:
            admin_error = "Invalid user id."
        else:
            target_user = next((u for u in users if u.get("id") == target_id), None)
            if not target_user:
                admin_error = "User not found."
            else:
                target_user["password_hash"] = generate_password_hash(new_password)
                save_data(data)
                admin_message = f"Password updated for user '{target_user.get('username')}'."

    voyages = data.get("voyages", [])
    routes = data.get("routes", [])
    log_entries = data.get("log_entries", [])
    contacts = data.get("contacts", [])
    personal_contacts = data.get("personal_contacts", [])
    weather_notes = data.get("weather_notes", [])

    summary = {
        "users": len(users),
        "voyages": len(voyages),
        "routes": len(routes),
        "log_entries": len(log_entries),
        "contacts": len(contacts),
        "personal_contacts": len(personal_contacts),
        "weather_notes": len(weather_notes),
    }

    return render_template(
        "admin.html",
        users=users,
        voyages=voyages,
        summary=summary,
        admin_message=admin_message,
        admin_error=admin_error,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    data = load_data()
    users = data.get("users", [])

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return render_template("register.html", error="Username and password are required.")
        if len(password) < 4:
            return render_template("register.html", error="Password should have at least 4 characters.")
        if any(u.get("username") == username for u in users):
            return render_template("register.html", error="Username already taken.")

        next_id = max((u.get("id", 0) for u in users), default=0) + 1

        users.append({
            "id": next_id,
            "username": username,
            "password_hash": generate_password_hash(password),
            "is_admin": False,
            "can_post": True,
        })

        data["users"] = users
        save_data(data)

        session["user_id"] = next_id
        session["username"] = username
        return redirect(url_for("home"))

    return render_template("register.html", error=None)
# //doneee
@app.route("/login", methods=["GET", "POST"])
def login():
    data = load_data()
    users = data.get("users", [])

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = next((u for u in users if u.get("username") == username), None)
        if not user:
            return render_template("login.html", error="Invalid username or password.")

        if not check_password_hash(user.get("password_hash", ""), password):
            return render_template("login.html", error="Invalid username or password.")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("home"))

    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    data = load_data()
    users = data.get("users", [])

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        password2 = request.form.get("password2", "").strip()

        if not username or not password or not password2:
            return render_template("forgot_password.html", error="All fields are required.", success=None)

        if password != password2:
            return render_template("forgot_password.html", error="Passwords do not match.", success=None)

        target = next((u for u in users if u.get("username") == username), None)
        if not target:
            return render_template("forgot_password.html", error="Username not found.", success=None)

        target["password_hash"] = generate_password_hash(password)
        data["users"] = users
        save_data(data)

        return render_template(
            "forgot_password.html",
            error=None,
            success="Password successfully reset. You can now log in with the new password.",
        )

    return render_template("forgot_password.html", error=None, success=None)
# //doneee
@app.route("/voyage", methods=["GET", "POST"])
def voyage_sheet():
    data = load_data()
    voyages = data.get("voyages", [])

    selected_voyage = None
    selected_index = None
    editing = False
    form_voyage = None
    edit_index = None

    if request.method == "POST":
        if not require_login():
            return redirect(url_for("voyage_sheet"))

        idx_str = request.form.get("voyage_index", "").strip()

        departure = request.form.get("departure", "").strip()
        destination = request.form.get("destination", "").strip()
        etd = request.form.get("etd", "").strip()
        eta = request.form.get("eta", "").strip()
        distance_nm = request.form.get("distance_nm", "").strip()
        notes = request.form.get("notes", "").strip()

        existing_checklist = {}
        existing_user_id = None

        if idx_str:
            try:
                idx = int(idx_str)
                if 0 <= idx < len(voyages):
                    existing_checklist = voyages[idx].get("checklist", {})
                    existing_user_id = voyages[idx].get("user_id")
            except ValueError:
                pass

        new_voyage = {
            "departure": departure,
            "destination": destination,
            "etd": etd,
            "eta": eta,
            "distance_nm": distance_nm,
            "notes": notes,
            "checklist": existing_checklist,
            "user_id": existing_user_id if idx_str else session.get("user_id"),
        }

        if idx_str:
            try:
                idx = int(idx_str)
            except ValueError:
                voyages.append(new_voyage)
            else:
                if 0 <= idx < len(voyages):
                    voyages[idx] = new_voyage
                else:
                    voyages.append(new_voyage)
        else:
            voyages.append(new_voyage)

        data["voyages"] = voyages
        save_data(data)
        return redirect(url_for("voyage_sheet"))

    view_index = request.args.get("view")
    if view_index is not None:
        try:
            idx = int(view_index)
            if 0 <= idx < len(voyages):
                selected_voyage = voyages[idx]
                selected_index = idx + 1
        except ValueError:
            pass

    edit_param = request.args.get("edit")
    if edit_param is not None:
        try:
            idx = int(edit_param)
            if 0 <= idx < len(voyages):
                editing = True
                edit_index = idx
                form_voyage = voyages[idx]
        except ValueError:
            pass

    current_user_id = session.get("user_id")
    user_voyage_count = None
    if current_user_id:
        user_voyage_count = sum(1 for v in voyages if v.get("user_id") == current_user_id)

    return render_template(
        "voyage_sheet.html",
        voyages=voyages,
        selected_voyage=selected_voyage,
        selected_index=selected_index,
        editing=editing,
        edit_index=edit_index,
        form_voyage=form_voyage,
        user_voyage_count=user_voyage_count,
    )


@app.route("/voyage/<int:voyage_id>", methods=["GET", "POST"])
def voyage_detail(voyage_id):
    data = load_data()
    voyages = data.get("voyages", [])

    voyage = next((v for v in voyages if v.get("id") == voyage_id), None)
    if not voyage:
        flash("Voyage not found.", "error")
        return redirect(url_for("voyage_sheet"))

    uid = session.get("user_id")
    current_user = g.get("current_user")
    is_admin = bool(current_user and current_user.get("is_admin", False))
    is_owner = (voyage.get("author_id") == uid) or (voyage.get("user_id") == uid)

    if request.method == "POST":
        if not uid:
            return redirect(url_for("login"))

        if not (is_admin or is_owner):
            flash("You are not allowed to edit this voyage.", "error")
            return redirect(url_for("voyage_detail", voyage_id=voyage_id))

        voyage["notes"] = request.form.get("notes", "").strip()
        voyage["tags"] = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]

        data["voyages"] = voyages
        save_data(data)
        flash("Voyage saved.", "success")
        return redirect(url_for("voyage_detail", voyage_id=voyage_id))

    return render_template(
        "voyage_detail.html",
        voyage=voyage,
        is_admin=is_admin,
        is_owner=is_owner,
    )


def _can_edit_voyage(voyage: dict, uid: int | None, is_admin: bool) -> bool:
    if not uid:
        return False
    is_owner = (voyage.get("user_id") == uid) or (voyage.get("author_id") == uid)
    return bool(is_admin or is_owner)


@app.route("/voyage/delete/<int:index>", methods=["POST"])
def delete_voyage(index):
    if not require_login():
        return redirect(url_for("voyage_sheet"))

    data = load_data()
    voyages = data.get("voyages", [])

    uid = session.get("user_id")
    current_user = g.get("current_user")
    is_admin = bool(current_user and current_user.get("is_admin", False))

    if 0 <= index < len(voyages):
        v = voyages[index]
        if not _can_edit_voyage(v, uid, is_admin):
            flash("You are not allowed to delete this voyage.", "error")
            return redirect(url_for("voyage_sheet"))

        voyages.pop(index)
        data["voyages"] = voyages
        save_data(data)
        flash("Voyage deleted.", "success")

    return redirect(url_for("voyage_sheet"))


@app.route("/voyage/checklist/<int:index>", methods=["POST"])
def update_checklist(index):
    if not require_login():
        return redirect(url_for("voyage_sheet"))

    data = load_data()
    voyages = data.get("voyages", [])

    uid = session.get("user_id")
    current_user = g.get("current_user")
    is_admin = bool(current_user and current_user.get("is_admin", False))

    if 0 <= index < len(voyages):
        v = voyages[index]
        if not _can_edit_voyage(v, uid, is_admin):
            flash("You are not allowed to update this checklist.", "error")
            return redirect(url_for("voyage_sheet", view=index))

        checklist = {
            "fuel": "fuel" in request.form,
            "weather": "weather" in request.form,
            "crew": "crew" in request.form,
            "documents": "documents" in request.form,
            "safety": "safety" in request.form,
        }

        voyages[index]["checklist"] = checklist
        data["voyages"] = voyages
        save_data(data)
        flash("Checklist updated.", "success")

    return redirect(url_for("voyage_sheet", view=index))
# //doneee

@app.route("/route", methods=["GET", "POST"])
def route_planner():
    data = load_data()
    data = ensure_route_ids(data)

    routes_all = data.get("routes", [])
    routes_view = list(routes_all)

    calc_result = None
    calc_error = None

    sort_by = request.args.get("sort", "new")   # new | old | nm_desc | nm_asc
    limit = request.args.get("limit", "10")     # 10 | 25 | 50 | all

    def created_key(r: dict):
        return r.get("created_at", "")

    if sort_by == "old":
        routes_view = sorted(routes_view, key=created_key)
    elif sort_by == "nm_desc":
        routes_view = sorted(
            routes_view,
            key=lambda r: (r.get("calc") or {}).get("total_nm", 0),
            reverse=True,
        )
    elif sort_by == "nm_asc":
        routes_view = sorted(
            routes_view,
            key=lambda r: (r.get("calc") or {}).get("total_nm", 0),
        )
    else:
        routes_view = sorted(routes_view, key=created_key, reverse=True)

    if limit != "all":
        try:
            n = int(limit)
        except ValueError:
            n = 10
        routes_view = routes_view[:n]

    if request.method == "POST":
        if not session.get("user_id"):
            return redirect(url_for("login"))

        route_name = request.form.get("route_name", "").strip()
        route_departure = request.form.get("route_departure", "").strip()
        route_destination = request.form.get("route_destination", "").strip()
        speed_kn_str = request.form.get("speed_kn", "").strip()
        waypoints_text = request.form.get("waypoints", "").strip()
        route_notes = request.form.get("route_notes", "").strip()

        checklist = {
            "fuel": "fuel" in request.form,
            "weather": "weather" in request.form,
            "crew": "crew" in request.form,
            "documents": "documents" in request.form,
            "safety": "safety" in request.form,
        }

        try:
            if not speed_kn_str:
                raise ValueError("Speed (kn) is required.")

            speed_kn = float(speed_kn_str)
            if speed_kn <= 0:
                raise ValueError("Speed must be > 0 knots.")

            locations_path = os.path.join(app.root_path, "data", "locations.json")
            resolver = LocalLocationsResolver(locations_path)

            build = build_route_from_text(waypoints_text, resolver)
            if build.errors:
                raise ValueError("; ".join(build.errors))

            points = [(w.lat, w.lon) for w in build.waypoints]

            route_warnings = compute_route_warnings(points=points, haversine_nm=haversine_nm)

            calc = compute_route_calculation(
                points=points,
                speed_kn=speed_kn,
                haversine_nm=haversine_nm,
                bearing_deg=bearing_deg,
                hours_to_hhmm=hours_to_hhmm,
            )

            calc_result = {
                "speed_kn": calc.speed_kn,
                "total_nm": calc.total_nm,
                "total_eta_hours": calc.total_eta_hours,
                "total_eta_hhmm": calc.total_eta_hhmm,
                "segments": calc.segments,
                "warnings": route_warnings,
            }

            next_id = 1
            if routes_all:
                ids = [r.get("id", 0) for r in routes_all if isinstance(r.get("id", 0), int)]
                next_id = (max(ids) + 1) if ids else 1

            new_route = {
                "id": next_id,
                "name": route_name or f"{route_departure} - {route_destination}".strip(" -"),
                "departure": route_departure,
                "destination": route_destination,
                "waypoints_raw": waypoints_text,
                "notes": route_notes,
                "checklist": checklist,
                "calc": calc_result,
                "author": session.get("username") or "Unknown",
                "author_id": session.get("user_id"),
                "created_at": datetime.utcnow().isoformat(),
                "status": "planned",
                "done_at": None,
            }

            data["routes"].append(new_route)
            save_data(data)

            return redirect(url_for("route_planner"))

        except Exception as e:
            calc_error = str(e)

    current_user = g.get("current_user")
    is_admin = bool(current_user and current_user.get("is_admin", False))

    return render_template(
        "route_planner.html",
        routes=routes_view,
        users=data.get("users", []),
        is_admin=is_admin,
        calc_result=calc_result,
        calc_error=calc_error,
    )
# //doneee

def _route_coords_for_geojson(route: dict) -> list[list[float]]:
    calc = route.get("calc") or {}
    segments = calc.get("segments") or []

    if segments:
        coords: list[list[float]] = []
        first = segments[0].get("from", {})
        coords.append([first.get("lon"), first.get("lat")])  # GeoJSON: [lon, lat]

        for s in segments:
            to = s.get("to", {})
            coords.append([to.get("lon"), to.get("lat")])

        return coords

    raw = (route.get("waypoints_raw") or "").strip()
    if not raw:
        raise ValueError("This route has no waypoints saved yet.")

    points = parse_waypoints(raw)
    if len(points) < 2:
        raise ValueError("You need at least 2 waypoints to export GeoJSON.")

    return [[lon, lat] for (lat, lon) in points]


def _route_geojson_feature(route: dict, include_id: bool = False) -> dict:
    calc = route.get("calc") or {}
    coords = _route_coords_for_geojson(route)

    if len(coords) < 2:
        raise ValueError("Not enough points to build a LineString.")

    props = {
        "name": route.get("name", ""),
        "departure": route.get("departure", ""),
        "destination": route.get("destination", ""),
        "total_nm": calc.get("total_nm"),
        "eta_hhmm": calc.get("total_eta_hhmm"),
        "author": route.get("author", ""),
    }
    if include_id:
        props["id"] = route.get("id")

    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


@app.route("/route/geojson/<int:index>")
def export_route_geojson(index):
    data = load_data()
    routes = data.get("routes", [])

    if not (0 <= index < len(routes)):
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    r = routes[index]

    try:
        feature = _route_geojson_feature(r, include_id=False)
        geojson = {"type": "FeatureCollection", "features": [feature]}

        response = make_response(json.dumps(geojson, ensure_ascii=False, indent=2))
        response.headers["Content-Type"] = "application/geo+json; charset=utf-8"
        response.headers["Content-Disposition"] = f"attachment; filename=route_{index + 1}.geojson"
        return response

    except Exception as e:
        flash(f"GeoJSON export failed: {e}", "error")
        return redirect(url_for("route_planner"))


@app.route("/route/<int:route_id>/geojson")
def route_geojson_by_id(route_id):
    data = load_data()
    data = ensure_route_ids(data)
    routes = data.get("routes", [])

    r = next((x for x in routes if x.get("id") == route_id), None)
    if not r:
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    try:
        feature = _route_geojson_feature(r, include_id=True)
        return {"type": "FeatureCollection", "features": [feature]}

    except Exception as e:
        return {"type": "FeatureCollection", "features": [], "error": str(e)}


@app.route("/route/export/<int:index>")
def export_route_csv(index):
    data = load_data()
    routes = data.get("routes", [])

    if not (0 <= index < len(routes)):
        return redirect(url_for("route_planner"))

    r = routes[index]
    calc = r.get("calc") or {}
    segments = calc.get("segments") or []

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["route_name", "departure", "destination", "speed_kn", "total_nm", "total_eta_hhmm"])
    writer.writerow([
        r.get("name", ""),
        r.get("departure", ""),
        r.get("destination", ""),
        calc.get("speed_kn", ""),
        calc.get("total_nm", ""),
        calc.get("total_eta_hhmm", ""),
    ])

    writer.writerow([])
    writer.writerow(["seg_no", "from_lat", "from_lon", "to_lat", "to_lon", "distance_nm", "bearing_deg", "eta_hhmm"])

    for i, s in enumerate(segments, start=1):
        writer.writerow([
            i,
            (s.get("from") or {}).get("lat", ""),
            (s.get("from") or {}).get("lon", ""),
            (s.get("to") or {}).get("lat", ""),
            (s.get("to") or {}).get("lon", ""),
            s.get("distance_nm", ""),
            s.get("bearing_deg", ""),
            s.get("eta_hhmm", ""),
        ])

    response = make_response(output.getvalue())
    safe_name = (r.get("name") or "route").replace(" ", "_")
    response.headers["Content-Disposition"] = f"attachment; filename={safe_name}.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response
# //doneee
@app.route("/logbook", methods=["GET", "POST"])
def logbook():
    data = load_data()
    log_entries = data.get("log_entries", [])

    if request.method == "POST":
        entry = {
            "date": request.form.get("entry_date", "").strip(),
            "time": request.form.get("entry_time", "").strip(),
            "position": request.form.get("position", "").strip(),
            "category": (request.form.get("category", "").strip() or "Other"),
            "notes": request.form.get("log_notes", "").strip(),
        }

        log_entries.append(entry)
        data["log_entries"] = log_entries
        save_data(data)
        return redirect(url_for("logbook"))

    return render_template("logbook.html", log_entries=log_entries)


@app.route("/logbook/delete/<int:index>", methods=["POST"])
def delete_log_entry(index):
    data = load_data()
    log_entries = data.get("log_entries", [])

    if 0 <= index < len(log_entries):
        log_entries.pop(index)
        data["log_entries"] = log_entries
        save_data(data)

    return redirect(url_for("logbook"))


@app.route("/logbook/export")
def export_logbook():
    data = load_data()
    log_entries = data.get("log_entries", [])

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["date", "time", "position", "category", "notes"])

    for entry in log_entries:
        notes = (entry.get("notes") or "").replace("\r\n", " ").replace("\n", " ")
        writer.writerow([
            entry.get("date", ""),
            entry.get("time", ""),
            entry.get("position", ""),
            entry.get("category", ""),
            notes,
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=logbook.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@app.route("/contacts", methods=["GET", "POST"])
def contacts():
    data = load_data()
    contacts_list = data.get("contacts", [])
    personal_contacts_all = data.get("personal_contacts", [])

    selected_port = request.args.get("port", "").strip()

    if request.method == "POST":
        if not require_login():
            port_back = request.form.get("port", "").strip()
            return redirect(url_for("contacts", port=port_back) if port_back else url_for("contacts"))

        form_type = request.form.get("form_type", "")
        if form_type != "personal":
            return redirect(url_for("contacts", port=selected_port) if selected_port else url_for("contacts"))

        port = request.form.get("port", "").strip()
        person_name = request.form.get("person_name", "").strip()
        person_role = request.form.get("person_role", "").strip()
        person_phone = request.form.get("person_phone", "").strip()
        person_notes = request.form.get("person_notes", "").strip()

        if person_name and port:
            personal_contacts_all.append({
                "port": port,
                "name": person_name,
                "role": person_role,
                "phone": person_phone,
                "notes": person_notes,
                "user_id": session.get("user_id"),
            })
            data["personal_contacts"] = personal_contacts_all
            save_data(data)

        return redirect(url_for("contacts", port=port))

    ports = sorted(
        {c.get("port", "") for c in contacts_list} |
        {p.get("port", "") for p in personal_contacts_all}
    )
    ports = [p for p in ports if p]

    if selected_port:
        official_filtered = [
            c for c in contacts_list
            if (c.get("port") or "").strip() == selected_port
        ]

        personal_filtered = []
        for idx, p in enumerate(personal_contacts_all):
            if (p.get("port") or "").strip() == selected_port:
                item = dict(p)
                item["idx"] = idx
                personal_filtered.append(item)

        port_stats = compute_contact_stats_for_port(
            contacts_list,
            personal_contacts_all,
            selected_port,
        )
    else:
        official_filtered = []
        personal_filtered = []
        port_stats = None

    return render_template(
        "contacts.html",
        ports=ports,
        selected_port=selected_port,
        official_contacts=official_filtered,
        personal_contacts=personal_filtered,
        port_stats=port_stats,
        total_official=len(contacts_list),
        total_personal=len(personal_contacts_all),
        total_ports=len(ports),
    )
# //doneee

@app.route("/contacts/personal/delete/<int:index>", methods=["POST"])
def delete_personal_contact(index):
    if not require_login():
        return redirect(url_for("contacts"))

    data = load_data()
    personal_contacts_all = data.get("personal_contacts", [])

    uid = session.get("user_id")
    current_user = g.get("current_user")
    is_admin = bool(current_user and current_user.get("is_admin", False))

    deleted_port = ""

    if 0 <= index < len(personal_contacts_all):
        item = personal_contacts_all[index]
        deleted_port = (item.get("port") or "").strip()

        is_owner = (item.get("user_id") == uid)
        if not (is_admin or is_owner):
            flash("You are not allowed to delete this contact.", "error")
            return redirect(url_for("contacts", port=deleted_port)) if deleted_port else redirect(url_for("contacts"))

        personal_contacts_all.pop(index)
        data["personal_contacts"] = personal_contacts_all
        save_data(data)
        flash("Contact deleted.", "success")

    return redirect(url_for("contacts", port=deleted_port)) if deleted_port else redirect(url_for("contacts"))


@app.route("/weather", methods=["GET", "POST"])
def weather():
    data = load_data()
    notes = data.get("weather_notes", [])

    if request.method == "POST":
        if not require_login():
            return redirect(url_for("weather"))

        note_text = request.form.get("weather_note", "").strip()
        if note_text:
            notes.append({
                "text": note_text,
                "user_id": session.get("user_id"),
                "created_at": datetime.utcnow().isoformat(),
            })
            data["weather_notes"] = notes
            save_data(data)

        return redirect(url_for("weather"))

    return render_template("weather.html", weather_notes=notes)


@app.route("/weather/delete/<int:index>", methods=["POST"])
def weather_delete(index):
    if not require_login():
        return redirect(url_for("weather"))

    data = load_data()
    notes = data.get("weather_notes", [])

    uid = session.get("user_id")
    current_user = g.get("current_user")
    is_admin = bool(current_user and current_user.get("is_admin", False))

    if 0 <= index < len(notes):
        item = notes[index]

        if isinstance(item, dict):
            is_owner = (item.get("user_id") == uid)
        else:
            is_owner = True  # format vechi: nu există ownership real

        if not (is_admin or is_owner):
            flash("You are not allowed to delete this note.", "error")
            return redirect(url_for("weather"))

        notes.pop(index)
        data["weather_notes"] = notes
        save_data(data)
        flash("Weather note deleted.", "success")

    return redirect(url_for("weather"))
# //doneee

def build_summary(data: dict) -> dict:
    return {
        "voyages": len(data.get("voyages", [])),
        "routes": len(data.get("routes", [])),
        "log_entries": len(data.get("log_entries", [])),
        "contacts": len(data.get("contacts", [])),
        "personal_contacts": len(data.get("personal_contacts", [])),
        "weather_notes": len(data.get("weather_notes", [])),
    }


@app.route("/settings")
def settings():
    data = load_data()
    return render_template(
        "settings.html",
        summary=build_summary(data),
        import_error=None,
        import_success=False,
    )


@app.route("/settings/export")
def export_settings():
    data = load_data()
    json_text = json.dumps(data, indent=2, ensure_ascii=False)

    response = make_response(json_text)
    response.headers["Content-Disposition"] = "attachment; filename=ned_data.json"
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return response


@app.route("/settings/import", methods=["POST"])
def import_settings():
    raw_json = request.form.get("json_content", "").strip()
    data = load_data()
    summary = build_summary(data)

    if not raw_json:
        return render_template(
            "settings.html",
            summary=summary,
            import_error="Empty JSON content.",
            import_success=False,
        )

    try:
        new_data = json.loads(raw_json)
        if not isinstance(new_data, dict):
            raise ValueError("Top-level JSON must be an object (dictionary).")

        save_data(new_data)

        data = load_data()
        return render_template(
            "settings.html",
            summary=build_summary(data),
            import_error=None,
            import_success=True,
        )

    except Exception as e:
        return render_template(
            "settings.html",
            summary=summary,
            import_error=str(e),
            import_success=False,
        )


@app.route("/settings/reset", methods=["POST"])
def reset_settings():
    data = load_data()
    contacts = data.get("contacts", [])

    new_data = {
        "voyages": [],
        "routes": [],
        "log_entries": [],
        "contacts": contacts,
        "personal_contacts": [],
        "weather_notes": [],
    }

    save_data(new_data)

    return render_template(
        "settings.html",
        summary={
            "voyages": 0,
            "routes": 0,
            "log_entries": 0,
            "contacts": len(contacts),
            "personal_contacts": 0,
            "weather_notes": 0,
        },
        import_error=None,
        import_success=False,
    )


def get_phrasebook():
    return [
        {
            "ro": "Bună ziua, domnule căpitan, sunt nava ...",
            "en": "Good day, Captain, this is vessel ...",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Eu o să-mi păstrez drumul.",
            "en": "I will keep my course.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Ne întâlnim dreapta-dreapta.",
            "en": "We will pass starboard to starboard.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Ne întâlnim la austec.",
            "en": "We will pass port to port.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Nu am posibilitatea de manevră.",
            "en": "I am not under command / unable to manoeuvre.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Vreau să ancorez.",
            "en": "I intend to anchor.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Să aveți o zi bună.",
            "en": "Have a good day.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Mulțumesc.",
            "en": "Thank you.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
        {
            "ro": "Am o problemă la motoare.",
            "en": "I have an engine problem.",
            "de": "",
            "fr": "",
            "ru": "",
            "hu": "",
        },
    ]
# /doneee
@app.route("/help")
def help_page():
    return render_template("help.html", phrases=get_phrasebook())


@app.route("/api/locations/suggest")
def api_locations_suggest():
    q = request.args.get("q", "").strip()
    locations_path = os.path.join(app.root_path, "data", "locations.json")
    return {"results": suggest_locations(q, locations_path, limit=10)}


@app.route("/route/<int:route_id>/map")
def route_map(route_id):
    data = load_data()
    data = ensure_route_ids(data)
    routes = data.get("routes", [])

    r = next((x for x in routes if x.get("id") == route_id), None)
    if not r:
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    calc = r.get("calc") or {}
    return render_template(
        "route_map.html",
        route=r,
        current_username=session.get("username"),
        total_nm=calc.get("total_nm"),
        total_eta=calc.get("total_eta_hhmm"),
    )


@app.route("/route/chat/<int:route_id>", methods=["GET", "POST"])
def route_chat(route_id):
    data = load_data()
    data = ensure_route_ids(data)
    routes = data.get("routes", [])

    route = next((r for r in routes if r.get("id") == route_id), None)
    if not route:
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Please log in to post in route chat.", "error")
            return redirect(url_for("login"))

        current_user = get_current_user(data)
        if not can_user_post(current_user):
            flash("Posting is disabled for your account.", "error")
            return redirect(url_for("route_chat", route_id=route_id))

        text = request.form.get("message", "").strip()
        ok, err = add_route_message(
            route,
            author=session.get("username", "user"),
            author_id=session.get("user_id"),
            text=text,
        )

        if ok:
            save_data(data)
        else:
            flash(err or "Message not sent.", "error")

        return redirect(url_for("route_chat", route_id=route_id))

    messages = route.get("chat", [])
    related_routes = related_routes_for(routes, route, limit=10)

    return render_template(
        "chat.html",
        route=route,
        messages=messages,
        related_routes=related_routes,
        is_admin=is_admin_user(data),
        current_username=session.get("username"),
    )


@app.route("/route/chat/<int:route_id>/delete/<int:msg_id>", methods=["POST"])
def admin_delete_route_message(route_id, msg_id):
    data = load_data()
    data = ensure_route_ids(data)

    if not is_admin_user(data):
        return redirect(url_for("login"))

    routes = data.get("routes", [])
    route = next((r for r in routes if r.get("id") == route_id), None)
    if not route:
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    removed = delete_route_message(route, msg_id)
    save_data(data)

    flash("Message removed." if removed else "Message not found.", "success" if removed else "error")
    return redirect(url_for("route_chat", route_id=route_id))


@app.route("/route/delete/<int:route_id>", methods=["POST"])
def delete_route(route_id):
    data = load_data()
    data = ensure_route_ids(data)

    uid = session.get("user_id")
    if not uid:
        return redirect(url_for("login"))

    current_user = g.get("current_user")
    if not current_user:
        return redirect(url_for("login"))

    routes = data.get("routes", [])
    route = next((r for r in routes if r.get("id") == route_id), None)
    if not route:
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    is_admin = bool(current_user.get("is_admin", False))
    is_owner = (route.get("author_id") == uid)
    if not (is_admin or is_owner):
        flash("You are not allowed to delete this route.", "error")
        return redirect(url_for("route_planner"))

    data["routes"] = [r for r in routes if r.get("id") != route_id]
    save_data(data)

    flash("Route deleted.", "success")
    return redirect(url_for("route_planner"))


@app.route("/communication")
def communication():
    data = load_phrases_data()

    category = request.args.get("category", "").strip()
    q = request.args.get("q", "").strip()

    categories = data.get("categories", []) or []
    phrases = filter_phrases(data, category=category, q=q)

    return render_template(
        "communication.html",
        categories=categories,
        phrases=phrases,
        selected_category=category,
        q=q,
    )


@app.route("/route/done/<int:route_id>", methods=["POST"])
def mark_route_done(route_id):
    uid = session.get("user_id")
    if not uid:
        return redirect(url_for("login"))

    data = load_data()
    data = ensure_route_ids(data)

    current_user = g.get("current_user")
    if not current_user:
        return redirect(url_for("login"))

    routes = data.get("routes", [])
    route = next((r for r in routes if r.get("id") == route_id), None)
    if not route:
        flash("Route not found.", "error")
        return redirect(url_for("route_planner"))

    is_admin = bool(current_user.get("is_admin", False))
    is_owner = (route.get("author_id") == uid)
    if not (is_admin or is_owner):
        flash("You are not allowed to modify this route.", "error")
        return redirect(url_for("route_planner"))

    route["status"] = "done"
    route["done_at"] = datetime.utcnow().isoformat()

    voyages = data.get("voyages", [])
    already = next((v for v in voyages if v.get("source_route_id") == route_id), None)

    if not already:
        vids = [v.get("id", 0) for v in voyages if isinstance(v.get("id", 0), int)]
        next_vid = (max(vids) + 1) if vids else 1

        voyage = {
            "id": next_vid,
            "source_route_id": route_id,
            "title": route.get("name") or f"{route.get('departure','')} - {route.get('destination','')}".strip(" -"),
            "departure": route.get("departure", ""),
            "destination": route.get("destination", ""),
            "author": route.get("author", ""),
            "author_id": route.get("author_id"),
            "user_id": route.get("author_id"),
            "created_at": datetime.utcnow().isoformat(),
            "done_at": route.get("done_at"),
            "notes": "",
            "tags": [],
            "route_snapshot": route,
            "checklist": route.get("checklist", {}),
            "etd": "",
            "eta": route.get("calc", {}).get("total_eta_hhmm", ""),
            "distance_nm": str(route.get("calc", {}).get("total_nm", "")),
        }

        voyages.append(voyage)
        data["voyages"] = voyages

    save_data(data)
    flash("Route marked as DONE.", "success")

    created = next((v for v in data.get("voyages", []) if v.get("source_route_id") == route_id), None)
    if created:
        return redirect(url_for("voyage_detail", voyage_id=created["id"]))

    return redirect(url_for("route_planner"))


if __name__ == "__main__":
    app.run(debug=True)

