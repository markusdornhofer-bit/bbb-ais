"""Replay the recorded .nm4 archives onto a virtual serial port, in real
time, starting at a chosen point in the recording.

The point is to exercise the whole chain -- reader, decoder, database, web
map -- without the receiver being present, and without the archives having
to be re-ingested in bulk. Whatever reads the port cannot tell the
difference from the real stick: the tag block that the archives carry is
added by ais_logger/reader.py, not by the hardware, so it is stripped again
here and the bare NMEA sentence goes out, CRLF-terminated.

    python tools/replay_serial.py 2026-08-29T06:00 --link /tmp/ttyAIS

    AIS_SET_CLOCK=0 AIS_DEVICE=/tmp/ttyAIS python -m ais_logger.run_logger

AIS_SET_CLOCK=0 is not optional on the BeagleBone. The replayed stream
carries the GPS time of the recording, and ais_logger/gps_clock.py believes
it: a live logger pointed at this port would step the system clock days
into the past, and every timestamp written afterwards would be wrong.

The port is a pty. It has no real baud rate, so a reader may open it at any
speed; the pacing comes from the recorded timestamps, not from the line.

    --tempo N      run N times faster than real time (default 1.0). The
                   reader has to keep up: on the BeagleBone, real time is
                   about 10 sentences/s and loses nothing, while 20x reached
                   154/s and the port dropped more than half. Drops are
                   counted and reported, never silent.
    --max-gap S    compress idle stretches longer than S seconds (default
                   60; "keep" reproduces them in full). The recording has
                   three overnight gaps of 8-9 hours -- without this the
                   replay would simply sit there.
    --until T      stop at this point in the recording
    --link PATH    symlink PATH to the pty, so the port has a stable name
    --list         print what the archives cover, then exit

Times are read as UTC unless --local is given; both are shown at startup.

What lands in the database is stamped with the wall clock, not with the
time of the recording -- reader.py uses time.time(), exactly as it does
with the real stick. So a replay of a morning three days ago shows up as
vessels seen just now, which is what the live map wants. Use the archives
themselves, or the web player, when the original timestamps matter.
"""
import argparse
import errno
import os
import signal
import sys
import termios
import time
import tty
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ais_logger import config  # noqa: E402
from ais_logger.nmea_tagblock import strip_tagblock  # noqa: E402

# Archives live in raw/ while the logger is writing them and are moved to
# archiv_*/ by hand afterwards; a replay wants both.
QUELLEN = ["raw", "archiv_*"]

# How far into a file to look for the RMC sentence that reveals the clock
# offset. The offset is a property of the boot, so the first fix decides it.
PRUEF_ZEILEN = 5000
# Below this, a difference between tag block and GPS time is ordinary drift
# rather than a wrong clock, and correcting it would add noise.
VERSATZ_SCHWELLE = 600

_laeuft = True


def _stopp(signum, rahmen):
    global _laeuft
    _laeuft = False


class Datei:
    """One archive file with the correction its timestamps need."""

    def __init__(self, pfad, start, ende, versatz):
        self.pfad = pfad
        self.start = start
        self.ende = ende
        self.versatz = versatz


