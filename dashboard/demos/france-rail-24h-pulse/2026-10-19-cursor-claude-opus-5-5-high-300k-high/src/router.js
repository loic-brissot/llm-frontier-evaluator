// Connection Scan Algorithm over every scheduled stop-to-stop hop of the service day.
// Transfers need a minimum change time at the station (10 / 7 / 5 min by station size);
// staying aboard the same train costs nothing; walking / urban links come from the
// footpath table built by the pipeline.

import { DAY } from "./data.js";

export const BANDS = [
  { max: 3600, label: "< 1 h", color: [255, 243, 160] },
  { max: 7200, label: "1 – 2 h", color: [255, 190, 77] },
  { max: 10800, label: "2 – 3 h", color: [255, 112, 67] },
  { max: 18000, label: "3 – 5 h", color: [226, 54, 112] },
  { max: Infinity, label: "> 5 h", color: [138, 70, 220] },
];
export const UNREACHED = [70, 84, 104];

export function bandOf(sec) {
  if (!isFinite(sec)) return -1;
  for (let i = 0; i < BANDS.length; i++) if (sec < BANDS[i].max) return i;
  return BANDS.length - 1;
}

export class Router {
  constructor(model) {
    const { S, T } = model;
    this.S = S;
    this.T = T;
    let n = 0;
    for (let k = 0; k < T.n; k++) n += T.stops[k].length / 4 - 1;
    const tmp = { dep: new Int32Array(n), arr: new Int32Array(n), from: new Int32Array(n), to: new Int32Array(n),
      trip: new Int32Array(n), seq: new Int16Array(n), flags: new Uint8Array(n) };
    let w = 0;
    for (let k = 0; k < T.n; k++) {
      const st = T.stops[k];
      const ns = st.length / 4;
      for (let i = 0; i < ns - 1; i++) {
        const dep = st[4 * i + 2];
        const arr = Math.max(st[4 * (i + 1) + 1], dep);
        tmp.dep[w] = dep;
        tmp.arr[w] = arr;
        tmp.from[w] = st[4 * i];
        tmp.to[w] = st[4 * (i + 1)];
        tmp.trip[w] = k;
        tmp.seq[w] = i;
        tmp.flags[w] = ((st[4 * i + 3] & 1) ? 0 : 1) | ((st[4 * (i + 1) + 3] & 2) ? 0 : 2);
        w++;
      }
    }
    const order = new Uint32Array(n).map((_, i) => i);
    order.sort((a, b) => tmp.dep[a] - tmp.dep[b] || tmp.arr[a] - tmp.arr[b]);
    for (const key of Object.keys(tmp)) {
      const src = tmp[key];
      const dst = new src.constructor(n);
      for (let i = 0; i < n; i++) dst[i] = src[order[i]];
      this[key] = dst;
    }
    this.n = n;
    this.change = new Int32Array(S.n);
    for (let s = 0; s < S.n; s++) {
      const seg = S.seg[s];
      this.change[s] = seg === "A" || S.total[s] > 150 ? 600 : seg === "B" || S.total[s] > 40 ? 420 : 300;
    }
    this.arrT = new Float64Array(S.n);
    this.ready = new Float64Array(S.n);
    this.pConn = new Int32Array(S.n);
    this.pEnter = new Int32Array(S.n);
    this.pFoot = new Int32Array(S.n);
    this.enter = new Int32Array(T.n);
  }

  lowerBound(t) {
    let lo = 0, hi = this.n;
    while (lo < hi) {
      const m = (lo + hi) >> 1;
      if (this.dep[m] < t) lo = m + 1;
      else hi = m;
    }
    return lo;
  }

