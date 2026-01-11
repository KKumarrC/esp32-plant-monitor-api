from flask import Flask, request, jsonify
from datetime import datetime
import os
import sqlite3
import psycopg2

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
IS_PG = DATABASE_URL is not None
DB_PATH = os.environ.get("DB_PATH", "/tmp/plant_readings.db")


def get_conn():
    """
    Returns a DB connection that is guaranteed to have a `readings` table.
    - On Heroku (DATABASE_URL set): Postgres
    - Otherwise: SQLite (file at DB_PATH)
    """
    if IS_PG:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id SERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                moisture INTEGER NOT NULL,
                temperature DOUBLE PRECISION NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
        return conn

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
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
            "GET /readings/history?hours=168&limit=500",
            "GET /readings/summary",
            "GET /status",
            "GET /health"
        ]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200


@app.route("/readings", methods=["POST"])
def save_readings():
    data = request.get_json()

    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    device_id = data.get("device_id", "esp32-1")

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
    cur = conn.cursor()

    if IS_PG:
        cur.execute("""
            INSERT INTO readings (device_id, moisture, temperature)
            VALUES (%s, %s, %s)
        """, (device_id, moisture, temperature))
    else:
        cur.execute("""
            INSERT INTO readings (device_id, moisture, temperature)
            VALUES (?, ?, ?)
        """, (device_id, moisture, temperature))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Reading saved successfully!"}), 201


@app.route("/readings/latest", methods=["GET"])
def latest_readings():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, device_id, moisture, temperature, timestamp
        FROM readings
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"message": "No readings yet"}), 404

    return jsonify({
        "id": row[0],
        "device_id": row[1],
        "moisture": row[2],
        "temperature": row[3],
        "timestamp": str(row[4]),
    })


@app.route("/readings/history", methods=["GET"])
def reading_history():
    conn = get_conn()
    cur = conn.cursor()

    hours = request.args.get("hours", 168, type=int)
    if hours <= 0:
        conn.close()
        return jsonify({"status": "error", "message": "hours must be > 0"}), 400

    limit = request.args.get("limit", 500, type=int)
    if limit <= 0 or limit > 5000:
        conn.close()
        return jsonify({"status": "error", "message": "limit must be between 1 and 5000"}), 400

    if IS_PG:
        cur.execute("""
            SELECT id, device_id, moisture, temperature, timestamp
            FROM readings
            WHERE timestamp > NOW() - (%s * INTERVAL '1 hour')
            ORDER BY timestamp DESC
            LIMIT %s
        """, (hours, limit))
        rows = cur.fetchall()
    else:
        time_string = f"-{hours} hours"
        cur.execute("""
            SELECT id, device_id, moisture, temperature, timestamp
            FROM readings
            WHERE timestamp > datetime('now', ?)
            ORDER BY timestamp DESC
            LIMIT ?
        """, (time_string, limit))
        rows = cur.fetchall()

    conn.close()

    rows = list(rows)
    rows.reverse()  # oldest -> newest

    readings = [{
        "id": r[0],
        "device_id": r[1],
        "moisture": r[2],
        "temperature": r[3],
        "timestamp": str(r[4]),
    } for r in rows]

    return jsonify({
        "hours": hours,
        "limit": limit,
        "count": len(readings),
        "readings": readings
    })


@app.route("/status", methods=["GET"])
def get_status():
    conn = get_conn()
    cur = conn.cursor()

    if IS_PG:
        cur.execute("""
            SELECT id, device_id, moisture, temperature, timestamp,
                   CAST(EXTRACT(EPOCH FROM (NOW() - timestamp)) AS INTEGER) AS seconds_ago
            FROM readings
            ORDER BY timestamp DESC
            LIMIT 1
        """)
    else:
        cur.execute("""
            SELECT id, device_id, moisture, temperature, timestamp,
                   CAST((strftime('%s','now') - strftime('%s', timestamp)) AS INTEGER) AS seconds_ago
            FROM readings
            ORDER BY timestamp DESC
            LIMIT 1
        """)

    latest = cur.fetchone()

    if not latest:
        conn.close()
        return jsonify({"message": "No readings yet"}), 404

    if IS_PG:
        cur.execute("""
            SELECT moisture FROM readings
            WHERE timestamp <= NOW() - INTERVAL '24 hours'
            ORDER BY timestamp DESC
            LIMIT 1
        """)
    else:
        cur.execute("""
            SELECT moisture FROM readings
            WHERE timestamp <= datetime('now','-24 hours')
            ORDER BY timestamp DESC
            LIMIT 1
        """)

    yesterday = cur.fetchone()
    conn.close()

    seconds_ago = latest[5]
    stale = seconds_ago > 600  # 10 minutes

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
            "timestamp": str(latest[4])
        },
        "changes": {
            "moisture_24h": moisture_change
        }
    })


@app.route("/delete-latest", methods=["POST"])
def delete_latest_reading():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, device_id, moisture, temperature, timestamp
        FROM readings
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    latest = cur.fetchone()

    if not latest:
        conn.close()
        return jsonify({"status": "error", "message": "No readings to delete"}), 404

    deleted_data = {
        "id": latest[0],
        "device_id": latest[1],
        "moisture": latest[2],
        "temperature": latest[3],
        "timestamp": str(latest[4]),
    }

    if IS_PG:
        cur.execute("DELETE FROM readings WHERE id = %s", (latest[0],))
    else:
        cur.execute("DELETE FROM readings WHERE id = ?", (latest[0],))

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
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM readings")
    count = cur.fetchone()[0]

    if count == 0:
        conn.close()
        return jsonify({
            "status": "info",
            "message": "No readings to delete",
            "deleted_count": 0
        }), 200

    if IS_PG:
        cur.execute("TRUNCATE readings RESTART IDENTITY;")
    else:
        cur.execute("DELETE FROM readings")
        cur.execute("DELETE FROM sqlite_sequence WHERE name='readings'")

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
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM readings")
    total_count = cur.fetchone()[0]

    if total_count == 0:
        conn.close()
        return jsonify({"message": "No readings yet"}), 404

    cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM readings")
    first_date, last_date = cur.fetchone()

    cur.execute("SELECT MIN(moisture), MAX(moisture) FROM readings")
    min_moisture, max_moisture = cur.fetchone()

    cur.execute("SELECT MIN(temperature), MAX(temperature) FROM readings")
    min_temperature, max_temperature = cur.fetchone()

    cur.execute("SELECT AVG(moisture), AVG(temperature) FROM readings")
    avg_moisture, avg_temp = cur.fetchone()

    conn.close()

    # These may be datetime objects (Postgres) or strings (SQLite). Convert safely.
    start = first_date if isinstance(first_date, datetime) else datetime.fromisoformat(str(first_date))
    end = last_date if isinstance(last_date, datetime) else datetime.fromisoformat(str(last_date))
    days_monitored = (end - start).days

    return jsonify({
        "total_readings": total_count,
        "monitoring_since": str(first_date),
        "last_reading": str(last_date),
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