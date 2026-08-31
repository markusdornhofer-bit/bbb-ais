# Projekt auf einen anderen Rechner portieren

Diese Anleitung beschreibt, wie das AIS-Logger-Projekt auf einen anderen
Rechner übertragen und dort in Betrieb genommen wird – egal ob ein weiterer
BeagleBone/Raspberry Pi, ein Linux-PC, ein Windows-PC oder ein Mac.

Das Projekt ist reines Python ohne kompilierte Abhängigkeiten und läuft
plattformübergreifend. Nur die Gerätebezeichnung des seriellen Ports und der
Autostart unterscheiden sich je nach Betriebssystem.

## 1. Was übertragen werden muss

| Verzeichnis / Datei | Übertragen? | Bemerkung |
|---|---|---|
| `ais_logger/` | **ja** | der gesamte Programmcode |
| `tools/` | **ja** | Selbsttest ohne Hardware |
| `systemd/` | ja (nur Linux) | Unit-Dateien, Pfade müssen angepasst werden |
| `requirements.txt` | **ja** | Abhängigkeiten |
| `README.md`, `PORTING.md` | ja | Doku |
| `data/` | **nein** | Messdaten + Datenbank, siehe Abschnitt 7 |
| `.venv/` | **nein** | enthält plattformspezifische Binärdateien, wird neu erzeugt |

## 2. Übertragen

**Variante A – Git (empfohlen)**, wenn ihr das Projekt versioniert:

```bash
git clone <euer-repo-url> bbb && cd bbb
```

Ein `.gitignore` ist bereits vorhanden und schließt `data/`, `.venv/` und
`__pycache__/` aus.

**Variante B – direkt kopieren (Linux/Mac):**

```bash
rsync -av --exclude='.venv' --exclude='data' --exclude='__pycache__' ~/bbb/ user@zielrechner:~/bbb/
```

**Variante C – von Windows aus:**

```bash
scp -r "C:\2026\claude\bbb\ais_logger" "C:\2026\claude\bbb\tools" "C:\2026\claude\bbb\systemd" "C:\2026\claude\bbb\requirements.txt" user@zielrechner:~/bbb/
```

## 3. Voraussetzungen

- **Python 3.9 oder neuer** (`pyais` verlangt mindestens 3.9)
- Abhängigkeiten laut `requirements.txt`: `pyserial`, `pynmea2`, `pyais` –
  alle reines Python, es wird **kein** Compiler und kein Rust-Toolchain
  benötigt (das war der Grund, `aisdb` nicht als Kernabhängigkeit zu
  verwenden, siehe `README.md`).

Python-Version prüfen:

```bash
python3 --version
```

## 4. Einrichten

**Linux / macOS:**

