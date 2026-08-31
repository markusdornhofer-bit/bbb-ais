"""Discipline the system clock from the GPS receiver.

The BeagleBone has no battery-backed RTC, and at the observation site there
is no internet route for NTP — after a power cycle the clock resumes near
wherever it left off, so every timestamp written to the database is wrong.
Measured on 28.08.2026 the system clock was two days behind reality. The
AIS stick already delivers UTC in every RMC sentence, which makes it the
natural time source here.

Setting the clock is deliberately done system-wide rather than only for the
database columns: the journal, the hourly rotation of the raw archive and
the web map's "how old is this vessel" logic all read the system clock, and
correcting only some of them would leave them disagreeing with each other.

Two implementation notes:

- Setting the clock needs `CAP_SYS_TIME`. `systemd/ais-logger.service`
  grants exactly that one capability, so the logger still runs as the
  unprivileged `debian` user rather than as root.
- `os.clock_settime` is absent from the Python build shipped with Debian
  Trixie (checked on the device: `os` has the `timerfd_*` family but no
  `clock_settime`), so libc is called through `ctypes` — still standard
  library, still no extra package to install.
"""
import ctypes
import os
import sys
import time
from datetime import timezone

_CLOCK_REALTIME = 0

# A GPS date outside this window cannot be a real fix; without the guard a
# garbled sentence that still parses could throw the clock into 2084 and
# take the whole archive's timestamps with it.
_MIN_EPOCH = 1735689600   # 2025-01-01
_MAX_EPOCH = 4102444800   # 2100-01-01


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


def set_system_clock(epoch: float) -> None:
    """Step CLOCK_REALTIME to `epoch`. Raises OSError (EPERM without
    CAP_SYS_TIME) so the caller can report it and carry on."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    spec = _Timespec(int(epoch), int((epoch - int(epoch)) * 1e9))
    if libc.clock_settime(_CLOCK_REALTIME, ctypes.byref(spec)) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


class GpsClock:
    """Steps the system clock whenever GPS disagrees with it by more than
    `tolerance` seconds. Never slews — a jump is what is wanted here, the
    clock can be days out after a cold start."""

    # `setter` stays None by default and is resolved in update() rather than
    # bound here, so tests can swap out the module-level function without
    # having to reach into every construction site.
    def __init__(self, enabled=True, tolerance=2.0, min_interval=60.0,
                 setter=None, now=time.time, monotonic=time.monotonic):
        self.enabled = enabled
        self.tolerance = tolerance
        self.min_interval = min_interval
        self.corrections = 0
        self.last_offset = None
        self._setter = setter
        self._now = now
        self._monotonic = monotonic
        # Rate limiting has to run off the monotonic clock: the wall clock is
        # the very thing being stepped, so a jump would otherwise either
        # block the next correction for days or disable the limit entirely.
        self._next_attempt = 0.0
        self._complained = False

    def update(self, gps_dt):
        """Feed a GPS UTC datetime. Returns the correction actually applied
        in seconds, or None when the clock was left alone."""
        if not self.enabled or gps_dt is None:
            return None
        if gps_dt.tzinfo is None:
            gps_dt = gps_dt.replace(tzinfo=timezone.utc)
        epoch = gps_dt.timestamp()
        if not (_MIN_EPOCH < epoch < _MAX_EPOCH):
            return None

        offset = epoch - self._now()
        self.last_offset = offset
        if abs(offset) <= self.tolerance:
            return None
        if self._monotonic() < self._next_attempt:
            return None
        self._next_attempt = self._monotonic() + self.min_interval

        try:
            (self._setter or set_system_clock)(epoch)
        except OSError as exc:
            if not self._complained:
                self._complained = True
                print(f"[clock] cannot set system clock ({exc}); timestamps stay "
                      f"{offset:+.0f}s off. Grant CAP_SYS_TIME in the systemd "
                      f"unit or set AIS_SET_CLOCK=0 to silence this.",
                      file=sys.stderr)
            return None

        self.corrections += 1
        print(f"[clock] stepped system clock by {offset:+.1f}s to "
              f"{gps_dt.isoformat()} (GPS)", file=sys.stderr)
        return offset
