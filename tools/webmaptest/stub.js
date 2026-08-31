/* Headless-Umgebung fuer webmap/static/index.html.
 *
 * Der Zeichencode der Karte laesst sich ohne Browser pruefen, indem Canvas
 * und DOM durch Attrappen ersetzt werden, die jeden Aufruf mitschreiben.
 * Geprueft wird damit die Mechanik (Geometrie, Reihenfolge, Schwellen), nicht
 * das Bild -- wie die Karte aussieht, sieht weiterhin nur ein Mensch.
 *
 *   node tools/webmaptest/run.js                # alle Suiten
 *   node tools/webmaptest/run.js filter ebenen  # einzelne
 */
const calls = [];

/* moveTo und lineTo sind pro gezeichnetem Stuetzpunkt einer, bei der vollen
   Basiskarte rund 600 000 Stueck. Sie alle aufzuheben kostet ueber 100 MB
   und liess die Suiten auf dem BeagleBone am Heap-Limit sterben. Sie werden
   deshalb nur gezaehlt; keine Pruefung sieht sie sich einzeln an. */
const NUR_ZAEHLEN = new Set(["moveTo", "lineTo"]);
const callCounts = {};
const rec = n => (...a) => {
  callCounts[n] = (callCounts[n] || 0) + 1;
  if (!NUR_ZAEHLEN.has(n)) calls.push({op:n, args:a});
};
const ctxStub = new Proxy({}, {get(t,p){ if(p==="canvas") return {};
  if(p==="measureText") return ()=>({width:20}); if(!(p in t)) t[p]=rec(p); return t[p]; },
  set(t,p,v){ t[p]=v; calls.push({op:"set:"+p, args:[v]}); return true; }});
const elems = new Map();
function el(id){
  if(!elems.has(id)) elems.set(id, {id, textContent:"", value:0, style:{}, innerHTML:"",
    classList:{on:false, toggle(c,v){this.on = v===undefined ? !this.on : v;},
               add(){this.on=true;}, remove(){this.on=false;}},
    addEventListener(t,f){ if(t==="click") this.onclick=f; },
    setPointerCapture(){}, getContext:()=>ctxStub, clientWidth:1280, clientHeight:800,
    querySelectorAll(){ const out=[];
      for (const m of String(this.innerHTML||"").matchAll(/data-mmsi="(\d+)"/g))
        out.push({dataset:{mmsi:m[1]}, style:{}});
      return out; }});
  return elems.get(id);
}
globalThis.calls = calls;
globalThis.callCounts = callCounts;
globalThis.elems = elems;
globalThis.keyHandlers = [];
globalThis.document = {getElementById: el, documentElement:{setAttribute(){}}, activeElement:null};
globalThis.localStorage = {getItem:()=>null, setItem(){}};
globalThis.window = {addEventListener:(t,f)=>{ if(t==="keydown") keyHandlers.push(f); },
  innerWidth:1280, innerHeight:800, devicePixelRatio:1};
globalThis.requestAnimationFrame = () => {};
globalThis.fakeNow = 1000;
globalThis.performance = { now: () => fakeNow };
globalThis.fetchLog = [];
globalThis.fetch = async (url) => {
  fetchLog.push(url);
  if (url.startsWith("/api/days")) return { json: async () => globalThis.DAYS };
  if (url.startsWith("/api/live")) return { json: async () => ({
    own:{ts:0,lat:43.59,lon:15.9,sog:0,cog:null}, ships:[], tracks:{},
    now:0, max_age_min:90 }) };
  return { json: async () => globalThis.HIST };
};
globalThis.ok = (name, bedingung, info="") => {
  console.log((bedingung ? "  OK  " : "  FEHLER ") + name + (info ? "  " + info : ""));
  if (!bedingung) globalThis.__fail++;
};
globalThis.__fail = 0;
