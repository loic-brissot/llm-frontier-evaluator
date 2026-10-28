// The single filter row above every view: arrondissement, genus/species, setting, height, girth, stage, remarkable.
import { DATA, GENUS_SLOTS, commonEn } from "./data.js";
import { filters, view, setFilters, toggleIn, activeCount, resetFilters, onFilterChange } from "./state.js";
import { h, clear, fmt, debounce } from "./format.js";
import { icon } from "./icons.js";

const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const popRoot = () => document.getElementById("popovers");
let openPop = null;

export function closePopover() {
  if (!openPop) return;
  openPop.el.remove();
  openPop.anchor.setAttribute("aria-expanded", "false");
  document.removeEventListener("pointerdown", openPop.onDoc, true);
  document.removeEventListener("keydown", openPop.onKey, true);
  openPop = null;
}

function openPopover(anchor, content, { width = 340 } = {}) {
  closePopover();
  const el = h("div", { class: "pop", role: "dialog", style: { width: width + "px" } }, content.node);
  popRoot().append(el);
  const r = anchor.getBoundingClientRect();
  el.style.left = Math.max(8, Math.min(r.left, innerWidth - width - 8)) + "px";
  el.style.top = r.bottom + 8 + "px";
  anchor.setAttribute("aria-expanded", "true");
  const onDoc = (e) => { if (!el.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); closePopover(); anchor.focus(); } };
  document.addEventListener("pointerdown", onDoc, true);
  document.addEventListener("keydown", onKey, true);
  openPop = { el, anchor, onDoc, onKey, refresh: content.refresh };
  content.focus?.();
}

// ---------------------------------------------------------------- popover contents
function checkRow({ label, sub, count, dot, pressed, onClick, italic }) {
  return h("button", { class: "check-row", type: "button", "aria-pressed": String(pressed), onClick },
    h("span", { class: "cbox" }, icon("check", { "stroke-width": 2.6 })),
    dot ? h("i", { class: "dot", style: { background: dot } }) : null,
    h("span", { class: "nm" }, h("span", { class: italic ? "it" : "" }, label), sub ? h("small", {}, sub) : null),
    count != null ? h("span", { class: "ct" }, fmt(count)) : null);
}
const genusColor = (g) => `var(--c${DATA.slot[g] + 1})`;

function arrondissementContent() {
  const D = DATA, grid = h("div", { class: "arr-grid" }), extra = h("div", { class: "arr-extra" });
  const counts = new Uint32Array(23);
  for (let i = 0; i < D.n; i++) counts[D.arr[i]]++;
  const dens = D.arrGeo.features.map((f, a) => counts[a] / D.arrHa[a]);
  const dmax = Math.max(...dens);
  const cell = (a, main, small) =>
    h("button", { class: "arr-cell", type: "button", "aria-pressed": String(filters.arr.has(a)), style: a < 20 ? { "--d": (dens[a] / dmax).toFixed(2) } : null, title: `${a < 20 ? D.arrGeo.features[a].properties.name + " · " : ""}${fmt(counts[a])} trees`,
      onClick: () => setFilters({ arr: toggleIn(filters.arr, a) }) }, h("span", {}, main), small ? h("small", {}, small) : null);
  const node = h("div", {},
    h("div", { class: "pop-head" }, h("h4", {}, "Arrondissement"),
      h("span", {}, h("button", { class: "linkbtn", type: "button", onClick: () => setFilters({ arr: new Set(Array.from({ length: 20 }, (_, i) => i)) }) }, "All Paris"),
        h("button", { class: "linkbtn", type: "button", onClick: () => setFilters({ arr: new Set() }) }, "Clear"))),
    grid, extra,
    h("p", { class: "pop-note" }, "Shading shows tree density (trees per hectare); hover for the district name. The two Bois are listed apart, as in the inventory. “Outside Paris” = city-owned parks and cemeteries in neighbouring communes."));
  const refresh = () => {
    clear(grid).append(...Array.from({ length: 20 }, (_, a) => cell(a, a === 0 ? "1er" : a + 1 + "e")));
    clear(extra).append(cell(20, "Bois de Boulogne"), cell(21, "Bois de Vincennes"), cell(22, "Outside Paris"));
  };
  refresh();
  return { node, refresh };
}

