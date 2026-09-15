"""
LAB ACCESS - Privacy-First Campus Security
Flask backend for a hackathon prototype.

Architecture:
    Arduino (LCD Keypad Shield) --USB Serial--> Python backend --HTTP--> Browser dashboard

The Arduino sends simple comma-separated text lines over Serial at 9600 baud:
    CHECK_IN,<student_id>,<current_capacity>
    CHECK_OUT,<student_id>,<current_capacity>,<session_duration_seconds>
    STATUS,<current_capacity>   (heartbeat, sent every few seconds regardless
                                 of button presses, so the dashboard's number
                                 is always the board's real counter - not a
                                 stale default guessed before the first event)

(The Arduino also prints a decorative human-readable log for anyone watching
the Serial Monitor - we ignore any line that isn't one of the formats above,
but we PRINT every raw line to this terminal so you can see exactly what's
arriving over Serial.)

This file:
  1. Auto-detects the Arduino's USB serial port (no hardcoded device paths).
  2. Listens for Serial events in a background thread and updates shared state.
  3. Exposes a small JSON API the frontend polls once a second.
  4. Logs every event to an in-memory list AND appends it to logs.csv.
  5. Provides "demo mode" endpoints so the whole thing can be shown off
     even if the Arduino is unplugged or misbehaving.
  6. Prints verbose [ARDUINO ...] / [EVENT] debug lines to the terminal and
     exposes /api/debug/serial, so a broken hardware pipeline is obvious
     instead of silently doing nothing.
"""

import csv
import errno
import os
import random
import sys
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template

import serial
from serial.tools import list_ports

# Force line-buffered stdout so every [ARDUINO ...] / [EVENT] print shows up
# immediately in the terminal - without this, Python fully buffers stdout
# whenever it isn't attached to a real TTY (e.g. IntelliJ's run console,
# or output redirected to a log file), which can delay debug prints by
# minutes and make the pipeline look broken when it isn't.
sys.stdout.reconfigure(line_buffering=True)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BAUD_RATE = 9600
MAX_CAPACITY = 20
RECONNECT_DELAY_SECONDS = 2        # how often we retry finding/opening the Arduino
LOGS_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs.csv")
CSV_COLUMNS = ["timestamp", "student_id", "action", "capacity", "duration_seconds", "message"]

# Environmental sensors are simulated - there's no physical temperature/air
# quality hardware wired up yet, just a plausible random walk so the
# dashboard has something live to show. Safe-range thresholds mirrored in
# static/app.js for the gauge - keep both in sync if these change.
SENSOR_UPDATE_SECONDS = 1
TEMPERATURE_SAFE_MAX_C = 26.0    # above this: overheating equipment / fire risk
AIR_QUALITY_SAFE_MAX_PPM = 50.0  # above this: fumes (e.g. soldering), poor ventilation

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
    "temperatureC": 22.0,
    "temperatureSafe": True,
    "airQualityPpm": 15.0,
    "airQualitySafe": True,
}

