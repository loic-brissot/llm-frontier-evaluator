import maplibregl, { type GeoJSONSource, type Map } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/fraunces/latin-400-italic.css";
import "@fontsource/outfit/latin-300.css";
import "@fontsource/outfit/latin-400.css";
import "@fontsource/outfit/latin-500.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./styles.css";
import { createTrainLayer, type Frame } from "./layer";

type Station = { name: string; lon: number; lat: number; deps: number; arrs: number };
type Train = { n: string; c: number; b: string; s: number[][]; p: number[] };
type Atlas = {
  dayLabel: string;
  stations: Station[];
  xfer: number[];
  foot: number[][];
  edges: number[][][];
  paths: number[][];
  trains: Train[];
  profile: number[][];
  hourly: number[][][];
};
type Geom = { lon: Float64Array; lat: Float64Array; cum: Float64Array; total: number };
type Mode = "run" | "access" | "flow";
type Hit = { kind: "train" | "station"; index: number; x: number; y: number };

const CATS = [
  { name: "TGV", color: "#e7b15a", rgb: [0.906, 0.694, 0.353] },
  { name: "Intercités", color: "#ef6b4a", rgb: [0.937, 0.42, 0.29] },
  { name: "TER", color: "#3dcec2", rgb: [0.239, 0.808, 0.761] },
];
const BIN_COLOR = ["#ffe08a", "#b6e38a", "#3dcec2", "#7aa2ff", "#c792ea", "#3a424c"];

const atlas = await loadAtlas();
const flow = await fetchJson<GeoJSON.FeatureCollection>(`${import.meta.env.BASE_URL}data/flow.geojson`);
const land = await fetchJson<GeoJSON.FeatureCollection>(`${import.meta.env.BASE_URL}data/land.geojson`);

const stations = atlas.stations;
const trains = atlas.trains;
const geoms: Geom[] = atlas.paths.map((path) => buildGeom(path));
const ranked = stations.map((_, i) => i).sort((a, b) => stations[b].deps - stations[a].deps);
const folded = stations.map((s) => fold(s.name));
const board: { ti: number; si: number; arr: number; dep: number }[][] = stations.map(() => []);
trains.forEach((tr, ti) => {
  tr.s.forEach((st, si) => board[st[0]].push({ ti, si, arr: st[1], dep: st[2] }));
});
board.forEach((list) => list.sort((a, b) => a.dep - b.dep || a.arr - b.arr));
const daily = [0, 0, 0];
for (const tr of trains) daily[tr.c] += 1;

let mode: Mode = "run";
let mask = 7;
let playing = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let rate = 5;
let scrubbing = false;
let clock = parisMinutes();
let selection: { kind: "train" | "station"; index: number } | null = null;
let origin: number | null = null;
let access: { dur: Int16Array; leave: Int16Array } | null = null;
let reveal = 0;
const hits: Hit[] = [];
const coreBuf = new Float32Array(16000 * 7);
const trailBuf = new Float32Array(16000 * 8 * 7);

const worker = new Worker(new URL("./csa.ts", import.meta.url), { type: "module" });
const footAdj: number[][] = stations.map(() => []);
for (const [a, b, minutes] of atlas.foot) footAdj[a].push(b, minutes);
worker.postMessage({
  type: "init",
  n: stations.length,
  xfer: atlas.xfer,
  foot: footAdj,
  url: new URL(`${import.meta.env.BASE_URL}data/conn.json`, window.location.href).toString(),
});
const accessCache = new Map<string, { dur: Int16Array; leave: Int16Array }>();
let querySeq = 0;
let workerReady = false;
const waiting: { id: number; origin: number; mask: number }[] = [];

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const dayEl = $("day");
dayEl.textContent = atlas.dayLabel;
document.querySelectorAll<HTMLElement>("[data-day]").forEach((el) => {
  const cat = Number(el.dataset.day);
  el.textContent = `${fmt(daily[cat])} / jour`;
});

const map: Map = new maplibregl.Map({
  container: "map",
  style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#081018" } }] },
  center: [2.4, 46.6],
  zoom: 5.4,
  minZoom: 4.3,
  maxZoom: 13.2,
  maxBounds: [[-11.5, 39.2], [15.5, 53.6]],
  attributionControl: false,
  fadeDuration: 0,
});
map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");
map.dragRotate.disable();
map.touchZoomRotate.disableRotation();

