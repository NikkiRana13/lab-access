"""
LAB ACCESS - Privacy-First Campus Security
Flask backend for a hackathon prototype.

Architecture:
    Arduino (LCD Keypad Shield) --USB Serial--> Python backend --HTTP--> Browser dashboard

The Arduino sends simple comma-separated text lines over Serial at 9600 baud:
    CHECK_IN,<student_id>,<current_capacity>
    CHECK_OUT,<student_id>,<current_capacity>,<session_duration_seconds>

(The Arduino also prints a decorative human-readable log for anyone watching
the Serial Monitor - we simply ignore any line that isn't one of the two
formats above.)

This file:
  1. Auto-detects the Arduino's USB serial port (no hardcoded device paths).
  2. Listens for Serial events in a background thread and updates shared state.
  3. Exposes a small JSON API the frontend polls once a second.
  4. Logs every event to an in-memory list AND appends it to logs.csv.
  5. Provides "demo mode" endpoints so the whole thing can be shown off
     even if the Arduino is unplugged or misbehaving.
"""

import csv
import os
import random
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template

import serial
from serial.tools import list_ports

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BAUD_RATE = 9600
MAX_CAPACITY = 20
CAMERA_ACTIVE_SECONDS = 4          # how long the "camera active" simulation lasts
RECONNECT_DELAY_SECONDS = 2        # how often we retry finding/opening the Arduino
LOGS_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs.csv")
CSV_COLUMNS = ["timestamp", "student_id", "action", "capacity", "duration_seconds", "message"]

app = Flask(__name__)

# --------------------------------------------------------------------------
# Shared state (read/written from both the Flask request threads and the
# background Serial-reading thread, so everything goes through `state_lock`)
# --------------------------------------------------------------------------

state_lock = threading.Lock()

state = {
    "arduinoConnected": False,
    "capacity": 0,
    "maxCapacity": MAX_CAPACITY,
    "cameraActive": False,
}

logs = []  # appended oldest -> newest; /api/logs reverses this for newest-first


# --------------------------------------------------------------------------
# CSV logging
# --------------------------------------------------------------------------

def ensure_csv_exists():
    """Create logs.csv with a header row if it doesn't exist yet."""
    if not os.path.exists(LOGS_CSV_PATH):
        with open(LOGS_CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)


def append_log_to_csv(entry):
    """Append a single log entry (dict) to logs.csv. Never lets a logging
    failure crash a request - worst case we just print a warning."""
    try:
        with open(LOGS_CSV_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                entry["timestamp"],
                entry["student_id"],
                entry["action"],
                entry["capacity"],
                entry["duration_seconds"] if entry["duration_seconds"] is not None else "",
                entry["message"],
            ])
    except OSError as e:
        print(f"[logs.csv] failed to write log: {e}")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def format_duration_long(total_seconds):
    """2234 -> '37 minutes and 14 seconds' (used in the human-readable message)."""
    minutes, seconds = divmod(int(total_seconds), 60)
    minute_word = "minute" if minutes == 1 else "minutes"
    second_word = "second" if seconds == 1 else "seconds"
    return f"{minutes} {minute_word} and {seconds} {second_word}"


def activate_camera_briefly():
    """Simulate the privacy-mode camera turning on for a check-in, then
    automatically turning back off a few seconds later. This is a pure UI
    simulation for the prototype - no real camera is ever touched."""
    with state_lock:
        state["cameraActive"] = True

    def deactivate():
        with state_lock:
            state["cameraActive"] = False

    timer = threading.Timer(CAMERA_ACTIVE_SECONDS, deactivate)
    timer.daemon = True
    timer.start()


def record_event(action, student_id, capacity, duration_seconds=None):
    """Build a log entry for a CHECK_IN / CHECK_OUT event, store it in memory,
    append it to logs.csv, and update the shared occupancy state.

    This is the single place that both the real Arduino serial parser and
    the /api/demo/* endpoints funnel through, so the two paths always
    behave identically.
    """
    now = datetime.now()  # computer time, per spec: Arduino owns duration, computer owns timestamp
    timestamp = now.strftime("%I:%M:%S %p").lstrip("0")  # e.g. "6:42:13 PM"

    capacity = max(0, min(MAX_CAPACITY, int(capacity)))

    if action == "CHECK_IN":
        message = (
            f"At {timestamp}, student {student_id} checked in for their lab. "
            f"Current lab occupancy is {capacity}/{MAX_CAPACITY}."
        )
    else:  # CHECK_OUT
        duration_text = format_duration_long(duration_seconds or 0)
        message = (
            f"At {timestamp}, student {student_id} finished their lab section. "
            f"Their lab session lasted {duration_text}. "
            f"Current lab occupancy is {capacity}/{MAX_CAPACITY}."
        )

    entry = {
        "timestamp": timestamp,
        "student_id": student_id,
        "action": action,
        "capacity": capacity,
        "duration_seconds": duration_seconds,
        "message": message,
    }

    with state_lock:
        state["capacity"] = capacity
        logs.append(entry)

    append_log_to_csv(entry)

    if action == "CHECK_IN":
        activate_camera_briefly()

    return entry


