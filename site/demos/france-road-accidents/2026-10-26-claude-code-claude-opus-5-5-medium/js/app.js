import { CODES, label } from './codebook.js';

/* =========================================================================
   Constants & palettes
   ========================================================================= */
const SEV_NAMES = ['Unharmed', 'Slightly injured', 'Hospitalised', 'Killed'];
const SEV_RGB = [[111, 124, 140], [222, 198, 132], [242, 140, 56], [255, 52, 72]];
const SEV_CSS = SEV_RGB.map(c => `rgb(${c})`);
// mode index (build_data.py): 0 PED 1 BIKE 2 EDPM 3 2RM 4 CAR 5 VAN 6 HEAVY 7 OTHER ; 8 NONE
const MODE_SHORT = ['Pedestrian', 'Bicycle', 'E-scooter', 'Motor 2-wheeler', 'Car', 'Van', 'Heavy vehicle', 'Other', 'No other party'];
const MODE_HEX = ['#d95926', '#199e70', '#d55181', '#c98500', '#3987e5', '#008300', '#9085e9', '#77756f', '#4b4b48'];
const MODE_RGB = MODE_HEX.map(h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)));
// legend order = validated categorical slot order
const MODE_LEGEND_ORDER = [4, 0, 1, 3, 2, 5, 6, 7];
const CATV_MODE = {};
[1, 80].forEach(c => CATV_MODE[c] = 1);
[50].forEach(c => CATV_MODE[c] = 2);
[2, 30, 31, 32, 33, 34, 41, 42, 43].forEach(c => CATV_MODE[c] = 3);
[3, 7].forEach(c => CATV_MODE[c] = 4);
[10].forEach(c => CATV_MODE[c] = 5);
[13, 14, 15, 16, 17, 20, 21, 37, 38, 39, 40].forEach(c => CATV_MODE[c] = 6);
const catvMode = c => CATV_MODE[c] ?? 7;
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DOW_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const FRANCE = [[-5.3, 41.3], [9.65, 51.15]];
const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const nf = new Intl.NumberFormat('en-GB');
const fmt = n => nf.format(Math.round(n));
const fmtK = n => n >= 10000 ? (n / 1000).toFixed(0) + 'k' : n >= 1000 ? (n / 1000).toFixed(1).replace('.0', '') + 'k' : String(n);
const pct = (a, b, d = 1) => b ? (100 * a / b).toFixed(d) : '–';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const $ = s => document.querySelector(s);

/* single-hue (orange) sequential ramp for the dark surface: low = recedes, high = bright */
const RAMP = [[34, 26, 23], [92, 40, 22], [168, 64, 28], [235, 101, 52], [255, 150, 105], [255, 205, 180]];
function ramp(t) {
  t = Math.max(0, Math.min(1, t)) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(t)), f = t - i;
  return RAMP[i].map((c, k) => Math.round(c + (RAMP[i + 1][k] - c) * f));
}
const rampCss = t => `rgb(${ramp(t)})`;
const rampGradient = () => `linear-gradient(90deg, ${RAMP.map(c => `rgb(${c})`).join(',')})`;

/* =========================================================================
   Load data
   ========================================================================= */
const meta = await (await fetch('data/meta.json')).json();
const [accBuf, vicBuf, depGeo] = await Promise.all([
  fetch('data/accidents.bin').then(r => r.arrayBuffer()),
  fetch('data/victims.bin').then(r => r.arrayBuffer()),
  fetch('data/departements.geojson').then(r => r.json()),
]);
const N = meta.n, NV = meta.nVictims;
const A = {};
for (const c of meta.columns) A[c.name] = c.type === 'f32' ? new Float32Array(accBuf, c.offset, N) : new Uint8Array(accBuf, c.offset, N);
const V = {};
for (const c of meta.victimColumns) V[c.name] = c.type === 'u32' ? new Uint32Array(vicBuf, c.offset, NV) : new Uint8Array(vicBuf, c.offset, NV);
const YEARS = meta.years;
const DEPS = meta.departments;
const ND = DEPS.length;

// victims are written in accident order → offsets
const vStart = new Uint32Array(N + 1);
{ let j = 0; for (let i = 0; i < N; i++) { vStart[i] = j; while (j < NV && V.acc[j] === i) j++; } vStart[N] = NV; }

const positions = new Float32Array(N * 2);
for (let i = 0; i < N; i++) { positions[2 * i] = A.lon[i]; positions[2 * i + 1] = A.lat[i]; }
const colorsSev = new Uint8Array(N * 4), colorsMode = new Uint8Array(N * 4), radii = new Float32Array(N);
for (let i = 0; i < N; i++) {
  const s = A.sev[i], m = A.vmode[i] === 255 ? 7 : A.vmode[i];
  const cs = SEV_RGB[s], cm = MODE_RGB[m];
  colorsSev.set([cs[0], cs[1], cs[2], [150, 140, 190, 255][s]], 4 * i);
  colorsMode.set([cm[0], cm[1], cm[2], s === 3 ? 255 : 200], 4 * i);
  radii[i] = [0.85, 0.9, 1.15, 1.6][s];
}
const killedIdx = [];
for (let i = 0; i < N; i++) if (A.sev[i] === 3) killedIdx.push(i);
const killedPos = new Float32Array(killedIdx.length * 2);
killedIdx.forEach((i, k) => { killedPos[2 * k] = A.lon[i]; killedPos[2 * k + 1] = A.lat[i]; });

/* =========================================================================
   Filter dimensions
   ========================================================================= */
const DIMS = [
  { key: 'year', title: 'Year', col: 'year', labels: YEARS.map(String), map: v => v },
  { key: 'hour', title: 'Hour of day', col: 'hour', kind: 'v', labels: [...Array(24).keys()].map(String), map: v => v < 24 ? v : 255 },
  { key: 'dow', title: 'Day of week', col: 'dow', kind: 'v', labels: DOW, map: v => v },
  { key: 'lum', title: 'Lighting', col: 'lum', labels: ['Daylight', 'Dusk / dawn', 'Night, street-lit', 'Night, unlit'], map: v => ({ 1: 0, 2: 1, 5: 2, 3: 3, 4: 3 })[v] ?? 255 },
  { key: 'atm', title: 'Weather', col: 'atm', labels: ['Normal', 'Overcast', 'Rain', 'Snow / hail', 'Fog / smoke', 'Wind / storm', 'Dazzling sun', 'Other'], map: v => ({ 1: 0, 8: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 9: 7 })[v] ?? 255 },
  { key: 'catr', title: 'Road category', col: 'catr', labels: ['Motorway', 'National road', 'Departmental', 'Communal road', 'Urban metropolitan', 'Car park / private', 'Other'], map: v => ({ 1: 0, 2: 1, 3: 2, 4: 3, 7: 4, 5: 5, 6: 5, 9: 6 })[v] ?? 255 },
  { key: 'vmab', title: 'Speed limit (km/h)', col: 'vmab', labels: meta.vmaLabels, map: v => v < 6 ? v : 255 },
  { key: 'infra', title: 'Cycling infrastructure', col: 'infra', labels: ['Cycle track or lane', 'None recorded'], map: v => ({ 1: 0, 0: 1 })[v] ?? 255 },
  { key: 'agg', title: 'Setting', col: 'agg', labels: ['Built-up area', 'Outside built-up area'], map: v => ({ 2: 0, 1: 1 })[v] ?? 255 },
];
const NDIM = DIMS.length;
for (const d of DIMS) {
  const lut = new Uint8Array(256);
  for (let v = 0; v < 256; v++) lut[v] = d.map(v);
  const b = new Uint8Array(N), src = A[d.col];
  for (let i = 0; i < N; i++) b[i] = lut[src[i]];
  d.bucket = b; d.nb = d.labels.length;
  d.allowed = new Uint8Array(256);
}

/* =========================================================================
   State
   ========================================================================= */