const trainLayer = createTrainLayer(sampleFrame);
map.on("load", () => {
  map.addSource("land", { type: "geojson", data: land });
  map.addSource("flow", { type: "geojson", data: flow });
  map.addSource("stations", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: stations.map((s, i) => ({
        type: "Feature",
        id: i,
        properties: { deps: s.deps },
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      })),
    },
  });
  map.addSource("route", { type: "geojson", data: emptyCollection() });
  map.addSource("route-stops", { type: "geojson", data: emptyCollection() });
  map.addLayer({ id: "countries", type: "fill", source: "land", filter: ["==", ["get", "kind"], "country"], paint: { "fill-color": "#101820" } });
  map.addLayer({
    id: "dept-coast",
    type: "line",
    source: "land",
    filter: ["==", ["get", "kind"], "dept"],
    paint: { "line-color": "rgba(232, 220, 196, 0.55)", "line-width": 2.2 },
  });
  map.addLayer({ id: "dept", type: "fill", source: "land", filter: ["==", ["get", "kind"], "dept"], paint: { "fill-color": "#161e28" } });
  map.addLayer({
    id: "dept-line",
    type: "line",
    source: "land",
    filter: ["==", ["get", "kind"], "dept"],
    paint: { "line-color": "rgba(243, 236, 223, 0.08)", "line-width": 0.6 },
  });
  map.addLayer({
    id: "flow-glow",
    type: "line",
    source: "flow",
    layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ["interpolate", ["linear"], ["get", "n"], 0, "#163038", 40, "#3d7a86", 140, "#e7d7b0", 300, "#fff6e4"],
      "line-width": widthExpr(2.4),
      "line-blur": 1.4,
      "line-opacity": 0.55,
    },
  });
  map.addLayer({
    id: "flow",
    type: "line",
    source: "flow",
    layout: { "line-cap": "round", "line-join": "round", "line-sort-key": ["get", "n"] },
    paint: {
      "line-color": runLineColor(),
      "line-width": widthExpr(0.55),
      "line-opacity": 0.9,
    },
  });
  map.addLayer({
    id: "route-casing",
    type: "line",
    source: "route",
    paint: { "line-color": "rgba(243,236,223,0.25)", "line-width": 7, "line-blur": 1.2 },
    layout: { "line-cap": "round", "line-join": "round" },
  });
  map.addLayer({
    id: "route",
    type: "line",
    source: "route",
    paint: { "line-color": "#f7f1e6", "line-width": 2.2 },
    layout: { "line-cap": "round", "line-join": "round" },
  });
  map.addLayer({
    id: "stations",
    type: "circle",
    source: "stations",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4.8, ["interpolate", ["linear"], ["get", "deps"], 0, 0.7, 40, 1.3, 200, 2.1], 8, ["interpolate", ["linear"], ["get", "deps"], 0, 1.6, 40, 2.6, 200, 4.2]],
      "circle-color": "#d9d0c3",
      "circle-opacity": 0.85,
      "circle-stroke-color": "#f7f1e6",
      "circle-stroke-width": ["case", ["==", ["feature-state", "on"], 1], 2, 0],
      "circle-stroke-opacity": 0.95,
    },
  });
  map.addLayer({
    id: "route-stops",
    type: "circle",
    source: "route-stops",
    paint: { "circle-radius": 3.5, "circle-color": "#f7f1e6", "circle-stroke-color": "#14181f", "circle-stroke-width": 1 },
  });
  map.addLayer(trainLayer);
  map.fitBounds([[-5.15, 41.3], [9.7, 51.12]], { padding: { top: 78, bottom: 118, left: 330, right: 350 }, duration: 0 });
  drawCharts();
  placeLabels();
  $("boot-fill").style.width = "100%";
  document.body.classList.add("ready");
  map.triggerRepaint();
});

map.on("move", placeLabels);
map.on("click", (event) => {
  const train = nearest(event.point.x, event.point.y, "train", 14);
  const station = nearest(event.point.x, event.point.y, "station", 12);
  if (mode !== "flow" && train && (!station || train.d < station.d)) selectTrain(train.index);
  else if (station) selectStation(station.index, true);
  else selection = null, renderInspector();
});
map.on("mousemove", (event) => {
  const train = mode === "flow" ? null : nearest(event.point.x, event.point.y, "train", 14);
  const station = nearest(event.point.x, event.point.y, "station", 12);
  const hit = train && (!station || train.d < station.d) ? train : station;
  const tip = $("tip");
  map.getCanvas().style.cursor = hit ? "pointer" : "";
  if (!hit) {
    tip.hidden = true;
    return;
  }
  tip.hidden = false;
  tip.style.left = `${event.point.x + 14}px`;
  tip.style.top = `${event.point.y + 14}px`;
  if (hit.kind === "train") {
    const tr = trains[hit.index];
    tip.innerHTML = `<b>${esc(CATS[tr.c].name)} ${esc(tr.n)}</b><br>${esc(stations[tr.s[0][0]].name)} → ${esc(stations[tr.s[tr.s.length - 1][0]].name)}`;
  } else {
    const s = stations[hit.index];
    let extra = "";
    if (mode === "access" && access && origin !== null && hit.index !== origin) {
      const dur = access.dur[hit.index];
      extra = dur >= 32767 ? "<br>Sans liaison" : `<br>${esc(formatDur(dur))} depuis ${esc(stations[origin].name)}`;
    }
    tip.innerHTML = `<b>${esc(s.name)}</b>${extra}`;
  }
});