def _rmc_zeit(satz):
    """UTC of an RMC sentence that carries a valid fix, else None."""
    feld = satz.split(",")
    if len(feld) < 10 or feld[2] != "A" or not feld[1] or not feld[9]:
        return None
    try:
        return datetime.strptime(feld[9] + feld[1][:6],
                                 "%d%m%y%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _kopf(pfad):
    """First tag-block timestamp and the clock offset of the file.

    The board has no RTC, so after a reboot the system clock resumed from a
    stale value and the tag blocks lie -- by 49.3 h in the two files rescued
    from the 28.08. archive. The GPS time in the RMC sentences is the truth,
    so the difference between the two is the correction for the whole file.
    """
    erste = None
    versatz = 0
    with open(pfad, encoding="ascii", errors="replace") as f:
        for nummer, zeile in enumerate(f):
            satz, ts = strip_tagblock(zeile.strip())
            if ts is None:
                continue
            if erste is None:
                erste = ts
            if "RMC" in satz:
                wann = _rmc_zeit(satz)
                if wann is not None:
                    weicht = wann.timestamp() - ts
                    versatz = round(weicht) if abs(weicht) > VERSATZ_SCHWELLE else 0
                    break
            if nummer > PRUEF_ZEILEN:
                break
    return erste, versatz


def _fusszeit(pfad, block=65536):
    """Last tag-block timestamp, read from the tail instead of the whole file."""
    with open(pfad, "rb") as f:
        f.seek(0, os.SEEK_END)
        groesse = f.tell()
        f.seek(max(0, groesse - block))
        zeilen = f.read().decode("ascii", errors="replace").splitlines()
    for zeile in reversed(zeilen):
        _, ts = strip_tagblock(zeile.strip())
        if ts is not None:
            return ts
    return None


def sammle_dateien(datenverzeichnis):
    """Index every archive file by the true time span it covers."""
    pfade = []
    for muster in QUELLEN:
        for ordner in sorted(datenverzeichnis.glob(muster)):
            pfade.extend(sorted(ordner.glob("*.nm4")))

    dateien = []
    for pfad in pfade:
        erste, versatz = _kopf(pfad)
        letzte = _fusszeit(pfad)
        if erste is None or letzte is None:
            continue
        dateien.append(Datei(pfad, erste + versatz, letzte + versatz, versatz))
    dateien.sort(key=lambda d: d.start)
    return dateien


def saetze(dateien, ab, bis):
    """Yield (timestamp, sentence) in order, skipping anything before `ab`."""
    for datei in dateien:
        if datei.ende < ab or (bis is not None and datei.start > bis):
            continue
        with open(datei.pfad, encoding="ascii", errors="replace") as f:
            for zeile in f:
                satz, ts = strip_tagblock(zeile.strip())
                if ts is None or not satz:
                    continue
                ts += datei.versatz
                if ts < ab:
                    continue
                if bis is not None and ts > bis:
                    return
                yield ts, satz


FORMATE = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
           "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d",
           "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y")


def lies_zeit(text, lokal):
    for form in FORMATE:
        try:
            wann = datetime.strptime(text, form)
        except ValueError:
            continue
        zone = None if lokal else timezone.utc
        return wann.replace(tzinfo=zone).timestamp()
    raise argparse.ArgumentTypeError(
        f"cannot read time {text!r}; try 2026-08-29T06:00 or 29.08.2026 06:00")


def zeige(ts):
    return (datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
            + datetime.fromtimestamp(ts).strftime("  (local %H:%M:%S)"))


def oeffne_port(link):
    """A pty in raw mode, so nothing rewrites the bytes on the way out."""
    haupt, neben = os.openpty()
    tty.setraw(neben, termios.TCSANOW)
    # Non-blocking: a real serial line drops bytes when nobody listens, it
    # does not stall the sender. Keeping the slave open on our side stops
    # the master from erroring out between readers.
    os.set_blocking(haupt, False)
    name = os.ttyname(neben)
    if link:
        pfad = Path(link)
        if pfad.is_symlink() or pfad.exists():
            pfad.unlink()
        pfad.symlink_to(name)
    return haupt, neben, name


