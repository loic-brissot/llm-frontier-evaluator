import { loadAll, CATS, CAT_LABEL, CAT_COLOR, DAY, fmtTime, fmtDur, normalize } from "./data.js";
import { Router, BANDS, UNREACHED, bandOf } from "./router.js";
import { drawProfile, drawStationHours } from "./charts.js";

const {
  Deck, MapView, WebMercatorViewport, FlyToInterpolator, SolidPolygonLayer, PathLayer,
  ScatterplotLayer, TextLayer, TripsLayer, CollisionFilterExtension,
} = window.deck;

const $ = (s) => document.querySelector(s);
const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const ADDITIVE = {
  depthCompare: "always",
  blendColorOperation: "add",
  blendColorSrcFactor: "src-alpha",
  blendColorDstFactor: "one",
  blendAlphaOperation: "add",
  blendAlphaSrcFactor: "one",
  blendAlphaDstFactor: "one-minus-src-alpha",
};
const NO_DEPTH = { depthCompare: "always" };
const BRAND_COLOR = {
  "TGV INOUI": [255, 79, 126], OUIGO: [255, 110, 190], "TGV Lyria": [255, 96, 96], ICE: [240, 240, 255],
  Eurostar: [255, 214, 92], "Intercités": [255, 184, 74], "Intercités de nuit": [168, 140, 255],
  TER: [63, 200, 255], "Tram-train": [110, 240, 200], Navette: [120, 220, 255],
};

const state = {
  t: 7.75 * 3600,
  playing: true,
  speed: 300,
  mode: "pulse",
  catOn: [true, true, true],
  hoverCat: -1,
  sel: null, // {type:'trip', k} | {type:'station', s}
  follow: false,
  reach: null,
  reachMode: "best",
  reachPin: -1,
  hoverStation: -1,
  hoverJourney: null,
  busyMode: "now",
  boardTab: "dep",
  view: null,
};

let M, R, deckgl;
let lastFrame = performance.now();
let lastMinute = -1;
const cache = {};

// ------------------------------------------------------------------ boot
(async function boot() {
  try {
    M = await loadAll((p, name) => {
      $("#loader-bar").style.width = `${Math.round(p * 70)}%`;
      $("#loader-msg").textContent = `Loaded ${name}…`;
    });
    $("#loader-msg").textContent = "Indexing connections…";
    $("#loader-bar").style.width = "85%";
    await new Promise((r) => setTimeout(r, 20));
    R = new Router(M);
    prepare();
    initDeck();
    initUI();
    if (isSoftwareGL()) setLite(true, "software WebGL renderer");
    $("#loader-bar").style.width = "100%";
    setTimeout(() => $("#loader").classList.add("done"), 150);
    window.__railPulse = { ready: true, model: M, state, deck: deckgl };
    requestAnimationFrame(tick);
  } catch (err) {
    console.error(err);
    $("#loader-msg").textContent = `Failed to load data: ${err.message}`;
  }
})();

function prepare() {
  const { S, T, buf, segs } = M;
  // segment -> station endpoints
  M.segPair = new Int32Array(segs.length * 2).fill(-1);
  for (let k = 0; k < T.n; k++) {
    const st = T.stops[k];
    T.segs[k].forEach((sg, i) => {
      if (!sg) return;
      const si = Math.abs(sg) - 1;
      const a = st[4 * i], b = st[4 * (i + 1)];
      M.segPair[2 * si] = sg > 0 ? a : b;
      M.segPair[2 * si + 1] = sg > 0 ? b : a;
    });
  }
  // traffic profile, 5-minute bins, trains in circulation at the bin centre
  M.profile = CATS.map(() => new Float32Array(288));
  for (let k = 0; k < T.n; k++) {
    const b0 = Math.max(0, Math.ceil((T.start[k] - 150) / 300));
    const b1 = Math.min(287, Math.floor((T.end[k] - 150) / 300));
    for (let b = b0; b <= b1; b++) M.profile[T.cat[k]][b]++;
  }
  M.daily = [0, 0, 0];
  for (let k = 0; k < T.n; k++) if (!T.prev[k]) M.daily[T.cat[k]]++;

  M.stationIdx = [];
  for (let s = 0; s < S.n; s++) if (S.total[s] > 0) M.stationIdx.push(s);
  M.stationIdx.sort((a, b) => S.total[a] - S.total[b]);
  M.labelIdx = [...M.stationIdx].sort((a, b) => S.total[b] - S.total[a]).slice(0, 420);
  M.maxTotal = Math.max(...S.total);
  M.corrIdx = M.corr.path.map((_, i) => i);
  M.corrMax = Math.max(...M.corr.c.map((c) => c[0] + c[1] + c[2]));

  const n = T.n;
  M.heads = {
    pos: new Float32Array(n * 2), col: new Uint8ClampedArray(n * 4), rad: new Float32Array(n),
    halo: new Uint8ClampedArray(n * 4), haloRad: new Float32Array(n), trip: new Int32Array(n), n: 0,
    active: [0, 0, 0],
  };
}

// ------------------------------------------------------------------ deck
function fitView(bounds, padding) {
  const w = window.innerWidth, h = window.innerHeight;
  const vp = new WebMercatorViewport({ width: w, height: h });
  const pad = padding || { left: w > 1100 ? 380 : 320, right: 40, top: 80, bottom: 160 };
  const { longitude, latitude, zoom } = vp.fitBounds(bounds, { padding: pad });
  return { longitude, latitude, zoom, pitch: 0, bearing: 0 };
}

function initDeck() {
  const v = fitView([[-4.9, 42.3], [8.3, 51.1]]);
  state.view = { ...v, minZoom: 4, maxZoom: 14 };
  deckgl = new Deck({
    parent: $("#map"),
    views: new MapView({ repeat: false }),
    initialViewState: state.view,
    controller: { inertia: 250, scrollZoom: { smooth: true, speed: 0.02 } },
    onViewStateChange: ({ viewState }) => {
      state.view = viewState;
      state.dirty = true;
    },
    onInteractionStateChange: (s) => { if (s.isDragging && state.follow) setFollow(false); },
    useDevicePixels: Math.min(window.devicePixelRatio || 1, 2),
    pickingRadius: 6,
    getCursor: ({ isDragging, isHovering }) => (isDragging ? "grabbing" : isHovering ? "pointer" : "grab"),
    onHover,
    onClick,
    layers: [],
  });
}

function flyTo(v, duration = 1400) {
  state.view = { ...state.view, ...v };
  deckgl.setProps({
    initialViewState: { ...state.view, transitionDuration: duration, transitionInterpolator: new FlyToInterpolator({ speed: 1.6 }) },
  });
}

function boundsOf(lons, lats) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < lons.length; i++) {
    x0 = Math.min(x0, lons[i]); x1 = Math.max(x1, lons[i]);
    y0 = Math.min(y0, lats[i]); y1 = Math.max(y1, lats[i]);
  }
  const pad = 0.05;
  return [[x0 - pad, y0 - pad], [x1 + pad, y1 + pad]];
}

function panelPadding() {
  const w = window.innerWidth;
  return { left: w > 1100 ? 380 : 320, right: $("#panel").classList.contains("hidden") ? 40 : 420, top: 90, bottom: 170 };
}

// ------------------------------------------------------------------ frame loop
function tick(now) {
  const gap = now - lastFrame;
  const dt = Math.min(0.1, gap / 1000);
  lastFrame = now;
  if (state.playing) {
    state.t += dt * state.speed;
    if (state.t >= DAY) state.t -= DAY;
    state.dirty = true;
  }
  const animating = !state.lite && (state.sel?.type === "station" || (state.mode === "reach" && state.reach));
  const minGap = state.lite ? 220 : 0;
  if ((state.dirty || animating) && now - (cache.lastRender || 0) >= minGap) {
    state.dirty = false;
    cache.lastRender = now;
    render();
  }
  watchFrameRate(gap);
  requestAnimationFrame(tick);
}

// Fall back to lightweight rendering (no comet trails) on software / very slow GPUs.
function watchFrameRate(gap) {
  if (state.lite || cache.userTrails) return;
  const f = (cache.fr ||= { n: 0, slow: 0 });
  f.n++;
  if (f.n < 15) return;
  if (gap > 180) f.slow++;
  if (f.slow >= 4) setLite(true, "slow GPU detected");
}

function setLite(on, why) {
  state.lite = on;
  deckgl?.setProps({ useDevicePixels: on ? 1 : Math.min(window.devicePixelRatio || 1, 2) });
  const b = $("#trails");
  if (b) {
    b.classList.toggle("on", !on);
    b.textContent = on ? "Trails off" : "Trails on";
    b.title = on ? `Comet trails disabled${why ? ` (${why})` : ""} — click to enable` : "Click to disable comet trails";
  }
  state.dirty = true;
}

function isSoftwareGL() {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
    const r = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
    return /swiftshader|llvmpipe|softpipe|software|basic render/i.test(r);
  } catch {
    return false;
  }
}