document.querySelectorAll<HTMLButtonElement>(".modes button").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode as Mode));
});
document.querySelectorAll<HTMLButtonElement>(".cat").forEach((button) => {
  const cat = Number(button.dataset.cat);
  button.addEventListener("click", () => toggleCat(cat));
  button.addEventListener("dblclick", (event) => {
    event.preventDefault();
    isolateCat(cat);
  });
});
$("show-all").addEventListener("click", () => {
  mask = 7;
  syncCats();
});
$("play").addEventListener("click", () => {
  playing = !playing;
  syncPlay();
  map.triggerRepaint();
});
document.querySelectorAll<HTMLButtonElement>(".speeds button").forEach((button) => {
  button.addEventListener("click", () => {
    rate = Number(button.dataset.rate);
    document.querySelectorAll(".speeds button").forEach((el) => el.setAttribute("aria-pressed", el === button ? "true" : "false"));
  });
});
$("now").addEventListener("click", () => {
  clock = parisMinutes();
  map.triggerRepaint();
});
const track = $("track");
track.addEventListener("pointerdown", (event) => {
  scrubbing = true;
  track.setPointerCapture(event.pointerId);
  seek(event);
});
track.addEventListener("pointermove", (event) => {
  if (scrubbing) seek(event);
});
track.addEventListener("pointerup", () => {
  scrubbing = false;
});
window.addEventListener("resize", () => {
  drawCharts();
  placeLabels();
});
window.addEventListener("keydown", (event) => {
  const typing = document.activeElement === $("q");
  if (event.code === "Space" && !typing) {
    event.preventDefault();
    playing = !playing;
    syncPlay();
    map.triggerRepaint();
  } else if (event.key === "Escape") {
    selection = null;
    origin = null;
    access = null;
    clearAccessPaint();
    renderInspector();
    map.triggerRepaint();
  } else if (!typing && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    const step = event.altKey ? 60 : event.shiftKey ? 10 : 1;
    clock = (clock + (event.key === "ArrowRight" ? step : -step) + 1440) % 1440;
    map.triggerRepaint();
  } else if (event.key === "/" && !typing) {
    event.preventDefault();
    $("q").focus();
  }
});

const search = $<HTMLInputElement>("q");
const results = $<HTMLUListElement>("results");
let searchPick = 0;
search.addEventListener("input", () => renderSearch());
search.addEventListener("keydown", (event) => {
  const items = [...results.querySelectorAll("button")];
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    searchPick = (searchPick + (event.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(1, items.length);
    renderSearch();
  } else if (event.key === "Enter" && items[searchPick]) {
    event.preventDefault();
    items[searchPick].click();
  } else if (event.key === "Escape") {
    results.hidden = true;
    search.blur();
  }
});
search.addEventListener("focus", () => renderSearch());
document.addEventListener("click", (event) => {
  if (!(event.target as HTMLElement).closest(".search")) results.hidden = true;
});

worker.onmessage = (event) => {
  if (event.data.type === "ready") {
    workerReady = true;
    for (const job of waiting.splice(0)) worker.postMessage({ type: "query", ...job });
    return;
  }
  if (event.data.type !== "result" || event.data.id !== querySeq) return;
  const packed = { dur: event.data.dur as Int16Array, leave: event.data.leave as Int16Array };
  accessCache.set(`${origin}:${mask}`, packed);
  access = packed;
  paintAccess(true);
  renderInspector();
};

$("busy").addEventListener("click", (event) => {
  const button = (event.target as HTMLElement).closest("button");
  if (!button) return;
  selectStation(Number(button.dataset.i), true);
});
$("inspector").addEventListener("click", (event) => {
  const target = event.target as HTMLElement;
  const jump = target.closest<HTMLElement>("[data-train]");
  if (jump) selectTrain(Number(jump.dataset.train));
  if (target.id === "close-sheet") {
    selection = null;
    renderInspector();
  }
  if (target.id === "make-origin" && selection?.kind === "station") {
    setMode("access");
    setOrigin(selection.index);
  }
});

syncPlay();
syncCats();
applyMode();

function sampleFrame(): Frame {
  const now = performance.now();
  const dt = Math.min(0.05, (now - lastTick) / 1000);
  lastTick = now;
  if (playing && !scrubbing && !document.hidden) clock = (clock + dt * rate) % 1440;
  paintClock();
  const zoom = map.getZoom();
  const scale = zoom < 5.2 ? 0.75 : zoom > 8.6 ? 1.25 : 0.75 + ((zoom - 5.2) / 3.4) * 0.5;
  const dim = mode === "access" ? 0.42 : 1;
  let nCore = 0;
  let nTrail = 0;
  hits.length = 0;
  if (mode !== "flow") {
    for (let i = 0; i < trains.length; i++) {
      const tr = trains[i];
      if (((1 << tr.c) & mask) === 0) continue;
      const pos = locate(tr, clock);
      if (!pos) continue;
      const [x, y] = mercator(pos[0], pos[1]);
      const screen = map.project(pos);
      hits.push({ kind: "train", index: i, x: screen.x, y: screen.y });
      const selected = selection?.kind === "train" && selection.index === i;
      const fade = selected || selection?.kind !== "train" ? dim : dim * 0.28;
      const size = (tr.c === 0 ? 8.4 : tr.c === 1 ? 6.5 : 4.7) * scale * (selected ? 1.45 : 1);
      push(coreBuf, nCore++, x, y, CATS[tr.c].rgb, size, fade);
      if (selected) push(coreBuf, nCore++, x, y, [0.97, 0.95, 0.9], size * 1.7, 0.55);
      for (let k = 1; k <= 6; k++) {
        const back = locate(tr, clock - k * 1.1);
        if (!back) continue;
        const [bx, by] = mercator(back[0], back[1]);
        push(trailBuf, nTrail++, bx, by, CATS[tr.c].rgb, size * (1 - k * 0.1), fade * (0.45 - k * 0.06));
      }
    }
  }
  for (let i = 0; i < stations.length; i++) {
    if (stations[i].deps + stations[i].arrs < 8 && map.getZoom() < 7) continue;
    const screen = map.project([stations[i].lon, stations[i].lat]);
    if (screen.x < -20 || screen.y < -20 || screen.x > map.getCanvas().clientWidth + 20 || screen.y > map.getCanvas().clientHeight + 20) continue;
    hits.push({ kind: "station", index: i, x: screen.x, y: screen.y });
  }
  return { cores: coreBuf, nCore, trails: trailBuf, nTrail, animating: playing && !scrubbing && !document.hidden };
}
let lastTick = performance.now();

function locate(tr: Train, t: number): [number, number] | null {
  const stops = tr.s;
  const first = stops[0][2];
  const last = stops[stops.length - 1][1];
  if (t < first || t >= last) return null;
  for (let i = 0; i < stops.length - 1; i++) {
    const dep = stops[i][2];
    const arr = stops[i + 1][1];
    if (t < dep) return null;
    const geom = geoms[tr.p[i]];
    if (!geom) return [stations[stops[i][0]].lon, stations[stops[i][0]].lat];
    if (t <= arr) return pointAlong(geom, arr === dep ? 1 : (t - dep) / (arr - dep));
    if (t < stops[i + 1][2]) return pointAlong(geom, 1);
  }
  return null;
}

function selectTrain(index: number) {
  selection = { kind: "train", index };
  const tr = trains[index];
  const line: number[][] = [];
  const stops = {
    type: "Feature" as const,
    properties: {},
    geometry: { type: "MultiPoint" as const, coordinates: tr.s.map((st) => [stations[st[0]].lon, stations[st[0]].lat]) },
  };
  for (const pid of tr.p) {
    const g = geoms[pid];
    for (let i = 0; i < g.lon.length; i++) line.push([g.lon[i], g.lat[i]]);
  }
  (map.getSource("route") as GeoJSONSource).setData({
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: line },
  });
  (map.getSource("route-stops") as GeoJSONSource).setData(stops);
  const bounds = new maplibregl.LngLatBounds();
  for (const st of tr.s) bounds.extend([stations[st[0]].lon, stations[st[0]].lat]);
  map.fitBounds(bounds, { padding: { top: 90, bottom: 130, left: 340, right: 370 }, maxZoom: 9.2, duration: 800 });
  renderInspector();
}

