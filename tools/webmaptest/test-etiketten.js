// Ortsnamen weichen Schiffsbeschriftungen aus.
C = THEMES.light; W = 1280; H = 800;
const ORT = {n:"Primošten", k:"village", c:[[[15.9228, 43.5863]]]};
base = {layers:{ocean:[], place_labels:[ORT]}, bounds:[15.4,43.3,16.2,43.9], attribution:""};
view = {cx: mx(15.9185), cy: my(43.5906), scale: 5485428};

const X = sx(mx(15.9228)), Y = sy(my(43.5863));
const namen = () => { calls.length = 0; draw();
  return calls.filter(x=>x.op==="fillText").map(x=>x.args[0]); };

console.log("\n--- ohne Schiff ---");
live = {own:null, now:0, max_age_min:90, ships:[], tracks:{}};
ok("Ortsname wird gezeichnet", namen().includes("Primošten"));

console.log("\n--- Schiff so, dass seine Beschriftung den Ort trifft ---");
// Die Schiffsbeschriftung sitzt 25 bzw. 14 px UEBER dem Symbol. Verdeckt
// wird der Ort also, wenn das Schiff etwas unterhalb von ihm liegt --
// im echten Kartenbild waren es 13 px.
function schiffBei(pixelUnterOrt, name) {
  const yWelt = (Y + pixelUnterOrt - H / 2) / view.scale + view.cy;
  return {mmsi:1, lat: invMy(yWelt), lon: 15.9228,
          sog:0, cog:null, hdg:null, ts:0, name};
}
{
  live = {own:null, now:0, max_age_min:90, tracks:{}, ships:[schiffBei(13, "MANATEE")]};
  const t = namen();
  ok("Ortsname weicht aus", !t.includes("Primošten"), t.join(", "));
  ok("Schiffsname bleibt", t.includes("MANATEE"));
}
{
  live = {own:null, now:0, max_age_min:90, tracks:{}, ships:[schiffBei(-40, "DRUEBER")]};
  ok("Schiff oberhalb verdeckt nicht", namen().includes("Primošten"));
}

console.log("\n--- Schiff weit genug weg ---");
{
  const s = {mmsi:1, lat:43.5700, lon:15.9500, sog:0, cog:null, hdg:null, ts:0, name:"WEIT"};
  live = {own:null, now:0, max_age_min:90, ships:[s], tracks:{}};
  const t = namen();
  ok("Ortsname wird wieder gezeichnet", t.includes("Primošten"), t.join(", "));
}

console.log("\n--- ohne Schiffsbeschriftung (weit herausgezoomt) ---");
{
  view = {cx: mx(15.9185), cy: my(43.5906), scale: 50000};
  const s = {mmsi:1, lat:43.5863, lon:15.9228, sog:0, cog:null, hdg:null, ts:0, name:"MANATEE"};
  live = {own:null, now:0, max_age_min:90, ships:[s], tracks:{}};
  const t = namen();
  ok("kein Schiffslabel -> keine Verdeckung noetig", !t.includes("MANATEE"));
  // Ortsname faellt hier ohnehin unter die Zoomschwelle
  ok("Dorf unterhalb der Zoomschwelle nicht benannt", !t.includes("Primošten"));
}

console.log(globalThis.__fail ? `\n${globalThis.__fail} FEHLER` : "\nalle Pruefungen bestanden");
process.exit(globalThis.__fail ? 1 : 0);
