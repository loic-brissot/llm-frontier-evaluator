// Filter widgets: click/drag histograms (hour, weekday, speed limit) and row-bar lists (lighting, weather, …).
// Each shows the accident count per bin *given every other active filter*, plus the share of severe outcomes as a colour ribbon.
import { h, fmt, pct, tooltip } from '../util.js';
import { ramp } from '../theme.js';

const FATAL_MAX = 0.14; // ribbon saturates at 14 % fatal accidents (national average ≈ 6 %)

export const sevShare = (hist, b) => {
  const n = hist[b * 4] + hist[b * 4 + 1] + hist[b * 4 + 2] + hist[b * 4 + 3];
  return { n, severe: n ? (hist[b * 4 + 2] + hist[b * 4 + 3]) / n : 0, killed: n ? hist[b * 4 + 3] / n : 0, k: hist[b * 4 + 3], hosp: hist[b * 4 + 2] };
};
const binTip = (title, s) => `<div class="tt-h">${title}</div><div class="tt-r"><b>${fmt(s.n)}</b> accidents</div>` +
  (s.n ? `<div class="tt-r"><b>${pct(s.killed)}</b> fatal (${fmt(s.k)} accidents)</div><div class="tt-r tt-dim">${pct(s.severe)} killed or hospitalised</div>` : '');

function block(title, sub, body, headExtra) {
  const clear = h('button.link', { type: 'button', hidden: true }, 'Clear');
  const el = h('section.fblock', h('header', h('h3', title), sub && h('span.sub', sub), h('span.grow'), headExtra, clear), body);
  return { el, clear };
}

/** Histogram with drag-to-select over `order` (array of bin indices shown left → right). */
export function Histogram({ engine, key, title, sub, order, labels, tickEvery = 1, tickLabels, height = 58, onChange, extra }) {
  const cols = order.map((bin, i) => {
    const bar = h('div.hbar'), rib = h('div.hrib');
    const col = h('button.hcol', { type: 'button', 'data-i': i, 'aria-pressed': 'false', 'aria-label': `${title}: ${labels[bin]}` }, h('div.hwrap', bar), rib);
    return { bin, bar, rib, col };
  });
  const track = h('div.hist', { style: { '--n': order.length, '--h': height + 'px' } }, cols.map((c) => c.col));
  const axis = h('div.haxis', { style: { '--n': order.length } }, order.map((bin, i) => h('span', i % tickEvery === 0 ? (tickLabels ? tickLabels[bin] : labels[bin]) : '')));
  const { el, clear } = block(title, sub, [track, axis], extra);
  clear.addEventListener('click', () => { engine.clear(key); onChange(); });

  // drag selection: first press decides whether the gesture selects or deselects
  let drag = null;
  const idxAt = (e) => { const t = document.elementFromPoint(e.clientX, e.clientY)?.closest('.hcol'); return t && track.contains(t) ? +t.dataset.i : null; };
  track.addEventListener('pointerdown', (e) => {
    const i = idxAt(e); if (i == null) return;
    track.setPointerCapture(e.pointerId);
    const snapshot = new Set(order.filter((b) => engine.has(key, b)));
    drag = { i0: i, add: !snapshot.has(order[i]), snapshot, moved: false };
    e.preventDefault();
  });
  track.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const i = idxAt(e); if (i == null) return;
    if (i !== drag.i0) drag.moved = true;
    const [a, b] = [Math.min(drag.i0, i), Math.max(drag.i0, i)], next = new Set(drag.snapshot);
    for (let k = a; k <= b; k++) drag.add ? next.add(order[k]) : next.delete(order[k]);
    engine.setValues(key, next); onChange(true);
  });
  const end = (e) => {
    if (!drag) return;
    if (!drag.moved) { // plain click
      const next = new Set(drag.snapshot); const bin = order[drag.i0];
      drag.add ? next.add(bin) : next.delete(bin); engine.setValues(key, next);
    }
    drag = null; onChange();
  };
  track.addEventListener('pointerup', end); track.addEventListener('pointercancel', end);
  track.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { const c = e.target.closest('.hcol'); if (c) { engine.toggle(key, order[+c.dataset.i]); onChange(); e.preventDefault(); } } });

  cols.forEach((c, i) => tooltip(c.col, () => binTip(labels[c.bin], sevShare(engine.R.hist[key], c.bin))));
  return {
    el,
    update(R) {
      const hist = R.hist[key], any = engine.counts[key] > 0;
      let max = 1;
      for (const c of cols) max = Math.max(max, sevShare(hist, c.bin).n);
      for (const c of cols) {
        const s = sevShare(hist, c.bin), on = engine.has(key, c.bin);
        c.bar.style.height = (s.n / max) * 100 + '%';
        c.rib.style.background = s.n >= 20 ? ramp(s.killed / FATAL_MAX) : 'transparent';
        c.col.classList.toggle('on', on); c.col.classList.toggle('dim', any && !on);
        c.col.setAttribute('aria-pressed', on);
      }
      clear.hidden = !any;
    },
  };
}