const state = {
  sel: Object.fromEntries(DIMS.map(d => [d.key, new Set()])),
  cell: null,            // {v: row|null, o: col|null}
  colorBy: 'sev', choro: 'off', mxMetric: 'cas', rankMetric: 'rate',
  selection: null,       // inspector selection indices
};
const anyFilter = () => state.cell || DIMS.some(d => state.sel[d.key].size);

// working buffers
const passAll = new Uint8Array(N);   // passes every condition filter
const cellOK = new Uint8Array(N);    // has a victim in the selected matrix cell
const inView = new Uint8Array(N);
let filterVals = new Float32Array(N);
let killedFilter = new Float32Array(killedIdx.length);
const hist = DIMS.map(d => new Float64Array(d.nb));
const M = { cas: new Float64Array(72), kill: new Float64Array(72), hosp: new Float64Array(72) };
const depAcc = new Float64Array(ND), depKill = new Float64Array(ND), depCas = new Float64Array(ND);
let summary = null;

const cellMatch = (vm, om) => !state.cell || ((state.cell.v == null || state.cell.v === vm) && (state.cell.o == null || state.cell.o === om));

function recomputeCell() {
  if (!state.cell) return;
  cellOK.fill(0);
  for (let j = 0; j < NV; j++) if (cellMatch(V.vmode[j], V.omode[j])) cellOK[V.acc[j]] = 1;
}

/* condition filters → passAll, crossfilter histograms need viewport, so done in computeView */
function recomputeFilters() {
  const active = [];
  for (let k = 0; k < NDIM; k++) {
    const d = DIMS[k], s = state.sel[d.key];
    d.allowed.fill(0);
    if (s.size) { s.forEach(b => d.allowed[b] = 1); active.push(k); }
  }
  const useCell = !!state.cell;
  depAcc.fill(0);
  for (let i = 0; i < N; i++) {
    let ok = 1;
    for (let a = 0; a < active.length; a++) { const d = DIMS[active[a]]; if (!d.allowed[d.bucket[i]]) { ok = 0; break; } }
    passAll[i] = ok;
    const vis = ok && (!useCell || cellOK[i]);
    filterVals[i] = vis ? 1 : 0;
    if (vis) depAcc[A.dep[i]]++;
  }
  depKill.fill(0); depCas.fill(0);
  for (let j = 0; j < NV; j++) {
    const a = V.acc[j];
    if (!passAll[a] || !cellMatch(V.vmode[j], V.omode[j])) continue;
    depCas[A.dep[a]]++;
    if (V.sev[j] === 3) depKill[A.dep[a]]++;
  }
  killedFilter = new Float32Array(killedIdx.length);
  killedIdx.forEach((i, k) => killedFilter[k] = filterVals[i]);
  filterVals = new Float32Array(filterVals); // new reference → deck re-uploads
}

function computeView() {
  const b = map.getBounds();
  const w = b.getWest(), e = b.getEast(), s = b.getSouth(), n = b.getNorth();
  const active = [];
  for (let k = 0; k < NDIM; k++) if (state.sel[DIMS[k].key].size) active.push(k);
  hist.forEach(h => h.fill(0));
  const useCell = !!state.cell;
  let nAcc = 0, nAccView = 0;
  for (let i = 0; i < N; i++) {
    const x = A.lon[i], y = A.lat[i];
    const v = x >= w && x <= e && y >= s && y <= n ? 1 : 0;
    inView[i] = v;
    if (!v) continue;
    nAccView++;
    if (useCell && !cellOK[i]) continue;
    let fails = 0, fd = -1;
    for (let a = 0; a < active.length; a++) {
      const d = DIMS[active[a]];
      if (!d.allowed[d.bucket[i]]) { fails++; fd = active[a]; if (fails > 1) break; }
    }
    if (fails === 0) {
      nAcc++;
      for (let k = 0; k < NDIM; k++) { const bb = DIMS[k].bucket[i]; if (bb !== 255) hist[k][bb]++; }
    } else if (fails === 1) {
      const bb = DIMS[fd].bucket[i]; if (bb !== 255) hist[fd][bb]++;
    }
  }
  M.cas.fill(0); M.kill.fill(0); M.hosp.fill(0);
  const sev = [0, 0, 0, 0];
  const ageBins = Array.from({ length: 18 }, () => [0, 0, 0, 0]);
  const sexCount = [0, 0, 0];
  const ages = new Uint32Array(120);
  for (let j = 0; j < NV; j++) {
    const a = V.acc[j];
    if (!inView[a] || !passAll[a]) continue;
    const vm = V.vmode[j], om = V.omode[j], sv = V.sev[j], c = vm * 9 + om;
    M.cas[c]++;
    if (sv === 3) M.kill[c]++; else if (sv === 2) M.hosp[c]++;
    if (!cellMatch(vm, om)) continue;
    sev[sv]++;
    const age = V.age[j];
    if (age !== 255) { ageBins[Math.min(17, Math.floor(age / 5))][sv]++; ages[Math.min(119, age)]++; }
    const sx = V.sex[j]; sexCount[sx === 1 ? 1 : sx === 2 ? 2 : 0]++;
  }
  let half = 0, tot = ages.reduce((p, c) => p + c, 0), med = null;
  for (let k = 0; k < 120; k++) { half += ages[k]; if (half >= tot / 2) { med = k; break; } }
  summary = { nAcc, nAccView, sev, ageBins, sexCount, medianAge: tot ? med : null };
}

/* =========================================================================
   Map
   ========================================================================= */
