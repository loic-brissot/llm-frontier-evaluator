// Remarkable-trees showcase.
import { DATA, speciesLatin } from "./data.js";
import { view } from "./state.js";
import { h, svg, fmt, clear, debounce, safeUrl } from "./format.js";
import { icon } from "./icons.js";
import { ageOf } from "./detail.js";
import { tip, tipNode, bindTip } from "./charts.js";

const YEAR = new Date().getFullYear();
const ui = { q: "", cat: "All", sort: "name", shown: 24 };
const CATS = ["All", "Landscape", "Botanical", "Symbolic", "Historical"];
const SORTS = { name: "Name A–Z", oldest: "Oldest first", tallest: "Tallest", girth: "Largest girth", arr: "Arrondissement" };

export function renderHeritage(root, { onLocate }) {
  const D = DATA;
  const list = D.heritage.filter((r) => view.mask[r.row]).map((r) => ({ r, age: ageOf(r) }));
  const known = list.filter((x) => x.r.year);
  const oldest = known.reduce((a, x) => (!a || x.r.year < a.r.year ? x : a), null);
  const tallest = list.reduce((a, x) => (!a || x.r.height > a.r.height ? x : a), null);
  const widest = list.reduce((a, x) => (!a || x.r.girth > a.r.girth ? x : a), null);
  const speciesN = new Set(list.map((x) => x.r.latin)).size;

  const page = h("div", { class: "page" });
  page.append(h("div", { class: "hero" },
    h("div", { class: "hero-main" }, h("div", { class: "eyebrow" }, "Arbres remarquables"),
      h("h2", {}, "The heritage trees of Paris"),
      h("p", {}, "Giants, rarities and living witnesses of the city's history, recognised by the City of Paris for their scale, botany or symbolism. Browse them here, then fly straight to any tree on the map.")),
    h("div", { class: "hero-stats" },
      h("div", { class: "hstat" }, h("span", {}, "Remarkable trees"), h("b", {}, fmt(list.length)), h("em", {}, `${speciesN} species${view.active ? " · in current selection" : ""}`)),
      h("div", { class: "hstat" }, h("span", {}, "Oldest known planting"), h("b", {}, oldest ? oldest.r.year : "—"), h("em", {}, oldest ? `${oldest.r.name} · ${YEAR - oldest.r.year} years` : "")),
      h("div", { class: "hstat" }, h("span", {}, "Tallest"), h("b", {}, tallest ? [tallest.r.height, h("small", {}, "m")] : "—"), h("em", {}, tallest ? tallest.r.name : "")),
      h("div", { class: "hstat" }, h("span", {}, "Largest girth"), h("b", {}, widest ? [widest.r.girth, h("small", {}, "cm")] : "—"), h("em", {}, widest ? widest.r.name : "")))));

  if (!list.length) {
    page.append(h("div", { class: "empty" }, h("h3", {}, "No remarkable tree in this selection"), h("p", {}, "Relax the filters above — the heritage list follows them.")));
    root.replaceChildren(page); return;
  }

  // ---- timeline of known planting years
  const tl = h("section", { class: "card timeline" }, h("div", { class: "card-head" }, h("div", {}, h("h3", {}, "Planted through the centuries"), h("p", { class: "sub" }, `${known.length} of ${list.length} trees have a documented planting year · the other ${list.length - known.length} are dated by girth in their cards`))));
  tl.append(timeline(known));
  page.append(tl);

  // ---- toolbar
  const grid = h("div", { class: "hgrid" }), more = h("div", { style: { textAlign: "center", margin: "22px 0" } });
  const search = h("input", { type: "search", placeholder: "Search name, site or street…", "aria-label": "Search remarkable trees", value: ui.q });
  const sortSel = h("select", { class: "select", "aria-label": "Sort by", onChange: (e) => { ui.sort = e.target.value; ui.shown = 24; paint(); } },
    Object.entries(SORTS).map(([k, v]) => h("option", { value: k, selected: ui.sort === k }, v)));
  const pills = h("div", { class: "pill-seg", role: "group", "aria-label": "Criteria" });
  const paintPills = () => clear(pills).append(...CATS.map((c) => h("button", { class: "pill", type: "button", "aria-pressed": String(ui.cat === c), onClick: () => { ui.cat = c; ui.shown = 24; paintPills(); paint(); } },
    c === "All" ? "All criteria" : c)));
  search.addEventListener("input", debounce(() => { ui.q = search.value; ui.shown = 24; paint(); }, 120));
  page.append(h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), pills, h("div", { class: "grow-fill" }), sortSel));
  paintPills();
  page.append(grid, more);

  const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  function paint() {
    const q = norm(ui.q.trim());
    let items = list.filter((x) => (ui.cat === "All" || x.r.category === ui.cat) && (!q || norm(`${x.r.name} ${x.r.latin} ${x.r.site} ${x.r.address}`).includes(q)));
    const by = { name: (a, b) => a.r.name.localeCompare(b.r.name, "fr"), oldest: (a, b) => (b.age?.years ?? -1) - (a.age?.years ?? -1), tallest: (a, b) => b.r.height - a.r.height, girth: (a, b) => b.r.girth - a.r.girth, arr: (a, b) => a.r.arr - b.r.arr || a.r.name.localeCompare(b.r.name, "fr") };
    items = items.slice().sort(by[ui.sort]);
    clear(grid);
    for (const x of items.slice(0, ui.shown)) grid.append(heritageCard(x, onLocate));
    clear(more);
    if (!items.length) more.append(h("div", { class: "empty" }, h("h3", {}, "No tree matches"), h("p", {}, "Try another search or criterion.")));
    else if (items.length > ui.shown) more.append(h("button", { class: "btn", type: "button", onClick: () => { ui.shown += 24; paint(); } }, `Show ${Math.min(24, items.length - ui.shown)} more · ${items.length - ui.shown} remaining`));
    else more.append(h("span", { class: "muted" }, `${items.length} ${items.length === 1 ? "tree" : "trees"}`));
  }
  paint();
  root.replaceChildren(page);
  grid._items = list;
}

