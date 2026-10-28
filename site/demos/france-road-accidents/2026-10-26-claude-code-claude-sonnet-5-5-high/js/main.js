// Collision Observatory – application shell: wires data → engine → map + panels.
import { loadData, loadText } from './data.js';
import { Engine, FILTERS, NOPP, cellOf } from './engine.js';
import { MapView, FRANCE_BOUNDS } from './mapview.js';
import { THEME } from './theme.js';
import { h, s, initTip, showTip, hideTip, fmt, pct, throttleRaf, throttleTime, debounce, plural } from './util.js';
import { icon } from './icons.js';
import { Matrix, pairName } from './ui/matrix.js';
import { buildFilters } from './ui/filters.js';
import { Summary } from './ui/summary.js';
import { Ranking } from './ui/ranking.js';
import { Record } from './ui/record.js';
import { ActiveBar, Legend, Search, Scenes, About } from './ui/chrome.js';

const DATA_URL = 'data';
const $ = (id) => document.getElementById(id);
initTip();

// ---- loader ---------------------------------------------------------------------------------------------------
const loaderBar = $('loader-bar'), loaderMsg = $('loader-msg');
const setProgress = (f) => { loaderBar.style.transform = `scaleX(${Math.max(0.03, f)})`; loaderMsg.textContent = f < 0.98 ? `Loading accidents… ${Math.round(f * 100)}%` : 'Preparing the map…'; };

let data;
try {
  data = await loadData(DATA_URL, setProgress);
} catch (err) {
  loaderMsg.textContent = 'Could not load the data files. Run the site from a web server (see README).';
  throw err;
}
const { meta } = data;

// ---- engine ---------------------------------------------------------------------------------------------------
const engine = new Engine(data.acc, data.rel);
engine.rebuildAll();
engine.run(); // unfiltered baseline ("France")

const state = { colorBy: 'sev', follow: true, selection: null, tab: 'overview', baseZoom: 5.4 };

// ---- UI construction ---------------------------------------------------------------------------------------------
const refresh = throttleRaf((opts = {}) => update(opts));
const onChange = (live) => refresh({ filters: true, live });

const matrix = Matrix({ engine, meta, theme: THEME, onChange });
const filters = buildFilters({ engine, meta, onChange });
const summary = Summary({ engine, meta, theme: THEME, onSev: (sv) => { engine.toggle('sev', sv); onChange(); }, onPair: (c) => { engine.togglePair(c); onChange(); } });
const ranking = Ranking({ engine, meta, onFocus: focusDep, onHover: (i) => view.setDepHover(i), onMetric: () => refresh({ filters: true }) });
const record = Record({
  engine, data, meta, theme: THEME, loadText: () => loadText(DATA_URL),
  onClose: () => select(null), onOpen: (i) => select({ type: 'acc', i }), onZoom: (i) => view.flyTo(view.lonlat(i), 17.2, 900),
});
const activeBar = ActiveBar({ engine, meta, theme: THEME, onChange });
const legend = Legend({ engine, meta, theme: THEME, onToggle: (k, v) => { engine.toggle(k, v); onChange(); } });
const about = About({ meta });

