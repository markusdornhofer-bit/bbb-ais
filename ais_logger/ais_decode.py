"""Decode AIVDM/AIVDO sentences with pyais, reassembling multi-fragment
messages (e.g. type 5 static/voyage data spans 2 sentences). Kept as a
pure-Python path since aisdb's native decoder proved unreliable in testing
(see README) — this only writes to our own ais_messages table.
"""
import time

import pyais
from pyais.messages import MSG_CLASS

from ais_logger.nmea_tagblock import nmea_checksum_valid

# Types the AIS spec defines with one fixed length, so anything shorter is
# provably truncated. Deliberately excludes the variable-length types
# (6/7/8/12/13/14/15/17/20/21/24/25/26): those legitimately come in short
# forms, and length-checking them would throw away valid traffic — e.g.
# aid-to-navigation reports (21) are 272-360 bits depending on the name.
_FIXED_LENGTH_TYPES = {1, 2, 3, 4, 5, 9, 11, 18, 19, 27}

# msg_type + repeat + mmsi: below this nothing can be decoded at all.
_HEADER_BITS = 38

# Only message types that actually populate a column of ais_messages are
# stored. Everything else — the binary, safety, interrogation and management
# types (6/7/8/10/12/13/14/15/16/17/20/22/23/25/26) — leaves every column
# empty, so keeping it buys nothing.
#
# It is also the practical noise filter. Those types are variable length,
# which means is_plausible has no length expectation to check them against,
# and with the weak reception measured on 28.08.2026 (nothing beyond 0.86 nm)
# garbled bursts decode into them disproportionately often: of 53 stored
# messages, four were provably bogus and three of those were types 12 and 15,
# two with payload lengths the standard does not define for them at all.
#
# Type 17 is excluded deliberately even though pyais decodes a position from
# it: that is a DGNSS reference station's location, not a vessel, and it
# would be drawn on the map as a ship.
#
# The raw .nm4 archive keeps every sentence regardless, so nothing is lost.
_STORED_TYPES = {1, 2, 3, 4, 5, 9, 11, 18, 19, 21, 24, 27}

_min_bits_cache = {}


def _min_bits(msg_type):
    """Required payload bits for fixed-length message types, derived from
    pyais' own field widths. None means "no length expectation"."""
    if msg_type not in _FIXED_LENGTH_TYPES:
        return None
    if msg_type not in _min_bits_cache:
        try:
            widths = [f.metadata["width"] for f in MSG_CLASS[msg_type].fields()]
            _min_bits_cache[msg_type] = sum(widths) or None
        except Exception:
            _min_bits_cache[msg_type] = None
    return _min_bits_cache[msg_type]


def _payload_bits(fragments) -> int:
    """Total six-bit payload bits across fragments, minus the fill bits
    declared by the last fragment."""
    bits = sum(len(f.split(",")[5]) for f in fragments) * 6
    try:
        fill = int(fragments[-1].split(",")[6].split("*")[0])
    except (IndexError, ValueError):
        fill = 0
    return bits - fill


def is_plausible(decoded, fragments) -> bool:
    """Reject decodes that cannot be real. A receiver with poor reception
    emits truncated sentences that still carry a valid NMEA checksum;
    pyais decodes those silently into nonsense (e.g. lon=24287.3), so the
    values have to be sanity-checked before they reach the database."""
    d = decoded.asdict()

    # ITU-R M.1371 defines message types 1-27. pyais will happily decode a
    # garbled payload into e.g. type 28, so anything outside that range is
    # noise by definition.
    msg_type = d.get("msg_type")
    if msg_type is None or not (1 <= int(msg_type) <= 27):
        return False

    bits = _payload_bits(fragments)
    if bits < _HEADER_BITS:
        return False
    required = _min_bits(msg_type)
    if required is not None and bits < required:
        return False

    lat, lon = d.get("lat"), d.get("lon")
    # 91 / 181 are the standard "not available" sentinels and are legitimate.
    if lat is not None and not (-90 <= lat <= 90 or lat == 91):
        return False
    if lon is not None and not (-180 <= lon <= 180 or lon == 181):
        return False

    mmsi = d.get("mmsi")
    if mmsi is not None and not (0 < int(mmsi) <= 999999999):
        return False

    return True


