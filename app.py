from flask import Flask, render_template, request, redirect, url_for, session, make_response
from data_utils import load_data, save_data
from werkzeug.security import generate_password_hash, check_password_hash
from collections import Counter

import json
import csv 
import io
import math
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "change-this-in-production"


def haversine_nm(lat1, lon1, lat2, lon2):
    """
    Great-circle distance in nautical miles (NM).
    Input: decimal degrees.
    """
    R_km = 6371.0
    km_to_nm = 0.539956803

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    km = R_km * c
    return km * km_to_nm


def bearing_deg(lat1, lon1, lat2, lon2):
    """
    Initial bearing (0..360 degrees) from point 1 to point 2.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lam = math.radians(lon2 - lon1)

    y = math.sin(d_lam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lam)

    brng = math.degrees(math.atan2(y, x))
    return (brng + 360) % 360


def parse_waypoints(text):
    """
    Accepts multiline or semicolon-separated:
      lat, lon
      45.12, 29.89
      44.16, 28.64

    Returns list of tuples: [(lat, lon), ...]
    Raises ValueError with a friendly message.
    """
    if not text or not text.strip():
        raise ValueError("Waypoints are empty. Add at least 2 points (lat, lon).")

    # split by newlines first, also allow ';'
    raw_lines = []
    for part in text.replace(";", "\n").splitlines():
        line = part.strip()
        if line:
            raw_lines.append(line)

    points = []
    for i, line in enumerate(raw_lines, start=1):
        # allow "lat, lon" or "lat lon"
        if "," in line:
            pieces = [p.strip() for p in line.split(",")]
        else:
            pieces = [p.strip() for p in line.split()]

        if len(pieces) != 2:
            raise ValueError(f"Waypoint line {i} is invalid. Use 'lat, lon' (example: 44.16, 28.64).")

        try:
            lat = float(pieces[0])
            lon = float(pieces[1])
        except ValueError:
            raise ValueError(f"Waypoint line {i} has non-numeric values.")

        if not (-90 <= lat <= 90):
            raise ValueError(f"Waypoint line {i}: latitude must be between -90 and 90.")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Waypoint line {i}: longitude must be between -180 and 180.")

        points.append((lat, lon))

    if len(points) < 2:
        raise ValueError("You need at least 2 waypoints (start and end).")

    return points


def hours_to_hhmm(hours_float):
    if hours_float is None:
        return "-"
    total_minutes = int(round(hours_float * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def compute_voyage_stats(voyages):
    """
    Primește lista de voyages (dict-uri) și calculează:
      - distanța totală (în NM)
      - cel mai lung voyage
      - cele mai frecvente porturi de plecare/destinație
    """
    total_distance = 0.0
    distances = []  # (distance, voyage_dict)
    departures = []
    destinations = []

    for v in voyages:
        # distanță
        dist_raw = v.get("distance_nm")
        if dist_raw is not None and dist_raw != "":
            try:
                dist_val = float(dist_raw)
                total_distance += dist_val
                distances.append((dist_val, v))
            except ValueError:
                # dacă nu se poate converti, îl ignorăm
                pass

        # porturi
        dep = (v.get("departure") or "").strip()
        dest = (v.get("destination") or "").strip()
        if dep:
            departures.append(dep)
        if dest:
            destinations.append(dest)

    # longest voyage
    longest_voyage = None
    if distances:
        dist_val, v = max(distances, key=lambda x: x[0])
        longest_voyage = {
            "distance_nm": dist_val,
            "departure": v.get("departure"),
            "destination": v.get("destination"),
        }

    # top ports
    top_departures = Counter(departures).most_common(3)
    top_destinations = Counter(destinations).most_common(3)

    return {
        "total_distance_nm": round(total_distance, 1),
        "longest_voyage": longest_voyage,
        "top_departures": top_departures,
        "top_destinations": top_destinations,
    }

def compute_contact_stats_for_port(official_contacts, personal_contacts, port_name):
    """
    Calculează statistici simple pentru un port:
      - număr de contacte oficiale
      - număr de contacte personale
      - top roluri/tipuri de contacte (MRCC, Agent, Pilot etc.)
    """
    official = [c for c in official_contacts if (c.get("port") or "").strip() == port_name]
    personal = [p for p in personal_contacts if (p.get("port") or "").strip() == port_name]

    roles = []
    for c in official + personal:
        role = (c.get("role") or c.get("type") or "").strip()
        if role:
            roles.append(role)

    role_counts = Counter(roles).most_common(3)

    return {
        "official_count": len(official),
        "personal_count": len(personal),
        "total_count": len(official) + len(personal),
        "top_roles": role_counts,
    }



@app.context_processor
def inject_current_user():
    return {
        "current_username": session.get("username"),
        "current_user_id": session.get("user_id"),
    }


# @app.route("/")
# def home():
#     data = load_data()
#     voyages = data.get("voyages", [])

#     summary = {
#         "voyages": len(voyages),
#         "routes": len(data.get("routes", [])),
#         "log_entries": len(data.get("log_entries", [])),
#         "contacts": len(data.get("contacts", [])) + len(data.get("personal_contacts", [])),
#         "weather_notes": len(data.get("weather_notes", [])),
#     }

#     voyage_stats = compute_voyage_stats(voyages)

#     return render_template(
#         "index.html",
#         summary=summary,
#         voyage_stats=voyage_stats,
#     )


@app.route("/")
def home():
    data = load_data()
    users = data.get("users", [])

    uid = session.get("user_id")
    current_user = next((u for u in users if u.get("id") == uid), None)

    # dacă este admin -> trimitem direct la panoul de control
    if current_user and current_user.get("is_admin", False):
        return redirect(url_for("admin_panel"))

    # dacă NU este admin -> afișăm dashboard-ul standard
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

    uid = session.get("user_id")
    current_user = next((u for u in users if u.get("id") == uid), None)

    # doar adminul are voie aici
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



@app.route("/admin/reset_password", methods=["POST"])
def admin_reset_password():
    data = load_data()
    users = data.get("users", [])

    uid = session.get("user_id")
    current_user = next((u for u in users if u.get("id") == uid), None)

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

    # reload summary pentru afișare
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

        # validări simple
        if not username or not password:
            return render_template("register.html", error="Username and password are required.")

        if len(password) < 4:
            return render_template("register.html", error="Password should have at least 4 characters.")

        # verifică dacă există deja username-ul
        for u in users:
            if u.get("username") == username:
                return render_template("register.html", error="Username already taken.")

        # calculează următorul id
        if users:
            max_id = max(u.get("id", 0) for u in users)
            new_id = max_id + 1
        else:
            new_id = 1

            user = {
            "id": new_id,
            "username": username,
            "password_hash": generate_password_hash(password),
            "is_admin": False,   # cont normal, fără drepturi de admin
            "can_post": True,    # poate posta (voyages, contacts etc.)
        }


        users.append(user)
        data["users"] = users
        save_data(data)

        # auto-login după register
        session["user_id"] = new_id
        session["username"] = username

        return redirect(url_for("home"))  

    return render_template("register.html", error=None)

@app.route("/login", methods=["GET", "POST"])
def login():
    data = load_data()
    users = data.get("users", [])

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # caută userul
        user = None
        for u in users:
            if u.get("username") == username:
                user = u
                break

        if user is None:
            return render_template("login.html", error="Invalid username or password.")

        if not check_password_hash(user.get("password_hash", ""), password):
            return render_template("login.html", error="Invalid username or password.")

        # login ok
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

        # validări de bază
        if not username or not password or not password2:
            return render_template(
                "forgot_password.html",
                error="All fields are required.",
                success=None,
            )

        if password != password2:
            return render_template(
                "forgot_password.html",
                error="Passwords do not match.",
                success=None,
            )

        # căutăm userul după username
        target = None
        for u in users:
            if u.get("username") == username:
                target = u
                break

        if target is None:
            return render_template(
                "forgot_password.html",
                error="Username not found.",
                success=None,
            )

        # schimbăm parola (hash)
        target["password_hash"] = generate_password_hash(password)
        data["users"] = users
        save_data(data)

        return render_template(
            "forgot_password.html",
            error=None,
            success="Password successfully reset. You can now log in with the new password.",
        )

    # GET simplu
    return render_template(
        "forgot_password.html",
        error=None,
        success=None,
    )



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
        # create or update based on hidden voyage_index
        idx_str = request.form.get("voyage_index", "").strip()

        departure = request.form.get("departure", "").strip()
        destination = request.form.get("destination", "").strip()
        etd = request.form.get("etd", "").strip()
        eta = request.form.get("eta", "").strip()
        distance_nm = request.form.get("distance_nm", "").strip()
        notes = request.form.get("notes", "").strip()

        # dacă editezi → păstrăm checklist-ul și user_id-ul vechi
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
            # dacă e editare -> păstrăm user_id-ul, dacă e nou -> punem user-ul logat (sau None)
            "user_id": existing_user_id if idx_str else session.get("user_id"),
        }

        if idx_str:
            try:
                idx = int(idx_str)
                if 0 <= idx < len(voyages):
                    voyages[idx] = new_voyage
                else:
                    voyages.append(new_voyage)
            except ValueError:
                voyages.append(new_voyage)
        else:
            voyages.append(new_voyage)

        data["voyages"] = voyages
        save_data(data)

        return redirect(url_for("voyage_sheet"))

    # ------------------ GET REQUEST BELOW ------------------

    # handle GET parameters: view (for notes)
    view_index = request.args.get("view")
    if view_index is not None:
        try:
            idx = int(view_index)
            if 0 <= idx < len(voyages):
                selected_voyage = voyages[idx]
                selected_index = idx + 1
        except ValueError:
            pass

    # handle GET parameters: edit (for loading form)
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

    # count voyages
    voyage_count = len(voyages)

    # count voyages belonging to this user
    current_user_id = session.get("user_id")
    user_voyage_count = None
    if current_user_id:
        user_voyage_count = sum(
            1 for v in voyages
            if v.get("user_id") == current_user_id
        )

    return render_template(
        "voyage_sheet.html",
        voyages=voyages,
        selected_voyage=selected_voyage,
        selected_index=selected_index,
        editing=editing,
        edit_index=edit_index,
        form_voyage=form_voyage
    )



@app.route("/voyage/delete/<int:index>", methods=["POST"])
def delete_voyage(index):
    data = load_data()
    voyages = data.get("voyages", [])

    if 0 <= index < len(voyages):
        voyages.pop(index)
        data["voyages"] = voyages
        save_data(data)

    return redirect(url_for("voyage_sheet"))

@app.route("/voyage/checklist/<int:index>", methods=["POST"])
def update_checklist(index):
    data = load_data()
    voyages = data.get("voyages", [])

    if 0 <= index < len(voyages):
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

    return redirect(url_for("voyage_sheet", view=index))


@app.route("/route", methods=["GET", "POST"])
def route_planner():
    data = load_data()
    routes = data.get("routes", [])

    calc_result = None
    calc_error = None

    if request.method == "POST":
        # dacă vrei doar user logat să salveze rute:
        if not session.get("user_id"):
            return redirect(url_for("login"))

        route_name = request.form.get("route_name", "").strip()
        route_departure = request.form.get("route_departure", "").strip()
        route_destination = request.form.get("route_destination", "").strip()

        speed_kn_str = request.form.get("speed_kn", "").strip()
        waypoints_text = request.form.get("waypoints", "").strip()
        route_notes = request.form.get("route_notes", "").strip()

        # checklist (dacă îl păstrezi)
        checklist = {
            "fuel": "fuel" in request.form,
            "weather": "weather" in request.form,
            "crew": "crew" in request.form,
            "documents": "documents" in request.form,
            "safety": "safety" in request.form,
        }

        # parse + calc
        try:
            if not speed_kn_str:
                raise ValueError("Speed (kn) is required.")
            speed_kn = float(speed_kn_str)
            if speed_kn <= 0:
                raise ValueError("Speed must be > 0 knots.")

            points = parse_waypoints(waypoints_text)

            segments = []
            total_nm = 0.0
            total_hours = 0.0

            for i in range(len(points) - 1):
                (lat1, lon1) = points[i]
                (lat2, lon2) = points[i + 1]

                dist_nm = haversine_nm(lat1, lon1, lat2, lon2)
                brng = bearing_deg(lat1, lon1, lat2, lon2)

                seg_hours = dist_nm / speed_kn if speed_kn else None

                segments.append({
                    "from": {"lat": lat1, "lon": lon1},
                    "to": {"lat": lat2, "lon": lon2},
                    "distance_nm": round(dist_nm, 2),
                    "bearing_deg": round(brng, 1),
                    "eta_hours": round(seg_hours, 2) if seg_hours is not None else None,
                    "eta_hhmm": hours_to_hhmm(seg_hours) if seg_hours is not None else "-",
                })

                total_nm += dist_nm
                total_hours += seg_hours

            calc_result = {
                "speed_kn": speed_kn,
                "total_nm": round(total_nm, 2),
                "total_eta_hours": round(total_hours, 2),
                "total_eta_hhmm": hours_to_hhmm(total_hours),
                "segments": segments,
            }

            new_route = {
                "name": route_name or f"{route_departure} - {route_destination}".strip(" -"),
                "departure": route_departure,
                "destination": route_destination,
                "waypoints_raw": waypoints_text,
                "notes": route_notes,
                "checklist": checklist,
                "calc": calc_result,
                "author": session.get("username") or "Unknown",
            }

            routes.append(new_route)
            data["routes"] = routes
            save_data(data)

            return redirect(url_for("route_planner"))

        except Exception as e:
            calc_error = str(e)

    return render_template(
        "route_planner.html",
        routes=routes,
        calc_result=calc_result,
        calc_error=calc_error
    )

@app.route("/route/export/<int:index>")
def export_route_csv(index):
    data = load_data()
    routes = data.get("routes", [])

    if index < 0 or index >= len(routes):
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
            s.get("from", {}).get("lat", ""),
            s.get("from", {}).get("lon", ""),
            s.get("to", {}).get("lat", ""),
            s.get("to", {}).get("lon", ""),
            s.get("distance_nm", ""),
            s.get("bearing_deg", ""),
            s.get("eta_hhmm", ""),
        ])

    response = make_response(output.getvalue())
    safe_name = (r.get("name") or "route").replace(" ", "_")
    response.headers["Content-Disposition"] = f"attachment; filename={safe_name}.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@app.route("/logbook", methods=["GET", "POST"])
def logbook():
    data = load_data()
    log_entries = data.get("log_entries", [])

    if request.method == "POST":
        entry_date = request.form.get("entry_date", "").strip()
        entry_time = request.form.get("entry_time", "").strip()
        position = request.form.get("position", "").strip()
        category = request.form.get("category", "").strip() or "Other"
        log_notes = request.form.get("log_notes", "").strip()

        new_entry = {
            "date": entry_date,
            "time": entry_time,
            "position": position,
            "category": category,
            "notes": log_notes,
        }

        log_entries.append(new_entry)
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

    # pregătim un CSV în memorie
    output = io.StringIO()
    writer = csv.writer(output)

    # antet
    writer.writerow(["date", "time", "position", "category", "notes"])

    # rânduri
    for entry in log_entries:
        writer.writerow([
            entry.get("date", ""),
            entry.get("time", ""),
            entry.get("position", ""),
            entry.get("category", ""),
            entry.get("notes", "").replace("\r\n", " ").replace("\n", " ")
        ])

    # pregătim răspunsul HTTP cu attachment
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=logbook.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"

    return response


@app.route("/contacts", methods=["GET", "POST"])
def contacts():
    data = load_data()
    contacts = data.get("contacts", [])
    personal_contacts_all = data.get("personal_contacts", [])

    # port selectat din query string, ex: /contacts?port=Constanța
    selected_port = request.args.get("port", "").strip()

    # dacă vine un POST, e formularul de personal contact
    if request.method == "POST":
        form_type = request.form.get("form_type", "")
        if form_type == "personal":
            port = request.form.get("port", "").strip()
            person_name = request.form.get("person_name", "").strip()
            person_role = request.form.get("person_role", "").strip()
            person_phone = request.form.get("person_phone", "").strip()
            person_notes = request.form.get("person_notes", "").strip()

            if person_name and port:
                new_personal = {
                    "port": port,
                    "name": person_name,
                    "role": person_role,
                    "phone": person_phone,
                    "notes": person_notes,
                }
                personal_contacts_all.append(new_personal)
                data["personal_contacts"] = personal_contacts_all
                save_data(data)

            # după salvare, ne întoarcem la /contacts?port=<port>
            return redirect(url_for("contacts", port=port))

    # lista de porturi unice pentru dropdown (din contacts + personal_contacts)
    ports = sorted({c.get("port", "") for c in contacts} | {p.get("port", "") for p in personal_contacts_all})
    ports = [p for p in ports if p]  # scoatem stringuri goale

    if selected_port:
        # filtrare pentru portul selectat + atașăm indexul real din lista mare
        official_filtered = [c for c in contacts if (c.get("port") or "").strip() == selected_port]

        personal_filtered = []
        for idx, p in enumerate(personal_contacts_all):
            if (p.get("port") or "").strip() == selected_port:
                p_with_index = dict(p)
                p_with_index["idx"] = idx
                personal_filtered.append(p_with_index)

        port_stats = compute_contact_stats_for_port(contacts, personal_contacts_all, selected_port)
    else:
        official_filtered = []
        personal_filtered = []
        port_stats = None

    total_official = len(contacts)
    total_personal = len(personal_contacts_all)
    total_ports = len(ports)

    return render_template(
        "contacts.html",
        ports=ports,
        selected_port=selected_port,
        official_contacts=official_filtered,
        personal_contacts=personal_filtered,
        port_stats=port_stats,
        total_official=total_official,
        total_personal=total_personal,
        total_ports=total_ports,
    )

@app.route("/contacts/personal/delete/<int:index>", methods=["POST"])
def delete_personal_contact(index):
    data = load_data()
    personal_contacts_all = data.get("personal_contacts", [])

    deleted_port = ""
    if 0 <= index < len(personal_contacts_all):
        deleted_port = personal_contacts_all[index].get("port", "")
        personal_contacts_all.pop(index)
        data["personal_contacts"] = personal_contacts_all
        save_data(data)

    if deleted_port:
        return redirect(url_for("contacts", port=deleted_port))
    return redirect(url_for("contacts"))


@app.route("/weather", methods=["GET", "POST"])
def weather():
    data = load_data()
    notes = data.get("weather_notes", [])

    if request.method == "POST":
        note = request.form.get("weather_note", "").strip()
        if note:
            notes.append(note)
            data["weather_notes"] = notes
            save_data(data)
        return redirect(url_for("weather"))

    return render_template("weather.html", weather_notes=notes)

@app.route("/weather/delete/<int:index>", methods=["POST"])
def weather_delete(index):
    data = load_data()
    notes = data.get("weather_notes", [])

    if 0 <= index < len(notes):
        notes.pop(index)
        data["weather_notes"] = notes
        save_data(data)

    return redirect(url_for("weather"))



@app.route("/settings")
def settings():
    data = load_data()

    summary = {
        "voyages": len(data.get("voyages", [])),
        "routes": len(data.get("routes", [])),
        "log_entries": len(data.get("log_entries", [])),
        "contacts": len(data.get("contacts", [])),
        "personal_contacts": len(data.get("personal_contacts", [])),
        "weather_notes": len(data.get("weather_notes", [])),
    }

    # la GET simplu nu avem mesaje de import
    return render_template(
        "settings.html",
        summary=summary,
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

    summary = {
        "voyages": len(data.get("voyages", [])),
        "routes": len(data.get("routes", [])),
        "log_entries": len(data.get("log_entries", [])),
        "contacts": len(data.get("contacts", [])),
        "personal_contacts": len(data.get("personal_contacts", [])),
        "weather_notes": len(data.get("weather_notes", [])),
    }

    if not raw_json:
        return render_template(
            "settings.html",
            summary=summary,
            import_error="Empty JSON content.",
            import_success=False,
        )

    try:
        new_data = json.loads(raw_json)

        # opțional: mici verificări de structură
        if not isinstance(new_data, dict):
            raise ValueError("Top-level JSON must be an object (dictionary).")

        save_data(new_data)

        # recalculează summary după import
        data = load_data()
        summary = {
            "voyages": len(data.get("voyages", [])),
            "routes": len(data.get("routes", [])),
            "log_entries": len(data.get("log_entries", [])),
            "contacts": len(data.get("contacts", [])),
            "personal_contacts": len(data.get("personal_contacts", [])),
            "weather_notes": len(data.get("weather_notes", [])),
        }

        return render_template(
            "settings.html",
            summary=summary,
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

    # păstrăm official contacts, restul listelor le golim
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

    summary = {
        "voyages": 0,
        "routes": 0,
        "log_entries": 0,
        "contacts": len(contacts),
        "personal_contacts": 0,
        "weather_notes": 0,
    }

    return render_template(
        "settings.html",
        summary=summary,
        import_error=None,
        import_success=False,
    )


if __name__ == "__main__":
    app.run(debug=True)
