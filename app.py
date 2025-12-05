from flask import Flask, render_template, request, redirect, url_for
from data_utils import load_data, save_data

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

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

@app.route("/contacts", methods=["GET", "POST"])
def contacts():
    data = load_data()
    contacts = data.get("contacts", [])
    personal_contacts_all = data.get("personal_contacts", [])

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

    # filtrare pentru portul selectat
    if selected_port:
        official_filtered = [c for c in contacts if c.get("port") == selected_port]
        personal_filtered = [p for p in personal_contacts_all if p.get("port") == selected_port]
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

@app.route("/weather")
def weather():
    return render_template("weather.html")

@app.route("/settings")
def settings():
    return render_template("settings.html")


if __name__ == "__main__":
    app.run(debug=True)
