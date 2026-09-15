"""
test_arduino.py - standalone Serial debug tool for the LAB ACCESS Arduino.

Run this BY ITSELF (never at the same time as app.py - only one program can
own the serial port at once) to check, in isolation, whether the Arduino is
actually sending anything at all over Serial.

Usage:
    python3 test_arduino.py

It will:
  1. Auto-detect the Arduino's USB serial port.
  2. Connect at 9600 baud.
  3. Wait 2 seconds (Arduino resets when the port opens).
  4. Print every line it receives, forever, until you Ctrl+C.
"""

import sys
import time

import serial
from serial.tools import list_ports

BAUD_RATE = 9600


def find_arduino_port():
    candidates = [
        p for p in list_ports.comports()
        if "usbmodem" in p.device.lower()
        or "usbserial" in p.device.lower()
        or "arduino" in (p.description or "").lower()
    ]
    if not candidates:
        return None
    for port in candidates:
        if "arduino" in (port.description or "").lower():
            return port.device
    return candidates[0].device


def main():
    port_name = find_arduino_port()

    if not port_name:
        print("No Arduino found. Is it plugged in over USB?")
        print("(Also make sure Arduino IDE's Serial Monitor is closed.)")
        sys.exit(1)

    print(f"Arduino found: {port_name}")

    try:
        ser = serial.Serial(port_name, BAUD_RATE, timeout=1)
    except (serial.SerialException, OSError) as e:
        print(f"Could not open {port_name}: {e}")
        print("If this says the port is busy, close Arduino Serial Monitor and try again.")
        sys.exit(1)

    print("Connected.")
    time.sleep(2)
    ser.reset_input_buffer()

    print("Waiting for Arduino messages... (Ctrl+C to quit)")
    print()

    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if line:
                print(f"RAW: {line}")
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