const SCENES = [
  { title: 'After dark, no street lights', blurb: 'Night-time accidents on roads without public lighting.', apply: (e) => e.setValues('lum', [3]), camera: 'france' },
  { title: 'Pedestrians struck by cars', blurb: 'Where people on foot are hit by passenger cars.', apply: (e) => e.setPairs([cellOf(0, 4)]), camera: 'france' },
  { title: 'Cyclists & e-scooters in Paris', blurb: 'Two-wheeled soft mobility in the capital, coloured by victim mode.', apply: (e) => e.setPairs(Array.from({ length: NOPP }, (_, j) => [cellOf(1, j), cellOf(2, j)]).flat()), camera: { center: [2.35, 48.86], zoom: 11.4 }, colorBy: 'mode' },
  { title: 'Motorcyclists on country roads', blurb: 'Riders hurt on departmental roads limited to 80 or 90 km/h.', apply: (e) => { e.setPairs(Array.from({ length: NOPP }, (_, j) => cellOf(3, j))); e.setValues('road', [3]); e.setValues('vma', [4, 5]); }, camera: 'france' },
  { title: 'Motorway at 130', blurb: 'Accidents on motorways where the limit is 130 km/h.', apply: (e) => { e.setValues('road', [1]); e.setValues('vma', [7]); }, camera: 'france' },
  { title: 'Fog, snow and ice', blurb: 'Accidents in fog, snow or hail.', apply: (e) => e.setValues('atm', [4, 5]), camera: 'france' },
  { title: 'Collisions with animals', blurb: 'Every accident in which a recorded animal was the opposing party.', apply: (e) => e.setPairs(Array.from({ length: 8 }, (_, i) => cellOf(i, 8))), camera: 'france' },
  { title: 'Rush hour around Paris', blurb: 'Weekday commutes, 7–9 h and 16–19 h, in Île-de-France.', apply: (e) => { e.setValues('hour', [7, 8, 9, 16, 17, 18, 19]); e.setValues('dow', [0, 1, 2, 3, 4]); }, camera: { center: [2.4, 48.85], zoom: 9.3 } },
  { title: 'Cycle tracks and lanes', blurb: 'Cyclists hurt on roads that have a cycle track or lane.', apply: (e) => { e.setPairs(Array.from({ length: NOPP }, (_, j) => cellOf(1, j))); e.setValues('vosp', [2, 3]); }, camera: 'france' },
  { title: 'Weekend nights', blurb: 'Saturday and Sunday, 22:00 to 05:59.', apply: (e) => { e.setValues('dow', [5, 6]); e.setValues('hour', [22, 23, 0, 1, 2, 3, 4, 5]); }, camera: 'france' },
];
const scenes = Scenes({ scenes: SCENES, onPick: applyScene });
const search = Search({ meta, onPick: (it) => (it.dep != null ? view.fit(depBounds(it.dep), { maxZoom: 10 }) : view.flyTo(it.lonlat, 12.6)) });

// header
const colorSeg = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Colour the map by' },
  ...[['sev', 'Worst injury'], ['mode', 'Victim mode']].map(([v, l]) => h('button', { type: 'button', role: 'radio', 'aria-checked': v === state.colorBy, 'data-v': v, onclick: () => setColorBy(v) }, l)));
const yearBtns = [0, 1, 2].map((y) => h('button', { type: 'button', class: 'ybtn', 'aria-pressed': 'false', onclick: () => { engine.toggle('year', y); onChange(); } }, String(2022 + y)));
const headerEl = $('top');
headerEl.append(
  h('div', { class: 'brand' },
    s('svg', { class: 'logo', viewBox: '0 0 32 32', 'aria-hidden': 'true', html: '<circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-opacity=".35"/><circle cx="16" cy="16" r="8" fill="none" stroke="currentColor" stroke-opacity=".6"/><circle cx="16" cy="16" r="2.6" fill="#e8456b"/><circle cx="24.6" cy="11.4" r="1.7" fill="#c98500"/><circle cx="9.4" cy="21.8" r="1.7" fill="#3987e5"/>' }),
    h('div', h('h1', 'Collision Observatory'), h('p', 'Injury road accidents · metropolitan France · 2022–2024'))),
  h('div', { class: 'top-controls' },
    h('div', { class: 'ctl' }, h('span', { class: 'ctl-l' }, 'Colour by'), colorSeg),
    h('div', { class: 'ctl' }, h('span', { class: 'ctl-l' }, 'Year'), h('div', { class: 'years' }, yearBtns)),
    scenes.el,
    h('button', { type: 'button', class: 'btn ghost', id: 'btn-reset', onclick: resetAll, title: 'Clear every filter and return to the national view' }, h('span', { html: icon('reset', 15) }), 'Reset'),
    h('button', { type: 'button', class: 'btn ghost', onclick: shareLink, title: 'Copy a link to this exact view and filters' }, h('span', { html: icon('link', 15) }), 'Share'),
    h('button', { type: 'button', class: 'btn ghost', onclick: () => about.open() }, h('span', { html: icon('info', 15) }), 'Method')));

