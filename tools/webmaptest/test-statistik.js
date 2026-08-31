// Statistikfenster: Inhalt, Bedienung, Maskierung.
(async () => {
C = THEMES.light; W = 1280; H = 800;
base = {layers:{ocean:[],place_labels:[]}, bounds:[15.4,43.3,16.2,43.9], attribution:""};

const STATS = {ships: 124, messages: 4069, dropped: 5,
  from: 1788000000, to: 1788100000,
  records: [
    {titel:"weiteste Entfernung", mmsi:1, name:"SPIEGELGRACHT", wert:45.11, einheit:"nm", ts:1788010000},
    {titel:"längster Kontakt",    mmsi:2, name:"BALANCE SIBENIK", wert:2024, einheit:"min", ts:1788020000},
    {titel:"größte Fahrt",        mmsi:3, name:"<b>BOESE</b>",  wert:30.4, einheit:"kn", ts:1788030000},
  ]};
const echtesFetch = globalThis.fetch;
globalThis.fetch = async (url) => url.startsWith("/api/stats")
  ? { json: async () => STATS } : echtesFetch(url);

const box = () => document.getElementById("stats");
const rows = () => document.getElementById("st-rows").innerHTML;

console.log("\n--- oeffnen ---");
ok("zu Beginn verborgen", box().style.display !== "block");
await toggleStats();
ok("sichtbar", box().style.display === "block");
ok("Knopf markiert", document.getElementById("stats-btn").classList.on === true);

console.log("\n--- Inhalt ---");
ok("eine Zeile je Rekord", rows().split("<tr>").length - 1 === STATS.records.length,
   `${rows().split("<tr>").length - 1} Zeilen`);
ok("Titel, Wert und Einheit", rows().includes("weiteste Entfernung")
   && rows().includes("45.11 nm"));
ok("Schiffsname dabei", rows().includes("SPIEGELGRACHT"));
ok("Zeitraum und Bestand",
   document.getElementById("st-zeitraum").textContent.includes("124 Schiffe")
   && document.getElementById("st-zeitraum").textContent.includes("4069 Meldungen"),
   document.getElementById("st-zeitraum").textContent);
ok("Hinweis auf verworfene Meldungen",
   document.getElementById("st-fuss").textContent.includes("5 Meldungen über 100 nm"),
   document.getElementById("st-fuss").textContent.slice(0, 48));
ok("Schiffsnamen maskiert", !rows().includes("<b>BOESE</b>") && rows().includes("&lt;b&gt;"));

console.log("\n--- schliessen ---");
await toggleStats();
ok("wieder verborgen", box().style.display === "none");
ok("Knopf nicht mehr markiert", document.getElementById("stats-btn").classList.on === false);
await toggleStats();
const press=(k)=>{keyHandlers[0]({key:k,ctrlKey:false,metaKey:false,altKey:false,
                                  preventDefault:()=>{}});};
press("Escape");
ok("Esc schliesst das Fenster", box().style.display === "none");

console.log("\n--- leere Aufzeichnung ---");
STATS.records = []; STATS.from = null; STATS.dropped = 0;
await toggleStats();
ok("sagt, dass nichts da ist",
   document.getElementById("st-zeitraum").textContent === "keine Aufzeichnung");
ok("Tabelle meldet es", rows().includes("nichts aufgezeichnet"));
ok("kein Hinweis ohne verworfene", document.getElementById("st-fuss").textContent === "");
await toggleStats();

console.log(globalThis.__fail ? `\n${globalThis.__fail} FEHLER` : "\nalle Pruefungen bestanden");
process.exit(globalThis.__fail ? 1 : 0);
})();