async function loadStyle() {
  try {
    const ctl = new AbortController();
    setTimeout(() => ctl.abort(), 6000);
    const r = await fetch(BASEMAP, { signal: ctl.signal });
    if (r.ok) return await r.json();
  } catch (e) { /* offline: fall back to a blank dark canvas */ }
  return { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#0e0f11' } }] };
}
const style = await loadStyle();
// soften the basemap so data carries the contrast
for (const l of style.layers) {
  if (l.id === 'background') l.paint = { 'background-color': '#0c0d0f' };
  if (l.id === 'water') l.paint = { 'fill-color': '#08090b' };
}
const LABEL_BEFORE = style.layers.find(l => l.id === 'waterway_label') ? 'waterway_label' : undefined;

const map = new maplibregl.Map({
  container: 'map', style, bounds: FRANCE, fitBoundsOptions: { padding: 30 },
  minZoom: 4, maxZoom: 18.5, dragRotate: false, pitchWithRotate: false, attributionControl: { compact: true },
});
map.touchZoomRotate.disableRotation();
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
const overlay = new deck.MapboxOverlay({ interleaved: true, layers: [], getTooltip: null });
map.addControl(overlay);

const depBBox = depGeo.features.map(f => {
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  const walk = c => { if (typeof c[0] === 'number') { x0 = Math.min(x0, c[0]); x1 = Math.max(x1, c[0]); y0 = Math.min(y0, c[1]); y1 = Math.max(y1, c[1]); } else c.forEach(walk); };
  walk(f.geometry.coordinates);
  return { idx: f.properties.idx, bbox: [[x0, y0], [x1, y1]] };
}).reduce((o, d) => (o[d.idx] = d.bbox, o), {});

function nYears() { const s = state.sel.year; return s.size || YEARS.length; }
function depMetric(k, metric) {
  const pop = DEPS[k].pop;
  if (metric === 'rate') return pop ? depAcc[k] / pop * 1e5 / nYears() : 0;
  if (metric === 'kill') return pop ? depKill[k] / pop * 1e6 / nYears() : 0;
  return depAcc[k] >= 30 ? depKill[k] / depAcc[k] * 100 : null; // killed per 100 accidents
}
const METRIC_TXT = {
  rate: ['Accidents per 100,000 inhabitants per year', v => v.toFixed(0)],
  kill: ['Deaths per million inhabitants per year', v => v.toFixed(0)],
  sev: ['Deaths per 100 accidents (min. 30 accidents)', v => v.toFixed(1)],
};
let choroScale = { max: 1 };

function radiusScale(z) { return Math.max(0.9, Math.min(6, 0.55 * Math.pow(1.27, z - 4))); }

function buildLayers() {
  const z = map.getZoom();
  const rs = radiusScale(z);
  const filtered = anyFilter();
  const sel = state.selection;
  const layers = [];
  if (state.choro !== 'off') {
    const vals = DEPS.map((_, k) => depMetric(k, state.choro));
    const max = Math.max(...vals.filter(v => v != null)) || 1;
    choroScale = { max, vals };
    layers.push(new deck.GeoJsonLayer({
      id: 'dep-fill', data: depGeo, filled: true, stroked: false, pickable: true, beforeId: LABEL_BEFORE,
      getFillColor: f => { const v = vals[f.properties.idx]; return v == null ? [40, 40, 40, 120] : [...ramp(Math.sqrt(v / max)), 200]; },
      updateTriggers: { getFillColor: [state.choro, filterVersion] },
      transitions: { getFillColor: 300 },
    }));
  } else {
    layers.push(new deck.GeoJsonLayer({ id: 'dep-fill', data: depGeo, filled: true, stroked: false, pickable: true, beforeId: LABEL_BEFORE, getFillColor: [0, 0, 0, 0] }));
  }
  layers.push(new deck.GeoJsonLayer({
    id: 'dep-line', data: depGeo, filled: false, stroked: true, beforeId: LABEL_BEFORE,
    getLineColor: [255, 255, 255, state.choro === 'off' ? 48 : 70], lineWidthUnits: 'pixels', getLineWidth: 0.8,
  }));
  if (filtered) {
    layers.push(new deck.ScatterplotLayer({
      id: 'acc-ghost', beforeId: LABEL_BEFORE,
      data: { length: N, attributes: { getPosition: { value: positions, size: 2 } } },
      getFillColor: [150, 160, 180, 22], radiusUnits: 'pixels', getRadius: 1, radiusScale: rs * 0.85, radiusMinPixels: 0.6,
    }));
  }
  const showPoints = state.choro === 'off' || z > 6.2;
  layers.push(new deck.ScatterplotLayer({
    id: 'acc', beforeId: LABEL_BEFORE, visible: showPoints,
    data: { length: N, attributes: {
      getPosition: { value: positions, size: 2 },
      getFillColor: { value: state.colorBy === 'sev' ? colorsSev : colorsMode, size: 4, normalized: true },
      getRadius: { value: radii, size: 1 },
      getFilterValue: { value: filterVals, size: 1 },
    } },
    radiusUnits: 'pixels', radiusScale: rs, radiusMinPixels: 0.7, stroked: false,
    pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 255],
    extensions: [new deck.DataFilterExtension({ filterSize: 1 })], filterRange: [0.5, 1.5],
  }));
  if (state.colorBy === 'sev' && showPoints && z >= 7.5) {
    layers.push(new deck.ScatterplotLayer({
      id: 'killed-halo', beforeId: LABEL_BEFORE,
      data: { length: killedIdx.length, attributes: { getPosition: { value: killedPos, size: 2 }, getFilterValue: { value: killedFilter, size: 1 } } },
      radiusUnits: 'pixels', getRadius: 1, radiusScale: rs * 1.75 + 2.2, filled: false, stroked: true,
      getLineColor: [255, 61, 61, z < 9 ? 110 : 170], lineWidthUnits: 'pixels', getLineWidth: 0.8,
      extensions: [new deck.DataFilterExtension({ filterSize: 1 })], filterRange: [0.5, 1.5],
    }));
  }
  if (sel && sel.length) {
    const p = new Float32Array(sel.length * 2);
    sel.forEach((i, k) => { p[2 * k] = A.lon[i]; p[2 * k + 1] = A.lat[i]; });
    layers.push(new deck.ScatterplotLayer({
      id: 'selection', data: { length: sel.length, attributes: { getPosition: { value: p, size: 2 } } },
      radiusUnits: 'pixels', getRadius: 1, radiusScale: sel.length === 1 ? 9 : rs * 1.6 + 3, filled: false, stroked: true,
      getLineColor: [255, 255, 255, 230], lineWidthUnits: 'pixels', getLineWidth: 1.6,
    }));
  }
  if (clickRing) {
    layers.push(new deck.ScatterplotLayer({
      id: 'click-ring', data: [clickRing], getPosition: d => d.lngLat, radiusUnits: 'pixels', getRadius: CLICK_PX,
      filled: true, getFillColor: [255, 255, 255, 12], stroked: true, getLineColor: [255, 255, 255, 160], lineWidthUnits: 'pixels', getLineWidth: 1,
    }));
  }
  overlay.setProps({ layers, onHover, onClick: null });
}
let filterVersion = 0;
let clickRing = null;
const CLICK_PX = 14;

/* =========================================================================
   Tooltip
   ========================================================================= */
const tt = $('#tooltip');
function showTip(html, x, y) {
  tt.innerHTML = html; tt.classList.add('on');
  const r = tt.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tt.style.left = left + 'px'; tt.style.top = top + 'px';
}
const hideTip = () => tt.classList.remove('on');

function pairsOf(i) {
  const out = [];
  for (let j = vStart[i]; j < vStart[i + 1]; j++) out.push([V.vmode[j], V.omode[j], V.sev[j]]);
  return out.sort((a, b) => b[2] - a[2]);
}
function whenText(i) {
  const h = A.hour[i];
  return `${DOW_LONG[A.dow[i]]}, ${MONTHS[A.month[i] - 1]} ${YEARS[0] + A.year[i]}${h < 24 ? ` · ${String(h).padStart(2, '0')}h` : ''}`;
}
function onHover(info) {
  const { x, y } = info;
  if (info.layer?.id === 'acc' && info.index >= 0) {
    const i = info.index, s = A.sev[i];
    const p = pairsOf(i)[0];
    showTip(`<div class="tt-t"><span class="badge"><i style="background:${SEV_CSS[s]}"></i>${SEV_NAMES[s]}</span></div>
      <div class="tt-s" style="margin-top:4px">${p ? `${MODE_SHORT[p[0]]} ← ${MODE_SHORT[p[1]].toLowerCase()}` : ''}</div>
      <div class="tt-s">${whenText(i)}</div>
      <div class="tt-s">${A.nveh[i]} vehicle${A.nveh[i] > 1 ? 's' : ''} · ${A.nusers[i]} people involved · ${DEPS[A.dep[i]].name}</div>
      <div class="tt-s" style="color:var(--text-muted);margin-top:3px">Click to inspect</div>`, x + mapRect().left, y + mapRect().top);
  } else if (info.layer?.id === 'dep-fill' && info.object) {
    const k = info.object.properties.idx, d = DEPS[k];
    const m = state.choro !== 'off' ? state.choro : state.rankMetric;
    const v = depMetric(k, m);
    showTip(`<div class="tt-t">${esc(d.name)} <span style="color:var(--text-muted)">(${d.code})</span></div>
      <div class="tt-row"><span>Accidents</span><b>${fmt(depAcc[k])}</b></div>
      <div class="tt-row"><span>Killed</span><b>${fmt(depKill[k])}</b></div>
      <div class="tt-row"><span>${METRIC_TXT[m][0]}</span><b>${v == null ? '–' : METRIC_TXT[m][1](v)}</b></div>`, x + mapRect().left, y + mapRect().top);
  } else hideTip();
}
const mapRect = () => $('#map').getBoundingClientRect();

/* =========================================================================
   Click → inspect accident / local cluster
   ========================================================================= */