function taxaContent() {
  const D = DATA;
  const gIdx = D.genera.map((g, i) => ({ i, t: norm(`${g} ${commonEn(g)} ${D.genusFr[i]} ${g === "Styphnolobium" ? "sophora japonica" : ""}`) })).filter((x) => D.genusCount[x.i]);
  const sIdx = D.spp.map((s, i) => ({ i, t: norm(`${D.genera[s.genus]} ${s.epithet} ${s.fr}`) })).filter((x) => D.speciesCount[x.i] && D.spp[x.i].epithet !== "sp.");
  const input = h("input", { type: "search", placeholder: "Search: platane, Sophora, Tilia cordata…", "aria-label": "Search genus or species", autocomplete: "off" });
  const tags = h("div", { class: "tag-row" }), quick = h("div", { class: "quick-genera" }), list = h("div", { class: "list-scroll" });
  const gLabel = (g) => (g === D.genera.indexOf("Styphnolobium") ? "Styphnolobium (Sophora)" : D.genera[g]);
  const sLabel = (s) => { const sp = D.spp[s]; return `${D.genera[sp.genus]} ${sp.epithet.replace(/^x /, "× ")}`; };
  const node = h("div", {},
    h("div", { class: "pop-head" }, h("h4", {}, "Genus & species"), h("button", { class: "linkbtn", type: "button", onClick: () => setFilters({ genus: new Set(), species: new Set() }) }, "Clear")),
    h("div", { class: "search" }, icon("search"), input), tags, quick, list);

  const genusRow = (g) => checkRow({ label: gLabel(g), italic: true, sub: [commonEn(D.genera[g]), D.genusFr[g]].filter(Boolean).join(" · "), count: D.genusCount[g],
    dot: D.slot[g] < GENUS_SLOTS.length ? genusColor(g) : null, pressed: filters.genus.has(g), onClick: () => setFilters({ genus: toggleIn(filters.genus, g) }) });
  const speciesRow = (s) => checkRow({ label: sLabel(s), italic: true, sub: D.spp[s].fr, count: D.speciesCount[s], pressed: filters.species.has(s), onClick: () => setFilters({ species: toggleIn(filters.species, s) }) });

  const refresh = () => {
    clear(tags).append(...[...filters.genus].map((g) => tagEl(gLabel(g), () => setFilters({ genus: toggleIn(filters.genus, g) }))),
      ...[...filters.species].map((s) => tagEl(sLabel(s), () => setFilters({ species: toggleIn(filters.species, s) }))));
    tags.hidden = !tags.childNodes.length;
    const q = norm(input.value.trim());
    quick.hidden = !!q;
    if (!q) {
      clear(quick).append(...D.slotGenus.filter((g) => g >= 0).map((g) =>
        h("button", { class: "qg", type: "button", "aria-pressed": String(filters.genus.has(g)), onClick: () => setFilters({ genus: toggleIn(filters.genus, g) }) },
          h("i", { class: "dot", style: { background: genusColor(g) } }), h("span", { class: "qn" }, h("b", {}, D.genera[g]), h("small", {}, g === D.genera.indexOf("Styphnolobium") ? "Sophora" : commonEn(D.genera[g]))), h("span", { class: "ct" }, fmt(D.genusCount[g])))));
      clear(list).append(h("h4", {}, `All ${gIdx.length} genera`), ...gIdx.sort((a, b) => D.genusCount[b.i] - D.genusCount[a.i]).map((x) => genusRow(x.i)));
    } else {
      const gs = gIdx.filter((x) => x.t.includes(q)).sort((a, b) => D.genusCount[b.i] - D.genusCount[a.i]).slice(0, 8);
      const ss = sIdx.filter((x) => x.t.includes(q)).sort((a, b) => D.speciesCount[b.i] - D.speciesCount[a.i]).slice(0, 40);
      clear(list).append(...(gs.length ? [h("h4", {}, "Genera"), ...gs.map((x) => genusRow(x.i))] : []),
        ...(ss.length ? [h("h4", { style: { marginTop: "10px" } }, "Species"), ...ss.map((x) => speciesRow(x.i))] : []),
        !gs.length && !ss.length ? h("p", { class: "pop-note" }, "No match — try a French name (“tilleul”) or Latin genus.") : null);
    }
  };
  input.addEventListener("input", debounce(refresh, 80));
  refresh();
  return { node, refresh: () => { const st = list.scrollTop; refresh(); list.scrollTop = st; }, focus: () => input.focus() };
}
const tagEl = (text, onRemove) => h("span", { class: "tag" }, h("span", { class: "it" }, text), h("button", { type: "button", "aria-label": "Remove " + text, onClick: onRemove }, "×"));

