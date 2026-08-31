import time
from datetime import datetime

import pynmea2


def parse_gps_datetime(line: str):
    """Return a UTC datetime from an RMC sentence, even without a fix —
    used for a live status printout so `run_logger` shows the receiver is
    alive before a fix is acquired."""
    try:
        msg = pynmea2.parse(line)
    except pynmea2.ParseError:
        return None
    if type(msg).__name__ != "RMC" or not msg.timestamp or not msg.datestamp:
        return None
    return datetime.combine(msg.datestamp, msg.timestamp)


def parse_own_position(line: str):
    """Return an own-position dict for GGA/RMC/GLL fixes, else None."""
    try:
        msg = pynmea2.parse(line)
    except pynmea2.ParseError:
        return None

    sentence = type(msg).__name__  # pynmea2's .sentence_type attribute is version-fragile
    if sentence not in ("GGA", "RMC", "GLL"):
        return None
    if msg.latitude in (None, 0) and msg.longitude in (None, 0):
        return None
    if sentence == "RMC" and getattr(msg, "status", "A") != "A":
        return None  # RMC void/invalid fix
    if sentence == "GGA" and str(getattr(msg, "gps_qual", 1)) == "0":
        return None  # GGA fix-not-available

    return {
        "ts_unix": int(time.time()),
        "lat": msg.latitude,
        "lon": msg.longitude,
        "sog_knots": getattr(msg, "spd_over_grnd", None),
        "cog_deg": getattr(msg, "true_course", None),
        "source_sentence": sentence,
    }