map.on('click', e => {
  const pt = e.point, r2 = CLICK_PX * CLICK_PX, hits = [];
  const b = map.getBounds();
  for (let i = 0; i < N; i++) {
    if (!filterVals[i] || !inView[i]) continue;
    const p = map.project([A.lon[i], A.lat[i]]);
    const dx = p.x - pt.x, dy = p.y - pt.y, d2 = dx * dx + dy * dy;
    if (d2 <= r2) hits.push([i, d2]);
  }
  if (!hits.length) {
    // no accident under the cursor: zoom to the department instead
    const info = overlay.pickObject({ x: pt.x, y: pt.y, layerIds: ['dep-fill'] });
    if (info?.object && map.getZoom() < 8) flyToDep(info.object.properties.idx);
    return;
  }
  hits.sort((a, b) => a[1] - b[1]);
  const close = hits.filter(h => h[1] <= 16);
  if (hits.length === 1 || (close.length === 1 && map.getZoom() > 13)) { clickRing = null; openAccident(close.length ? close[0][0] : hits[0][0]); }
  else { clickRing = { lngLat: [e.lngLat.lng, e.lngLat.lat] }; openCluster(hits.map(h => h[0]), e.lngLat); }
});

const detailCache = {};
async function loadDetails(depIdx) {
  const code = DEPS[depIdx].code;
  if (!detailCache[code]) detailCache[code] = fetch(`data/details/${code}.json`).then(r => r.json());
  return detailCache[code];
}

const insp = $('#inspector'), inspBody = $('#insp-body');
$('#insp-close').onclick = closeInspector;
function closeInspector() { insp.classList.add('hidden'); state.selection = null; clickRing = null; buildLayers(); }
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !insp.classList.contains('hidden')) closeInspector(); });

let clusterCtx = null;
function openCluster(idx, lngLat) {
  idx.sort((a, b) => A.sev[b] - A.sev[a] || b - a);
  clusterCtx = { idx, lngLat };
  state.selection = idx;
  const nk = idx.reduce((s, i) => s + A.nkilled[i], 0), nh = idx.reduce((s, i) => s + A.nhosp[i], 0), ns = idx.reduce((s, i) => s + A.nslight[i], 0);
  const pairs = {};
  idx.forEach(i => pairsOf(i).forEach(([v, o, s]) => { const k = v * 9 + o; (pairs[k] ??= [0, 0])[0]++; if (s === 3) pairs[k][1]++; }));
  const top = Object.entries(pairs).sort((a, b) => b[1][0] - a[1][0]).slice(0, 4);
  const depSet = [...new Set(idx.map(i => DEPS[A.dep[i]].name))];
  const LIM = 80;
  inspBody.innerHTML = `
    <div class="insp-kicker">Local cluster · ${CLICK_PX}px around the click</div>
    <div class="insp-title">${fmt(idx.length)} accident${idx.length > 1 ? 's' : ''}</div>
    <div class="insp-sub">${esc(depSet.slice(0, 3).join(', '))}${depSet.length > 3 ? ` +${depSet.length - 3}` : ''}</div>
    <div class="sb-legend" style="margin-top:10px">
      <span><i style="background:${SEV_CSS[3]}"></i>Killed <b>${fmt(nk)}</b></span>
      <span><i style="background:${SEV_CSS[2]}"></i>Hospitalised <b>${fmt(nh)}</b></span>
      <span><i style="background:${SEV_CSS[1]}"></i>Slight <b>${fmt(ns)}</b></span>
    </div>
    <div class="insp-sec"><h3>Main collision pairs here</h3>
      ${top.map(([k, [n, kk]]) => `<div class="tt-row" style="font-size:12px;padding:2px 0"><span>${MODE_SHORT[Math.floor(k / 9)]} <span style="color:var(--text-muted)">←</span> ${MODE_SHORT[k % 9].toLowerCase()}</span><b>${fmt(n)}${kk ? ` <span style="color:var(--sev-3)">· ${kk} killed</span>` : ''}</b></div>`).join('')}
    </div>
    <div class="insp-sec"><h3>Accidents, most severe first</h3>
      <div class="cl-list">${idx.slice(0, LIM).map(i => {
        const p = pairsOf(i)[0];
        return `<div class="cl-item" data-i="${i}" tabindex="0"><span class="d" style="background:${SEV_CSS[A.sev[i]]}"></span>
          <span><div class="t">${p ? `${MODE_SHORT[p[0]]} ← ${MODE_SHORT[p[1]].toLowerCase()}` : 'No casualty recorded'}</div><div class="s">${whenText(i)}</div></span>
          <span class="s">${A.nveh[i]} veh.</span></div>`;
      }).join('')}</div>
      ${idx.length > LIM ? `<p class="hint">…and ${fmt(idx.length - LIM)} more. Zoom in to narrow the cluster.</p>` : ''}
    </div>`;
  inspBody.querySelectorAll('.cl-item').forEach(el => {
    const go = () => openAccident(+el.dataset.i, true);
    el.onclick = go; el.onkeydown = e => { if (e.key === 'Enter') go(); };
  });
  insp.classList.remove('hidden'); insp.scrollTop = 0;
  buildLayers();
  keepClear([lngLat.lng, lngLat.lat]);
}
// pan so the inspected spot is not hidden under the inspector card
function keepClear(ll) {
  const p = map.project(ll), w = $('#map').clientWidth, free = w - insp.offsetWidth - 24;
  if (free > 200 && p.x > free - 30) map.panBy([p.x - free / 2, 0], { duration: 500 });
}

async function openAccident(i, fromCluster = false) {
  if (!fromCluster) clusterCtx = null;
  state.selection = [i];
  buildLayers();
  insp.classList.remove('hidden'); insp.scrollTop = 0;
  inspBody.innerHTML = `<div class="insp-kicker">Loading record…</div>`;
  if (!fromCluster) keepClear([A.lon[i], A.lat[i]]);
  const recs = await loadDetails(A.dep[i]);
  if (state.selection?.[0] !== i) return;
  const r = recs[i];
  if (!r) { inspBody.innerHTML = '<p>Record not found.</p>'; return; }
  inspBody.innerHTML = renderRecord(i, r);
  inspBody.querySelector('.back')?.addEventListener('click', () => openCluster(clusterCtx.idx, clusterCtx.lngLat));
  inspBody.querySelector('.zoomto')?.addEventListener('click', () => map.flyTo({ center: [A.lon[i], A.lat[i]], zoom: Math.max(map.getZoom(), 16.5), speed: 1.6 }));
}

