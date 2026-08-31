"""Offline web map for watching AIS traffic, served straight off the
BeagleBone. Standard library only — no web framework, no map library, no
internet access required at the observation site.

    python -m webmap.server
    -> http://<beaglebone>:8080/
"""
import datetime as dt
import gzip
import json
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from ais_logger import config
from webmap.tiles import find_mbtiles, load_basemap

STATIC_DIR = Path(__file__).resolve().parent / "static"

_basemap_cache = {"json": None, "gzipped": None}


def _load_basemap_once():
    if _basemap_cache["json"] is not None:
        return
    path = config.MBTILES or find_mbtiles([config.BASE_DIR, config.DATA_DIR])
    if not path or not Path(path).exists():
        payload = {"error": "no .mbtiles found", "layers": {}, "bounds": None}
    else:
        print(f"[web] loading base map from {path}", file=sys.stderr)
        payload = load_basemap(path)
        counts = {k: len(v) for k, v in payload["layers"].items() if v}
        print(f"[web] base map ready: {counts}", file=sys.stderr)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    _basemap_cache["json"] = raw
    _basemap_cache["gzipped"] = gzip.compress(raw, 6)


def _query_live():
    """Latest position per vessel, their tracks, and our own position."""
    db_path = Path(config.DB_PATH)
    if not db_path.exists():
        return {"own": None, "ships": [], "tracks": {}, "now": int(time.time()),
                "max_age_min": config.SHIP_MAX_AGE_MINUTES}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        now = int(time.time())
        since = now - config.SHIP_MAX_AGE_MINUTES * 60
        track_since = now - config.TRACK_MINUTES * 60

        # Bare columns alongside MAX() return that row's values in SQLite.
        ships = [
            {
                "mmsi": r[0], "ts": r[1], "lat": r[2], "lon": r[3],
                "sog": r[4], "cog": r[5], "hdg": r[6],
            }
            for r in conn.execute(
                "SELECT mmsi, MAX(ts_unix), lat, lon, sog_knots, cog_deg, heading_deg "
                "FROM ais_messages WHERE lat IS NOT NULL AND lon IS NOT NULL "
                "AND ts_unix >= ? GROUP BY mmsi", (since,))
        ]

        names = dict(conn.execute(
            "SELECT mmsi, shipname FROM ais_messages "
            "WHERE shipname IS NOT NULL GROUP BY mmsi"))
        for ship in ships:
            ship["name"] = names.get(ship["mmsi"])

        # Only for vessels that are actually on screen. The two windows are
        # independent — SHIP_MAX_AGE_MINUTES decides who is shown,
        # TRACK_MINUTES how much of their path — and without this filter a
        # longer track window leaves orphan lines behind vessels that dropped
        # out of the display window.
        # Points carry their timestamp because the client derives a vessel's
        # actual motion from the last segment — reported course and speed are
        # a snapshot, the segment is what the vessel really did.
        shown = {s["mmsi"] for s in ships}
        tracks = {}
        for mmsi, ts, lat, lon in conn.execute(
                "SELECT mmsi, ts_unix, lat, lon FROM ais_messages "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL AND ts_unix >= ? "
                "ORDER BY ts_unix", (track_since,)):
            if mmsi in shown:
                tracks.setdefault(str(mmsi), []).append([lon, lat, ts])

        own_row = conn.execute(
            "SELECT ts_unix, lat, lon, sog_knots, cog_deg FROM own_position "
            "ORDER BY ts_unix DESC LIMIT 1").fetchone()
        own = None
        if own_row:
            own = {"ts": own_row[0], "lat": own_row[1], "lon": own_row[2],
                   "sog": own_row[3], "cog": own_row[4]}

        # The window travels with the payload so the page can label what it
        # is showing instead of leaving "0 vessels" ambiguous.
        return {"own": own, "ships": ships, "tracks": tracks, "now": now,
                "max_age_min": config.SHIP_MAX_AGE_MINUTES}
    finally:
        conn.close()


def _query_days():
    """Days that hold recorded traffic, newest first, for the day picker."""
    db_path = Path(config.DB_PATH)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [
            {"date": d, "messages": n, "ships": v}
            for d, n, v in conn.execute(
                "SELECT date(ts_unix,'unixepoch'), COUNT(*), COUNT(DISTINCT mmsi) "
                "FROM ais_messages WHERE lat IS NOT NULL AND lon IS NOT NULL "
                "GROUP BY 1 ORDER BY 1 DESC")
        ]
    finally:
        conn.close()