function selectStation(index: number, fly: boolean) {
  selection = { kind: "station", index };
  clearRoute();
  if (fly) {
    const s = stations[index];
    map.fitBounds(new maplibregl.LngLatBounds([s.lon, s.lat], [s.lon, s.lat]), {
      padding: { top: 90, bottom: 130, left: 340, right: 370 },
      maxZoom: Math.max(map.getZoom(), 6.6),
      duration: 700,
    });
  }
  if (mode === "access") setOrigin(index);
  markSelection();
  renderInspector();
}

function setOrigin(index: number) {
  origin = index;
  const key = `${index}:${mask}`;
  const cached = accessCache.get(key);
  if (cached) {
    access = cached;
    paintAccess(false);
    renderInspector();
    return;
  }
  const id = ++querySeq;
  const job = { id, origin: index, mask };
  if (workerReady) worker.postMessage({ type: "query", ...job });
  else waiting.push(job);
  $("access-note").textContent = "Calcul des correspondances…";
}

function paintAccess(animate: boolean) {
  if (!access || origin === null) return;
  const dur = access.dur;
  reveal += 1;
  const token = reveal;
  for (let i = 0; i < stations.length; i++) {
    map.setFeatureState({ source: "stations", id: i }, { access: 1, bin: 5, origin: i === origin ? 1 : 0, on: selection?.kind === "station" && selection.index === i ? 1 : 0 });
  }
  const order: number[] = [];
  for (let i = 0; i < stations.length; i++) if (i !== origin && dur[i] < 32767) order.push(i);
  order.sort((a, b) => dur[a] - dur[b]);
  const counts = [0, 0, 0, 0, 0, 0];
  counts[0] = 1;
  for (const i of order) counts[binOf(dur[i])] += 1;
  counts[5] = stations.length - order.length - 1;
  document.querySelectorAll<HTMLElement>("[data-bin]").forEach((el) => {
    el.textContent = fmt(counts[Number(el.dataset.bin)]);
  });
  const note = `Depuis ${stations[origin].name}. Meilleur temps de la journée, attentes et correspondances comprises.`;
  const apply = (upto: number) => {
    for (let k = 0; k < upto; k++) {
      const i = order[k];
      map.setFeatureState({ source: "stations", id: i }, { bin: binOf(dur[i]) });
    }
  };
  if (!animate) {
    apply(order.length);
    $("access-note").textContent = note;
    return;
  }
  let cursor = 0;
  const step = () => {
    if (token !== reveal) return;
    cursor = Math.min(order.length, cursor + Math.ceil(order.length / 16));
    apply(cursor);
    if (cursor < order.length) requestAnimationFrame(step);
    else $("access-note").textContent = note;
  };
  requestAnimationFrame(step);
}

