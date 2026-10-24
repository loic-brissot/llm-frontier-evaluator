// Loads the compact JSON bundle produced by scripts/build_data.py and expands it into
// GPU-ready typed arrays (trip paths + timestamps per category) and lookup indexes.

export const CATS = ["TGV", "IC", "TER"];
export const CAT_LABEL = ["TGV", "Intercités", "TER"];
export const CAT_COLOR = [
  [255, 79, 126],
  [255, 184, 74],
  [63, 200, 255],
];
export const DAY = 86400;

const M_PER_DEG_LAT = 110540;

export function decodeLine(enc) {
  const n = enc.length / 2;
  const out = new Float64Array(enc.length);
  let x = 0, y = 0;
  for (let i = 0; i < n; i++) {
    x += enc[2 * i];
    y += enc[2 * i + 1];
    out[2 * i] = x / 1e5;
    out[2 * i + 1] = y / 1e5;
  }
  return out;
}

async function fetchJSON(url, onProgress) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  const j = await r.json();
  onProgress?.();
  return j;
}

export async function loadAll(onProgress) {
  const names = ["meta", "stations", "segments", "trips", "corridors", "basemap"];
  let done = 0;
  const res = await Promise.all(
    names.map((n) => fetchJSON(`data/${n}.json`, () => onProgress?.(++done / names.length, n)))
  );
  const raw = Object.fromEntries(names.map((n, i) => [n, res[i]]));
  return buildModel(raw);
}