function sevBadge(grav) {
  const s = { 1: 0, 4: 1, 3: 2, 2: 3 }[grav];
  if (s == null) return '<span class="badge">Unknown</span>';
  return `<span class="badge"><i style="background:${SEV_CSS[s]}"></i>${SEV_NAMES[s]}</span>`;
}
function kv(rows) {
  return `<dl class="kv">${rows.filter(r => r[1] != null && r[1] !== '' && r[1] !== '—').map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
}
function equipment(secu) {
  const l = secu.map(s => CODES.secu[s]).filter(Boolean);
  return l.length ? l.join(', ') : 'Not recorded';
}
function renderRecord(i, r) {
  const [id, date, hrmn, adr, com, comName, lum, atm, agg, int, col, lieux, vehs] = r;
  const s = A.sev[i];
  const d = new Date(date + 'T12:00:00');
  const dateTxt = d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const dep = DEPS[A.dep[i]];
  const vehChips = vehs.filter(v => v[0] !== '?').map(v => {
    const m = catvMode(v[1]);
    return `<span class="badge"><i style="background:${MODE_HEX[m]}"></i>${esc(v[0])} ${MODE_SHORT[m]}</span>`;
  }).join(' <span style="color:var(--text-muted)">×</span> ');
  const peds = [];
  const vehHtml = vehs.map(v => {
    const [num, catv, obs, obsm, choc, manv, motor, senc, occutc, users] = v;
    const m = catvMode(catv);
    const occ = users.filter(u => u[0] !== 3);
    users.filter(u => u[0] === 3).forEach(u => peds.push([num, catv, u]));
    const obstacle = [obs > 0 ? CODES.obs[obs] : null, obsm > 0 ? `struck: ${(CODES.obsm[obsm] || '').toLowerCase()}` : null].filter(Boolean).join(' · ');
    return `<div class="veh">
      <div class="veh-head"><span class="veh-id" style="background:${MODE_HEX[m]}">${esc(num)}</span><span class="veh-name">${esc(label('catv', catv, 'Unknown vehicle'))}</span></div>
      <div class="veh-meta">${[label('manv', manv, null), choc > 0 ? `impact: ${label('choc', choc).toLowerCase()}` : null, obstacle || null, motor > 0 ? label('motor', motor) : null, occutc > 0 ? `${occutc} public-transport occupants` : null].filter(Boolean).map(esc).join(' · ')}</div>
      ${occ.length ? `<table class="users">${occ.map(u => userRow(u)).join('')}</table>` : '<div class="veh-meta">No occupant record</div>'}
    </div>`;
  }).join('');
  const pedHtml = peds.map(([num, catv, u]) => `<div class="veh">
      <div class="veh-head"><span class="veh-id" style="background:${MODE_HEX[0]}">PED</span><span class="veh-name">Pedestrian struck by ${esc(num)}</span></div>
      <div class="veh-meta">${[label('locp', u[7], null), label('actp', u[8], null), label('etatp', u[9], null)].filter(Boolean).map(esc).join(' · ')}</div>
      <table class="users">${userRow(u)}</table></div>`).join('');
  const roadHtml = lieux.map((l, k) => {
    const [catr, voie, circ, nbv, vosp, prof, plan, surf, infra, situ, vma, v1, v2, larrout] = l;
    const name = [voie && voie !== 'N/A' ? voie : null].filter(Boolean).join(' ');
    return `${k ? '<div class="lg-sep"></div>' : ''}${kv([
      ['Road', `${esc(label('catr', catr))}${name ? ` · ${esc(name)}` : ''}`],
      ['Speed limit', vma > 0 ? `${vma} km/h` : null],
      ['Traffic', [label('circ', circ, null), nbv > 0 ? `${nbv} lane${nbv > 1 ? 's' : ''}` : null].filter(v => v && v !== '—').join(', ')],
      ['Cycling facility', vosp >= 0 ? label('vosp', vosp) : null],
      ['Profile / layout', [label('prof', prof, null), label('plan', plan, null)].filter(v => v && v !== '—').join(', ')],
      ['Surface', label('surf', surf)],
      ['Infrastructure', infra > 0 ? label('infra', infra) : null],
      ['Position', situ > 0 ? label('situ', situ) : null],
    ])}`;
  }).join('');
  return `
    ${clusterCtx ? `<button class="back">← Back to cluster (${fmt(clusterCtx.idx.length)})</button>` : ''}
    <div class="insp-kicker">Accident ${esc(id)}</div>
    <div class="insp-title">${esc(dateTxt)}${hrmn ? `, ${esc(hrmn)}` : ''}</div>
    <div class="insp-sub">${esc(adr || '')}${adr ? ' — ' : ''}${esc(comName || com)} · ${esc(dep.name)} (${dep.code})</div>
    <div style="margin-top:9px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">${sevBadge({ 0: 1, 1: 4, 2: 3, 3: 2 }[s])} ${vehChips}</div>
    <div class="insp-sec"><h3>Circumstances</h3>${kv([
      ['Lighting', label('lum', lum)], ['Weather', label('atm', atm)], ['Setting', label('agg', agg)],
      ['Intersection', label('int', int)], ['Collision type', label('col', col)],
    ])}</div>
    <div class="insp-sec"><h3>Location & road profile</h3>${roadHtml || '<p class="hint">No road record.</p>'}
      <p class="hint" style="margin-top:6px">${A.lat[i].toFixed(5)}, ${A.lon[i].toFixed(5)} · <button class="back zoomto" style="margin:0">Zoom to street level</button></p></div>
    <div class="insp-sec"><h3>Vehicles & occupants</h3>${vehHtml}</div>
    ${pedHtml ? `<div class="insp-sec"><h3>Pedestrians</h3>${pedHtml}</div>` : ''}`;
}
function userRow(u) {
  const [catu, place, grav, sexe, age, trajet, secu, locp, actp, etatp, om] = u;
  const who = [label('catu', catu, 'User'), catu === 2 && place > 0 ? `seat ${place}` : null].filter(Boolean).join(', ');
  const ident = [label('sexe', sexe, null), age >= 0 ? `${age} y` : null].filter(v => v && v !== '—').join(', ');
  return `<tr><td class="r">${esc(who)}<br><span class="eq">${esc(ident || '—')}</span></td>
    <td><span class="eq">${esc(equipment(secu))}</span>${trajet > 0 ? `<br><span class="eq">Trip: ${esc(label('trajet', trajet))}</span>` : ''}<br><span class="eq">vs ${esc(MODE_SHORT[om].toLowerCase())}</span></td>
    <td style="text-align:right">${sevBadge(grav)}</td></tr>`;
}

/* =========================================================================
   Left panel: crossfilter bars
   ========================================================================= */
const filtersEl = $('#filters');
for (const [k, d] of DIMS.entries()) {
  const el = document.createElement('div');
  el.className = 'fblock'; el.dataset.k = k;
  el.innerHTML = `<div class="fblock-head"><h3>${d.title}</h3><button class="clear">clear</button></div>` +
    (d.kind === 'v'
      ? `<div class="vbars">${d.labels.map((l, b) => `<div class="vbar" data-b="${b}" tabindex="0" aria-label="${d.title} ${l}"><div class="fill"></div></div>`).join('')}</div>
         <div class="vticks">${d.labels.map((l, b) => `<span>${d.key === 'hour' ? (b % 3 === 0 ? l : '') : l}</span>`).join('')}</div>`
      : d.labels.map((l, b) => `<div class="hbar" data-b="${b}" tabindex="0" role="checkbox" aria-checked="false"><span class="lab" title="${l}">${l}</span><span class="track"><span class="fill"></span></span><span class="val"></span></div>`).join(''));
  filtersEl.appendChild(el);
  d.el = el;
  el.querySelector('.clear').onclick = () => { state.sel[d.key].clear(); onFilterChange(); };
  const toggle = (b, additive) => {
    const s = state.sel[d.key];
    if (additive || d.kind !== 'v') s.has(b) ? s.delete(b) : s.add(b);
    else if (s.size === 1 && s.has(b)) s.clear();
    else { s.clear(); s.add(b); }
    onFilterChange();
  };
  el.querySelectorAll('.hbar').forEach(h => {
    h.onclick = () => toggle(+h.dataset.b, true);
    h.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(+h.dataset.b, true); } };
  });
  if (d.kind === 'v') {
    const bars = [...el.querySelectorAll('.vbar')];
    let drag = null;
    bars.forEach(bar => {
      const b = +bar.dataset.b;
      bar.onpointerdown = e => { e.preventDefault(); drag = { start: b, end: b, additive: e.shiftKey || e.metaKey || e.ctrlKey, moved: false }; };
      bar.onpointerenter = () => {
        if (!drag || b === drag.end) return;
        drag.end = b; drag.moved = true;
        const s = state.sel[d.key];
        if (!drag.additive) s.clear();
        const [lo, hi] = [Math.min(drag.start, b), Math.max(drag.start, b)];
        for (let x = lo; x <= hi; x++) s.add(x);
        paintFilters();
      };
      bar.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(b, true); } };
      bar.onmousemove = e => {
        const c = hist[k][b];
        showTip(`<div class="tt-t">${d.key === 'hour' ? `${b}:00–${b}:59` : DOW_LONG[b]}</div><div class="tt-row"><span>Accidents in view</span><b>${fmt(c)}</b></div>`, e.clientX, e.clientY);
      };
      bar.onmouseleave = hideTip;
    });
    window.addEventListener('pointerup', () => {
      if (!drag) return;
      const dd = drag; drag = null;
      if (!dd.moved) toggle(dd.start, dd.additive); else onFilterChange();
    });
  }
}

function paintFilters() {
  DIMS.forEach((d, k) => {
    const s = state.sel[d.key], h = hist[k];
    const max = Math.max(...h) || 1;
    d.el.classList.toggle('active', s.size > 0);
    if (d.kind === 'v') {
      d.el.querySelectorAll('.vbar').forEach((bar, b) => {
        bar.querySelector('.fill').style.height = (100 * h[b] / max) + '%';
        bar.classList.toggle('sel', s.has(b));
      });
    } else {
      d.el.querySelectorAll('.hbar').forEach((row, b) => {
        row.querySelector('.fill').style.width = (100 * h[b] / max) + '%';
        row.querySelector('.val').textContent = fmtK(h[b]);
        row.classList.toggle('sel', s.has(b));
        row.setAttribute('aria-checked', s.has(b));
      });
    }
  });
  $('#reset').disabled = !anyFilter();
}

/* =========================================================================
   Right panel
   ========================================================================= */
function paintSummary() {
  const S = summary;
  const cas = S.sev[1] + S.sev[2] + S.sev[3];
  const full = map.getZoom() < 5.6;
  const filtered = anyFilter();
  $('#scope').innerHTML = `${full ? '<b>All of metropolitan France</b>' : '<b>In the current view</b>'}${filtered ? ' · filtered' : ''} — ${fmt(S.nAcc)} of ${fmt(S.nAccView)} accidents ${state.cell ? 'with a victim in the selected matrix cell' : 'in view'}`;
  $('#kpis').innerHTML = [
    [fmt(S.nAcc), 'Accidents', `${fmt(S.nAcc / nYears())} per year`],
    [fmt(cas), 'Casualties', `${(cas / Math.max(1, S.nAcc)).toFixed(2)} per accident`],
    [fmt(S.sev[3]), 'Killed', `${pct(S.sev[3], cas)}% fatality rate`],
    [fmt(S.sev[2]), 'Hospitalised', `${pct(S.sev[2], cas)}% of casualties`],
  ].map(([v, l, r]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div><div class="r">${r}</div></div>`).join('');
  $('#sevbar').innerHTML = `<div class="sb-track" role="img" aria-label="Casualties by severity">${[3, 2, 1].map(s => `<div style="flex-grow:${S.sev[s] || 0.0001};background:${SEV_CSS[s]}"></div>`).join('')}</div>
    <div class="sb-legend">${[3, 2, 1].map(s => `<span><i style="background:${SEV_CSS[s]}"></i>${SEV_NAMES[s]} <b>${pct(S.sev[s], cas)}%</b></span>`).join('')}</div>`;
  paintMatrix(); paintPairs(); paintAges();
}

