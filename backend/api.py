from flask import Flask, request, jsonify
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "/tmp/plant_readings.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Create table if it doesn't exist (new installs)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            moisture INTEGER NOT NULL,
            temperature REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration for older DBs: add device_id if missing
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(readings)").fetchall()]
    if "device_id" not in cols:
        conn.execute("ALTER TABLE readings ADD COLUMN device_id TEXT NOT NULL DEFAULT 'esp32-1'")

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

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200

@app.route("/readings", methods=["POST"])
def save_readings():
    data = request.get_json()
    device_id = data.get("device_id", "esp32-1")

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
    cursor.execute('''
    INSERT INTO readings (device_id, moisture, temperature)
    VALUES (?, ?, ?)
    ''', (device_id, moisture, temperature))
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
        "device_id": reading[1],
        "moisture": reading[2],
        "temperature": reading[3],
        "timestamp": reading[4]
        })


@app.route('/readings/history', methods=['GET'])
def reading_history():
    conn = get_conn()
    cursor = conn.cursor()

    # How far back to look (default 168 hours = 7 days)
    hours = request.args.get('hours', 168, type=int)
    if hours <= 0:
        conn.close()
        return jsonify({"status": "error", "message": "hours must be > 0"}), 400

    # Safety cap so the endpoint doesn't grow forever
    limit = request.args.get('limit', 500, type=int)
    if limit <= 0 or limit > 5000:
        conn.close()
        return jsonify({"status": "error", "message": "limit must be between 1 and 5000"}), 400

    time_string = f'-{hours} hours'

    # Grab the most recent N rows efficiently, then reverse so output is oldest -> newest
    cursor.execute('''
        SELECT * FROM readings
        WHERE timestamp > datetime('now', ?)
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (time_string, limit))
    rows = cursor.fetchall()
    conn.close()

    rows.reverse()  # oldest -> newest

    readings = []
    for r in rows:
        readings.append({
            "id": r[0],
            "moisture": r[1],
            "temperature": r[2],
            "timestamp": r[3]
        })

    return jsonify({
        "hours": hours,
        "limit": limit,
        "count": len(readings),
        "readings": readings
    })


@app.route("/status", methods=["GET"])
def get_status():
    conn = get_conn()
    cursor = conn.cursor()

    # Get latest reading + how many seconds ago it was
    cursor.execute("""
        SELECT id, device_id, moisture, temperature, timestamp,
               CAST((strftime('%s','now') - strftime('%s', timestamp)) AS INTEGER) AS seconds_ago
        FROM readings
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    latest = cursor.fetchone()

    if not latest:
        conn.close()
        return jsonify({"message": "No readings yet"}), 404

    # Get moisture from >=24 hours ago (for change calculation)
    cursor.execute("""
        SELECT moisture FROM readings
        WHERE timestamp <= datetime('now','-24 hours')
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    yesterday = cursor.fetchone()

    conn.close()

    # Compute staleness (always)
    seconds_ago = latest[5]
    stale = seconds_ago > 600  # 10 minutes

    # Compute moisture change (optional)
    moisture_change = None
    if yesterday:
        moisture_change = latest[2] - yesterday[0]

    return jsonify({
        "device": {
            "device_id": latest[1],
            "last_seen_seconds_ago": seconds_ago,
            "stale": stale
        },
        "current": {
            "moisture": latest[2],
            "temperature": latest[3],
            "timestamp": latest[4]
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