$('left-scroll').append(matrix.el, h('section', { class: 'card filters-card' }, h('header', { class: 'card-h' }, h('div', h('p', { class: 'eyebrow' }, 'Slice the accidents'), h('h2', 'Filters'))), filters.el));

// right panel: tabs
const followToggle = h('label', { class: 'switch', title: 'When on, every number and chart describes only the part of the map you can see' },
  h('input', { type: 'checkbox', checked: true, onchange: (e) => { state.follow = e.target.checked; refresh({}); } }), h('span', { class: 'track' }, h('i')), h('span', 'Follow map view'));
const panes = {
  overview: h('div', { class: 'pane', id: 'pane-overview' }, h('div', { class: 'follow-row' }, followToggle), summary.el),
  deps: h('div', { class: 'pane', id: 'pane-deps', hidden: true }, ranking.el),
  record: h('div', { class: 'pane', id: 'pane-record', hidden: true }, record.el),
};
const tabsEl = $('tabs');
const tabBtns = { overview: 'Overview', deps: 'Départements', record: 'Record' };
for (const [k, label] of Object.entries(tabBtns)) tabsEl.append(h('button', { type: 'button', role: 'tab', 'data-tab': k, 'aria-selected': k === state.tab, onclick: () => setTab(k) }, label, k === 'record' ? h('i', { class: 'tabdot', hidden: true }) : null));
$('right-scroll').append(...Object.values(panes));
function setTab(k) {
  state.tab = k;
  tabsEl.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === k));
  for (const [n, p] of Object.entries(panes)) p.hidden = n !== k;
  view?.setChoroVisible(k === 'deps');
  if (isNarrow()) toggleSheet('right', true); else { $('right').classList.remove('collapsed'); updateInsets(); }
}

// map overlays
const mapui = $('mapui');
mapui.append(h('div', { class: 'mapui-top' }, search.el, activeBar.el), h('div', { class: 'mapui-bottom' }, h('div', { class: 'mapui-note', id: 'hint' },
  h('b', 'One dot = one accident.'), ' Hover for a summary, click for the full record. Pan and zoom — every number follows.', h('button', { type: 'button', 'aria-label': 'Dismiss', html: icon('close', 12), onclick: (e) => e.currentTarget.closest('.mapui-note').remove() })), legend.el));
document.body.append(about.el);

// collapse buttons & insets
for (const side of ['left', 'right']) {
  const btn = h('button', { type: 'button', class: 'collapse ' + side, 'aria-label': `Toggle ${side} panel`, html: icon(side === 'left' ? 'chevL' : 'chevR', 16), onclick: () => { $(side).classList.toggle('collapsed'); updateInsets(); } });
  $(side).append(btn);
}
const isNarrow = () => innerWidth < 1060;
function updateInsets() {
  const L = $('left'), R = $('right'), narrow = isNarrow();
  const left = narrow ? 8 : L.classList.contains('collapsed') ? 12 : L.getBoundingClientRect().right + 12;
  const right = narrow ? 8 : R.classList.contains('collapsed') ? 12 : innerWidth - R.getBoundingClientRect().left + 12;
  const top = headerEl.getBoundingClientRect().bottom + 6;
  const sheetOpen = narrow && (L.classList.contains('open') || R.classList.contains('open'));
  const bottom = narrow ? (sheetOpen ? Math.round(innerHeight * 0.62) + 8 : 60) : 12;
  const css = document.documentElement.style;
  css.setProperty('--inset-left', left + 'px'); css.setProperty('--inset-right', right + 'px'); css.setProperty('--inset-top', top + 'px');
  css.setProperty('--inset-bottom', bottom + 'px');
  view?.setInsets({ left, right, top, bottom: bottom === 12 ? 0 : bottom });
  refresh({});
}
// narrow screens: bottom sheets switched by a dock
const dock = h('nav', { id: 'dock', 'aria-label': 'Panels' },
  h('button', { type: 'button', 'data-p': 'left', 'aria-pressed': 'false', onclick: () => toggleSheet('left') }, 'Matrix & filters'),
  h('button', { type: 'button', 'data-p': 'right', 'aria-pressed': 'false', onclick: () => toggleSheet('right') }, 'Insights'));
