// Overview tab: live totals, rates vs. France, severity split, victim ages and the top collision pairs.
import { h, fmt, fmtCompact, pct, tooltip, plural } from '../util.js';
import { MODE_ICON, OPP_ICON, icon } from '../icons.js';
import { NMODE, NOPP, AGE_BINS } from '../engine.js';
import { pairName, MODE_NAMES } from './matrix.js';

const HIST_DIMS = [['lum', 'Lighting'], ['atm', 'Weather'], ['road', 'Road'], ['vma', 'Speed limit'], ['vosp', 'Cycling infrastructure'], ['int', 'Junction'], ['surf', 'Surface'], ['agg', 'Area']];

const ageLabel = (b) => (b === AGE_BINS - 1 ? '85+' : `${b * 5}–${b * 5 + 4}`);

function versus(rate, base) {
  if (!isFinite(rate) || !base) return '';
  const r = rate / base;
  if (r > 0.95 && r < 1.05) return `<span class="vs eq">≈ France</span>`;
  return `<span class="vs ${r > 1 ? 'up' : 'down'}">${r > 1 ? '▲' : '▼'} ${r >= 10 ? r.toFixed(0) : r.toFixed(1)}× France</span>`;
}

/** Descriptive, auto-generated observations about whatever is currently selected. */
function insights(R, engine, meta) {
  const out = [], total = R.total, fatal = R.sevAcc[3] / (total || 1);
  if (total < 300) return [];
  // 1. which victim type is over-represented among the dead
  const vic = new Array(8).fill(0), kil = new Array(8).fill(0);
  for (let c = 0; c < NMODE * NOPP; c++) { const m = Math.floor(c / NOPP); vic[m] += R.selCell.n[c]; kil[m] += R.selCell.sev[c * 4 + 3]; }
  const tv = vic.reduce((a, b) => a + b, 0), tk = kil.reduce((a, b) => a + b, 0);
  if (tk >= 30) {
    let best = -1, ratio = 1.3;
    for (let m = 0; m < 8; m++) if (vic[m] >= 100 && kil[m] >= 10 && kil[m] / tk / (vic[m] / tv) > ratio) { ratio = kil[m] / tk / (vic[m] / tv); best = m; }
    if (best >= 0) out.push(['Victims', `<b>${MODE_NAMES[best]}</b> make up ${pct(vic[best] / tv, 0)} of the people hurt but ${pct(kil[best] / tk, 0)} of those killed.`]);
  }
  // 2. deadliest hour
  const hh = R.hist.hour; let bh = -1, bs = 0;
  for (let hr = 0; hr < 24; hr++) { const n = hh[hr * 4] + hh[hr * 4 + 1] + hh[hr * 4 + 2] + hh[hr * 4 + 3]; const s = hh[hr * 4 + 3] / (n || 1); if (n >= Math.max(120, total * 0.01) && s > bs) { bs = s; bh = hr; } }
  if (bh >= 0 && bs > fatal * 1.3) out.push(['When', `Fatal accidents peak around <b>${String(bh).padStart(2, '0')}:00</b> — ${pct(bs)} of accidents then, against ${pct(fatal)} overall.`]);
  // 3. condition with the highest fatal share
  let top = null;
  for (const [key, title] of HIST_DIMS) {
    const hs = R.hist[key], L = meta.labels[key];
    for (let b = 1; b < hs.length / 4; b++) {
      if (key === 'vma' && b === 8) continue;
      const n = hs[b * 4] + hs[b * 4 + 1] + hs[b * 4 + 2] + hs[b * 4 + 3];
      if (n < Math.max(200, total * 0.012) || /^(Not recorded|—|Other|Unknown)/.test(L[b] || '')) continue;
      const s = hs[b * 4 + 3] / n;
      if (!top || s > top.s) top = { s, n, label: key === 'vma' ? `${L[b]} km/h limit` : L[b], title };
    }
  }
  if (top && top.s > fatal * 1.4) out.push(['Where', `<b>${top.label}</b>: ${pct(top.s)} of ${fmt(top.n)} accidents are fatal — ${(top.s / fatal).toFixed(1)}× the ${pct(fatal)} average.`]);
  return out;
}