```bash
cd ~/bbb && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
cd C:\pfad\zu\bbb; python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

Auf **Linux** zusätzlich den Benutzer für den seriellen Port berechtigen:

```bash
sudo usermod -aG dialout $USER
```

Danach neu anmelden, damit die Gruppenmitgliedschaft aktiv wird. Auf Windows
und macOS ist das nicht nötig.

## 5. Installation ohne Hardware prüfen

Bevor ihr den Stick anschließt, verifiziert der Selbsttest die komplette
Verarbeitungskette (Einlesen, AIS-Decodierung inkl. mehrteiliger
Nachrichten, GPS-Auswertung, Datenbank, Rohdaten-Archiv) mit einem
simulierten Datenstrom:

```bash
python tools/selftest.py
```

Erwartete Ausgabe am Ende: `SELFTEST PASSED`. Schlägt er fehl, stimmt etwas
an der Installation nicht – dann lohnt sich das Anschließen der Hardware
noch nicht.

## 6. Serielle Schnittstelle auf dem neuen Rechner

Die Gerätebezeichnung ist plattformabhängig:

| System | typische Bezeichnung |
|---|---|
| Linux | `/dev/ttyACM0` oder `/dev/ttyUSB0` |
| macOS | `/dev/tty.usbmodem*` oder `/dev/tty.usbserial*` |
| Windows | `COM3`, `COM4`, … |

Verfügbare Ports auflisten:

```bash
python -c "import serial.tools.list_ports as p; [print(x.device, '|', x.description) for x in p.comports()]"
```

Automatische Erkennung testen:

```bash
python -m ais_logger.serial_finder
```

Wenn ihr Gerät und Baudrate kennt, setzt sie besser explizit – dann wird
die Port-Suche komplett übersprungen (sie öffnet und schließt den Port
sonst kurz zum Testen, was manche USB-Geräte aus dem Tritt bringt):

```bash
export AIS_DEVICE=/dev/ttyACM0   # Windows: set AIS_DEVICE=COM3
export AIS_BAUD=4800
```

Minimaler Lesetest (öffnet den Port genau einmal, ohne Datenbank):

```bash
python -m ais_logger.diag /dev/ttyACM0 4800
```

Dann der eigentliche Logger:

```bash
python -m ais_logger.run_logger
```

## 7. Vorhandene Messdaten mitnehmen (optional)

Die Datenbank ist eine einzelne SQLite-Datei unter `data/aisdb.sqlite`.
Sie läuft im WAL-Modus, es gehören also bis zu drei Dateien zusammen:
`aisdb.sqlite`, `aisdb.sqlite-wal` und `aisdb.sqlite-shm`.

**Logger vorher stoppen**, sonst kopiert ihr einen inkonsistenten Stand.
Am saubersten ist eine konsolidierte Kopie – die schreibt alles in eine
einzige Datei ohne WAL-Beiwerk:

```bash
python -c "import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute('VACUUM INTO ?', (sys.argv[2],))" data/aisdb.sqlite aisdb_backup.sqlite
```

Die entstandene `aisdb_backup.sqlite` könnt ihr gefahrlos kopieren und auf
dem Zielrechner als `data/aisdb.sqlite` ablegen. Die Rohdaten-Archive unter
`data/raw/` und `data/processed/` sind normale Textdateien und lassen sich
einfach mitkopieren; aus ihnen kann die Datenbank mit
`python -m ais_logger.run_ingest` jederzeit neu aufgebaut werden.

## 8. Konfiguration (Umgebungsvariablen)

Alle Einstellungen laufen über Umgebungsvariablen, es gibt keine zu
bearbeitende Konfigurationsdatei:

| Variable | Standard | Zweck |
|---|---|---|
| `AIS_DEVICE` | (automatische Suche) | seriellen Port fest vorgeben |
| `AIS_BAUD` | `4800` | Baudrate |
| `AIS_DATA_DIR` | `<projekt>/data` | Ablageort für Datenbank + Rohdaten |
| `AIS_DB_PATH` | `<AIS_DATA_DIR>/aisdb.sqlite` | Pfad der SQLite-Datei |
| `AIS_SOURCE_LABEL` | `SEANEXX` | Quellkennung in Datenbank und Archiv |
| `AIS_ROTATE_MINUTES` | `60` | Rotationsintervall der Archivdateien |
| `AIS_DEBUG` | (aus) | `1` gibt jede empfangene Rohzeile aus |
| `AIS_HEARTBEAT_SECONDS` | `10` | Statuszeile mit Zählern; `0` schaltet sie ab |

Damit lässt sich das Projekt auch mehrfach parallel betreiben (z. B. zwei
Empfänger), indem pro Instanz ein eigenes `AIS_DATA_DIR` und `AIS_DEVICE`
gesetzt wird.

## 9. Automatischer Start

**Linux mit systemd:** Die Unit-Dateien in `systemd/` enthalten fest
eingetragene Pfade (`/home/debian/bbb`) und den Benutzer `debian`. Beides
auf dem neuen Rechner anpassen:

```bash
sed -i "s|/home/debian/bbb|$HOME/bbb|g; s|^User=debian|User=$USER|" systemd/*.service
```

```bash
sudo cp systemd/ais-logger.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now ais-logger.service
```

Falls ihr `AIS_DEVICE`/`AIS_BAUD` fest setzen wollt, ergänzt in der
`.service`-Datei im Abschnitt `[Service]`:

```ini
Environment=AIS_DEVICE=/dev/ttyACM0
Environment=AIS_BAUD=4800
```

**Windows:** systemd gibt es dort nicht. Am einfachsten über die
Aufgabenplanung eine Aufgabe „Beim Start ausführen“ anlegen, die
`C:\pfad\zu\bbb\.venv\Scripts\python.exe -m ais_logger.run_logger` im
Arbeitsverzeichnis `C:\pfad\zu\bbb` startet. Für einen echten
Windows-Dienst eignet sich zusätzlich [NSSM](https://nssm.cc/).

**macOS:** über einen `launchd`-Eintrag in
`~/Library/LaunchAgents/`.

## 10. Stolperfallen

- **`.venv` niemals mitkopieren.** Sie enthält absolute Pfade und für die
  jeweilige Architektur gebaute Dateien; auf einem anderen Rechner (erst
  recht bei Wechsel zwischen ARM und x86) funktioniert sie nicht. Immer neu
  anlegen.
- **Rechte auf den seriellen Port.** Unter Linux führt eine fehlende
  `dialout`-Mitgliedschaft zu `Permission denied` beim Öffnen des Ports.
- **Gerätepfade sind nicht stabil.** Unter Linux kann aus `/dev/ttyACM0`
  nach einem Neustart oder Umstecken `/dev/ttyACM1` werden. Für den
  Dauerbetrieb empfiehlt sich eine udev-Regel mit einem festen Aliasnamen
  (`udevadm info -a -n /dev/ttyACM0` zeigt die passenden Attribute).
- **Konkurrierende Programme.** Unter Linux greifen `gpsd` oder
  `ModemManager` gelegentlich automatisch auf neu angesteckte serielle
  Geräte zu und blockieren sie. Prüfen mit `sudo fuser -v /dev/ttyACM0`.
- **Zeitstempel.** Der Logger schreibt Unix-Zeitstempel aus der Systemuhr.
  Ein Rechner ohne Netzwerk und ohne Echtzeituhr (wie der BeagleBone) hat
  nach dem Einschalten eine falsche Uhrzeit. Der Logger korrigiert das
  selbst aus der GPS-Zeit (`ais_logger/gps_clock.py`, siehe `README.md`),
  braucht dafür aber `CAP_SYS_TIME`:
  - **Linux mit systemd:** die mitgelieferte Unit erteilt das Recht bereits.
    Beim Übernehmen einer eigenen Unit die beiden `*Capabilities`-Zeilen
    mitnehmen.
  - **Linux ohne systemd:** entweder als root starten oder
    `setcap cap_sys_time+ep` auf das Python-Binary – Letzteres wirkt auf
    *alle* Python-Programme des Rechners, also lieber die Unit-Variante.
  - **Windows und macOS:** funktioniert nicht. Der Versuch scheitert mit
    einer einmaligen Warnung im Log, sonst läuft alles normal weiter. Dort
    einfach NTP verwenden und mit `AIS_SET_CLOCK=0` Ruhe geben.

## 11. Stand der Verifizierung

Auf einem Windows-Entwicklungsrechner geprüft (ohne AIS-Hardware):
Selbsttest, AIS-Decodierung gegen echte Referenzdaten, GPS-Auswertung,
Datenbankzugriff sowie die plattformübergreifenden Bestandteile
(Signalbehandlung, Port-Auflistung).

Auf dem BeagleBone geprüft: Installation, Port-Erkennung
(`/dev/ttyACM0` @ 4800) und Empfang von GPS-Sätzen über
`ais_logger.serial_finder`.

Auf dem BeagleBone im Betrieb bestätigt: Empfang über `/dev/ttyACM0` bei
4800 Baud, gültige GPS-Positionen in der Datenbank. Das frühere Problem
(„Port offen, aber keine Daten") ist behoben.

**Noch offen:** Der Betrieb mit echten AIS-Daten. Am bisherigen Standort im
Binnenland ist AIS-Empfang physikalisch unmöglich; die Plausibilitätsprüfung
und die Kartendarstellung sind daher bisher nur mit Referenz- und
Simulationsdaten geprüft, nicht mit echtem Schiffsverkehr.
