// District comparison: choropleth + sortable table + street-vs-park contrast.
import { DATA, GENUS_SLOTS, commonEn } from "./data.js";
import { filters, computeMask, setFilters, activeCount } from "./state.js";
import { districtStats, diversity } from "./stats.js";
import { h, svg, fmt, fmt1, pct, clear } from "./format.js";
import { stackedBar, legendRow, bindTip, tipNode } from "./charts.js";
import { COLORS, isDark } from "./theme.js";
import { GROUP_COLOR, genusColor } from "./analytics.js";

const METRICS = {
  density: { label: "Density", unit: "trees / ha", get: (r) => r.density, fmt: (v) => v.toFixed(1), help: "Trees per hectare of arrondissement area" },
  trees: { label: "Trees", unit: "trees", get: (r) => r.n, fmt: (v) => fmt(v), help: "Number of municipal trees" },
  richness: { label: "Species", unit: "species", get: (r) => r.div.richness, fmt: (v) => fmt(v), help: "Number of distinct species" },
  effective: { label: "Diversity", unit: "effective spp.", get: (r) => r.div.effective, fmt: (v) => v.toFixed(1), help: "Effective number of species (exp of Shannon index): higher = more evenly mixed" },
  height: { label: "Height", unit: "m median", get: (r) => (r.height.n ? r.height.median : null), fmt: (v) => v + " m", help: "Median recorded height" },
};
const ui = { metric: "density", sel: -1, sort: "density", dir: -1 };
const label = (a) => (a < 20 ? (a === 0 ? "1er" : a + 1 + "e") : DATA.arrNames[a]);

