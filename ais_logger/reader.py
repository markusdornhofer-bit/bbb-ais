import signal
import sys
import time
from datetime import datetime, timezone

import serial

from ais_logger import config
from ais_logger.ais_decode import FragmentBuffer, to_record
from ais_logger.db_ais import ensure_schema as ensure_ais_schema, insert_message
from ais_logger.db_own_position import ensure_schema as ensure_pos_schema, insert_own_position
from ais_logger.gps_clock import GpsClock
from ais_logger.gps_position import parse_gps_datetime, parse_own_position
from ais_logger.nmea_tagblock import wrap_tagblock
from ais_logger.serial_finder import find_ais_port

_running = True


def _handle_stop(signum, frame):
    global _running
    _running = False


class RawLogWriter:
    """Writes tagged NMEA lines to hour-bucketed .nm4 files, kept as an
    aisdb-compatible raw archive for later reprocessing/analysis. A file is
    only "closed" (safe for ais_logger.ingest to read) once its bucket has
    passed, so the writer never touches a file ingest might read
    concurrently."""

    def __init__(self):
        self._fh = None
        self._bucket = None

    def _bucket_for(self, dt: datetime) -> str:
        minute_bucket = (dt.minute // config.ROTATE_MINUTES) * config.ROTATE_MINUTES
        return dt.strftime("%Y%m%d_%H") + f"{minute_bucket:02d}"

    def write(self, tagged_line: str):
        now = datetime.now(timezone.utc)
        bucket = self._bucket_for(now)
        if bucket != self._bucket:
            if self._fh:
                self._fh.close()
            config.RAW_DIR.mkdir(parents=True, exist_ok=True)
            path = config.RAW_DIR / f"ais_{bucket}.nm4"
            self._fh = open(path, "a", encoding="ascii", errors="replace")
            self._bucket = bucket
            self._purge_old()
        self._fh.write(tagged_line + "\n")
        self._fh.flush()

    @staticmethod
    def _purge_old():
        """Drop raw archives past the retention window. Runs on rotation, so
        an unattended logger cannot slowly fill the eMMC."""
        if not config.RAW_RETENTION_DAYS:
            return
        cutoff = time.time() - config.RAW_RETENTION_DAYS * 86400
        for folder in (config.RAW_DIR, config.PROCESSED_DIR):
            if not folder.is_dir():
                continue
            for old in folder.glob("ais_*.nm4"):
                try:
                    if old.stat().st_mtime < cutoff:
                        old.unlink()
                        print(f"[reader] purged old archive {old.name}", file=sys.stderr)
                except OSError:
                    pass

    def close(self):
        if self._fh:
            self._fh.close()


def run():
    ensure_ais_schema()
    ensure_pos_schema()
    writer = RawLogWriter()
    ais_buffer = FragmentBuffer()
    clock = GpsClock(enabled=config.SET_CLOCK,
                     tolerance=config.CLOCK_TOLERANCE_SECONDS)

    counts = {"lines": 0, "ais": 0, "gps": 0, "other": 0}
    next_heartbeat = time.time() + config.HEARTBEAT_SECONDS
    next_gps_log = 0.0
    next_position_store = 0.0
    last_fix = None

    while _running:
        try:
            device, baud = find_ais_port()
            print(f"[reader] opening {device} @ {baud} ...", file=sys.stderr)
            with serial.Serial(device, baud, timeout=1) as ser:
                print("[reader] port open, waiting for data", file=sys.stderr)
                while _running:
                    if config.HEARTBEAT_SECONDS and time.time() >= next_heartbeat:
                        print(f"[reader] alive: {counts['lines']} lines "
                              f"({counts['ais']} AIS, {counts['gps']} GPS, "
                              f"{counts['other']} other, "
                              f"{ais_buffer.rejected} AIS rejected, "
                              f"{ais_buffer.filtered} filtered)", file=sys.stderr)
                        next_heartbeat = time.time() + config.HEARTBEAT_SECONDS

                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("ascii", errors="replace").strip()
                    if not line:
                        continue

                    counts["lines"] += 1
                    if config.DEBUG:
                        print(f"[raw] {line}", file=sys.stderr)

                    now = int(time.time())
                    writer.write(wrap_tagblock(line, config.SOURCE_LABEL, now))

                    if line.startswith("!"):
                        counts["ais"] += 1
                        result = ais_buffer.feed(line, now)
                        if result:
                            decoded, ts = result
                            insert_message(to_record(decoded, ts, config.SOURCE_LABEL, line))
                    elif line.startswith("$"):
                        counts["gps"] += 1
                        gps_dt = parse_gps_datetime(line)

                        # Correct the clock before reading the position out
                        # of the sentence: parse_own_position stamps the row
                        # from the system clock, so a stale one would be
                        # baked into the database row we are about to write.
                        shift = clock.update(gps_dt)
                        if shift is not None:
                            # Every deadline below was computed against the
                            # old clock and now points into the far past or
                            # future; restart them from the corrected one.
                            now = int(time.time())
                            next_heartbeat = time.time() + config.HEARTBEAT_SECONDS
                            next_gps_log = 0.0
                            next_position_store = 0.0

                        pos = parse_own_position(line)
                        if gps_dt:
                            has_fix = pos is not None
                            # Always report a change of fix status immediately,
                            # otherwise at most every GPS_LOG_SECONDS.
                            if has_fix != last_fix or now >= next_gps_log:
                                print(f"[gps] {gps_dt.isoformat()} "
                                      f"({'fix' if has_fix else 'no fix'})", file=sys.stderr)
                                next_gps_log = now + config.GPS_LOG_SECONDS
                            last_fix = has_fix
                        if pos and now >= next_position_store:
                            insert_own_position(pos)
                            next_position_store = now + config.POSITION_INTERVAL_SECONDS
                    else:
                        counts["other"] += 1
        except (OSError, serial.SerialException, RuntimeError) as exc:
            print(f"[reader] device error: {exc}; retrying in "
                  f"{config.RECONNECT_BACKOFF_SECONDS}s", file=sys.stderr)
            time.sleep(config.RECONNECT_BACKOFF_SECONDS)

    writer.close()


def main():
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    run()


if __name__ == "__main__":
    main()