document.body.append(dock);
function toggleSheet(side, force) {
  const el = $(side), other = $(side === 'left' ? 'right' : 'left'), on = force ?? !el.classList.contains('open');
  el.classList.toggle('open', on); if (on) other.classList.remove('open');
  dock.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', $(b.dataset.p).classList.contains('open')));
  updateInsets();
}

// ---- map ------------------------------------------------------------------------------------------------------------
const view = new MapView({ container: 'map', data, engine, theme: THEME });
view.map.addControl(new maplibregl.NavigationControl({ showCompass: false, visualizePitch: false }), 'bottom-right');
await view.ready;
updateInsets();
view.fit(FRANCE_BOUNDS, { duration: 0, pad: 6 });
state.baseZoom = view.map.getZoom();

const moveRefresh = throttleTime(() => refresh({}), 70);
view.on('view', moveRefresh);
view.on('viewend', () => { refresh({}); scheduleHash(); });
view.on('click', (e) => { clickMap(e); dismissHint(); });
view.on('hover', hoverMap);
addEventListener('resize', debounce(updateInsets, 120));
addEventListener('keydown', (e) => { if (e.key === 'Escape' && state.selection) select(null); });

const dismissHint = () => $('hint')?.remove();
setTimeout(dismissHint, 18000);

// ---- the update cycle ---------------------------------------------------------------------------------------
function update(opts = {}) {
  if (state.follow) engine.setView(view.regionBounds()); else engine.setView(null);
  const R = engine.run();
  const zoomed = view.map.getZoom() > state.baseZoom + 0.35;
  const scope = !state.follow ? 'Accidents · metropolitan France' : zoomed ? 'Accidents in the current map view' : 'Accidents · metropolitan France';
  matrix.update(R); filters.update(R); summary.update(R, { scope }); ranking.update(R); activeBar.update(); legend.update(R, state.colorBy);
  yearBtns.forEach((b, y) => { const hs = R.hist.year, n = hs[y * 4] + hs[y * 4 + 1] + hs[y * 4 + 2] + hs[y * 4 + 3]; b.setAttribute('aria-pressed', engine.has('year', y)); b.classList.toggle('dim', engine.counts.year > 0 && !engine.has('year', y)); b.title = `${fmt(n)} accidents`; });
  if (opts.filters) { view.layer.touchVis(); view.setChoropleth(ranking.shades); }
  scheduleHash();
}

function setColorBy(v) {
  state.colorBy = v; view.setColorBy(v === 'sev' ? 0 : 1);
  colorSeg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', b.dataset.v === v));
  refresh({});
}

function resetAll() {
  engine.clearAll(); select(null); setColorBy('sev');
  state.follow = true; followToggle.querySelector('input').checked = true;
  view.resetView(); onChange();
}

async function shareLink() {
  writeHash();
  try { await navigator.clipboard.writeText(location.href); toast('Link copied — it restores this view and every filter'); } catch { toast('Copy the address bar to share this view'); }
}
let toastEl;
function toast(msg) {
  toastEl?.remove(); toastEl = h('div', { class: 'toast', role: 'status' }, msg); document.body.append(toastEl);
  setTimeout(() => toastEl?.classList.add('out'), 2600); setTimeout(() => toastEl?.remove(), 3100);
}
function depBounds(i) { const [w, s, e, n] = meta.deps[i].bbox; return [[w, s], [e, n]]; }
function focusDep(i) {
  const had = engine.has('dep', i) && engine.counts.dep === 1;
  engine.setValues('dep', had ? [] : [i]);
  if (!had) view.fit(depBounds(i), { maxZoom: 11 });
  onChange();
}

