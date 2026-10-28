// Cross-filter engine: every accident carries a 16-bit "failed filters" mask; one O(N) pass yields
// every chart's numbers ("everything except my own filter") plus the headline selection.

export const NOPP = 11, NMODE = 8, NCELL = NMODE * NOPP;
export const FILTERS = [
  { key: 'year', col: 'year', n: 3, hist: true },
  { key: 'hour', col: 'hour', n: 24, hist: true },
  { key: 'dow', col: 'dow', n: 7, hist: true },
  { key: 'lum', col: 'lum', n: 6, hist: true },
  { key: 'atm', col: 'atm', n: 10, hist: true },
  { key: 'road', col: 'road', n: 7, hist: true },
  { key: 'vma', col: 'vma', n: 9, hist: true },
  { key: 'vosp', col: 'vosp', n: 5, hist: true },
  { key: 'sev', col: 'sev', n: 4, hist: true },
  { key: 'wmode', col: 'wmode', n: 8, hist: true },
  { key: 'agg', col: 'agg', n: 3, hist: true },
  { key: 'int', col: 'int', n: 10, hist: true },
  { key: 'surf', col: 'surf', n: 10, hist: true },
  { key: 'dep', col: 'dep', n: 96, hist: false },
];
const BIT = {};
FILTERS.forEach((f, i) => (BIT[f.key] = 1 << i));
BIT.pair = 1 << FILTERS.length;
BIT.view = 1 << (FILTERS.length + 1);
export const AGE_BINS = 18; // 0-4 … 80-84, 85+ ; index 18 = unknown

export class Engine {
  constructor(acc, rel) {
    this.acc = acc; this.rel = rel; this.N = acc.lon.length;
    this.fail = new Uint16Array(this.N);
    this.vis = new Uint8Array(this.N);
    this.sel = new Uint8Array(this.N);
    this.okEP = new Uint8Array(this.N);
    this.pairHit = new Uint8Array(this.N);
    this.masks = {}; this.counts = {};
    for (const f of FILTERS) { this.masks[f.key] = new Uint8Array(f.n); this.counts[f.key] = 0; }
    this.pairMask = new Uint8Array(NCELL); this.pairCount = 0;
    this.bounds = null;
    this.hist = {};
    this.listeners = [];
    this.R = this.alloc();
    this.base = null;
  }

  alloc() {
    const R = { hist: {}, cell: { n: new Int32Array(NCELL), sev: new Int32Array(NCELL * 4) },
      selCell: { n: new Int32Array(NCELL), sev: new Int32Array(NCELL * 4) },
      age: new Int32Array((AGE_BINS + 1) * 4), ageSex: new Int32Array((AGE_BINS + 1) * 3),
      dep: { n: new Int32Array(96), severe: new Int32Array(96), killed: new Int32Array(96), fatalAcc: new Int32Array(96) },
      sevAcc: new Int32Array(4), people: new Int32Array(4), total: 0, victims: 0 };
    for (const f of FILTERS) if (f.hist) R.hist[f.key] = new Int32Array(f.n * 4);
    return R;
  }

  // ---- filter state -------------------------------------------------------------------
  active(key) { return key === 'pair' ? this.pairCount > 0 : this.counts[key] > 0; }
  anyActive() { return FILTERS.some((f) => this.counts[f.key] > 0) || this.pairCount > 0; }
  has(key, v) { return this.masks[key][v] === 1; }

  toggle(key, v, only = false) {
    const m = this.masks[key];
    if (only) { const wasOnly = m[v] && this.counts[key] === 1; m.fill(0); this.counts[key] = 0; if (!wasOnly) { m[v] = 1; this.counts[key] = 1; } } else {
      m[v] = m[v] ? 0 : 1; this.counts[key] += m[v] ? 1 : -1;
    }
    this.applyDim(key);
  }
  setValues(key, values) {
    const m = this.masks[key]; m.fill(0); this.counts[key] = 0;
    for (const v of values) if (!m[v]) { m[v] = 1; this.counts[key]++; }
    this.applyDim(key);
  }
  clear(key) { this.masks[key].fill(0); this.counts[key] = 0; this.applyDim(key); }
  clearAll() { for (const f of FILTERS) { this.masks[f.key].fill(0); this.counts[f.key] = 0; } this.pairMask.fill(0); this.pairCount = 0; this.rebuildAll(); }

  applyDim(key) {
    const f = FILTERS.find((x) => x.key === key), bit = BIT[key], col = this.acc[f.col], m = this.masks[key], fail = this.fail, N = this.N;
    if (this.counts[key] === 0) { for (let i = 0; i < N; i++) fail[i] &= ~bit; return; }
    for (let i = 0; i < N; i++) fail[i] = m[col[i]] ? fail[i] & ~bit : fail[i] | bit;
  }

