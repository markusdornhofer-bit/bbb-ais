# Installation

Vollständige Einrichtung des AIS-Loggers samt Karte auf einem BeagleBone
Black. Für den Umzug einer bestehenden Installation auf einen anderen
Rechner siehe [PORTING.md](PORTING.md), für den laufenden Betrieb
[README.md](README.md).

Geprüft am 30.08.2026 auf: Debian 13 (trixie), Kernel 6.19.13-bone16
armv7l, Python 3.13.5, Seanexx-AIS/GPS-USB-Stick.

---

## 1. Voraussetzungen

| | |
|---|---|
| Hardware | BeagleBone Black (oder ein anderer Linux-Rechner) |
| | AIS/GPS-USB-Stick, meldet sich als `/dev/ttyACM0` |
| | UKW-Antenne, siehe Abschnitt 9 |
| Software | Python **3.9 oder neuer** (`pyais` verlangt das) |
| | `python3-venv` |

Es wird **kein Compiler und kein Rust-Toolchain** gebraucht – alle
Abhängigkeiten sind reines Python. Das war der Grund, `aisdb` nicht als
Kernabhängigkeit zu verwenden (Begründung in `README.md`).

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
python3 --version
```

---

## 2. Dateien aufs Gerät bringen

Zu übertragen sind:

```
ais_logger/   tools/   webmap/   systemd/
requirements.txt   README.md   PORTING.md   INSTALL.md   CLAUDE.md
sibenik_archipel.mbtiles                      # Kartengrundlage, 9,4 MB
```

**Nicht** übertragen: `data/` (Messdaten) und `.venv/` (enthält absolute
Pfade und für die jeweilige Architektur gebaute Dateien).

Von einem anderen Rechner aus:

```bash
rsync -av --exclude='.venv' --exclude='data' --exclude='__pycache__' \
      ./ debian@<beaglebone>:~/bbb/
```

Der Rest dieser Anleitung geht davon aus, dass das Projekt unter `~/bbb`
liegt und der Benutzer `debian` heißt. Andere Pfade oder Benutzernamen
müssen in den systemd-Units angepasst werden (Abschnitt 6).

---

## 3. Python-Umgebung

```bash
cd ~/bbb
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Kontrolle – erwartet werden `pyserial`, `pynmea2` und `pyais`:

```bash
.venv/bin/pip list | grep -iE 'pyais|pynmea2|pyserial'
```

---

## 4. Zugriff auf den seriellen Port

Der Port gehört der Gruppe `dialout`:

```bash
ls -l /dev/ttyACM0        # crw-rw---- root dialout
sudo usermod -aG dialout $USER
```

**Danach neu anmelden**, sonst ist die Gruppenmitgliedschaft nicht aktiv.
Prüfen mit `id -nG` – `dialout` muss in der Liste stehen.

Fehlt die Gruppe, scheitert das Öffnen des Ports später mit
`Permission denied`.

---

## 5. Installation ohne Hardware prüfen

Der Selbsttest schickt einen aufgezeichneten NMEA-Datenstrom durch den
echten Reader und prüft die komplette Kette: Einlesen, AIS-Decodierung
inklusive mehrteiliger Nachrichten, GPS-Auswertung, Datenbank und
Rohdatenarchiv.

```bash
cd ~/bbb && .venv/bin/python tools/selftest.py
```

Erwartete letzte Zeile: **`SELFTEST PASSED`**. Schlägt er fehl, lohnt das
Anschließen der Hardware noch nicht.

Der Test setzt intern `AIS_SET_CLOCK=0`. Sein Datenstrom enthält echte
RMC-Sätze; ohne diese Sperre würde er auf dem BeagleBone die Systemuhr
tatsächlich verstellen.

---

## 6. Hardware anschließen und ausprobieren

Stick anstecken, dann der minimale Lesetest – er öffnet den Port genau
einmal, ohne Datenbank:

```bash
.venv/bin/python -m ais_logger.diag /dev/ttyACM0 4800
```

Es müssen NMEA-Zeilen erscheinen (`$GNRMC…`, gelegentlich `!AIVDM…`).

