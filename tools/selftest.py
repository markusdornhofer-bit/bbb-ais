"""Hardware-free self-test: feeds a canned NMEA stream through the real
reader loop and checks that AIS messages and own position land in the
database. Use this after moving the project to a new machine to confirm
the install works before plugging in the stick.

    python tools/selftest.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = tempfile.mkdtemp(prefix="ais_selftest_")
os.environ["AIS_DATA_DIR"] = TMP
os.environ["AIS_HEARTBEAT_SECONDS"] = "0"
# The canned stream carries real RMC dates, and the reader disciplines the
# system clock from those. A self-test must never move the clock of the
# machine it runs on — on the BeagleBone it would actually succeed.
os.environ["AIS_SET_CLOCK"] = "0"
os.environ.pop("AIS_DEBUG", None)

import serial  # noqa: E402

# Real sentences (checksums verified). Multi-fragment type 5 pair included
# so reassembly is exercised too.
STREAM = [
    b"$GNRMC,072826.00,V,,,,,,,250826,,,N*61\r\n",
    b"!AIVDM,1,1,,,15Di=4002i<chWiba2`rPpD:04;`,0*37\r\n",
    b"!AIVDM,2,1,2,,57`B?hl2CdtQ`lO;SK9L4Tl5@62222222222220l1@>666QVS>1jDhSl,0*20\r\n",
    b"!AIVDM,2,2,2,,SQH888888888880,2*15\r\n",
    b"$GNRMC,072827.00,A,4807.038,N,01131.000,E,022.4,084.4,250826,,,A*4D\r\n",
]


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.i = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def readline(self):
        if self.i >= len(STREAM):
            import ais_logger.reader as reader
            reader._running = False
            return b""
        line = STREAM[self.i]
        self.i += 1
        return line


def main():
    serial.Serial = FakeSerial

    import ais_logger.reader as reader
    from ais_logger import config
    reader.find_ais_port = lambda: ("/dev/fake", 4800)
    reader.run()

    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    ais_rows = conn.execute(
        "SELECT mmsi, msg_type, shipname FROM ais_messages ORDER BY id"
    ).fetchall()
    pos_rows = conn.execute(
        "SELECT lat, lon, sog_knots, cog_deg FROM own_position"
    ).fetchall()

    failures = []
    if len(ais_rows) != 2:
        failures.append(f"expected 2 AIS messages, got {len(ais_rows)}: {ais_rows}")
    elif ais_rows[1][2] is None:
        failures.append(f"multi-fragment type 5 not reassembled: {ais_rows[1]}")
    if len(pos_rows) != 1:
        failures.append(f"expected 1 own position, got {len(pos_rows)}: {pos_rows}")
    elif round(pos_rows[0][0], 4) != 48.1173:
        failures.append(f"unexpected own position: {pos_rows[0]}")

    raw_files = list((Path(TMP) / "raw").glob("*.nm4"))
    if not raw_files:
        failures.append("no raw .nm4 archive file was written")

    print()
    print("AIS messages :", ais_rows)
    print("own position :", pos_rows)
    print("raw archive  :", [p.name for p in raw_files])
    print()
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
