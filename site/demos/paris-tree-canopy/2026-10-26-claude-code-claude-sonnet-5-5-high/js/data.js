// Loads the columnar tree dataset and builds the derived lookup tables.
// Fixed categorical slots (validated palette order). Color follows the genus, never its rank.
export const GENUS_SLOTS = ["Platanus", "Aesculus", "Tilia", "Acer", "Styphnolobium", "Prunus", "Quercus", "Celtis"];
export const OTHER_SLOT = GENUS_SLOTS.length; // grey "Other genera"

const COMMON_EN = {
  Platanus: "Plane tree", Aesculus: "Horse chestnut", Tilia: "Linden", Acer: "Maple",
  Styphnolobium: "Pagoda tree", Sophora: "Sophora", Prunus: "Cherry & plum", Quercus: "Oak",
  Celtis: "Hackberry", Fraxinus: "Ash", Pinus: "Pine", Pyrus: "Pear", Carpinus: "Hornbeam", Corylus: "Hazel",
  Malus: "Apple & crabapple", Populus: "Poplar", Taxus: "Yew", Ulmus: "Elm", Gleditsia: "Honey locust",
  Robinia: "Black locust", Betula: "Birch", Fagus: "Beech", Magnolia: "Magnolia", Cercis: "Judas tree",
  Paulownia: "Paulownia", Juglans: "Walnut", Cedrus: "Cedar", Ginkgo: "Ginkgo", Catalpa: "Catalpa",
  Liquidambar: "Sweetgum", Salix: "Willow", Alnus: "Alder", Sorbus: "Rowan", Cupressus: "Cypress",
  Sequoia: "Redwood", Sequoiadendron: "Giant sequoia", Castanea: "Sweet chestnut", Morus: "Mulberry",
  Ailanthus: "Tree of heaven", Cedrela: "Cedrela", Toona: "Chinese mahogany", Zelkova: "Zelkova",
  Liriodendron: "Tulip tree", Metasequoia: "Dawn redwood", Taxodium: "Bald cypress", Ilex: "Holly",
  Laburnum: "Laburnum", Koelreuteria: "Golden-rain tree", Crataegus: "Hawthorn", Cornus: "Dogwood",
  Ficus: "Fig", Olea: "Olive", Cedar: "Cedar", Larix: "Larch", Picea: "Spruce", Abies: "Fir",
  Eucalyptus: "Eucalyptus", Albizia: "Silk tree", Maclura: "Osage orange", Diospyros: "Persimmon",
};
export const commonEn = (g) => COMMON_EN[g] || "";

export async function loadData(onProgress = () => {}) {
  onProgress("Fetching the inventory…");
  const [meta, res, heritage, arrGeo] = await Promise.all([
    fetch("data/meta.json").then((r) => r.json()),
    fetch("data/trees.bin.gz"),
    fetch("data/heritage.json").then((r) => r.json()),
    fetch("data/arrondissements.json").then((r) => r.json()),
  ]);
  if (!res.ok) throw new Error("trees.bin.gz: HTTP " + res.status);
  if (typeof DecompressionStream === "undefined") throw new Error("This browser lacks DecompressionStream support.");
  onProgress("Unpacking the trees…");
  const buf = await new Response(res.body.pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();

  const n = meta.n;
  const TYPES = { I: Uint32Array, i: Int32Array, H: Uint16Array, B: Uint8Array };
  // per-tree columns: id lon lat species name height circ domain arr stage flag addr comp cultivar
  const D = { n, meta, heritage, arrGeo };
  for (const c of meta.columns) D[c.name] = new TYPES[c.type](buf, c.offset, n);

  // --- dictionaries
  D.genera = meta.genera;
  D.spp = meta.species.map(([genus, epithet, fr]) => ({ genus, epithet, fr }));
  D.domains = meta.domains;
  D.groups = meta.groups;
  D.stages = meta.stages;
  D.arrNames = meta.arrondissements;
  D.speciesGenus = Uint8Array.from(D.spp.map((s) => s.genus));

  // --- derived per-tree columns
  onProgress("Indexing…");
  const groupOfDomain = Uint8Array.from(meta.domains.map((d) => d.group));
  D.genus = new Uint8Array(n);
  D.group = new Uint8Array(n);
  D.mx = new Float64Array(n);
  D.my = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    D.genus[i] = D.speciesGenus[D.species[i]];
    D.group[i] = groupOfDomain[D.domain[i]];
    const lon = D.lon[i] / 1e6, lat = D.lat[i] / 1e6;
    D.mx[i] = mercX(lon);
    D.my[i] = mercY(lat);
  }

  // genus -> color slot (0..7 named genera, 8 = other)
  D.slot = new Uint8Array(D.genera.length).fill(OTHER_SLOT);
  GENUS_SLOTS.forEach((g, s) => {
    const gi = D.genera.indexOf(g);
    if (gi >= 0) D.slot[gi] = s;
  });
  D.slotGenus = GENUS_SLOTS.map((g) => D.genera.indexOf(g));

  // static counts (declared before use below)
  D.genusCount = new Uint32Array(D.genera.length);
  D.speciesCount = new Uint32Array(D.spp.length);
  for (let i = 0; i < n; i++) { D.genusCount[D.genus[i]]++; D.speciesCount[D.species[i]]++; }

  // French genus name = French name of the genus' most frequent species ("Platanus" -> "Platane")
  D.genusFr = D.genera.map(() => "");
  const best = new Uint32Array(D.genera.length);
  D.spp.forEach((sp, si) => {
    if (sp.fr && D.speciesCount[si] > best[sp.genus]) { best[sp.genus] = D.speciesCount[si]; D.genusFr[sp.genus] = sp.fr.split(" ")[0]; }
  });

  // The official outlines of the 12e and 16e include the Bois de Vincennes / Boulogne, whose trees the inventory
  // lists separately. Density therefore uses the area *without* the Bois (995 ha and 846 ha) so it compares like with like.
  D.arrHa = D.arrGeo.features.map((f, a) => f.properties.ha - (a === 11 ? 995 : a === 15 ? 846 : 0));

  // heritage lookup: tree row -> heritage record
  D.heritageByRow = new Map(D.heritage.map((r) => [r.row, r]));
  buildGrid(D);
  return D;
}