> **Falle: Port erkennen lassen oder nicht.**
> `ais_logger.serial_finder` probiert Ports und Baudraten durch, indem es
> sie öffnet, liest und wieder schließt. Bei CDC-ACM-Geräten wie diesem
> Stick bringt genau dieser Zyklus das Gerät dazu, nichts mehr zu senden –
> der Port ist dann offen, aber es kommen keine Daten. **Sind Gerät und
> Baudrate bekannt, immer fest vorgeben**; der Code überspringt die Suche
> dann vollständig. Die mitgelieferte Unit tut das bereits.

Kurzer Dauerlauf von Hand:

```bash
AIS_DEVICE=/dev/ttyACM0 AIS_BAUD=4800 AIS_HEARTBEAT_SECONDS=10 \
  .venv/bin/python -m ais_logger.run_logger
```

Erwartet:

```
[reader] opening /dev/ttyACM0 @ 4800 ...
[reader] port open, waiting for data
[clock] stepped system clock by +… to …  (nur beim ersten Mal)
[gps] 2026-08-30T…+00:00 (fix)
[reader] alive: 412 lines (8 AIS, 400 GPS, 0 other, 0 AIS rejected, 0 filtered)
```

Mit `Strg+C` beenden.

---

## 7. Dauerbetrieb per systemd

```bash
sudo cp ~/bbb/systemd/ais-logger.service ~/bbb/systemd/ais-map.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ais-logger.service ais-map.service
```

Bei abweichendem Pfad oder Benutzer vorher anpassen:

```bash
sed -i "s|/home/debian/bbb|$HOME/bbb|g; s|^User=debian|User=$USER|" \
    ~/bbb/systemd/*.service
```

> **Falle: `AmbientCapabilities` nicht verlieren.**
> `ais-logger.service` enthält `AmbientCapabilities=CAP_SYS_TIME` und
> `CapabilityBoundingSet=CAP_SYS_TIME`. Der BeagleBone hat keine gepufferte
> Echtzeituhr; ohne dieses Recht kann der Logger die Systemuhr nicht aus
> der GPS-Zeit stellen und **alle Zeitstempel im Archiv sind falsch** – am
> 28.08.2026 waren es zwei Tage. Es wird genau diese eine Berechtigung
> erteilt, der Dienst läuft weiter als unprivilegierter Benutzer. Fehlt
> sie, steht einmalig eine Warnung im Journal.

> **Falle: Unit-Datei nach jeder Änderung neu installieren.**
> Das Bearbeiten von `~/bbb/systemd/*.service` wirkt nicht – systemd liest
> `/etc/systemd/system/`. Nach jeder Änderung erneut `cp`, dann
> `daemon-reload`, dann `restart`.

> **Rohdaten werden nicht automatisch gelöscht.** Die mitgelieferte
> `ais-logger.service` setzt `AIS_RAW_RETENTION_DAYS=0`. Wer den Logger
> monatelang unbeaufsichtigt laufen lässt, sollte den Wert auf eine
> Tageszahl setzen – sonst füllt sich die Platte mit rund 45 MB pro Tag.

`ais-ingest.service` und `.timer` sind **optional** und standardmäßig nicht
installiert. Sie lesen abgeschlossene Rohdatenarchive nachträglich in die
Datenbank ein – nur nötig, wenn der Reader zeitweise ausfiel, die
Rohaufzeichnung aber weiterlief. Vorsicht: der Timer holt auch alte Archive
mit falschen Zeitstempeln zurück in eine bereinigte Datenbank.

---

## 8. Karte

Der Kartendienst braucht keine eigene Einrichtung. Beim Start sucht er im
Projektordner nach einer `.mbtiles`-Datei und lädt die erste gefundene.

```bash
systemctl status ais-map.service
ls -lh ~/bbb/*.mbtiles      # sibenik_archipel.mbtiles, 9,4 MB
journalctl -u ais-map.service -n 5 --no-pager | grep 'base map ready'
```

Das Einlesen der Kacheln dauert auf dem BeagleBone rund 13 Sekunden; so
lange antwortet der Dienst noch nicht. Einen eigenen Ausschnitt erzeugen:
siehe Abschnitt *Kartengrundlage* in [README.md](README.md).

Dann im Browser `http://<beaglebone-ip>:8080/` öffnen.

