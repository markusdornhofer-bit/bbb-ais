# Projektkontext für Claude

AIS-Logger auf einem BeagleBone Black: liest einen Seanexx-AIS/GPS-USB-Stick
aus und speichert AIS-Nachrichten und die eigene GPS-Position in einer
SQLite-Datenbank. Benutzersprache ist Deutsch.

Ausführliche Doku: `README.md` (Betrieb), `PORTING.md` (Umzug auf andere
Rechner).

## Hardware / Umgebung

- BeagleBone Black, Debian, Netzwerk über `systemd-networkd`
- Stick meldet sich als `/dev/ttyACM0`, **4800 Baud** (bestätigt auf der
  Hardware; als Standard in `ais_logger/config.py` gesetzt)
- Der Stick liefert AIS (`!AIVDM`) **und** GPS-Sätze (`$GNRMC`, `$GNGSA`,
  `$GPGSV`, …) im selben Datenstrom
- Entwickelt und getestet wird zusätzlich auf einem Windows-Rechner ohne
  angeschlossene Hardware

## Architekturentscheidungen

- **AIS-Decodierung über `pyais`, nicht über `aisdb`.** Ursprünglich war
  `aisdb` (AISViz/Dalhousie) vorgesehen. Getestet mit Version 1.7.2:
  `aisdb.decode_msgs` schreibt **null Zeilen** in die Zieltabelle, auch mit
  den offiziellen Testdaten des Pakets selbst. `pyais` decodiert dieselben
  Daten korrekt (verifiziert: 979 Nachrichten, 843 MMSIs). `pyais` ist
  zudem reines Python – kein Rust-Toolchain auf ARM nötig. Diese
  Entscheidung nicht ohne erneute Prüfung zurückdrehen.
- Rohdaten werden trotzdem im **aisdb-kompatiblen `.nm4`-Format** mit
  Tagblock archiviert (`data/raw/`), damit die aisdb-Analysewerkzeuge
  später nutzbar bleiben.
- **Reader und Ingest sind getrennt**: der Reader decodiert live, `ingest`
  ist nur ein Nachbearbeitungs-/Wiederherstellungswerkzeug für archivierte
  Rohdaten.
- Konfiguration ausschließlich über Umgebungsvariablen (`AIS_*`), keine
  Konfigurationsdatei. Tabelle in `README.md`.
- **Die GPS-Zeit stellt die Systemuhr**, nicht nur die Datenbankspalten
  (`ais_logger/gps_clock.py`). Journal, Rotation des Roharchivs und die
  Altersberechnung der Karte lesen alle die Systemuhr – eine nur teilweise
  korrigierte Zeit wäre schlimmer als eine durchgehend falsche. Das Recht
  dazu kommt über `AmbientCapabilities=CAP_SYS_TIME` in der systemd-Unit,
  der Dienst bleibt unprivilegiert. `os.clock_settime` fehlt im
  Python-Build von Debian Trixie, deshalb libc über `ctypes`.
- **Der Selbsttest muss `AIS_SET_CLOCK=0` setzen.** Sein Datenstrom enthält
  echte RMC-Sätze; auf dem BeagleBone würde er sonst die Uhr wirklich
  verstellen.

## Befehle

```bash
python tools/selftest.py                      # Prüfung ohne Hardware
python -m ais_logger.diag /dev/ttyACM0 4800   # minimaler Lesetest am Port
python -m ais_logger.serial_finder            # Port-/Baudraten-Erkennung
python -m ais_logger.run_logger               # Dauerbetrieb
python -m ais_logger.run_ingest               # Rohdaten nachträglich einlesen
python -m webmap.server                       # Karte auf Port 8080
```

Nützliche Variablen beim Debuggen: `AIS_DEVICE=/dev/ttyACM0`, `AIS_DEBUG=1`
(gibt jede Rohzeile aus), `AIS_HEARTBEAT_SECONDS`.

## Arbeitsweise in diesem Projekt

- Änderungen möglichst **verifizieren, bevor sie als fertig gemeldet
  werden** – der Selbsttest bzw. eine Simulation mit gefälschtem seriellen
  Port ersetzt die fehlende Hardware auf dem Entwicklungsrechner.
- Auf dem BeagleBone wird von Hand per `scp` übertragen; der Benutzer führt
  die Befehle auf dem Gerät selbst aus und schickt die Ausgabe zurück.
- Nicht Getestetes klar als solches benennen.

## Karte (`webmap/`)