/** Horizontal bar list; click toggles (additive). */
export function RowBars({ engine, key, title, sub, order, labels, onChange, hint }) {
  const rows = order.map((bin) => {
    const fill = h('span.rfill'), val = h('span.rval'), rib = h('span.rrib');
    const btn = h('button.rbar', { type: 'button', 'aria-pressed': 'false' }, h('span.rlabel', labels[bin]), h('span.rtrack', fill), val, rib);
    btn.addEventListener('click', (e) => { engine.toggle(key, bin, e.altKey || e.metaKey ? true : false); onChange(); });
    return { bin, btn, fill, val, rib };
  });
  const list = h('div.rbars', rows.map((r) => r.btn));
  const { el, clear } = block(title, sub, list);
  if (hint) el.append(h('p.fnote', hint));
  clear.addEventListener('click', () => { engine.clear(key); onChange(); });
  rows.forEach((r) => tooltip(r.btn, () => binTip(labels[r.bin], sevShare(engine.R.hist[key], r.bin))));
  return {
    el,
    update(R) {
      const hist = R.hist[key], any = engine.counts[key] > 0;
      let max = 1;
      for (const r of rows) max = Math.max(max, sevShare(hist, r.bin).n);
      for (const r of rows) {
        const s = sevShare(hist, r.bin), on = engine.has(key, r.bin);
        r.fill.style.width = (s.n / max) * 100 + '%';
        r.val.textContent = fmt(s.n);
        r.rib.textContent = s.n >= 20 ? (s.killed * 100).toFixed(s.killed < 0.1 ? 1 : 0) + '%' : '–';
        r.rib.style.background = s.n >= 20 ? ramp(s.killed / FATAL_MAX) : 'transparent';
        r.btn.classList.toggle('on', on); r.btn.classList.toggle('dim', any && !on); r.btn.classList.toggle('zero', !s.n);
        r.btn.setAttribute('aria-pressed', on);
      }
      clear.hidden = !any;
    },
  };
}

export function buildFilters({ engine, meta, onChange }) {
  const L = meta.labels;
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const hourLabels = hours.map((i) => `${String(i).padStart(2, '0')}:00 – ${String(i).padStart(2, '0')}:59`);
  const hourTicks = hours.map((i) => (i % 6 === 0 ? `${i}h` : ''));

  const presets = h('div.presets',
    h('button.link', { type: 'button', onclick: () => { engine.setValues('hour', [22, 23, 0, 1, 2, 3, 4, 5]); onChange(); } }, 'Night'),
    h('button.link', { type: 'button', onclick: () => { engine.setValues('hour', [7, 8, 9, 16, 17, 18, 19]); onChange(); } }, 'Rush hours'));

  const widgets = [
    Histogram({ engine, key: 'hour', title: 'Hour of day', order: hours, labels: hourLabels, tickLabels: hourTicks, onChange, extra: presets }),
    Histogram({ engine, key: 'dow', title: 'Day of week', order: [0, 1, 2, 3, 4, 5, 6], labels: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'], tickLabels: L.dow, onChange, height: 44 }),
    RowBars({ engine, key: 'lum', title: 'Lighting', order: [1, 2, 5, 4, 3, 0], labels: L.lum, onChange }),
    RowBars({ engine, key: 'atm', title: 'Weather', order: [1, 8, 2, 3, 5, 4, 6, 7, 9, 0], labels: L.atm, onChange }),
    RowBars({ engine, key: 'road', title: 'Road category', order: [1, 2, 3, 5, 4, 6], labels: L.road, onChange }),
    Histogram({ engine, key: 'vma', title: 'Speed limit', sub: 'km/h', order: [1, 2, 3, 4, 5, 6, 7, 8, 0], labels: L.vma.map((v, i) => (i === 0 ? 'Unknown' : i === 8 ? 'Other limits (40, 45, 60, 100…)' : `${v} km/h`)), tickLabels: L.vma.map((v, i) => (i === 8 ? 'oth.' : i === 0 ? '?' : v.replace('≤ ', '≤'))), onChange, height: 50 }),
    RowBars({ engine, key: 'vosp', title: 'Cycling infrastructure', sub: 'on the road at the crash site', order: [2, 3, 4, 1, 0], labels: L.vosp, onChange }),
  ];
  const more = [
    RowBars({ engine, key: 'agg', title: 'Built-up area', order: [2, 1, 0], labels: L.agg, onChange }),
    RowBars({ engine, key: 'int', title: 'Junction', order: [1, 2, 3, 4, 5, 6, 7, 8, 9, 0], labels: L.int, onChange }),
    RowBars({ engine, key: 'surf', title: 'Road surface', order: [1, 2, 3, 7, 5, 4, 6, 8, 9, 0], labels: L.surf, onChange }),
  ];
  const moreBox = h('details.more', h('summary', 'More conditions'), more.map((w) => w.el));
  const legend = h('div.ribbon-legend',
    h('span', 'Colour = share of accidents that were fatal'),
    h('span.rl-scale', { style: { background: `linear-gradient(90deg, ${ramp(0)}, ${ramp(0.5)}, ${ramp(1)})` } }),
    h('span.rl-ends', h('i', '0%'), h('i', '14%+')));
  const root = h('div.filters', legend, widgets.map((w) => w.el), moreBox);
  const all = [...widgets, ...more];
  return { el: root, update: (R) => all.forEach((w) => w.update(R)) };
}
