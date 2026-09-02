"""Write one line every ten seconds to a log file: the closest vessel
that is actually moving, measured from our own position.

This is the proximity watch the recording is for -- a moored boat wants to
know what is approaching under way, not how many targets are in the
database. A vessel below the speed threshold is at anchor or alongside and
cannot run into anything, so it is left out; anything beyond the range
limit is too far to matter and is reported as "none".

    python tools/closest_ship.py                  # /tmp/ais_closest.log
    python tools/closest_ship.py --once --echo    # one line, to the terminal
    tail -f /tmp/ais_closest.log

Each line names the distance, the bearing from us, the vessel's speed, how
old its last report is, and who it is:

    2026-09-02T14:31:00Z  dist 2.4nm  brg 118  sog 7.3kn  age 22s  \\
        mmsi 238537940  KORNAT
    2026-09-02T14:32:00Z  none within 9.9 nm

An "age" above 180 cannot appear: such a report is dropped before the
distance is even computed.

The age matters as much as the distance. AIS is not radar: a target that
last reported three minutes ago has already moved half a mile at 10 kn.
Reports older than --max-age are ignored entirely rather than presented as
current, so a quiet line means nothing is both near, moving and recent --
not that the sea is empty.
"""
import argparse
import math
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ais_logger import config  # noqa: E402
from webmap.server import _nm, _SOG_UNAVAILABLE  # noqa: E402

# A vessel under this is anchored, moored or drifting; it is not closing on
# anyone and would otherwise fill every line with the same neighbour.
MIN_FAHRT = 2.0
# Beyond this the answer is "nothing worth reporting". Also keeps the
# printed distance to three characters, so the column never jumps.
GRENZE_NM = 9.9
# A position report older than this is history, not a target. Three
# minutes: a vessel at 10 kn covers half a mile in that time, which is
# already more error than the reported distance is worth.
HOECHSTALTER = 180
# Ten seconds is well below the rate at which anything in the picture
# changes -- a vessel at 10 kn moves 30 m -- but it means the log shows a
# closing target within one step of the report arriving, not up to a
# minute later.
INTERVALL = 10.0
# AIS reports "course not available" as 360. Unlike the speed sentinel this
# one is stored raw, so it has to be caught here: 1699 of 7141 position
# reports carry it. Among vessels actually making way it is rare -- two out
# of 3434 -- so dead reckoning is available for practically every target
# that matters.
_COG_UNAVAILABLE = 360.0
LOGDATEI = "/tmp/ais_closest.log"

_laeuft = True


def _stopp(signum, rahmen):
    global _laeuft
    _laeuft = False


def peilung(la1, lo1, la2, lo2):
    """True bearing from the first point to the second, in degrees."""
    nord = (la2 - la1) * 60
    ost = (lo2 - lo1) * 60 * math.cos(math.radians((la1 + la2) / 2))
    return math.degrees(math.atan2(ost, nord)) % 360


def koppeln(la, lo, cog, sog, sekunden):
    """Carry a reported position forward along its course.

    A report is always in the past, and the vessel has not waited there.
    Over the seconds involved here a straight line on a flat earth is far
    more accuracy than the input deserves -- the reported course is a
    tenth of a degree at best, and a turn between reports is invisible
    either way.
    """
    weg = sog * sekunden / 3600.0
    return (la + weg * math.cos(math.radians(cog)) / 60.0,
            lo + weg * math.sin(math.radians(cog)) / (60.0 * math.cos(math.radians(la))))


def eigene_position(conn):
    zeile = conn.execute(
        "SELECT ts_unix, lat, lon FROM own_position "
        "ORDER BY ts_unix DESC LIMIT 1").fetchone()
    return zeile


def naechstes_schiff(conn, jetzt, mindestfahrt, hoechstalter, grenze):
    """The closest vessel above the speed threshold, or None.

    Only the newest report of each vessel counts. An older one is a
    position the vessel has already left, and taking the closest over all
    reports would answer a question nobody asked -- how near something once
    came, not where it is.

    That position is then carried forward to now along the reported course,
    and the ranking uses the carried-forward distance. Without it the log
    answers where a vessel was up to three minutes ago; at 10 kn that is
    half a mile of error, and the whole point is what is closing now. The
    reported distance stays in the line so the extrapolation can be checked
    against it.
    """
    eigen = eigene_position(conn)
    if eigen is None:
        return None, "no own position recorded"
    _, eigen_la, eigen_lo = eigen

    letzte = {}
    for mmsi, ts, la, lo, sog, cog in conn.execute(
            "SELECT mmsi, ts_unix, lat, lon, sog_knots, cog_deg FROM ais_messages "
            "WHERE lat IS NOT NULL AND lon IS NOT NULL AND ts_unix >= ? "
            "ORDER BY ts_unix", (jetzt - hoechstalter,)):
        letzte[mmsi] = (ts, la, lo, sog, cog)

    bestes = None
    for mmsi, (ts, la, lo, sog, cog) in letzte.items():
        if sog is None or sog >= _SOG_UNAVAILABLE or sog < mindestfahrt:
            continue
        alter = jetzt - ts
        gemeldet = _nm(eigen_la, eigen_lo, la, lo)
        if cog is None or cog >= _COG_UNAVAILABLE:
            # No course, so nothing to carry the position along. Better to
            # say so in the line than to invent a direction.
            kla, klo, kurs = la, lo, None
        else:
            kla, klo = koppeln(la, lo, cog, sog, alter)
            kurs = cog % 360
        weit = _nm(eigen_la, eigen_lo, kla, klo)
        if weit > grenze:
            continue
        if bestes is None or weit < bestes[0]:
            bestes = (weit, gemeldet, peilung(eigen_la, eigen_lo, kla, klo),
                      kurs, sog, alter, mmsi)

    if bestes is None:
        return None, f"none within {grenze:.1f} nm"
    return bestes, None