Offline-Seekarte im Browser, Port 8080, zeigt empfangene Schiffe und die
eigene Position live an. Kartengrundlage ist eine `.mbtiles`-Datei mit
**Vektorkacheln im Shortbread-Schema**.

Seit 30.08.2026 ist `data/sibenik_archipel.mbtiles` in Betrieb: 34,8 × 36,0
nm statt der ursprünglichen 5,9 × 4,8 nm, mit planetiler und dessen
`samples/shortbread.yml` selbst erzeugt (Befehl in `README.md`). Das alte
ZIP im Projektordner wird nicht mehr angefasst, weil `find_mbtiles` zuerst
`data/` durchsucht.

**Die Ebenenauswahl ist hier eine Leistungsfrage, keine Geschmacksfrage.**
Auf dem großen Blatt wurde gemessen (BeagleBone, Zoom 14, ganzes Blatt):

| Ebenen | Objekte | Dekodierung |
|---|---|---|
| alle | 51 667 | 89,6 s |
| ohne `streets`, `land`, `buildings` | 4 123 | 12,7 s |

Diese drei sind 92 % der Datenmenge und sagen nichts über Schiffe: die
Küstenlinie kommt aus `ocean`, Land ist schlicht der Hintergrund, auf den
der Ozean gemalt wird. `decode_tile(data, wanted)` überspringt sie deshalb
schon beim Lesen, bevor Geometrie dekodiert wird. Wer Ebenen wieder
aufnimmt, muss die Startzeit neu messen.

Bewusst **ohne Kartenbibliothek**: Der Server decodiert die Vektorkacheln
selbst (`webmap/mvt.py`, handgeschriebener MVT-/Protobuf-Leser ohne
Fremdabhängigkeit) und schickt fertige Geometrie an den Browser, der sie
auf einem Canvas zeichnet. Grund: MapLibre GL wäre offline mit Stildatei
und Schriften fragil, und der BeagleBone soll keine Zusatzpakete brauchen.

Zwei Fallstricke, die schon Fehler verursacht haben – nicht erneut
hineinlaufen:

1. **Shortbread hat keine Landmassen-Ebene.** Der Hintergrund *ist* das
   Land, die `ocean`-Polygone werden darauf gezeichnet. Die Ebene `land`
   enthält nur Bodenbedeckung (Wald, Strand, Obstplantage …). Umgekehrt
   gezeichnet sehen Land und Meer identisch aus.

   **Daraus folgt: eine Insel ist ein Loch im Ozean-Polygon.** Alle Ringe
   eines Polygons müssen deshalb in *einen* Pfad und mit *einem* `fill()`
   gezeichnet werden (`fillPolygon()`), damit die Nonzero-Regel die Löcher
   ausstanzt. Ring für Ring zu füllen übermalt die Inseln in Meerfarbe –
   genau dieser Fehler hat am 28.08.2026 vier Inseln verschwinden lassen,
   darunter eine von 0,56 × 0,33 nm mitten in der Fahrrinne. Betrifft
   ebenso `drawLandcover` (10 Objekte mit Lichtungen). Die gegenläufigen
   Umlaufsinne kommen so aus den Kacheln; die y-Spiegelung in `my()` dreht
   alle Ringe gleichermaßen, der relative Umlaufsinn bleibt also erhalten.
2. **Vektorkacheln beschneiden Polygone an ihrem Rand.** Den Rand eines
   Ozean-Polygons zu streichen zeichnet deshalb ein Netz im Kachelabstand
   über das Wasser – am 30.08.2026 als „doppeltes Koordinatengitter"
   aufgefallen, nachdem die Küstenlinie eingeführt wurde. Die Küstenlinie
   wird darum in `tiles.py` als eigene Ebene `coastline` abgeleitet:
   Schnittkanten sind achsparallel **und** liegen außerhalb der
   Kachelfläche (Beschnitt bei −64 und extent + 64), echte Küste bleibt
   innerhalb. Wer künftig eine Polygonebene umrandet, läuft in dieselbe
   Falle.
3. **AIS meldet „nicht verfügbar" als Zahlenwert, nicht als leeres Feld.**
   Steuerkurs 511, Kurs über Grund 360, Fahrt 102,3. `pyais` reicht sie
   unverändert durch, sie kommen also als gewöhnliche Zahlen an. Als Winkel
   verwendet zeigt 511 mod 360 = **151°** – am 29.08.2026 wurden dadurch
   29 Schiffe (400 von 733 Meldungen) sämtlich nach Südost gezeichnet,
   unabhängig von ihrem echten Kurs. Klasse-B-Transponder haben meist
   keinen Kompass und melden deshalb immer 511. Abgefangen in
   `validAngle()`; jede neue Stelle, die einen Winkel aus den Daten
   verwendet, muss da durch.
