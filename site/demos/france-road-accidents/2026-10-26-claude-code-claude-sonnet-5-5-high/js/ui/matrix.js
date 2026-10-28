// "Who hits whom": victims (rows) × opposing party (columns). Bubble area = people hurt, colour = share severe.
import { h, s, fmt, pct, tooltip } from '../util.js';
import { ramp } from '../theme.js';
import { MODE_ICON, OPP_ICON, iconBody, icon } from '../icons.js';
import { NMODE, NOPP, cellOf } from '../engine.js';

const CW = 28, CH = 34, LW = 114, GAP = 9, HEAD = 56, TOP = 14;
const SHORT = ['Ped.', 'Bike', 'E-sc.', 'Moto', 'Car', 'Van', 'Truck', 'Other', 'Anim.', 'Obst.', 'Alone'];
const ROWNAME = ['Pedestrian', 'Bicycle', 'E-scooter', 'Moped / moto', 'Car', 'Van', 'Heavy vehicle', 'Other vehicle'];
const SHRINK = 20, FATAL_MAX = 0.12;
const W = LW + NOPP * CW + GAP + 4, H = TOP + HEAD + NMODE * CH + 4;
const cx = (j) => LW + j * CW + (j >= 8 ? GAP : 0) + CW / 2;
const cy = (i) => TOP + HEAD + i * CH + CH / 2;
const svgIcon = (name, x, y, size, cls, color) => s('svg', { x, y, width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color || 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: cls, html: iconBody(name) });

export const MODE_NAMES = ROWNAME;
export const pairName = (meta, c) => ({ victim: ROWNAME[Math.floor(c / NOPP)], opp: meta.opps[c % NOPP].label });