  // Earliest arrival from `src` leaving no earlier than t0. Results in this.arrT etc.
  scan(src, t0, horizon = 18 * 3600) {
    const { arrT, ready, pConn, pEnter, pFoot, enter, S } = this;
    arrT.fill(Infinity);
    ready.fill(Infinity);
    pConn.fill(-1);
    pEnter.fill(-1);
    pFoot.fill(-1);
    enter.fill(-1);
    arrT[src] = t0;
    ready[src] = t0;
    for (const [f, w] of S.foot[src]) {
      if (t0 + w < arrT[f]) { arrT[f] = t0 + w; ready[f] = t0 + w; pFoot[f] = src; }
    }
    const tEnd = t0 + horizon;
    const { dep, arr, from, to, trip, flags } = this;
    for (let c = this.lowerBound(t0); c < this.n; c++) {
      const d = dep[c];
      if (d > tEnd) break;
      const tr = trip[c];
      if (enter[tr] < 0) {
        if ((flags[c] & 1) && ready[from[c]] <= d) enter[tr] = c;
        else continue;
      }
      const v = to[c];
      const a = arr[c];
      if ((flags[c] & 2) && a < arrT[v]) {
        arrT[v] = a;
        ready[v] = a + this.change[v];
        pConn[v] = c;
        pEnter[v] = enter[tr];
        pFoot[v] = -1;
        const fp = S.foot[v];
        for (let i = 0; i < fp.length; i++) {
          const f = fp[i][0], ta = a + fp[i][1];
          if (ta < arrT[f]) { arrT[f] = ta; ready[f] = ta; pFoot[f] = v; pConn[f] = -1; }
        }
      }
    }
  }

  // Departure instants worth testing from src (its own boardable departures + those of
  // stations within walking distance, shifted by the walk time).
  departures(src, from = 0, to = DAY) {
    const set = new Set();
    const lo = this.lowerBound(from - 3600);
    const neigh = new Map([[src, 0]]);
    for (const [f, w] of this.S.foot[src]) neigh.set(f, w);
    for (let c = lo; c < this.n && this.dep[c] < to; c++) {
      const w = neigh.get(this.from[c]);
      if (w === undefined || !(this.flags[c] & 1)) continue;
      const t = this.dep[c] - w;
      if (t >= from && t < to) set.add(t);
    }
    return [...set].sort((a, b) => a - b);
  }

  // Minimum door-to-door rail time from src to every station.
  // mode "best": the fastest trip over the whole service day (includes transfer waits).
  // mode "depart": leaving at clock time t0 (includes the initial wait).
  reach(src, mode, t0) {
    const nS = this.S.n;
    const best = new Float64Array(nS).fill(Infinity);
    const bestT0 = new Float64Array(nS).fill(NaN);
    const firstArr = new Float64Array(nS).fill(Infinity);
    if (mode === "depart") {
      this.scan(src, t0);
      for (let s = 0; s < nS; s++) {
        if (isFinite(this.arrT[s])) { best[s] = this.arrT[s] - t0; bestT0[s] = t0; firstArr[s] = this.arrT[s]; }
      }
    } else {
      const deps = this.departures(src);
      for (let i = deps.length - 1; i >= 0; i--) {
        const t = deps[i];
        this.scan(src, t, 14 * 3600);
        const a = this.arrT;
        for (let s = 0; s < nS; s++) {
          const d = a[s] - t;
          if (d < best[s] || (d === best[s] && a[s] < firstArr[s])) {
            best[s] = d; bestT0[s] = t; firstArr[s] = a[s];
          }
        }
      }
    }
    best[src] = 0;
    return { src, mode, t0, dur: best, t0s: bestT0, arrival: firstArr };
  }

  // Rebuild the fastest itinerary to `dst` for a reach() result.
  journey(res, dst) {
    if (dst === res.src || !isFinite(res.dur[dst])) return null;
    const t0 = res.t0s[dst];
    this.scan(res.src, t0, 20 * 3600);
    const legs = [];
    let cur = dst;
    let guard = 0;
    while (cur !== res.src && guard++ < 50) {
      if (this.pFoot[cur] >= 0) {
        const f = this.pFoot[cur];
        legs.push({ type: "walk", from: f, to: cur, arr: this.arrT[cur], dep: this.arrT[f] });
        cur = f;
        continue;
      }
      const c = this.pConn[cur];
      const e = this.pEnter[cur];
      if (c < 0 || e < 0) return null;
      legs.push({ type: "train", trip: this.trip[c], fromSeq: this.seq[e], toSeq: this.seq[c] + 1,
        from: this.from[e], to: cur, dep: this.dep[e], arr: this.arr[c] });
      cur = this.from[e];
    }
    legs.reverse();
    if (legs.length && legs[0].type === "walk") legs[0].dep = t0;
    return { legs, t0, arrival: this.arrT[dst], dur: this.arrT[dst] - t0 };
  }
}