# Extra fields for /api/debug/serial - kept separate from `state` so the
# public /api/status shape never changes.
debug_state = {
    "port": None,
    "lastRawMessage": None,
    "lastMessageTime": None,
    "listenerRunning": False,
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


def record_event(action, student_id, capacity, duration_seconds=None):
    """Build a log entry for a CHECK_IN / CHECK_OUT event, store it in memory,
    append it to logs.csv, and update the shared occupancy state.

    This is the single place that both the real Arduino serial parser and
    the /api/demo/* endpoints funnel through, so the two paths always
    behave identically - a real check-in and a simulated one produce the
    exact same shape of log entry.
    """
    now = datetime.now()  # computer time, per spec: Arduino owns duration, computer owns timestamp
    timestamp = now.strftime("%I:%M:%S %p").lstrip("0")  # e.g. "6:42:13 PM"

    capacity = max(0, min(MAX_CAPACITY, int(capacity)))

    if action == "CHECK_IN":
        message = (
            f"At {timestamp}, student {student_id} checked in for their lab. "
            f"Current lab occupancy is {capacity}/{MAX_CAPACITY}."
        )
        print(f"[EVENT] Student {student_id} CHECKED IN")
        print(f"[EVENT] Capacity = {capacity}/{MAX_CAPACITY}")
    else:  # CHECK_OUT
        duration_text = format_duration_long(duration_seconds or 0)
        message = (
            f"At {timestamp}, student {student_id} finished their lab section. "
            f"Their lab session lasted {duration_text}. "
            f"Current lab occupancy is {capacity}/{MAX_CAPACITY}."
        )
        print(f"[EVENT] Student {student_id} CHECKED OUT")
        print(f"[EVENT] Session duration = {duration_seconds} seconds")
        print(f"[EVENT] Capacity = {capacity}/{MAX_CAPACITY}")

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
        # Camera is on whenever the lab is occupied, off when it's empty -
        # not a timed blip. Tied directly to capacity so it stays correct
        # regardless of which event (or demo button) changed it.
        state["cameraActive"] = capacity > 0
        logs.append(entry)

    append_log_to_csv(entry)

    return entry


def sync_capacity_from_arduino(capacity):
    """Apply a STATUS heartbeat from the Arduino: brings the dashboard's
    capacity (and camera state) in line with the board's real counter
    without creating an activity log entry - this isn't a check-in/check-out
    event, just the Arduino telling us what it already knows.
    """
    capacity = max(0, min(MAX_CAPACITY, int(capacity)))
    with state_lock:
        changed = state["capacity"] != capacity
        state["capacity"] = capacity
        state["cameraActive"] = capacity > 0
    if changed:
        print(f"[ARDUINO] Capacity synced from board: {capacity}/{MAX_CAPACITY}")


# --------------------------------------------------------------------------
# Arduino auto-detection + Serial listener thread
# --------------------------------------------------------------------------

def find_arduino_port(verbose=False):
    """Look through available Serial ports and try to find the Arduino,
    without ever hardcoding a device path like /dev/cu.usbmodem21101.

    We prefer ports whose device name looks like a USB modem/serial device
    (how macOS names Arduino Uno connections) or whose description mentions
    "Arduino", and prefer an Arduino-described port if more than one
    candidate exists.

    When verbose=True, prints every detected serial port - useful at
    startup so you can see exactly what macOS is offering.
    """
    all_ports = list(list_ports.comports())

    if verbose:
        print("=== SERIAL DEVICES ===")
        if not all_ports:
            print("(none found)")
        for p in all_ports:
            print(p.device)
        print("======================")

    candidates = [
        p for p in all_ports
        if "usbmodem" in p.device.lower()
        or "usbserial" in p.device.lower()
        or "arduino" in (p.description or "").lower()
    ]

    if not candidates:
        if verbose:
            print("Arduino not detected.")
        return None

    chosen = None
    for port in candidates:
        if "arduino" in (port.description or "").lower():
            chosen = port.device
            break
    if chosen is None:
        chosen = candidates[0].device

    if verbose:
        print(f"Arduino detected: {chosen}")

    return chosen


def process_arduino_message(line):
    """Parse one line of text from the Arduino and record the event.

    Expected formats (anything else - including the Arduino's decorative
    human-readable log lines - is reported as ignored, not treated as an
    error):
        CHECK_IN,<student_id>,<current_capacity>
        CHECK_OUT,<student_id>,<current_capacity>,<session_duration_seconds>
        STATUS,<current_capacity>   (periodic heartbeat, not a log-worthy event)
    """
    parts = line.strip().split(",")
    action = parts[0].strip().upper() if parts else ""

    if action not in ("CHECK_IN", "CHECK_OUT", "STATUS"):
        return  # decorative/log noise from the Arduino - not an error, not printed as one

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

        elif action == "STATUS" and len(parts) >= 2:
            capacity = int(parts[1].strip())
            sync_capacity_from_arduino(capacity)

        else:
            print(f"[ARDUINO] Ignoring malformed message: {line!r}")

    except (ValueError, IndexError) as e:
        print(f"[ARDUINO] Ignoring malformed message: {line!r} ({e})")


def serial_worker():
    """Background thread: keeps trying to find + open the Arduino, reads
    lines from it forever, and reconnects automatically if it's unplugged.
    Runs for the lifetime of the app; never raises out of the loop.

    NOTE: if the Arduino Serial Monitor (in the Arduino IDE) is open, it
    holds the port exclusively - close it (the IDE itself can stay open)
    before starting this app.
    """
    with state_lock:
        debug_state["listenerRunning"] = True

    ser = None
    was_connected_before = False

    while True:
        if ser is None:
            port_name = find_arduino_port()

            if not port_name:
                with state_lock:
                    state["arduinoConnected"] = False
                    debug_state["port"] = None
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue

            try:
                ser = serial.Serial(port_name, BAUD_RATE, timeout=1)

                # Opening the port resets an Arduino Uno. Give it a moment to
                # boot, then throw away whatever garbage it wrote during reset
                # so we don't try to parse boot noise as a real event.
                time.sleep(2)
                ser.reset_input_buffer()

                with state_lock:
                    state["arduinoConnected"] = True
                    debug_state["port"] = port_name

                if was_connected_before:
                    print(f"[ARDUINO] Reconnected to {port_name}")
                else:
                    print(f"[ARDUINO] Connected to {port_name} @ {BAUD_RATE} baud")
                was_connected_before = True

            except (serial.SerialException, OSError) as e:
                if getattr(e, "errno", None) == errno.EBUSY or "resource busy" in str(e).lower():
                    print("[ARDUINO] Port is busy.")
                    print("Close Arduino Serial Monitor (or Serial Plotter) and try again.")
                else:
                    print(f"[ARDUINO] Could not open {port_name}: {e}")
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
            if not line:
                continue

            print(f"[ARDUINO RAW] {line}")
            with state_lock:
                debug_state["lastRawMessage"] = line
                debug_state["lastMessageTime"] = datetime.now().isoformat(timespec="seconds")

            process_arduino_message(line)

        except (serial.SerialException, OSError) as e:
            print(f"[ARDUINO] Disconnected ({e})")
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            with state_lock:
                state["arduinoConnected"] = False
                debug_state["port"] = None
            time.sleep(RECONNECT_DELAY_SECONDS)


# --------------------------------------------------------------------------
# Simulated environmental sensors (temperature / air quality)
#
# No physical sensor is wired up for these - this is a random walk that
# occasionally drifts into the "not safe" range so the dashboard has
# something realistic to show. Runs independently of the Arduino connection.
# --------------------------------------------------------------------------

def sensor_worker():
    temperature = state["temperatureC"]
    air_quality = state["airQualityPpm"]

    while True:
        # Small step most of the time; rare bigger jump to simulate an
        # overheating device or a soldering session kicking up fumes.
        temperature += random.uniform(-0.3, 0.3)
        if random.random() < 0.03:
            temperature += random.uniform(2.0, 6.0)
        temperature = max(15.0, min(45.0, temperature))

        air_quality += random.uniform(-2.0, 2.0)
        if random.random() < 0.03:
            air_quality += random.uniform(20.0, 60.0)
        air_quality = max(0.0, min(150.0, air_quality))

        # Gently pull both back toward their normal resting values so a
        # spike is temporary rather than a permanent drift.
        temperature += (22.0 - temperature) * 0.05
        air_quality += (15.0 - air_quality) * 0.08

        with state_lock:
            state["temperatureC"] = round(temperature, 1)
            state["temperatureSafe"] = temperature <= TEMPERATURE_SAFE_MAX_C
            state["airQualityPpm"] = round(air_quality, 1)
            state["airQualitySafe"] = air_quality <= AIR_QUALITY_SAFE_MAX_PPM

        time.sleep(SENSOR_UPDATE_SECONDS)


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
            "temperatureC": state["temperatureC"],
            "temperatureSafe": state["temperatureSafe"],
            "airQualityPpm": state["airQualityPpm"],
            "airQualitySafe": state["airQualitySafe"],
        })