export function Summary({ engine, meta, theme, onSev, onPair }) {
  const heroN = h('div', { class: 'hero-n', 'aria-live': 'polite' }, '0'), heroSub = h('div', { class: 'hero-sub' }), scope = h('p', { class: 'eyebrow' }, 'Accidents');
  const kFatal = kpi('Fatal accidents', 'at least one death'), kHosp = kpi('Hospitalised', 'worst outcome: hospital stay'), kKilled = kpi('People killed', 'within 30 days of the accident');
  function kpi(label, sub) {
    const v = h('div', { class: 'kv' }), vs = h('div', { class: 'kvs' }), el = h('div', { class: 'kpi' }, h('div', { class: 'kl' }, label), v, vs, h('div', { class: 'ks' }, sub));
    return { el, v, vs };
  }

  // severity stack
  const segs = [3, 2, 1].map((sv) => {
    const b = h('button', { type: 'button', class: 'sseg', 'aria-label': theme.sevNames[sv], style: { background: theme.sev[sv] }, onclick: () => onSev(sv) });
    tooltip(b, () => { const R = engine.R, n = R.sevAcc[sv]; return `<div class="tt-h">${theme.sevNames[sv]}</div><div class="tt-r"><b>${fmt(n)}</b> accidents as worst outcome (${pct(n / (R.total || 1))})</div><div class="tt-r tt-dim">Click to filter</div>`; });
    return b;
  });
  const sbar = h('div', { class: 'sbar' }, segs);
  const sleg = h('div', { class: 'sleg' });
  const people = h('p', { class: 'people' });

  // ages
  let ageMode = 'count';
  const ageCols = Array.from({ length: AGE_BINS }, (_, b) => {
    const stack = [1, 2, 3].map((sv) => h('i', { class: 'a' + sv, style: { background: theme.sev[sv] } }));
    const el = h('div', { class: 'acol' }, h('div', { class: 'astack' }, stack), h('span', { class: 'ax' }, b % 4 === 0 ? (b === AGE_BINS - 1 ? '85+' : b * 5) : ''));
    tooltip(el, () => {
      const R = engine.R, a = R.age, n = a[b * 4 + 1] + a[b * 4 + 2] + a[b * 4 + 3];
      return `<div class="tt-h">${ageLabel(b)} years</div><div class="tt-r"><b>${fmt(n)}</b> people hurt or killed</div>` +
        (n ? `<div class="tt-r"><i class="sw" style="background:${theme.sev[3]}"></i>${fmt(a[b * 4 + 3])} killed (${pct(a[b * 4 + 3] / n)})</div><div class="tt-r"><i class="sw" style="background:${theme.sev[2]}"></i>${fmt(a[b * 4 + 2])} hospitalised</div><div class="tt-r"><i class="sw" style="background:${theme.sev[1]}"></i>${fmt(a[b * 4 + 1])} slightly injured</div>` : '');
    });
    return { el, stack };
  });
  const ageNote = h('p', { class: 'fnote' });
  const ageSeg = h('div', { class: 'seg small' }, ...[['count', 'Victims'], ['share', '% killed']].map(([v, l]) => h('button', { type: 'button', 'aria-checked': v === ageMode, 'data-v': v, role: 'radio',
    onclick: () => { ageMode = v; ageSeg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', b.dataset.v === v)); renderAge(engine.R); } }, l)));
  const ageChart = h('div', { class: 'ages' }, ageCols.map((c) => c.el));

  function renderAge(R) {
    const a = R.age, tot = [];
    let max = 1, nUnknown = a[AGE_BINS * 4 + 1] + a[AGE_BINS * 4 + 2] + a[AGE_BINS * 4 + 3];
    for (let b = 0; b < AGE_BINS; b++) {
      const n = a[b * 4 + 1] + a[b * 4 + 2] + a[b * 4 + 3]; tot.push(n);
      max = Math.max(max, ageMode === 'count' ? n : n >= 25 ? a[b * 4 + 3] / n : 0);
    }
    ageCols.forEach((c, b) => {
      const n = tot[b];
      if (ageMode === 'count') {
        [1, 2, 3].forEach((sv, k) => { c.stack[k].style.height = (a[b * 4 + sv] / max) * 100 + '%'; });
      } else {
        const v = n >= 25 ? a[b * 4 + 3] / n : 0;
        c.stack[0].style.height = '0%'; c.stack[1].style.height = '0%'; c.stack[2].style.height = (v / max) * 100 + '%';
      }
    });
    const all = tot.reduce((x, y) => x + y, 0) + nUnknown;
    let male = 0, female = 0;
    for (let b = 0; b <= AGE_BINS; b++) { male += R.ageSex[b * 3 + 1]; female += R.ageSex[b * 3 + 2]; }
    ageNote.textContent = all ? `${pct(male / (male + female || 1), 0)} men · ${pct(female / (male + female || 1), 0)} women${nUnknown / all > 0.001 ? ` · age unknown for ${pct(nUnknown / all, 1)}` : ''}${ageMode === 'share' ? ' · bins under 25 people hidden' : ''}` : '';
  }

  // top pairs
  let pairMetric = 'n';
  const pairList = h('div', { class: 'pairs' });
  const pairSeg = h('div', { class: 'seg small' }, ...[['n', 'Most hurt'], ['k', 'Most killed']].map(([v, l]) => h('button', { type: 'button', role: 'radio', 'aria-checked': v === pairMetric, 'data-v': v,
    onclick: () => { pairMetric = v; pairSeg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', b.dataset.v === v)); renderPairs(engine.R); } }, l)));
  function renderPairs(R) {
    const rows = [];
    for (let c = 0; c < NMODE * NOPP; c++) if (R.selCell.n[c]) rows.push({ c, n: R.selCell.n[c], k: R.selCell.sev[c * 4 + 3], sev: R.selCell.sev[c * 4 + 2] + R.selCell.sev[c * 4 + 3] });
    rows.sort((a, b) => b[pairMetric] - a[pairMetric] || b.n - a.n);
    const top = rows.slice(0, 7), max = Math.max(1, ...top.map((r) => r[pairMetric]));
    pairList.replaceChildren(...top.map((r) => {
      const i = Math.floor(r.c / NOPP), j = r.c % NOPP, nm = pairName(meta, r.c);
      const row = h('button', { type: 'button', class: 'prow' + (engine.pairMask[r.c] ? ' on' : ''), onclick: () => onPair(r.c) },
        h('span', { class: 'pico', style: { color: theme.mode[i] }, html: icon(MODE_ICON[i], 16) }), h('span', { class: 'pname' }, nm.victim, h('em', ' × '), nm.opp),
        h('span', { class: 'pico dim', html: icon(OPP_ICON[j], 16) }),
        h('span', { class: 'ptrack' }, h('i', { style: { width: (r[pairMetric] / max) * 100 + '%', background: pairMetric === 'k' ? theme.sev[3] : '#8895ad' } })),
        h('span', { class: 'pval' }, fmt(r[pairMetric])));
      tooltip(row, () => `<div class="tt-h">${nm.victim} × ${nm.opp}</div><div class="tt-r"><b>${fmt(r.n)}</b> hurt · <b>${fmt(r.k)}</b> killed (${pct(r.k / r.n)})</div><div class="tt-r tt-dim">${pct(r.sev / r.n, 0)} killed or hospitalised</div>`);
      return row;
    }));
    if (!top.length) pairList.replaceChildren(h('p', { class: 'fnote' }, 'No victims match the current filters.'));
  }

  const stand = h('ul', { class: 'stand' });
  const standCard = h('section', { class: 'card standout' }, h('p', { class: 'eyebrow' }, 'What stands out here'), stand);
  const el = h('div', { class: 'overview' },
    h('section', { class: 'card hero' }, scope, heroN, heroSub, h('div', { class: 'kpis' }, kFatal.el, kHosp.el, kKilled.el)), standCard,
    h('section', { class: 'card' }, h('header', { class: 'card-h' }, h('div', h('p', { class: 'eyebrow' }, 'Worst injury per accident'), h('h3', 'Severity'))), sbar, sleg, people),
    h('section', { class: 'card' }, h('header', { class: 'card-h' }, h('div', h('p', { class: 'eyebrow' }, 'Who gets hurt'), h('h3', 'Age of victims')), h('span', { class: 'grow' }), ageSeg), ageChart,
      h('div', { class: 'age-legend' }, [3, 2, 1].map((sv) => h('span', h('i', { style: { background: theme.sev[sv] } }), theme.sevNames[sv]))), ageNote),
    h('section', { class: 'card' }, h('header', { class: 'card-h' }, h('div', h('p', { class: 'eyebrow' }, 'Top collision pairs'), h('h3', 'Victim × opponent')), h('span', { class: 'grow' }), pairSeg), pairList));

  return {
    el,
    update(R, ctx) {
      const base = engine.base;
      scope.textContent = ctx.scope;
      heroN.textContent = fmt(R.total);
      heroSub.innerHTML = R.total ? `${plural(R.total, 'accident')} · ${R.total / base.total < 0.001 ? 'under 0.1%' : pct(R.total / base.total, R.total / base.total < 0.1 ? 1 : 0)} of the ${fmt(base.total)} mapped` : 'No accident matches — relax a filter or pan the map';
      const fatal = R.sevAcc[3] / (R.total || 1), hosp = R.sevAcc[2] / (R.total || 1);
      const bf = base.sevAcc[3] / base.total, bh = base.sevAcc[2] / base.total;
      kFatal.v.textContent = R.total ? pct(fatal) : '—'; kFatal.vs.innerHTML = R.total ? versus(fatal, bf) : '';
      kHosp.v.textContent = R.total ? pct(hosp) : '—'; kHosp.vs.innerHTML = R.total ? versus(hosp, bh) : '';
      kKilled.v.textContent = fmt(R.people[3]); kKilled.vs.innerHTML = R.total ? `<span class="vs eq">${(R.people[3] / R.total * 100).toFixed(1)} per 100 acc.</span>` : '';
      const n = R.total || 1;
      segs.forEach((b, k) => { const sv = 3 - k; b.style.flexGrow = R.sevAcc[sv]; b.style.display = R.sevAcc[sv] ? '' : 'none'; b.classList.toggle('on', engine.has('sev', sv)); b.classList.toggle('dim', engine.counts.sev > 0 && !engine.has('sev', sv)); });
      sleg.replaceChildren(...[3, 2, 1].map((sv) => h('button', { type: 'button', class: 'sl' + (engine.has('sev', sv) ? ' on' : ''), onclick: () => onSev(sv) },
        h('i', { style: { background: theme.sev[sv] } }), h('span', theme.sevNames[sv]), h('b', fmt(R.sevAcc[sv])), h('em', pct(R.sevAcc[sv] / n, 1)))));
      people.innerHTML = `<b>${fmt(R.people[0] + R.people[1] + R.people[2] + R.people[3])}</b> people involved: ${fmt(R.people[3])} killed · ${fmt(R.people[2])} hospitalised · ${fmt(R.people[1])} slightly injured · ${fmt(R.people[0])} unharmed`;
      renderAge(R); renderPairs(R);
      const ins = insights(R, engine, meta);
      standCard.hidden = !ins.length;
      stand.replaceChildren(...ins.map(([k, t]) => h('li', h('span', { class: 'sk' }, k), h('span', { html: t }))));
    },
  };
}