function clearAccessPaint() {
  reveal += 1;
  for (let i = 0; i < stations.length; i++) {
    map.setFeatureState({ source: "stations", id: i }, { access: 0, bin: 0, origin: 0, on: 0 });
  }
}

function markSelection() {
  for (let i = 0; i < stations.length; i++) {
    const on = (selection?.kind === "station" && selection.index === i) || origin === i ? 1 : 0;
    map.setFeatureState({ source: "stations", id: i }, { on, origin: origin === i ? 1 : 0 });
  }
}

function renderInspector() {
  const host = $("inspector");
  const detail = $("stats-detail");
  markSelection();
  if (!selection) {
    host.hidden = true;
    host.innerHTML = "";
    detail.hidden = false;
    clearRoute();
    return;
  }
  detail.hidden = true;
  host.hidden = false;
  if (selection.kind === "train") {
    const tr = trains[selection.index];
    const focus = focusStop(tr, clock);
    const rows = tr.s.map((st, si) => {
      const when = si === 0 ? formatClock(st[2]) : formatClock(st[1]);
      const conn = si === 0 ? "" : connections(tr, si);
      return `<div class="stop${si === focus ? " now" : ""}"><span class="when">${when}</span><span class="name">${esc(stations[st[0]].name)}</span></div>${conn}`;
    }).join("");
    host.innerHTML = `
      <div class="sheet-top"><div><span class="pill ${["", "ic", "ter"][tr.c]}">${esc(tr.b)} ${esc(tr.n)}</span><h3>${esc(stations[tr.s[0][0]].name)}</h3><p class="od">→ ${esc(stations[tr.s[tr.s.length - 1][0]].name)}</p></div><button class="ghost" id="close-sheet" type="button">Fermer</button></div>
      <div class="itinerary">${rows}</div>`;
    return;
  }
  const s = stations[selection.index];
  const reach = mode === "access" && access && origin !== null && selection.index !== origin
    ? `<p class="time-note"><b>${esc(formatDur(access.dur[selection.index]))}</b> depuis ${esc(stations[origin].name)}${access.dur[selection.index] < 32767 ? ` · départ ${formatClock(access.leave[selection.index])}` : ""}</p>`
    : "";
  const deps = board[selection.index].filter((ev) => ev.si < trains[ev.ti].s.length - 1 && ev.dep >= clock - 20 && ev.dep < 1440 && ((1 << trains[ev.ti].c) & mask) !== 0).slice(0, 28);
  const rows = deps.map((ev) => {
    const tr = trains[ev.ti];
    const past = ev.dep < clock ? " past" : "";
    return `<button class="dep${past}" type="button" data-train="${ev.ti}"><span class="when">${formatClock(ev.dep)}</span><i style="background:${CATS[tr.c].color}"></i><span class="dest">${esc(tr.b)} ${esc(tr.n)}<small>${esc(stations[tr.s[tr.s.length - 1][0]].name)}</small></span></button>`;
  }).join("");
  host.innerHTML = `
    <div class="sheet-top"><div><h3>${esc(s.name)}</h3><p class="od">${fmt(s.deps)} départs · ${fmt(s.arrs)} arrivées</p></div><button class="ghost" id="close-sheet" type="button">Fermer</button></div>
    ${reach}
    ${mode !== "access" ? `<button class="ghost" id="make-origin" type="button">Temps de parcours depuis cette gare</button>` : ""}
    <h2 style="margin-top:12px">Tableau des départs</h2>
    <div class="board">${rows || `<p class="hint">Aucun départ autour de cette heure.</p>`}</div>`;
}

function connections(tr: Train, si: number): string {
  const st = tr.s[si];
  const arr = st[1];
  const wait = atlas.xfer[st[0]] ?? 4;
  const found = board[st[0]].filter((ev) => {
    if (ev.ti === trains.indexOf(tr)) return false;
    const other = trains[ev.ti];
    if (ev.si >= other.s.length - 1) return false;
    if (((1 << other.c) & mask) === 0) return false;
    return ev.dep >= arr + wait && ev.dep <= arr + 40;
  }).slice(0, 3);
  if (!found.length) return "";
  return `<div class="conn">${found.map((ev) => {
    const other = trains[ev.ti];
    return `<button type="button" data-train="${ev.ti}">${formatClock(ev.dep)} ${esc(CATS[other.c].name)} ${esc(other.n)} → ${esc(stations[other.s[other.s.length - 1][0]].name)}</button>`;
  }).join("")}</div>`;
}

function focusStop(tr: Train, t: number): number {
  for (let i = 0; i < tr.s.length - 1; i++) {
    if (t < tr.s[i + 1][2]) return t >= tr.s[i + 1][1] ? i + 1 : i;
  }
  return tr.s.length - 1;
}

function clearRoute() {
  const empty = emptyCollection();
  const route = map.getSource("route") as GeoJSONSource | undefined;
  const stops = map.getSource("route-stops") as GeoJSONSource | undefined;
  route?.setData(empty);
  stops?.setData(empty);
}