Bedienung, Farbgebung, Vorhersagepfade, Wiedergabe und alle
Umgebungsvariablen stehen in [README.md](README.md).

---

## 9. Antenne

Der wirksamste Hebel für dieses Projekt, und der einzige Punkt, den keine
Software behebt. AIS ist maritimer UKW-Funk auf 162 MHz mit Sichtweite.

| Bauform | gebaute Länge |
|---|---|
| Viertelwelle (braucht 4 Radials) | 44 cm |
| **Halbwellen-Dipol** (kein Gegengewicht) | 2 × 44 cm |
| 5/8 Welle | 110 cm |

Senkrecht montieren – AIS ist vertikal polarisiert, waagerecht kostet rund
20 dB. Nach draußen und möglichst hoch: eine gute Antenne hinter einer
Hauswand ist schlechter als eine mittelmäßige im Freien. Kabel kurz halten,
RG58 verliert etwa 0,2 dB pro Meter.

Zur Einordnung: eine intakte Anlage empfängt Klasse A auf 15–20 nm, Klasse
B auf 5–10 nm. Am 28.08.2026 endete hier **jede** Meldung unter 1 nm, nach
einer Antennenänderung am 29.08. reichte es bis 2,22 nm.

---

## 10. Abnahme

Nach der Einrichtung sollte alles davon zutreffen:

```bash
# Dienste laufen
systemctl is-active ais-logger.service ais-map.service     # 2x active

# Uhr stimmt (mit einem bekannt richtigen Rechner vergleichen)
date -u '+%Y-%m-%d %H:%M:%S UTC'

# der Logger hat das Recht, sie zu stellen
systemctl show -p AmbientCapabilities --value ais-logger.service   # cap_sys_time

# Zeilen in der Datenbank
cd ~/bbb && ./query.sh                  # AIS: (2217,)  own_position: (2699,)

# GPS liefert Positionen
cd ~/bbb && .venv/bin/python -c "
import sqlite3
c = sqlite3.connect('data/aisdb.sqlite')
for r in c.execute('''SELECT datetime(ts_unix,"unixepoch"), lat, lon
                      FROM own_position ORDER BY ts_unix DESC LIMIT 3'''):
    print(r)"

# die Karte antwortet
curl -s http://127.0.0.1:8080/api/live | head -c 200
```

Das Kommandozeilenwerkzeug `sqlite3` ist auf dem BeagleBone-Image **nicht**
installiert – deshalb hier überall der Umweg über Python, das SQLite in der
Standardbibliothek mitbringt. Wer es lieber direkt hat:
`sudo apt-get install sqlite3`.

---

## 11. Wenn etwas nicht geht

| Symptom | Ursache und Abhilfe |
|---|---|
| `Permission denied` am Port | Benutzer nicht in `dialout`, oder nach `usermod` nicht neu angemeldet |
| Port offen, aber keine Daten | Die Portsuche hat das CDC-ACM-Gerät gestört. `AIS_DEVICE` und `AIS_BAUD` fest setzen, dann wird nicht mehr gesucht |
| Port belegt | `gpsd` oder `ModemManager` greifen automatisch auf neu angesteckte serielle Geräte zu. Prüfen mit `sudo fuser -v /dev/ttyACM0` |
| Zeitstempel um Tage daneben | `CAP_SYS_TIME` fehlt in der installierten Unit, oder `AIS_SET_CLOCK=0` ist gesetzt. Journal zeigt einmalig `[clock] cannot set system clock` |
| Karte bleibt leer | Meist kein Verkehr in Reichweite, nicht defekt. Das HUD schreibt das Zeitfenster neben die Schiffszahl. Empfang gegenprüfen: `grep -c '!AIVDM' ~/bbb/data/raw/*.nm4` |
| Karte lädt gar nicht | `journalctl -u ais-map.service -n 30`; fehlt die `.mbtiles`, steht dort `no .mbtiles found` |
| Gerätepfad wechselt nach Neustart | Aus `/dev/ttyACM0` kann `/dev/ttyACM1` werden. Für Dauerbetrieb eine udev-Regel mit festem Aliasnamen anlegen (`udevadm info -a -n /dev/ttyACM0`) |

Laufende Ausgabe verfolgen:

```bash
journalctl -u ais-logger.service -f
```
