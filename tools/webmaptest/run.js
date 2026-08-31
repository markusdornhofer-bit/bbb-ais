/* Fuehrt die Kartenpruefungen aus. Siehe stub.js fuer den Aufbau. */
const fs = require("fs"), path = require("path");
const HIER = __dirname, WURZEL = path.join(HIER, "..", "..");

const seite = fs.readFileSync(path.join(WURZEL, "webmap/static/index.html"), "utf8");
const script = seite.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const code = script.slice(0, script.indexOf("setInterval(() => {"));

const suiten = process.argv.slice(2).length
  ? process.argv.slice(2)
  : fs.readdirSync(HIER).filter(f => f.startsWith("test-")).map(f => f.slice(5, -3)).sort();

let fehler = 0;
for (const name of suiten) {
  const datei = path.join(HIER, `test-${name}.js`);
  if (!fs.existsSync(datei)) { console.log(`\n### ${name}: nicht gefunden`); fehler++; continue; }
  console.log(`\n### ${name}`);
  const stub = fs.readFileSync(path.join(HIER, "stub.js"), "utf8");
  const test = fs.readFileSync(datei, "utf8");
  const ergebnis = require("child_process").spawnSync(process.execPath,
    ["-e", stub + "\n" + code + "\n" + test], { encoding: "utf8", env: {...process.env, HIER} });
  process.stdout.write(ergebnis.stdout);
  if (ergebnis.stderr) process.stderr.write(ergebnis.stderr);
  if (ergebnis.status !== 0) fehler++;
}
console.log(fehler ? `\n${fehler} Suite(n) mit Fehlern` : "\nalle Suiten bestanden");
process.exit(fehler ? 1 : 0);
