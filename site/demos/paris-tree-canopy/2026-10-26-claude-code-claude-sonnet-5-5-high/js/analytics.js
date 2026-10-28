// Urban forest analytics: everything here re-computes from the current filter selection.
import { DATA, GENUS_SLOTS, commonEn, speciesLatin } from "./data.js";
import { filters, view, setFilters, toggleIn } from "./state.js";
import { computeStats, ranked } from "./stats.js";
import { h, fmt, fmt1, pct, clear } from "./format.js";
import { barList, histogram, stackedBar, legendRow, tableView, viewToggle, tipNode, bindTip } from "./charts.js";
import { icon } from "./icons.js";

export const GROUP_COLOR = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c9)"];
export const genusColor = (g) => `var(--c${DATA.slot[g] + 1})`;
export const speciesName = (si) => DATA.spp[si].fr || speciesLatin(si);

function kpi(label, value, unit, sub, cls = "") {
  return h("div", { class: "kpi " + cls }, h("div", { class: "k-label" }, label), h("div", { class: "k-val" }, value, unit ? h("small", {}, unit) : null), h("div", { class: "k-sub" }, sub));
}
const card = (title, sub, body, tools) =>
  h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", {}, title), sub ? h("p", { class: "sub" }, sub) : null), tools || null), body);