function checklistContent(title, key, items) {
  const list = h("div", { class: "check-list" });
  const node = h("div", {}, h("div", { class: "pop-head" }, h("h4", {}, title), h("button", { class: "linkbtn", type: "button", onClick: () => setFilters({ [key]: new Set() }) }, "Clear")), list);
  const refresh = () => clear(list).append(...items.map((it) => checkRow({ ...it, pressed: filters[key].has(it.id), onClick: () => setFilters({ [key]: toggleIn(filters[key], it.id) }) })));
  refresh();
  return { node, refresh };
}

function rangeContent({ key, title, min, max, step, unit, values, note }) {
  const D = DATA, nb = Math.round((max - min) / step) + 1;
  const hist = new Array(nb).fill(0);
  for (let i = 0; i < D.n; i++) { const v = values[i]; if (v) hist[Math.min(nb - 1, Math.max(0, Math.floor((v - min) / step)))]++; }
  const hmax = Math.max(...hist);
  const bars = hist.map((c) => h("i", { style: { height: Math.max(2, (Math.sqrt(c) / Math.sqrt(hmax)) * 100) + "%" } }));
  const lo = h("input", { type: "range", min, max, step, value: min, "aria-label": `Minimum ${title.toLowerCase()}` });
  const hi = h("input", { type: "range", min, max, step, value: max, "aria-label": `Maximum ${title.toLowerCase()}` });
  const fillbar = h("div", { class: "fillbar" }), read = h("div", { class: "range-read" });
  const fmtV = (v, isHi) => (isHi && v >= max ? `${max}+` : `${v}`) + " " + unit;
  const paint = () => {
    const a = +lo.value, b = +hi.value;
    fillbar.style.left = ((a - min) / (max - min)) * 100 + "%";
    fillbar.style.right = (1 - (b - min) / (max - min)) * 100 + "%";
    bars.forEach((el, k) => { const v = min + k * step; el.classList.toggle("in", v >= a && v <= b); });
    clear(read).append(h("div", {}, h("span", {}, "From"), h("b", {}, fmtV(a))), h("div", { style: { textAlign: "right" } }, h("span", {}, "To"), h("b", {}, fmtV(b, true))));
  };
  const commit = () => {
    let a = +lo.value, b = +hi.value;
    if (a > b) { [a, b] = [b, a]; }
    setFilters({ [key]: a <= min && b >= max ? null : [a, b >= max ? 99999 : b] });
  };
  for (const inp of [lo, hi]) {
    inp.addEventListener("input", () => { if (+lo.value > +hi.value) { if (inp === lo) lo.value = hi.value; else hi.value = lo.value; } paint(); });
    inp.addEventListener("change", commit);
    inp.addEventListener("input", debounce(commit, 120));
  }
  const node = h("div", {},
    h("div", { class: "pop-head" }, h("h4", {}, title), h("button", { class: "linkbtn", type: "button", onClick: () => { lo.value = min; hi.value = max; paint(); commit(); } }, "Reset")),
    h("div", { class: "range-hist", "aria-hidden": "true" }, bars),
    h("div", { class: "dual" }, h("div", { class: "track" }), fillbar, lo, hi), read, h("p", { class: "pop-note" }, note));
  let dragging = false;
  node.addEventListener("pointerdown", () => { dragging = true; });
  document.addEventListener("pointerup", () => { dragging = false; });
  const refresh = () => {
    if (dragging) return;
    const r = filters[key];
    if (!r) { lo.value = min; hi.value = max; } else { lo.value = r[0]; hi.value = Math.min(r[1], max); }
    paint();
  };
  refresh();
  return { node, refresh };
}

