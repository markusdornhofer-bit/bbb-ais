// Auswahl der Schiffe in der Wiedergabe: genug Punkte und in Fahrt gewesen.
(async () => {
C = THEMES.light; W = 1280; H = 800;
base = {layers:{ocean:[],place_labels:[]}, bounds:[15.4,43.3,16.2,43.9], attribution:""};

function meld(mmsi, n, sog) {
  return Array.from({length:n}, (_,i) => ({mmsi, ts: 1000 + i*60, lat: 43.59 + i*1e-4,
                                           lon: 15.9, sog, cog: 0, hdg: null}));
}
const FAELLE = [
  ...meld(1, 20, 7.5),   // viele Punkte, in Fahrt   -> bleibt
  ...meld(2,  6, 2.5),   // genau 6 Punkte, in Fahrt -> bleibt
  ...meld(3,  5, 9.0),   // zu wenige Punkte         -> raus
  ...meld(4, 30, 0.4),   // vor Anker                -> raus
  ...meld(5, 30, 2.0),   // exakt 2,0 kn             -> raus, wie die Farbregel
  ...meld(6,  1, 8.0),   // Einzelmeldung            -> raus
].sort((a,b)=>a.ts-b.ts);
globalThis.HIST = {from:0, to:100000, ships:FAELLE, names:{}, own:[[1000,43.59,15.9]]};
globalThis.DAYS = [];

await toggleReplay();
const drin = [...replay.byShip.keys()].sort((a,b)=>a-b);

console.log("\n--- Auswahl ---");
ok("REPLAY_MIN_POINTS ist 6", REPLAY_MIN_POINTS === 6);
ok("nur die beiden tauglichen Schiffe", drin.join(",") === "1,2", drin.join(", "));
ok("zu wenige Punkte fliegt raus", !drin.includes(3));
ok("Ankerlieger fliegt raus", !drin.includes(4));
ok("exakt 2,0 kn fliegt raus, wie bei der Farbe", !drin.includes(5));
ok("Einzelmeldung fliegt raus", !drin.includes(6));
ok("Zaehler der Ausgeblendeten stimmt", replay.ausgeblendet === 4, String(replay.ausgeblendet));

console.log("\n--- Folgen fuer den Rest des Players ---");
ok("Meldungsliste nur von den gezeigten", replay.ships.every(s => drin.includes(s.mmsi)));
ok("Meldungszahl stimmt", replay.ships.length === 26, String(replay.ships.length));
ok("Start bei der ersten gezeigten Meldung", replay.t === replay.ships[0].ts);
ok("Schiffsliste enthaelt nur die zwei", replay.listEls.size === 2);
ok("Hinweis auf die Ausblendung",
   document.getElementById("rp-span").textContent.includes("4 ausgeblendet"),
   document.getElementById("rp-span").textContent);
ok("Zaehler zeigt die gefilterte Zahl",
   document.getElementById("rp-info").textContent.startsWith("2 Schiffe"),
   document.getElementById("rp-info").textContent);

console.log("\n--- Darstellung ---");
scrubTo(0.02);
ok("nur gefilterte Schiffe auf der Karte", live.ships.every(s => drin.includes(s.mmsi)),
   `${live.ships.length} sichtbar`);
calls.length = 0; draw();
ok("draw() laeuft durch", calls.length > 0);

console.log("\n--- Grenzfall: alles gefiltert ---");
globalThis.HIST = {from:0, to:100000, ships: meld(9, 30, 0.1), names:{}, own:[[1000,43.59,15.9]]};
await openReplay("hours=24", null);
ok("keine Schiffe uebrig", replay.byShip.size === 0);
ok("spielt nicht los", replay.playing === false);
ok("Uhr sagt warum", document.getElementById("rp-clock").textContent === "nichts in Fahrt",
   document.getElementById("rp-clock").textContent);
ok("Liste meldet es", document.getElementById("rp-ships").innerHTML.includes("keine Schiffe"));
exitReplay();

console.log(globalThis.__fail ? `\n${globalThis.__fail} FEHLER` : "\nalle Pruefungen bestanden");
process.exit(globalThis.__fail ? 1 : 0);
})();