function computeHeads(t) {
  const { T, buf } = M;
  const H = M.heads;
  H.active = [0, 0, 0];
  let n = 0;
  const selK = state.sel?.type === "trip" ? state.sel.k : -1;
  const selStation = state.sel?.type === "station" ? state.sel.s : -1;
  const hc = state.hoverCat;
  for (let k = 0; k < T.n; k++) {
    if (t < T.start[k] || t > T.end[k]) continue;
    const c = T.cat[k];
    H.active[c]++;
    if (!state.catOn[c]) continue;
    const B = buf[c];
    let lo = T.vStart[k], hi = lo + T.vLen[k] - 1;
    const time = B.time;
    while (hi - lo > 1) {
      const m = (lo + hi) >> 1;
      if (time[m] <= t) lo = m;
      else hi = m;
    }
    const t0 = time[lo], t1 = time[hi];
    const f = t1 > t0 ? Math.min(1, Math.max(0, (t - t0) / (t1 - t0))) : 0;
    H.pos[2 * n] = B.pos[2 * lo] + (B.pos[2 * hi] - B.pos[2 * lo]) * f;
    H.pos[2 * n + 1] = B.pos[2 * lo + 1] + (B.pos[2 * hi + 1] - B.pos[2 * lo + 1]) * f;
    const col = CAT_COLOR[c];
    let alpha = 255;
    let dim = hc >= 0 && hc !== c;
    if (selStation >= 0) dim = dim || !tripServes(k, selStation);
    if (dim) alpha = 40;
    const isSel = k === selK;
    H.col[4 * n] = isSel ? 255 : Math.min(255, col[0] + 60);
    H.col[4 * n + 1] = isSel ? 255 : Math.min(255, col[1] + 60);
    H.col[4 * n + 2] = isSel ? 255 : Math.min(255, col[2] + 60);
    H.col[4 * n + 3] = alpha;
    H.rad[n] = (c === 0 ? 3.1 : c === 1 ? 2.7 : 2.0) * (isSel ? 2 : 1);
    H.halo[4 * n] = col[0];
    H.halo[4 * n + 1] = col[1];
    H.halo[4 * n + 2] = col[2];
    H.halo[4 * n + 3] = dim ? 8 : isSel ? 150 : c === 0 ? 70 : 55;
    H.haloRad[n] = (c === 0 ? 11 : c === 1 ? 9 : 6.5) * (isSel ? 2.2 : 1);
    H.trip[n] = k;
    n++;
  }
  H.n = n;
}

const servesCache = new Map();
function tripServes(k, s) {
  let set = servesCache.get(s);
  if (!set) {
    set = new Set(M.S.events[s].map((e) => e[1]));
    servesCache.set(s, set);
  }
  return set.has(k);
}

function trainPosition(k, t) {
  const { T, buf } = M;
  const B = buf[T.cat[k]];
  if (t < T.start[k] || t > T.end[k]) return null;
  let lo = T.vStart[k], hi = lo + T.vLen[k] - 1;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (B.time[m] <= t) lo = m;
    else hi = m;
  }
  const f = B.time[hi] > B.time[lo] ? (t - B.time[lo]) / (B.time[hi] - B.time[lo]) : 0;
  const lon = B.pos[2 * lo] + (B.pos[2 * hi] - B.pos[2 * lo]) * f;
  const lat = B.pos[2 * lo + 1] + (B.pos[2 * hi + 1] - B.pos[2 * lo + 1]) * f;
  const kx = Math.cos((lat * Math.PI) / 180) * 111.32;
  const dkm = Math.hypot((B.pos[2 * hi] - B.pos[2 * lo]) * kx, (B.pos[2 * hi + 1] - B.pos[2 * lo + 1]) * 110.54);
  const dt = B.time[hi] - B.time[lo];
  return { lon, lat, kmh: dt > 0 ? (dkm / dt) * 3600 : 0 };
}

function render() {
  computeHeads(state.t);
  if (state.follow && state.sel?.type === "trip") {
    const p = trainPosition(state.sel.k, state.t);
    if (p) {
      state.view = { ...state.view, longitude: p.lon, latitude: p.lat };
      deckgl.setProps({ initialViewState: { ...state.view, transitionDuration: 0 } });
    }
  }
  deckgl.setProps({ layers: buildLayers() });
  updateHUD();
}

// ------------------------------------------------------------------ layers
function staticLayers() {
  if (cache.base) return cache.base;
  const { land, deps, regs } = M.basemap;
  cache.base = [
    new SolidPolygonLayer({
      id: "land", data: land, getPolygon: (d) => d.ring, positionFormat: "XY",
      getFillColor: (d) => (d.iso === "FRA" ? [14, 28, 50] : [11, 20, 36]), parameters: NO_DEPTH,
    }),
    new PathLayer({
      id: "deps", data: deps, getPath: (d) => d.ring, positionFormat: "XY", _pathType: "loop",
      getColor: [70, 110, 160, 34], widthUnits: "pixels", getWidth: 0.6, parameters: NO_DEPTH,
    }),
    new PathLayer({
      id: "regs", data: regs, getPath: (d) => d.ring, positionFormat: "XY", _pathType: "loop",
      getColor: [95, 140, 200, 60], widthUnits: "pixels", getWidth: 1, parameters: NO_DEPTH,
    }),
    new PathLayer({
      id: "coast", data: land, getPath: (d) => d.ring, positionFormat: "XY", _pathType: "loop",
      getColor: (d) => (d.iso === "FRA" ? [100, 150, 210, 150] : [70, 100, 140, 90]), widthUnits: "pixels",
      getWidth: (d) => (d.iso === "FRA" ? 1.2 : 0.8), parameters: NO_DEPTH,
    }),
  ];
  return cache.base;
}

function corridorCount(i) {
  const c = M.corr.c[i];
  return (state.catOn[0] ? c[0] : 0) + (state.catOn[1] ? c[1] : 0) + (state.catOn[2] ? c[2] : 0);
}

const FLOW_RAMP = [
  [0, [34, 70, 130]], [0.22, [36, 130, 225]], [0.45, [80, 205, 255]], [0.7, [190, 245, 255]], [1, [255, 250, 228]],
];
export function flowColor(v) {
  for (let i = 1; i < FLOW_RAMP.length; i++) {
    if (v <= FLOW_RAMP[i][0]) {
      const [a, ca] = FLOW_RAMP[i - 1], [b, cb] = FLOW_RAMP[i];
      const f = (v - a) / (b - a);
      return [0, 1, 2].map((j) => Math.round(ca[j] + (cb[j] - ca[j]) * f));
    }
  }
  return FLOW_RAMP[FLOW_RAMP.length - 1][1];
}
const flowV = (n) => Math.sqrt(n / M.corrMax);

function corridorLayers() {
  const key = state.catOn.join() + state.mode;
  const flow = state.mode === "flow";
  const common = {
    data: M.corrIdx, getPath: (i) => M.corr.path[i], positionFormat: "XY", widthUnits: "pixels",
    updateTriggers: { getColor: key, getWidth: key }, capRounded: true, jointRounded: true,
  };
  const layers = [];
  if (flow) {
    layers.push(new PathLayer({
      ...common, id: "corr-glow",
      getColor: (i) => { const n = corridorCount(i); return n ? [...flowColor(flowV(n)), Math.round(10 + 40 * flowV(n))] : [0, 0, 0, 0]; },
      getWidth: (i) => { const n = corridorCount(i); return n ? 3 + 16 * flowV(n) : 0; },
      parameters: ADDITIVE,
    }));
  }
  layers.push(new PathLayer({
    ...common, id: "corridors", pickable: flow, autoHighlight: flow, highlightColor: [255, 255, 255, 90],
    getColor: (i) => {
      const n = corridorCount(i);
      if (flow) return n ? [...flowColor(flowV(n)), 245] : [40, 58, 84, 120];
      if (state.mode === "reach") return [34, 50, 74, n ? 160 : 90];
      return n ? [44 + Math.round(30 * flowV(n)), 78 + Math.round(50 * flowV(n)), 118 + Math.round(60 * flowV(n)), 130 + Math.round(100 * flowV(n))] : [30, 46, 68, 110];
    },
    getWidth: (i) => {
      const n = corridorCount(i);
      if (flow) return n ? 0.7 + 6.5 * flowV(n) : 0.5;
      return n ? 0.8 + 1.4 * flowV(n) : 0.6;
    },
    parameters: NO_DEPTH,
  }));
  return layers;
}