function setMode(next: Mode) {
  mode = next;
  document.querySelectorAll<HTMLButtonElement>(".modes button").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.mode === next ? "true" : "false");
  });
  $("legend-cats").hidden = false;
  $("legend-access").hidden = next !== "access";
  $("legend-flow").hidden = next !== "flow";
  applyMode();
  if (next === "access" && selection?.kind === "station") setOrigin(selection.index);
  else if (next !== "access") {
    /* keep the painting only while the mode is open */
  }
  if (next !== "access") clearAccessPaint();
  if (next === "access" && origin !== null) {
    const cached = accessCache.get(`${origin}:${mask}`);
    if (cached) {
      access = cached;
      paintAccess(false);
    }
  }
  renderInspector();
  map.triggerRepaint();
}

function applyMode() {
  if (!map.getLayer("flow")) return;
  const flowMode = mode === "flow";
  map.setPaintProperty("flow", "line-color", flowMode ? flowLineColor() : runLineColor());
  map.setPaintProperty("flow", "line-width", widthExpr(flowMode ? 1 : 0.42));
  map.setLayoutProperty("flow-glow", "visibility", flowMode ? "visible" : "none");
  map.setPaintProperty("stations", "circle-opacity", mode === "access" ? 0.95 : 0.8);
  map.setPaintProperty("stations", "circle-radius", mode === "access"
    ? ["interpolate", ["linear"], ["zoom"], 4.8, 2.4, 7.5, 5.5, 10, 8]
    : ["interpolate", ["linear"], ["zoom"], 4.8, ["interpolate", ["linear"], ["get", "deps"], 0, 0.7, 40, 1.3, 200, 2.1], 8, ["interpolate", ["linear"], ["get", "deps"], 0, 1.6, 40, 2.6, 200, 4.2]]);
  map.setPaintProperty("stations", "circle-color", mode === "access"
    ? ["case", ["==", ["feature-state", "origin"], 1], "#fff8ea", ["==", ["feature-state", "access"], 1], ["match", ["feature-state", "bin"], 0, BIN_COLOR[0], 1, BIN_COLOR[1], 2, BIN_COLOR[2], 3, BIN_COLOR[3], 4, BIN_COLOR[4], BIN_COLOR[5]], "#d9d0c3"]
    : "#d9d0c3");
}

function toggleCat(cat: number) {
  const next = mask ^ (1 << cat);
  if (next === 0) return;
  mask = next;
  syncCats();
}
function isolateCat(cat: number) {
  mask = mask === 1 << cat ? 7 : 1 << cat;
  syncCats();
}
function syncCats() {
  document.querySelectorAll<HTMLButtonElement>(".cat").forEach((button) => {
    button.setAttribute("aria-pressed", (mask & (1 << Number(button.dataset.cat))) !== 0 ? "true" : "false");
  });
  $("show-all").hidden = mask === 7;
  if (mode === "access" && origin !== null) setOrigin(origin);
  renderInspector();
  map.triggerRepaint();
}

function paintClock() {
  const shown = formatNow(clock);
  if ($("hh").textContent !== shown.hh) $("hh").textContent = shown.hh;
  if ($("mm").textContent !== shown.mm) $("mm").textContent = shown.mm;
  if ($("ss").textContent !== shown.ss) $("ss").textContent = shown.ss;
  const u = `${(clock / 1440) * 100}%`;
  $("playhead").style.left = u;
  $("spark-play").style.left = u;
  const minute = Math.floor(clock);
  if (minute !== paintedMinute) {
    paintedMinute = minute;
    const counts = [0, 0, 0];
    for (const tr of trains) {
      if (((1 << tr.c) & mask) === 0) continue;
      if (clock >= tr.s[0][2] && clock < tr.s[tr.s.length - 1][1]) counts[tr.c] += 1;
    }
    const total = counts[0] + counts[1] + counts[2];
    $("active-total").textContent = fmt(total);
    document.querySelectorAll<HTMLElement>("[data-live]").forEach((el) => {
      el.textContent = fmt(counts[Number(el.dataset.live)]);
    });
    const max = Math.max(...counts, 1);
    $("bars").innerHTML = counts.map((count, i) => `<div class="bar-row"><span>${["TGV", "IC", "TER"][i]}</span><div class="bar"><i style="width:${(count / max) * 100}%;background:${CATS[i].color}"></i></div><span>${fmt(count)}</span></div>`).join("");
    const hour = Math.floor(clock / 60) % 24;
    if (hour !== paintedHour) {
      paintedHour = hour;
      $("hour-title").textContent = `Gares les plus actives · ${hour} h`;
      const rows = atlas.hourly[hour] || [];
      $("busy").innerHTML = rows.map(([index, count], rank) => `<li><button type="button" data-i="${index}"><span class="rank">${rank + 1}</span><span>${esc(stations[index].name)}</span><span class="rank">${count}</span></button></li>`).join("");
    }
  }
}
let paintedMinute = -1;
let paintedHour = -1;

