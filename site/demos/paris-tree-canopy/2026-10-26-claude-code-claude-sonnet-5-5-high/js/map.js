// Map: MapLibre basemap + a custom canvas layer that renders 220k trees.
//   z < ~14.5  hexagonal bins (cached per integer level), colour = dominant class / mean value
//   z > ~14.8  individual trees, drawn as true-to-scale crowns
//   always     remarkable-tree badges, arrondissement outlines and numerals
import {
  DATA, mercX, mercY, unmercX, unmercY, queryRect, treeName, treeLatin, GENUS_SLOTS,
} from "./data.js";
import { view, filters } from "./state.js";
import { COLORS, GOLD, classArray, classOfHeight, classOfGirth, legendLabels } from "./theme.js";
import { fmt, h, clamp } from "./format.js";

const maplibregl = window.maplibregl;
const TILE = 512, SQRT3 = Math.sqrt(3), M_PER_WORLD = 40075016.686;
const HEXPX = 9;                    // hex circumradius in px at the integer zoom level
const FADE = [14.2, 14.9];          // crossfade hex -> trees
const PARIS_BOUNDS = [[2.215, 48.812], [2.495, 48.905]];
const MAX_BOUNDS = [[2.0, 48.68], [2.7, 49.03]];
const STYLE = {
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
};
const TINT = {
  light: { water: "#c7dce4", park: "rgba(206,227,196,0.62)", bg: "#f6f5f0" },
  dark: { water: "#1d2a33", park: "#13201a", bg: "#0f1110" },
};
const PARK_LAYERS = ["landcover", "park_national_park", "park_nature_reserve", "landuse"];

const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