// Trails are uploaded for the trains running inside a sliding time window only, which keeps
// the GPU path buffers ~8x smaller than the whole day.
function trailWindow() {
  const t = state.t;
  const W = cache.win;
  if (W && t >= W.from && t <= W.to && W.cats === state.catOn.join()) return W.data;
  const span = Math.min(3 * 3600, Math.max(1800, state.speed * 10));
  const from = t - 120, to = t + span;
  const trail = 1500;
  const { T, buf } = M;
  const data = buf.map((B, c) => {
    const ks = [];
    let nv = 0;
    for (const k of B.trips) {
      if (T.start[k] <= to && T.end[k] + trail >= from) { ks.push(k); nv += T.vLen[k]; }
    }
    const pos = new Float32Array(nv * 2), time = new Float32Array(nv), startIndices = new Int32Array(ks.length);
    let w = 0;
    ks.forEach((k, i) => {
      startIndices[i] = w;
      const a = T.vStart[k], n = T.vLen[k];
      pos.set(B.pos.subarray(2 * a, 2 * (a + n)), 2 * w);
      time.set(B.time.subarray(a, a + n), w);
      w += n;
    });
    return { length: ks.length, startIndices, attributes: { getPath: { value: pos, size: 2 }, getTimestamps: { value: time, size: 1 } } };
  });
  cache.win = { from, to, data, cats: state.catOn.join() };
  return data;
}

function tripLayers() {
  if (state.mode === "reach" || state.lite) return [];
  const flow = state.mode === "flow";
  return trailWindow().map((data, c) => {
    const dim = state.hoverCat >= 0 && state.hoverCat !== c;
    return new TripsLayer({
      id: `trips-${c}`, data, _pathType: "open",
      getColor: CAT_COLOR[c], widthUnits: "pixels", getWidth: c === 0 ? 2.4 : c === 1 ? 2 : 1.5,
      widthMinPixels: 1, capRounded: true, jointRounded: true,
      opacity: flow ? 0.25 : dim ? 0.12 : state.sel?.type === "station" ? 0.35 : 0.9,
      trailLength: c === 0 ? 1500 : 1200, fadeTrail: true, currentTime: state.t,
      visible: state.catOn[c], parameters: ADDITIVE,
    });
  });
}

function headLayers() {
  if (state.mode === "reach") return [];
  const H = M.heads;
  const n = H.n;
  const flow = state.mode === "flow";
  const pos = H.pos.subarray(0, n * 2);
  return [
    !flow && new ScatterplotLayer({
      id: "heads-halo",
      data: { length: n, attributes: { getPosition: { value: pos, size: 2 }, getFillColor: { value: H.halo.subarray(0, n * 4), size: 4 }, getRadius: { value: H.haloRad.subarray(0, n), size: 1 } } },
      radiusUnits: "pixels", opacity: flow ? 0.4 : 1, parameters: ADDITIVE,
    }),
    new ScatterplotLayer({
      id: "heads",
      data: { length: n, attributes: { getPosition: { value: pos, size: 2 }, getFillColor: { value: H.col.subarray(0, n * 4), size: 4 }, getRadius: { value: H.rad.subarray(0, n), size: 1 } } },
      radiusUnits: "pixels", radiusScale: flow ? 0.7 : 1, opacity: flow ? 0.75 : 1, pickable: true, parameters: NO_DEPTH,
    }),
  ].filter(Boolean);
}

function stationColor(s) {
  if (state.mode === "reach" && state.reach) {
    if (s === state.reach.src) return [255, 255, 255, 255];
    const b = bandOf(state.reach.dur[s]);
    return b < 0 ? [...UNREACHED, 130] : [...BANDS[b].color, 255];
  }
  if (state.mode === "flow") return [170, 200, 235, 110];
  return [190, 215, 245, 150];
}

function stationRadius(s) {
  const base = 1.1 + 4.2 * Math.sqrt(M.S.total[s] / M.maxTotal);
  if (state.mode === "reach") return base + 1.3;
  return base;
}

function stationLayers() {
  const jdim = !!state.hoverJourney;
  const key = `${state.mode}|${state.reach?.src}|${state.reach?.mode}|${state.reach?.t0}|${jdim}`;
  const layers = [];
  if (state.mode === "reach" && state.reach) {
    layers.push(new ScatterplotLayer({
      id: "stations-glow", data: M.stationIdx, getPosition: (s) => [M.S.lon[s], M.S.lat[s]],
      getRadius: (s) => (isFinite(state.reach.dur[s]) ? stationRadius(s) * 2.4 : 0),
      getFillColor: (s) => { const b = bandOf(state.reach.dur[s]); return b < 0 ? [0, 0, 0, 0] : [...BANDS[b].color, jdim ? 8 : 30]; },
      radiusUnits: "pixels", parameters: ADDITIVE, updateTriggers: { getFillColor: key, getRadius: key },
    }));
  }
  layers.push(new ScatterplotLayer({
    id: "stations", data: M.stationIdx, getPosition: (s) => [M.S.lon[s], M.S.lat[s]],
    getRadius: stationRadius, getFillColor: stationColor, radiusUnits: "pixels",
    stroked: state.mode !== "reach", getLineColor: [5, 10, 20, 200], lineWidthUnits: "pixels", getLineWidth: 0.5,
    pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 255],
    updateTriggers: { getFillColor: key, getRadius: key }, parameters: NO_DEPTH,
  }));
  return layers;
}

function labelLayer() {
  const z = state.view?.zoom ?? 5.5;
  const reach = state.mode === "reach" && state.reach;
  return new TextLayer({
    id: "labels", data: M.labelIdx,
    getPosition: (s) => [M.S.lon[s], M.S.lat[s]],
    getText: (s) => (reach && isFinite(state.reach.dur[s]) && s !== state.reach.src ? `${M.S.name[s]}  ${fmtDur(state.reach.dur[s])}` : M.S.name[s]),
    getSize: (s) => (M.S.total[s] > 250 ? 12 : 11),
    getColor: (s) => (reach && s !== state.reach.src ? (bandOf(state.reach.dur[s]) >= 0 ? [...BANDS[bandOf(state.reach.dur[s])].color, 230] : [120, 135, 155, 160]) : [205, 222, 245, 210]),
    getPixelOffset: [0, -12], fontFamily: "Inter, system-ui, -apple-system, sans-serif", fontWeight: 500,
    characterSet: "auto", fontSettings: { sdf: true, fontSize: 48, buffer: 6 }, outlineWidth: 3, outlineColor: [3, 8, 16, 230],
    extensions: [new CollisionFilterExtension()], collisionEnabled: true,
    getCollisionPriority: (s) => (s === state.reach?.src ? 1000 : Math.round((M.S.total[s] / M.maxTotal) * 990)),
    collisionTestProps: { sizeScale: 2.2 },
    updateTriggers: { getText: `${reach && state.reach.src}|${state.reach?.mode}|${state.reach?.t0}`, getColor: `${reach && state.reach.src}|${state.reach?.t0}` },
    visible: z > 4.6, parameters: NO_DEPTH,
  });
}

function tripPath(k, i0 = 0, i1 = null) {
  const { T, buf } = M;
  const B = buf[T.cat[k]];
  const sv = T.stopV[k];
  const a = i0 === 0 ? T.vStart[k] : sv[i0];
  const b = i1 === null ? T.vStart[k] + T.vLen[k] - 1 : sv[i1];
  return B.pos.subarray(2 * a, 2 * (b + 1));
}

function selectionLayers() {
  const out = [];
  const sel = state.sel;
  if (sel?.type === "trip" && state.mode !== "reach") {
    const k = sel.k;
    const col = CAT_COLOR[M.T.cat[k]];
    const path = tripPath(k);
    out.push(new PathLayer({
      id: "sel-glow", data: [path], getPath: (d) => d, positionFormat: "XY", getColor: [...col, 70],
      widthUnits: "pixels", getWidth: 12, capRounded: true, jointRounded: true, parameters: ADDITIVE,
    }));
    out.push(new PathLayer({
      id: "sel-path", data: [path], getPath: (d) => d, positionFormat: "XY", getColor: [255, 255, 255, 230],
      widthUnits: "pixels", getWidth: 2.2, capRounded: true, jointRounded: true, parameters: NO_DEPTH,
    }));
    const st = M.T.stops[k];
    const stops = [];
    for (let i = 0; i < st.length / 4; i++) stops.push({ s: st[4 * i], i, t: st[4 * i + 1] });
    out.push(new ScatterplotLayer({
      id: "sel-stops", data: stops, getPosition: (d) => [M.S.lon[d.s], M.S.lat[d.s]],
      getRadius: (d) => (d.i === 0 || d.i === stops.length - 1 ? 5 : 3.5), radiusUnits: "pixels",
      getFillColor: (d) => (d.t <= state.t ? [...col, 255] : [8, 14, 26, 255]), stroked: true,
      getLineColor: [...col, 255], lineWidthUnits: "pixels", getLineWidth: 1.6, pickable: true,
      updateTriggers: { getFillColor: Math.floor(state.t / 60) }, parameters: NO_DEPTH,
    }));
    out.push(new TextLayer({
      id: "sel-stop-labels", data: stops, getPosition: (d) => [M.S.lon[d.s], M.S.lat[d.s]],
      getText: (d) => `${M.S.name[d.s]} ${fmtTime(d.i === 0 ? st[2] : d.t)}`, getSize: 11,
      getColor: [255, 255, 255, 235], getPixelOffset: [10, 0], getTextAnchor: "start", getAlignmentBaseline: "center",
      characterSet: "auto", fontSettings: { sdf: true, fontSize: 48, buffer: 6 }, outlineWidth: 3, outlineColor: [3, 8, 16, 240],
      fontFamily: "Inter, system-ui, sans-serif", fontWeight: 500,
      extensions: [new CollisionFilterExtension()], collisionEnabled: true, collisionGroup: "sel",
      getCollisionPriority: (d) => (d.i === 0 || d.i === stops.length - 1 ? 1000 : Math.round((M.S.total[d.s] / M.maxTotal) * 990)),
      parameters: NO_DEPTH,
    }));
  }
  if (sel?.type === "station" && state.mode !== "reach") {
    const s = sel.s;
    if (cache.stationPathsFor !== s) {
      const trips = [...new Set(M.S.events[s].map((e) => e[1]))].filter((k) => !M.T.prev[k]);
      cache.stationPaths = trips.map((k) => ({ k, path: tripPath(k), c: M.T.cat[k] }));
      cache.stationPathsFor = s;
    }
    out.push(new PathLayer({
      id: "station-routes", data: cache.stationPaths.filter((d) => state.catOn[d.c]), getPath: (d) => d.path, positionFormat: "XY",
      getColor: (d) => [...CAT_COLOR[d.c], 110], widthUnits: "pixels", getWidth: (d) => (d.c === 0 ? 3 : 2.2), capRounded: true, jointRounded: true,
      parameters: NO_DEPTH, updateTriggers: { data: state.catOn.join() },
    }));
    out.push(pulseRing(s, [143, 227, 255]));
  }
  return out;
}