  setPairs(cells) {
    this.pairMask.fill(0); this.pairCount = 0;
    for (const c of cells) if (!this.pairMask[c]) { this.pairMask[c] = 1; this.pairCount++; }
    this.applyPair();
  }
  togglePair(c) { this.pairMask[c] = this.pairMask[c] ? 0 : 1; this.pairCount += this.pairMask[c] ? 1 : -1; this.applyPair(); }
  applyPair() {
    const bit = BIT.pair, fail = this.fail, N = this.N;
    if (!this.pairCount) { for (let i = 0; i < N; i++) fail[i] &= ~bit; return; }
    const hit = this.pairHit, { u_acc, u_sev, u_mode, u_opp } = this.rel, pm = this.pairMask;
    hit.fill(0);
    for (let u = 0, U = u_acc.length; u < U; u++) {
      const s = u_sev[u];
      if (s >= 1 && s <= 3 && pm[u_mode[u] * NOPP + u_opp[u]]) hit[u_acc[u]] = 1;
    }
    for (let i = 0; i < N; i++) fail[i] = hit[i] ? fail[i] & ~bit : fail[i] | bit;
  }

  /** bounds = [west, south, east, north] or null */
  setView(bounds) {
    this.bounds = bounds;
    const bit = BIT.view, fail = this.fail, { lon, lat } = this.acc, N = this.N;
    if (!bounds) { for (let i = 0; i < N; i++) fail[i] &= ~bit; return; }
    const [w, s, e, n] = bounds;
    for (let i = 0; i < N; i++) {
      const x = lon[i], y = lat[i];
      fail[i] = x >= w && x <= e && y >= s && y <= n ? fail[i] & ~bit : fail[i] | bit;
    }
  }

  rebuildAll() { for (const f of FILTERS) this.applyDim(f.key); this.applyPair(); this.setView(this.bounds); }

  // ---- aggregation --------------------------------------------------------------------
  run() {
    const R = this.R, { fail, sel, okEP, vis, N, acc } = this;
    for (const k in R.hist) R.hist[k].fill(0);
    R.cell.n.fill(0); R.cell.sev.fill(0); R.selCell.n.fill(0); R.selCell.sev.fill(0);
    R.age.fill(0); R.ageSex.fill(0);
    for (const k in R.dep) R.dep[k].fill(0);
    R.sevAcc.fill(0); R.people.fill(0); R.total = 0; R.victims = 0;

    const hdims = FILTERS.filter((f) => f.hist).map((f) => ({ key: f.key, bit: BIT[f.key], col: acc[f.col], h: R.hist[f.key] }));
    const bitIdx = new Int8Array(1 << 16).fill(-1);
    hdims.forEach((d, k) => { bitIdx[d.bit] = k; });
    const nd = hdims.length, hcols = hdims.map((d) => d.col), hhist = hdims.map((d) => d.h);
    const sevCol = acc.sev, depCol = acc.dep, nk = acc.n_kil, nh = acc.n_hos, ns = acc.n_slt, nu = acc.n_unh;
    const NOT_PAIR = ~BIT.pair, NOT_VIEW = ~BIT.view, RANK_MASK = ~(BIT.dep | BIT.view);
    const people = R.people, sevAcc = R.sevAcc, dep = R.dep;

    for (let i = 0; i < N; i++) {
      const f = fail[i], s = sevCol[i];
      vis[i] = (f & NOT_VIEW) === 0 ? 1 : 0;
      okEP[i] = (f & NOT_PAIR) === 0 ? 1 : 0;
      if (f === 0) {
        sel[i] = 1; R.total++; sevAcc[s]++;
        people[0] += nu[i]; people[1] += ns[i]; people[2] += nh[i]; people[3] += nk[i];
        for (let d = 0; d < nd; d++) hhist[d][hcols[d][i] * 4 + s]++;
      } else {
        sel[i] = 0;
        if ((f & (f - 1)) === 0) { const d = bitIdx[f]; if (d >= 0) hhist[d][hcols[d][i] * 4 + s]++; }
      }
      if ((f & RANK_MASK) === 0) {
        const d = depCol[i];
        dep.n[d]++; dep.killed[d] += nk[i];
        if (s >= 2) dep.severe[d]++;
        if (s === 3) dep.fatalAcc[d]++;
      }
    }

    // user pass: collision-pair matrix (victims = injured or killed) and age structure
    const { u_acc, u_sev, u_mode, u_opp, u_age, u_sex } = this.rel, pm = this.pairMask, pActive = this.pairCount > 0;
    const cN = R.cell.n, cS = R.cell.sev, sN = R.selCell.n, sS = R.selCell.sev, age = R.age, ageSex = R.ageSex;
    for (let u = 0, U = u_acc.length; u < U; u++) {
      const a = u_acc[u];
      if (!okEP[a]) continue;
      const s = u_sev[u];
      if (s < 1 || s > 3) continue;
      const c = u_mode[u] * NOPP + u_opp[u];
      cN[c]++; cS[c * 4 + s]++;
      if (sel[a] && (!pActive || pm[c])) {
        sN[c]++; sS[c * 4 + s]++; R.victims++;
        const ag = u_age[u], b = ag === 255 ? AGE_BINS : Math.min(AGE_BINS - 1, (ag / 5) | 0);
        age[b * 4 + s]++; ageSex[b * 3 + u_sex[u]]++;
      }
    }
    if (!this.base) this.base = this.snapshot();
    for (const fn of this.listeners) fn(R);
    return R;
  }

  snapshot() {
    const R = this.R;
    return { total: R.total, sevAcc: Int32Array.from(R.sevAcc), people: Int32Array.from(R.people) };
  }
  onRun(fn) { this.listeners.push(fn); }
}

export const cellOf = (mode, opp) => mode * NOPP + opp;
