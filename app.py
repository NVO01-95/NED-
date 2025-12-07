from flask import Flask, render_template, request, redirect, url_for, session, make_response
from data_utils import load_data, save_data
from werkzeug.security import generate_password_hash, check_password_hash
import json
import csv 
import io
app = Flask(__name__)
app.secret_key = "change-this-in-production"

@app.context_processor
def inject_current_user():
    return {
        "current_username": session.get("username")
    }

@app.route("/")
def index():
    return render_template("index.html")


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
        }

        users.append(user)
        data["users"] = users
        save_data(data)

        # auto-login după register
        session["user_id"] = new_id
        session["username"] = username

        return redirect(url_for("index"))  # ajustează dacă ai altă rută principală

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

        return redirect(url_for("index"))  # sau altă pagină default

    return render_template("login.html", error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))  # sau altă rută principală


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

        # if editing, keep old checklist
        existing_checklist = {}
        if idx_str:
            try:
                idx = int(idx_str)
                if 0 <= idx < len(voyages):
                    existing_checklist = voyages[idx].get("checklist", {})
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

    # handle GET parameters: view (for notes) and edit (for loading form)
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

    return render_template(
        "voyage_sheet.html",
        voyages=voyages,
        selected_voyage=selected_voyage,
        selected_index=selected_index,
        editing=editing,
        edit_index=edit_index,
        form_voyage=form_voyage,
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

    if request.method == "POST":
        route_name = request.form.get("route_name", "").strip()
        route_departure = request.form.get("route_departure", "").strip()
        route_destination = request.form.get("route_destination", "").strip()
        waypoints = request.form.get("waypoints", "").strip()
        route_notes = request.form.get("route_notes", "").strip()

        checklist = {
            "fuel": "fuel" in request.form,
            "weather": "weather" in request.form,
            "crew": "crew" in request.form,
            "documents": "documents" in request.form,
            "safety": "safety" in request.form,
        }

        new_route = {
            "name": route_name,
            "departure": route_departure,
            "destination": route_destination,
            "waypoints": waypoints,
            "notes": route_notes,
            "checklist": checklist,
        }

        routes.append(new_route)
        data["routes"] = routes
        save_data(data)

        return redirect(url_for("route_planner"))

    return render_template("route_planner.html", routes=routes)


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
                    "notes": person_notes
                }
                personal_contacts_all.append(new_personal)
                data["personal_contacts"] = personal_contacts_all
                save_data(data)

            # după salvare, ne întoarcem la /contacts?port=<port>
            return redirect(url_for("contacts", port=port))

    # lista de porturi unice pentru dropdown (din contacts + personal_contacts)
    ports = sorted({c["port"] for c in contacts} | {p["port"] for p in personal_contacts_all})

    # filtrare pentru portul selectat + atașăm indexul real din lista mare
    if selected_port:
        official_filtered = [c for c in contacts if c.get("port") == selected_port]

        personal_filtered = []
        for idx, p in enumerate(personal_contacts_all):
            if p.get("port") == selected_port:
                # copiem dict-ul și îi atașăm indexul pentru delete
                p_with_index = dict(p)
                p_with_index["idx"] = idx
                personal_filtered.append(p_with_index)
    else:
        official_filtered = []
        personal_filtered = []

    return render_template(
        "contacts.html",
        ports=ports,
        selected_port=selected_port,
        official_contacts=official_filtered,
        personal_contacts=personal_filtered,
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
