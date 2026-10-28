// Tree detail card (right-hand panel on the map).
import { DATA, treeName, treeLatin, speciesLatin, addressOf, complementOf, cultivarOf, commonEn } from "./data.js";
import { h, fmt, fmt1, clear, safeUrl } from "./format.js";
import { icon } from "./icons.js";

const YEAR = new Date().getFullYear();

/** cm of girth gained per year, calibrated on the heritage trees whose planting year is known. */
let girthPerYear = null;
export function ageModel() {
  if (girthPerYear) return girthPerYear;
  const r = DATA.heritage.filter((t) => t.year && t.girth && YEAR - t.year > 20).map((t) => t.girth / (YEAR - t.year)).sort((a, b) => a - b);
  girthPerYear = r.length ? r[r.length >> 1] : 2.2;
  return girthPerYear;
}
/** Age facts for a heritage record: exact when the planting year is known, else a rough girth-based estimate. */
export function ageOf(rec) {
  if (rec.year) return { years: YEAR - rec.year, exact: true, year: rec.year };
  if (rec.girth) return { years: Math.max(10, Math.round(rec.girth / ageModel() / 5) * 5), exact: false, year: null };
  return null;
}

const speciesStats = new Map();
function statsForSpecies(si) {
  let s = speciesStats.get(si);
  if (s) return s;
  const D = DATA;
  s = { n: 0, hh: new Uint32Array(61), cc: new Uint32Array(1001) };
  for (let i = 0; i < D.n; i++) if (D.species[i] === si) { s.n++; s.hh[D.height[i]]++; s.cc[D.circ[i]]++; }
  speciesStats.set(si, s);
  return s;
}
function percentile(hist, v) {
  let below = 0, eq = 0, n = 0;
  for (let k = 1; k < hist.length; k++) { n += hist[k]; if (k < v) below += hist[k]; else if (k === v) eq = hist[k]; }
  return { n, pct: n ? (below + eq / 2) / n : 0 };
}
const quantile = (hist, p) => { let n = 0; for (let k = 1; k < hist.length; k++) n += hist[k]; let a = 0; for (let k = 1; k < hist.length; k++) { a += hist[k]; if (a >= p * n) return k; } return hist.length - 1; };

function compare(label, unit, hist, value, hi) {
  const { n, pct } = percentile(hist, value);
  if (n < 8 || !value) return null;
  const p5 = quantile(hist, 0.05), p95 = quantile(hist, 0.95), med = quantile(hist, 0.5);
  const lo = Math.min(p5, value), top = Math.max(p95, value), span = Math.max(1, top - lo), pos = (v) => ((v - lo) / span) * 100;
  const word = pct >= 0.5 ? "bigger" : "smaller";
  return h("div", { class: "cmp" },
    h("div", { class: "cmp-head" }, h("b", {}, `${label}: ${value} ${unit}`), h("span", {}, pct >= 0.995 ? "among the very largest" : pct <= 0.005 ? "among the smallest" : `${Math.round((pct >= 0.5 ? pct : 1 - pct) * 100)}% of peers ${pct >= 0.5 ? "are smaller" : "are larger"}`)),
    h("div", { class: "cmp-track", role: "img", "aria-label": `${label} ${value} ${unit}; species median ${med} ${unit}` },
      h("s", { style: { left: pos(p5) + "%", width: Math.max(1, pos(p95) - pos(p5)) + "%" } }), h("i", { style: { left: pos(med) + "%" } }), h("u", { style: { left: pos(value) + "%" } })),
    h("div", { class: "cmp-foot" }, h("span", {}, `${p5} ${unit}`), h("span", {}, `median ${med} ${unit} · 90% range`), h("span", {}, `${p95} ${unit}`)));
}

