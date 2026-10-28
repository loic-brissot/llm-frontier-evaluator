// Loads the static data bundle and derives the indices used by the renderer, the router and the panels.
import { upperIdx, lowerIdx } from './util.js';

const fetchJSON = async (name) => {
  const r = await fetch('data/' + name);
  if (!r.ok) throw new Error(`Failed to load ${name}: ${r.status}`);
  return r.json();
};

function decodeLine(a) {
  const n = a.length >> 1;
  const xy = new Float64Array(a.length);
  let x = a[0], y = a[1];
  xy[0] = x; xy[1] = y;
  for (let i = 1; i < n; i++) {
    x += a[2 * i]; y += a[2 * i + 1];
    xy[2 * i] = x; xy[2 * i + 1] = y;
  }
  return xy;
}

export async function loadStatic(onProgress = () => {}) {
  const names = ['meta', 'network', 'lines', 'stations', 'legs', 'walk', 'basemap'];
  let done = 0;
  const parts = await Promise.all(names.map((n) => fetchJSON(n + '.json').then((r) => { onProgress(++done / names.length); return r; })));
  const [meta, net, lines, st, legs, walk, base] = parts;

  const M = { meta, lines, legsRaw: legs, walk, legCache: new Map() };

  // ---- stations
  const n = st.uic.length;
  M.st = {
    n, uic: st.uic, name: st.name, cc: st.cc, seg: st.seg, commune: st.commune, dept: st.dept, node: st.node,
    x: Float64Array.from(st.x), y: Float64Array.from(st.y),
  };
  M.stByUic = new Map(st.uic.map((u, i) => [u, i]));

  // ---- rail network edges
  const ne = net.pts.length;
  M.edges = {
    n: ne, xy: new Array(ne), u: Int32Array.from(net.u), v: Int32Array.from(net.v), code: Int32Array.from(net.code),
    lgv: Uint8Array.from(net.lgv), len: Float64Array.from(net.len), bbox: new Float64Array(ne * 4),
  };
  for (let i = 0; i < ne; i++) {
    const xy = decodeLine(net.pts[i]);
    M.edges.xy[i] = xy;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let k = 0; k < xy.length; k += 2) {
      if (xy[k] < x0) x0 = xy[k]; if (xy[k] > x1) x1 = xy[k];
      if (xy[k + 1] < y0) y0 = xy[k + 1]; if (xy[k + 1] > y1) y1 = xy[k + 1];
    }
    M.edges.bbox.set([x0, y0, x1, y1], i * 4);
  }
  // edges grouped by line code
  M.edgesOfCode = lines.map(() => []);
  for (let i = 0; i < ne; i++) M.edgesOfCode[M.edges.code[i]].push(i);

  // ---- basemap (decode once)
  M.base = {
    countries: base.countries.map((c) => ({ name: c.name, fr: c.fr, polys: c.polys.map((rings) => rings.map(decodeLine)) })),
    dep: base.dep.map(decodeLine),
  };

  // walking links
  M.walkAdj = Array.from({ length: n }, () => []);
  for (const [a, b, s] of walk) { M.walkAdj[a].push([b, s]); M.walkAdj[b].push([a, s]); }
  return M;
}

/** Geometry of a leg (consecutive stop pair): polyline + cumulative length. */
export function getLeg(M, id) {
  let g = M.legCache.get(id);
  if (g) return g;
  const L = M.legsRaw;
  const sig = L.e[id];
  let pts = [];
  if (sig.length) {
    for (const s of sig) {
      const e = Math.abs(s) - 1;
      const xy = M.edges.xy[e];
      const m = xy.length >> 1;
      if (s > 0) {
        for (let i = pts.length ? 1 : 0; i < m; i++) pts.push(xy[2 * i], xy[2 * i + 1]);
      } else {
        for (let i = pts.length ? m - 2 : m - 1; i >= 0; i--) pts.push(xy[2 * i], xy[2 * i + 1]);
      }
    }
  } else {
    const a = L.a[id], b = L.b[id];
    pts = [M.st.x[a], M.st.y[a], M.st.x[b], M.st.y[b]];
  }
  const xy = Float64Array.from(pts);
  const np = xy.length >> 1;
  const cum = new Float64Array(np);
  for (let i = 1; i < np; i++) cum[i] = cum[i - 1] + Math.hypot(xy[2 * i] - xy[2 * i - 2], xy[2 * i + 1] - xy[2 * i - 1]);
  g = { xy, cum, n: np, len: cum[np - 1] || 1, straight: sig.length === 0 };
  M.legCache.set(id, g);
  return g;
}