function renderSearch() {
  const q = fold(search.value.trim());
  results.innerHTML = "";
  if (!q) {
    results.hidden = true;
    return;
  }
  const found = ranked.filter((i) => folded[i].includes(q)).slice(0, 8);
  searchPick = Math.min(searchPick, Math.max(0, found.length - 1));
  found.forEach((i, n) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-selected", n === searchPick ? "true" : "false");
    button.innerHTML = `<span>${esc(stations[i].name)}</span><small>${fmt(stations[i].deps)} dép.</small>`;
    button.addEventListener("click", () => {
      results.hidden = true;
      search.value = stations[i].name;
      selectStation(i, true);
    });
    li.append(button);
    results.append(li);
  });
  results.hidden = found.length === 0;
}

function placeLabels() {
  if (!map.getLayer("stations")) return;
  const host = $("labels");
  host.innerHTML = "";
  const zoom = map.getZoom();
  const limit = zoom < 5.5 ? 14 : zoom < 6.6 ? 32 : zoom < 8 ? 70 : 110;
  const chosen = new Set<number>(ranked.slice(0, limit));
  if (selection?.kind === "station") chosen.add(selection.index);
  if (origin !== null) chosen.add(origin);
  const taken: { x: number; y: number }[] = [];
  const canvas = map.getCanvas();
  const safe = { l: 330, r: canvas.clientWidth - 350, t: 70, b: canvas.clientHeight - 120 };
  const seas = [
    ["Manche", -1.7, 50.05],
    ["Mer du Nord", 2.5, 51.28],
    ["Golfe de Gascogne", -3.6, 45.15],
    ["Méditerranée", 5.15, 42.25],
    ["Corse", 9.05, 42.18],
  ] as const;
  for (const [name, lon, lat] of seas) {
    if (zoom > 7.4) continue;
    const p = map.project([lon, lat]);
    if (p.x < 40 || p.y < 40 || p.x > canvas.clientWidth - 40 || p.y > canvas.clientHeight - 40) continue;
    const el = document.createElement("div");
    el.className = "label sea";
    el.style.left = `${p.x}px`;
    el.style.top = `${p.y}px`;
    el.innerHTML = name === "Corse" ? "Corse<small>hors RFN</small>" : name;
    host.append(el);
  }
  const ordered = [...chosen].sort((a, b) => stations[b].deps - stations[a].deps);
  for (const i of ordered) {
    const s = stations[i];
    const p = map.project([s.lon, s.lat]);
    if (p.x < safe.l || p.x > safe.r || p.y < safe.t || p.y > safe.b) continue;
    if (taken.some((spot) => Math.abs(spot.x - p.x) < 70 && Math.abs(spot.y - p.y) < 16)) continue;
    taken.push(p);
    const el = document.createElement("div");
    el.className = s.deps > 120 ? "label major" : "label";
    el.style.left = `${p.x}px`;
    el.style.top = `${p.y}px`;
    el.textContent = s.name;
    host.append(el);
  }
}

