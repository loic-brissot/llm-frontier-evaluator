// Canvas renderer: a static-ish "base" layer (map, network, stations, labels) and a per-frame "dynamic" layer (trains, selection).
import { CATS, BANDS, bandOf, clamp, ramp, rgba, mix, durShort } from './util.js';
import { getLeg, trainState, pointOnLeg } from './data.js';

const FLOW_LEVELS = 16;
const ALL_RAMP = [[0, [44, 58, 150]], [0.22, [112, 56, 190]], [0.45, [214, 58, 138]], [0.7, [255, 142, 48]], [1, [255, 244, 196]]];
const TRAIN_SIZE = [3.3, 2.5, 1.7];
const TRAIL_PX = [30, 20, 13];
const GLOW_K = [4.6, 4.0, 3.3];
const GLOW_A = [0.95, 0.85, 0.55];

const CITIES = [
  // [label, station name, tier]
  ['Paris', 'Paris Gare du Nord', 1], ['Lyon', 'Lyon Part Dieu', 1], ['Marseille', 'Marseille Saint-Charles', 1],
  ['Lille', 'Lille Flandres', 1], ['Bordeaux', 'Bordeaux Saint-Jean', 1], ['Toulouse', 'Toulouse Matabiau', 1],
  ['Nantes', 'Nantes', 1], ['Strasbourg', 'Strasbourg', 1], ['Nice', 'Nice', 1], ['Rennes', 'Rennes', 1],
  ['Montpellier', 'Montpellier Saint-Roch', 1], ['Bruxelles', 'Bruxelles Midi', 1], ['Genève', 'Genève Cornavin', 1],
  ['Barcelona', 'Barcelone-Sants', 1], ['Luxembourg', 'Luxembourg', 2],
  ['Dijon', 'Dijon', 2], ['Grenoble', 'Grenoble', 2], ['Metz', 'Metz', 2], ['Brest', 'Brest', 2],
  ['Clermont-Ferrand', 'Clermont-Ferrand', 2], ['Limoges', 'Limoges Bénédictins', 2], ['Tours', 'Tours', 2],
  ['Reims', 'Reims', 2], ['Rouen', 'Rouen Rive Droite', 2], ['Le Havre', 'Le Havre', 2], ['Orléans', 'Orléans', 2],
  ['Amiens', 'Amiens', 2], ['Caen', 'Caen', 2], ['Perpignan', 'Perpignan', 2], ['Besançon', 'Besançon Viotte', 2],
  ['Mulhouse', 'Mulhouse', 2], ['Poitiers', 'Poitiers', 2], ['Angers', 'Angers Saint-Laud', 2], ['Le Mans', 'Le Mans', 2],
  ['Nancy', 'Nancy', 2], ['Toulon', 'Toulon', 2], ['Avignon', 'Avignon Centre', 2], ['Saint-Étienne', 'Saint-Étienne Châteaucreux', 2],
  ['Bayonne', 'Bayonne', 2], ['Lausanne', 'Lausanne', 2], ['Stuttgart', 'Stuttgart Hbf', 2], ['Torino', 'Turin Porta Susa', 2],
  ['Frankfurt', 'Francfort sur le Main', 2], ['Basel', 'Basel SBB', 2], ['Quimper', 'Quimper', 3], ['Chambéry', 'Chambéry - Challes-les-Eaux', 3],
  ['Pau', 'Pau', 3], ['Brive', 'Brive-la-Gaillarde', 3], ['Nîmes', 'Nîmes', 3], ['Valence', 'Valence', 3], ['La Rochelle', 'La Rochelle', 3],
  ['Troyes', 'Troyes', 3], ['Cherbourg', 'Cherbourg-en-Cotentin', 3], ['Dunkerque', 'Dunkerque', 3], ['Biarritz', 'Biarritz', 3],
  ['Annecy', 'Annecy', 3], ['Albi', 'Albi', 3], ['Rodez', 'Rodez', 3], ['Carcassonne', 'Carcassonne', 3], ['Calais', 'Calais', 3],
  ['Vannes', 'Vannes', 3], ['Saint-Malo', 'Saint-Malo', 3], ['Colmar', 'Colmar', 3], ['Belfort', 'Belfort', 3], ['Cannes', 'Cannes', 3],
];