/** Decode a day file into trips and the derived indices (connections, per-station calls, profile). */
export async function loadDay(M, key) {
  const raw = await fetchJSON(`day-${key}.json`);
  const trips = new Array(raw.trips.length);
  for (let i = 0; i < trips.length; i++) {
    const r = raw.trips[i];
    const ns = r.s.length;
    const arr = new Int32Array(ns), dep = new Int32Array(ns);
    arr[0] = dep[0] = r.t[0];
    for (let k = 1; k < ns; k++) {
      arr[k] = dep[k - 1] + r.t[2 * k - 1];
      dep[k] = arr[k] + r.t[2 * k];
    }
    const fl = new Uint8Array(ns);
    if (r.f) for (let k = 0; k < ns; k++) fl[k] = r.f[k];
    trips[i] = {
      i, cat: r.c, brand: r.b, num: r.n, rshort: r.r, rlong: r.rl, o: r.o,
      st: Int32Array.from(r.s), arr, dep, legs: Int32Array.from(r.l), fl,
      start: dep[0], end: arr[ns - 1],
    };
  }
  const D = { key, date: raw.date, label: raw.label, long: raw.long, trips };
  indexDay(M, D);
  return D;
}

function indexDay(M, D) {
  const { trips } = D;
  const nst = M.st.n;

  // ---- connections (consecutive stop pairs), sorted by departure
  let nc = 0;
  for (const t of trips) nc += t.st.length - 1;
  const c = {
    n: nc, dep: new Int32Array(nc), arr: new Int32Array(nc), from: new Int32Array(nc), to: new Int32Array(nc),
    trip: new Int32Array(nc), idx: new Int16Array(nc), board: new Uint8Array(nc), alight: new Uint8Array(nc),
  };
  let k = 0;
  for (const t of trips) {
    for (let i = 0; i < t.st.length - 1; i++, k++) {
      c.dep[k] = t.dep[i]; c.arr[k] = t.arr[i + 1]; c.from[k] = t.st[i]; c.to[k] = t.st[i + 1];
      c.trip[k] = t.i; c.idx[k] = i;
      c.board[k] = (t.fl[i] & 1) ? 0 : 1;
      c.alight[k] = (t.fl[i + 1] & 2) ? 0 : 1;
    }
  }
  const order = new Int32Array(nc);
  for (let i = 0; i < nc; i++) order[i] = i;
  order.sort((a, b) => c.dep[a] - c.dep[b] || c.arr[a] - c.arr[b]);
  const sorted = {};
  for (const f of ['dep', 'arr', 'from', 'to', 'trip', 'idx', 'board', 'alight']) {
    const src = c[f], dst = new src.constructor(nc);
    for (let i = 0; i < nc; i++) dst[i] = src[order[i]];
    sorted[f] = dst;
  }
  sorted.n = nc;
  D.conns = sorted;
  D.tripFirstConn = new Int32Array(trips.length);
  // first connection index of each trip (for the CSA "trip reached" bookkeeping)
  {
    const first = new Int32Array(trips.length).fill(-1);
    for (let i = 0; i < nc; i++) {
      const t = sorted.trip[i];
      if (first[t] < 0 || sorted.idx[i] < sorted.idx[first[t]]) first[t] = i;
    }
    D.tripFirstConn = first;
  }

  // ---- per-station departures / arrivals / calls
  const deps = Array.from({ length: nst }, () => []);
  const arrs = Array.from({ length: nst }, () => []);
  const calls = Array.from({ length: nst }, () => []);
  const nCalls = new Int32Array(nst * 3);
  for (const t of trips) {
    const ns = t.st.length;
    for (let i = 0; i < ns; i++) {
      const s = t.st[i];
      const noBoard = t.fl[i] & 1, noAlight = t.fl[i] & 2;
      if (noBoard && noAlight) continue; // pass-through timing point
      const ref = t.i * 256 + i;
      if (!noBoard && i < ns - 1) deps[s].push([t.dep[i], ref]);
      if (!noAlight && i > 0) arrs[s].push([t.arr[i], ref]);
      const when = noBoard ? t.arr[i] : t.dep[i];
      calls[s].push((when + 86400) * 4 + t.cat);
      if (when >= 0 && when < 86400) nCalls[s * 3 + t.cat]++;
    }
  }
  const pack = (lists) => lists.map((l) => {
    l.sort((a, b) => a[0] - b[0]);
    return { t: Int32Array.from(l, (x) => x[0]), ref: Int32Array.from(l, (x) => x[1]) };
  });
  D.deps = pack(deps);
  D.arrs = pack(arrs);
  D.calls = calls.map((l) => Int32Array.from(l).sort());
  D.nCalls = nCalls; // per day (0..24h), by station x category
  D.callsTotal = new Int32Array(nst);
  for (let s = 0; s < nst; s++) D.callsTotal[s] = nCalls[s * 3] + nCalls[s * 3 + 1] + nCalls[s * 3 + 2];

  // ---- 24 h traffic profile: trains in circulation per minute and category
  const diff = [new Int32Array(1442), new Int32Array(1442), new Int32Array(1442)];
  for (const t of trips) {
    if (t.end < 0 || t.start >= 86400) continue;
    const a = Math.max(0, Math.floor(t.start / 60)), b = Math.min(1439, Math.floor(t.end / 60));
    diff[t.cat][a]++; diff[t.cat][b + 1]--;
  }
  D.profile = diff.map((d) => {
    const out = new Int32Array(1440);
    let acc = 0;
    for (let i = 0; i < 1440; i++) { acc += d[i]; out[i] = acc; }
    return out;
  });
  D.peak = Math.max(...Array.from({ length: 1440 }, (_, i) => D.profile[0][i] + D.profile[1][i] + D.profile[2][i]));
  D.flowCache = new Map();
}