function pulseRing(s, col) {
  const ph = (performance.now() / 1400) % 1;
  return new ScatterplotLayer({
    id: `ring-${s}`, data: [s], getPosition: (d) => [M.S.lon[d], M.S.lat[d]], radiusUnits: "pixels",
    getRadius: 8 + ph * 26, filled: false, stroked: true, lineWidthUnits: "pixels", getLineWidth: 2,
    getLineColor: [...col, Math.round(255 * (1 - ph))], updateTriggers: { getRadius: ph, getLineColor: ph },
    parameters: NO_DEPTH,
  });
}

function reachLayers() {
  if (state.mode !== "reach" || !state.reach) return [];
  const r = state.reach;
  const key = `${r.src}|${r.mode}|${r.t0}|${state.catOn.join()}`;
  if (cache.reachKey !== key) {
    const data = [];
    for (let si = 0; si < M.segs.length; si++) {
      const a = M.segPair[2 * si], b = M.segPair[2 * si + 1];
      if (a < 0) continue;
      const da = r.dur[a], db = r.dur[b];
      if (!isFinite(da) || !isFinite(db)) continue;
      data.push({ si, d: Math.max(da, db) });
    }
    data.sort((x, y) => y.d - x.d);
    cache.reachSegs = data;
    cache.reachKey = key;
  }
  const dim = !!state.hoverJourney;
  const ckey = `${key}|${dim}`;
  const out = [
    new PathLayer({
      id: "reach-glow", data: cache.reachSegs, getPath: (d) => M.segs[d.si], positionFormat: "XY",
      getColor: (d) => [...BANDS[bandOf(d.d)].color, dim ? 6 : 26], widthUnits: "pixels", getWidth: 6,
      capRounded: true, jointRounded: true, parameters: ADDITIVE, updateTriggers: { getColor: ckey },
    }),
    new PathLayer({
      id: "reach-net", data: cache.reachSegs, getPath: (d) => M.segs[d.si], positionFormat: "XY",
      getColor: (d) => [...BANDS[bandOf(d.d)].color, dim ? 80 : 210], widthUnits: "pixels", getWidth: 1.6,
      capRounded: true, jointRounded: true, parameters: NO_DEPTH, updateTriggers: { getColor: ckey },
    }),
  ];
  const j = state.hoverJourney;
  if (j) {
    const paths = j.legs.map((l) =>
      l.type === "train" ? { path: tripPath(l.trip, l.fromSeq, l.toSeq), c: M.T.cat[l.trip] }
        : { path: new Float32Array([M.S.lon[l.from], M.S.lat[l.from], M.S.lon[l.to], M.S.lat[l.to]]), c: -1 });
    out.push(new PathLayer({
      id: "journey-glow", data: paths, getPath: (d) => d.path, positionFormat: "XY",
      getColor: (d) => (d.c < 0 ? [255, 255, 255, 60] : [...CAT_COLOR[d.c], 120]), widthUnits: "pixels", getWidth: 12,
      capRounded: true, jointRounded: true, parameters: ADDITIVE,
    }));
    out.push(new PathLayer({
      id: "journey", data: paths, getPath: (d) => d.path, positionFormat: "XY",
      getColor: [255, 255, 255, 255], widthUnits: "pixels", getWidth: 2.5,
      capRounded: true, jointRounded: true, parameters: NO_DEPTH,
    }));
    const xfers = j.legs.slice(1).map((l) => l.from);
    out.push(new ScatterplotLayer({
      id: "journey-xfers", data: xfers, getPosition: (s) => [M.S.lon[s], M.S.lat[s]], radiusUnits: "pixels",
      getRadius: 5, getFillColor: [255, 255, 255, 255], stroked: true, getLineColor: [10, 16, 30], lineWidthUnits: "pixels", getLineWidth: 2,
      parameters: NO_DEPTH,
    }));
  }
  return out;
}

function buildLayers() {
  const layers = [...staticLayers(), ...corridorLayers()];
  layers.push(...reachLayers());
  if (state.sel?.type === "station") layers.push(...selectionLayers().filter((l) => l.id === "station-routes"));
  layers.push(...tripLayers(), ...headLayers());
  layers.push(...stationLayers());
  if (state.sel?.type === "trip") layers.push(...selectionLayers());
  if (state.sel?.type === "station") layers.push(...selectionLayers().filter((l) => l.id !== "station-routes"));
  if (state.mode === "reach" && state.reach) layers.push(pulseRing(state.reach.src, [255, 255, 255]));
  layers.push(labelLayer());
  return layers;
}

// ------------------------------------------------------------------ interaction
function onHover(info) {
  const tip = $("#tooltip");
  let html = null;
  const id = info.layer?.id;
  if (id === "heads" && info.index >= 0) {
    const k = M.heads.trip[info.index];
    html = tripTooltip(k);
  } else if ((id === "stations" || id === "sel-stops") && info.index >= 0) {
    const s = id === "stations" ? info.object : info.object.s;
    html = stationTooltip(s);
    if (state.mode === "reach" && state.reach && state.hoverStation !== s) {
      state.hoverStation = s;
      if (state.reachPin < 0) state.hoverJourney = R.journey(state.reach, s);
      if (state.reachPin < 0) renderReachJourney(s, state.hoverJourney);
    }
  } else if (id === "corridors" && info.index >= 0) {
    const i = info.object;
    const c = M.corr.c[i];
    const code = M.corr.line[i];
    html = `<div class="tt-h">RFN line ${code.slice(0, 3)} ${code.slice(3)}</div>
      <div class="mono">${c[0] + c[1] + c[2]} trains / day</div>
      <div class="tt-s"><span style="color:${rgb(CAT_COLOR[0])}">TGV ${c[0]}</span> · <span style="color:${rgb(CAT_COLOR[1])}">Intercités ${c[1]}</span> · <span style="color:${rgb(CAT_COLOR[2])}">TER ${c[2]}</span></div>`;
  }
  if (!html && state.mode === "reach" && state.hoverStation >= 0 && state.reachPin < 0) {
    state.hoverStation = -1;
    state.hoverJourney = null;
  }
  if (html) {
    tip.innerHTML = html;
    tip.style.display = "block";
    const x = Math.min(info.x + 16, window.innerWidth - 320);
    tip.style.left = `${x}px`;
    tip.style.top = `${info.y + 16}px`;
  } else tip.style.display = "none";
}

function badge(k) {
  const b = M.T.brand[k];
  const c = BRAND_COLOR[b] || CAT_COLOR[M.T.cat[k]];
  return `<span class="badge" style="background:${rgb(c)}">${b.toUpperCase()}</span>`;
}

function tripTooltip(k) {
  const T = M.T;
  const p = trainPosition(k, state.t);
  const nx = nextStop(k, state.t);
  return `<div class="tt-h">${badge(k)} <span class="mono">${T.num[k]}</span></div>
    <div>${M.S.name[T.orig[k]]} → ${M.S.name[T.dest[k]]}</div>
    <div class="tt-s mono">${fmtTime(T.start[k])} – ${fmtTime(T.end[k])}${p ? ` · ${Math.round(p.kmh)} km/h` : ""}</div>
    ${nx ? `<div class="tt-s">${nx.at ? "At" : "Next"}: ${M.S.name[nx.s]} <span class="mono">${fmtTime(nx.t)}</span></div>` : ""}`;
}

