// Filter state + the filtered index. Every view reads from `view.idx` / `view.mask`.
import { DATA } from "./data.js";

export const filters = {
  arr: new Set(),      // 0..22 (0-19 = arrondissements, 20/21 = bois, 22 = outside Paris)
  genus: new Set(),    // genus indices
  species: new Set(),  // species indices
  group: new Set(),    // 0 street, 1 parks, 2 cemeteries, 3 facilities, 4 périphérique
  stage: new Set(),    // 0..4
  height: null,        // [lo, hi] in metres, or null
  girth: null,         // [lo, hi] in cm, or null
  remarkable: false,
};

export const view = {
  mask: null,   // Uint8Array(n): 1 when the tree passes every filter
  idx: null,    // Uint32Array of passing rows
  count: 0,
  active: false,
};

const listeners = new Set();
export const onFilterChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };

let queued = false;
export function setFilters(patch) {
  for (const [k, v] of Object.entries(patch)) filters[k] = v;
  if (queued) return;
  queued = true;
  queueMicrotask(() => { queued = false; refresh(); });
}

export function toggleIn(set, v) {
  const next = new Set(set);
  next.has(v) ? next.delete(v) : next.add(v);
  return next;
}

export function activeCount() {
  let c = 0;
  c += filters.arr.size ? 1 : 0;
  c += filters.genus.size || filters.species.size ? 1 : 0;
  c += filters.group.size ? 1 : 0;
  c += filters.stage.size ? 1 : 0;
  c += filters.height ? 1 : 0;
  c += filters.girth ? 1 : 0;
  c += filters.remarkable ? 1 : 0;
  return c;
}

export function resetFilters() {
  setFilters({
    arr: new Set(), genus: new Set(), species: new Set(), group: new Set(), stage: new Set(),
    height: null, girth: null, remarkable: false,
  });
}

/** Compute the mask for a filter set. `skip` lists filter keys to ignore (e.g. ["arr"] for district comparison). */
export function computeMask(f, skip = []) {
  const D = DATA, n = D.n;
  const use = (k) => !skip.includes(k);
  const lut = (set, size) => {
    if (!set.size) return null;
    const t = new Uint8Array(size);
    for (const v of set) t[v] = 1;
    return t;
  };
  const arrOK = use("arr") ? lut(f.arr, 23) : null;
  const groupOK = use("group") ? lut(f.group, 5) : null;
  const stageOK = use("stage") ? lut(f.stage, 5) : null;
  let taxOK = null;
  if (use("taxa") && (f.genus.size || f.species.size)) {
    taxOK = new Uint8Array(D.spp.length);
    for (let s = 0; s < taxOK.length; s++) taxOK[s] = f.genus.has(D.speciesGenus[s]) || f.species.has(s) ? 1 : 0;
  }
  const hr = use("height") ? f.height : null, cr = use("girth") ? f.girth : null;
  const rem = use("remarkable") && f.remarkable;

  const mask = new Uint8Array(n);
  let count = 0;
  for (let i = 0; i < n; i++) {
    if (arrOK && !arrOK[D.arr[i]]) continue;
    if (groupOK && !groupOK[D.group[i]]) continue;
    if (stageOK && !stageOK[D.stage[i]]) continue;
    if (taxOK && !taxOK[D.species[i]]) continue;
    if (hr) { const v = D.height[i]; if (!v || v < hr[0] || v > hr[1]) continue; }
    if (cr) { const v = D.circ[i]; if (!v || v < cr[0] || v > cr[1]) continue; }
    if (rem && !D.flag[i]) continue;
    mask[i] = 1;
    count++;
  }
  return { mask, count };
}

export function refresh() {
  const { mask, count } = computeMask(filters);
  const idx = new Uint32Array(count);
  for (let i = 0, k = 0; i < mask.length; i++) if (mask[i]) idx[k++] = i;
  view.mask = mask; view.idx = idx; view.count = count; view.active = activeCount() > 0;
  for (const fn of listeners) fn(view);
}