export function renderDistricts(root, { onViewOnMap }) {
  const D = DATA;
  const { mask } = computeMask(filters, ["arr"]);
  const rows = districtStats(mask);
  const paris = rows.slice(0, 20);
  const page = h("div", { class: "page" });
  const others = activeCount() - (filters.arr.size ? 1 : 0);
  page.append(h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "eyebrow" }, "District comparison"), h("h2", {}, "Twenty arrondissements, twenty different urban forests"),
      h("p", {}, "How dense is the tree cover, how varied are the species, and how do street alignments compare with parks and squares? Pick a metric, then a district.")),
    h("span", { class: "scope-note" }, others > 0 ? ["Other filters apply · ", h("b", {}, "arrondissement filter is ignored here")] : "All 20 arrondissements shown")));

  // ---------------- metric switch + choropleth
  const metricSeg = h("div", { class: "seg", role: "group", "aria-label": "Metric" });
  const mapHost = h("div"), legendHost = h("div");
  const mapCard = h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", {}, "Tree coverage across Paris"), h("p", { class: "sub", id: "metric-help" }, METRICS[ui.metric].help)), metricSeg), mapHost, legendHost,
    h("p", { class: "legend-note" }, "The 12e and 16e outlines include the Bois de Vincennes and Boulogne; densities count those districts without the Bois."));

  const tableHost = h("div", { class: "table-wrap", style: { maxHeight: "none" } });
  const tableCard = h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", {}, "Street trees vs parks & squares"), h("p", { class: "sub" }, "Click a row to focus a district · click a column to sort")),
    h("div", { class: "legend", style: { margin: 0 } }, h("span", {}, h("i", { class: "sw", style: { background: GROUP_COLOR[0] } }), "Street trees"), h("span", {}, h("i", { class: "sw", style: { background: GROUP_COLOR[1] } }), "Parks & squares"), h("span", {}, h("i", { class: "sw", style: { background: GROUP_COLOR[4] } }), "Other"))), tableHost);

  const detailHost = h("div", { class: "dsel" });
  page.append(h("div", { class: "dist-layout" }, h("div", { class: "stackcol" }, mapCard, detailHost), tableCard));

  function paintMetric() {
    clear(metricSeg).append(...Object.entries(METRICS).map(([k, m]) => h("button", { type: "button", "aria-pressed": String(ui.metric === k), onClick: () => { ui.metric = k; paintMetric(); paintMap(); document.getElementById("metric-help").textContent = m.help; } }, m.label)));
  }

  // ---------------- choropleth (equirectangular around Paris)
  function paintMap() {
    const M = METRICS[ui.metric], feats = D.arrGeo.features;
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    const visit = (c) => Array.isArray(c[0]) ? c.forEach(visit) : (x0 = Math.min(x0, c[0]), x1 = Math.max(x1, c[0]), y0 = Math.min(y0, c[1]), y1 = Math.max(y1, c[1]));
    feats.forEach((f) => visit(f.geometry.coordinates));
    const k = Math.cos((48.86 * Math.PI) / 180), S = 5200, w = (x1 - x0) * k * S, hh = (y1 - y0) * S;
    const px = (lon) => ((lon - x0) * k * S + 8).toFixed(1), py = (lat) => ((y1 - lat) * S + 8).toFixed(1);
    const vals = paris.map((r) => M.get(r)).filter((v) => v != null && isFinite(v));
    const vmin = Math.min(...vals), vmax = Math.max(...vals), pal = COLORS[isDark() ? "dark" : "light"].height;
    const cls = (v) => (v == null || vmax === vmin ? 0 : Math.min(5, Math.floor(((v - vmin) / (vmax - vmin)) * 6)));
    const root_ = svg("svg", { class: "choro", viewBox: `0 0 ${w + 16} ${hh + 16}`, role: "img", "aria-label": `Choropleth of ${M.help.toLowerCase()} by arrondissement` });
    const dark = isDark();
    feats.forEach((f, a) => {
      const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
      const d = polys.map((poly) => poly.map((ring) => "M" + ring.map((p) => px(p[0]) + "," + py(p[1])).join("L") + "Z").join("")).join("");
      const v = M.get(rows[a]), c = cls(v);
      const p = svg("path", { d, fill: pal[c], class: (ui.sel === a ? "sel " : "") + (ui.sel >= 0 && ui.sel !== a ? "dim" : ""), tabindex: 0, role: "button", "aria-label": `${label(a)} arrondissement: ${M.fmt(v)} ${M.unit}` });
      bindTip(p, () => tipNode(`${label(a)} · ${f.properties.name}`, [{ label: M.label, value: M.fmt(v) + " " + (M.unit.startsWith("trees /") ? "/ ha" : "") }, { label: "Trees", value: fmt(rows[a].n) }, { label: "Species", value: fmt(rows[a].div.richness) }]));
      p.addEventListener("click", () => { ui.sel = ui.sel === a ? -1 : a; paintMap(); paintTable(); paintDetail(); });
      p.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); p.dispatchEvent(new Event("click")); } });
      root_.append(p);
      const lightFill = dark ? c >= 3 : c < 3;
      root_.append(svg("text", { x: px(f.properties.lon), y: (+py(f.properties.lat) + 4).toFixed(1), fill: lightFill ? "#0b0b0b" : "#ffffff" }, a + 1));
    });
    clear(mapHost).append(root_);
    clear(legendHost).append(h("div", { class: "ramp-legend" }, h("span", {}, vals.length ? M.fmt(vmin) : "–"),
      h("i", { style: { background: `linear-gradient(90deg, ${pal.slice(0, 6).join(", ")})` } }), h("span", {}, vals.length ? M.fmt(vmax) : "–"), h("span", {}, M.unit)));
  }

  // ---------------- table
  const COLS = [
    { id: "arr", label: "District", get: (r) => r.arr },
    { id: "trees", label: "Trees", get: (r) => r.n },
    { id: "density", label: "Per ha", get: (r) => r.density ?? -1, num: true },
    { id: "richness", label: "Species: street vs park", get: (r) => r.div.richness },
    { id: "height", label: "Median h.", get: (r) => (r.height.n ? r.height.median : -1), num: true },
  ];
  function paintTable() {
    const maxN = Math.max(...rows.map((r) => r.n), 1), maxR = Math.max(...rows.map((r) => Math.max(r.divStreet.richness, r.divPark.richness)), 1);
    const col = COLS.find((c) => c.id === ui.sort);
    const sorted = [...paris].sort((p, q) => (col.get(p) - col.get(q)) * ui.dir || p.arr - q.arr);
    const body = [...sorted, rows[20], rows[21], rows[22]].map((r) => {
      const segs = [{ label: "Street trees", value: r.group[0], color: GROUP_COLOR[0] }, { label: "Parks & squares", value: r.group[1], color: GROUP_COLOR[1] }, { label: "Cemeteries, schools & other", value: r.group[2] + r.group[3] + r.group[4], color: GROUP_COLOR[4] }];
      const bar = h("div", { style: { width: Math.max(2, (r.n / maxN) * 100) + "%" } }, stackedBar(segs, { thin: true }));
      const rs = r.divStreet.richness, rp = r.divPark.richness, pos = (v) => (v / maxR) * 100 + "%";
      const dumb = h("div", { class: "dumbbell", role: "img", "aria-label": `${rs} street species, ${rp} park species` }, h("div", { class: "rail" }),
        rs && rp ? h("div", { class: "link", style: { left: pos(Math.min(rs, rp)), width: `calc(${pos(Math.abs(rs - rp))})` } }) : null,
        rs ? h("div", { class: "pt", style: { left: pos(rs), background: GROUP_COLOR[0] } }) : null, rp ? h("div", { class: "pt", style: { left: pos(rp), background: GROUP_COLOR[1] } }) : null);
      bindTip(dumb, () => tipNode(`${label(r.arr)} species variety`, [{ label: "Street trees", value: rs + " species", color: GROUP_COLOR[0] }, { label: "Parks & squares", value: rp + " species", color: GROUP_COLOR[1] }, { label: "All trees", value: fmt(r.div.richness) + " species" }]));
      const tr = h("tr", { class: ui.sel === r.arr ? "sel" : "", tabindex: 0, onClick: () => { if (r.arr < 20) { ui.sel = ui.sel === r.arr ? -1 : r.arr; paintMap(); paintTable(); paintDetail(); } } },
        h("td", {}, h("div", { class: "an" }, h("b", {}, r.arr < 20 ? label(r.arr) : label(r.arr)), h("small", {}, r.arr < 20 ? r.official : ""))),
        h("td", { class: "mini" }, h("div", { style: { fontSize: "12px", marginBottom: "3px" } }, fmt(r.n)), bar),
        h("td", { class: "num" }, r.density != null ? r.density.toFixed(1) : "—"),
        h("td", { class: "mini" }, dumb),
        h("td", { class: "num" }, r.height.n ? r.height.median + " m" : "—"));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") tr.click(); });
      return tr;
    });
    const head = h("tr", {}, COLS.map((c) => h("th", { class: (c.num ? "num " : "") + (ui.sort === c.id ? "sorted" : ""), "aria-sort": ui.sort === c.id ? (ui.dir < 0 ? "descending" : "ascending") : "none" },
      h("button", { type: "button", onClick: () => { if (ui.sort === c.id) ui.dir *= -1; else { ui.sort = c.id; ui.dir = c.id === "arr" ? 1 : -1; } paintTable(); } }, c.label, h("span", { class: "ar" }, ui.dir < 0 ? "▼" : "▲")))));
    clear(tableHost).append(h("table", { class: "dtable" }, h("thead", {}, head), h("tbody", {}, body)));
  }

  // ---------------- selected district / citywide street-vs-park panel
  function aggregate() {
    const sp = new Uint32Array(D.spp.length), sk = new Uint32Array(D.spp.length), group = new Uint32Array(5), genus = new Uint32Array(D.genera.length);
    let n = 0;
    for (const r of paris) { n += r.n; for (let i = 0; i < sp.length; i++) { sp[i] += r.spStreet[i]; sk[i] += r.spPark[i]; } r.group.forEach((c, i) => (group[i] += c)); r.genus.forEach((c, i) => (genus[i] += c)); }
    return { n, group, genus, divStreet: diversity(sp), divPark: diversity(sk) };
  }
  function paintDetail() {
    const sel = ui.sel >= 0 ? rows[ui.sel] : null, src = sel || aggregate(), n = Math.max(1, src.n);
    const title = sel ? `${label(sel.arr)} arrondissement · ${sel.official}` : "All twenty arrondissements";
    const rank = sel ? [...paris].sort((p, q) => q.density - p.density).findIndex((r) => r.arr === sel.arr) + 1 : null;
    const pair = (name, color, gi, dv) => h("div", { class: "pair" }, h("h4", {}, h("i", { style: { background: color } }), name),
      h("div", { class: "p-main" }, fmt(src.group[gi]), h("small", {}, `trees · ${pct(src.group[gi] / n)} of the total`)),
      h("div", { class: "p-sub" }, dv.richness ? `${fmt(dv.richness)} species · effective diversity ${dv.effective.toFixed(1)}` : "no trees"),
      h("div", { class: "p-sub muted" }, dv.richness ? `Shannon evenness ${dv.evenness.toFixed(2)}` : ""));
    const gRank = [...src.genus].map((c, g) => [g, c]).filter((x) => x[1]).sort((a, b) => b[1] - a[1]);
    const slotSegs = []; let shown = 0;
    for (const [g, c] of gRank.slice(0, 6)) { slotSegs.push({ label: D.genera[g], value: c, color: genusColor(g) }); shown += c; }
    const covered = gRank.slice(0, 6).reduce((a, x) => a + x[1], 0);
    if (src.n - covered > 0) slotSegs.push({ label: "Other genera", value: src.n - covered, color: "var(--c9)" });
    const card = h("section", { class: "card" },
      h("div", { class: "dsel-head" }, h("div", {}, h("div", { class: "eyebrow" }, sel ? "Selected district" : "Citywide"), h("h3", {}, title)),
        h("div", { style: { display: "flex", gap: "8px" } },
          sel ? h("button", { class: "btn primary sm", type: "button", onClick: () => onViewOnMap(sel.arr) }, "View on map") : null,
          sel ? h("button", { class: "btn sm", type: "button", onClick: () => { ui.sel = -1; paintMap(); paintTable(); paintDetail(); } }, "Clear") : null)),
      sel ? h("div", { class: "dsel-grid" },
        h("div", { class: "metric" }, h("span", {}, "Trees"), h("b", {}, fmt(sel.n)), h("em", {}, `${fmt(sel.remarkable)} remarkable`)),
        h("div", { class: "metric" }, h("span", {}, "Density"), h("b", {}, sel.density.toFixed(1), h("small", {}, "/ ha")), h("em", {}, `#${rank} of 20 · ${fmt(sel.ha)} ha${sel.arr === 11 || sel.arr === 15 ? " excl. Bois" : ""}`)),
        h("div", { class: "metric" }, h("span", {}, "Median height"), h("b", {}, sel.height.n ? [sel.height.median, h("small", {}, "m")] : "—"), h("em", {}, sel.height.n ? `mean ${fmt1(sel.height.mean)} m` : "")),
        h("div", { class: "metric" }, h("span", {}, "Species"), h("b", {}, fmt(sel.div.richness)), h("em", {}, `effective ${sel.div.effective.toFixed(1)}`))) : null,
      h("div", { class: "pairs" }, pair("Street trees", GROUP_COLOR[0], 0, src.divStreet), pair("Parks & public squares", GROUP_COLOR[1], 1, src.divPark)),
      h("div", { style: { marginTop: "16px" } }, h("h4", { style: { fontSize: "11px", letterSpacing: ".09em", textTransform: "uppercase", color: "var(--muted)", marginBottom: "8px" } }, "Leading genera"), stackedBar(slotSegs), legendRow(slotSegs)));
    clear(detailHost).append(card);
  }

  paintMetric(); paintMap(); paintTable(); paintDetail();
  root.replaceChildren(page);
}