/** Calls (train stops) at station s in [t0, t1) split by category; returns total. */
export function callsSplit(D, s, t0, t1, out) {
  const a = D.calls[s];
  const i0 = lowerIdx(a, (t0 + 86400) * 4), i1 = lowerIdx(a, (t1 + 86400) * 4);
  out[0] = out[1] = out[2] = 0;
  for (let i = i0; i < i1; i++) out[a[i] & 3]++;
  return i1 - i0;
}
export function callsBetween(D, s, t0, t1) {
  const a = D.calls[s];
  return lowerIdx(a, (t1 + 86400) * 4) - lowerIdx(a, (t0 + 86400) * 4);
}

/** Active trains at time t (seconds) per category -> Int32Array(3) */
export function countActive(D, t, out) {
  out[0] = out[1] = out[2] = 0;
  const tr = D.trips;
  for (let i = 0; i < tr.length; i++) {
    const x = tr[i];
    if (x.start <= t && t <= x.end) out[x.cat]++;
  }
  return out;
}

/** Position of a trip at time t. Writes {x,y,ang,state,seg,u,dist} into out. Returns false when not running. */
export function trainState(M, trip, t, out) {
  if (t < trip.start || t > trip.end) return false;
  const ns = trip.st.length;
  // last stop index whose departure <= t
  let i = upperIdx(trip.dep, t, ns);
  if (i < 0) i = 0;
  if (i >= ns - 1) {
    // at the terminus
    const s = trip.st[ns - 1];
    out.x = M.st.x[s]; out.y = M.st.y[s]; out.state = 0; out.seg = ns - 2; out.u = 1; out.moving = false; out.stop = ns - 1;
    out.leg = null; out.dist = 0;
    return true;
  }
  if (t < trip.arr[i + 1] || trip.arr[i + 1] === trip.dep[i]) {
    const t0 = trip.dep[i], t1 = trip.arr[i + 1];
    let u = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
    if (u > 1) u = 1;
    // ease in/out so that trains accelerate out of stations
    const e = 0.45 * u + 0.55 * (u * u * (3 - 2 * u));
    const leg = getLeg(M, trip.legs[i]);
    const d = e * leg.len;
    // find segment
    const cum = leg.cum;
    let lo = 0, hi = leg.n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] <= d) lo = m; else hi = m; }
    const seg = cum[hi] - cum[lo] || 1;
    const f = (d - cum[lo]) / seg;
    const xy = leg.xy;
    out.x = xy[2 * lo] + (xy[2 * hi] - xy[2 * lo]) * f;
    out.y = xy[2 * lo + 1] + (xy[2 * hi + 1] - xy[2 * lo + 1]) * f;
    out.ang = Math.atan2(xy[2 * hi + 1] - xy[2 * lo + 1], xy[2 * hi] - xy[2 * lo]);
    out.moving = true; out.seg = i; out.u = u; out.stop = i; out.leg = leg; out.dist = d;
    return true;
  }
  // dwelling at stop i+1
  const s = trip.st[i + 1];
  out.x = M.st.x[s]; out.y = M.st.y[s]; out.moving = false; out.seg = i; out.u = 1; out.stop = i + 1; out.leg = null; out.dist = 0;
  return true;
}

/** Point on a leg polyline at distance d (clamped) */
export function pointOnLeg(leg, d, out) {
  d = d < 0 ? 0 : d > leg.len ? leg.len : d;
  const cum = leg.cum;
  let lo = 0, hi = leg.n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] <= d) lo = m; else hi = m; }
  const seg = cum[hi] - cum[lo] || 1;
  const f = (d - cum[lo]) / seg;
  const xy = leg.xy;
  out.x = xy[2 * lo] + (xy[2 * hi] - xy[2 * lo]) * f;
  out.y = xy[2 * lo + 1] + (xy[2 * hi + 1] - xy[2 * lo + 1]) * f;
  return out;
}

/** Corridor flow: trains per edge (by category) for service day (full) or up to time t (cumulative). */
export function computeFlow(M, D, tUpTo /* null = full day */) {
  const ne = M.edges.n;
  const f = [new Int32Array(ne), new Int32Array(ne), new Int32Array(ne)];
  for (const t of D.trips) {
    if (tUpTo == null) { if (t.o !== 0) continue; } else if (t.o === 1) continue;
    const nl = t.legs.length;
    for (let i = 0; i < nl; i++) {
      if (tUpTo != null && t.arr[i + 1] > tUpTo) break;
      const sig = M.legsRaw.e[t.legs[i]];
      for (let k = 0; k < sig.length; k++) f[t.cat][Math.abs(sig[k]) - 1]++;
    }
  }
  return f;
}

export function tripLabel(M, t) {
  const a = M.st.name[t.st[0]], b = M.st.name[t.st[t.st.length - 1]];
  return `${a} → ${b}`;
}
