"""Minimal serial read test: opens the port exactly once and prints raw
bytes as they arrive. No probing, no database, no file logging — used to
isolate whether the device streams on a plain single open.

    python -m ais_logger.diag [device] [baud]
"""
import sys
import time

import serial

from ais_logger import config


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else (config.DEVICE or "/dev/ttyACM0")
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else (config.BAUD or 4800)

    print(f"opening {device} @ {baud} (single open, no probe) ...")
    ser = serial.Serial(device, baud, timeout=1)
    print(f"open ok. dsr={ser.dsr} cts={ser.cts} dtr={ser.dtr} rts={ser.rts}")
    print("reading for 15s ...")

    deadline = time.time() + 15
    total = 0
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            total += len(chunk)
            sys.stdout.write(chunk.decode("ascii", errors="replace"))
            sys.stdout.flush()
        else:
            print(f"[.] no data yet (in_waiting={ser.in_waiting})")

    print(f"\ntotal bytes read: {total}")
    ser.close()


if __name__ == "__main__":
    main()