4. **`<canvas>` ist ein ersetztes Element**: `position:absolute; inset:0`
   dehnt es *nicht*: ohne explizite `width:100%; height:100%` bleibt es bei
   300×150.

Zwei Folgen des größeren Blatts, die schon Anpassungen nötig machten:

- **Ortsnamen nach Art und Zoom filtern.** Das Blatt enthält 848 Weiler
  gegen 3 Städte; alle gleichzeitig zu zeichnen begräbt die Küstenlinie
  unter Text. `PLACE_MIN_SCALE` regelt, ab welchem Zoom eine Art benannt
  wird – Städte immer, Weiler erst nah heran.
- **Die Startansicht rückt auf die eigene Position** (`placeInitialView`,
  rund 8 nm breit). `fitAll()` beim Laden war richtig, solange das Blatt
  6 nm groß war; bei 35 nm schrumpft der beobachtete Bereich sonst auf
  wenige Pixel. Der ⤢-Knopf liefert weiter die Übersicht.

Die Karte hat eine Tag- und eine Nachtansicht. Beim Ändern der Farben
darauf achten, dass Land und Meer sich in der **Helligkeit** unterscheiden,
nicht nur im Farbton – im Nachtmodus war der Kontrast anfangs 1,01 und die
Küstenlinie damit unsichtbar.

## Stand und offene Punkte (28.08.2026)