export function buildDetail(row, { onClose, onFilterGenus }) {
  const D = DATA, rec = D.heritageByRow.get(row), si = D.species[row], g = D.genus[row];
  const dom = D.domains[D.domain[row]], arr = D.arr[row];
  const lat = D.lat[row] / 1e6, lon = D.lon[row] / 1e6;
  const arrLabel = arr < 20 ? `${arr === 0 ? "1er" : arr + 1 + "e"} arrondissement` : D.arrNames[arr];
  const genusColor = `var(--c${D.slot[g] + 1})`;
  const addr = [addressOf(row), complementOf(row)].filter(Boolean);
  const stage = D.stage[row], stageLabel = D.stages[stage];
  const sp = D.spp[si];
  const age = rec ? ageOf(rec) : null;

  const copy = h("button", { class: "btn sm", type: "button", onClick: async () => {
    try { await navigator.clipboard.writeText(`${lat.toFixed(6)}, ${lon.toFixed(6)}`); copy.lastChild.textContent = "Copied"; setTimeout(() => (copy.lastChild.textContent = "Copy"), 1400); } catch { /* clipboard unavailable */ }
  } }, icon("copy"), h("span", {}, "Copy"));

  const photo = safeUrl(rec?.photo) ? h("img", { class: "d-photo", src: rec.photo, alt: `${rec.name}, ${rec.site}`, loading: "lazy", referrerpolicy: "no-referrer", onError: (e) => e.target.remove() }) : null;

  const card = h("div", {},
    h("div", { class: "d-hero" },
      h("button", { class: "d-close", type: "button", "aria-label": "Close details", onClick: onClose }, icon("x", { "stroke-width": 2 })),
      h("div", { class: "d-eyebrow" }, h("i", { class: "dot", style: { background: genusColor } }), `${dom.label} · ${arr < 20 ? (arr === 0 ? "1er" : arr + 1 + "e") + " arr." : D.arrNames[arr]}`),
      h("h2", {}, treeName(row)),
      h("div", { class: "d-latin" }, treeLatin(row)),
      cultivarOf(row) ? h("div", { class: "d-cultivar" }, `Cultivar ‘${cultivarOf(row)}’`) : null,
      rec ? h("div", { class: "d-badge" }, h("span", { class: "badge-ico" }, "★"), "Remarkable tree", rec.label ? ` · ${rec.label}` : "") : null),
    photo,
    h("div", { class: "d-metrics" },
      h("div", { class: "metric" }, h("span", {}, "Height"), h("b", {}, D.height[row] ? [D.height[row], h("small", {}, "m")] : "—"), D.height[row] ? null : h("em", {}, "not recorded")),
      h("div", { class: "metric" }, h("span", {}, "Circumference"), h("b", {}, D.circ[row] ? [D.circ[row], h("small", {}, "cm")] : "—"), h("em", {}, D.circ[row] ? `≈ ${Math.round(D.circ[row] / Math.PI)} cm trunk Ø` : "not recorded")),
      h("div", { class: "metric" }, h("span", {}, "Stage"), h("b", { style: { fontSize: "16px", paddingTop: "3px" } }, stageLabel),
        h("div", { class: "stage-steps", "aria-hidden": "true" }, [0, 1, 2, 3].map((k) => h("i", { class: stage < 4 && k <= stage ? "on" : "" }))))),
    rec ? heritageSection(rec, age) : null,
    h("div", { class: "d-sec" }, h("h4", {}, "Botany"),
      h("dl", { class: "kv" },
        h("dt", {}, "Common name"), h("dd", {}, treeName(row)),
        h("dt", {}, "Genus"), h("dd", {}, h("i", {}, D.genera[g]), commonEn(D.genera[g]) ? ` · ${commonEn(D.genera[g])}` : ""),
        h("dt", {}, "Species"), h("dd", {}, h("i", {}, speciesLatin(si))),
        cultivarOf(row) ? [h("dt", {}, "Cultivar"), h("dd", {}, cultivarOf(row))] : null,
        h("dt", {}, "Same species"), h("dd", {}, `${fmt(D.speciesCount[si])} trees in Paris`))),
    comparisons(row, si),
    h("div", { class: "d-sec" }, h("h4", {}, "Location"),
      h("dl", { class: "kv" },
        h("dt", {}, "Address"), h("dd", {}, addr.length ? addr.join(" · ") : "—"),
        h("dt", {}, "Setting"), h("dd", {}, dom.label),
        h("dt", {}, "District"), h("dd", {}, arr < 20 ? `${arrLabel} · ${D.arrGeo.features[arr].properties.name}` : arrLabel),
        h("dt", {}, "Coordinates"), h("dd", {}, h("span", { class: "coords" }, `${lat.toFixed(5)}° N, ${lon.toFixed(5)}° E`, copy)))),
    h("div", { class: "d-links" },
      h("a", { class: "btn", href: `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=19/${lat}/${lon}`, target: "_blank", rel: "noopener" }, icon("ext"), "OpenStreetMap"),
      h("a", { class: "btn", href: `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${lat},${lon}`, target: "_blank", rel: "noopener" }, icon("ext"), "Street View"),
      h("button", { class: "btn", type: "button", onClick: () => onFilterGenus(g) }, icon("leaf"), `All ${D.genera[g]}`)),
    h("div", { class: "d-foot" }, `Inventory ID ${D.id[row]} · Source: Ville de Paris, Open Data (ODbL)`));
  return card;
}

