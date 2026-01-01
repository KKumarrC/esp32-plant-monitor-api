from flask import Flask, request, jsonify
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "/tmp/plant_readings.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moisture INTEGER NOT NULL,
            temperature REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "message": "Plant Monitor API is running",
        "endpoints": [
            "POST /readings",
            "GET /readings/latest",
            "GET /readings/history?hours=168",
            "GET /readings/summary",
            "GET /status"
        ]
    })


@app.route("/readings", methods=["POST"])
def save_readings():
    data = request.get_json()

    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    if "moisture" not in data:
        return jsonify({"status": "error", "message": "moisture data is missing"}), 400

    if "temperature" not in data:
        return jsonify({"status": "error", "message": "temperature data is missing"}), 400

    try:
        moisture = int(data["moisture"])
        temperature = float(data["temperature"])
    except (ValueError, TypeError):
        return jsonify({
            "status": "error",
            "message": "Invalid data types: moisture must be integer, temperature must be number"
        }), 400

    if moisture < 0 or moisture > 2000:
        return jsonify({"status": "error", "message": "moisture levels are invalid"}), 400

    if temperature < -20 or temperature > 100:
        return jsonify({"status": "error", "message": "temperature levels are invalid"}), 400

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO readings (moisture, temperature)
        VALUES (?, ?)
    """, (moisture, temperature))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Reading saved successfully!"}), 201


@app.route("/readings/latest", methods=["GET"])
def latest_readings():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1")
    reading = cursor.fetchone()

    conn.close()

    if reading is None:
        return jsonify({"message": "No readings yet"}), 404

    return jsonify({
        "id": reading[0],
        "moisture": reading[1],
        "temperature": reading[2],
        "timestamp": reading[3]
    })


@app.route("/readings/history", methods=["GET"])
def reading_history():
    conn = get_conn()
    cursor = conn.cursor()

    hours = request.args.get("hours", 168, type=int)
    time_string = f"-{hours} hours"

    cursor.execute("""
        SELECT * FROM readings
        WHERE timestamp > datetime('now', ?)
        ORDER BY timestamp DESC
    """, (time_string,))
    readings = cursor.fetchall()

    conn.close()

    if not readings:
        return jsonify({"message": "No readings yet"}), 404

    result = []
    for reading in readings:
        result.append({
            "id": reading[0],
            "moisture": reading[1],
            "temperature": reading[2],
            "timestamp": reading[3]
        })

    return jsonify({"readings": result})


@app.route("/status", methods=["GET"])
def get_status():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1")
    latest = cursor.fetchone()

    if not latest:
        conn.close()
        return jsonify({"message": "No readings yet"}), 404

    cursor.execute("""
        SELECT moisture FROM readings
        WHERE timestamp <= datetime('now','-24 hours')
        ORDER BY timestamp DESC LIMIT 1
    """)
    yesterday = cursor.fetchone()

    conn.close()

    moisture_change = None
    if yesterday:
        moisture_change = latest[1] - yesterday[0]

    return jsonify({
        "current": {
            "moisture": latest[1],
            "temperature": latest[2],
            "timestamp": latest[3]
        },
        "changes": {
            "moisture_24h": moisture_change
        }
    })


@app.route("/delete-latest", methods=["POST"])
def delete_latest_reading():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1")
    latest = cursor.fetchone()

    if not latest:
        conn.close()
        return jsonify({"status": "error", "message": "No readings to delete"}), 404

    deleted_data = {
        "id": latest[0],
        "moisture": latest[1],
        "temperature": latest[2],
        "timestamp": latest[3]
    }

    cursor.execute("DELETE FROM readings WHERE id = ?", (latest[0],))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": "Deleted latest reading",
        "deleted": deleted_data
    }), 200


@app.route("/plant/reset", methods=["POST"])
def reset_plant_data():
    data = request.get_json()
    if not data or data.get("confirm") != "yes-delete-all":
        return jsonify({
            "status": "error",
            "message": "Confirmation required. Send {'confirm': 'yes-delete-all'}"
        }), 400

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM readings")
    count = cursor.fetchone()[0]

    if count == 0:
        conn.close()
        return jsonify({
            "status": "info",
            "message": "No readings to delete",
            "deleted_count": 0
        }), 200

    cursor.execute("DELETE FROM readings")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='readings'")
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": f"Plant data reset. Deleted {count} readings",
        "deleted_count": count,
        "reset_time": datetime.now().isoformat()
    }), 200


@app.route("/readings/summary", methods=["GET"])
def summary():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM readings")
    total_count = cursor.fetchone()[0]

    if total_count == 0:
        conn.close()
        return jsonify({"message": "No readings yet"}), 404

    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM readings")
    first_date, last_date = cursor.fetchone()

    cursor.execute("SELECT MIN(moisture), MAX(moisture) FROM readings")
    min_moisture, max_moisture = cursor.fetchone()

    cursor.execute("SELECT MIN(temperature), MAX(temperature) FROM readings")
    min_temperature, max_temperature = cursor.fetchone()

    cursor.execute("SELECT AVG(moisture), AVG(temperature) FROM readings")
    avg_moisture, avg_temp = cursor.fetchone()

    conn.close()

    
    start = datetime.strptime(first_date, "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(last_date, "%Y-%m-%d %H:%M:%S")
    days_monitored = (end - start).days

    return jsonify({
        "total_readings": total_count,
        "monitoring_since": first_date,
        "last_reading": last_date,
        "days_monitored": days_monitored,
        "moisture": {
            "min": min_moisture,
            "max": max_moisture,
            "average": round(avg_moisture, 1) if avg_moisture else 0
        },
        "temperature": {
            "min": min_temperature,
            "max": max_temperature,
            "average": round(avg_temp, 1) if avg_temp else 0
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)