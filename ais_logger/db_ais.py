import sqlite3

from ais_logger import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ais_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_unix INTEGER NOT NULL,
    mmsi INTEGER,
    msg_type INTEGER,
    lat REAL,
    lon REAL,
    sog_knots REAL,
    cog_deg REAL,
    heading_deg REAL,
    nav_status TEXT,
    shipname TEXT,
    callsign TEXT,
    source TEXT,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_ais_messages_ts ON ais_messages (ts_unix);
CREATE INDEX IF NOT EXISTS idx_ais_messages_mmsi ON ais_messages (mmsi);
"""


def ensure_schema(dbpath=None):
    dbpath = dbpath or config.DB_PATH
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(dbpath) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SCHEMA)


def insert_message(record: dict, dbpath=None):
    dbpath = dbpath or config.DB_PATH
    with sqlite3.connect(dbpath) as conn:
        conn.execute(
            "INSERT INTO ais_messages "
            "(ts_unix, mmsi, msg_type, lat, lon, sog_knots, cog_deg, heading_deg, "
            " nav_status, shipname, callsign, source, raw) VALUES "
            "(:ts_unix, :mmsi, :msg_type, :lat, :lon, :sog_knots, :cog_deg, :heading_deg, "
            " :nav_status, :shipname, :callsign, :source, :raw)",
            record,
        )