def namen(conn):
    return {m: n.strip() for m, n in conn.execute(
        "SELECT mmsi, shipname FROM ais_messages "
        "WHERE shipname IS NOT NULL AND shipname != '' GROUP BY mmsi") if n.strip()}


def zeile_bauen(jetzt, bestes, grund, benennung):
    stempel = datetime.fromtimestamp(jetzt, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if bestes is None:
        return f"{stempel}  {grund}"
    weit, gemeldet, brg, kurs, sog, alter, mmsi = bestes
    name = benennung.get(mmsi, "")
    # "cog ---" means the vessel reported no course, so dist could not be
    # carried forward and equals rep.
    cog = f"{kurs:03.0f}" if kurs is not None else "---"
    return (f"{stempel}  dist {weit:3.1f}nm  rep {gemeldet:3.1f}nm  "
            f"brg {brg:03.0f}  cog {cog}  sog {sog:4.1f}kn  "
            f"age {alter:3.0f}s  mmsi {mmsi}" + (f"  {name}" if name else ""))


def main():
    zerleger = argparse.ArgumentParser(
        description="Log the closest moving vessel every few seconds.")
    zerleger.add_argument("--log", default=LOGDATEI,
                          help=f"log file to append to (default {LOGDATEI})")
    zerleger.add_argument("--interval", type=float, default=INTERVALL,
                          help=f"seconds between lines (default {INTERVALL:g})")
    zerleger.add_argument("--limit", type=float, default=GRENZE_NM,
                          help=f"report nothing farther than this, in nautical "
                               f"miles (default {GRENZE_NM})")
    zerleger.add_argument("--min-speed", type=float, default=MIN_FAHRT,
                          help=f"ignore vessels slower than this (default {MIN_FAHRT})")
    zerleger.add_argument("--max-age", type=float, default=HOECHSTALTER,
                          help=f"ignore reports older than this many seconds "
                               f"(default {HOECHSTALTER})")
    zerleger.add_argument("--once", action="store_true",
                          help="write a single line and exit")
    zerleger.add_argument("--echo", action="store_true",
                          help="also write each line to stdout")
    argumente = zerleger.parse_args()

    if argumente.interval <= 0:
        zerleger.error("--interval must be positive")

    db = Path(config.DB_PATH)
    if not db.exists():
        print(f"no database at {db}", file=sys.stderr)
        return 1

    signal.signal(signal.SIGINT, _stopp)
    signal.signal(signal.SIGTERM, _stopp)

    log = open(argumente.log, "a", encoding="utf-8")
    kopf = (f"# closest moving vessel, every {argumente.interval:g}s: "
            f"min {argumente.min_speed:g} kn, within {argumente.limit:g} nm, "
            f"reports up to {argumente.max_age:g}s old")
    print(kopf, file=log, flush=True)
    if argumente.echo:
        print(kopf)
    else:
        print(f"logging to {argumente.log}", file=sys.stderr)

    while _laeuft:
        jetzt = time.time()
        # Read-only: the logger is writing this file at the same time. WAL
        # is on (db_own_position.ensure_schema), so this never blocks it.
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            bestes, grund = naechstes_schiff(
                conn, jetzt, argumente.min_speed, argumente.max_age, argumente.limit)
            benennung = namen(conn) if bestes else {}
        finally:
            conn.close()

        zeile = zeile_bauen(jetzt, bestes, grund, benennung)
        print(zeile, file=log, flush=True)
        if argumente.echo:
            print(zeile, flush=True)

        if argumente.once:
            break
        # Align to the interval so the timestamps stay on round steps
        # however long the query took.
        rest = argumente.interval - (time.time() % argumente.interval)
        ende = time.monotonic() + rest
        while _laeuft and time.monotonic() < ende:
            time.sleep(min(0.5, ende - time.monotonic()))

    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
