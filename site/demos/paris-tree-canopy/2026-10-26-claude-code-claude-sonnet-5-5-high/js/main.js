import { loadData, setData, DATA, GENUS_SLOTS, commonEn } from "./data.js";
import { filters, view, refresh, onFilterChange, setFilters, toggleIn } from "./state.js";
import { applyThemeVars, COLORS, MODES, legendLabels } from "./theme.js";
import { createMap } from "./map.js";
import { initFilterBar } from "./filters-ui.js";
import { buildDetail } from "./detail.js";
import { renderAnalytics } from "./analytics.js";
import { renderHeritage } from "./heritage.js";
import { renderDistricts } from "./districts.js";
import { h, fmt, clear, $ } from "./format.js";
import { icon } from "./icons.js";

const splash = $("#splash"), splashMsg = $("#splash-msg");
let theme = document.documentElement.dataset.theme;
applyThemeVars(theme);

async function boot() {
  const D = await loadData((m) => { splashMsg.textContent = m; });
  setData(D);
  refresh();
  $("#about").querySelector("p b").textContent = `${fmt(D.n)} trees`;

  let mode = "genus", selected = -1, inView = null, current = "map";
  let legendCollapsed = matchMedia("(max-width: 760px)").matches;
  const views = {
    map: { el: $("#view-map") },
    analytics: { el: $("#view-analytics"), render: () => renderAnalytics($("#view-analytics")), dirty: true },
    heritage: { el: $("#view-heritage"), render: () => renderHeritage($("#view-heritage"), { onLocate: locate }), dirty: true },
    districts: { el: $("#view-districts"), render: () => renderDistricts($("#view-districts"), { onViewOnMap: viewArrOnMap }), dirty: true },
  };

  // ------------------------------------------------------------ map + HUD
  const detailEl = $("#detail"), pill = $("#zoom-pill");
  const mapApi = createMap({
    el: $("#map"), theme, mode,
    onSelect: (row) => showDetail(row),
    onViewChange: (v) => { inView = v.inView; renderHud(); },
    onZoomState: (st) => {
      pill.classList.toggle("off", st === "transition");
      clear(pill);
      if (st === "aggregate") pill.append(h("b", {}, "Hexagons"), " group nearby trees — zoom in to meet each one");
      else if (st === "trees") pill.append("Each disc is one tree, ", h("b", {}, "crown drawn to scale"), " — click for details");
    },
  });

  function showDetail(row) {
    selected = row;
    $("#view-map").classList.toggle("has-detail", row >= 0);
    if (row < 0) { detailEl.hidden = true; clear(detailEl); return; }
    detailEl.hidden = false;
    const node = buildDetail(row, { onClose: () => mapApi.select(-1), onFilterGenus: (g) => setFilters({ genus: new Set([g]) }) });
    detailEl.replaceChildren(node);
    detailEl.scrollTop = 0;
  }
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && selected >= 0 && !document.querySelector(".pop")) mapApi.select(-1); });

  function renderHud() {
    const rem = countRemarkable();
    const chip = (cls, ic, big, small) => h("div", { class: "stat-chip " + cls }, h("span", { class: "ic" }, ic), h("div", {}, h("b", {}, big), h("br"), h("span", {}, small)));
    $("#hud-stats").replaceChildren(
      chip("", icon("tree"), fmt(view.count), view.active ? `of ${fmt(DATA.n)} trees` : "municipal trees"),
      chip("gold", "★", fmt(rem), "remarkable"),
      inView != null ? chip("", icon("eye"), fmt(inView), "in view") : null);
  }
  function countRemarkable() { let c = 0; for (const r of DATA.heritage) if (view.mask[r.row]) c++; return c; }

  // ------------------------------------------------------------ legend (colour mode + filter shortcuts)
  function renderLegend() {
    const D = DATA, el = $("#legend"), counts = mapApi.classCounts(), labels = legendLabels(mode, D), pal = COLORS[theme][mode];
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Colour trees by" }, Object.entries(MODES).map(([k, m]) =>
      h("button", { type: "button", title: m.help, "aria-pressed": String(mode === k), onClick: () => { mode = k; mapApi.setMode(k); renderLegend(); } }, m.label)));
    const rows = labels.map((lab, k) => {
      if (mode !== "genus" && !counts[k] && (k === labels.length - 1)) return null;
      if (mode === "stage" && k === 4 && !counts[4]) return null;
      const g = mode === "genus" && k < GENUS_SLOTS.length ? D.slotGenus[k] : -1;
      const sub = mode === "genus" && k < GENUS_SLOTS.length ? commonEn(GENUS_SLOTS[k]) : "";
      return h(g >= 0 ? "button" : "div", { class: "lg-row" + (mode === "genus" ? "" : " ramp") + (counts[k] ? "" : " zero"), type: g >= 0 ? "button" : null, "aria-pressed": g >= 0 ? String(filters.genus.has(g)) : null,
        title: g >= 0 ? "Click to filter this genus" : null, onClick: g >= 0 ? () => setFilters({ genus: toggleIn(filters.genus, g) }) : null },
        h("i", { class: "sw", style: { background: pal[k] } }), h("span", { class: "nm" }, g >= 0 ? h("span", { style: { fontStyle: "italic" } }, lab) : lab, sub ? h("i", {}, sub) : null), h("em", {}, fmt(counts[k])));
    });
    const title = { genus: "Colour · botanical genus", height: "Colour · mean height", girth: "Colour · trunk circumference", stage: "Colour · development stage" }[mode];
    el.classList.toggle("collapsed", legendCollapsed);
    const toggle = h("button", { class: "lg-toggle", type: "button", "aria-expanded": String(!legendCollapsed), "aria-label": legendCollapsed ? "Show legend" : "Hide legend",
      onClick: () => { legendCollapsed = !legendCollapsed; renderLegend(); } }, icon("chev", { style: { transform: legendCollapsed ? "rotate(180deg)" : "" } }));
    el.replaceChildren(seg, h("div", { class: "lg-title" }, title, toggle), h("div", { class: "lg-list" }, rows),
      h("div", { class: "lg-foot" }, h("span", { class: "badge-ico" }, "★"), "Remarkable heritage tree"));
  }

  // ------------------------------------------------------------ filters
  initFilterBar($("#filterbar"));
  let lastArr = "";
  onFilterChange(() => {
    mapApi.invalidate();
    mapApi.setArrondissements(filters.arr);
    renderHud(); renderLegend();
    for (const [k, v] of Object.entries(views)) if (v.render) v.dirty = true;
    if (current !== "map") renderCurrent();
    const key = [...filters.arr].sort().join(",");
    if (key !== lastArr) { lastArr = key; if (current === "map") mapApi.fitArr(filters.arr); }
    if (selected >= 0 && !view.mask[selected]) mapApi.select(-1);
  });
  document.dispatchEvent(new Event("filters-ready"));

  // ------------------------------------------------------------ views / routing
  function renderCurrent() {
    const v = views[current];
    if (v.render && v.dirty) { v.dirty = false; v.render(); }
  }
  function showView(name) {
    if (!views[name]) name = "map";
    current = name;
    for (const [k, v] of Object.entries(views)) v.el.classList.toggle("on", k === name);
    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === name)));
    renderCurrent();
    if (name === "map") requestAnimationFrame(() => mapApi.resize());
    else views[name].el.scrollTop = 0;
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  }
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

  function locate(row) { showView("map"); setTimeout(() => mapApi.flyTo(row, 18.4), 60); }
  async function viewArrOnMap(a) {
    setFilters({ arr: new Set([a]) });
    await Promise.resolve();
    showView("map");
    setTimeout(() => mapApi.fitArr(filters.arr), 80);
  }

  // ------------------------------------------------------------ theme + about
  $("#theme-btn").addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("canopee-theme", theme); } catch { /* private mode */ }
    applyThemeVars(theme);
    mapApi.setTheme(theme);
    renderLegend();
    for (const v of Object.values(views)) if (v.render) v.dirty = true;
    renderCurrent();
  });
  $("#about-btn").addEventListener("click", () => $("#about").showModal());
  $("#about").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });

  renderHud(); renderLegend();
  showView(location.hash.slice(1) || "map");
  mapApi.map.once("idle", () => splash.classList.add("done"));
  setTimeout(() => splash.classList.add("done"), 6000);
  window.__canopee = { mapApi, DATA, filters, view, showView };
}

boot().catch((err) => {
  console.error(err);
  splashMsg.textContent = "Something went wrong: " + err.message;
  document.querySelector(".splash-bar").remove();
});
