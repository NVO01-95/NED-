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


@app.route("/route")
def route_planner():
    return render_template("route_planner.html")

@app.route("/logbook")
def logbook():
    return render_template("logbook.html")

@app.route("/contacts")
def contacts():
    return render_template("contacts.html")

@app.route("/weather")
def weather():
    return render_template("weather.html")

@app.route("/settings")
def settings():
    return render_template("settings.html")


if __name__ == "__main__":
    app.run(debug=True)