export const mercX = (lon) => (lon + 180) / 360;
export const mercY = (lat) => {
  const s = Math.sin((lat * Math.PI) / 180);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};
export const unmercX = (x) => x * 360 - 180;
export const unmercY = (y) => (360 / Math.PI) * Math.atan(Math.exp((0.5 - y) * 2 * Math.PI)) - 90;

/** Uniform grid (CSR layout) over the data's bounding box for fast viewport / nearest-tree queries. */
const GRID = 512;
function buildGrid(D) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < D.n; i++) {
    const x = D.mx[i], y = D.my[i];
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  const g = { x0, y0, sx: GRID / (x1 - x0 + 1e-12), sy: GRID / (y1 - y0 + 1e-12) };
  const start = new Uint32Array(GRID * GRID + 1);
  const cellOf = new Uint32Array(D.n);
  for (let i = 0; i < D.n; i++) {
    const cx = Math.min(GRID - 1, ((D.mx[i] - x0) * g.sx) | 0), cy = Math.min(GRID - 1, ((D.my[i] - y0) * g.sy) | 0);
    const c = cy * GRID + cx;
    cellOf[i] = c;
    start[c + 1]++;
  }
  for (let c = 0; c < GRID * GRID; c++) start[c + 1] += start[c];
  const fill = start.slice(0, -1);
  const order = new Uint32Array(D.n);
  for (let i = 0; i < D.n; i++) order[fill[cellOf[i]]++] = i;
  g.start = start; g.order = order; g.size = GRID;
  g.bbox = [x0, y0, x1, y1];
  D.grid = g;
}

/** Calls fn(row) for every tree whose world coords fall inside the rectangle. */
export function queryRect(D, xa, ya, xb, yb, fn) {
  const g = D.grid, N = g.size;
  const c0 = Math.max(0, ((xa - g.x0) * g.sx) | 0), c1 = Math.min(N - 1, ((xb - g.x0) * g.sx) | 0);
  const r0 = Math.max(0, ((ya - g.y0) * g.sy) | 0), r1 = Math.min(N - 1, ((yb - g.y0) * g.sy) | 0);
  if (xb < g.x0 || xa > g.bbox[2] || yb < g.y0 || ya > g.bbox[3]) return;
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) {
      const cell = r * N + c;
      for (let k = g.start[cell], e = g.start[cell + 1]; k < e; k++) {
        const i = g.order[k];
        const x = D.mx[i], y = D.my[i];
        if (x >= xa && x <= xb && y >= ya && y <= yb) fn(i);
      }
    }
  }
}

// ---------- labelling helpers
export function speciesLatin(si) {
  const s = DATA.spp[si], g = DATA.genera[s.genus];
  const e = s.epithet === "sp." ? "sp." : s.epithet.replace(/^x /, "× ");
  return `${g} ${e}`;
}
export function treeName(i) {
  const fr = DATA.meta.names[DATA.name[i]];
  return fr || DATA.spp[DATA.species[i]].fr || DATA.genera[DATA.genus[i]];
}
export const treeLatin = (i) => speciesLatin(DATA.species[i]);
export const speciesLabelFr = (si) => DATA.spp[si].fr || "";
export const addressOf = (i) => DATA.meta.addresses[DATA.addr[i]] || "";
export const complementOf = (i) => DATA.meta.complements[DATA.comp[i]] || "";
export const cultivarOf = (i) => DATA.meta.cultivars[DATA.cultivar[i]] || "";

/** Global dataset handle, set once by main.js (helpers above read from it). */
export let DATA = null;
export const setData = (d) => { DATA = d; };