function stationTooltip(s) {
  const S = M.S;
  const c = S.calls[s];
  let extra = "";
  if (state.mode === "reach" && state.reach) {
    const d = state.reach.dur[s];
    extra = s === state.reach.src ? `<div class="tt-s">Origin</div>`
      : `<div class="mono" style="color:${isFinite(d) ? rgb(BANDS[bandOf(d)].color) : "#889"}">${isFinite(d) ? fmtDur(d) : "not reachable"}${isFinite(d) && state.reach.mode === "best" ? ` · leave ${fmtTime(state.reach.t0s[s])}` : ""}</div>`;
  }
  return `<div class="tt-h">${S.name[s]}</div>
    <div class="tt-s">${S.total[s]} trains / day · <span style="color:${rgb(CAT_COLOR[0])}">${c[0]}</span> / <span style="color:${rgb(CAT_COLOR[1])}">${c[1]}</span> / <span style="color:${rgb(CAT_COLOR[2])}">${c[2]}</span></div>${extra}`;
}

function onClick(info) {
  $("#tooltip").style.display = "none";
  const id = info.layer?.id;
  if (id === "heads" && info.index >= 0) return selectTrip(M.heads.trip[info.index]);
  if (id === "stations" && info.index >= 0) {
    if (state.mode === "reach") return setReachOrigin(info.object);
    return selectStation(info.object);
  }
  if (id === "sel-stops" && info.object) return selectStation(info.object.s);
  if (id === "corridors") return;
  if (!info.layer) {
    if (state.mode === "reach" && state.reachPin >= 0) { state.reachPin = -1; state.hoverJourney = null; renderReachPanel(); return; }
    if (state.mode !== "reach") closePanel();
  }
}

function nextStop(k, t) {
  const st = M.T.stops[k];
  const ns = st.length / 4;
  for (let i = 0; i < ns; i++) {
    const arr = st[4 * i + 1], dep = st[4 * i + 2];
    if (t <= arr) return { s: st[4 * i], t: arr, i, at: false };
    if (t <= dep) return { s: st[4 * i], t: dep, i, at: true };
  }
  return null;
}

// ------------------------------------------------------------------ selection panels
function openPanel(html) {
  const p = $("#panel");
  p.classList.remove("hidden");
  $("#panel-body").innerHTML = html;
  $("#panel-body").scrollTop = 0;
}
function closePanel() {
  $("#panel").classList.add("hidden");
  state.sel = null;
  setFollow(false);
  if (state.mode === "reach") { state.mode = "reach"; }
  updateLegend();
}

function selectTrip(k, fly = false) {
  if (state.mode === "reach") setMode("pulse");
  state.sel = { type: "trip", k };
  renderTripPanel();
  if (fly) {
    const p = tripPath(k);
    const lons = [], lats = [];
    for (let i = 0; i < p.length; i += 2) { lons.push(p[i]); lats.push(p[i + 1]); }
    flyTo(fitView(boundsOf(lons, lats), panelPadding()));
  }
  // jump the clock onto the train if it is not running
  const T = M.T;
  if (state.t < T.start[k] - 1 || state.t > T.end[k] + 1) {
    if (fly) state.t = Math.max(0, Math.min(DAY - 1, T.start[k]));
  }
}

function connectionsAt(k, i) {
  const T = M.T, S = M.S;
  const st = T.stops[k];
  const s = st[4 * i];
  const arr = st[4 * i + 1];
  const res = [];
  const stations = [[s, 0], ...S.foot[s]];
  const ns = st.length / 4;
  const nextS = i < ns - 1 ? st[4 * (i + 1)] : -1;
  for (const [x, walk] of stations) {
    const minT = arr + (walk || R.change[x]);
    for (const [t, kk, ii] of S.events[x]) {
      if (t < minT) continue;
      if (t > arr + 3600) break;
      if (kk === k) continue;
      const st2 = T.stops[kk];
      if (ii >= st2.length / 4 - 1) continue; // terminating here
      if (nextS >= 0 && st2[4 * (ii + 1)] === nextS && T.dest[kk] === T.dest[k]) continue;
      const dep = st2[4 * ii + 2];
      if (dep < minT) continue;
      res.push({ k: kk, t: dep, s: x });
    }
  }
  res.sort((a, b) => a.t - b.t);
  return res;
}

function renderTripPanel() {
  if (state.sel?.type !== "trip") return;
  const k = state.sel.k;
  const T = M.T, S = M.S;
  const st = T.stops[k];
  const ns = st.length / 4;
  const col = rgb(CAT_COLOR[T.cat[k]]);
  const dur = T.end[k] - T.start[k];
  const km = T.length[k] / 1000;
  const rows = [];
  const nx = nextStop(k, state.t);
  for (let i = 0; i < ns; i++) {
    const s = st[4 * i], arr = st[4 * i + 1], dep = st[4 * i + 2];
    const past = (i === 0 ? dep : arr) < state.t;
    const isNext = nx && nx.i === i;
    let times;
    if (i === 0) times = `${fmtTime(dep)}`;
    else if (i === ns - 1) times = `${fmtTime(arr)}`;
    else times = dep > arr ? `${fmtTime(arr)}<small>${fmtTime(dep)}</small>` : fmtTime(arr);
    let conn = "";
    if (i > 0) {
      const cs = connectionsAt(k, i);
      if (cs.length) {
        const chips = cs.slice(0, i === ns - 1 ? 8 : 4).map((c) =>
          `<span class="chip" data-trip="${c.k}" title="${T.brand[c.k]} ${T.num[c.k]} to ${S.name[T.dest[c.k]]}${c.s !== s ? ` (from ${S.name[c.s]})` : ""}"><i style="background:${rgb(CAT_COLOR[T.cat[c.k]])}"></i>${fmtTime(c.t)} ${shortName(S.name[T.dest[c.k]])}</span>`).join("");
        conn = `<div class="conn">${chips}${cs.length > (i === ns - 1 ? 8 : 4) ? `<span class="more">+${cs.length - (i === ns - 1 ? 8 : 4)}</span>` : ""}</div>`;
      }
    }
    const flags = st[4 * i + 3];
    const note = i === 0 || i === ns - 1 ? "" : flags === 1 ? " · set down only" : flags === 2 ? " · pick up only" : "";
    rows.push(`<li class="${past ? "past" : ""} ${isNext ? "next" : ""}"><div class="tm">${times}</div><div class="rail"></div>
      <div class="st"><span class="sn" data-station="${s}">${S.name[s]}</span><span class="p-sub">${note}</span>${conn}</div></li>`);
  }
  openPanel(`
    <div class="p-kicker">${badge(k)} Train <span class="mono" style="color:#fff">${T.num[k]}</span> ${T.line[k] ? `· line ${T.line[k]}` : ""}</div>
    <div class="p-title">${S.name[T.orig[k]]} → ${S.name[T.dest[k]]}</div>
    <div class="p-sub">${T.route[k] || ""}${T.prev[k] ? " · departed the previous evening" : ""}</div>
    <div class="kpis">
      <div class="kpi"><b>${fmtTime(T.start[k])}</b><span>Departure</span></div>
      <div class="kpi"><b>${fmtTime(T.end[k])}</b><span>Arrival</span></div>
      <div class="kpi"><b>${fmtDur(dur)}</b><span>Duration</span></div>
      <div class="kpi"><b>${Math.round(km)} km</b><span>Route length</span></div>
      <div class="kpi"><b>${ns}</b><span>Stops</span></div>
      <div class="kpi"><b>${dur > 0 ? Math.round(km / (dur / 3600)) : "—"}</b><span>Avg km/h</span></div>
    </div>
    <div class="status" id="trip-status"></div>
    <div class="btn-row">
      <button class="btn ghost ${state.follow ? "on" : ""}" id="btn-follow">◎ Follow train</button>
      <button class="btn ghost" id="btn-fit">⤢ Show full route</button>
    </div>
    <div class="h3">Stop-by-stop timetable &amp; scheduled connections</div>
    <ul class="tt" style="--c:${col}">${rows.join("")}</ul>
    <div class="note">Connections list departures from the same station (or a station within walking / urban-transfer distance) between the minimum change time and 60 minutes after arrival.</div>`);
  $("#btn-follow").onclick = () => setFollow(!state.follow);
  $("#btn-fit").onclick = () => selectTrip(k, true);
  bindPanelLinks();
  updateTripStatus();
  updateLegend();
}

