// Gebuendelte Regression der Kartendarstellung.
C = THEMES.light; W = 1280; H = 800;
const bm = require(process.env.HIER + "/basemap.json");
base = {layers: bm, bounds:[15.4,43.3,16.2,43.9],
        attribution:'<a href="x">&copy; OpenStreetMap contributors</a>'};
const NOW = 100000;
const lum = h => { const [r,g,b]=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
                   return 0.2126*r+0.7152*g+0.0722*b; };
function schiff(o={}) {
  const s = {mmsi:1, lat:43.59, lon:15.9, sog:8, cog:0, hdg:null, ts:NOW-60, ...o};
  live = {own:null, now:NOW, max_age_min:90, ships:[s],
          tracks:{"1":[[15.9,43.5887,NOW-120],[s.lon,s.lat,s.ts]]}};
  return s;
}
const zeichne = (s, scale=2367400) => {
  view = {cx: mx(15.9), cy: my(43.59), scale};
  calls.length = 0; drawShip(s, NOW); return calls.slice();
};
const voll = (scale=2367400) => {
  view = {cx: mx(15.9), cy: my(43.59), scale};
  calls.length = 0; draw(); return calls.slice();
};

console.log("\n--- AIS-Kennwerte ---");
ok("511 verworfen", validAngle(511) === null);
ok("360 verworfen", validAngle(360) === null);
ok("hdg 511 -> COG uebernimmt", shipCourse({hdg:511, cog:313.2}) === 313.2);
ok("fmtCog(360) ist Strich", fmtCog(360) === "–");

console.log("\n--- Farbe und Groesse ---");
ok("ueber 2 kn warme Rampe", shipColour({sog:7.3, ts:NOW}, NOW) === C.rampMoving[0]);
ok("2,0 kn neutrale Rampe", shipColour({sog:2.0, ts:NOW}, NOW) === C.rampSlow[0]);
ok("stufenlos dunkler", (() => {
     const l = [0,15,45,90].map(m => lum(shipColour({sog:8, ts:0}, m*60)));
     return l.every((v,i) => i===0 || v < l[i-1]); })());
const skala = c => { const s = c.find(x=>x.op==="scale"); return s ? s.args[0] : 1; };
ok("Vergroesserung ist 1,5x", FRESH_SCALE === 1.5, String(FRESH_SCALE));
ok("frisch + Fahrt vergroessert",
   skala(zeichne(schiff({ts:NOW-60, sog:8}))) === FRESH_SCALE);
ok("frisch ohne Fahrt normal", skala(zeichne(schiff({ts:NOW-60, sog:0.4}))) === 1);
ok("Grenze 6 min", skala(zeichne(schiff({ts:NOW-359}))) === FRESH_SCALE &&
                   skala(zeichne(schiff({ts:NOW-361}))) === 1);
ok("Umriss waechst nicht mit", (() => {
     const c = zeichne(schiff({ts:NOW-60, sog:8}));
     return c.filter(x=>x.op==="set:lineWidth").some(x =>
       Math.abs(x.args[0] - 1.2/FRESH_SCALE) < 1e-9); })(),
   `Linienbreite 1,2/${FRESH_SCALE}`);
ok("Beschriftung folgt der Rumpfspitze", (() => {
     const t = zeichne(schiff({ts:NOW-60, sog:8})).filter(x=>x.op==="fillText");
     const oben = 400 - 10 * FRESH_SCALE;
     return t[0].args[2] === oben - 15 && t[1].args[2] === oben - 4; })());
ok("Beschriftung Minuten|Fahrt",
   zeichne(schiff({ts:NOW-240, sog:6.5})).filter(x=>x.op==="fillText")[1].args[0] === "4|6.5kn");