# --------------------------------------------------------------------------
# Arduino auto-detection + Serial listener thread
# --------------------------------------------------------------------------

def find_arduino_port():
    """Look through available Serial ports and try to find the Arduino,
    without ever hardcoding a device path like /dev/cu.usbmodem21101.

    We prefer ports whose device name looks like a USB modem/serial device
    (how macOS names Arduino Uno connections), and prefer one whose
    description mentions "Arduino" if more than one candidate exists.
    """
    candidates = [
        p for p in list_ports.comports()
        if "usbmodem" in p.device.lower() or "usbserial" in p.device.lower()
    ]

    if not candidates:
        return None

    for port in candidates:
        if "arduino" in (port.description or "").lower():
            return port.device

    return candidates[0].device


def parse_serial_line(line):
    """Parse one line of text from the Arduino and record the event.

    Expected formats (anything else - including the Arduino's decorative
    human-readable log lines - is silently ignored):
        CHECK_IN,<student_id>,<current_capacity>
        CHECK_OUT,<student_id>,<current_capacity>,<session_duration_seconds>
    """
    parts = line.strip().split(",")
    if not parts:
        return

    action = parts[0].strip().upper()
    if action not in ("CHECK_IN", "CHECK_OUT"):
        return  # decorative/log noise from the Arduino - not an error

    try:
        if action == "CHECK_IN" and len(parts) >= 3:
            student_id = parts[1].strip()
            capacity = int(parts[2].strip())
            record_event("CHECK_IN", student_id, capacity)

        elif action == "CHECK_OUT" and len(parts) >= 4:
            student_id = parts[1].strip()
            capacity = int(parts[2].strip())
            duration_seconds = int(parts[3].strip())
            record_event("CHECK_OUT", student_id, capacity, duration_seconds)

        else:
            print(f"[serial] malformed {action} line (wrong field count): {line!r}")

    except (ValueError, IndexError) as e:
        print(f"[serial] ignoring malformed line {line!r}: {e}")


def serial_worker():
    """Background thread: keeps trying to find + open the Arduino, reads
    lines from it forever, and reconnects automatically if it's unplugged.
    Runs for the lifetime of the app; never raises out of the loop.

    NOTE: if the Arduino Serial Monitor (in the Arduino IDE) is open, it
    holds the port exclusively - close it before starting this app.
    """
    ser = None

    while True:
        if ser is None:
            port_name = find_arduino_port()

            if not port_name:
                with state_lock:
                    state["arduinoConnected"] = False
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue

            try:
                ser = serial.Serial(port_name, BAUD_RATE, timeout=1)
                time.sleep(2)  # Arduino resets when the serial port opens; let it boot
                with state_lock:
                    state["arduinoConnected"] = True
                print(f"[serial] connected to Arduino on {port_name}")
            except (serial.SerialException, OSError) as e:
                print(f"[serial] could not open {port_name}: {e}")
                ser = None
                with state_lock:
                    state["arduinoConnected"] = False
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue

        try:
            raw = ser.readline()  # blocks up to `timeout` seconds, then returns b""
            if not raw:
                continue  # just a read timeout, nothing arrived - loop and try again
            line = raw.decode("utf-8", errors="ignore").strip()
            if line:
                parse_serial_line(line)

        except (serial.SerialException, OSError) as e:
            print(f"[serial] lost connection to Arduino: {e}")
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            with state_lock:
                state["arduinoConnected"] = False
            time.sleep(RECONNECT_DELAY_SECONDS)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify({
            "arduinoConnected": state["arduinoConnected"],
            "capacity": state["capacity"],
            "maxCapacity": state["maxCapacity"],
            "cameraActive": state["cameraActive"],
        })


@app.route("/api/logs")
def api_logs():
    with state_lock:
        newest_first = list(reversed(logs))
    return jsonify(newest_first)


@app.route("/api/demo/checkin", methods=["POST"])
def demo_checkin():
    """Fake a CHECK_IN event so the dashboard can be demoed without hardware."""
    student_id = "1234"
    with state_lock:
        new_capacity = min(MAX_CAPACITY, state["capacity"] + 1)
    entry = record_event("CHECK_IN", student_id, new_capacity)
    return jsonify(entry)


@app.route("/api/demo/checkout", methods=["POST"])
def demo_checkout():
    """Fake a CHECK_OUT event so the dashboard can be demoed without hardware."""
    student_id = "1234"
    with state_lock:
        new_capacity = max(0, state["capacity"] - 1)
    duration_seconds = random.randint(30, 3600)
    entry = record_event("CHECK_OUT", student_id, new_capacity, duration_seconds)
    return jsonify(entry)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    ensure_csv_exists()

    listener = threading.Thread(target=serial_worker, daemon=True)
    listener.start()

    # PORT can be overridden with an env var (useful on macOS, where
    # AirPlay Receiver often squats on port 5000 by default).
    port = int(os.environ.get("PORT", 5000))

    # debug=False so a bug in a request handler never dumps a full
    # traceback onto the page in front of judges.
    app.run(host="0.0.0.0", port=port, debug=False)
