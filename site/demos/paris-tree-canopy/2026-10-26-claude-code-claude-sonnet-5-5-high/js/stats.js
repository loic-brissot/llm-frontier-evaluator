// Aggregations over a filter mask. Histogram counting keeps every median exact and every pass O(n).
import { DATA } from "./data.js";
import { histStats } from "./format.js";

const isTaxon = (si) => DATA.spp[si].epithet !== "sp." && DATA.spp[si].epithet !== "n. sp.";

export function diversity(speciesCounts) {
  let total = 0, richness = 0;
  for (let s = 0; s < speciesCounts.length; s++) {
    if (speciesCounts[s] && isTaxon(s)) { total += speciesCounts[s]; richness++; }
  }
  let H = 0;
  for (let s = 0; s < speciesCounts.length; s++) {
    const c = speciesCounts[s];
    if (c && isTaxon(s)) { const p = c / total; H -= p * Math.log(p); }
  }
  return { richness, shannon: H, effective: Math.exp(H), evenness: richness > 1 ? H / Math.log(richness) : 0 };
}

export function computeStats(mask) {
  const D = DATA, n = D.n;
  const S = {
    count: 0, remarkable: 0,
    genusCount: new Uint32Array(D.genera.length),
    speciesCount: new Uint32Array(D.spp.length),
    hHist: new Uint32Array(61), cHist: new Uint32Array(1001),
    stage: new Uint32Array(5), group: new Uint32Array(5), arr: new Uint32Array(23),
  };
  for (let i = 0; i < n; i++) {
    if (!mask[i]) continue;
    S.count++;
    S.genusCount[D.genus[i]]++;
    S.speciesCount[D.species[i]]++;
    S.hHist[D.height[i]]++;
    S.cHist[D.circ[i]]++;
    S.stage[D.stage[i]]++;
    S.group[D.group[i]]++;
    S.arr[D.arr[i]]++;
    if (D.flag[i]) S.remarkable++;
  }
  S.height = histStats(S.hHist);
  S.girth = histStats(S.cHist);
  S.div = diversity(S.speciesCount);
  S.genera = S.genusCount.reduce((a, c) => a + (c ? 1 : 0), 0);
  return S;
}

/** Sorted [index, count] pairs, descending. */
export function ranked(counts, limit = Infinity) {
  const out = [];
  for (let i = 0; i < counts.length; i++) if (counts[i]) out.push([i, counts[i]]);
  out.sort((a, b) => b[1] - a[1]);
  return out.slice(0, limit);
}

/** Per-arrondissement statistics (arr 0..22) from a mask that ignores the arrondissement filter. */
export function districtStats(mask) {
  const D = DATA, A = 23, SP = D.spp.length;
  const rows = Array.from({ length: A }, (_, a) => ({
    arr: a, n: 0, group: new Uint32Array(5), remarkable: 0,
    sp: new Uint32Array(SP),                 // species counts (all trees)
    spStreet: new Uint32Array(SP), spPark: new Uint32Array(SP),
    genus: new Uint32Array(D.genera.length),
    hHist: new Uint32Array(61), cHist: new Uint32Array(1001),
  }));
  for (let i = 0; i < D.n; i++) {
    if (!mask[i]) continue;
    const r = rows[D.arr[i]], g = D.group[i], s = D.species[i];
    r.n++; r.group[g]++; r.sp[s]++; r.genus[D.genus[i]]++;
    if (g === 0) r.spStreet[s]++; else if (g === 1) r.spPark[s]++;
    r.hHist[D.height[i]]++; r.cHist[D.circ[i]]++;
    if (D.flag[i]) r.remarkable++;
  }
  const features = D.arrGeo.features;
  for (const r of rows) {
    r.div = diversity(r.sp);
    r.divStreet = diversity(r.spStreet);
    r.divPark = diversity(r.spPark);
    r.height = histStats(r.hHist);
    r.girth = histStats(r.cHist);
    r.topGenera = ranked(r.genus, 3);
    if (r.arr < 20) {
      const f = features[r.arr];
      r.ha = D.arrHa[r.arr];
      r.official = f.properties.name;
      r.density = r.n / r.ha;
      r.streetDensity = r.group[0] / r.ha;
    }
  }
  return rows;
}