function applyScene(sc) {
  engine.clearAll(); select(null); sc.apply(engine);
  state.follow = true; followToggle.querySelector('input').checked = true;
  setColorBy(sc.colorBy || 'sev');
  if (sc.camera === 'france') view.resetView(900); else view.flyTo(sc.camera.center, sc.camera.zoom, 1300);
  onChange();
}

// ---- hover & selection ----------------------------------------------------------------------------------------------------
const A = data.acc;
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
function accidentTip(i) {
  const nm = pairName(meta, A.wmode[i] * NOPP + A.wopp[i]), k = A.n_kil[i], hs = A.n_hos[i];
  const out = k ? `${k} killed` : hs ? `${hs} hospitalised` : `${A.n_slt[i]} slightly injured`;
  const com = meta.communes[A.com[i]]?.[1] || '';
  return `<div class="tt-h"><i class="sw" style="background:${THEME.sev[A.sev[i]]}"></i>${nm.victim} × ${nm.opp}</div>` +
    `<div class="tt-r">${DOW[A.dow[i]]} ${A.day[i]}/${String(A.month[i]).padStart(2, '0')}/${2022 + A.year[i]} · ${String(A.hour[i]).padStart(2, '0')}:${String(A.minute[i]).padStart(2, '0')}</div>` +
    `<div class="tt-r">${out} · ${A.nusr[i]} ${plural(A.nusr[i], 'person', 'people')}${com ? ' · ' + com : ''}</div><div class="tt-r tt-dim">Click for the full record</div>`;
}
let hoverIdx = null;
function hoverMap(idx, ev) {
  const canvas = view.map.getCanvas();
  if (idx != null) {
    canvas.style.cursor = 'pointer';
    if (hoverIdx !== idx) { hoverIdx = idx; view.setHighlights({ hover: idx, selected: selIndex(), selectedColor: selColor(), cluster: clusterShape() }); }
    showTip(accidentTip(idx), ev.originalEvent.clientX, ev.originalEvent.clientY);
    view.setDepHover(null);
    return;
  }
  canvas.style.cursor = '';
  if (hoverIdx != null) { hoverIdx = null; view.setHighlights({ selected: selIndex(), selectedColor: selColor(), cluster: clusterShape() }); }
  if (!ev) { hideTip(); view.setDepHover(null); return; }
  const dep = view.map.getZoom() < 10.5 ? view.depAt(ev.point) : null;
  view.setDepHover(dep);
  if (dep != null) {
    const d = meta.deps[dep], R = engine.R, n = R.dep.n[dep];
    showTip(`<div class="tt-h">${d.name} <span class="tt-dim">(${d.code})</span></div><div class="tt-r"><b>${fmt(n)}</b> accidents · ${fmt(R.dep.killed[dep])} killed</div><div class="tt-r">${fmt(n / (d.pop / 1e5) / (engine.counts.year || 3))} / 100k residents / yr</div>`, ev.originalEvent.clientX, ev.originalEvent.clientY);
  } else hideTip();
}

const selIndex = () => (state.selection?.type === 'acc' ? state.selection.i : null);
const selColor = () => (state.selection?.type === 'acc' ? THEME.sev[A.sev[state.selection.i]] : '#fff');
const clusterShape = () => (state.selection?.type === 'cluster' ? { center: state.selection.center, rpx: state.selection.rpx } : null);