console.log("\n--- Vorhersagepfade ---");
{
  const s = schiff({ts:NOW-60, sog:8, cog:0});
  ok("Segmentpfad", predictPosition(s, NOW) !== null);
  ok("gruener Pfad", predictReported(s, NOW) !== null);
  ok("ab Alter 0", predictReported(schiff({ts:NOW}), NOW) !== null);
  ok("Grenze bei 6 min: 359 s noch, 361 s nicht mehr",
     predictReported(schiff({ts:NOW-359}), NOW) !== null &&
     predictReported(schiff({ts:NOW-361}), NOW) === null);
  ok("Vorschau so lange wie die Vergroesserung",
     PREDICT_MAX_SECONDS === FRESH_SECONDS, `${PREDICT_MAX_SECONDS} s`);
  ok("vor Anker keiner", predictReported(schiff({sog:0.4}), NOW) === null);
  const c = zeichne(s);
  ok("vier Marken", c.filter(x=>x.op==="arc" && (x.args[2]===2.2||x.args[2]===3.5)).length === 4);
  ok("nur ein fill", c.filter(x=>x.op==="fill").length === 1);
}

console.log("\n--- Grundkarte ---");
{
  const mehr = (bm.ocean||[]).filter(f => f.c.length > 1);
  calls.length = 0; for (const f of mehr) fillPolygon(f);
  ok("Inseln: ein fill je Polygon", calls.filter(x=>x.op==="fill").length === mehr.length,
     `${mehr.length} mehrringige`);
}
{
  live = {own:{lat:43.59,lon:15.9,ts:0}, now:0, ships:[], tracks:{}, max_age_min:90};
  const c = voll();
  const farben = c.filter(x=>x.op==="set:strokeStyle").map(x=>x.args[0]);
  ok("Kuestenlinie", farben.includes(C.coast));
  ok("Flachwassersaum", farben.includes(C.shallow));
  ok("Gradnetz", farben.includes(C.grid));
  for (const [n, f] of [["Grenzen",C.boundary],["Faehren",C.ferry],["Bruecken",C.bridge]])
    ok(n, farben.includes(f));
  const t = c.filter(x=>x.op==="fillText").map(x=>x.args[0]);
  ok("Massstab", t.some(x=>/^[\d,]+ nm$/.test(x)), t.find(x=>/nm$/.test(x)));
  ok("Attribution als Text", t.includes("© OpenStreetMap contributors"));
  ok("Koordinaten beschriftet", t.some(x=>/^\d+°[\d.]+'[NSOW]$/.test(x)));
  ok("Bodenbedeckung", c.some(x=>x.op==="set:fillStyle" && x.args[0]===C.cover.forest));
  ok("save/restore paarweise",
     c.filter(x=>x.op==="save").length === c.filter(x=>x.op==="restore").length);
}
{
  calls.length = 0; drawRings({lat:43.59, lon:15.9});
  const step = nmToWorld(1,43.59)*view.scale;
  ok("Ringe exakte Vielfache von 1 nm",
     calls.filter(x=>x.op==="arc").map(a=>a.args[2]).every((r,i)=>Math.abs(r-(i+1)*step)<1e-9));
}

console.log("\n--- HUD und Tastatur ---");
live = {own:{lat:43.59,lon:15.918,ts:0}, now:0, max_age_min:90, tracks:{},
        ships:[{mmsi:1,ts:0,sog:7.3,cog:340,lat:43.59,lon:15.9,name:"X"}]};
updateHud();
ok("Fenster im HUD", document.getElementById("ship-window").textContent === " (90 min)");
ok("Liste mit Kurs", document.getElementById("recent-rows").innerHTML.includes(">340°<"));
{
  const press=(k,m={})=>{let d=false;
    keyHandlers[0]({key:k,ctrlKey:false,metaKey:false,altKey:false,...m,preventDefault:()=>{d=true}});
    return d;};
  view={cx:0.5, cy:0.5, scale:100000};
  press("+"); ok("+ zoomt", view.scale===150000);
  press("-"); ok("- zoomt zurueck", view.scale===100000);
  ok("Strg+ bleibt dem Browser", press("+",{ctrlKey:true})===false);
}
console.log(globalThis.__fail ? `\n${globalThis.__fail} FEHLER` : "\nalle Pruefungen bestanden");
process.exit(globalThis.__fail ? 1 : 0);