export function renderAnalytics(root) {
  const D = DATA, S = computeStats(view.mask), total = Math.max(1, S.count);
  const page = h("div", { class: "page" });
  const scope = view.active ? h("span", { class: "scope-note" }, "Showing ", h("b", {}, `${fmt(S.count)} trees`), " in the current selection") : h("span", { class: "scope-note" }, "Showing the whole municipal inventory");
  page.append(h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "eyebrow" }, "Urban forest analytics"), h("h2", {}, S.count ? `${fmt(S.count)} trees, ${fmt(S.div.richness)} species: the shape of Paris's canopy` : "No tree matches the current filters"),
      h("p", {}, "Every number and chart below follows the filters above — slice by arrondissement, genus, size or setting to see how the composition shifts.")), scope));
  if (!S.count) { page.append(h("div", { class: "empty" }, h("h3", {}, "Nothing to analyse"), h("p", {}, "Relax a filter to bring trees back."))); root.replaceChildren(page); return; }

  // ---- KPIs
  page.append(h("div", { class: "kpis" },
    kpi("Trees", fmt(S.count), "", view.active ? `${pct(S.count / D.n, 1)} of ${fmt(D.n)} in the inventory` : "municipal inventory"),
    kpi("Species", fmt(S.div.richness), "", `${fmt(S.genera)} genera · ${pct(S.speciesCount.reduce((a, c, i) => a + (D.spp[i].epithet === "sp." ? c : 0), 0) / total)} identified to genus only`),
    kpi("Median height", S.height.n ? fmt(S.height.median) : "—", "m", S.height.n ? `mean ${fmt1(S.height.mean)} m · 90% under ${S.height.p90} m` : "not recorded"),
    kpi("Median girth", S.girth.n ? fmt(S.girth.median) : "—", "cm", S.girth.n ? `mean ${fmt(S.girth.mean)} cm · 90% under ${S.girth.p90} cm` : "not recorded"),
    kpi("Effective diversity", fmt(S.div.effective), "spp.", `Shannon H′ ${S.div.shannon.toFixed(2)} · evenness ${S.div.evenness.toFixed(2)}`),
    kpi("Remarkable", fmt(S.remarkable), "", S.remarkable ? "heritage-listed trees" : "none in this selection", "gold")));

  // ---- left column: species + genus
  const topSp = ranked(S.speciesCount, 15);
  const spItems = topSp.map(([si, c]) => ({ label: speciesName(si), sub: D.spp[si].fr ? speciesLatin(si) : null, value: c, share: c / total, color: genusColor(D.speciesGenus[si]),
    active: filters.species.has(si), onClick: () => setFilters({ species: toggleIn(filters.species, si) }),
    tip: tipNode(speciesName(si), [{ label: speciesLatin(si), value: null }, { label: "Trees", value: fmt(c), color: genusColor(D.speciesGenus[si]) }, { label: "Share", value: pct(c / total, 1) }, { label: "Click to filter the map", value: null }]) }));
  const spToggle = viewToggle("species",
    () => barList(spItems),
    () => tableView([{ label: "#" }, { label: "Common name" }, { label: "Species" }, { label: "Trees", num: true }, { label: "Share", num: true }],
      ranked(S.speciesCount, 40).map(([si, c], k) => [k + 1, D.spp[si].fr || "—", speciesLatin(si), fmt(c), pct(c / total, 1)])));

  const gRank = ranked(S.genusCount);
  const slotSegs = [];
  let shown = 0;
  for (const [g, c] of gRank) if (D.slot[g] < GENUS_SLOTS.length) { slotSegs.push({ label: D.genera[g], value: c, color: genusColor(g) }); shown += c; }
  slotSegs.sort((a, b) => b.value - a.value);
  if (total - shown > 0) slotSegs.push({ label: "Other genera", value: total - shown, color: "var(--c9)" });
  const gList = h("div", { class: "glist" }, gRank.slice(0, 14).map(([g, c]) =>
    h("button", { class: "grow", type: "button", title: "Click to filter", onClick: () => setFilters({ genus: toggleIn(filters.genus, g) }) },
      h("i", { class: "sw", style: { background: genusColor(g) } }), h("span", {}, h("i", { style: { fontStyle: "italic" } }, D.genera[g]), commonEn(D.genera[g]) ? h("span", { class: "muted" }, ` ${commonEn(D.genera[g])}`) : null), h("em", {}, pct(c / total, 1)))));
  const left = h("div", { class: "stackcol c-7" },
    card("Top species", "Most frequent species in the selection · click a bar to filter", spToggle.body, spToggle.seg),
    card("Genus mix", `${fmt(S.genera)} genera — the eight colour-coded genera cover ${pct(shown / total)} of trees`, h("div", {}, stackedBar(slotSegs), legendRow(slotSegs), gList)));

  // ---- right column: density by arrondissement + resilience
  const dens = D.arrGeo.features.map((f, a) => ({ a, n: S.arr[a], d: S.arr[a] / D.arrHa[a], f })).sort((x, y) => y.d - x.d);
  const dmax = Math.max(...dens.map((x) => x.d), 1);
  const densBars = barList(dens.map((x) => ({ label: `${x.a === 0 ? "1er" : x.a + 1 + "e"}`, sub: x.f.properties.name, value: x.d, color: "var(--seq-4)", active: filters.arr.has(x.a),
    onClick: () => setFilters({ arr: toggleIn(filters.arr, x.a) }),
    tip: tipNode(`${x.a + 1}${x.a === 0 ? "er" : "e"} · ${x.f.properties.name}`, [{ label: "Trees per hectare", value: x.d.toFixed(1) }, { label: "Trees", value: fmt(x.n) }, { label: "Area", value: fmt(D.arrHa[x.a]) + " ha" + (x.a === 11 || x.a === 15 ? " (excl. Bois)" : "") }]) })),
    { max: dmax, valueFmt: (v) => v.toFixed(1), showShare: false });
  densBars.style.gap = "1px";
  const topSpecies = ranked(S.speciesCount.map((c, i) => (D.spp[i].epithet === "sp." ? 0 : c)), 1)[0];
  const topGenus = gRank[0];
  const guide = (label, sub, share, line, scaleMax = 0.4) =>
    h("div", { class: "guide-row" }, h("div", { class: "gl" }, label, h("small", {}, sub)),
      h("div", { class: "guide-track", role: "img", "aria-label": `${label}: ${pct(share, 1)}; guideline ${pct(line)}` }, h("s", { style: { width: Math.min(100, (share / scaleMax) * 100) + "%", background: share > line ? "var(--c2)" : "var(--c3)" } }), h("u", { "data-l": `${pct(line)} rule`, style: { left: (line / scaleMax) * 100 + "%" } })),
      h("div", { class: "gv" + (share > line ? " over" : "") }, pct(share, 1)));
  const resilience = h("div", {}, topSpecies ? guide("Most common species", speciesName(topSpecies[0]), topSpecies[1] / total, 0.1) : null, topGenus ? guide("Most common genus", D.genera[topGenus[0]] + (commonEn(D.genera[topGenus[0]]) ? ` · ${commonEn(D.genera[topGenus[0]])}` : ""), topGenus[1] / total, 0.2) : null,
    topSpecies && topGenus ? h("div", { class: "insight" }, icon("bulb"),
      h("span", {}, topSpecies[1] / total > 0.1 || topGenus[1] / total > 0.2
        ? `A single ${topSpecies[1] / total > 0.1 ? "species" : "genus"} above the guideline leaves the canopy exposed to pests such as the plane tree canker stain or the horse-chestnut leaf miner — diversifying plantings is the usual remedy.`
        : "No species or genus exceeds the classic 10-20-30 guideline in this selection — a comparatively resilient mix.")) : null,
    h("p", { class: "legend-note" }, "The 10-20-30 rule of thumb (Santamour, 1990): no more than 10% of one species, 20% of one genus, 30% of one family."));
  const right = h("div", { class: "stackcol c-5" },
    card("Canopy density by arrondissement", "Trees per hectare (a proxy, not measured canopy cover) · click to filter", densBars),
    card("Resilience check", "Is the canopy dominated by too few species?", resilience));

  const hc = card("Height distribution", S.height.n ? `${fmt(S.height.n)} trees with a recorded height · median ${S.height.median} m · mean ${fmt1(S.height.mean)} m` : "No height recorded", histogram(S.hHist, { from: 0, to: 40, bin: 2, unit: " m", median: S.height.median, color: "var(--c1)", label: "tree height" }));
  const cc = card("Circumference distribution", S.girth.n ? `${fmt(S.girth.n)} trees with a recorded girth · median ${S.girth.median} cm · mean ${fmt(S.girth.mean)} cm` : "No girth recorded", histogram(S.cHist, { from: 0, to: 400, bin: 20, unit: " cm", median: S.girth.median, color: "var(--c2)", label: "trunk circumference" }));
  hc.classList.add("c-6"); cc.classList.add("c-6");

  const stageSegs = D.stages.map((s, i) => ({ label: s, value: S.stage[i], color: `var(--st-${i})` }));
  const stageCard = card("Development stage", "Age class recorded by the city's foresters", h("div", {}, stackedBar(stageSegs), legendRow(stageSegs),
    h("p", { class: "legend-note" }, S.stage[4] ? `${pct(S.stage[4] / total)} of the selection has no stage recorded.` : "Every tree has a recorded stage.")));
  const grpSegs = D.groups.map((g, i) => ({ label: i === 0 ? "Street trees" : g, value: S.group[i], color: GROUP_COLOR[i] }));
  const grpCard = card("Where the trees stand", "Street alignments, parks and squares, cemeteries and facilities", h("div", {}, stackedBar(grpSegs), legendRow(grpSegs),
    h("p", { class: "legend-note" }, `Street trees: ${fmt(S.group[0])} · Parks & squares: ${fmt(S.group[1])}`)));
  stageCard.classList.add("c-6"); grpCard.classList.add("c-6");
  page.append(h("div", { class: "grid" }, left, right, hc, cc, stageCard, grpCard));
  root.replaceChildren(page);
}
