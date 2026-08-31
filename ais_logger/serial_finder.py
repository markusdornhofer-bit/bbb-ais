"""Auto-detect the Seanexx AIS USB stick's serial port and baud rate.

There is no known stable USB VID:PID for this device to match against, so
detection is heuristic: enumerate serial ports, prefer ones whose
description hints at an AIS/GPS/USB-serial chip, then actually open each
candidate at each candidate baud rate and check whether the incoming bytes
look like valid NMEA sentences.
"""
import time

import serial
import serial.tools.list_ports

from ais_logger import config
from ais_logger.nmea_tagblock import nmea_checksum_valid

DESCRIPTION_HINTS = (
    "seanexx", "ais", "gps", "u-blox", "ublox", "cp210",
    "ftdi", "silicon labs", "prolific", "ch340",
)


def _candidate_ports():
    ports = list(serial.tools.list_ports.comports())

    def score(p):
        text = f"{p.description} {p.manufacturer or ''}".lower()
        return 0 if any(h in text for h in DESCRIPTION_HINTS) else 1

    ports.sort(key=score)
    return [p.device for p in ports]


def probe_port(device: str, baud: int, read_seconds: float = 2.5) -> int:
    """Return count of valid NMEA lines seen; 0 means "not this port/baud"."""
    valid = 0
    try:
        with serial.Serial(device, baud, timeout=1) as ser:
            deadline = time.time() + read_seconds
            while time.time() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                if nmea_checksum_valid(line):
                    valid += 1
    except (OSError, serial.SerialException):
        return 0
    return valid


def find_ais_port():
    if config.DEVICE:
        if config.BAUD:
            # Both explicitly configured: trust them and skip probing. Probing
            # would open and close the port first, and on USB CDC-ACM devices
            # that open/close/reopen cycle can leave the device not streaming.
            return config.DEVICE, config.BAUD
        for baud in config.BAUD_CANDIDATES:
            if probe_port(config.DEVICE, baud) > 0:
                return config.DEVICE, baud
        raise RuntimeError(
            f"AIS_DEVICE={config.DEVICE} set but no valid NMEA data seen "
            f"at any of {config.BAUD_CANDIDATES}"
        )

    bauds = [config.BAUD] if config.BAUD else config.BAUD_CANDIDATES
    best = None
    for device in _candidate_ports():
        for baud in bauds:
            hits = probe_port(device, baud)
            if hits and (best is None or hits > best[2]):
                best = (device, baud, hits)
        if best and best[2] >= 5:
            break  # good enough, stop scanning

    if best is None:
        raise RuntimeError(
            "No AIS/GPS serial device found. Plug in the Seanexx stick, "
            "check `dmesg`/`ls /dev/ttyUSB* /dev/ttyACM*`, or set "
            "AIS_DEVICE/AIS_BAUD explicitly."
        )
    return best[0], best[1]


if __name__ == "__main__":
    device, baud = find_ais_port()
    print(f"found AIS/GPS device: {device} @ {baud} baud")
    with serial.Serial(device, baud, timeout=1) as ser:
        for _ in range(20):
            raw = ser.readline()
            if raw:
                print(raw.decode("ascii", errors="replace").strip())