function updateTripStatus() {
  const el = $("#trip-status");
  if (!el || state.sel?.type !== "trip") return;
  const k = state.sel.k;
  const T = M.T, S = M.S;
  const t = state.t;
  const col = rgb(CAT_COLOR[T.cat[k]]);
  let html;
  if (t < T.start[k]) html = `Scheduled · departs <b>${S.name[T.orig[k]]}</b> in <b>${fmtDur(T.start[k] - t)}</b>`;
  else if (t > T.end[k]) html = `Arrived at <b>${S.name[T.dest[k]]}</b> at <b>${fmtTime(T.end[k])}</b>`;
  else {
    const nx = nextStop(k, t);
    const p = trainPosition(k, t);
    html = nx?.at ? `Standing at <b>${S.name[nx.s]}</b> · departs <b>${fmtTime(nx.t)}</b>`
      : `Running at <b>${Math.round(p?.kmh || 0)} km/h</b> · next stop <b>${nx ? S.name[nx.s] : "—"}</b> at <b>${nx ? fmtTime(nx.t) : ""}</b>`;
  }
  const prog = Math.max(0, Math.min(1, (t - T.start[k]) / (T.end[k] - T.start[k] || 1)));
  el.innerHTML = `${html}<div class="progress"><div style="width:${prog * 100}%;background:${col}"></div></div>`;
}

function setFollow(on) {
  state.follow = on;
  const b = $("#btn-follow");
  if (b) b.classList.toggle("on", on);
  if (on && state.sel?.type === "trip") {
    const p = trainPosition(state.sel.k, state.t);
    if (p) flyTo({ longitude: p.lon, latitude: p.lat, zoom: Math.max(state.view.zoom, 8.5) }, 900);
  }
}

function shortName(n) {
  return n.replace(/^Gare de /, "").replace(/ - .*$/, "").replace(/\s*\(.*\)$/, "").slice(0, 22);
}

function selectStation(s, fly = false) {
  if (state.mode === "reach") return setReachOrigin(s);
  state.sel = { type: "station", s };
  setFollow(false);
  renderStationPanel();
  if (fly) flyTo({ longitude: M.S.lon[s], latitude: M.S.lat[s], zoom: Math.max(state.view.zoom, 8) });
}

function renderStationPanel() {
  if (state.sel?.type !== "station") return;
  const s = state.sel.s;
  const S = M.S, T = M.T;
  const c = S.calls[s];
  const ev = S.events[s];
  const dep = state.boardTab === "dep";
  const rows = [];
  let nowPlaced = false;
  let nowIdx = 0;
  const list = ev.filter(([, k, i]) => {
    const ns = T.stops[k].length / 4;
    return dep ? i < ns - 1 : i > 0;
  }).filter(([, k]) => state.catOn[T.cat[k]]);
  list.forEach(([, k, i], idx) => {
    const st = T.stops[k];
    const t = dep ? st[4 * i + 2] : st[4 * i + 1];
    if (t < 0 && !T.prev[k]) return;
    const past = t < state.t;
    let cls = past ? "past" : "";
    if (!past && !nowPlaced) { cls += " nowline"; nowPlaced = true; nowIdx = idx; }
    const other = dep ? T.dest[k] : T.orig[k];
    const via = dep && i + 1 < st.length / 4 - 1 ? `<span class="p-sub"> · next ${shortName(S.name[st[4 * (i + 1)]])}</span>` : "";
    rows.push(`<tr class="${cls}" data-trip="${k}" ${!past && cls.includes("nowline") ? 'id="board-now"' : ""}>
      <td class="t">${fmtTime(t)}</td><td>${badge(k)}</td><td class="num">${T.num[k]}</td>
      <td class="dst">${S.name[other]}${via}</td></tr>`);
  });
  void nowIdx;
  // direct destinations
  const direct = new Map();
  for (const [, k, i] of ev) {
    const st = T.stops[k];
    for (let j = i + 1; j < st.length / 4; j++) {
      const x = st[4 * j];
      if (!direct.has(x)) direct.set(x, { n: 0, best: Infinity });
      const d = direct.get(x);
      d.n++;
      d.best = Math.min(d.best, st[4 * j + 1] - st[4 * i + 2]);
    }
  }
  const dests = [...direct.entries()].sort((a, b) => S.total[b[0]] - S.total[a[0]]).slice(0, 14);
  openPanel(`
    <div class="p-kicker">Station ${S.seg[s] ? `· DRG category ${S.seg[s]}` : ""} · UIC ${S.uic[s]}</div>
    <div class="p-title">${S.name[s]}</div>
    <div class="p-sub">${S.dep[s] || ""}</div>
    <div class="kpis">
      <div class="kpi"><b style="color:${rgb(CAT_COLOR[0])}">${c[0]}</b><span>TGV / day</span></div>
      <div class="kpi"><b style="color:${rgb(CAT_COLOR[1])}">${c[1]}</b><span>Intercités</span></div>
      <div class="kpi"><b style="color:${rgb(CAT_COLOR[2])}">${c[2]}</b><span>TER / day</span></div>
    </div>
    <canvas id="station-hours" style="width:100%;height:70px;display:block"></canvas>
    <div class="btn-row">
      <button class="btn" id="btn-reach">◉ Travel-time map from here</button>
      <button class="btn ghost" id="btn-zoom">⤢ Zoom</button>
    </div>
    <div class="h3">Direct connections · fastest time</div>
    <div class="dests">${dests.map(([x, d]) => `<span class="chip" data-station="${x}">${shortName(S.name[x])} <span style="color:var(--dim)">${fmtDur(d.best)} · ${d.n}×</span></span>`).join("")}</div>
    <div class="tabs"><button data-tab="dep" class="${dep ? "on" : ""}">Departures</button><button data-tab="arr" class="${dep ? "" : "on"}">Arrivals</button></div>
    <div class="board-wrap" id="board-wrap"><table class="board"><tbody>${rows.join("") || `<tr><td class="p-sub">No trains</td></tr>`}</tbody></table></div>`);
  drawStationHours($("#station-hours"), M, s, state);
  $("#btn-reach").onclick = () => { setMode("reach"); setReachOrigin(s); };
  $("#btn-zoom").onclick = () => flyTo({ longitude: S.lon[s], latitude: S.lat[s], zoom: 9.5 });
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => { state.boardTab = b.dataset.tab; renderStationPanel(); }));
  bindPanelLinks();
  const now = $("#board-now"), wrap = $("#board-wrap");
  if (now && wrap) wrap.scrollTop = now.offsetTop - 60;
  $("#panel-body").scrollTop = 0;
  updateLegend();
}

function bindPanelLinks() {
  document.querySelectorAll("#panel-body [data-trip]").forEach((el) =>
    (el.onclick = (e) => { e.stopPropagation(); selectTrip(+el.dataset.trip, true); }));
  document.querySelectorAll("#panel-body [data-station]").forEach((el) =>
    (el.onclick = (e) => { e.stopPropagation(); selectStation(+el.dataset.station, true); }));
}

// ------------------------------------------------------------------ accessibility
function setReachOrigin(s) {
  state.reachPin = -1;
  state.hoverJourney = null;
  const t0 = performance.now();
  state.reach = R.reach(s, state.reachMode, Math.round(state.t));
  state.reach.ms = performance.now() - t0;
  state.sel = null;
  renderReachPanel();
}

function recomputeReach() {
  if (!state.reach) return;
  const src = state.reach.src;
  const pin = state.reachPin;
  const t0 = performance.now();
  state.reach = R.reach(src, state.reachMode, Math.round(state.t));
  state.reach.ms = performance.now() - t0;
  if (pin >= 0) state.hoverJourney = R.journey(state.reach, pin);
  renderReachPanel(true);
}

