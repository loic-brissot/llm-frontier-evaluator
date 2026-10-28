// Loads the columnar binaries produced by pipeline/build_data.py

const CTORS = { f4: Float32Array, u1: Uint8Array, u2: Uint16Array, u4: Uint32Array, i8: BigInt64Array };

async function inflate(url, onBytes) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  let stream = res.body;
  if (onBytes) {
    let seen = 0;
    stream = stream.pipeThrough(new TransformStream({
      transform(chunk, ctl) { seen += chunk.byteLength; onBytes(seen); ctl.enqueue(chunk); },
    }));
  }
  return new Response(stream.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
}

function parsePack(buf) {
  const hl = new DataView(buf).getUint32(0, true);
  const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl)));
  let base = 4 + hl;
  base += (8 - (base % 8)) % 8;
  const out = {};
  for (const [k, v] of Object.entries(head)) out[k] = new CTORS[v.t](buf, base + v.o, v.n);
  return out;
}

/** Fetches everything needed for the first interactive frame. `progress(0..1, label)` is optional. */
export async function loadData(base, progress = () => {}) {
  const parts = { meta: 0, acc: 0, rel: 0, geo: 0 };
  const sizes = { meta: 0.5e6, acc: 3.25e6, rel: 2.75e6, geo: 2.4e6 };
  const report = (k) => (n) => {
    parts[k] = Math.min(n, sizes[k]);
    const tot = Object.values(sizes).reduce((a, b) => a + b, 0);
    progress(Object.values(parts).reduce((a, b) => a + b, 0) / tot);
  };
  const json = async (u, k) => {
    const r = await fetch(u); const t = await r.text(); report(k)(sizes[k]); return JSON.parse(t);
  };
  const [meta, acc, rel, deps, mask] = await Promise.all([
    json(`${base}/meta.json`, 'meta'),
    inflate(`${base}/accidents.bin.gz`, report('acc')).then(parsePack),
    inflate(`${base}/relations.bin.gz`, report('rel')).then(parsePack),
    json(`${base}/departements.geojson`, 'geo'),
    fetch(`${base}/mask.geojson`).then((r) => r.json()),
  ]);
  return { meta, acc, rel, deps, mask };
}

let textPromise = null;
/** Address / road-name sidecar, loaded lazily; resolves to a function (accidentIndex) -> {adr, voie, others}. */
export function loadText(base) {
  if (!textPromise) {
    textPromise = inflate(`${base}/text.tsv.gz`).then((buf) => {
      const lines = new TextDecoder().decode(buf).split('\n');
      return (i) => {
        const [adr = '', voie = '', oth = ''] = (lines[i] || '').split('\t');
        return { adr, voie, others: oth ? JSON.parse(oth) : [] };
      };
    });
  }
  return textPromise;
}

/** Web-mercator (0..1) with a hi/lo float32 split so street-level zooms stay sub-pixel accurate on the GPU. */
export function mercatorColumns(lon, lat) {
  const n = lon.length;
  const hi = new Float32Array(n * 2), lo = new Float32Array(n * 2);
  const mx = new Float64Array(n), my = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const x = (lon[i] + 180) / 360;
    const s = Math.sin((lat[i] * Math.PI) / 180);
    const y = 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
    mx[i] = x; my[i] = y;
    hi[2 * i] = x; hi[2 * i + 1] = y;
    lo[2 * i] = x - hi[2 * i]; lo[2 * i + 1] = y - hi[2 * i + 1];
  }
  return { hi, lo, mx, my };
}

/** Uniform grid over mercator space for fast radius queries. */
export class PointGrid {
  constructor(mx, my, cell = 1 / 16384) {
    this.mx = mx; this.my = my; this.cell = cell;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i < mx.length; i++) {
      if (mx[i] < x0) x0 = mx[i]; if (mx[i] > x1) x1 = mx[i];
      if (my[i] < y0) y0 = my[i]; if (my[i] > y1) y1 = my[i];
    }
    this.x0 = x0; this.y0 = y0;
    this.w = Math.floor((x1 - x0) / cell) + 1; this.h = Math.floor((y1 - y0) / cell) + 1;
    const n = mx.length, cellOf = new Uint32Array(n);
    const start = new Uint32Array(this.w * this.h + 1);
    for (let i = 0; i < n; i++) {
      const c = Math.floor((my[i] - y0) / cell) * this.w + Math.floor((mx[i] - x0) / cell);
      cellOf[i] = c; start[c + 1]++;
    }
    for (let c = 0; c < start.length - 1; c++) start[c + 1] += start[c];
    const fill = start.slice(0, -1), items = new Uint32Array(n);
    for (let i = 0; i < n; i++) items[fill[cellOf[i]]++] = i;
    this.start = start; this.items = items;
  }

  /** Indices within `r` (mercator units) of (x, y) for which accept(i) is true. */
  query(x, y, r, accept) {
    const { cell, w, h, x0, y0, start, items, mx, my } = this;
    const cx0 = Math.max(0, Math.floor((x - r - x0) / cell)), cx1 = Math.min(w - 1, Math.floor((x + r - x0) / cell));
    const cy0 = Math.max(0, Math.floor((y - r - y0) / cell)), cy1 = Math.min(h - 1, Math.floor((y + r - y0) / cell));
    const out = [], r2 = r * r;
    for (let cy = cy0; cy <= cy1; cy++) {
      for (let cx = cx0; cx <= cx1; cx++) {
        const c = cy * w + cx;
        for (let k = start[c]; k < start[c + 1]; k++) {
          const i = items[k], dx = mx[i] - x, dy = my[i] - y;
          const d2 = dx * dx + dy * dy;
          if (d2 <= r2 && accept(i)) out.push(i, d2);
        }
      }
    }
    return out; // flat [index, dist², index, dist², …]
  }
}