def main():
    zerleger = argparse.ArgumentParser(
        description="Replay recorded AIS/GPS archives onto a virtual serial port.")
    zerleger.add_argument("start", nargs="?",
                          help="where to start in the recording, e.g. "
                               "2026-08-29T06:00; omit with --list")
    zerleger.add_argument("--until", help="stop here instead of at the end")
    zerleger.add_argument("--tempo", type=float, default=1.0,
                          help="speed factor, 1.0 = real time")
    zerleger.add_argument("--max-gap", default="60",
                          help="compress idle stretches longer than this many "
                               "seconds; 'keep' reproduces them in full")
    zerleger.add_argument("--link", help="symlink this path to the pty")
    zerleger.add_argument("--local", action="store_true",
                          help="read the given times as local time, not UTC")
    zerleger.add_argument("--list", action="store_true",
                          help="show what the archives cover, then exit")
    zerleger.add_argument("--quiet", action="store_true",
                          help="no progress line")
    argumente = zerleger.parse_args()

    if argumente.tempo <= 0:
        zerleger.error("--tempo must be positive")
    hoechstluecke = (float("inf") if argumente.max_gap == "keep"
                     else float(argumente.max_gap))

    dateien = sammle_dateien(config.DATA_DIR)
    if not dateien:
        print(f"no .nm4 archives under {config.DATA_DIR}", file=sys.stderr)
        return 1

    if argumente.list:
        print(f"{len(dateien)} archive files, "
              f"{zeige(dateien[0].start)} .. {zeige(dateien[-1].ende)}")
        vorige = None
        for datei in dateien:
            hinweis = f"  clock {datei.versatz / 3600:+.1f} h" if datei.versatz else ""
            luecke = ""
            if vorige is not None and datei.start - vorige > 3600:
                luecke = f"   <- gap {(datei.start - vorige) / 3600:.1f} h"
            print(f"  {datei.pfad.name:24s} "
                  f"{datetime.fromtimestamp(datei.start, timezone.utc):%d.%m. %H:%M} - "
                  f"{datetime.fromtimestamp(datei.ende, timezone.utc):%d.%m. %H:%M}"
                  f"{hinweis}{luecke}")
            vorige = datei.ende
        return 0

    if not argumente.start:
        zerleger.error("a start time is required (or use --list)")

    try:
        ab = lies_zeit(argumente.start, argumente.local)
        bis = lies_zeit(argumente.until, argumente.local) if argumente.until else None
    except argparse.ArgumentTypeError as fehler:
        zerleger.error(str(fehler))
    if ab > dateien[-1].ende or (bis is not None and bis < dateien[0].start):
        print(f"nothing recorded in that range; archives cover\n"
              f"  {zeige(dateien[0].start)}\n  .. {zeige(dateien[-1].ende)}",
              file=sys.stderr)
        return 1

    signal.signal(signal.SIGINT, _stopp)
    signal.signal(signal.SIGTERM, _stopp)

    haupt, neben, name = oeffne_port(argumente.link)
    print(f"port    : {name}" + (f"  -> {argumente.link}" if argumente.link else ""),
          file=sys.stderr)
    print(f"start   : {zeige(ab)}", file=sys.stderr)
    if bis is not None:
        print(f"until   : {zeige(bis)}", file=sys.stderr)
    print(f"tempo   : {argumente.tempo:g}x"
          + ("" if hoechstluecke == float("inf")
             else f", gaps over {hoechstluecke:g}s compressed"), file=sys.stderr)
    print(f"reader  : AIS_SET_CLOCK=0 AIS_DEVICE={argumente.link or name} "
          f"python -m ais_logger.run_logger", file=sys.stderr)
    print("warning : without AIS_SET_CLOCK=0 the reader will step the system "
          "clock back to the recording", file=sys.stderr)

    gesendet = verworfen = 0
    uebersprungen = 0.0
    vorige_ts = None
    uhr0 = time.monotonic()
    naechste_meldung = uhr0 + 1.0
    letzte_ts = ab

    try:
        for ts, satz in saetze(dateien, ab, bis):
            if not _laeuft:
                break
            if vorige_ts is not None:
                luecke = ts - vorige_ts
                if luecke > hoechstluecke:
                    uebersprungen += luecke - hoechstluecke
                    if not argumente.quiet:
                        print(f"\r[gap] {luecke / 3600:.1f} h skipped at "
                              f"{datetime.fromtimestamp(vorige_ts, timezone.utc):%d.%m. %H:%M}"
                              f"{' ' * 20}", file=sys.stderr)
            vorige_ts = ts
            letzte_ts = ts

            faellig = (ts - ab - uebersprungen) / argumente.tempo
            warten = faellig - (time.monotonic() - uhr0)
            if warten > 0:
                time.sleep(warten)

            roh = (satz + "\r\n").encode("ascii", errors="replace")
            try:
                geschrieben = os.write(haupt, roh)
                if geschrieben < len(roh):
                    verworfen += 1
                else:
                    gesendet += 1
            except OSError as fehler:
                if fehler.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EIO):
                    verworfen += 1
                else:
                    raise

            jetzt = time.monotonic()
            if not argumente.quiet and jetzt >= naechste_meldung:
                naechste_meldung = jetzt + 1.0
                print(f"\r{datetime.fromtimestamp(ts, timezone.utc):%d.%m. %H:%M:%S} UTC"
                      f"   sent {gesendet}   dropped {verworfen}"
                      f"   {gesendet / max(jetzt - uhr0, 1e-9):5.1f}/s ",
                      end="", file=sys.stderr, flush=True)
    finally:
        if not argumente.quiet:
            print(file=sys.stderr)
        print(f"stopped at {zeige(letzte_ts)}", file=sys.stderr)
        print(f"sent {gesendet} sentences, dropped {verworfen}", file=sys.stderr)
        if verworfen:
            anteil = verworfen / max(gesendet + verworfen, 1) * 100
            print(f"          {anteil:.0f}% lost -- either nothing was reading "
                  f"the port, or --tempo {argumente.tempo:g} outran the reader",
                  file=sys.stderr)
        os.close(haupt)
        os.close(neben)
        if argumente.link:
            pfad = Path(argumente.link)
            if pfad.is_symlink():
                pfad.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