function renderReachPanel(keepPin = false) {
  if (state.mode !== "reach") return;
  if (!state.reach) {
    openPanel(`<div class="p-kicker">Accessibility atlas</div>
      <div class="p-title">Travel time by rail</div>
      <div class="empty">Click <b>any station</b> on the map (or search one) to compute the shortest rail travel time to every station in France,<br/>including connections and transfer waits.</div>
      ${bandsHTML(null)}
      <div class="btn-row">${["Paris Gare de Lyon", "Lyon Part Dieu", "Bordeaux Saint-Jean", "Lille Flandres", "Marseille Saint-Charles", "Strasbourg", "Rennes", "Toulouse Matabiau"].map((n) => {
        const s = M.S.name.findIndex((x) => normalize(x) === normalize(n));
        return s >= 0 ? `<button class="btn ghost" data-origin="${s}">${n}</button>` : "";
      }).join("")}</div>`);
    document.querySelectorAll("[data-origin]").forEach((b) => (b.onclick = () => setReachOrigin(+b.dataset.origin)));
    updateLegend();
    return;
  }
  const r = state.reach;
  const S = M.S;
  const reached = [];
  for (let s = 0; s < S.n; s++) if (s !== r.src && isFinite(r.dur[s]) && S.total[s] > 0) reached.push(s);
  const list = majorCities().filter((s) => s !== r.src && isFinite(r.dur[s])).sort((a, b) => r.dur[a] - r.dur[b]);
  const sorted = reached.map((s) => r.dur[s]).sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : NaN;
  openPanel(`
    <div class="p-kicker">Accessibility from</div>
    <div class="p-title">${S.name[r.src]}</div>
    <div class="p-sub">${reached.length} of ${M.stationIdx.length - 1} stations reachable · median ${fmtDur(median)} · computed in ${Math.round(r.ms || 0)} ms</div>
    <div class="btn-row">
      <span class="seg-toggle" id="reach-mode">
        <button data-v="best" class="${r.mode === "best" ? "on" : ""}">Fastest of the day</button>
        <button data-v="depart" class="${r.mode === "depart" ? "on" : ""}">Leave at ${fmtTime(r.t0)}</button>
      </span>
      <button class="btn ghost" id="btn-station-tt">Timetable</button>
    </div>
    ${bandsHTML(r)}
    <div id="reach-journey"></div>
    <div class="h3">Major cities · click to pin the itinerary</div>
    <ul class="rlist">${list.map((s) => `<li data-dst="${s}"><span class="d" style="background:${rgb(BANDS[bandOf(r.dur[s])].color)}"></span><span>${S.name[s]}</span><span class="tv">${fmtDur(r.dur[s])}</span></li>`).join("")}</ul>
    <div class="note">${r.mode === "best"
      ? "Shortest door-to-door rail time over every departure of the service day (no initial wait counted), including transfer waits."
      : `Time from ${fmtTime(r.t0)} until arrival, counting the wait for the first train. Scrub the timeline to update.`}
      Minimum change time: 10 min at major hubs, 7 min at mid-size stations, 5 min elsewhere; walking links up to 1.3 km and urban transfers between terminals of the same city (e.g. Paris) are included.</div>`);
  document.querySelectorAll("#reach-mode button").forEach((b) => (b.onclick = () => { state.reachMode = b.dataset.v; recomputeReach(); }));
  $("#btn-station-tt").onclick = () => { const s = r.src; setMode("pulse"); selectStation(s, true); };
  document.querySelectorAll("[data-dst]").forEach((li) => {
    li.onclick = () => pinJourney(+li.dataset.dst);
    li.onmouseenter = () => { if (state.reachPin < 0) { state.hoverJourney = R.journey(r, +li.dataset.dst); renderReachJourney(+li.dataset.dst, state.hoverJourney); } };
  });
  if (keepPin && state.reachPin >= 0) renderReachJourney(state.reachPin, state.hoverJourney);
  updateLegend();
}

const CITIES = ["Paris", "Lyon", "Marseille", "Lille", "Bordeaux", "Toulouse", "Nantes", "Strasbourg", "Rennes",
  "Montpellier", "Nice", "Grenoble", "Dijon", "Rouen", "Clermont-Ferrand", "Tours", "Metz", "Nancy", "Brest", "Limoges",
  "Perpignan", "Poitiers", "Le Mans", "Reims", "Besançon", "Caen", "Amiens", "Orléans", "Bayonne", "Avignon", "Toulon", "Mulhouse"];
function majorCities() {
  if (cache.cities) return cache.cities;
  const S = M.S;
  cache.cities = CITIES.map((c) => {
    const q = normalize(c);
    let best = -1;
    for (const s of M.stationIdx) if (S.norm[s].startsWith(q) && (best < 0 || S.total[s] > S.total[best])) best = s;
    return best;
  }).filter((s) => s >= 0);
  return cache.cities;
}

function pinJourney(s) {
  state.reachPin = s;
  state.hoverJourney = R.journey(state.reach, s);
  renderReachJourney(s, state.hoverJourney);
}

function bandsHTML(r) {
  const counts = BANDS.map(() => 0);
  let un = 0;
  if (r) for (const s of M.stationIdx) {
    if (s === r.src) continue;
    const b = bandOf(r.dur[s]);
    if (b < 0) un++;
    else counts[b]++;
  }
  const max = Math.max(1, ...counts, un);
  return `<div class="bands">${BANDS.map((b, i) => `<div class="band"><span class="sq" style="background:${rgb(b.color)};box-shadow:0 0 10px ${rgb(b.color, 0.5)}"></span><span>${b.label}</span>
    <span class="bb"><div style="width:${(counts[i] / max) * 100}%;background:${rgb(b.color)}"></div></span><span class="bc">${r ? counts[i] : ""}</span></div>`).join("")}
    <div class="band"><span class="sq" style="background:${rgb(UNREACHED)}"></span><span>no service</span><span class="bb"><div style="width:${(un / max) * 100}%;background:${rgb(UNREACHED)}"></div></span><span class="bc">${r ? un : ""}</span></div></div>`;
}

function renderReachJourney(dst, j) {
  const el = $("#reach-journey");
  if (!el) return;
  const S = M.S, T = M.T;
  if (!j) { el.innerHTML = ""; return; }
  const legs = j.legs.map((l) => {
    if (l.type === "walk") return `<div class="leg walk">Transfer ${S.name[l.from]} → ${S.name[l.to]} (${fmtDur(l.arr - l.dep)} walk / urban link)</div>`;
    return `<div class="leg"><span class="lt">${fmtTime(l.dep)} → ${fmtTime(l.arr)}</span> ${badge(l.trip)} <span class="mono">${T.num[l.trip]}</span><br/>${S.name[l.from]} → ${S.name[l.to]}</div>`;
  });
  const changes = j.legs.filter((l) => l.type === "train").length - 1;
  el.innerHTML = `<div class="h3">${state.reachPin === dst ? "Pinned" : "Fastest"} journey to ${S.name[dst]} · ${fmtDur(state.reach.dur[dst])} · ${changes <= 0 ? "direct" : `${changes} change${changes > 1 ? "s" : ""}`}</div>
    <div class="journey">${legs.join("")}</div>`;
}

// ------------------------------------------------------------------ HUD
function updateHUD() {
  const t = state.t;
  const hh = fmtTime(t, true);
  $("#clock").innerHTML = `${hh.slice(0, 5)}<small>:${hh.slice(6)}</small>`;
  const H = M.heads;
  $("#active-total").textContent = H.active.reduce((a, b, i) => a + (state.catOn[i] ? b : 0), 0);
  const peak = M.peak || (M.peak = CATS.map((_, c) => Math.max(...M.profile[c])));
  CATS.forEach((_, c) => {
    const row = cache.catRows[c];
    row.ct.textContent = H.active[c];
    row.bar.style.width = `${(H.active[c] / peak[c]) * 100}%`;
  });
  drawProfile($("#profile"), M, state, cache);
  const minute = Math.floor(t / 60);
  if (minute !== lastMinute) {
    lastMinute = minute;
    if (minute % 2 === 0 || !cache.busyDrawn) updateBusy();
    updateTripStatus();
    const h = t / 3600;
    const night = h < 5 ? 1 : h < 7.5 ? 1 - (h - 5) / 2.5 : h > 22 ? Math.min(1, (h - 22) / 1.5) : 0;
    document.documentElement.style.setProperty("--night", night.toFixed(2));
    if (state.mode === "reach" && state.reach?.mode === "depart" && minute % 5 === 0 && !cache.dragging) recomputeReach();
  }
}

function updateBusy() {
  cache.busyDrawn = true;
  const S = M.S;
  const now = state.busyMode === "now";
  const b0 = Math.floor(state.t / 600);
  const score = [];
  for (const s of M.stationIdx) {
    let v = 0;
    const parts = [0, 0, 0];
    if (now) {
      for (let b = b0 - 3; b <= b0 + 2; b++) {
        const bb = ((b % 144) + 144) % 144;
        for (let c = 0; c < 3; c++) if (state.catOn[c]) parts[c] += S.bins[(s * 144 + bb) * 3 + c];
      }
    } else {
      for (let c = 0; c < 3; c++) if (state.catOn[c]) parts[c] = S.calls[s][c];
    }
    v = parts[0] + parts[1] + parts[2];
    if (v) score.push([s, v, parts]);
  }
  score.sort((a, b) => b[1] - a[1]);
  const top = score.slice(0, 8);
  const max = top[0]?.[1] || 1;
  $("#busy").innerHTML = top.map(([s, v, p], i) => `<li data-s="${s}"><span class="rk">${i + 1}</span><span class="n">${S.name[s]}</span><span class="v">${v}<small style="color:var(--faint)"> ${now ? "trains" : "/day"}</small></span>
    <span class="mini" style="width:${(v / max) * 100}%">${p.map((x, c) => `<span style="flex:${x};background:${rgb(CAT_COLOR[c])}"></span>`).join("")}</span></li>`).join("");
  document.querySelectorAll("#busy li").forEach((li) => (li.onclick = () => selectStation(+li.dataset.s, true)));
}

