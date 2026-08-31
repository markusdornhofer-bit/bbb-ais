// Mehrstufige Farbverlaeufe: Monotonie, Farbtrennung, Interpolation.
C = THEMES.light; W = 1280; H = 800;
live = {max_age_min: 90};
const lum = h => { const [r,g,b]=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
                   return 0.2126*r+0.7152*g+0.0722*b; };
const rgb = h => [1,3,5].map(i=>parseInt(h.slice(i,i+2),16));

console.log("\n--- rampColour ---");
const R = ["#000000", "#ff0000", "#ffffff"];
ok("t=0 erster Stopp", rampColour(R, 0) === "#000000");
ok("t=1 letzter Stopp", rampColour(R, 1) === "#ffffff");
ok("t=0,5 mittlerer Stopp", rampColour(R, 0.5) === "#ff0000");
ok("t=0,25 zwischen Stopp 1 und 2", rampColour(R, 0.25) === "#800000", rampColour(R,0.25));
ok("t=0,75 zwischen Stopp 2 und 3", rampColour(R, 0.75) === "#ff8080", rampColour(R,0.75));
ok("unter 0 geklemmt", rampColour(R, -3) === "#000000");
ok("ueber 1 geklemmt", rampColour(R, 7) === "#ffffff");
ok("immer sechsstellig", [0,0.13,0.5,0.87,1].every(t => /^#[0-9a-f]{6}$/.test(rampColour(R,t))));

console.log("\n--- Helligkeit faellt streng, in beiden Themen ---");
for (const [thema, T] of Object.entries(THEMES)) {
  for (const name of ["rampMoving", "rampSlow"]) {
    const l = T[name].map(lum);
    ok(`${thema} ${name}`, l.every((v,i)=>i===0||v<l[i-1]),
       l.map(v=>v.toFixed(0)).join(" > "));
  }
}
console.log("\n--- ueber die Rampe hinweg, nicht nur an den Stopps ---");
for (const [thema, T] of Object.entries(THEMES)) {
  C = T;
  for (const sog of [8, 0.4]) {
    const werte = [];
    for (let m = 0; m <= 90; m += 3) werte.push(lum(shipColour({sog, ts:0}, m*60)));
    const fallend = werte.every((v, i) => i === 0 || v < werte[i-1]);
    ok(`${thema}, ${sog} kn: ${werte.length} Stufen streng fallend`, fallend,
       `${werte[0].toFixed(0)} .. ${werte[werte.length-1].toFixed(0)}`);
  }
}
C = THEMES.light;

console.log("\n--- Fahrt bleibt am Farbton ablesbar ---");
for (const [thema, T] of Object.entries(THEMES)) {
  for (let i = 0; i < 4; i++) {
    const [wr,wg,wb] = rgb(T.rampMoving[i]), [nr,ng,nb] = rgb(T.rampSlow[i]);
    const warm = wr - (wg+wb)/2, neutral = nr - (ng+nb)/2;
    ok(`${thema} Stufe ${i}: warm waermer als neutral`, warm > neutral + 8,
       `${warm.toFixed(0)} gegen ${neutral.toFixed(0)}`);
  }
}

console.log("\n--- sichtbar gegen den Untergrund ---");
for (const [thema, T] of Object.entries(THEMES)) {
  for (const name of ["rampMoving", "rampSlow"]) {
    const d = Math.abs(lum(T[name][3]) - lum(T.sea));
    ok(`${thema} ${name}: dunkelste Stufe hebt sich vom Meer ab`, d > 20,
       `Abstand ${d.toFixed(0)}`);
  }
}

console.log("\n--- Anwendung ---");
C = THEMES.light; live = {max_age_min: 90};
ok("frisch = erster Stopp", shipColour({sog:8, ts:100}, 100) === C.rampMoving[0]);
ok("am Fensterende = letzter Stopp",
   shipColour({sog:8, ts:0}, 90*60) === C.rampMoving[3], shipColour({sog:8,ts:0},90*60));
ok("darueber hinaus nicht dunkler",
   shipColour({sog:8, ts:0}, 900*60) === C.rampMoving[3]);
ok("ohne Zeitangabe erster Stopp", shipColour({sog:8, ts:0}, null) === C.rampMoving[0]);
live = {max_age_min: 15};
ok("Fenster steuert die Spanne",
   shipColour({sog:8, ts:0}, 15*60) === shipColour({sog:8, ts:0}, 90*60));

console.log(globalThis.__fail ? `\n${globalThis.__fail} FEHLER` : "\nalle Pruefungen bestanden");
process.exit(globalThis.__fail ? 1 : 0);
