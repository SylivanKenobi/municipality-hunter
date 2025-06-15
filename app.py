from flask import Flask
from flask import render_template
import json

app = Flask(__name__)

@app.route('/')
def my_runs():
    activities = []
    municipalitiesCh = {}
    municipalitiesNl = {}
    with open("municipality-ch.json", "r") as topo:
        municipalitiesCh = json.load(topo)
    with open("municipality-nl.json", "r") as topo:
        municipalitiesNl = json.load(topo)
    merged = {
        "type": "FeatureCollection",
        "features": municipalitiesCh["features"] + municipalitiesNl["features"]
    }   
    with open("data.json", "r") as activity_file:
        reader = json.load(activity_file)
        for row in reader:
            activities.append(row["map"]["summary_polyline"])
    return render_template("leaflet.html", activities = json.dumps(activities), municipalities = json.dumps(merged))

if __name__ == "__main__":
    app.run(port = 5001)