function mxValue(c) {
  const m = state.mxMetric;
  if (m === 'cas') return M.cas[c];
  if (m === 'kill') return M.kill[c];
  return M.cas[c] >= 20 ? 100 * M.kill[c] / M.cas[c] : null;
}
function paintMatrix() {
  const el = $('#matrix');
  const vals = []; let max = 0;
  for (let c = 0; c < 72; c++) { const v = mxValue(c); vals.push(v); if (v != null && v > max) max = v; }
  const scale = v => state.mxMetric === 'leth' ? v / (max || 1) : Math.log1p(v) / Math.log1p(max || 1);
  const cs = state.cell;
  const rowTot = r => { let a = 0, k = 0; for (let o = 0; o < 9; o++) { a += M.cas[r * 9 + o]; k += M.kill[r * 9 + o]; } return [a, k]; };
  const tot = r => { const [a, k] = rowTot(r); return state.mxMetric === 'cas' ? fmtK(a) : state.mxMetric === 'kill' ? fmtK(k) : (a >= 20 ? (100 * k / a).toFixed(1) : '–'); };
  let html = `<div class="mx${cs ? ' has-sel' : ''}"><div class="mx-axis">Victim ↓<br>Other party →</div>`;
  for (let o = 0; o < 9; o++) html += `<div class="mx-col${cs && cs.v == null && cs.o === o ? ' sel' : ''}" data-o="${o}" title="All victims whose other party was: ${MODE_SHORT[o]}"><span>${MODE_SHORT[o]}</span></div>`;
  html += `<div class="mx-axis" style="justify-content:center">${state.mxMetric === 'leth' ? '%' : 'Σ'}</div>`;
  for (let r = 0; r < 8; r++) {
    html += `<div class="mx-row${cs && cs.o == null && cs.v === r ? ' sel' : ''}" data-v="${r}" title="All ${MODE_SHORT[r].toLowerCase()} victims"><i style="background:${MODE_HEX[r]}"></i>${MODE_SHORT[r]}</div>`;
    for (let o = 0; o < 9; o++) {
      const c = r * 9 + o, v = vals[c];
      const insel = cs && (cs.v == null || cs.v === r) && (cs.o == null || cs.o === o);
      const t = v ? scale(v) : 0;
      const bg = v ? rampCss(0.08 + 0.92 * t) : '#17181b';
      const txt = v == null ? (M.cas[c] ? '·' : '') : !v ? '' : state.mxMetric === 'leth' ? v.toFixed(v < 10 ? 1 : 0) : fmtK(v);
      html += `<div class="mx-cell${t > 0.72 ? ' dark-ink' : t > 0.3 ? ' mid-ink' : ''}${insel ? ' insel' : ''}${cs && cs.v === r && cs.o === o ? ' sel' : ''}" data-c="${c}" tabindex="0" style="background:${bg}">${txt}</div>`;
    }
    html += `<div class="mx-tot">${tot(r)}</div>`;
  }
  html += `</div><div class="mx-scale"><span>${state.mxMetric === 'leth' ? '0%' : '1'}</span><span class="ramp" style="background:${rampGradient()}"></span><span>${state.mxMetric === 'leth' ? max.toFixed(0) + '% killed' : fmtK(max) + (state.mxMetric === 'kill' ? ' killed' : ' casualties')}</span><span style="margin-left:auto">${state.mxMetric === 'leth' ? 'killed per 100 casualties' : 'log scale'}</span></div>`;
  el.innerHTML = html;
  el.querySelectorAll('.mx-cell').forEach(cell => {
    const c = +cell.dataset.c, r = Math.floor(c / 9), o = c % 9;
    const pick = () => setCell(cs && cs.v === r && cs.o === o ? null : { v: r, o });
    cell.onclick = pick;
    cell.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };
    cell.onmousemove = e => showTip(`<div class="tt-t">${MODE_SHORT[r]} <span style="color:var(--text-muted)">hit by / in collision with</span> ${MODE_SHORT[o].toLowerCase()}</div>
      <div class="tt-row"><span>Casualties</span><b>${fmt(M.cas[c])}</b></div>
      <div class="tt-row"><span>Killed</span><b>${fmt(M.kill[c])}</b></div>
      <div class="tt-row"><span>Hospitalised</span><b>${fmt(M.hosp[c])}</b></div>
      <div class="tt-row"><span>Killed per 100 casualties</span><b>${pct(M.kill[c], M.cas[c])}</b></div>`, e.clientX, e.clientY);
    cell.onmouseleave = hideTip;
  });
  el.querySelectorAll('.mx-row').forEach(row => { const r = +row.dataset.v; row.onclick = () => setCell(cs && cs.v === r && cs.o == null ? null : { v: r, o: null }); });
  el.querySelectorAll('.mx-col').forEach(col => { const o = +col.dataset.o; col.onclick = () => setCell(cs && cs.o === o && cs.v == null ? null : { v: null, o }); });
}

