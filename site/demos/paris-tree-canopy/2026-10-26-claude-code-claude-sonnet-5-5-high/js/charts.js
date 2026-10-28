// Chart primitives: tooltip service, bar list, histogram, stacked bar, table view.
import { h, svg, fmt, compact, clear } from "./format.js";

// ---------------------------------------------------------------- tooltip
const tipEl = () => document.getElementById("tooltip");
export const tip = {
  show(evt, node) {
    const el = tipEl();
    el.replaceChildren(node);
    el.classList.add("on");
    this.move(evt);
  },
  move(evt) {
    const el = tipEl(), w = el.offsetWidth, hh = el.offsetHeight;
    let x = evt.clientX + 14, y = evt.clientY + 16;
    if (x + w > innerWidth - 8) x = evt.clientX - w - 14;
    if (y + hh > innerHeight - 8) y = evt.clientY - hh - 14;
    el.style.left = Math.max(8, x) + "px";
    el.style.top = Math.max(8, y) + "px";
  },
  hide() { tipEl().classList.remove("on"); },
};

/** Bind hover + keyboard focus tooltips. `build` returns a node. */
export function bindTip(el, build) {
  el.addEventListener("pointerenter", (e) => tip.show(e, build()));
  el.addEventListener("pointermove", (e) => tip.move(e));
  el.addEventListener("pointerleave", () => tip.hide());
  el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); tip.show({ clientX: r.left + r.width / 2, clientY: r.top }, build()); });
  el.addEventListener("blur", () => tip.hide());
  return el;
}

export const tipNode = (title, rows = []) =>
  h("div", {}, h("div", { class: "t-title" }, title),
    rows.map((r) => h("div", { class: "t-row" }, r.color ? h("i", { style: { background: r.color } }) : null, r.label, r.value != null ? h("b", {}, r.value) : null)));

// ---------------------------------------------------------------- bar list (horizontal, nominal)
/**
 * items: [{ label, sub, value, share, color, tip, onClick, active }]
 */
export function barList(items, { max, valueFmt = fmt, showShare = true } = {}) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value));
  const wrap = h("div", { class: "bars" });
  for (const it of items) {
    const row = h(it.onClick ? "button" : "div", { class: "brow" + (it.active ? " hl" : ""), type: it.onClick ? "button" : null, onClick: it.onClick },
      h("span", { class: "bl" }, h("b", {}, it.label), it.sub ? h("i", {}, it.sub) : null),
      h("span", { class: "bt" }, h("s", { style: { width: Math.max(0.4, (it.value / top) * 100) + "%", background: it.color } })),
      h("span", { class: "bv" }, valueFmt(it.value), showShare && it.share != null ? h("small", {}, (it.share * 100).toFixed(1) + "%") : null));
    bindTip(row, () => it.tip ?? tipNode(it.label, [{ label: "Trees", value: fmt(it.value), color: it.color }]));
    wrap.append(row);
  }
  return wrap;
}

// ---------------------------------------------------------------- stacked bar (2px gaps via CSS)
export function stackedBar(segs, { thin = false } = {}) {
  const total = segs.reduce((a, s) => a + s.value, 0) || 1;
  const bar = h("div", { class: "stack" + (thin ? " thin" : ""), role: "img", "aria-label": segs.map((s) => `${s.label} ${((s.value / total) * 100).toFixed(1)}%`).join(", ") });
  for (const s of segs) {
    if (!s.value) continue;
    const seg = h("s", { style: { flex: `${s.value} 1 0`, background: s.color }, tabindex: "0" });
    bindTip(seg, () => tipNode(s.label, [{ label: "Trees", value: fmt(s.value), color: s.color }, { label: "Share", value: ((s.value / total) * 100).toFixed(1) + "%" }]));
    bar.append(seg);
  }
  return bar;
}

export function legendRow(segs) {
  const total = segs.reduce((a, s) => a + s.value, 0) || 1;
  return h("div", { class: "legend" }, segs.filter((s) => s.value).map((s) =>
    h("span", {}, h("i", { class: "sw", style: { background: s.color } }), s.label, h("b", {}, ((s.value / total) * 100).toFixed(0) + "%"))));
}

// ---------------------------------------------------------------- histogram (svg)
/**
 * counts: array indexed by integer value. Bins of `bin` units from `from` to `to`; the last bin gathers the tail (≥ to).
 */
