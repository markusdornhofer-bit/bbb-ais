import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AIS_DATA_DIR", BASE_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = Path(os.environ.get("AIS_DB_PATH", DATA_DIR / "aisdb.sqlite"))

SOURCE_LABEL = os.environ.get("AIS_SOURCE_LABEL", "SEANEXX")

# None = auto-detect via serial_finder; set AIS_DEVICE to force a fixed port.
DEVICE = os.environ.get("AIS_DEVICE") or None
# Seanexx stick confirmed to run at 4800 baud; override via AIS_BAUD if needed.
BAUD = int(os.environ["AIS_BAUD"]) if os.environ.get("AIS_BAUD") else 4800
BAUD_CANDIDATES = [4800, 38400, 9600, 115200]

# New raw log file every N minutes; ingest only touches files older than this
# so it never races the logger's currently-open file.
ROTATE_MINUTES = int(os.environ.get("AIS_ROTATE_MINUTES", "60"))

RECONNECT_BACKOFF_SECONDS = 5

# AIS_DEBUG=1 echoes every raw line read from the port.
DEBUG = os.environ.get("AIS_DEBUG", "") not in ("", "0", "false", "False")
# Seconds between "still alive" counter lines; 0 disables them.
HEARTBEAT_SECONDS = int(os.environ.get("AIS_HEARTBEAT_SECONDS", "10"))

# The receiver sends one RMC sentence per second. Logging and storing every
# single one would write ~86k journal lines and ~86k database rows per day —
# pointless wear on the BeagleBone's eMMC during unattended operation. Both
# are therefore rate-limited; a change of fix status is always logged at once.
GPS_LOG_SECONDS = int(os.environ.get("AIS_GPS_LOG_SECONDS", "60"))
POSITION_INTERVAL_SECONDS = int(os.environ.get("AIS_POSITION_INTERVAL_SECONDS", "30"))

# Delete archived raw logs older than this so an unattended logger cannot
# fill the disk; 0 keeps them forever.
RAW_RETENTION_DAYS = int(os.environ.get("AIS_RAW_RETENTION_DAYS", "14"))

# The BeagleBone has no RTC and no NTP route at the observation site, so the
# GPS receiver is the only reliable time source. On by default because a
# wrong clock silently corrupts every timestamp in the archive; needs
# CAP_SYS_TIME (granted in systemd/ais-logger.service) and does nothing
# without it beyond one warning.
SET_CLOCK = os.environ.get("AIS_SET_CLOCK", "1") not in ("", "0", "false", "False")
CLOCK_TOLERANCE_SECONDS = float(os.environ.get("AIS_CLOCK_TOLERANCE_SECONDS", "2"))

# Web map server.
WEB_HOST = os.environ.get("AIS_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("AIS_WEB_PORT", "8080"))
# Path to an .mbtiles file; auto-discovered in BASE_DIR/DATA_DIR when unset.
MBTILES = os.environ.get("AIS_MBTILES") or None
# Vessels not heard from for this long disappear from the map.
SHIP_MAX_AGE_MINUTES = int(os.environ.get("AIS_SHIP_MAX_AGE_MINUTES", "60"))
# Length of the track drawn behind each vessel.
TRACK_MINUTES = int(os.environ.get("AIS_TRACK_MINUTES", "30"))