function paintPairs() {
  const arr = [];
  for (let c = 0; c < 72; c++) if (M.cas[c] && cellMatch(Math.floor(c / 9), c % 9)) arr.push(c);
  const key = state.mxMetric === 'kill' || state.mxMetric === 'leth' ? M.kill : M.cas;
  arr.sort((a, b) => key[b] - key[a] || M.cas[b] - M.cas[a]);
  const top = arr.slice(0, 7);
  const max = Math.max(1, ...top.map(c => M.cas[c]));
  $('#pairs').innerHTML = (top.length ? '' : '<p class="hint">No casualties in view.</p>') + top.map(c => {
    const r = Math.floor(c / 9), o = c % 9;
    const w = 100 * M.cas[c] / max, wk = M.kill[c] / M.cas[c], wh = M.hosp[c] / M.cas[c];
    return `<div class="pair" data-c="${c}" title="Filter by this pair"><span class="nm"><span style="color:${MODE_HEX[r]}">●</span> ${MODE_SHORT[r]} <span class="vs">←</span> ${MODE_SHORT[o].toLowerCase()}</span>
      <span class="bar"><div style="width:${w * (1 - wk - wh)}%;background:${SEV_CSS[1]}"></div><div style="width:${w * wh}%;background:${SEV_CSS[2]}"></div><div style="width:${w * wk}%;background:${SEV_CSS[3]};min-width:${M.kill[c] ? 2 : 0}px"></div></span>
      <span class="n">${fmt(M.cas[c])}<small>${M.kill[c] ? fmt(M.kill[c]) + ' killed' : '&nbsp;'}</small></span></div>`;
  }).join('') + `<p class="hint" style="margin:8px 0 0">Ranked by ${key === M.kill ? 'deaths' : 'casualties'} · bar = casualties split by severity.</p>`;
  $('#pairs').querySelectorAll('.pair').forEach(p => { const c = +p.dataset.c; p.onclick = () => setCell({ v: Math.floor(c / 9), o: c % 9 }); });
}

function paintAges() {
  const S = summary, bins = S.ageBins;
  const W = 416, H = 128, padL = 2, padB = 18, bw = (W - padL) / 18;
  const tots = bins.map(b => b[1] + b[2] + b[3]);
  const max = Math.max(1, ...tots);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Casualties by age group and severity">`;
  for (let g = 1; g <= 3; g++) { const y = (H - padB) * (1 - g / 3); svg += `<line x1="0" x2="${W}" y1="${y}" y2="${y}" stroke="#2c2c2a" stroke-width="1"/>`; }
  bins.forEach((b, k) => {
    let y = H - padB;
    const x = padL + k * bw + 1.5, w = bw - 3;
    [1, 2, 3].forEach((s, si) => {
      const h = (H - padB - 4) * b[s] / max;
      if (h <= 0) return;
      const hh = Math.max(si === 2 && b[3] ? 1.5 : 0, h - (si ? 2 : 0));
      y -= h;
      svg += `<rect x="${x}" y="${y + (h - hh)}" width="${w}" height="${hh}" fill="${SEV_CSS[s]}" ${si === 2 ? 'rx="2"' : ''}/>`;
    });
    svg += `<rect x="${padL + k * bw}" y="0" width="${bw}" height="${H}" fill="transparent" data-k="${k}" class="age-hit"/>`;
    if (k % 2 === 0) svg += `<text x="${x + w / 2}" y="${H - 4}" text-anchor="middle">${k === 17 ? '85+' : k * 5}</text>`;
  });
  svg += `<line x1="0" x2="${W}" y1="${H - padB}" y2="${H - padB}" stroke="#3a3a37"/></svg>`;
  const el = $('#ages');
  el.className = 'ages';
  el.innerHTML = svg + `<div class="sb-legend">${[1, 2, 3].map(s => `<span><i style="background:${SEV_CSS[s]}"></i>${SEV_NAMES[s]}</span>`).join('')}</div>`;
  const sx = S.sexCount, sxT = sx[1] + sx[2];
  $('#age-note').textContent = S.medianAge != null ? `median age ${S.medianAge} · ${pct(sx[1], sxT, 0)}% male` : '';
  el.querySelectorAll('.age-hit').forEach(r => {
    const k = +r.dataset.k, b = bins[k], t = tots[k];
    r.onmousemove = e => showTip(`<div class="tt-t">Aged ${k === 17 ? '85+' : `${k * 5}–${k * 5 + 4}`}</div>
      <div class="tt-row"><span>Casualties</span><b>${fmt(t)}</b></div>
      <div class="tt-row"><span>Killed</span><b>${fmt(b[3])}</b></div>
      <div class="tt-row"><span>Hospitalised</span><b>${fmt(b[2])}</b></div>
      <div class="tt-row"><span>Killed per 100 casualties</span><b>${pct(b[3], t)}</b></div>`, e.clientX, e.clientY);
    r.onmouseleave = hideTip;
  });
}

function paintRanking() {
  const m = state.rankMetric;
  const rows = DEPS.map((d, k) => ({ k, d, v: depMetric(k, m) })).filter(r => r.v != null).sort((a, b) => b.v - a.v);
  const max = rows[0]?.v || 1;
  const b = map.getBounds();
  $('#rank-hint').textContent = `${METRIC_TXT[m][0]}${anyFilter() ? ', under current filters' : ''}. Population: INSEE legal population. Click to zoom.`;
  $('#ranking').innerHTML = rows.map((r, n) => {
    const c = map.project ? b.contains([(depBBox[r.k][0][0] + depBBox[r.k][1][0]) / 2, (depBBox[r.k][0][1] + depBBox[r.k][1][1]) / 2]) : false;
    return `<div class="rk${c ? ' inview' : ''}" data-k="${r.k}" title="${esc(r.d.name)}: ${fmt(depAcc[r.k])} accidents, ${fmt(depKill[r.k])} killed"><span class="no">${n + 1}</span><span class="nm"><small>${r.d.code}</small>${esc(r.d.name)}</span><span class="track"><div class="fill" style="width:${100 * r.v / max}%"></div></span><span class="v">${METRIC_TXT[m][1](r.v)}</span></div>`;
  }).join('');
  $('#ranking').querySelectorAll('.rk').forEach(el => el.onclick = () => flyToDep(+el.dataset.k));
}
function flyToDep(k) { map.fitBounds(depBBox[k], { padding: 40, duration: 1200 }); }

/* legend & scope chips */
function paintLegend() {
  let h = '';
  if (state.colorBy === 'sev') {
    h += `<h4>Worst injury in accident</h4>` + [3, 2, 1].map(s => `<div class="lg-row"><span class="lg-dot" style="background:${SEV_CSS[s]};${s === 3 ? 'box-shadow:0 0 0 2px #0c0d0f,0 0 0 3px rgba(255,61,61,.6)' : ''}"></span>${SEV_NAMES[s]}</div>`).join('');
  } else {
    h += `<h4>Mode of the most severe victim</h4>` + MODE_LEGEND_ORDER.map(m => `<div class="lg-row"><span class="lg-dot" style="background:${MODE_HEX[m]}"></span>${MODE_SHORT[m]}</div>`).join('');
  }
  if (state.choro !== 'off') {
    const mx = choroScale.max;
    h += `<div class="lg-sep"></div><h4>${METRIC_TXT[state.choro][0]}</h4><div class="lg-ramp" style="background:${rampGradient()}"></div><div class="lg-ends"><span>0</span><span>${METRIC_TXT[state.choro][1](mx / 4)}</span><span>${METRIC_TXT[state.choro][1](mx)}</span></div>`;
    if (map.getZoom() <= 6.2) h += `<div class="lg-ends" style="margin-top:4px">Zoom in to see individual accidents</div>`;
  }
  $('#legend').innerHTML = h;
}
function paintChips() {
  const chips = [];
  if (state.cell) {
    const { v, o } = state.cell;
    chips.push(['cell', v != null && o != null ? `${MODE_SHORT[v]} ← ${MODE_SHORT[o].toLowerCase()}` : v != null ? `All ${MODE_SHORT[v].toLowerCase()} victims` : `Other party: ${MODE_SHORT[o].toLowerCase()}`]);
  }
  DIMS.forEach(d => {
    const s = [...state.sel[d.key]].sort((a, b) => a - b);
    if (!s.length) return;
    let txt;
    if (d.key === 'hour') txt = compressRanges(s).map(([a, b]) => a === b ? `${a}h` : `${a}–${b + 1}h`).join(', ');
    else txt = s.map(b => d.labels[b]).join(', ');
    chips.push([d.key, `${d.title}: ${txt}`]);
  });
  const el = $('#scope-chip');
  el.style.display = chips.length ? 'flex' : 'none';
  el.innerHTML = chips.map(([k, t]) => `<span class="chip">${esc(t)}<button data-k="${k}" aria-label="Remove filter">×</button></span>`).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => {
    if (b.dataset.k === 'cell') setCell(null); else { state.sel[b.dataset.k].clear(); onFilterChange(); }
  });
}
function compressRanges(a) {
  const out = []; let s = a[0], p = a[0];
  for (let i = 1; i <= a.length; i++) { if (a[i] === p + 1) { p = a[i]; continue; } out.push([s, p]); s = p = a[i]; }
  return out;
}