export class Renderer {
  constructor(M, baseCanvas, dynCanvas, cam) {
    this.M = M; this.cam = cam;
    this.bc = baseCanvas; this.dc = dynCanvas;
    this.b = baseCanvas.getContext('2d');
    this.d = dynCanvas.getContext('2d');
    this.dpr = 1;
    this.D = null;
    this.legPaths = new Map();
    this.flow = null;
    this.tree = null;
    this.drawn = { n: 0, x: new Float32Array(8192), y: new Float32Array(8192), t: new Int32Array(8192) };
    this._st = {};
    this._pt = { x: 0, y: 0 };

    // static edge paths
    this.allEdgesPath = this._pathOf(M.edges.xy.map((_, i) => i));
    // city anchors
    const byName = new Map();
    M.st.name.forEach((n, i) => { if (!byName.has(n)) byName.set(n, i); });
    this.cities = CITIES.map(([label, sn, tier]) => ({ label, tier, s: byName.get(sn) })).filter((c) => c.s != null);
    this.sprites = CATS.map((c) => this._sprite(c.rgb));
    this.bounds = null;
  }

  resize(W, H, dpr) {
    this.dpr = dpr;
    for (const c of [this.bc, this.dc]) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); c.style.width = W + 'px'; c.style.height = H + 'px'; }
  }

  setDay(D) {
    this.D = D;
    const M = this.M;
    // station importance ranking
    const n = M.st.n;
    const idx = Array.from({ length: n }, (_, i) => i).sort((a, b) => D.callsTotal[b] - D.callsTotal[a]);
    this.rank = new Int32Array(n);
    idx.forEach((s, r) => { this.rank[s] = r; });
    this.maxCalls = Math.max(1, D.callsTotal[idx[0]]);
    this.legPaths.clear();
  }

  _pathOf(list) {
    const p = new Path2D();
    const E = this.M.edges.xy;
    for (const e of list) {
      const xy = E[e];
      p.moveTo(xy[0], xy[1]);
      for (let k = 2; k < xy.length; k += 2) p.lineTo(xy[k], xy[k + 1]);
    }
    return p;
  }
  pathOfCode(code) { return this._pathOf(this.M.edgesOfCode[code]); }

  legPath(id) {
    let p = this.legPaths.get(id);
    if (p) return p;
    const g = getLeg(this.M, id);
    p = new Path2D();
    p.moveTo(g.xy[0], g.xy[1]);
    for (let k = 2; k < g.xy.length; k += 2) p.lineTo(g.xy[k], g.xy[k + 1]);
    this.legPaths.set(id, p);
    return p;
  }

  _sprite(rgb) {
    const s = 64, c = document.createElement('canvas');
    c.width = c.height = s;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    gr.addColorStop(0, rgba(rgb, 1));
    gr.addColorStop(0.18, rgba(rgb, 0.75));
    gr.addColorStop(0.45, rgba(rgb, 0.22));
    gr.addColorStop(1, rgba(rgb, 0));
    g.fillStyle = gr; g.fillRect(0, 0, s, s);
    return c;
  }

  /** (re)build the traffic-volume buckets of the flow view. `counts` is [Int32Array x3], `enabled` flags. */
  setFlow(counts, enabled) {
    const M = this.M, ne = M.edges.n;
    const val = new Int32Array(ne);
    let nEn = 0, only = -1;
    for (let c = 0; c < 3; c++) if (enabled[c]) { nEn++; only = c; }
    for (let c = 0; c < 3; c++) if (enabled[c]) for (let e = 0; e < ne; e++) val[e] += counts[c][e];
    let max = 1;
    for (let e = 0; e < ne; e++) if (val[e] > max) max = val[e];
    const buckets = Array.from({ length: FLOW_LEVELS }, () => []);
    const idle = [];
    for (let e = 0; e < ne; e++) {
      if (val[e] <= 0) { idle.push(e); continue; }
      const q = Math.sqrt(val[e] / max);
      buckets[Math.min(FLOW_LEVELS - 1, Math.floor(q * FLOW_LEVELS))].push(e);
    }
    let stops = ALL_RAMP;
    if (nEn === 1) {
      const rgb = CATS[only].rgb;
      stops = [[0, mix(rgb, [0, 0, 0], 0.7)], [0.55, rgb], [1, mix(rgb, [255, 255, 255], 0.88)]];
    }
    this.flow = {
      val, max, idle: this._pathOf(idle),
      levels: buckets.map((l, i) => ({ path: this._pathOf(l), q: (i + 0.5) / FLOW_LEVELS, n: l.length, rgb: ramp(stops, (i + 0.5) / FLOW_LEVELS) })),
      stops,
    };
  }

  /** Build the shortest-travel-time tree of the accessibility mode from a Router result. */
  setAccess(router) {
    const { M, D } = this;
    const paths = BANDS.map(() => new Path2D());
    const c = D.conns;
    const cls = new Int8Array(M.st.n).fill(-1);
    for (let s = 0; s < M.st.n; s++) {
      const t = router.time(s);
      if (!(t < Infinity) || s === router.origin) continue;
      const b = bandOf(t);
      cls[s] = b;
      const ci = router.via[s];
      if (ci >= 0) {
        const trip = D.trips[c.trip[ci]];
        paths[b].addPath(this.legPath(trip.legs[c.idx[ci]]));
      } else if (router.walkFrom[s] >= 0) {
        const f = router.walkFrom[s];
        const p = new Path2D(); p.moveTo(M.st.x[f], M.st.y[f]); p.lineTo(M.st.x[s], M.st.y[s]);
        paths[b].addPath(p);
      }
    }
    this.tree = { paths, cls, router };
  }

  // ------------------------------------------------------------------ base layer
  _world(ctx) {
    const cam = this.cam, s = cam.scale, d = this.dpr;
    ctx.setTransform(d * s, 0, 0, -d * s, d * (cam.W / 2 + cam.ox - cam.cx * s), d * (cam.H / 2 + cam.oy + cam.cy * s));
  }
  _screen(ctx) { ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0); }

  _stroke(ctx, path, px, style, alpha = 1) {
    ctx.lineWidth = px / this.cam.scale;
    ctx.strokeStyle = style;
    ctx.globalAlpha = alpha;
    ctx.stroke(path);
  }

  /** CSS-transform the cached base bitmap to the current camera (cheap stand-in while the camera moves). */
  transformBase() {
    const b = this.baseCam, c = this.cam;
    if (!b) return;
    const k = c.scale / b.s;
    const tx = (b.cx - c.cx) * c.scale + (c.ox - b.ox);
    const ty = (c.cy - b.cy) * c.scale + (c.oy - b.oy);
    const st = this.bc.style;
    st.transformOrigin = `${b.W / 2 + b.ox}px ${b.H / 2 + b.oy}px`;
    st.transform = `translate(${tx}px, ${ty}px) scale(${k})`;
  }

  drawBase(S) {
    const ctx = this.b, cam = this.cam, M = this.M;
    this.baseCam = { cx: cam.cx, cy: cam.cy, s: cam.scale, ox: cam.ox, oy: cam.oy, W: cam.W, H: cam.H };
    this.bc.style.transform = '';
    const zr = cam.scale / cam.fitScale;
    const zf = clamp(Math.pow(zr, 0.32), 1, 2.4);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, this.bc.width, this.bc.height);
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';

    // --- graticule (Lambert-93 kilometre grid)
    this._screen(ctx);
    {
      const step = zr > 14 ? 10000 : zr > 4 ? 50000 : 100000;
      ctx.lineWidth = 1;
      const x0 = Math.floor(cam.wx(0) / step) * step, x1 = cam.wx(cam.W);
      const y1 = Math.ceil(cam.wy(0) / step) * step, y0 = cam.wy(cam.H);
      ctx.beginPath();
      for (let x = x0; x <= x1; x += step) { const sx = Math.round(cam.sx(x)) + 0.5; ctx.moveTo(sx, 0); ctx.lineTo(sx, cam.H); }
      for (let y = y0 - ((y0 % step) + step) % step; y <= y1; y += step) { const sy = Math.round(cam.sy(y)) + 0.5; ctx.moveTo(0, sy); ctx.lineTo(cam.W, sy); }
      ctx.strokeStyle = 'rgba(110,150,220,0.045)';
      ctx.stroke();
    }

    // --- land
    this._world(ctx);
    for (const c of M.base.countries) {
      ctx.beginPath();
      for (const poly of c.polys) for (const ring of poly) {
        ctx.moveTo(ring[0], ring[1]);
        for (let k = 2; k < ring.length; k += 2) ctx.lineTo(ring[k], ring[k + 1]);
        ctx.closePath();
      }
      ctx.fillStyle = c.fr ? 'rgba(26,43,73,0.94)' : 'rgba(13,22,39,0.9)';
      ctx.fill('evenodd');
      if (c.fr) {
        ctx.lineWidth = 7 / cam.scale; ctx.strokeStyle = 'rgba(70,120,200,0.07)'; ctx.stroke();
        ctx.lineWidth = 2.6 / cam.scale; ctx.strokeStyle = 'rgba(90,150,240,0.12)'; ctx.stroke();
        ctx.lineWidth = 1 / cam.scale; ctx.strokeStyle = 'rgba(140,185,255,0.42)'; ctx.stroke();
      } else {
        ctx.lineWidth = 0.9 / cam.scale; ctx.strokeStyle = 'rgba(120,150,200,0.2)'; ctx.stroke();
      }
    }
    // --- départements
    ctx.beginPath();
    for (const l of M.base.dep) {
      ctx.moveTo(l[0], l[1]);
      for (let k = 2; k < l.length; k += 2) ctx.lineTo(l[k], l[k + 1]);
    }
    ctx.lineWidth = 0.7 / cam.scale; ctx.strokeStyle = 'rgba(120,160,225,0.11)'; ctx.stroke();

    // --- network
    ctx.globalCompositeOperation = 'lighter';
    const mode = S.mode;
    if (mode === 'flow' && this.flow) this._drawFlow(ctx, zf);
    else this._drawPlainNetwork(ctx, zf, mode === 'access');

    if (mode === 'access' && this.tree) {
      const w = [2.7, 2.3, 2.0, 1.7, 1.5];
      // soft glow first (additive), then opaque cores ordered far -> near so that nearer classes stay readable
      for (let b = BANDS.length - 1; b >= 0; b--) this._stroke(ctx, this.tree.paths[b], w[b] * zf * 3.6, rgba(hex(BANDS[b].color), 1), 0.075);
      ctx.globalCompositeOperation = 'source-over';
      for (let b = BANDS.length - 1; b >= 0; b--) {
        this._stroke(ctx, this.tree.paths[b], w[b] * zf + 1.8, 'rgba(4,8,14,1)', 0.55);
        this._stroke(ctx, this.tree.paths[b], w[b] * zf, BANDS[b].color, 0.96);
      }
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';

    // --- stations + labels
    this._screen(ctx);
    this._drawStations(ctx, S, zr, zf);
    this._drawLabels(ctx, S, zr);
  }

  _drawPlainNetwork(ctx, zf, dim) {
    const D = this.D;
    if (!this.plain) this._buildPlain();
    const P = this.plain;
    const k = dim ? 0.55 : 1;
    this._stroke(ctx, P.idle, 0.7 * zf, 'rgba(80,105,150,1)', 0.3 * k);
    this._stroke(ctx, P.used, 4.6 * zf, 'rgba(70,130,230,1)', 0.07 * k);
    this._stroke(ctx, P.used, 1.25 * zf, 'rgba(120,160,235,1)', 0.7 * k);
    this._stroke(ctx, P.lgv, 4 * zf, 'rgba(120,150,255,1)', 0.1 * k);
    this._stroke(ctx, P.lgv, 1.7 * zf, 'rgba(190,208,255,1)', 0.8 * k);
  }
  _buildPlain() {
    const M = this.M, D = this.D;
    const used = [], idle = [], lgv = [];
    const tot = D.flowFull;
    for (let e = 0; e < M.edges.n; e++) {
      const v = tot[0][e] + tot[1][e] + tot[2][e];
      if (v <= 0) idle.push(e);
      else if (M.edges.lgv[e]) lgv.push(e);
      else used.push(e);
    }
    this.plain = { idle: this._pathOf(idle), used: this._pathOf(used), lgv: this._pathOf(lgv) };
  }
  invalidatePlain() { this.plain = null; }

  _drawFlow(ctx, zf) {
    const F = this.flow;
    this._stroke(ctx, F.idle, 0.6 * zf, 'rgba(60,82,120,1)', 0.2);
    for (let i = 0; i < F.levels.length; i++) {
      const L = F.levels[i];
      if (!L.n) continue;
      const w = (0.7 + 5.6 * Math.pow(L.q, 1.15)) * zf;
      const col = rgba(L.rgb, 1);
      const lum = 0.35 + 0.65 * L.q;
      this._stroke(ctx, L.path, w * 3.6, col, 0.05 + 0.07 * L.q);
      this._stroke(ctx, L.path, w * 1.7, col, 0.14 + 0.2 * L.q);
      this._stroke(ctx, L.path, w, col, 0.55 + 0.45 * lum);
    }
  }

  _drawStations(ctx, S, zr, zf) {
    const M = this.M, cam = this.cam, D = this.D;
    const mode = S.mode;
    const K = mode === 'access' ? M.st.n : Math.min(M.st.n, Math.floor(18 * Math.pow(zr, 1.9)));
    const W = cam.W, H = cam.H;
    const cls = mode === 'access' && this.tree ? this.tree.cls : null;
    const origin = mode === 'access' && this.tree ? this.tree.router.origin : -1;
    const halo = new Path2D(), core = new Path2D();
    const byBand = BANDS.map(() => ({ core: new Path2D(), halo: new Path2D() }));
    const none = new Path2D();
    for (let s = 0; s < M.st.n; s++) {
      if (this.rank[s] >= K && s !== origin) continue;
      const x = cam.sx(M.st.x[s]), y = cam.sy(M.st.y[s]);
      if (x < -10 || y < -10 || x > W + 10 || y > H + 10) continue;
      const imp = Math.sqrt(D.callsTotal[s] / this.maxCalls);
      if (mode === 'access') {
        const b = cls ? cls[s] : -1;
        const r = (1.35 + 2.6 * imp) * Math.min(zf, 1.8);
        if (b < 0) { none.moveTo(x + r * 0.6, y); none.arc(x, y, r * 0.6, 0, 6.2832); continue; }
        byBand[b].core.moveTo(x + r, y); byBand[b].core.arc(x, y, r, 0, 6.2832);
        if (b <= 2) { byBand[b].halo.moveTo(x + r * 2.6, y); byBand[b].halo.arc(x, y, r * 2.6, 0, 6.2832); }
      } else {
        const r = (0.9 + 2.1 * imp) * Math.min(zf, 1.9);
        core.moveTo(x + r, y); core.arc(x, y, r, 0, 6.2832);
        halo.moveTo(x + r * 2.8, y); halo.arc(x, y, r * 2.8, 0, 6.2832);
      }
    }
    if (mode === 'access') {
      ctx.fillStyle = 'rgba(80,95,120,0.55)'; ctx.fill(none);
      ctx.globalCompositeOperation = 'lighter';
      for (let b = BANDS.length - 1; b >= 0; b--) {
        const rgb = hex(BANDS[b].color);
        ctx.fillStyle = rgba(rgb, 0.14); ctx.fill(byBand[b].halo);
      }
      ctx.globalCompositeOperation = 'source-over';
      for (let b = BANDS.length - 1; b >= 0; b--) {
        ctx.fillStyle = BANDS[b].color; ctx.fill(byBand[b].core);
        ctx.lineWidth = 0.8; ctx.strokeStyle = 'rgba(4,8,14,0.8)'; ctx.stroke(byBand[b].core);
      }
    } else {
      ctx.fillStyle = 'rgba(150,185,255,0.07)'; ctx.fill(halo);
      ctx.fillStyle = 'rgba(214,230,255,0.82)'; ctx.fill(core);
      ctx.lineWidth = 0.7; ctx.strokeStyle = 'rgba(4,8,14,0.7)'; ctx.stroke(core);
    }
  }

  _drawLabels(ctx, S, zr) {
    const M = this.M, cam = this.cam, D = this.D;
    const occ = [];
    const W = cam.W, H = cam.H;
    const fits = (x0, y0, x1, y1) => {
      if (x1 < 0 || y1 < 0 || x0 > W || y0 > H) return false;
      for (const o of occ) if (x0 < o[2] && x1 > o[0] && y0 < o[3] && y1 > o[1]) return false;
      return true;
    };
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    // curated city names
    ctx.font = '600 10.5px "Inter", system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.letterSpacing = '1.6px';
    const maxTier = zr < 1.3 ? 1 : zr < 2.2 ? 2 : 3;
    for (const c of this.cities) {
      if (c.tier > maxTier) continue;
      const x = cam.sx(M.st.x[c.s]), y = cam.sy(M.st.y[c.s]);
      const txt = c.label.toUpperCase();
      const w = ctx.measureText(txt).width;
      const x0 = x + 9, y0 = y - 9;
      if (!fits(x0 - 2, y0 - 7, x0 + w + 2, y0 + 7)) continue;
      occ.push([x0 - 2, y0 - 7, x0 + w + 2, y0 + 7]);
      ctx.lineWidth = 3.5; ctx.strokeStyle = 'rgba(5,9,16,0.85)'; ctx.strokeText(txt, x0, y0);
      ctx.fillStyle = 'rgba(190,208,238,0.62)'; ctx.fillText(txt, x0, y0);
    }
    ctx.letterSpacing = '0px';
    // station names by importance
    const access = S.mode === 'access' && this.tree;
    const Kl = access ? Math.floor(14 * Math.pow(zr, 1.7)) : Math.floor(5 * Math.pow(zr, 1.9));
    if (zr < 2.4 && !access) return;
    ctx.font = '500 10.5px "Inter", system-ui, -apple-system, "Segoe UI", sans-serif';
    const order = this._order || (this._order = Array.from({ length: M.st.n }, (_, i) => i).sort((a, b) => this.rank[a] - this.rank[b]));
    let shown = 0;
    for (let i = 0; i < order.length && i < Kl && shown < 260; i++) {
      const s = order[i];
      const x = cam.sx(M.st.x[s]), y = cam.sy(M.st.y[s]);
      if (x < 0 || y < 0 || x > W || y > H) continue;
      let txt = M.st.name[s];
      let tcol = null;
      if (access) {
        const t = this.tree.router.time(s);
        if (s === this.tree.router.origin) tcol = '#ffffff';
        else if (t < Infinity) { txt += '  ' + durShort(t); tcol = BANDS[bandOf(t)].color; }
      }
      const w = ctx.measureText(txt).width;
      const x0 = x + 7, y0 = y;
      if (!fits(x0 - 2, y0 - 7, x0 + w + 2, y0 + 7)) continue;
      occ.push([x0 - 2, y0 - 7, x0 + w + 2, y0 + 7]);
      ctx.lineWidth = 3.2; ctx.strokeStyle = 'rgba(5,9,16,0.9)'; ctx.strokeText(txt, x0, y0);
      ctx.fillStyle = 'rgba(224,234,252,0.88)';
      ctx.fillText(txt, x0, y0);
      if (tcol) {
        const nm = M.st.name[s];
        const wn = ctx.measureText(nm).width;
        ctx.fillStyle = tcol; ctx.fillText(txt.slice(nm.length), x0 + wn, y0);
      }
      shown++;
    }
  }

  // ------------------------------------------------------------------ dynamic layer
  drawDyn(S, now) {
    const ctx = this.d, cam = this.cam, M = this.M, D = this.D;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, this.dc.width, this.dc.height);
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    const zr = cam.scale / cam.fitScale;
    const zf = clamp(Math.pow(zr, 0.32), 1, 2.4);
    const pulse = 0.5 + 0.5 * Math.sin(now / 340);

    // highlighted corridor (flow list hover)
    if (S.hoverCode >= 0) {
      this._world(ctx);
      ctx.globalCompositeOperation = 'lighter';
      const p = this.pathOfCode(S.hoverCode);
      this._stroke(ctx, p, 9 * zf, 'rgba(255,255,255,1)', 0.12);
      this._stroke(ctx, p, 2.6 * zf, 'rgba(255,255,255,1)', 0.9);
      ctx.globalCompositeOperation = 'source-over';
    }
    if (S.hoverEdge >= 0) {
      this._world(ctx);
      const p = this._pathOf([S.hoverEdge]);
      this._stroke(ctx, p, 4 * zf, 'rgba(255,255,255,1)', 0.85);
    }

    // accessibility journey (hover)
    if (S.mode === 'access' && S.journey && S.journey.length) {
      this._world(ctx);
      ctx.globalCompositeOperation = 'lighter';
      for (const leg of S.journey) {
        if (leg.type === 'ride') {
          const tr = D.trips[leg.trip];
          for (let i = leg.i0; i < leg.i1; i++) {
            const p = this.legPath(tr.legs[i]);
            this._stroke(ctx, p, 8 * zf, 'rgba(255,255,255,1)', 0.18);
            this._stroke(ctx, p, 2.6 * zf, 'rgba(255,255,255,1)', 0.95);
          }
        } else {
          const p = new Path2D(); p.moveTo(M.st.x[leg.from], M.st.y[leg.from]); p.lineTo(M.st.x[leg.to], M.st.y[leg.to]);
          ctx.setLineDash([4 / cam.scale, 4 / cam.scale]);
          this._stroke(ctx, p, 2 * zf, 'rgba(255,255,255,1)', 0.9);
          ctx.setLineDash([]);
        }
      }
      ctx.globalCompositeOperation = 'source-over';
      this._screen(ctx);
      for (const leg of S.journey) {
        for (const s of [leg.from, leg.to]) {
          const x = cam.sx(M.st.x[s]), y = cam.sy(M.st.y[s]);
          ctx.beginPath(); ctx.arc(x, y, 4.2, 0, 6.2832);
          ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = 'rgba(4,8,14,0.9)'; ctx.stroke();
        }
      }
    }

    // selected train route
    const sel = S.selTrip >= 0 ? D.trips[S.selTrip] : null;
    let selPos = null;
    if (sel) {
      this._world(ctx);
      const rgb = CATS[sel.cat].rgb;
      const st = trainState(M, sel, S.t, this._st);
      const cur = st ? this._st.seg : (S.t < sel.start ? -1 : sel.legs.length);
      ctx.globalCompositeOperation = 'lighter';
      for (let i = 0; i < sel.legs.length; i++) {
        const p = this.legPath(sel.legs[i]);
        if (i < cur) this._stroke(ctx, p, 2.2 * zf, 'rgba(210,225,255,1)', 0.28);
        else {
          this._stroke(ctx, p, 8 * zf, rgba(rgb, 1), 0.14);
          this._stroke(ctx, p, 2.6 * zf, rgba(rgb, 1), 0.95);
        }
      }
      ctx.globalCompositeOperation = 'source-over';
      this._screen(ctx);
      // stops
      ctx.font = '500 10.5px "Inter", system-ui, sans-serif'; ctx.textBaseline = 'middle';
      for (let i = 0; i < sel.st.length; i++) {
        const s = sel.st[i];
        if (sel.fl[i] === 3) continue;
        const x = cam.sx(M.st.x[s]), y = cam.sy(M.st.y[s]);
        const end = i === 0 || i === sel.st.length - 1;
        ctx.beginPath(); ctx.arc(x, y, end ? 5 : 3.2, 0, 6.2832);
        ctx.fillStyle = i <= cur ? 'rgba(20,30,48,1)' : 'rgba(10,16,26,1)'; ctx.fill();
        ctx.lineWidth = end ? 2.2 : 1.6; ctx.strokeStyle = i <= cur ? 'rgba(190,205,235,0.8)' : rgba(rgb, 1); ctx.stroke();
        if (end || zr > 3) {
          const txt = M.st.name[s];
          ctx.lineWidth = 3.2; ctx.strokeStyle = 'rgba(5,9,16,0.92)'; ctx.strokeText(txt, x + 8, y - 8);
          ctx.fillStyle = 'rgba(235,242,255,0.95)'; ctx.fillText(txt, x + 8, y - 8);
        }
      }
      if (st) selPos = { x: this._st.x, y: this._st.y };
    }

    // trains
    const dr = this.drawn;
    dr.n = 0;
    const showTrains = S.mode === 'live' || S.showTrains;
    if (showTrains) {
      this._screen(ctx);
      ctx.globalCompositeOperation = 'lighter';
      const hov = S.hoverCat;
      const bySz = clamp(Math.pow(zr, 0.22), 1, 2.1);
      const trails = [[], [], []];
      const st = this._st, pt = this._pt;
      const trips = D.trips, t = S.t;
      const W = cam.W, H = cam.H;
      for (let i = 0; i < trips.length; i++) {
        const tr = trips[i];
        if (!S.enabled[tr.cat] || tr.start > t || tr.end < t) continue;
        if (!trainState(M, tr, t, st)) continue;
        const x = cam.sx(st.x), y = cam.sy(st.y);
        if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
        if (dr.n < dr.x.length) { dr.x[dr.n] = x; dr.y[dr.n] = y; dr.t[dr.n] = i; dr.n++; }
        const c = tr.cat;
        const dim = hov >= 0 && hov !== c ? 0.2 : 1;
        const R = TRAIN_SIZE[c] * bySz;
        if (st.moving) {
          // comet trail along the track
          const L = TRAIL_PX[c] * Math.sqrt(bySz) / cam.scale;
          pointOnLeg(st.leg, st.dist - L * 0.45, pt); const x1 = cam.sx(pt.x), y1 = cam.sy(pt.y);
          pointOnLeg(st.leg, st.dist - L, pt); const x2 = cam.sx(pt.x), y2 = cam.sy(pt.y);
          trails[c].push(x, y, x1, y1, x2, y2, dim);
        }
        const g = R * GLOW_K[c];
        ctx.globalAlpha = (st.moving ? GLOW_A[c] : GLOW_A[c] * 0.5) * dim;
        ctx.drawImage(this.sprites[c], x - g, y - g, 2 * g, 2 * g);
        ctx.globalAlpha = (st.moving ? 1 : 0.65) * dim;
        ctx.beginPath(); ctx.arc(x, y, st.moving ? R * 0.62 : R * 0.45, 0, 6.2832);
        ctx.fillStyle = st.moving ? '#fff' : CATS[c].color; ctx.fill();
      }
      // trails (batched per category and dim level)
      for (let c = 0; c < 3; c++) {
        const arr = trails[c];
        if (!arr.length) continue;
        const rgb = CATS[c].rgb;
        for (const pass of [0, 1]) {
          ctx.beginPath();
          let dimv = 1;
          for (let k = 0; k < arr.length; k += 7) {
            dimv = arr[k + 6];
            if (pass === 0) { ctx.moveTo(arr[k], arr[k + 1]); ctx.lineTo(arr[k + 2], arr[k + 3]); }
            else { ctx.moveTo(arr[k + 2], arr[k + 3]); ctx.lineTo(arr[k + 4], arr[k + 5]); }
          }
          ctx.lineWidth = (pass === 0 ? 2.2 : 1.5) * Math.sqrt(bySz) * (c === 0 ? 1.15 : c === 2 ? 0.85 : 1);
          ctx.strokeStyle = rgba(rgb, 1);
          ctx.globalAlpha = (pass === 0 ? 0.55 : 0.22) * (hov >= 0 && dimv < 1 ? 0.3 : 1);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
    }

    // hover / selection rings
    this._screen(ctx);
    if (selPos) {
      const x = cam.sx(selPos.x), y = cam.sy(selPos.y);
      const rgb = CATS[sel.cat].rgb;
      ctx.beginPath(); ctx.arc(x, y, 11 + 3 * pulse, 0, 6.2832);
      ctx.lineWidth = 1.6; ctx.strokeStyle = rgba(rgb, 0.95); ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, 17 + 6 * pulse, 0, 6.2832);
      ctx.lineWidth = 1; ctx.strokeStyle = rgba(rgb, 0.35 * (1 - pulse * 0.5)); ctx.stroke();
      S.selPos = selPos;
    } else S.selPos = null;
    if (S.hoverTrip >= 0 && S.hoverTrip !== S.selTrip) {
      const tr = D.trips[S.hoverTrip];
      if (trainState(M, tr, S.t, this._st)) {
        const x = cam.sx(this._st.x), y = cam.sy(this._st.y);
        ctx.beginPath(); ctx.arc(x, y, 10, 0, 6.2832); ctx.lineWidth = 1.4; ctx.strokeStyle = 'rgba(255,255,255,0.85)'; ctx.stroke();
      }
    }
    const ringStation = (s, col, r0, anim) => {
      const x = cam.sx(M.st.x[s]), y = cam.sy(M.st.y[s]);
      ctx.beginPath(); ctx.arc(x, y, r0 + (anim ? 4 * pulse : 0), 0, 6.2832);
      ctx.lineWidth = 1.8; ctx.strokeStyle = col; ctx.stroke();
      if (anim) {
        ctx.beginPath(); ctx.arc(x, y, r0 + 8 + 10 * pulse, 0, 6.2832);
        ctx.lineWidth = 1; ctx.strokeStyle = col.replace(/[\d.]+\)$/, (0.5 * (1 - pulse)) + ')'); ctx.stroke();
      }
    };
    if (S.selStation >= 0) ringStation(S.selStation, 'rgba(255,255,255,0.95)', 9, true);
    if (S.hoverStation >= 0) ringStation(S.hoverStation, 'rgba(255,255,255,0.8)', 8, false);
    if (S.mode === 'access' && this.tree) {
      ringStation(this.tree.router.origin, 'rgba(255,255,255,0.95)', 10, true);
    }
  }

  // ------------------------------------------------------------------ picking
  pickTrain(sx, sy, r = 11) {
    const dr = this.drawn;
    let best = -1, bd = r * r;
    for (let i = 0; i < dr.n; i++) {
      const d = (dr.x[i] - sx) ** 2 + (dr.y[i] - sy) ** 2;
      if (d < bd) { bd = d; best = dr.t[i]; }
    }
    return best;
  }
  pickStation(sx, sy, S, r = 11) {
    const M = this.M, cam = this.cam;
    const zr = cam.scale / cam.fitScale;
    const K = S.mode === 'access' ? M.st.n : Math.floor(18 * Math.pow(zr, 1.9));
    let best = -1, bd = r * r;
    for (let s = 0; s < M.st.n; s++) {
      if (this.rank[s] >= K) continue;
      const d = (cam.sx(M.st.x[s]) - sx) ** 2 + (cam.sy(M.st.y[s]) - sy) ** 2;
      if (d < bd) { bd = d; best = s; }
    }
    return best;
  }
  pickEdge(sx, sy, r = 7) {
    const M = this.M, cam = this.cam, E = M.edges;
    const wx = cam.wx(sx), wy = cam.wy(sy), tol = r / cam.scale;
    let best = -1, bd = tol * tol;
    for (let e = 0; e < E.n; e++) {
      const b = E.bbox;
      if (wx < b[4 * e] - tol || wx > b[4 * e + 2] + tol || wy < b[4 * e + 1] - tol || wy > b[4 * e + 3] + tol) continue;
      const xy = E.xy[e];
      for (let k = 0; k < xy.length - 2; k += 2) {
        const ax = xy[k], ay = xy[k + 1], bx = xy[k + 2], by = xy[k + 3];
        const dx = bx - ax, dy = by - ay;
        const l2 = dx * dx + dy * dy;
        let u = l2 ? ((wx - ax) * dx + (wy - ay) * dy) / l2 : 0;
        u = u < 0 ? 0 : u > 1 ? 1 : u;
        const px = ax + u * dx - wx, py = ay + u * dy - wy;
        const d = px * px + py * py;
        if (d < bd) { bd = d; best = e; }
      }
    }
    return best;
  }
}

function hex(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