function heritageCard({ r, age }, onLocate) {
  const D = DATA;
  const long = r.description || "";
  const desc = h("p", { class: "h-desc clamp" }, long);
  const readMore = long.length > 180 ? h("button", { class: "linkbtn", type: "button", style: { alignSelf: "flex-start", padding: 0 }, onClick: () => { const c = desc.classList.toggle("clamp"); readMore.textContent = c ? "Read more" : "Show less"; } }, "Read more") : null;
  const img = safeUrl(r.photo) ? h("img", { src: r.photo, alt: `${r.name} — ${r.site}`, loading: "lazy", decoding: "async", referrerpolicy: "no-referrer", onLoad: (e) => e.target.classList.add("ok"), onError: (e) => e.target.remove() }) : null;
  const arrLabel = r.arr < 20 ? `${r.arr === 0 ? "1er" : r.arr + 1 + "e"} arrondissement` : D.arrNames[r.arr];
  const ageText = !age ? "Age unknown" : age.exact ? `Planted ${age.year} · ${age.years} yrs` : `≈ ${age.years} yrs · estimated`;
  const el = h("article", { class: "hcard", id: "hc-" + r.id },
    h("div", { class: "h-photo" }, h("svg:svg", { class: "ph", viewBox: "0 0 64 64", "aria-hidden": "true" }, svg("circle", { cx: 32, cy: 26, r: 18 }), svg("rect", { x: 29.5, y: 38, width: 5, height: 20, rx: 2 })), img,
      h("span", { class: "chip gold h-cat" }, r.category), h("span", { class: "h-age" + (age?.exact ? "" : " est"), title: age?.exact ? "Documented planting year" : "Rough estimate from trunk girth" }, ageText)),
    h("div", { class: "h-body" },
      h("div", {}, h("h3", {}, r.name), h("div", { class: "h-latin" }, r.latin + (r.cultivar ? ` ‘${r.cultivar}’` : ""))),
      h("div", { class: "h-loc" }, icon("pin"), h("span", {}, [r.site || r.address, arrLabel].filter(Boolean).join(" · "))),
      h("div", { class: "h-stats" }, r.height ? h("span", {}, h("b", {}, r.height + " m"), " tall") : null, r.girth ? h("span", {}, h("b", {}, r.girth + " cm"), " girth") : null),
      h("div", { class: "chips" }, r.tags.map((t) => h("span", { class: "chip" }, t))),
      r.citation ? h("p", { class: "h-cite" }, r.citation) : null,
      long ? desc : null, readMore,
      h("div", { class: "h-actions" },
        h("button", { class: "btn primary sm", type: "button", onClick: () => onLocate(r.row) }, icon("pin"), "Locate on map"),
        safeUrl(r.pdf) ? h("a", { class: "btn sm", href: r.pdf, target: "_blank", rel: "noopener", title: "Official fact sheet (PDF)" }, icon("ext"), "PDF") : null)));
  return el;
}

function timeline(known) {
  const W = 1200, H = 170, m = { l: 20, r: 20, t: 16, b: 30 };
  const y0 = 1600, y1 = YEAR + 5, x = (y) => m.l + ((y - y0) / (y1 - y0)) * (W - m.l - m.r);
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img", "aria-label": "Planting years of remarkable trees" });
  root.append(svg("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }));
  for (let y = 1600; y <= 2000; y += 50) {
    root.append(svg("line", { class: "grid-line", x1: x(y), x2: x(y), y1: m.t, y2: H - m.b }), svg("text", { x: x(y), y: H - 10, "text-anchor": "middle" }, y));
  }
  root.append(svg("text", { x: x(YEAR), y: H - 10, "text-anchor": "end" }, "today"));
  // stack dots within 6-year columns
  const cols = new Map();
  const perCol = new Map();
  for (const t of known) perCol.set(Math.floor(t.r.year / 6), (perCol.get(Math.floor(t.r.year / 6)) || 0) + 1);
  const gap = Math.min(11, (H - m.t - m.b - 14) / Math.max(1, ...perCol.values()));
  for (const t of known.slice().sort((a, b) => a.r.year - b.r.year)) {
    const k = Math.floor(t.r.year / 6), n = cols.get(k) || 0;
    cols.set(k, n + 1);
    const cx = x(t.r.year), cy = H - m.b - 8 - n * gap;
    const dot = svg("circle", { cx, cy, r: 5, fill: "var(--gold)", stroke: "var(--gold-ink)", "stroke-width": 1.2, tabindex: 0, style: { cursor: "pointer" } });
    bindTip(dot, () => tipNode(t.r.name, [{ label: `${t.r.site || t.r.address}`, value: null }, { label: "Planted", value: String(t.r.year) }]));
    dot.addEventListener("click", () => {
      const el = document.getElementById("hc-" + t.r.id);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800);
    });
    root.append(dot);
  }
  return root;
}