def _query_history(since, until):
    """Everything recorded in [since, until), for the replay player.

    Sent in one piece rather than streamed: at the reception rates measured
    here (a few dozen messages an hour) even a full day is a handful of
    kilobytes, and having it all client-side makes scrubbing instant."""
    db_path = Path(config.DB_PATH)
    if not db_path.exists():
        return {"from": since, "to": until, "ships": [], "names": {}, "own": []}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ships = [
            {"mmsi": r[0], "ts": r[1], "lat": r[2], "lon": r[3],
             "sog": r[4], "cog": r[5], "hdg": r[6]}
            for r in conn.execute(
                "SELECT mmsi, ts_unix, lat, lon, sog_knots, cog_deg, heading_deg "
                "FROM ais_messages WHERE lat IS NOT NULL AND lon IS NOT NULL "
                "AND ts_unix >= ? AND ts_unix < ? ORDER BY ts_unix", (since, until))
        ]
        names = {str(m): n for m, n in conn.execute(
            "SELECT mmsi, shipname FROM ais_messages "
            "WHERE shipname IS NOT NULL GROUP BY mmsi")}
        own = [[r[0], r[1], r[2]] for r in conn.execute(
            "SELECT ts_unix, lat, lon FROM own_position "
            "WHERE ts_unix >= ? AND ts_unix < ? ORDER BY ts_unix", (since, until))]
        return {"from": since, "to": until, "ships": ships, "names": names, "own": own}
    finally:
        conn.close()


def _nm(la1, lo1, la2, lo2):
    """Great-circle-ish distance in nautical miles. Flat-earth is plenty over
    the few miles this receiver reaches."""
    import math
    return math.hypot((la2 - la1) * 60,
                      (lo2 - lo1) * 60 * math.cos(math.radians((la1 + la2) / 2)))


# AIS reports "speed not available" as 102.3 knots. Left in, it wins every
# "fastest vessel" question with a non-answer.
_SOG_UNAVAILABLE = 102.0

# AIS is line-of-sight VHF. Twenty to forty miles is the normal reach and
# exceptional atmospherics stretch it to perhaps a hundred; beyond that a
# position is a decoding artefact, not a vessel. Records computed over such
# rows are meaningless — on 31.08.2026 the "farthest contact" was 7507 nm.
_MAX_PLAUSIBLE_NM = 100.0