export function createMap({ el, theme = "light", mode = "genus", onSelect, onViewChange, onZoomState }) {
  const D = DATA;
  const S = { theme, mode, selected: -1, cls: classArray(mode, D), binsCache: new Map(), hoverRow: -1, hoverCell: null,
    lastLevel: -1, levelAt: 0, tipOn: false };

  const map = new maplibregl.Map({
    container: el, style: STYLE[theme], bounds: PARIS_BOUNDS, fitBoundsOptions: { padding: 24 },
    minZoom: 10.2, maxZoom: 20.5, maxBounds: MAX_BOUNDS, dragRotate: false, pitchWithRotate: false,
    attributionControl: false, fadeDuration: 0, renderWorldCopies: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  // ---------------------------------------------------------------- basemap tint + arrondissement layers
  let styleOK = false;
  const blankStyle = (t) => ({ version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": TINT[t].bg } }] });
  map.on("style.load", () => {
    styleOK = true;
    const t = TINT[S.theme];
    try {
      if (map.getLayer("water")) map.setPaintProperty("water", "fill-color", t.water);
      if (map.getLayer("background")) map.setPaintProperty("background", "background-color", t.bg);
      for (const id of PARK_LAYERS) if (map.getLayer(id)) map.setPaintProperty(id, "fill-color", t.park);
      for (const id of ["place_suburbs", "place_hamlet"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
      if (map.getLayer("building") && S.theme === "light") map.setPaintProperty("building", "fill-color", "#e6e4dc");
    } catch { /* style variant without these layers */ }
    addArrLayers();
    updateArrSelection();
  });
  setTimeout(() => { if (!styleOK) map.setStyle(blankStyle(S.theme)); }, 8000);

  let arrSel = [];
  function addArrLayers() {
    if (map.getSource("arr")) return;
    map.addSource("arr", { type: "geojson", data: D.arrGeo });
    const dark = S.theme === "dark";
    map.addLayer({ id: "arr-dim", type: "fill", source: "arr", paint: { "fill-color": dark ? "#000" : "#ffffff", "fill-opacity": 0 } });
    map.addLayer({ id: "arr-sel", type: "fill", source: "arr", paint: { "fill-color": dark ? "#6fc08c" : "#1f5f3b", "fill-opacity": 0 } });
    map.addLayer({ id: "arr-line", type: "line", source: "arr", paint: {
      "line-color": dark ? "rgba(240,239,236,0.30)" : "rgba(31,60,44,0.32)",
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.8, 15, 1.4], "line-dasharray": [3, 2] } });
    map.addLayer({ id: "arr-sel-line", type: "line", source: "arr", paint: {
      "line-color": dark ? "#8fd4a8" : "#1f5f3b", "line-width": 2.2, "line-opacity": 0 } });
  }
  function updateArrSelection() {
    if (!map.getLayer("arr-dim")) return;
    const has = arrSel.length > 0;
    const inSel = ["in", ["get", "n"], ["literal", arrSel.map((a) => a + 1)]];
    map.setFilter("arr-sel", has ? inSel : null);
    map.setFilter("arr-sel-line", has ? inSel : null);
    map.setFilter("arr-dim", has ? ["!", inSel] : null);
    map.setPaintProperty("arr-dim", "fill-opacity", has ? 0.55 : 0);
    map.setPaintProperty("arr-sel", "fill-opacity", has ? 0.07 : 0);
    map.setPaintProperty("arr-sel-line", "line-opacity", has ? 1 : 0);
  }

  // ---------------------------------------------------------------- canvas layer
  const canvas = h("canvas", { class: "tree-canvas" });
  map.getCanvasContainer().appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const tip = h("div", { class: "map-tip", role: "status", "aria-live": "polite" });
  el.appendChild(tip);
  let W = 0, H = 0, dpr = 1;

  function fit() {
    W = el.clientWidth; H = el.clientHeight; dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
  }

  // ---- hex bins (independent of the viewport; cached per integer zoom level until filters change)
  const KEY_OFF = 1 << 21, KEY_MUL = 1 << 22;
  function hexCell(x, y, s) {
    const qf = ((SQRT3 / 3) * x - y / 3) / s, rf = (2 / 3) * y / s, sf = -qf - rf;
    let q = Math.round(qf), r = Math.round(rf), t = Math.round(sf);
    const dq = Math.abs(q - qf), dr = Math.abs(r - rf), dt = Math.abs(t - sf);
    if (dq > dr && dq > dt) q = -r - t; else if (dr > dt) r = -q - t;
    return [q, r];
  }
  function getBins(L) {
    let b = S.binsCache.get(L);
    if (b) return b;
    const s = HEXPX / (TILE * 2 ** L), idx = view.idx, map_ = new Map();
    const cell = new Int32Array(idx.length);
    let nCells = 0;
    for (let k = 0; k < idx.length; k++) {
      const i = idx[k], [q, r] = hexCell(D.mx[i], D.my[i], s), key = (q + KEY_OFF) * KEY_MUL + (r + KEY_OFF);
      let c = map_.get(key);
      if (c === undefined) { c = nCells++; map_.set(key, c); }
      cell[k] = c;
    }
    b = {
      s, key: map_, n: new Uint32Array(nCells), cat: new Uint32Array(nCells * 9), sumH: new Float32Array(nCells),
      nH: new Uint32Array(nCells), sumC: new Float32Array(nCells), nC: new Uint32Array(nCells),
      sumS: new Float32Array(nCells), nS: new Uint32Array(nCells), rem: new Uint16Array(nCells),
      q: new Int32Array(nCells), r: new Int32Array(nCells), max: 1,
    };
    for (const [key, c] of map_) { b.q[c] = Math.floor(key / KEY_MUL) - KEY_OFF; b.r[c] = (key % KEY_MUL) - KEY_OFF; }
    for (let k = 0; k < idx.length; k++) {
      const i = idx[k], c = cell[k];
      b.n[c]++;
      b.cat[c * 9 + D.slot[D.genus[i]]]++;
      if (D.height[i]) { b.sumH[c] += D.height[i]; b.nH[c]++; }
      if (D.circ[i]) { b.sumC[c] += D.circ[i]; b.nC[c]++; }
      if (D.stage[i] < 4) { b.sumS[c] += D.stage[i]; b.nS[c]++; }
      if (D.flag[i]) b.rem[c]++;
    }
    for (let c = 0; c < nCells; c++) if (b.n[c] > b.max) b.max = b.n[c];
    S.binsCache.set(L, b);
    return b;
  }
  function binClass(b, c) {
    switch (S.mode) {
      case "genus": {
        // "Other" pools ~195 genera, so it only wins a cell when it clearly outweighs the best named genus.
        let best = 0, bi = 8;
        for (let k = 0; k < 8; k++) { const v = b.cat[c * 9 + k]; if (v > best) { best = v; bi = k; } }
        return b.cat[c * 9 + 8] * 0.4 > best ? 8 : bi;
      }
      case "height": return b.nH[c] ? classOfHeight(b.sumH[c] / b.nH[c]) : 6;
      case "girth": return b.nC[c] ? classOfGirth(b.sumC[c] / b.nC[c]) : 6;
      default: return b.nS[c] ? Math.min(3, Math.round(b.sumS[c] / b.nS[c])) : 4;
    }
  }

  // ---- projection helpers (identical maths to MapLibre in mercator, no rotation / pitch)
  let P = null;
  function projection() {
    const c = map.getCenter(), z = map.getZoom(), ws = TILE * 2 ** z, cx = mercX(c.lng), cy = mercY(c.lat);
    P = { z, ws, cx, cy, mpp: (M_PER_WORLD * Math.cos((c.lat * Math.PI) / 180)) / ws };
    return P;
  }
  const sx = (x) => (x - P.cx) * P.ws + W / 2;
  const sy = (y) => (y - P.cy) * P.ws + H / 2;

  const HEX_OFF = Array.from({ length: 6 }, (_, k) => [Math.cos(((30 + 60 * k) * Math.PI) / 180), Math.sin(((30 + 60 * k) * Math.PI) / 180)]);

  function drawHex(alpha) {
    const L = clamp(Math.floor(P.z), 10, 14);
    if (L !== S.lastLevel) { S.lastLevel = L; S.levelAt = performance.now(); }
    const fade = smooth(0, 1, (performance.now() - S.levelAt) / 260);
    if (fade < 1) requestAnimationFrame(draw);
    const b = getBins(L), pal = COLORS[S.theme][S.mode];
    const R = HEXPX * 2 ** (P.z - L), Rd = R * 0.93, lmax = Math.log1p(b.max);
    const xa = P.cx - (W / 2 + R * 2) / P.ws, xb = P.cx + (W / 2 + R * 2) / P.ws;
    const ya = P.cy - (H / 2 + R * 2) / P.ws, yb = P.cy + (H / 2 + R * 2) / P.ws;
    const outline = S.theme === "dark" ? "rgba(0,0,0,.35)" : "rgba(255,255,255,.55)";
    ctx.lineWidth = 1; ctx.strokeStyle = outline;
    for (let c = 0; c < b.n.length; c++) {
      const wx = b.s * SQRT3 * (b.q[c] + b.r[c] / 2), wy = b.s * 1.5 * b.r[c];
      if (wx < xa || wx > xb || wy < ya || wy > yb) continue;
      const x = sx(wx), y = sy(wy), t = Math.log1p(b.n[c]) / lmax;
      ctx.globalAlpha = alpha * fade * (0.3 + 0.66 * t);
      ctx.fillStyle = pal[binClass(b, c)];
      ctx.beginPath();
      for (let k = 0; k < 6; k++) { const px = x + HEX_OFF[k][0] * Rd, py = y + HEX_OFF[k][1] * Rd; k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }
      ctx.closePath(); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // ---- individual trees
  const crownPx = (i) => {
    const hm = D.height[i] || 8;
    return clamp((0.26 * hm + 0.9) / P.mpp, P.z < 16 ? 1.5 : 2, 90);
  };
  const buckets = Array.from({ length: 9 }, () => ({ x: [], y: [], r: [] }));
  function drawDots(alpha) {
    const xa = P.cx - (W / 2 + 40) / P.ws, xb = P.cx + (W / 2 + 40) / P.ws;
    const ya = P.cy - (H / 2 + 40) / P.ws, yb = P.cy + (H / 2 + 40) / P.ws;
    for (const bk of buckets) { bk.x.length = 0; bk.y.length = 0; bk.r.length = 0; }
    const ghosts = [], mask = view.mask, cls = S.cls, ghostOn = view.active && P.z >= 15.4;
    queryRect(D, xa, ya, xb, yb, (i) => {
      if (!mask[i]) { if (ghostOn) ghosts.push(sx(D.mx[i]), sy(D.my[i])); return; }
      const bk = buckets[cls[i]];
      bk.x.push(sx(D.mx[i])); bk.y.push(sy(D.my[i])); bk.r.push(crownPx(i));
    });
    const pal = COLORS[S.theme][S.mode], dark = S.theme === "dark";
    if (ghosts.length && ghosts.length < 160000) {
      ctx.globalAlpha = alpha * 0.5; ctx.fillStyle = dark ? "#4a4a46" : "#cfcdc3";
      for (let k = 0; k < ghosts.length; k += 2) ctx.fillRect(ghosts[k] - 1, ghosts[k + 1] - 1, 2, 2);
    }
    const big = P.z >= 16.2;
    for (let c = 0; c < 9; c++) {
      const bk = buckets[c];
      if (!bk.x.length) continue;
      ctx.beginPath();
      for (let k = 0; k < bk.x.length; k++) { ctx.moveTo(bk.x[k] + bk.r[k], bk.y[k]); ctx.arc(bk.x[k], bk.y[k], bk.r[k], 0, 6.2832); }
      ctx.fillStyle = pal[c];
      ctx.globalAlpha = alpha * (big ? 0.5 : 0.78);
      ctx.fill();
      if (big) {
        ctx.globalAlpha = alpha * 0.95; ctx.strokeStyle = pal[c]; ctx.lineWidth = 1.1; ctx.stroke();
        // trunk dot
        ctx.beginPath();
        for (let k = 0; k < bk.x.length; k++) { ctx.moveTo(bk.x[k] + 1.3, bk.y[k]); ctx.arc(bk.x[k], bk.y[k], 1.3, 0, 6.2832); }
        ctx.fillStyle = dark ? "#0b0b0b" : "#ffffff"; ctx.globalAlpha = alpha * 0.9; ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
  }

  // ---- arrondissement numerals
  function drawArrLabels() {
    const a = 1 - smooth(13.6, 14.6, P.z);
    if (a < 0.02) return;
    const dark = S.theme === "dark", feats = D.arrGeo.features;
    ctx.font = `600 ${P.z < 12.4 ? 11 : 12.5}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (const f of feats) {
      const n = f.properties.n, x = sx(mercX(f.properties.lon)), y = sy(mercY(f.properties.lat));
      if (x < -40 || y < -20 || x > W + 40 || y > H + 20) continue;
      const lab = n === 1 ? "1er" : n + "e";
      ctx.globalAlpha = a * (arrSel.length && !arrSel.includes(n - 1) ? 0.4 : 1);
      ctx.lineWidth = 4; ctx.lineJoin = "round";
      ctx.strokeStyle = dark ? "rgba(15,17,16,.85)" : "rgba(252,252,251,.9)"; ctx.strokeText(lab, x, y);
      ctx.fillStyle = dark ? "#e8e7e1" : "#1f3c2c"; ctx.fillText(lab, x, y);
    }
    ctx.globalAlpha = 1;
  }

  // ---- remarkable-tree badges
  function starPath(cx, cy, ro, ri) {
    ctx.beginPath();
    for (let k = 0; k < 10; k++) {
      const a = -Math.PI / 2 + (k * Math.PI) / 5, r = k % 2 ? ri : ro;
      k ? ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r) : ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
    }
    ctx.closePath();
  }
  const badges = []; // screen-space hit list for picking
  function drawBadges() {
    badges.length = 0;
    const mask = view.mask, z = P.z, dark = S.theme === "dark";
    const R = z < 12.8 ? 4.6 : z < 15 ? 8.5 : 11.5, showStar = R > 6;
    for (const r of D.heritage) {
      if (!mask[r.row]) continue;
      const x = sx(D.mx[r.row]), y = sy(D.my[r.row]);
      if (x < -20 || y < -20 || x > W + 20 || y > H + 20) continue;
      badges.push({ x, y, row: r.row, R });
      const sel = r.row === S.selected;
      // soft shadow + white ring + gold disc + dark star
      ctx.save();
      ctx.shadowColor = "rgba(40,25,0,.35)"; ctx.shadowBlur = 5; ctx.shadowOffsetY = 1.5;
      ctx.fillStyle = dark ? "#16130a" : "#ffffff";
      ctx.beginPath(); ctx.arc(x, y, R + (showStar ? 2 : 1.5), 0, 6.2832); ctx.fill();
      ctx.restore();
      ctx.fillStyle = GOLD.fill; ctx.beginPath(); ctx.arc(x, y, R, 0, 6.2832); ctx.fill();
      if (showStar) { ctx.fillStyle = GOLD.ink; starPath(x, y + 0.4, R * 0.66, R * 0.28); ctx.fill(); }
      if (sel) { ctx.strokeStyle = GOLD.ink; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, R + 4, 0, 6.2832); ctx.stroke(); }
      if (z >= 16.4) {
        const label = r.name;
        ctx.font = "600 12px system-ui, -apple-system, 'Segoe UI', sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
        ctx.lineWidth = 4; ctx.lineJoin = "round";
        ctx.strokeStyle = dark ? "rgba(15,17,16,.9)" : "rgba(252,252,251,.95)"; ctx.strokeText(label, x + R + 7, y);
        ctx.fillStyle = dark ? "#f3d68a" : "#6b4600"; ctx.fillText(label, x + R + 7, y);
      }
    }
  }

  function draw() {
    if (!view.mask || !W) return;
    projection();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const t = smooth(FADE[0], FADE[1], P.z);
    if (t < 0.99) drawHex(1 - t);
    if (t > 0.01) drawDots(t);
    drawArrLabels();
    drawBadges();
    updateZoomState();
  }

  let lastZoomState = "";
  function updateZoomState() {
    const st = P.z < FADE[0] ? "aggregate" : P.z < FADE[1] + 0.3 ? "transition" : "trees";
    if (st !== lastZoomState) { lastZoomState = st; onZoomState?.(st); }
  }

  map.on("render", draw);
  map.on("resize", () => { fit(); draw(); });
  new ResizeObserver(() => { fit(); map.resize(); draw(); }).observe(el);
  fit();

  // ---------------------------------------------------------------- in-view count
  let viewTimer;
  function emitView() {
    clearTimeout(viewTimer);
    viewTimer = setTimeout(() => {
      if (!view.idx) return;
      const b = map.getBounds(), xa = mercX(b.getWest()), xb = mercX(b.getEast()), ya = mercY(b.getNorth()), yb = mercY(b.getSouth());
      let c = 0;
      for (let k = 0; k < view.idx.length; k++) { const i = view.idx[k], x = D.mx[i], y = D.my[i]; if (x >= xa && x <= xb && y >= ya && y <= yb) c++; }
      onViewChange?.({ inView: c, zoom: map.getZoom() });
    }, 90);
  }
  map.on("move", emitView);

  // ---------------------------------------------------------------- picking + tooltip
  function worldAt(pt) { return [P.cx + (pt.x - W / 2) / P.ws, P.cy + (pt.y - H / 2) / P.ws]; }

  function pickBadge(pt) {
    let best = null, bd = 1e9;
    for (const b of badges) { const d = Math.hypot(b.x - pt.x, b.y - pt.y); if (d < b.R + 7 && d < bd) { bd = d; best = b; } }
    return best;
  }
  function pickTree(pt) {
    if (P.z < FADE[0] + 0.5) return -1;
    const [wx, wy] = worldAt(pt), rad = 14 / P.ws;
    let best = -1, bd = 1e12;
    queryRect(D, wx - rad, wy - rad, wx + rad, wy + rad, (i) => {
      if (!view.mask[i]) return;
      const dx = (D.mx[i] - wx) * P.ws, dy = (D.my[i] - wy) * P.ws, d = dx * dx + dy * dy;
      const rr = Math.max(crownPx(i), 6);
      if (d < rr * rr && d < bd) { bd = d; best = i; }
    });
    return best;
  }
  function pickHex(pt) {
    if (P.z >= FADE[1]) return null;
    const L = clamp(Math.floor(P.z), 10, 14), b = getBins(L), [wx, wy] = worldAt(pt);
    const [q, r] = hexCell(wx, wy, b.s), c = b.key.get((q + KEY_OFF) * KEY_MUL + (r + KEY_OFF));
    return c === undefined ? null : { b, c, wx: b.s * SQRT3 * (q + r / 2), wy: b.s * 1.5 * r };
  }

  function showTip(pt, node) {
    tip.replaceChildren(node);
    tip.classList.add("on");
    const w = tip.offsetWidth, hh = tip.offsetHeight;
    let x = pt.x + 16, y = pt.y + 16;
    if (x + w > W - 8) x = pt.x - w - 16;
    if (y + hh > H - 8) y = pt.y - hh - 16;
    tip.style.transform = `translate(${Math.max(8, x)}px, ${Math.max(8, y)}px)`;
  }
  const hideTip = () => tip.classList.remove("on");

  function treeTip(i) {
    const hr = D.heritageByRow.get(i);
    return h("div", { class: "tip-body" },
      h("div", { class: "tip-title" }, hr ? h("span", { class: "tip-star", "aria-label": "Remarkable tree" }, "★") : null, treeName(i)),
      h("div", { class: "tip-sub" }, treeLatin(i)),
      h("div", { class: "tip-row" },
        D.height[i] ? h("span", {}, h("b", {}, D.height[i] + " m"), " tall") : null,
        D.circ[i] ? h("span", {}, h("b", {}, D.circ[i] + " cm"), " girth") : null));
  }
  function hexTip(hx) {
    const { b, c } = hx, pal = COLORS[S.theme][S.mode], rows = [];
    if (S.mode === "genus") {
      const arr = [];
      for (let k = 0; k < 9; k++) if (b.cat[c * 9 + k]) arr.push([k, b.cat[c * 9 + k]]);
      arr.sort((p, q) => q[1] - p[1]);
      const labels = legendLabels("genus", D);
      for (const [k, v] of arr.slice(0, 3)) rows.push(h("div", { class: "tip-line" }, h("i", { style: { background: pal[k] } }), labels[k], h("b", {}, Math.round((v / b.n[c]) * 100) + "%")));
    } else if (S.mode === "height") {
      if (b.nH[c]) rows.push(h("div", { class: "tip-line" }, "Mean height", h("b", {}, (b.sumH[c] / b.nH[c]).toFixed(1) + " m")));
    } else if (S.mode === "girth") {
      if (b.nC[c]) rows.push(h("div", { class: "tip-line" }, "Mean girth", h("b", {}, Math.round(b.sumC[c] / b.nC[c]) + " cm")));
    } else if (b.nS[c]) {
      rows.push(h("div", { class: "tip-line" }, "Mean stage", h("b", {}, D.stages[Math.min(3, Math.round(b.sumS[c] / b.nS[c]))])));
    }
    return h("div", { class: "tip-body" },
      h("div", { class: "tip-title" }, fmt(b.n[c]) + (b.n[c] === 1 ? " tree" : " trees")),
      b.rem[c] ? h("div", { class: "tip-sub gold" }, `★ ${b.rem[c]} remarkable`) : null,
      ...rows, h("div", { class: "tip-hint" }, "Click to zoom in"));
  }

  let hoverRaf = 0;
  map.on("mousemove", (e) => {
    cancelAnimationFrame(hoverRaf);
    hoverRaf = requestAnimationFrame(() => {
      if (!P) return;
      const pt = e.point, bd = pickBadge(pt);
      let cursor = "";
      if (bd) { showTip(pt, treeTip(bd.row)); cursor = "pointer"; }
      else {
        const i = pickTree(pt);
        if (i >= 0) { showTip(pt, treeTip(i)); cursor = "pointer"; }
        else { const hx = pickHex(pt); if (hx) { showTip(pt, hexTip(hx)); cursor = "zoom-in"; } else hideTip(); }
      }
      map.getCanvas().style.cursor = cursor;
    });
  });
  map.on("mouseout", () => { hideTip(); });
  map.on("click", (e) => {
    const pt = e.point, bd = pickBadge(pt);
    if (bd) return api.select(bd.row, { fly: false });
    const i = pickTree(pt);
    if (i >= 0) return api.select(i, { fly: false });
    const hx = pickHex(pt);
    if (hx) { hideTip(); return map.easeTo({ center: [unmercX(hx.wx), unmercY(hx.wy)], zoom: Math.min(P.z + 2.2, 16.2), duration: 650 }); }
    api.select(-1);
  });

  // ---------------------------------------------------------------- selection marker
  const ringEl = h("div", { class: "sel-ring" }, h("i"), h("i"));
  const marker = new maplibregl.Marker({ element: ringEl, anchor: "center" });
  let markerOn = false;

  const api = {
    map,
    select(row, { fly = true, zoom = 18.6 } = {}) {
      S.selected = row;
      if (row < 0) { if (markerOn) { marker.remove(); markerOn = false; } onSelect?.(-1); draw(); return; }
      marker.setLngLat([D.lon[row] / 1e6, D.lat[row] / 1e6]);
      if (!markerOn) { marker.addTo(map); markerOn = true; }
      if (fly) {
        const wide = el.clientWidth > 900;
        map.flyTo({ center: [D.lon[row] / 1e6, D.lat[row] / 1e6], zoom: Math.max(map.getZoom(), zoom), offset: wide ? [-190, 0] : [0, -el.clientHeight * 0.18], duration: 1400, essential: true });
      }
      onSelect?.(row);
      draw();
    },
    setMode(m) { S.mode = m; S.cls = classArray(m, D); draw(); },
    setTheme(t) {
      if (t === S.theme) return;
      S.theme = t;
      map.setStyle(STYLE[t]);
      draw();
    },
    invalidate() { S.binsCache.clear(); S.lastLevel = -1; draw(); emitView(); },
    setArrondissements(set) {
      arrSel = [...set].filter((a) => a < 20);
      updateArrSelection();
      draw();
    },
    fitArr(set) {
      const sel = [...set].filter((a) => a < 20);
      if (!sel.length) return map.fitBounds(PARIS_BOUNDS, { padding: 24, duration: 900 });
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      const visit = (c) => Array.isArray(c[0]) ? c.forEach(visit) : (x0 = Math.min(x0, c[0]), x1 = Math.max(x1, c[0]), y0 = Math.min(y0, c[1]), y1 = Math.max(y1, c[1]));
      for (const a of sel) visit(D.arrGeo.features[a].geometry.coordinates);
      map.fitBounds([[x0, y0], [x1, y1]], { padding: { top: 60, bottom: 60, left: 60, right: el.clientWidth > 900 ? 440 : 60 }, duration: 900, maxZoom: 15 });
    },
    home() { map.fitBounds(PARIS_BOUNDS, { padding: 24, duration: 900 }); },
    flyTo(row, zoom) { api.select(row, { fly: true, zoom }); },
    classCounts() {
      const c = new Uint32Array(9);
      for (let k = 0; k < view.idx.length; k++) c[S.cls[view.idx[k]]]++;
      return c;
    },
    get mode() { return S.mode; },
    resize() { map.resize(); fit(); draw(); },
    redraw: draw,
  };
  map.on("load", () => { fit(); draw(); emitView(); });
  return api;
}