function updateLegend() {
  const el = $("#mode-legend");
  const panelOpen = !$("#panel").classList.contains("hidden");
  if (state.mode === "flow") {
    const max = M.corrMax;
    const stops = [0, 0.25, 0.5, 0.75, 1].map((v) => `${rgb(flowColor(v))} ${v * 100}%`).join(",");
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((v) => Math.round(v * v * max));
    el.innerHTML = `<div class="lg-title">Daily trains per corridor · ${CATS.filter((_, c) => state.catOn[c]).map((c) => CAT_LABEL[CATS.indexOf(c)]).join(" + ")}</div>
      <div class="ramp" style="background:linear-gradient(90deg,${stops})"></div>
      <div class="ramp-l">${ticks.map((x) => `<span>${x}</span>`).join("")}</div>
      <div class="lg-widths">${[5, 30, 100, max].map((n) => `<div><span style="height:${0.7 + 6.5 * flowV(n)}px;background:${rgb(flowColor(flowV(n)))}"></span>${n}</div>`).join("")}</div><div class="note" style="margin-top:6px">Line weight and luminance scale with the number of scheduled trains over 24 h on each RFN section (hover a line for details).</div>`;
    el.classList.remove("hidden");
    el.style.bottom = "150px";
    el.style.top = panelOpen ? "auto" : "";
  } else el.classList.add("hidden");
  if (state.mode === "flow" && panelOpen) el.classList.add("hidden");
}

// ------------------------------------------------------------------ UI wiring
function setMode(m) {
  if (state.mode === m) return;
  state.mode = m;
  document.querySelectorAll("#modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
  setFollow(false);
  if (m === "reach") {
    state.sel = null;
    renderReachPanel();
  } else {
    state.hoverJourney = null;
    if (state.sel?.type === "trip") renderTripPanel();
    else if (state.sel?.type === "station") renderStationPanel();
    else $("#panel").classList.add("hidden");
  }
  if (m === "flow" && !state.sel) $("#panel").classList.add("hidden");
  updateLegend();
}

function initUI() {
  const { meta } = M;
  const d = new Date(`${meta.service_day}T12:00:00`);
  $("#clock-day").textContent = `${d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })} · reference service day`;
  $("#feed-info").textContent = `GTFS feed ${meta.feed.feed_version} · ${meta.counts.runs_day.toLocaleString("en")} trains · ${meta.counts.stations.toLocaleString("en")} stations`;

  // categories legend
  const sub = { TGV: "INOUI · OUIGO · Lyria · ICE · Eurostar", IC: "day & night", TER: "regional · tram-train" };
  cache.catRows = CATS.map((c, i) => {
    const el = document.createElement("div");
    el.className = "cat";
    el.innerHTML = `<span class="sw" style="background:${rgb(CAT_COLOR[i])};box-shadow:0 0 10px ${rgb(CAT_COLOR[i], 0.7)}"></span>
      <span class="nm">${CAT_LABEL[i]}<small>${sub[c]}</small></span><span class="ct">0</span>
      <span class="barwrap"><span class="bar" style="display:block;background:${rgb(CAT_COLOR[i])}"></span></span>`;
    el.title = `${M.daily[i].toLocaleString("en")} ${CAT_LABEL[i]} trains on the service day`;
    el.onclick = () => {
      state.catOn[i] = !state.catOn[i];
      if (!state.catOn.some(Boolean)) state.catOn[i] = true;
      el.classList.toggle("off", !state.catOn[i]);
      cache.profileKey = null;
      updateBusy();
      updateLegend();
      if (state.sel?.type === "station") renderStationPanel();
    };
    el.onmouseenter = () => (state.hoverCat = i);
    el.onmouseleave = () => (state.hoverCat = -1);
    $("#cats").appendChild(el);
    return { el, ct: el.querySelector(".ct"), bar: el.querySelector(".bar") };
  });

  document.querySelectorAll("#modes button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  document.querySelectorAll("#busy-toggle button").forEach((b) => (b.onclick = () => {
    state.busyMode = b.dataset.v;
    document.querySelectorAll("#busy-toggle button").forEach((x) => x.classList.toggle("on", x === b));
    updateBusy();
  }));
  $("#panel-close").onclick = () => {
    if (state.mode === "reach") { state.reach = null; state.hoverJourney = null; state.reachPin = -1; renderReachPanel(); return; }
    closePanel();
  };
  $("#play").onclick = togglePlay;
  document.querySelectorAll("#speeds button").forEach((b) => (b.onclick = () => {
    state.speed = +b.dataset.s;
    document.querySelectorAll("#speeds button").forEach((x) => x.classList.toggle("on", x === b));
  }));

  // timeline scrubbing
  const cv = $("#profile");
  const timeAt = (e) => {
    const r = cv.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left - 26) / (r.width - 32)));
    return x * (DAY - 1);
  };
  cv.addEventListener("pointerdown", (e) => {
    cache.dragging = true;
    cache.wasPlaying = state.playing;
    cv.setPointerCapture(e.pointerId);
    state.t = timeAt(e);
  });
  cv.addEventListener("pointermove", (e) => {
    cache.hoverT = timeAt(e);
    if (cache.dragging) state.t = cache.hoverT;
  });
  cv.addEventListener("pointerleave", () => (cache.hoverT = null));
  cv.addEventListener("pointerup", () => {
    cache.dragging = false;
    if (state.mode === "reach" && state.reach?.mode === "depart") recomputeReach();
    if (state.sel?.type === "trip") renderTripPanel();
  });

  // search
  const input = $("#search"), results = $("#search-results");
  let items = [], cursor = 0;
  const choose = (it) => {
    results.classList.remove("open");
    input.value = "";
    input.blur();
    if (it.type === "s") {
      if (state.mode === "reach") { setReachOrigin(it.id); flyTo({ longitude: M.S.lon[it.id], latitude: M.S.lat[it.id], zoom: Math.max(5, state.view.zoom) }); }
      else selectStation(it.id, true);
    } else selectTrip(it.id, true);
  };
  input.addEventListener("input", () => {
    const q = normalize(input.value);
    if (!q) { results.classList.remove("open"); return; }
    const S = M.S, T = M.T;
    const st = [];
    for (const s of M.stationIdx) {
      const n = S.norm[s];
      const p = n.startsWith(q) ? 2 : n.includes(` ${q}`) ? 1 : n.includes(q) ? 0.5 : -1;
      if (p >= 0) st.push([s, p * 1e4 + S.total[s]]);
    }
    st.sort((a, b) => b[1] - a[1]);
    const tr = [];
    if (/^\d+/.test(q)) for (let k = 0; k < T.n && tr.length < 6; k++) if (!T.prev[k] && T.num[k].startsWith(q.replace(/\s/g, ""))) tr.push(k);
    items = [...st.slice(0, 8).map(([s]) => ({ type: "s", id: s })), ...tr.map((k) => ({ type: "t", id: k }))];
    cursor = 0;
    results.innerHTML = items.map((it, i) => it.type === "s"
      ? `<div data-i="${i}" class="${i === 0 ? "sel" : ""}">${S.name[it.id]}<span class="k">${S.total[it.id]} trains/day</span></div>`
      : `<div data-i="${i}" class="${i === 0 ? "sel" : ""}">${badge(it.id)} <span class="mono">${T.num[it.id]}</span> ${shortName(S.name[T.orig[it.id]])} → ${shortName(S.name[T.dest[it.id]])}<span class="k">${fmtTime(T.start[it.id])}</span></div>`).join("")
      || `<div class="k" style="color:var(--dim)">No match</div>`;
    results.classList.add("open");
    results.querySelectorAll("[data-i]").forEach((el) => (el.onmousedown = (e) => { e.preventDefault(); choose(items[+el.dataset.i]); }));
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && items[cursor]) choose(items[cursor]);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      cursor = Math.max(0, Math.min(items.length - 1, cursor + (e.key === "ArrowDown" ? 1 : -1)));
      results.querySelectorAll("[data-i]").forEach((el) => el.classList.toggle("sel", +el.dataset.i === cursor));
      e.preventDefault();
    }
    if (e.key === "Escape") { results.classList.remove("open"); input.blur(); }
    e.stopPropagation();
  });
  input.addEventListener("blur", () => setTimeout(() => results.classList.remove("open"), 150));

  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.code === "Space") { togglePlay(); e.preventDefault(); }
    else if (e.key === "ArrowRight") state.t = (state.t + (e.shiftKey ? 3600 : 300)) % DAY;
    else if (e.key === "ArrowLeft") state.t = (state.t - (e.shiftKey ? 3600 : 300) + DAY) % DAY;
    else if (e.key === "1") setMode("pulse");
    else if (e.key === "2") setMode("flow");
    else if (e.key === "3") setMode("reach");
    else if (e.key === "Escape") $("#panel-close").click();
    else if (e.key === "/") { $("#search").focus(); e.preventDefault(); }
  });
  window.addEventListener("resize", () => { drawProfile($("#profile"), M, state, cache, true); state.dirty = true; });
  for (const ev of ["pointermove", "pointerdown", "pointerup", "wheel", "keydown", "click"]) {
    window.addEventListener(ev, () => (state.dirty = true), { passive: true, capture: true });
  }
  $("#trails").onclick = () => { cache.userTrails = true; setLite(!state.lite, "turned off"); };
  updatePlayIcon();
  updateBusy();
}

function togglePlay() {
  state.playing = !state.playing;
  updatePlayIcon();
}
function updatePlayIcon() {
  $("#play-icon").setAttribute("d", state.playing ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M7 5l12 7-12 7z");
}

