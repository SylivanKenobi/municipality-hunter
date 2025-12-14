from flask import Flask
from flask import render_template
from utils import get_db_connection
import psycopg2
import json

app = Flask(__name__)

def get_activities():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            COALESCE(polyline_highres, polyline) AS polyline
        FROM activities WHERE polyline IS NOT NULL OR polyline_highres IS NOT NULL;
    """)

    polylines = [row[0] for row in cur.fetchall()]
    cur.close()
    return polylines

@app.route('/')
def my_runs():
    municipalities = {}
    
    with open("assets/municipality-merged-updated.json", "r") as topo:
        municipalities = json.load(topo)
    
    return render_template("leaflet.html", activities = json.dumps(get_activities()), municipalities = json.dumps(municipalities))

if __name__ == "__main__":
    app.run(port = 5001)