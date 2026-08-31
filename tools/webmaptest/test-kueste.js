// Die Kuestenlinie darf keine Kachel-Schnittkanten enthalten.
C = THEMES.light; W = 1280; H = 800;
const bm = require(process.env.HIER + "/basemap.json");
base = {layers: bm, bounds:[15.4,43.3,16.2,43.9], attribution:""};
live = {own:{lat:43.59,lon:15.9,ts:0}, ships:[], tracks:{}, now:0, max_age_min:90};

console.log("\n--- eigene Ebene statt Polygonrand ---");
ok("coastline geliefert", Array.isArray(bm.coastline) && bm.coastline.length > 0,
   `${(bm.coastline||[]).length} Objekte`);
ok("als Linien, nicht als Flaechen", bm.coastline.every(f => f.t === "ln"));

console.log("\n--- keine Kachelkanten mehr ---");
{
  const KACHEL = 360 / (1 << 14);
  let achs = 0, aufGitter = 0, kanten = 0;
  for (const f of bm.coastline) for (const p of f.c) for (let i=0;i<p.length-1;i++) {
    const [x1,y1] = p[i], [x2,y2] = p[i+1];
    kanten++;
    if (x1 === x2 && Math.abs(y2-y1) > 1e-4) {
      achs++;
      if (Math.abs(x1/KACHEL - Math.round(x1/KACHEL)) < 1e-6) aufGitter++;
    }
    if (y1 === y2 && Math.abs(x2-x1) > 1e-4) achs++;
  }
  ok("keine senkrechte Kante auf einer Kachelgrenze", aufGitter === 0,
     `${kanten} Kanten, ${achs} achsparallel, ${aufGitter} auf dem Raster`);
}

console.log("\n--- Zeichnung ---");
view = {cx: mx(15.9), cy: my(43.59), scale: 2367400};
calls.length = 0; draw();
const striche = calls.filter(x=>x.op==="set:strokeStyle").map(x=>x.args[0]);
ok("Flachwassersaum gezeichnet", striche.includes(C.shallow));
ok("Kuestenlinie gezeichnet", striche.includes(C.coast));
ok("Saum vor der Linie", striche.indexOf(C.shallow) < striche.indexOf(C.coast));
ok("runde Enden am Saum", calls.some(x=>x.op==="set:lineCap" && x.args[0]==="round"));
ok("Ozean nur gefuellt, nicht umrandet", (() => {
     // zwischen dem Fuellen des Ozeans und dem Saum darf keine Kontur liegen
     const iSee = calls.findIndex(x=>x.op==="set:fillStyle" && x.args[0]===C.sea);
     const iSaum = calls.findIndex(x=>x.op==="set:strokeStyle" && x.args[0]===C.shallow);
     return calls.slice(iSee, iSaum).every(x => x.op !== "set:strokeStyle"
                                             || x.args[0] !== C.coast); })());
ok("save/restore paarweise",
   calls.filter(x=>x.op==="save").length === calls.filter(x=>x.op==="restore").length);
console.log(globalThis.__fail ? `\n${globalThis.__fail} FEHLER` : "\nalle Pruefungen bestanden");
process.exit(globalThis.__fail ? 1 : 0);