// ---------------------------------------------------------------- the bar
export function initFilterBar(root) {
  const D = DATA;
  const names = (set, f) => [...set].map(f);
  const ARR = (a) => (a < 20 ? (a === 0 ? "1er" : a + 1 + "e") : D.arrNames[a]);
  const groupCounts = new Uint32Array(5), stageCounts = new Uint32Array(5);
  for (let i = 0; i < D.n; i++) { groupCounts[D.group[i]]++; stageCounts[D.stage[i]]++; }
  const GROUP_DOT = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c9)"];

  const defs = [
    { id: "arr", label: "Arrondissement", icon: "pin", active: () => filters.arr.size, value: () => (filters.arr.size <= 3 ? [...filters.arr].sort((a, b) => a - b).map(ARR).join(", ") : `${filters.arr.size} areas`), content: arrondissementContent },
    { id: "taxa", label: "Genus & species", icon: "leaf", active: () => filters.genus.size + filters.species.size, width: 360,
      value: () => { const n = filters.genus.size + filters.species.size; return n <= 2 ? [...[...filters.genus].map((g) => D.genera[g]), ...[...filters.species].map((s) => D.genera[D.spp[s].genus][0] + ". " + D.spp[s].epithet)].join(", ") : `${n} taxa`; }, content: taxaContent },
    { id: "group", label: "Setting", icon: "layers", active: () => filters.group.size, value: () => [...filters.group].map((g) => D.groups[g]).join(", ").replace("Parks & squares", "Parks"),
      content: () => checklistContent("Setting", "group", D.groups.map((g, i) => ({ id: i, label: g === "Street" ? "Street trees" : g, count: groupCounts[i], dot: GROUP_DOT[i] }))) },
    { id: "height", label: "Height", icon: "ruler", active: () => !!filters.height, value: () => { const r = filters.height; return `${r[0]}–${r[1] > 40 ? "40+" : r[1]} m`; },
      content: () => rangeContent({ key: "height", title: "Height", min: 1, max: 40, step: 1, unit: "m", values: D.height, note: "Trees without a recorded height are left out when a range is set." }) },
    { id: "girth", label: "Circumference", icon: "girth", active: () => !!filters.girth, value: () => { const r = filters.girth; return `${r[0]}–${r[1] > 400 ? "400+" : r[1]} cm`; },
      content: () => rangeContent({ key: "girth", title: "Circumference at 1 m", min: 10, max: 400, step: 10, unit: "cm", values: D.circ, note: "Trunk circumference. Trees without a recorded value are left out when a range is set." }) },
    { id: "stage", label: "Stage", icon: "sprout", active: () => filters.stage.size, value: () => [...filters.stage].sort().map((s) => D.stages[s]).join(", "),
      content: () => checklistContent("Development stage", "stage", D.stages.map((s, i) => ({ id: i, label: s, count: stageCounts[i] }))) },
  ];

  const chips = defs.map((d) => {
    const val = h("span", { class: "fv" });
    const btn = h("button", { class: "fchip", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false", onClick: () => {
      if (openPop && openPop.anchor === btn) return closePopover();
      openPopover(btn, d.content(), { width: d.width });
    } }, icon(d.icon), h("span", {}, d.label), val);
    return { d, btn, val };
  });
  const rem = h("button", { class: "fchip rem", type: "button", "aria-pressed": "false", title: "Show only the remarkable (heritage) trees", onClick: () => setFilters({ remarkable: !filters.remarkable }) },
    h("span", { class: "star", "aria-hidden": "true" }, "★"), h("span", {}, "Remarkable only"));
  const reset = h("button", { class: "fb-reset", type: "button", onClick: () => { closePopover(); resetFilters(); } }, "Reset");
  const resB = h("b"), resS = h("span"), meter = h("i");
  const result = h("div", { class: "fb-result", "aria-live": "polite" }, resB, resS, h("div", { class: "fb-meter" }, meter));

  root.append(h("span", { class: "fb-label" }, "Filter"), ...chips.map((c) => c.btn), h("span", { class: "fb-sep" }), rem, reset, result);
  root.addEventListener("scroll", closePopover, { passive: true });

  const update = () => {
    for (const { d, btn, val } of chips) {
      const on = !!d.active();
      btn.classList.toggle("active", on);
      val.textContent = on ? d.value() : "";
    }
    rem.setAttribute("aria-pressed", String(filters.remarkable));
    reset.disabled = activeCount() === 0;
    resB.textContent = fmt(view.count) + (view.count === 1 ? " tree" : " trees");
    resS.textContent = view.active ? `${((view.count / D.n) * 100).toFixed(view.count / D.n < 0.1 ? 1 : 0)}% of ${fmt(D.n)}` : `all ${fmt(D.n)} in the inventory`;
    meter.style.width = (view.count / D.n) * 100 + "%";
    openPop?.refresh?.();
  };
  onFilterChange(update);
  update();
  return { update };
}