- Logger läuft auf dem BeagleBone und empfängt Daten; GPS liefert gültige
  Positionen. Das frühere Problem („Port offen, aber keine Daten") ist
  gelöst: Bei gesetztem `AIS_DEVICE` wird der Port nicht mehr vorab
  geprüft, weil das Öffnen/Schließen/Wieder-Öffnen das CDC-ACM-Gerät stört.
- **Am aktuellen Standort (Steiermark, ~47,27° N / 15,32° O) ist AIS-Empfang
  physikalisch unmöglich** – AIS ist maritimer UKW-Funk mit Sichtweite. Die
  bisher empfangenen „AIS-Nachrichten" waren nachweislich Rauschen
  (Typ 17 mit 66 statt 80 Bit; Typ 28, den es im Standard gar nicht gibt).
  Deshalb gibt es eine Plausibilitätsprüfung in `ais_decode.is_plausible`.
- **Gespeichert wird nur eine Positivliste von Nachrichtentypen**
  (`_STORED_TYPES = {1,2,3,4,5,9,11,18,19,21,24,27}`) – genau die, die
  überhaupt eine Spalte von `ais_messages` füllen. Alle übrigen (Binär-,
  Sicherheits-, Abfrage- und Verwaltungstypen) lassen jede Spalte leer.
  Sie sind zugleich der Hauptanteil des Rauschens: variabel lang, also von
  `is_plausible` nicht längenprüfbar. In der Auswertung vom 28.08.2026
  waren 4 von 53 gespeicherten Nachrichten nachweislich Unsinn, drei davon
  Typ 12/15 – zwei mit Nutzlastlängen, die die Norm für diesen Typ gar
  nicht kennt. **Typ 17 ist bewusst nicht dabei**, obwohl `pyais` eine
  Position daraus liest: das ist der Standort einer DGNSS-Referenzstation,
  kein Schiff, und würde auf der Karte als solches gezeichnet. Im Roharchiv
  (`data/raw/*.nm4`) bleibt weiterhin alles erhalten.
- Der Heartbeat zählt **`rejected` und `filtered` getrennt**: `rejected`
  sind unmögliche Nachrichten und damit der Indikator für die
  Empfangsqualität – er darf nicht durch bewusst verworfene Typen
  verwässert werden.
- Geplant ist die Beobachtung bei **Šibenik, Kroatien**. Das vorhandene
  Kartenmaterial deckt 15,809–15,945° O / 43,551–43,630° N ab – das ist die
  **Seezufahrt mit den Inseln**, nicht die Stadt selbst (die liegt bei
  43,735° N, also nördlich außerhalb).
- **Erster echter AIS-Empfang bestätigt (26.08.2026, 09:42 UTC):** zwei
  Typ-1-Positionsmeldungen von MMSI 238537940 (MID 238 = Kroatien) bei
  43,5839° N / 15,9074° E, also innerhalb des Kartenausschnitts. Die beiden
  20 s auseinanderliegenden Positionen ergeben per Koppelrechnung 7,71 kn /
  343,4° gegenüber gemeldeten 7,3 kn / 343,3° – die Decodierung ist damit
  nachweislich korrekt und nicht zufälliges Rauschen. Die Kette
  Stick → Decoder → Datenbank funktioniert im Feld.
- **Die Empfangsreichweite hat sich am 29.08.2026 sprunghaft verbessert.**
  Gemessene Werte, jeweils gegen die eigene Position gerechnet:

  | | 28.08. | 29.08. |
  |---|---|---|
  | Meldungen pro Stunde | 12 | 117 |
  | Median-Entfernung | 0,40 nm | 0,68 nm |
  | weiteste | 0,86 nm | 2,22 nm |
  | verschiedene Schiffe | 11 | 16 |

  Am 28.08. lag **jede** Meldung unter 1 nm; am 29.08. liegen 48 im Band
  1–2 nm und vier zwischen 2 und 5 nm. Die Rohdaten des 28.08. wurden auf
  Wunsch gelöscht, diese Zahlen sind die verbliebene Referenz. Für eine
  intakte Anlage (Klasse A 15–20 nm) ist auch das noch wenig – die Antenne
  bleibt der größte Hebel.
- **Die Systemuhr ging zwei Tage nach** (kein RTC, kein NTP-Weg). Seit
  28.08.2026 stellt der Logger sie aus der GPS-Zeit. Der Versatz im Moment
  der Korrektur war **+177.492 s**, belegt durch die Lücke in
  `own_position` (177.522 s = Sprung + 30 s regulärer Abstand).

  **Der Versatz war aber nicht über die ganze Aufzeichnung konstant.** Bei
  jedem Neustart setzt systemd die Uhr auf den zuletzt gespeicherten
  Zeitpunkt; die reale Ausschaltdauer geht verloren, der Versatz wächst
  also mit jedem Boot. `journalctl --list-boots` zeigt fünf Boots, und die
  Fahrt Steiermark → Šibenik (rund 600 km) erscheint in der Systemuhr als
  wenige Minuten. Ein einheitlicher Versatz ist daher nur für die
  zusammenhängende, ortsfeste Phase in Kroatien zulässig.

  Konsequenz für die Datenbank: die Zeitstempel der kroatischen Zeilen
  wurden um +177.492 s korrigiert, die älteren Zeilen aus der Steiermark
  am 28.08.2026 **gelöscht** – ihr Versatz war nicht rekonstruierbar, und
  sie enthielten ohnehin nur Rauschen. Die Datenbank enthält seither
  ausschließlich Daten vom 28.08.2026 aus Šibenik.

  Sicherung mit dem vollständigen alten Stand (inkl. Steiermark-Zeilen und
  unkorrigierten Zeitstempeln): `data/aisdb_vor_uhrkorrektur.sqlite`.
- **Roharchive vor dem 28.08.2026 liegen in `data/archiv_vor_2026-08-28/`**,
  nicht mehr in `data/raw/`. Sie sind unverändert, tragen also weiterhin die
  falschen Tagblock-Zeiten. Bewusst nicht umgeschrieben: sie sind der
  Urbeleg, und ein geschätzter Versatz darin würde eine spätere, genauere
  Korrektur unmöglich machen. Aus `raw/` heraus sind sie, damit
  `run_ingest` die falschen Zeiten nicht zurück in die Datenbank holt.
- **Weiterhin ungetestet:** Kartendarstellung mit echten Schiffen und die
  Abstandsringe unter realen Bedingungen – beides ist bisher nur mit
  simulierten Daten geprüft, nie mit dem Auge auf der fertigen Karte.
- In der Datenbank standen drei **Rauschzeilen vom 25./26.08.** (IDs 1–3,
  Typ 17/28/25) aus der Zeit vor den Filtern; sie wurden am 28.08.2026
  gelöscht. Falls so etwas wieder aufräumt werden muss: **nach `id`
  löschen, nicht nach `msg_type`** – Typ 17 (DGNSS-Basisstation) steht
  nicht in `_UNSTORED_TYPES` und wird bei echtem Empfang zu Recht
  gespeichert. Ein `DELETE ... WHERE msg_type IN (17,…)` würde solche
  gültigen Zeilen stillschweigend mitnehmen.