export function buildModel(raw) {
  const { meta, stations, segments, trips, corridors, basemap } = raw;
  const nS = stations.name.length;
  const S = {
    n: nS,
    name: stations.name,
    uic: stations.uic,
    lon: Float64Array.from(stations.lon),
    lat: Float64Array.from(stations.lat),
    seg: stations.seg,
    dep: stations.dep,
    calls: stations.calls, // [tgv, ic, ter] trains per day
    total: stations.calls.map((c) => c[0] + c[1] + c[2]),
    foot: Array.from({ length: nS }, () => []),
  };
  for (const [a, b, sec] of stations.foot) {
    S.foot[a].push([b, sec]);
    S.foot[b].push([a, sec]);
  }
  S.norm = S.name.map((s) => normalize(s));

  // ---- segments
  const segs = segments.path.map(decodeLine);
  const segCum = segs.map((p) => {
    const n = p.length / 2;
    const c = new Float64Array(n);
    for (let i = 1; i < n; i++) {
      const kx = Math.cos((p[2 * i + 1] * Math.PI) / 180) * 111320;
      const dx = (p[2 * i] - p[2 * i - 2]) * kx;
      const dy = (p[2 * i + 1] - p[2 * i - 1]) * M_PER_DEG_LAT;
      c[i] = c[i - 1] + Math.hypot(dx, dy);
    }
    return c;
  });

  // ---- trips
  const nT = trips.cat.length;
  const T = {
    n: nT,
    cat: Uint8Array.from(trips.cat),
    brand: trips.brand.map((b) => meta.brands[b]),
    num: trips.num,
    route: trips.route,
    line: trips.line,
    prev: Uint8Array.from(trips.prev),
    stops: trips.stops, // flat [station, arr, dep, flags] * k
    segs: trips.segs,
    start: new Float64Array(nT),
    end: new Float64Array(nT),
    vStart: new Int32Array(nT), // vertex offset inside its category buffer
    vLen: new Int32Array(nT),
    stopV: new Array(nT), // per stop: vertex index (arrival) inside category buffer
    length: new Float64Array(nT),
    orig: new Int32Array(nT),
    dest: new Int32Array(nT),
  };

  // first pass: count vertices per category
  const vCount = [0, 0, 0];
  const tripVerts = new Int32Array(nT);
  for (let k = 0; k < nT; k++) {
    const st = T.stops[k];
    const ns = st.length / 4;
    let v = 1;
    for (let i = 0; i < ns - 1; i++) {
      if (st[4 * i + 2] > st[4 * i + 1]) v += 1;
      const sg = T.segs[k][i];
      if (sg !== 0) v += segs[Math.abs(sg) - 1].length / 2 - 1;
    }
    tripVerts[k] = v;
    vCount[T.cat[k]] += v;
  }

  const buf = CATS.map((_, c) => ({
    pos: new Float32Array(vCount[c] * 2),
    time: new Float32Array(vCount[c]),
    startIndices: [],
    trips: [],
    used: 0,
  }));

  for (let k = 0; k < nT; k++) {
    const c = T.cat[k];
    const B = buf[c];
    const st = T.stops[k];
    const ns = st.length / 4;
    let w = B.used;
    T.vStart[k] = w;
    B.startIndices.push(w);
    B.trips.push(k);
    const stopV = new Int32Array(ns);
    const s0 = st[0];
    B.pos[2 * w] = S.lon[s0];
    B.pos[2 * w + 1] = S.lat[s0];
    B.time[w] = st[1];
    stopV[0] = w;
    w++;
    let len = 0;
    for (let i = 0; i < ns - 1; i++) {
      const arr = st[4 * i + 1], dep = st[4 * i + 2];
      const sa = st[4 * i];
      if (dep > arr) {
        B.pos[2 * w] = S.lon[sa];
        B.pos[2 * w + 1] = S.lat[sa];
        B.time[w] = dep;
        w++;
      }
      const nextArr = Math.max(st[4 * (i + 1) + 1], dep);
      const sg = T.segs[k][i];
      if (sg !== 0) {
        const si = Math.abs(sg) - 1;
        const p = segs[si];
        const cum = segCum[si];
        const n = p.length / 2;
        const total = cum[n - 1] || 1;
        len += cum[n - 1];
        const dt = nextArr - dep;
        for (let j = 1; j < n; j++) {
          const jj = sg > 0 ? j : n - 1 - j;
          const frac = sg > 0 ? cum[j] / total : 1 - cum[jj] / total;
          B.pos[2 * w] = p[2 * jj];
          B.pos[2 * w + 1] = p[2 * jj + 1];
          B.time[w] = dep + dt * ease(frac, total);
          w++;
        }
      }
      stopV[i + 1] = w - 1;
    }
    B.used = w;
    T.vLen[k] = w - T.vStart[k];
    T.stopV[k] = stopV;
    T.start[k] = st[2];
    T.end[k] = st[4 * (ns - 1) + 1];
    T.length[k] = len;
    T.orig[k] = st[0];
    T.dest[k] = st[4 * (ns - 1)];
  }

  // per-station event index: [time, trip, stopIndex, kind(0 arr,1 dep)]
  const events = Array.from({ length: nS }, () => []);
  for (let k = 0; k < nT; k++) {
    const st = T.stops[k];
    const ns = st.length / 4;
    for (let i = 0; i < ns; i++) {
      events[st[4 * i]].push([i === 0 ? st[4 * i + 2] : st[4 * i + 1], k, i]);
    }
  }
  for (const e of events) e.sort((a, b) => a[0] - b[0]);
  S.events = events;

  // train calls per station, category and 10-minute bin: index (s * 144 + bin) * 3 + cat
  S.bins = new Uint16Array(nS * 144 * 3);
  for (let k = 0; k < nT; k++) {
    const st = T.stops[k];
    const ns = st.length / 4;
    for (let i = 0; i < ns; i++) {
      const t = st[4 * i + 2];
      if (t < 0 || t >= DAY) continue;
      S.bins[(st[4 * i] * 144 + Math.floor(t / 600)) * 3 + T.cat[k]]++;
    }
  }

  // corridors
  const corr = {
    path: corridors.path.map(decodeLine),
    c: corridors.c,
    line: corridors.line,
  };

  return {
    meta, S, T, segs, segCum, buf, corr,
    basemap: {
      land: basemap.land.map((d) => ({ iso: d.iso, ring: decodeLine(d.ring) })),
      deps: basemap.deps.map((d) => ({ code: d.code, name: d.name, ring: decodeLine(d.ring) })),
      regs: basemap.regs.map((d) => ({ name: d.name, ring: decodeLine(d.ring) })),
    },
  };
}

// Distance fraction -> time fraction with gentle acceleration / braking near stations.
function ease(s, totalMeters) {
  const ramp = Math.min(0.35, 2500 / Math.max(totalMeters, 1)); // ~2.5 km to reach speed
  if (ramp <= 0.001) return s;
  // speed ramps linearly from vmin to 1 over `ramp`; time = integral of 1/speed
  const vmin = 0.35;
  const a = 1 - vmin;
  const rampTime = (ramp / a) * Math.log(1 / vmin);
  const total = 2 * rampTime + (1 - 2 * ramp);
  let t;
  if (s < ramp) t = (ramp / a) * Math.log((vmin + (a * s) / ramp) / vmin);
  else if (s <= 1 - ramp) t = rampTime + (s - ramp);
  else t = total - (ramp / a) * Math.log((vmin + (a * (1 - s)) / ramp) / vmin);
  return t / total;
}

export function normalize(s) {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function fmtTime(sec, withSec = false) {
  let s = Math.round(sec);
  s = ((s % DAY) + DAY) % DAY;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (x) => String(x).padStart(2, "0");
  return withSec ? `${p(h)}:${p(m)}:${p(ss)}` : `${p(h)}:${p(m)}`;
}

export function fmtDur(sec) {
  if (!isFinite(sec)) return "—";
  const m = Math.round(sec / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`;
}
