from flask import Flask
from flask import render_template
import json

app = Flask(__name__)

@app.route('/')
def my_runs():
    activities = []
    municipalities = {}
    with open("assets/municipality-merged-updated.json", "r") as topo:
        municipalities = json.load(topo)
    with open("data.json", "r") as activity_file:
        reader = json.load(activity_file)
        for row in reader:
            activities.append(row["map"]["summary_polyline"])
    return render_template("leaflet.html", activities = json.dumps(activities), municipalities = json.dumps(municipalities))

if __name__ == "__main__":
    app.run(port = 5001)