function drawCharts() {
  drawArea($("profile"), 48);
  drawArea($("spark"), 54);
}
function drawArea(canvas: HTMLCanvasElement, height: number) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 300;
  canvas.width = Math.max(1, Math.floor(width * dpr));
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const max = Math.max(...atlas.profile.map((bin) => bin[0] + bin[1] + bin[2]), 1);
  const colors = ["#3dcec2", "#ef6b4a", "#e7b15a"];
  const order = [2, 1, 0];
  for (const cat of order) {
    ctx.beginPath();
    atlas.profile.forEach((bin, i) => {
      const x = (i / (atlas.profile.length - 1)) * width;
      let stack = 0;
      for (const other of order) {
        if (order.indexOf(other) > order.indexOf(cat)) break;
        stack += bin[other];
      }
      const y = height - (stack / max) * (height - 6) - 2;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    ctx.fillStyle = colors[cat];
    ctx.globalAlpha = cat === 2 ? 0.35 : 0.8;
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function seek(event: PointerEvent) {
  const rect = track.getBoundingClientRect();
  const u = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  clock = u * 1439.9;
  map.triggerRepaint();
}
function syncPlay() {
  $("play").setAttribute("aria-pressed", playing ? "true" : "false");
  $("play").setAttribute("aria-label", playing ? "Pause" : "Lecture");
  $("icon-play").hidden = playing;
  $("icon-pause").hidden = !playing;
}
function nearest(x: number, y: number, kind: Hit["kind"], radius: number) {
  let best: (Hit & { d: number }) | null = null;
  for (const hit of hits) {
    if (hit.kind !== kind) continue;
    const d = Math.hypot(hit.x - x, hit.y - y);
    if (d <= radius && (!best || d < best.d)) best = { ...hit, d };
  }
  return best;
}

function buildGeom(path: number[]): Geom {
  const lon: number[] = [];
  const lat: number[] = [];
  for (const signed of path) {
    const forward = signed >= 0;
    const edge = atlas.edges[forward ? signed : -signed - 1];
    const seq = forward ? edge : [...edge].reverse();
    for (const pt of seq) {
      const last = lon.length - 1;
      if (last >= 0 && Math.abs(lon[last] - pt[0]) < 1e-5 && Math.abs(lat[last] - pt[1]) < 1e-5) continue;
      lon.push(pt[0]);
      lat.push(pt[1]);
    }
  }
  if (lon.length === 0) {
    lon.push(0, 0);
    lat.push(0, 0);
  } else if (lon.length === 1) {
    lon.push(lon[0]);
    lat.push(lat[0]);
  }
  const cum = new Float64Array(lon.length);
  for (let i = 1; i < lon.length; i++) cum[i] = cum[i - 1] + meters(lon[i - 1], lat[i - 1], lon[i], lat[i]);
  return { lon: Float64Array.from(lon), lat: Float64Array.from(lat), cum, total: cum[cum.length - 1] };
}
function pointAlong(g: Geom, u: number): [number, number] {
  if (g.total <= 1) return [g.lon[0], g.lat[0]];
  const target = Math.min(g.total, Math.max(0, u * g.total));
  let lo = 0;
  let hi = g.cum.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (g.cum[mid] < target) lo = mid;
    else hi = mid;
  }
  const span = g.cum[hi] - g.cum[lo] || 1;
  const t = (target - g.cum[lo]) / span;
  return [g.lon[lo] + (g.lon[hi] - g.lon[lo]) * t, g.lat[lo] + (g.lat[hi] - g.lat[lo]) * t];
}
function push(buf: Float32Array, index: number, x: number, y: number, rgb: number[], size: number, alpha: number) {
  const o = index * 7;
  buf[o] = x;
  buf[o + 1] = y;
  buf[o + 2] = rgb[0];
  buf[o + 3] = rgb[1];
  buf[o + 4] = rgb[2];
  buf[o + 5] = size;
  buf[o + 6] = Math.max(0, alpha);
}
function mercator(lon: number, lat: number): [number, number] {
  const x = (lon + 180) / 360;
  const r = (lat * Math.PI) / 180;
  const y = (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2;
  return [x, y];
}
function meters(lon1: number, lat1: number, lon2: number, lat2: number) {
  const lat = ((lat1 + lat2) * 0.5 * Math.PI) / 180;
  const x = ((lon2 - lon1) * Math.PI) / 180 * Math.cos(lat) * 6371008.8;
  const y = ((lat2 - lat1) * Math.PI) / 180 * 6371008.8;
  return Math.hypot(x, y);
}
function binOf(min: number) {
  if (min < 60) return 0;
  if (min < 120) return 1;
  if (min < 180) return 2;
  if (min < 300) return 3;
  return 4;
}
function formatDur(min: number) {
  if (min >= 32767) return "Sans liaison dans la journée";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h <= 0 ? `${m} min` : `${h} h ${String(m).padStart(2, "0")}`;
}
function formatClock(min: number) {
  let value = Math.round(min);
  let mark = "";
  if (value < 0) {
    value += 1440;
    mark = " −1";
  } else if (value >= 1440) {
    value -= 1440;
    mark = " +1";
  }
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}${mark}`;
}
function formatNow(min: number) {
  const value = ((min % 1440) + 1440) % 1440;
  const hh = Math.floor(value / 60);
  const mm = Math.floor(value % 60);
  const ss = Math.floor((value * 60) % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return { hh: pad(hh), mm: pad(mm), ss: pad(ss) };
}
function parisMinutes() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Paris",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date());
  const pick = (type: string) => Number(parts.find((part) => part.type === type)?.value || 0);
  return pick("hour") * 60 + pick("minute") + pick("second") / 60;
}
function fmt(n: number) {
  return new Intl.NumberFormat("fr-FR").format(n);
}
function esc(value: string) {
  return value.replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch] || ch);
}
function fold(value: string) {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}
function emptyCollection(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}
function widthExpr(k: number): maplibregl.ExpressionSpecification {
  return ["interpolate", ["linear"], ["zoom"], 4.8, ["+", 0.25, ["*", ["sqrt", ["get", "n"]], 0.15 * k]], 7.4, ["+", 0.45, ["*", ["sqrt", ["get", "n"]], 0.34 * k]], 11, ["+", 0.8, ["*", ["sqrt", ["get", "n"]], 0.7 * k]]];
}
function runLineColor(): maplibregl.ExpressionSpecification {
  return ["case", ["==", ["get", "lgv"], 1], ["interpolate", ["linear"], ["get", "n"], 0, "#3a342c", 30, "#6a5436", 120, "#b08958", 280, "#e7d3a4"], ["interpolate", ["linear"], ["get", "n"], 0, "#243038", 30, "#3c5560", 120, "#7f9aa3", 280, "#d5ddd8"]];
}
function flowLineColor(): maplibregl.ExpressionSpecification {
  return ["interpolate", ["linear"], ["get", "n"], 0, "#1a242b", 16, "#2c4650", 50, "#3e7c86", 120, "#d9c7a0", 240, "#fff4dc"];
}

async function loadAtlas() {
  $("boot-status").textContent = "Lecture des horaires…";
  $("boot-fill").style.width = "35%";
  const data = await fetchJson<Atlas>(`${import.meta.env.BASE_URL}data/atlas.json`);
  $("boot-status").textContent = "Tracé du réseau ferré…";
  $("boot-fill").style.width = "72%";
  return data;
}
async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(url);
  return res.json() as Promise<T>;
}