/* =========================================================================
   Update orchestration
   ========================================================================= */
function onFilterChange() {
  recomputeFilters(); filterVersion++;
  refreshView(); buildLayers(); paintRanking(); paintLegend(); paintChips();
}
function setCell(c) { state.cell = c; recomputeCell(); onFilterChange(); }
function refreshView() { computeView(); paintFilters(); paintSummary(); }

let raf = 0, lastZ = null;
map.on('move', () => {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0; refreshView();
    const z = map.getZoom();
    if (lastZ === null || Math.abs(z - lastZ) > 0.05) { lastZ = z; buildLayers(); paintLegend(); }
  });
});
map.on('moveend', () => { paintRanking(); buildLayers(); });

function bindSeg(id, key, after) {
  const el = $(id);
  el.querySelectorAll('button').forEach(b => b.onclick = () => {
    state[key] = b.dataset.v;
    el.querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
    after();
  });
}
bindSeg('#color-by', 'colorBy', () => { buildLayers(); paintLegend(); });
bindSeg('#choro', 'choro', () => { buildLayers(); paintLegend(); if (state.choro !== 'off') { state.rankMetric = state.choro; syncSeg('#rank-metric', state.choro); paintRanking(); } });
bindSeg('#mx-metric', 'mxMetric', () => { paintMatrix(); paintPairs(); });
bindSeg('#rank-metric', 'rankMetric', paintRanking);
function syncSeg(id, v) { $(id).querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.v === v)); }
$('#reset').onclick = () => { DIMS.forEach(d => state.sel[d.key].clear()); state.cell = null; onFilterChange(); };

/* =========================================================================
   Stories: curated presets with live numbers
   ========================================================================= */
const STORIES = [
  { t: 'Pedestrians after dark', cell: { v: 0, o: null }, sel: { lum: [2, 3] }, d: 'pedestrian victims at night' },
  { t: 'Cyclists and heavy vehicles', cell: { v: 1, o: 6 }, sel: {}, d: 'cyclists in collisions with trucks, buses or trams' },
  { t: 'E-scooters in Greater Paris', cell: { v: 2, o: null }, sel: {}, d: 'e-scooter victims nationwide; view zooms to Paris', bounds: [[2.15, 48.75], [2.55, 48.95]] },
  { t: 'Motorcyclists alone on rural roads', cell: { v: 3, o: 8 }, sel: { agg: [1] }, d: 'single-vehicle motorbike crashes outside towns' },
  { t: 'The 80 km/h network', cell: null, sel: { vmab: [3] }, d: 'accidents on roads limited to 80 km/h' },
  { t: 'Weekend nights', cell: null, sel: { dow: [5, 6], hour: [0, 1, 2, 3, 4, 5] }, d: 'Saturday & Sunday, midnight to 6 am' },
];
function storyStats(st) {
  const allowed = {};
  for (const [k, v] of Object.entries(st.sel)) allowed[k] = new Set(v);
  const dims = DIMS.filter(d => allowed[d.key]);
  let cas = 0, kill = 0;
  const m = st.cell;
  for (let j = 0; j < NV; j++) {
    if (m && !((m.v == null || m.v === V.vmode[j]) && (m.o == null || m.o === V.omode[j]))) continue;
    const a = V.acc[j];
    if (dims.some(d => !allowed[d.key].has(d.bucket[a]))) continue;
    cas++; if (V.sev[j] === 3) kill++;
  }
  return { cas, kill };
}
$('#stories').innerHTML = STORIES.map((s, k) => {
  const r = storyStats(s);
  return `<button class="story" data-k="${k}"><b>${s.t}</b><span>${fmt(r.kill)} killed, ${fmt(r.cas)} casualties — ${s.d}</span></button>`;
}).join('');
$('#stories').querySelectorAll('.story').forEach(b => b.onclick = () => {
  const s = STORIES[+b.dataset.k];
  DIMS.forEach(d => { state.sel[d.key] = new Set(s.sel[d.key] || []); });
  state.cell = s.cell ? { ...s.cell } : null;
  recomputeCell(); onFilterChange();
  map.fitBounds(s.bounds || FRANCE, { padding: 30, duration: 1400 });
});

/* =========================================================================
   About
   ========================================================================= */
{
  const st = meta.stats;
  const totK = V.sev.reduce((s, v) => s + (v === 3), 0);
  $('#lede-years').textContent = `${YEARS[0]}–${YEARS[YEARS.length - 1]}`;
  $('#lede-n').innerHTML = `<b>${fmt(N)}</b> accidents, <b>${fmt(NV)}</b> casualties, <b>${fmt(totK)}</b> deaths.`;
  $('#about-body').innerHTML = `
    <p>Source: ONISR <b>BAAC</b> files (Bulletins d'analyse des accidents corporels), years ${YEARS.join(', ')}, the latest validated releases on data.gouv.fr. The four tables — <i>caractéristiques</i>, <i>lieux</i>, <i>véhicules</i>, <i>usagers</i> — are joined on <code>Num_Acc</code> / <code>id_vehicule</code>.</p>
    <ul>
      <li><b>${fmt(st.metro)}</b> injury accidents in the 96 metropolitan departments; <b>${fmt(N)}</b> mapped (${fmt(st.no_geo)} without usable coordinates).</li>
      <li>Severity follows the BAAC definitions: <b>killed</b> = died within 30 days; <b>hospitalised</b> = admitted for more than 24 h; <b>slightly injured</b> = treated, hospitalised ≤ 24 h. Point colour = the worst outcome among everyone involved.</li>
      <li><b>Who hits whom.</b> Each casualty is classified by their own mode (pedestrians are their own row). The <i>other party</i> is: for a pedestrian, the vehicle that struck them; for a vehicle occupant, the heaviest other vehicle in the accident, else a pedestrian if one was struck, else <i>No other party</i> (single-vehicle crash, obstacle, run-off-road). In 3+ vehicle crashes this is a simplification.</li>
      <li>Modes: <b>E-scooter</b> = motorised personal transporters (EDPM, catv 50); <b>Bicycle</b> includes e-bikes (VAE); <b>Motor 2-wheeler</b> includes mopeds, scooters, motorcycles and 3-wheelers; <b>Heavy vehicle</b> = trucks, road tractors, buses, coaches, trams, trains and farm/special vehicles; <b>Van</b> = light utility vehicles 1.5–3.5 t.</li>
      <li>Cycling infrastructure = a cycle track, cycle lane or reserved lane recorded on any road segment of the accident (<code>vosp</code>), or the accident located on a cycle track (<code>situ</code>=5).</li>
      <li>Department rates use INSEE legal populations (geo.api.gouv.fr) and are annualised over the selected years. Accident counts reflect where police reports were filed and how thoroughly — compare rates, not raw totals.</li>
    </ul>
    <p>Every chart describes what is <b>in the current map view</b> and passes all active filters; department rankings are national. Data: Licence Ouverte / Etalab 2.0.</p>`;
  $('#about-btn').onclick = () => $('#about').showModal();
}

/* =========================================================================
   Boot
   ========================================================================= */
map.on('load', () => {
  recomputeFilters();
  computeView(); paintFilters(); paintSummary(); paintRanking(); paintLegend(); paintChips(); buildLayers();
  $('#loading').classList.add('done');
});
window.__obs = { map, state, setCell, onFilterChange, openAccident, openCluster, DIMS, A, N };