function comparisons(row, si) {
  const D = DATA, st = statsForSpecies(si);
  const blocks = [D.height[row] ? compare("Height", "m", st.hh, D.height[row]) : null, D.circ[row] ? compare("Circumference", "cm", st.cc, D.circ[row]) : null].filter(Boolean);
  if (!blocks.length) return null;
  return h("div", { class: "d-sec" }, h("h4", {}, `Compared with ${fmt(st.n)} ${speciesLatin(si)}`), ...blocks);
}

function heritageSection(rec, age) {
  const long = rec.description || "";
  const more = h("div", { class: "d-text", style: { marginTop: "10px" } }, long.length > 260 ? long.slice(0, 260).replace(/\s\S*$/, "") + "…" : long);
  let open = false;
  const toggle = long.length > 260 ? h("button", { class: "linkbtn", type: "button", style: { padding: "6px 0" }, onClick: () => { open = !open; more.textContent = open ? long : long.slice(0, 260).replace(/\s\S*$/, "") + "…"; toggle.textContent = open ? "Show less" : "Read the full story"; } }, "Read the full story") : null;
  return h("div", { class: "d-sec" }, h("h4", {}, "Heritage"),
    h("div", { class: "kv", style: { marginBottom: "12px" } },
      h("div", { style: { gridColumn: "1 / -1" } }, h("div", { class: "d-quote" }, rec.citation || "Recognised by the City of Paris as a remarkable tree."))),
    h("dl", { class: "kv" },
      h("dt", {}, "Site"), h("dd", {}, rec.site || "—"),
      h("dt", {}, age?.exact ? "Planted" : "Age"),
      h("dd", {}, age ? (age.exact ? `${age.year} · ${age.years} years old` : `≈ ${age.years} years · rough estimate from girth (planting year unknown)`) : "unknown"),
      h("dt", {}, "Criteria"), h("dd", {}, h("div", { class: "chips" }, h("span", { class: "chip gold" }, rec.category), rec.tags.map((t) => h("span", { class: "chip" }, t)))),
      rec.deliberation ? [h("dt", {}, "Decision"), h("dd", {}, rec.deliberation)] : null),
    long ? more : null, toggle,
    h("div", { style: { display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" } },
      safeUrl(rec.pdf) ? h("a", { class: "btn sm", href: rec.pdf, target: "_blank", rel: "noopener" }, icon("ext"), "Fact sheet (PDF)") : null),
    rec.credit ? h("p", { class: "muted", style: { fontSize: "11px", marginTop: "8px" } }, "Photo: " + rec.credit) : null);
}
