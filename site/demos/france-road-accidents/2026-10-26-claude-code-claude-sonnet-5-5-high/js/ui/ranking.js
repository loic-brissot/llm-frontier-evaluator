// Départements tab: ranking by accident rate / fatality rate / severity / count; also drives the map choropleth.
import { h, fmt, pct, tooltip } from '../util.js';
import { THEME } from '../theme.js';

const METRICS = {
  rate: { label: 'Accident rate', unit: 'accidents per 100,000 residents per year', fmt: (v) => fmt(v) },
  killed: { label: 'Fatality rate', unit: 'people killed per 100,000 residents per year', fmt: (v) => v.toFixed(1) },
  severe: { label: 'Severity', unit: 'share of accidents ending in death or hospitalisation', fmt: (v) => pct(v, 0) },
  count: { label: 'Count', unit: 'accidents', fmt: (v) => fmt(v) },
};

export function Ranking({ engine, meta, onFocus, onHover, onMetric }) {
  let metric = 'rate';
  const deps = meta.deps;
  const rows = deps.map((d, i) => {
    const bar = h('i'), val = h('span', { class: 'dv' }), rank = h('span', { class: 'dr' });
    const el = h('button', { type: 'button', class: 'drow', onclick: () => onFocus(i), onpointerenter: () => onHover(i), onpointerleave: () => onHover(null) },
      rank, h('span', { class: 'dn' }, d.name, h('em', d.code)), h('span', { class: 'dt' }, bar), val);
    tooltip(el, () => tip(i));
    return { el, bar, val, rank, i };
  });
  let last = null;
  const tip = (i) => {
    if (!last) return '';
    const d = deps[i], R = engine.R, n = R.dep.n[i], yrs = engine.counts.year || 3;
    return `<div class="tt-h">${d.name} <span class="tt-dim">(${d.code}) · ${d.region}</span></div>` +
      `<div class="tt-r"><b>${fmt(n)}</b> accidents · <b>${fmt(R.dep.killed[i])}</b> killed</div>` +
      `<div class="tt-r">${fmt(n / (d.pop / 1e5) / yrs)} accidents / 100k residents / yr</div>` +
      `<div class="tt-r">${n ? pct(R.dep.severe[i] / n, 0) : '—'} killed or hospitalised</div><div class="tt-r tt-dim">Population ${fmt(d.pop)} · click to zoom and filter</div>`;
  };
  const list = h('div', { class: 'dlist' }, rows.map((r) => r.el));
  const legendBar = h('i', { class: 'rl-scale', style: { background: `linear-gradient(90deg, ${THEME.choro[0]}, ${THEME.choro[1]}, ${THEME.choro[2]})` } });
  const lo = h('span'), hi = h('span'), unit = h('p', { class: 'fnote' });
  const seg = h('div', { class: 'seg wrap', role: 'radiogroup', 'aria-label': 'Ranking measure' },
    ...Object.entries(METRICS).map(([k, m]) => h('button', { type: 'button', role: 'radio', 'aria-checked': k === metric, 'data-v': k,
      onclick: () => { metric = k; seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', b.dataset.v === k)); onMetric(); api.update(engine.R); } }, m.label)));
  const el = h('div', { class: 'ranking' },
    h('section', { class: 'card' }, h('header', { class: 'card-h' }, h('div', h('p', { class: 'eyebrow' }, 'Geography'), h('h3', 'Départements'))), seg, unit,
      h('div', { class: 'dleg' }, lo, legendBar, hi)),
    h('section', { class: 'card flush' }, list));

  const api = {
    el,
    /** normalised 0..1 per département for the map shading */
    shades: new Float32Array(deps.length),
    update(R) {
      last = R;
      const yrs = engine.counts.year || 3, M = METRICS[metric], vals = deps.map((d, i) => {
        const n = R.dep.n[i];
        switch (metric) {
          case 'rate': return n / (d.pop / 1e5) / yrs;
          case 'killed': return R.dep.killed[i] / (d.pop / 1e5) / yrs;
          case 'severe': return n >= 30 ? R.dep.severe[i] / n : null;
          default: return n;
        }
      });
      const order = rows.map((r) => r.i).sort((a, b) => (vals[b] ?? -1) - (vals[a] ?? -1));
      const valid = vals.filter((v) => v != null).sort((a, b) => a - b);
      const vmin = valid[0] ?? 0, vmax = valid[valid.length - 1] || 1, p95 = valid[Math.floor(valid.length * 0.95)] ?? vmax;
      order.forEach((i, k) => {
        const r = rows[i], v = vals[i];
        r.el.style.order = k;
        r.rank.textContent = v == null ? '' : k + 1;
        r.val.textContent = v == null ? '–' : M.fmt(v);
        r.bar.style.width = v == null ? '0%' : (v / vmax) * 100 + '%';
        r.el.classList.toggle('on', engine.has('dep', i));
        api.shades[i] = v == null ? 0 : Math.min(1, Math.max(0, (v - vmin) / ((p95 - vmin) || 1)));
      });
      lo.textContent = M.fmt(vmin); hi.textContent = M.fmt(p95) + '+';
      unit.textContent = `Shading on the map: ${M.unit}. Population from INSEE via geo.api.gouv.fr.`;
    },
  };
  return api;
}