@app.route("/api/logs")
def api_logs():
    with state_lock:
        newest_first = list(reversed(logs))
    return jsonify(newest_first)


@app.route("/api/debug/serial")
def api_debug_serial():
    """Diagnostic endpoint: is Flask actually receiving anything from the
    Arduino? If lastRawMessage stays null while you're pressing buttons on
    the LCD shield, the problem is upstream of Python (wiring, wrong sketch
    flashed, wrong port, Serial Monitor still holding the port, etc.)."""
    with state_lock:
        return jsonify({
            "connected": state["arduinoConnected"],
            "port": debug_state["port"],
            "baudRate": BAUD_RATE,
            "lastRawMessage": debug_state["lastRawMessage"],
            "lastMessageTime": debug_state["lastMessageTime"],
            "listenerRunning": debug_state["listenerRunning"],
        })


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

    print()
    print("IMPORTANT: Close Arduino IDE Serial Monitor/Serial Plotter before")
    print("running this server - only one program can own the serial port.")
    print("(The Arduino IDE window itself can stay open.)")
    print()

    find_arduino_port(verbose=True)  # just for the startup printout

    # Guard against Flask's reloader starting this twice (each copy would
    # try to open the same serial port). We run with use_reloader=False
    # below, so WERKZEUG_RUN_MAIN never actually gets set - this check is
    # a defensive backstop in case debug/reloader settings change later.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        listener = threading.Thread(target=serial_worker, daemon=True)
        listener.start()
        print("[ARDUINO] Listener thread started.")

        sensors = threading.Thread(target=sensor_worker, daemon=True)
        sensors.start()

    # PORT can be overridden with an env var (useful on macOS, where
    # AirPlay Receiver often squats on port 5000 by default).
    port = int(os.environ.get("PORT", 5000))

    # debug=False so a bug in a request handler never dumps a full traceback
    # onto the page in front of judges; use_reloader=False so Flask never
    # spins up a second process that would fight over the serial port.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
