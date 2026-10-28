// Connection Scan Algorithm (earliest arrival) over the day's timetable.
// Travel time = arrival − chosen departure time, so it includes the wait for the first train
// and every transfer wait (minimum transfer time + waiting for the next departure).
import { lowerIdx } from './util.js';

export const MIN_TRANSFER = 300; // seconds, same-station change
const HORIZON = 22 * 3600;       // stop scanning this long after departure

export class Router {
  constructor(M, D) {
    this.M = M; this.D = D;
    const n = M.st.n;
    this.earliest = new Float64Array(n);
    this.via = new Int32Array(n);          // connection index used to arrive (-1: none / walk / origin)
    this.walkFrom = new Int32Array(n);     // station we walked from (-1: none)
    this.tripEnter = new Int32Array(D.trips.length);
    this.origin = -1; this.T = 0;
    this.reached = 0;
    this.includeWait = false;                     // count the wait for the very first train?
    this.startDep = new Float64Array(n);          // departure time of the first train of the fastest itinerary
  }

  run(origin, T) {
    const { M, D, earliest, via, walkFrom, tripEnter } = this;
    const c = D.conns;
    earliest.fill(Infinity); via.fill(-1); walkFrom.fill(-1); tripEnter.fill(-1);
    this.origin = origin; this.T = T;
    earliest[origin] = T;
    const relax = (s, t) => {
      for (const [n2, w] of M.walkAdj[s]) {
        if (t + w < earliest[n2]) { earliest[n2] = t + w; via[n2] = -1; walkFrom[n2] = s; }
      }
    };
    relax(origin, T);
    let i = lowerIdx(c.dep, T, c.n);
    const limit = T + HORIZON;
    for (; i < c.n; i++) {
      const dep = c.dep[i];
      if (dep > limit) break;
      const trip = c.trip[i];
      let ok = tripEnter[trip] >= 0;
      if (!ok && c.board[i]) {
        const f = c.from[i];
        const ready = f === origin ? T : earliest[f] + MIN_TRANSFER;
        if (dep >= ready) { ok = true; tripEnter[trip] = i; }
      }
      if (!ok) continue;
      if (c.alight[i]) {
        const to = c.to[i], arr = c.arr[i];
        if (arr < earliest[to]) {
          earliest[to] = arr; via[to] = i; walkFrom[to] = -1;
          relax(to, arr);
        }
      }
    }
    let r = 0;
    for (let s = 0; s < earliest.length; s++) if (earliest[s] < Infinity && s !== origin) r++;
    this.reached = r;
    this._computeStart();
    return this;
  }

  _computeStart() {
    const { earliest, via, walkFrom, tripEnter, startDep, D } = this;
    const c = D.conns, n = earliest.length;
    const order = [];
    for (let s = 0; s < n; s++) if (earliest[s] < Infinity) order.push(s);
    order.sort((a, b) => earliest[a] - earliest[b]);
    startDep.fill(this.T);
    for (const s of order) {
      if (s === this.origin) continue;
      if (via[s] >= 0) {
        const b = tripEnter[c.trip[via[s]]];
        const f = c.from[b];
        startDep[s] = (f === this.origin || (via[f] < 0 && walkFrom[f] === this.origin)) ? c.dep[b] : startDep[f];
      } else if (walkFrom[s] >= 0) {
        startDep[s] = startDep[walkFrom[s]];
      }
    }
  }

  /** Travel time (s) to station s, Infinity if unreachable */
  time(s) {
    return this.earliest[s] - (this.includeWait ? this.T : this.startDep[s]);
  }
  /** Itinerary to destination d as legs [{type:'ride'|'walk', from,to,dep,arr,trip,i0,i1}] */
  journey(d) {
    const { D, earliest, via, walkFrom, tripEnter } = this;
    const c = D.conns;
    const legs = [];
    let s = d, guard = 0;
    if (!(earliest[d] < Infinity) || d === this.origin) return legs;
    while (s !== this.origin && guard++ < 40) {
      if (via[s] >= 0) {
        const ci = via[s];
        const trip = c.trip[ci];
        const b = tripEnter[trip];
        legs.push({ type: 'ride', from: c.from[b], to: s, dep: c.dep[b], arr: c.arr[ci], trip, i0: c.idx[b], i1: c.idx[ci] + 1 });
        s = c.from[b];
      } else if (walkFrom[s] >= 0) {
        const f = walkFrom[s];
        legs.push({ type: 'walk', from: f, to: s, dep: earliest[f], arr: earliest[s] });
        s = f;
      } else break;
    }
    legs.reverse();
    return legs;
  }
}