function clickMap(e) {
  hideTip();
  const mpp = view.mercPerPx(), near = view.pick(e.point, 10);
  if (!near.length) {
    const wide = view.pick(e.point, 18);
    if (!wide.length) return select(null);
    return select(wide.length === 1 ? { type: 'acc', i: wide[0][0] } : clusterFrom(wide, e, 18));
  }
  // dots whose drawn disc contains the click
  const rr = (view.layerRadiusPx() + 2) * mpp, under = near.filter((n) => n[1] <= rr * rr);
  if (under.length === 1 || (!under.length && near.length === 1)) return select({ type: 'acc', i: (under[0] || near[0])[0] });
  select(clusterFrom(view.pick(e.point, 16), e, 16));
}
function clusterFrom(hits, e, px) {
  const m = 40075016.686 * Math.cos((e.lngLat.lat * Math.PI) / 180) / (512 * Math.pow(2, view.map.getZoom())) * px;
  const ids = hits.map((h) => h[0]);
  return { type: 'cluster', ids, center: [e.lngLat.lng, e.lngLat.lat], rpx: px, radiusLabel: m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m / 10) * 10 || 10} m`, zoomLevel: view.map.getZoom() };
}

function select(sel) {
  state.selection = sel;
  const dot = tabsEl.querySelector('.tabdot');
  if (!sel) {
    record.clear(); dot.hidden = true; view.setHighlights({}); if (state.tab === 'record') setTab('overview'); scheduleHash(); return;
  }
  dot.hidden = false;
  if (sel.type === 'acc') record.show(sel.i);
  else record.showCluster(sel.ids, {
    radiusLabel: sel.radiusLabel, onHover: (i) => view.setHighlights({ hover: i, cluster: clusterShape() }),
    onZoom: () => { let w = 180, s = 90, ee = -180, n = -90; for (const i of sel.ids) { const [x, y] = view.lonlat(i); w = Math.min(w, x); ee = Math.max(ee, x); s = Math.min(s, y); n = Math.max(n, y); } view.fit([[w, s], [ee, n]], { maxZoom: 16.5, pad: 70 }); },
  });
  view.setHighlights({ selected: selIndex(), selectedColor: selColor(), cluster: clusterShape() });
  setTab('record'); scheduleHash();
}

// ---- shareable state (URL hash) --------------------------------------------------------------------------------------------
const scheduleHash = debounce(() => writeHash(), 350);
function writeHash() {
  if (!view?.map) return;
  const p = new URLSearchParams(), c = view.map.getCenter();
  p.set('v', `${c.lng.toFixed(4)},${c.lat.toFixed(4)},${view.map.getZoom().toFixed(2)}`);
  if (state.colorBy !== 'sev') p.set('c', state.colorBy);
  if (!state.follow) p.set('follow', '0');
  for (const f of FILTERS) if (engine.counts[f.key]) { const v = []; engine.masks[f.key].forEach((x, i) => x && v.push(i)); p.set(f.key, v.join('.')); }
  if (engine.pairCount) { const v = []; engine.pairMask.forEach((x, i) => x && v.push(i)); p.set('pair', v.join('.')); }
  if (state.selection?.type === 'acc') p.set('a', A.id[state.selection.i].toString());
  history.replaceState(null, '', '#' + p.toString());
}

function restoreHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (![...p.keys()].length) return false;
  for (const f of FILTERS) if (p.has(f.key)) engine.setValues(f.key, p.get(f.key).split('.').filter(Boolean).map(Number).filter((v) => v >= 0 && v < f.n));
  if (p.has('pair')) engine.setPairs(p.get('pair').split('.').filter(Boolean).map(Number).filter((v) => v >= 0 && v < 88));
  if (p.get('c') === 'mode') setColorBy('mode');
  if (p.get('follow') === '0') { state.follow = false; followToggle.querySelector('input').checked = false; }
  if (p.has('v')) { const [x, y, z] = p.get('v').split(',').map(Number); if ([x, y, z].every(isFinite)) view.map.jumpTo({ center: [x, y], zoom: z }); }
  if (p.has('a')) { const id = BigInt(p.get('a')); const i = Array.prototype.findIndex.call(A.id, (v) => v === id); if (i >= 0) select({ type: 'acc', i }); }
  return true;
}

// ---- go --------------------------------------------------------------------------------------------------------------------
restoreHash();
onChange();
view.map.once('idle', () => $('loader').classList.add('done'));
setTimeout(() => $('loader').classList.add('done'), 4000);
window.__app = { data, engine, view, state, select, refresh, update };
