import sqlite3

from ais_logger import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS own_position (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_unix INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    sog_knots REAL,
    cog_deg REAL,
    source_sentence TEXT
);
CREATE INDEX IF NOT EXISTS idx_own_position_ts ON own_position (ts_unix);
"""


def ensure_schema(dbpath=None):
    dbpath = dbpath or config.DB_PATH
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(dbpath) as conn:
        # WAL lets the logger (own_position writes) and the periodic
        # aisdb ingest job (AIS table writes) touch the same file safely.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SCHEMA)


def insert_own_position(record: dict, dbpath=None):
    dbpath = dbpath or config.DB_PATH
    with sqlite3.connect(dbpath) as conn:
        conn.execute(
            "INSERT INTO own_position "
            "(ts_unix, lat, lon, sog_knots, cog_deg, source_sentence) "
            "VALUES (:ts_unix, :lat, :lon, :sog_knots, :cog_deg, :source_sentence)",
            record,
        )
