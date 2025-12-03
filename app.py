from flask import Flask, render_template, request
from data_utils import load_data, save_data

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/voyage", methods=["GET", "POST"])
def voyage_sheet():
    last_voyage = None

    if request.method == "POST":
        # read form fields
        departure = request.form.get("departure", "").strip()
        destination = request.form.get("destination", "").strip()
        etd = request.form.get("etd", "").strip()
        eta = request.form.get("eta", "").strip()
        distance_nm = request.form.get("distance_nm", "").strip()
        notes = request.form.get("notes", "").strip()

        # build a voyage dict
        last_voyage = {
            "departure": departure,
            "destination": destination,
            "etd": etd,
            "eta": eta,
            "distance_nm": distance_nm,
            "notes": notes,
        }

        # load JSON, append voyage, save back
        data = load_data()
        voyages = data.get("voyages", [])
        voyages.append(last_voyage)
        data["voyages"] = voyages
        save_data(data)

    return render_template("voyage_sheet.html", last_voyage=last_voyage)
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
