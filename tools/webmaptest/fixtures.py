"""Erzeugt die Testdaten fuer die Kartenpruefungen aus der echten Kartendatei
und, falls vorhanden, der Datenbank. Ohne Datenbank wird eine kuenstliche
Aufzeichnung geschrieben, damit die Suiten auch auf einem Rechner ohne
Messdaten laufen."""
import json
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent.parent))

from webmap.tiles import find_mbtiles, load_basemap  # noqa: E402
from ais_logger import config  # noqa: E402


def main():
    mb = find_mbtiles([config.BASE_DIR, config.DATA_DIR])
    if not mb:
        raise SystemExit("keine .mbtiles gefunden")
    bm = load_basemap(mb)
    (HIER / "basemap.json").write_text(json.dumps(bm["layers"]))

    tage, hist = [], {"from": 0, "to": 86400, "ships": [], "names": {}, "own": []}
    db = Path(config.DB_PATH)
    if db.exists():
        from webmap.server import _query_days, _query_history
        import datetime as dt
        tage = _query_days()
        if tage:
            st = dt.datetime.strptime(tage[0]["date"], "%Y-%m-%d").replace(
                tzinfo=dt.timezone.utc)
            hist = _query_history(int(st.timestamp()), int(st.timestamp()) + 86400)
    if not tage:
        tage = [{"date": "2026-08-30", "messages": 0, "ships": 0}]
    (HIER / "hist.json").write_text(json.dumps(hist))
    (HIER / "days.json").write_text(json.dumps(tage))
    print(f"Testdaten: {len(bm['layers'])} Ebenen, {len(hist['ships'])} Meldungen, "
          f"{len(tage)} Tage")


if __name__ == "__main__":
    main()
