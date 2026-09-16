# UWATch

**Privacy-first lab access and occupancy tracking.**

UWATch is a hardware + software prototype for a university lab access system that tracks occupancy and simulates privacy-conscious camera behavior, built around a simple idea: the system should know *who's in the room and how many people are there*, without recording continuous video of everyone who walks by.

> **Built in a 50-minute hackathon.** This is a time-boxed prototype, not production software — the goal was an end-to-end working demo (real hardware → live dashboard), not hardened, feature-complete code. Expect rough edges: in-memory state, a dev-mode Flask server, and simulated (not real) environmental sensors.

## How it works

```
Arduino Uno + LCD Keypad Shield
        |  USB Serial @ 9600 baud
        v
Python backend (pyserial)
        |
Flask API (/api/status, /api/logs, /api/debug/serial)
        |  polled every ~1s
        v
Browser dashboard (HTML/CSS/JS, no build step)
```

A student approaches the lab, the Arduino's LCD keypad shield walks them through entering a student ID and choosing check-in or check-out, and the board reports the event over Serial as a simple comma-separated line (e.g. `CHECK_IN,1234,15`). The Python/Flask backend parses these events, keeps the current occupancy count, and serves a live-updating dashboard that shows real-time capacity, a simulated privacy-mode camera indicator, and an activity log — all without a database, authentication system, or cloud services.

## Privacy-first design

1. **Presence** — anonymous proximity detection (simulated by the shield's RIGHT button, standing in for a future ultrasonic sensor) wakes the system.
2. **Authentication** — the student voluntarily enters their ID at the lab entrance.
3. **Event-based verification** — the dashboard's "camera" only shows as active while the lab is actually occupied, not continuously.
4. **Derived data** — the system stores access *events* and occupancy *counts*, not video footage.

## Features

- Live occupancy dashboard (auto-detects the Arduino's USB port, no hardcoded device paths)
- Automatic reconnect if the Arduino is unplugged/replugged, no server restart needed
- Verbose `[ARDUINO ...]` / `[EVENT]` terminal logging plus a `/api/debug/serial` endpoint for diagnosing the hardware pipeline
- Demo mode (`SIMULATE CHECK IN` / `SIMULATE CHECK OUT` buttons) so the dashboard works even without the Arduino connected
- Simulated temperature and air-quality gauges with safe/unsafe thresholds and a legend
- All activity logged in-memory and appended to `logs.csv`

## Project structure

```
app.py                          Flask backend + Arduino Serial listener
requirements.txt                Flask, pyserial
templates/index.html            Dashboard page
static/app.js                   Polling + rendering logic
static/style.css                Dashboard styling
static/logo.png                 UWATch logo
arduino/lab_access/lab_access.ino   Arduino sketch (LCD keypad shield + Serial protocol)
test_arduino.py                 Standalone Serial debug script (run instead of app.py, never alongside it)
photo_upload.py                 Unrelated local utility for saving a photo to disk
logs.csv                        Generated at runtime - full activity history
```

## Running it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** (use `PORT=5050 python app.py` if 5000 is taken — common on macOS, where AirPlay Receiver claims it by default).

If using the physical Arduino: flash `arduino/lab_access/lab_access.ino` via the Arduino IDE first, and make sure its Serial Monitor/Plotter is closed before starting `app.py` — only one program can hold the serial port at a time.

## Limitations (by design, given the time box)

- No database — state lives in memory and resets when the server restarts (past events remain in `logs.csv`)
- No authentication — student IDs are a fixed demo list (`1234`, `4321`, `1122`, `3142`)
- Temperature/air-quality readings are simulated, not read from real sensors
- Flask's built-in dev server, not meant for production deployment