class FragmentBuffer:
    def __init__(self, stale_after=30):
        self.stale_after = stale_after
        self.rejected = 0   # decoded, but cannot be a real message
        self.filtered = 0   # valid, but a type we deliberately do not store
        self._pending = {}  # (seq_id, channel, total) -> {deadline, frags, ts}

    def _accept(self, decoded, fragments) -> bool:
        """Whether a decoded message should reach the database, counting the
        two reasons for dropping one separately: `rejected` is the reception
        quality indicator shown in the heartbeat and must not be inflated by
        messages we simply have no use for."""
        if not is_plausible(decoded, fragments):
            self.rejected += 1
            return False
        if decoded.asdict().get("msg_type") not in _STORED_TYPES:
            self.filtered += 1
            return False
        return True

    def feed(self, line: str, ts_unix=None):
        """Feed one bare NMEA sentence (no tag block). Returns
        (decoded_message, ts_unix) once a message is complete, else None."""
        if len(line) < 6 or line[0] != "!" or line[3:6] not in ("VDM", "VDO"):
            return None
        if not nmea_checksum_valid(line):
            self.rejected += 1
            return None
        parts = line.split(",")
        if len(parts) < 6:
            return None
        try:
            total = int(parts[1])
            frag_num = int(parts[2])
        except ValueError:
            return None

        if total <= 1:
            decoded = self._try_decode((line,))
            if decoded is None or not self._accept(decoded, (line,)):
                return None
            return decoded, (ts_unix if ts_unix is not None else int(time.time()))

        self._evict_stale()
        key = (parts[3], parts[4], total)
        entry = self._pending.setdefault(
            key, {"deadline": time.time() + self.stale_after, "frags": {}, "ts": None}
        )
        entry["frags"][frag_num] = line
        if ts_unix is not None and entry["ts"] is None:
            entry["ts"] = ts_unix
        if len(entry["frags"]) < total:
            return None

        del self._pending[key]
        if sorted(entry["frags"]) != list(range(1, total + 1)):
            return None  # missing a fragment despite count reached (dupes/out of order)
        ordered = tuple(entry["frags"][i] for i in range(1, total + 1))
        decoded = self._try_decode(ordered)
        if decoded is None or not self._accept(decoded, ordered):
            return None
        return decoded, (entry["ts"] if entry["ts"] is not None else int(time.time()))

    def _evict_stale(self):
        now = time.time()
        for key in [k for k, v in self._pending.items() if v["deadline"] < now]:
            del self._pending[key]

    @staticmethod
    def _try_decode(fragments):
        try:
            return pyais.decode(*fragments)
        except Exception:
            return None


def _oder_none(wert, kennwert):
    """AIS marks a missing value with an out-of-range number rather than an
    empty field: latitude 91, longitude 181, speed 102.3. Stored as they
    arrive they become real-looking data — 91/181 reads as a position 4765 nm
    away, and 102.3 wins every "fastest vessel" question with a non-answer.
    They belong in the database as NULL."""
    return None if wert is None or wert == kennwert else wert


def to_record(decoded, ts_unix: int, source: str, raw_line: str) -> dict:
    d = decoded.asdict()
    status = d.get("status")
    lat = _oder_none(d.get("lat"), 91)
    lon = _oder_none(d.get("lon"), 181)
    # A position is only a position with both halves; one sentinel voids it.
    if lat is None or lon is None:
        lat = lon = None
    return {
        "ts_unix": ts_unix,
        "mmsi": d.get("mmsi"),
        "msg_type": d.get("msg_type"),
        "lat": lat,
        "lon": lon,
        "sog_knots": _oder_none(d.get("speed"), 102.3),
        "cog_deg": d.get("course"),
        "heading_deg": d.get("heading"),
        "nav_status": str(status) if status is not None else None,
        "shipname": (d.get("shipname") or "").strip() or None,
        "callsign": (d.get("callsign") or "").strip() or None,
        "source": source,
        "raw": raw_line,
    }