def _query_stats():
    """Records over everything recorded: the farthest contact, the longest,
    the fastest and so on. Distances are measured against our own position
    at the time of the message, not against an average — the receiver has
    moved between countries once already."""
    db_path = Path(config.DB_PATH)
    leer = {"ships": 0, "messages": 0, "from": None, "to": None, "records": []}
    if not db_path.exists():
        return leer

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        eigen = conn.execute(
            "SELECT ts_unix, lat, lon FROM own_position ORDER BY ts_unix").fetchall()
        rows = conn.execute(
            "SELECT mmsi, ts_unix, lat, lon, sog_knots FROM ais_messages "
            "WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY ts_unix").fetchall()
        namen = {m: n for m, n in conn.execute(
            "SELECT mmsi, shipname FROM ais_messages "
            "WHERE shipname IS NOT NULL GROUP BY mmsi")}
    finally:
        conn.close()

    if not rows:
        return leer

    import bisect
    zeiten = [e[0] for e in eigen]

    def eigen_bei(ts):
        """Own position closest in time to a message."""
        if not eigen:
            return None
        i = bisect.bisect_left(zeiten, ts)
        kandidaten = [k for k in (i - 1, i) if 0 <= k < len(eigen)]
        return min(kandidaten, key=lambda k: abs(zeiten[k] - ts))

    proSchiff = {}
    verworfen = 0
    for mmsi, ts, lat, lon, sog in rows:
        k = eigen_bei(ts)
        d = _nm(eigen[k][1], eigen[k][2], lat, lon) if k is not None else None
        if d is not None and d > _MAX_PLAUSIBLE_NM:
            verworfen += 1
            continue
        s = proSchiff.setdefault(mmsi, {
            "n": 0, "erst": ts, "letzt": ts, "weit": 0.0, "weit_ts": ts,
            "sog": None, "strecke": 0.0, "vor": None})
        s["n"] += 1
        s["letzt"] = ts
        if d is not None and d > s["weit"]:
            s["weit"], s["weit_ts"] = d, ts
        if sog is not None and sog < _SOG_UNAVAILABLE:
            if s["sog"] is None or sog > s["sog"]:
                s["sog"] = sog
        if s["vor"] is not None:
            s["strecke"] += _nm(s["vor"][0], s["vor"][1], lat, lon)
        s["vor"] = (lat, lon)

    def name(mmsi):
        return namen.get(mmsi) or str(mmsi)

    def bester(schluessel, filter_=None):
        kand = [(m, s) for m, s in proSchiff.items()
                if (filter_ is None or filter_(s)) and schluessel(s) is not None]
        return max(kand, key=lambda t: schluessel(t[1])) if kand else None

    rekorde = []

    def eintrag(titel, treffer, wert, einheit, ts=None):
        if not treffer:
            return
        mmsi, s = treffer
        rekorde.append({"titel": titel, "mmsi": mmsi, "name": name(mmsi),
                        "wert": wert(s), "einheit": einheit,
                        "ts": ts(s) if ts else s["letzt"]})

    eintrag("weiteste Entfernung", bester(lambda s: s["weit"] or None),
            lambda s: round(s["weit"], 2), "nm", lambda s: s["weit_ts"])
    eintrag("längster Kontakt", bester(lambda s: s["letzt"] - s["erst"] or None),
            lambda s: round((s["letzt"] - s["erst"]) / 60), "min")
    eintrag("größte Fahrt", bester(lambda s: s["sog"]),
            lambda s: round(s["sog"], 1), "kn")
    eintrag("meiste Meldungen", bester(lambda s: s["n"]),
            lambda s: s["n"], "Meldungen")
    eintrag("längster Weg", bester(lambda s: s["strecke"] or None),
            lambda s: round(s["strecke"], 2), "nm")

    return {
        "ships": len(proSchiff),
        "messages": len(rows) - verworfen,
        "dropped": verworfen,
        "from": rows[0][1],
        "to": rows[-1][1],
        "records": rekorde,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AISMap/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the journal free of one line per poll

    def _send(self, body, content_type, gzipped=None):
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        if gzipped is not None and accepts_gzip:
            body, encoding = gzipped, "gzip"
        else:
            encoding = None
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                body = (STATIC_DIR / "index.html").read_bytes()
                self._send(body, "text/html; charset=utf-8")
            elif path == "/api/map":
                _load_basemap_once()
                self._send(_basemap_cache["json"], "application/json",
                           _basemap_cache["gzipped"])
            elif path == "/api/live":
                body = json.dumps(_query_live(), separators=(",", ":")).encode()
                self._send(body, "application/json")
            elif path == "/api/stats":
                raw = json.dumps(_query_stats(), separators=(",", ":")).encode()
                self._send(raw, "application/json")
            elif path == "/api/days":
                raw = json.dumps(_query_days(), separators=(",", ":")).encode()
                self._send(raw, "application/json")
            elif path == "/api/history":
                q = parse_qs(self.path.partition("?")[2])
                # A named day wins over the rolling window, so the picker can
                # ask for one calendar day in UTC — the same basis every
                # timestamp in the archive uses.
                day = q.get("date", [None])[0]
                start = None
                if day:
                    try:
                        start = dt.datetime.strptime(day, "%Y-%m-%d").replace(
                            tzinfo=dt.timezone.utc)
                    except ValueError:
                        start = None
                if start is not None:
                    since = int(start.timestamp())
                    until = since + 86400
                else:
                    try:
                        hours = min(max(float(q.get("hours", ["24"])[0]), 0.1), 720)
                    except ValueError:
                        hours = 24
                    until = int(time.time())
                    since = until - int(hours * 3600)
                raw = json.dumps(_query_history(since, until),
                                 separators=(",", ":")).encode()
                self._send(raw, "application/json", gzip.compress(raw, 6))
            else:
                self.send_error(404)
        except Exception as exc:  # never let one bad request kill the server
            self.send_error(500, str(exc))


def main():
    _load_basemap_once()
    server = ThreadingHTTPServer((config.WEB_HOST, config.WEB_PORT), Handler)
    print(f"[web] serving on http://{config.WEB_HOST}:{config.WEB_PORT}/",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