export function Matrix({ engine, meta, theme, onChange }) {
  const svg = s('svg', { class: 'mx', viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': 'Collision matrix: victim mode by opposing party' });
  let metric = 'row';

  // ---- static skeleton ---------------------------------------------------------------------
  svg.append(s('text', { class: 'axis', x: LW, y: 9 }, 'OPPOSING PARTY'), s('text', { class: 'axis', x: 0, y: TOP + HEAD - 6 }, 'VICTIM'));
  const colHeads = [], rowHeads = [], cells = [], guides = [];
  for (let j = 0; j < NOPP; j++) {
    const g = s('g', { class: 'colhead', tabindex: 0, role: 'button', 'aria-label': `Select every victim facing: ${meta.opps[j].label}` },
      s('rect', { x: cx(j) - CW / 2 + 1, y: TOP, width: CW - 2, height: HEAD - 4, rx: 6 }),
      svgIcon(OPP_ICON[j], cx(j) - 9, TOP + 6, 18),
      s('text', { class: 'cl', x: cx(j), y: TOP + 38, 'text-anchor': 'middle' }, SHORT[j]));
    g.addEventListener('click', () => selectLine('col', j));
    g.addEventListener('keydown', (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), selectLine('col', j)));
    tooltip(g, () => `<div class="tt-h">${meta.opps[j].label}</div><div class="tt-r tt-dim">Click to select every victim type facing this opponent</div>`);
    svg.append(g); colHeads.push(g);
  }
  for (let i = 0; i < NMODE; i++) {
    const band = s('rect', { class: 'band', x: 0, y: cy(i) - CH / 2, width: W, height: CH, rx: 6 });
    guides.push(band); svg.append(band);
  }
  for (let i = 0; i < NMODE; i++) {
    const cntT = s('text', { class: 'rc', x: 24, y: cy(i) + 11 });
    const g = s('g', { class: 'rowhead', tabindex: 0, role: 'button', 'aria-label': `Select all ${ROWNAME[i]} victims` },
      s('rect', { x: 0, y: cy(i) - CH / 2 + 1, width: LW - 4, height: CH - 2, rx: 6 }),
      svgIcon(MODE_ICON[i], 1, cy(i) - 8, 16, 'ri', theme.mode[i]),
      s('text', { class: 'rn', x: 24, y: cy(i) - 2 }, ROWNAME[i]), cntT);
    g.addEventListener('click', () => selectLine('row', i));
    g.addEventListener('keydown', (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), selectLine('row', i)));
    tooltip(g, () => `<div class="tt-h">${ROWNAME[i]}</div><div class="tt-r tt-dim">Click to select this victim type against every opponent</div>`);
    svg.append(g); rowHeads.push({ g, cntT });
  }
  for (let i = 0; i < NMODE; i++) {
    for (let j = 0; j < NOPP; j++) {
      const c = cellOf(i, j);
      const circle = s('circle', { class: 'bub', cx: cx(j), cy: cy(i), r: 0 });
      const ring = s('circle', { class: 'selring', cx: cx(j), cy: cy(i), r: 0 });
      const hit = s('rect', { class: 'hit', x: cx(j) - CW / 2 + 1, y: cy(i) - CH / 2 + 1, width: CW - 2, height: CH - 2, rx: 5 });
      const g = s('g', { class: 'cell', tabindex: 0, role: 'button', 'aria-pressed': 'false' }, hit, circle, ring);
      g.addEventListener('click', () => { engine.togglePair(c); onChange(); });
      g.addEventListener('keydown', (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), engine.togglePair(c), onChange()));
      g.addEventListener('pointerenter', () => hover(i, j));
      g.addEventListener('pointerleave', () => hover(null, null));
      g.addEventListener('focus', () => hover(i, j));
      g.addEventListener('blur', () => hover(null, null));
      tooltip(g, () => cellTip(i, j));
      svg.append(g); cells.push({ g, circle, ring, c, i, j });
    }
  }

  function selectLine(kind, k) {
    const set = [];
    for (let i = 0; i < NMODE; i++) for (let j = 0; j < NOPP; j++) if ((kind === 'row' ? i : j) === k) set.push(cellOf(i, j));
    const all = set.every((c) => engine.pairMask[c]);
    for (const c of set) if (!!engine.pairMask[c] === all) engine.togglePair(c);
    onChange();
  }
  function hover(i, j) {
    guides.forEach((b, k) => b.classList.toggle('on', k === i));
    cells.forEach((c) => c.g.classList.toggle('xhair', i != null && (c.i === i || c.j === j)));
    colHeads.forEach((g, k) => g.classList.toggle('on', k === j));
    rowHeads.forEach((r, k) => r.g.classList.toggle('on', k === i));
    caption(i, j);
  }

  // ---- numbers ---------------------------------------------------------------------------------
  const stats = (R, i, j) => {
    const c = cellOf(i, j), sv = R.cell.sev;
    return { n: R.cell.n[c], slight: sv[c * 4 + 1], hosp: sv[c * 4 + 2], killed: sv[c * 4 + 3] };
  };
  function cellTip(i, j) {
    const st = stats(engine.R, i, j), name = pairName(meta, cellOf(i, j)), sel = engine.pairMask[cellOf(i, j)];
    if (!st.n) return `<div class="tt-h">${name.victim} × ${name.opp}</div><div class="tt-r tt-dim">No victims with the current filters</div>`;
    return `<div class="tt-h">${name.victim} × ${name.opp}</div>` +
      `<div class="tt-r"><b>${fmt(st.n)}</b> people hurt or killed · ${pct(st.n / (rowOf(i) || 1), 0)} of all ${ROWNAME[i].toLowerCase()} victims</div>` +
      `<div class="tt-r"><i class="sw" style="background:${theme.sev[3]}"></i>${fmt(st.killed)} killed (${pct(st.killed / st.n)})</div>` +
      `<div class="tt-r"><i class="sw" style="background:${theme.sev[2]}"></i>${fmt(st.hosp)} hospitalised (${pct(st.hosp / st.n)})</div>` +
      `<div class="tt-r"><i class="sw" style="background:${theme.sev[1]}"></i>${fmt(st.slight)} slightly injured</div>` +
      `<div class="tt-r tt-dim">${sel ? 'Click to remove from the selection' : 'Click to filter the map and every chart'}</div>`;
  }

  const rowOf = (i) => { let t = 0; for (let j = 0; j < NOPP; j++) t += engine.R.cell.n[cellOf(i, j)]; return t; };
  const capEl = h('p', { class: 'mx-cap' });
  let defaultCaption = '';
  const caption = (i, j) => {
    if (i == null) { capEl.innerHTML = defaultCaption; return; }
    const st = stats(engine.R, i, j), name = pairName(meta, cellOf(i, j));
    capEl.innerHTML = st.n
      ? `<b>${name.victim}</b> × <b>${name.opp}</b> — ${fmt(st.n)} people hurt, <span class="k">${fmt(st.killed)} killed</span> (${pct(st.killed / st.n)}), ${fmt(st.hosp)} hospitalised`
      : `<b>${name.victim}</b> × <b>${name.opp}</b> — none with the current filters`;
  };

  const tableEl = h('div', { class: 'mx-table', hidden: true });
  function buildTable(R) {
    const m = metric === 'killed', rowTot = ROWNAME.map((_, i) => Array.from({ length: NOPP }, (__, j) => stats(R, i, j).n).reduce((a, b) => a + b, 0));
    tableEl.replaceChildren(h('table', { 'aria-label': 'Collision matrix as a table' },
      h('thead', h('tr', h('th', 'Victim ↓ · Opponent →'), SHORT.map((t, j) => h('th', { title: meta.opps[j].label }, t)))),
      h('tbody', ROWNAME.map((r, i) => h('tr', h('th', r), Array.from({ length: NOPP }, (_, j) => {
        const st = stats(R, i, j), c = cellOf(i, j);
        return h('td', { class: engine.pairMask[c] ? 'on' : '', onclick: () => { engine.togglePair(c); onChange(); }, title: `${fmt(st.n)} hurt · ${fmt(st.killed)} killed` }, st.n ? (metric === 'row' ? pct(st.n / rowTot[i], 0) : fmt(m ? st.killed : st.n)) : '·');
      }))))));
  }

  const metricValue = (st, tot) => (metric === 'killed' ? st.killed : metric === 'row' ? (tot ? st.n / tot : 0) : st.n);
  function render(R) {
    let vmax = 1e-9, sumN = 0, sumK = 0;
    const rowTot = new Array(NMODE).fill(0);
    for (let i = 0; i < NMODE; i++) for (let j = 0; j < NOPP; j++) rowTot[i] += stats(R, i, j).n;
    for (let i = 0; i < NMODE; i++) for (let j = 0; j < NOPP; j++) {
      const st = stats(R, i, j);
      vmax = Math.max(vmax, metricValue(st, rowTot[i])); sumN += st.n; sumK += st.killed;
    }
    legendArea.textContent = metric === 'killed' ? 'Area = people killed' : metric === 'row' ? 'Area = share of that victim type’s injuries' : 'Area = people hurt or killed';
    const p0 = sumN ? sumK / sumN : 0; // cells with few victims are shrunk toward the overall rate so noise does not paint them red
    const any = engine.pairCount > 0;
    for (const c of cells) {
      const st = stats(R, c.i, c.j), v = metricValue(st, rowTot[c.i]), sh = st.n ? (st.killed + SHRINK * p0) / (st.n + SHRINK) : 0;
      const r = v > 0 ? Math.max(1.8, Math.sqrt(v / vmax) * (CW / 2 - 1.6)) : 0;
      c.circle.style.r = r + 'px';
      c.circle.style.fill = v > 0 ? ramp(sh / FATAL_MAX) : 'transparent';
      const on = !!engine.pairMask[c.c];
      c.ring.style.r = on ? r + 2.6 + 'px' : '0px';
      c.g.classList.toggle('on', on); c.g.classList.toggle('dim', any && !on); c.g.classList.toggle('empty', !st.n); c.g.classList.toggle('thin', metric === 'row' && rowTot[c.i] < 8);
      c.g.setAttribute('aria-pressed', on);
      const nm = pairName(meta, c.c);
      c.g.setAttribute('aria-label', `${nm.victim} × ${nm.opp}: ${fmt(st.n)} victims, ${fmt(st.killed)} killed`);
    }
    rowHeads.forEach((r, i) => { r.cntT.textContent = rowTot[i] ? `${fmt(rowTot[i])} hurt` : '—'; r.g.classList.toggle('zero', !rowTot[i]); });
    // insight line
    let big = null, lethal = null;
    const minN = Math.max(30, Math.round(R.victims * 0.0006 / 10) * 10);
    for (let i = 0; i < NMODE; i++) for (let j = 0; j < NOPP; j++) {
      const st = stats(R, i, j);
      if (!big || st.n > big.st.n) big = { i, j, st };
      if (st.n >= minN && (!lethal || st.killed / st.n > lethal.st.killed / lethal.st.n)) lethal = { i, j, st };
    }
    const nm = (o) => pairName(meta, cellOf(o.i, o.j));
    defaultCaption = big && big.st.n
      ? `Most frequent: <b>${nm(big).victim} × ${nm(big).opp}</b> (${fmt(big.st.n)}).` + (lethal && lethal.st.killed ? ` Deadliest (≥${fmt(minN)} victims): <b>${nm(lethal).victim} × ${nm(lethal).opp}</b>, <span class="k">${pct(lethal.st.killed / lethal.st.n)} killed</span>.` : '')
      : 'No accidents match the current filters.';
    if (!capEl.dataset.hover) capEl.innerHTML = defaultCaption;
    if (!tableEl.hidden) buildTable(R);
  }

  // ---- card chrome -------------------------------------------------------------------------------
  const seg = h('div', { class: 'seg small', role: 'radiogroup', 'aria-label': 'Matrix measure' },
    ...[['row', 'By row'], ['victims', 'Hurt'], ['killed', 'Killed']].map(([v, l]) => h('button', { type: 'button', role: 'radio', 'aria-checked': v === metric, 'data-v': v,
      onclick: () => { metric = v; seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', b.dataset.v === v)); render(engine.R); } }, l)));
  const tableBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Show as table', 'aria-label': 'Toggle table view', html: icon('table', 16),
    onclick: () => { tableEl.hidden = !tableEl.hidden; svg.toggleAttribute('hidden', !tableEl.hidden); tableBtn.setAttribute('aria-pressed', !tableEl.hidden); if (!tableEl.hidden) buildTable(engine.R); } });
  const clearBtn = h('button', { class: 'link', type: 'button', hidden: true, onclick: () => { engine.setPairs([]); onChange(); } }, 'Clear selection');
  const legendArea = h('span', 'Area = share of that victim type’s injuries');
  const ramps = `linear-gradient(90deg, ${ramp(0)}, ${ramp(0.5)}, ${ramp(1)})`;
  const legend = h('div', { class: 'mx-legend' },
    legendArea,
    h('span', { class: 'mx-l2' }, h('span', 'Colour = share of victims killed'), h('i', { class: 'rl-scale', style: { background: ramps } }), h('span', '0 → 12%+')));
  svg.addEventListener('pointermove', () => { capEl.dataset.hover = '1'; });
  svg.addEventListener('pointerleave', () => { delete capEl.dataset.hover; capEl.innerHTML = defaultCaption; });

  const el = h('section', { class: 'card matrix' },
    h('header', { class: 'card-h' }, h('div', h('p', { class: 'eyebrow' }, 'Who hits whom'), h('h2', 'Collision matrix')), h('span', { class: 'grow' }), seg, tableBtn),
    h('p', { class: 'lede' }, 'Rows are who got hurt, columns are what they collided with. Bubbles show where each victim type’s injuries come from; colour shows how often they end in death. ', h('b', 'Click cells'), ' to filter the map and every chart.'),
    h('div', { class: 'mx-wrap' }, svg, tableEl), capEl, h('div', { class: 'mx-foot' }, legend, clearBtn));

  return { el, update(R) { render(R); clearBtn.hidden = !engine.pairCount; } };
}
