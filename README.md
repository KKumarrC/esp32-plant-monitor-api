# IoT Plant Monitor (ESP32 + Flask + Postgres + Heroku)

This IoT-style plant monitoring system collects soil moisture and temperature readings from an ESP32 sensor node and uploads them to a cloud hosted Flask REST API. The API stores readings in a database and provides endpoints for latest values, history, summary stats, and device health/status. I originally used SQLite locally, but moved to Postgres on Heroku so readings persist across restarts.


## Features
- ESP32 reads:
  - **Moisture** (raw capacitive sensor units)
  - **Temperature** (Celsius)
- Sends readings as **JSON** over WiFi to a cloud API
- Flask REST API with endpoints for:
  - ingesting readings
  - fetching latest reading
  - history queries
  - summary statistics
  - health + status (staleness detection)
- Deployed on **Heroku**
- Uses **PostgreSQL** in production (and can fall back to SQLite locally)

---

## Live Demo
- Base URL: `https://plant-monitor-api-dc28347b13d8.herokuapp.com/`

Try:
- `/health`
- `/status`
- `/readings/latest`

---

## Tech Stack
- **Hardware:** ESP32 + Adafruit Seesaw soil sensor
- **Backend:** Python, Flask (REST API)
- **Database:** PostgreSQL (Heroku), SQLite (local fallback)
- **Deployment:** Heroku
- **Transport/Data:** HTTP + JSON

---

## Key Decisions
- Started with SQLite locally for quick development
- Migrated to Postgres on Heroku for persistent storage
- Added `/health` and `/status` endpoints for monitoring

---

## API Endpoints

### `GET /`
Returns API info + available endpoints.

### `GET /health`
Quick health check.
**Response:** `{"ok": true}`

### `POST /readings`
Ingest a new reading.

**Request JSON**
```json
{
  "device_id": "esp32-1",
  "moisture": 510,
  "temperature": 22.7
}
