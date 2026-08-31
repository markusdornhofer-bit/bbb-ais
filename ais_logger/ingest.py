"""Reprocess archived raw .nm4 logs into ais_messages. Not required for
normal operation (ais_logger.reader decodes and stores live) — this is a
backfill/recovery tool, e.g. if the DB was reset or the reader was down
while raw logging still ran."""
import sys
import time
from datetime import datetime, timezone

from ais_logger import config
from ais_logger.ais_decode import FragmentBuffer, to_record
from ais_logger.db_ais import ensure_schema, insert_message
from ais_logger.nmea_tagblock import strip_tagblock


def _is_closed_bucket(path) -> bool:
    """A raw log is safe to ingest once its rotation bucket is in the past,
    i.e. the reader has moved on to a newer file."""
    stamp = path.stem[len("ais_"):]  # "YYYYMMDD_HHMM"
    try:
        bucket_start = datetime.strptime(stamp, "%Y%m%d_%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    bucket_end = bucket_start.timestamp() + config.ROTATE_MINUTES * 60
    return time.time() > bucket_end


def _ingest_file(path, buffer: FragmentBuffer) -> int:
    count = 0
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            payload, ts = strip_tagblock(line)
            if not payload.startswith("!"):
                continue
            result = buffer.feed(payload, ts)
            if result:
                decoded, msg_ts = result
                insert_message(to_record(decoded, msg_ts, config.SOURCE_LABEL, payload))
                count += 1
    return count


def run():
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    ensure_schema()

    files = sorted(
        p for p in config.RAW_DIR.glob("ais_*.nm4") if _is_closed_bucket(p)
    )
    if not files:
        print("[ingest] nothing to ingest", file=sys.stderr)
        return

    total = 0
    for path in files:
        buffer = FragmentBuffer()
        total += _ingest_file(path, buffer)
        path.rename(config.PROCESSED_DIR / path.name)

    print(f"[ingest] decoded {total} message(s) from {len(files)} file(s), "
          f"moved to {config.PROCESSED_DIR}", file=sys.stderr)


if __name__ == "__main__":
    run()