export function histogram(counts, { from, to, bin, unit, color = "var(--c1)", median, mean, label = "trees" }) {
  const W = 560, H = 210, m = { l: 40, r: 10, t: 22, b: 28 };
  const nb = Math.ceil((to - from) / bin) + 1;
  const agg = new Array(nb).fill(0);
  let total = 0;
  for (let v = 0; v < counts.length; v++) {
    if (!counts[v] || v < Math.max(from, 1)) continue; // index 0 = not recorded
    agg[Math.min(nb - 1, Math.floor((v - from) / bin))] += counts[v];
    total += counts[v];
  }
  const max = Math.max(1, ...agg), iw = W - m.l - m.r, ih = H - m.t - m.b, bw = iw / nb;
  const nice = (x) => { const p = 10 ** Math.floor(Math.log10(x)); const f = x / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; };
  const top = nice(max), y = (v) => m.t + ih - (v / top) * ih;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img", "aria-label": `Distribution of ${label}` });
  for (const t of [0, 0.5, 1]) {
    const v = top * t;
    root.append(svg("line", { class: t ? "grid-line" : "baseline", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }), svg("text", { x: m.l - 7, y: y(v) + 3.5, "text-anchor": "end" }, compact(v)));
  }
  const xOf = (v) => m.l + ((v - from) / bin) * bw;
  agg.forEach((c, b) => {
    const x = m.l + b * bw + 1, w = Math.max(1, bw - 2), yy = y(c), hh = m.t + ih - yy;
    if (c) {
      const r = Math.min(3.5, w / 2, hh);
      root.append(svg("path", { class: "bar", d: `M${x},${m.t + ih}V${yy + r}Q${x},${yy} ${x + r},${yy}H${x + w - r}Q${x + w},${yy} ${x + w},${yy + r}V${m.t + ih}Z`, style: { fill: color } }));
    }
    const lo = from + b * bin, hi = lo + bin - 1;
    const hit = svg("rect", { x: m.l + b * bw, y: m.t, width: bw, height: ih, fill: "transparent" });
    bindTip(hit, () => tipNode(b === nb - 1 ? `${lo}${unit} and more` : bin === 1 ? `${lo}${unit}` : `${lo}–${hi}${unit}`, [{ label: "Trees", value: fmt(c), color }, { label: "Share", value: total ? ((c / total) * 100).toFixed(1) + "%" : "–" }]));
    root.append(hit);
  });
  const step = nb > 24 ? 5 : nb > 12 ? 2 : 1;
  for (let b = 0; b < nb; b += step) {
    const v = from + b * bin;
    root.append(svg("text", { x: m.l + b * bw + bw / 2, y: H - 9, "text-anchor": "middle" }, (b === nb - 1 ? v + "+" : v) + (b === 0 ? unit : "")));
  }
  const mark = (v, text, dy = 0) => {
    if (!isFinite(v)) return;
    const x = Math.min(W - m.r - 2, Math.max(m.l, xOf(v) + bw / (2 * bin)));
    root.append(svg("line", { class: "ann-line", x1: x, x2: x, y1: m.t - 6, y2: m.t + ih }));
    const right = x < W - 150;
    root.append(svg("text", { class: "ann", x: x + (right ? 5 : -5), y: m.t - 9 + dy, "text-anchor": right ? "start" : "end" }, text));
  };
  mark(median, `median ${median}${unit}`);
  return root;
}

// ---------------------------------------------------------------- table view
export function tableView(cols, rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "dt" },
    h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.num ? "num" : "" }, c.label)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, cols.map((c, i) => h("td", { class: c.num ? "num" : "" }, r[i])))))));
}

const toggleMode = new Map();
/** "Chart | Table" segmented control swapping two renderers. The choice survives re-renders (keyed). */
export function viewToggle(key, renderChart, renderTable) {
  const body = h("div"), seg = h("div", { class: "seg", role: "group", "aria-label": "View as" });
  const mk = (id, text) => h("button", { type: "button", "aria-pressed": String((toggleMode.get(key) || "chart") === id), onClick: () => { toggleMode.set(key, id); paint(); } }, text);
  function paint() {
    const mode = toggleMode.get(key) || "chart";
    clear(seg).append(mk("chart", "Chart"), mk("table", "Table"));
    clear(body).append(mode === "chart" ? renderChart() : renderTable());
  }
  paint();
  return { seg, body };
}
