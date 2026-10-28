// DOM panels: timeline, statistics, legend / filters, detail panels, tooltip, search.
import { CATS, BANDS, bandOf, el, esc, hm, hms, dur, durShort, fmtInt, clamp, ramp, rgba, lowerIdx, upperIdx } from './util.js';
import { getLeg, callsSplit, countActive, tripLabel, trainState } from './data.js';
import { MIN_TRANSFER } from './csa.js';

const SPEEDS = [1, 60, 240, 600, 1800];
const PLAY_SVG = '<svg viewBox="0 0 20 20"><path d="M6 3.5v13l11-6.5z"/></svg>';
const PAUSE_SVG = '<svg viewBox="0 0 20 20"><path d="M5 3.5h3.6v13H5zM11.4 3.5H15v13h-3.6z"/></svg>';
const $ = (id) => document.getElementById(id);

export function dayLabel(D) {
  const d = new Date(D.date + 'T12:00:00');
  return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

// ====================================================================== timeline
export function initTimeline(A) {
  const play = $('play');
  play.innerHTML = PAUSE_SVG;
  play.onclick = () => A.togglePlay();
  const sp = $('speeds');
  SPEEDS.forEach((v) => {
    sp.append(el('button', { 'data-v': v, text: v === 1 ? '1×' : v + '×', title: v === 1 ? 'Real time' : `${v}× real time`, onclick: () => A.setSpeed(v) }));
  });
  const scrub = $('scrub');
  const tip = $('scrubTip');
  const timeAt = (e) => {
    const r = scrub.getBoundingClientRect();
    return clamp((e.clientX - r.left) / r.width, 0, 0.99999) * 86400;
  };
  let down = false;
  scrub.addEventListener('pointerdown', (e) => { down = true; scrub.setPointerCapture(e.pointerId); A.scrubbing = true; A.setTime(timeAt(e)); });
  scrub.addEventListener('pointermove', (e) => {
    const t = timeAt(e);
    tip.style.display = 'block'; tip.style.left = (t / 86400 * 100) + '%'; tip.textContent = hm(t);
    if (down) A.setTime(t);
  });
  scrub.addEventListener('pointerleave', () => { tip.style.display = 'none'; });
  const end = () => { down = false; A.scrubbing = false; };
  scrub.addEventListener('pointerup', end); scrub.addEventListener('pointercancel', end);
  scrub.addEventListener('keydown', (e) => {
    const k = { ArrowLeft: -600, ArrowRight: 600, PageDown: -3600, PageUp: 3600, Home: -86400, End: 86400 }[e.key];
    if (k) { e.preventDefault(); A.setTime(A.S.t + (e.shiftKey ? k * 6 : k)); }
  });
  new ResizeObserver(() => drawScrub(A)).observe(scrub);
  A.markSpeed = () => [...sp.children].forEach((b) => b.classList.toggle('on', +b.dataset.v === A.S.speed));
  A.markSpeed();
}

export function drawScrub(A) {
  const D = A.D; if (!D) return;
  const c = $('scrubCanvas'), r = c.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr);
  const g = c.getContext('2d');
  g.scale(dpr, dpr);
  const W = r.width, H = r.height, base = H - 13, top = 2;
  const n = 288; // 5-min resolution
  const peak = D.peak * 1.02;
  const xs = (i) => (i / n) * W;
  const acc = new Float64Array(n + 1);
  const stackOrder = [2, 1, 0];
  for (const c2 of stackOrder) {
    const prev = Float64Array.from(acc);
    for (let i = 0; i <= n; i++) acc[i] += D.profile[c2][Math.min(1439, i * 5)];
    g.beginPath();
    for (let i = 0; i <= n; i++) g.lineTo(xs(i), base - (acc[i] / peak) * (base - top));
    for (let i = n; i >= 0; i--) g.lineTo(xs(i), base - (prev[i] / peak) * (base - top));
    g.closePath();
    g.fillStyle = rgba(CATS[c2].rgb, 0.42);
    g.fill();
  }
  g.beginPath();
  for (let i = 0; i <= n; i++) g.lineTo(xs(i), base - (acc[i] / peak) * (base - top));
  g.strokeStyle = 'rgba(200,220,255,0.55)'; g.lineWidth = 1; g.stroke();
  // baseline + hour ticks
  g.fillStyle = 'rgba(130,170,235,0.25)'; g.fillRect(0, base, W, 1);
  g.font = '10px ui-monospace, Menlo, monospace'; g.textBaseline = 'top';
  for (let h = 0; h <= 24; h++) {
    const x = (h / 24) * W;
    g.fillStyle = h % 3 === 0 ? 'rgba(160,185,225,0.55)' : 'rgba(130,170,235,0.2)';
    g.fillRect(Math.min(W - 1, x), base, 1, h % 3 === 0 ? 5 : 3);
    if (h % 3 === 0 && h < 24) {
      g.fillStyle = 'rgba(157,176,204,0.85)';
      g.fillText(String(h).padStart(2, '0'), x + 3, base + 3);
    }
  }
}

export function updateClock(A) {
  const t = A.S.t;
  const s = Math.floor(t);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  $('clock').textContent = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  $('clockSec').textContent = ':' + String(sec).padStart(2, '0');
  $('scrubHead').style.left = `calc(${(t / 86400) * 100}% - 1px)`;
  const sc = $('scrub'); sc.setAttribute('aria-valuenow', Math.floor(t / 60)); sc.setAttribute('aria-valuetext', hm(t));
  $('play').innerHTML = A.S.playing ? PAUSE_SVG : PLAY_SVG;
  // night tint: darkest around 02:00, none during the day
  const hr = t / 3600;
  const night = hr < 6 ? 1 - hr / 6 * 0.3 : hr < 8 ? 0.7 * (1 - (hr - 6) / 2) : hr > 20 ? clamp((hr - 20) / 3, 0, 1) * 0.7 : 0;
  $('night').style.opacity = (night * 0.5).toFixed(3);
}

// ====================================================================== days + modes
export function initDays(A) {
  const box = $('days');
  box.innerHTML = '';
  A.M.meta.days.forEach((d) => {
    box.append(el('button', { 'data-k': d.key, text: d.label, title: new Date(d.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }), onclick: () => A.setDay(d.key) }));
  });
}
export function markDay(A) {
  [...$('days').children].forEach((b) => b.classList.toggle('on', b.dataset.k === A.S.day));
  $('dateLbl').textContent = new Date(A.D.date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) + ' · scheduled';
}
export function initAbout() {
  const b = $('infoBtn'), a = $('about');
  const set = (v) => { a.hidden = !v; b.setAttribute('aria-expanded', v); };
  b.onclick = () => set(a.hidden);
  $('aboutClose').onclick = () => set(false);
}
export function markMode(A) {
  document.querySelectorAll('#modes button').forEach((b) => b.classList.toggle('on', b.dataset.mode === A.S.mode));
  $('app').dataset.mode = A.S.mode;
}

// ====================================================================== main (left) card
let mainRefs = {};
export function buildMainCard(A) {
  const S = A.S, card = $('cardMain'), D = A.D;
  mainRefs = {};
  const perDay = [0, 0, 0];
  for (const t of D.trips) if (t.o === 0) perDay[t.cat]++;
  A.perDay = perDay;

  const catRows = () => {
    const box = el('div', { class: 'cats' });
    CATS.forEach((c, i) => {
      const b = el('button', { class: 'cat', style: { '--c': c.color }, 'data-c': i, title: 'Click: show / hide · Shift-click: isolate' });
      b.innerHTML = `<span class="sw"></span><span class="nm">${c.name}<small>${esc(c.long.split('·')[1] || c.long)}</small></span><span class="v num"><span class="cv">0</span><small>${S.mode === 'live' ? 'in service · ' : ''}${fmtInt(perDay[i])} / day</small></span>`;
      b.onclick = (e) => A.toggleCat(i, e.shiftKey);
      b.onmouseenter = () => { S.hoverCat = i; A.dirtyDyn(); };
      b.onmouseleave = () => { S.hoverCat = -1; A.dirtyDyn(); };
      mainRefs['cv' + i] = b.querySelector('.cv'); mainRefs['cat' + i] = b;
      box.append(b);
    });
    return box;
  };

  card.innerHTML = '';
  if (S.mode === 'live') {
    card.append(el('h2', { html: `Network status <span class="hint">at ${'<span id="hClock">--:--</span>'}</span>` }));
    card.append(el('div', { class: 'big', html: '<span class="n" id="bigN">0</span><span class="l">trains in circulation</span>' }));
    card.append(el('div', { class: 'stack', id: 'stack', html: CATS.map((c) => `<i style="background:${c.color};flex:1 1 0"></i>`).join('') }));
    card.append(catRows());
    card.append(el('p', { class: 'note', html: '<b>Click</b> to show / hide · <b>Shift-click</b> to isolate · <b>hover</b> to highlight' }));
    mainRefs.bigN = $('bigN'); mainRefs.stack = $('stack'); mainRefs.hClock = $('hClock');
  } else if (S.mode === 'flow') {
    card.append(el('h2', { html: `Corridor flow <span class="hint">trains per line section</span>` }));
    const seg = el('div', { class: 'seg', id: 'flowMode', style: { marginBottom: '10px', display: 'flex' }, html: '<button data-m="full" style="flex:1">Full 24 h</button><button data-m="cum" style="flex:1">Accumulating to clock</button>' });
    seg.querySelectorAll('button').forEach((b) => { b.classList.toggle('on', b.dataset.m === S.flowMode); b.onclick = () => A.setFlowMode(b.dataset.m); });
    card.append(seg);
    card.append(el('div', { html: `<div class="grad" id="grad"></div><div class="grad-l num"><span>1</span><span id="gMid"></span><span id="gMax"></span></div>` }));
    card.append(el('div', { style: { height: '10px' } }));
    card.append(catRows());
    card.append(el('div', { class: 'tools', html: '<button class="chip" id="chipTrains">Overlay moving trains</button>' }));
    $('chipTrains').classList.toggle('on', S.showTrains);
    $('chipTrains').onclick = () => A.toggleShowTrains();
    card.append(el('h2', { style: { marginTop: '14px' }, html: 'Busiest corridors <span class="hint">peak section · trains / day</span>' }));
    card.append(el('div', { class: 'corr', id: 'corr' }));
    mainRefs.corr = $('corr');
  } else {
    card.append(el('h2', { html: 'Travel time by rail <span class="hint">earliest arrival</span>' }));
    const o = el('div', { class: 'origin', id: 'originBox' });
    card.append(o);
    const bands = el('div', { class: 'bands', id: 'bands' });
    BANDS.forEach((b, i) => {
      const r = el('div', { class: 'band', style: { '--c': b.color } });
      r.innerHTML = `<span class="sw"></span><span>${b.label}</span><span class="bar"><i style="width:0"></i></span><span class="c num">0</span>`;
      mainRefs['band' + i] = r; bands.append(r);
    });
    card.append(bands);
    card.append(el('div', { class: 'tools', html: '<button class="chip" id="chipWait" title="Add the wait for the first train to every travel time">Include wait for 1st train</button><button class="chip" id="chipTrains">Show moving trains</button>' }));
    $('chipTrains').classList.toggle('on', S.showTrains);
    $('chipTrains').onclick = () => A.toggleShowTrains();
    $('chipWait').classList.toggle('on', A.router.includeWait);
    $('chipWait').onclick = () => A.toggleWait();
    card.append(el('p', { class: 'note', html: 'Leaving the origin at the <b>timeline clock</b> — scrub it to change the departure time. Times run from the first departure and include every <b>transfer</b>: ≥ 5 min to change, plus the wait for the next train. Hover a station for its itinerary.' }));
    mainRefs.originBox = o;
  }
  updateMainCard(A, true);
  catStates(A);
}

export function catStates(A) {
  CATS.forEach((c, i) => { const b = mainRefs['cat' + i]; if (b) b.classList.toggle('off', !A.S.enabled[i]); });
}

const _act = new Int32Array(3);
export function updateMainCard(A, force) {
  const S = A.S, D = A.D;
  if (S.mode === 'live') {
    countActive(D, S.t, _act);
    const tot = _act[0] + _act[1] + _act[2];
    mainRefs.bigN.textContent = fmtInt(tot);
    mainRefs.hClock.textContent = hm(S.t);
    const kids = mainRefs.stack.children;
    for (let i = 0; i < 3; i++) { kids[i].style.flexGrow = Math.max(0.0001, _act[i]); mainRefs['cv' + i].textContent = fmtInt(_act[i]); }
    A.active = Int32Array.from(_act);
  } else if (S.mode === 'flow') {
    const F = A.rend.flow;
    for (let i = 0; i < 3; i++) if (mainRefs['cv' + i]) mainRefs['cv' + i].textContent = fmtInt(A.flowTot ? A.flowTot[i] : 0);
    if (F && (force || A.flowDirty)) {
      const stops = F.stops;
      const css = [0, 0.25, 0.5, 0.75, 1].map((q) => { const c = ramp(stops, q); return `rgb(${c[0]},${c[1]},${c[2]}) ${q * 100}%`; }).join(',');
      $('grad').style.background = `linear-gradient(90deg,${css})`;
      $('gMid').textContent = fmtInt(F.max / 4) + ' ';
      $('gMax').textContent = fmtInt(F.max) + ' trains';
      renderCorridors(A);
      A.flowDirty = false;
    }
  } else if (A.router) {
    const R = A.router, n = [0, 0, 0, 0, 0];
    let tot = 0;
    for (let s = 0; s < A.M.st.n; s++) {
      const t = R.time(s);
      if (t < Infinity && s !== R.origin) { n[bandOf(t)]++; tot++; }
    }
    const mx = Math.max(1, ...n);
    BANDS.forEach((b, i) => {
      const r = mainRefs['band' + i];
      r.querySelector('i').style.width = (n[i] / mx * 100) + '%';
      r.querySelector('.c').textContent = fmtInt(n[i]);
    });
    const nm = A.M.st.name[R.origin];
    mainRefs.originBox.innerHTML = `<span class="dot"></span><div><small>Origin · from ${hm(R.T)}${R.includeWait ? '' : ' (first departure)'}</small><b>${esc(nm)}</b><small>${fmtInt(tot)} of ${fmtInt(A.M.st.n - 1)} stations reachable within the day</small></div>`;
  }
}
// ---- corridors list
function renderCorridors(A) {
  const F = A.rend.flow, M = A.M;
  const best = new Map();
  for (let e = 0; e < M.edges.n; e++) {
    const code = M.edges.code[e];
    if (M.lines[code].g === undefined) continue;
    const v = F.val[e];
    if (!v) continue;
    const b = best.get(code);
    if (!b || v > b.v) best.set(code, { v, e });
  }
  const top = [...best.entries()].sort((a, b) => b[1].v - a[1].v).slice(0, 7);
  const box = mainRefs.corr;
  box.innerHTML = '';
  const mx = top.length ? top[0][1].v : 1;
  for (const [code, { v }] of top) {
    const L = M.lines[code];
    const rgb = ramp(F.stops, Math.sqrt(v / F.max));
    const b = el('button', { title: 'Zoom to this line' });
    b.innerHTML = `<span class="nm">${esc(L.n || 'Line ' + L.c)}<small>${L.g ? 'LGV ' : ''}${L.c}</small></span><span class="vv num">${fmtInt(v)}</span><span class="meter"><i style="width:${v / mx * 100}%;background:rgb(${rgb[0]},${rgb[1]},${rgb[2]})"></i></span>`;
    b.onmouseenter = () => { A.S.hoverCode = code; A.dirtyDyn(); };
    b.onmouseleave = () => { A.S.hoverCode = -1; A.dirtyDyn(); };
    b.onclick = () => A.zoomToCode(code);
    box.append(b);
  }
}

// ====================================================================== profile chart
let profRefs = null;
export function buildProfile(A) {
  const D = A.D, host = $('profile');
  host.innerHTML = '';
  const W = 306, H = 118, L = 26, R = 4, T = 6, B = 16;
  const iw = W - L - R, ih = H - T - B;
  const peak = Math.ceil(D.peak / 200) * 200 || 200;
  const x = (m) => L + (m / 1440) * iw, y = (v) => T + ih - (v / peak) * ih;
  const step = 5, n = 1440 / step;
  const stackOrder = [2, 1, 0];
  const base = new Float64Array(n + 1);
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Trains in circulation over 24 hours, stacked by category');
  let html = '<g class="grid">';
  for (let k = 0; k <= 2; k++) { const v = peak * k / 2; html += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`; }
  html += '</g><g class="ax">';
  for (let k = 0; k <= 2; k++) { const v = peak * k / 2; html += `<text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${fmtInt(v)}</text>`; }
  for (let h = 0; h <= 24; h += 6) html += `<text x="${x(h * 60)}" y="${H - 3}" text-anchor="${h === 0 ? 'start' : h === 24 ? 'end' : 'middle'}">${String(h).padStart(2, '0')}h</text>`;
  html += '</g>';
  for (const c of stackOrder) {
    const prev = Float64Array.from(base);
    for (let i = 0; i <= n; i++) base[i] += D.profile[c][Math.min(1439, i * step)];
    let top = '', bot = '';
    for (let i = 0; i <= n; i++) top += (i ? 'L' : 'M') + x(i * step).toFixed(1) + ' ' + y(base[i]).toFixed(1);
    for (let i = n; i >= 0; i--) bot += 'L' + x(i * step).toFixed(1) + ' ' + y(prev[i]).toFixed(1);
    html += `<path class="area" d="${top}${bot}Z" fill="${CATS[c].color}" fill-opacity="0.78"/>`;
  }
  html += `<line class="cross" id="pcross" y1="${T}" y2="${T + ih}" x1="0" x2="0" style="display:none"/><line class="head" id="phead" y1="${T}" y2="${T + ih}" x1="${L}" x2="${L}"/><circle id="pdot" r="3.6" cx="${L}" cy="${T}" fill="#fff" stroke="#0a111c" stroke-width="1.5"/>`;
  svg.innerHTML = html;
  host.append(svg);
  const tip = el('div', { id: 'ptip' });
  host.append(tip);
  profRefs = { svg, x, y, L, iw, W, T, ih, peak };
  const cross = svg.querySelector('#pcross');
  const minAt = (e) => {
    const r = svg.getBoundingClientRect();
    return clamp(((e.clientX - r.left) / r.width * W - L) / iw, 0, 0.9999) * 1440 | 0;
  };
  svg.addEventListener('pointermove', (e) => {
    const m = minAt(e), px = x(m);
    cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.style.display = '';
    const v = CATS.map((_, c) => D.profile[c][m]);
    tip.innerHTML = `<div style="font:600 12px var(--mono);margin-bottom:3px">${hm(m * 60)}</div>` + CATS.map((c, i) => `<div class="r"><span><i style="background:${c.color}"></i> ${c.name}</span><b>${fmtInt(v[i])}</b></div>`).join('') + `<div class="r" style="border-top:1px solid var(--line);margin-top:3px;padding-top:3px"><span>Total</span><b>${fmtInt(v[0] + v[1] + v[2])}</b></div>`;
    tip.style.display = 'block';
    const r = svg.getBoundingClientRect();
    const pxs = (px / W) * r.width;
    tip.style.left = Math.min(r.width - 120, Math.max(0, pxs + 10)) + 'px'; tip.style.top = '0px';
    if (e.buttons) A.setTime(m * 60);
  });
  svg.addEventListener('pointerleave', () => { cross.style.display = 'none'; tip.style.display = 'none'; });
  svg.addEventListener('pointerdown', (e) => { svg.setPointerCapture(e.pointerId); A.setTime(minAt(e) * 60); });
  svg.style.cursor = 'pointer';
}
export function updateProfile(A) {
  if (!profRefs) return;
  const m = Math.min(1439, Math.floor(A.S.t / 60));
  const D = A.D;
  const px = profRefs.x(A.S.t / 60);
  const tot = D.profile[0][m] + D.profile[1][m] + D.profile[2][m];
  $('phead').setAttribute('x1', px); $('phead').setAttribute('x2', px);
  $('pdot').setAttribute('cx', px); $('pdot').setAttribute('cy', profRefs.y(tot));
}

// ====================================================================== busiest stations
let busyMode = 'now';
export function initBusy(A) {
  document.querySelectorAll('#busyMode button').forEach((b) => {
    b.onclick = () => { busyMode = b.dataset.m; document.querySelectorAll('#busyMode button').forEach((x) => x.classList.toggle('on', x === b)); updateBusy(A); };
  });
}
const _sp = new Int32Array(3);
export function updateBusy(A) {
  const { M, D, S } = A;
  const n = M.st.n;
  const t0 = busyMode === 'now' ? S.t - 1800 : 0, t1 = busyMode === 'now' ? S.t + 1800 : 86400;
  const score = A._busyScore || (A._busyScore = new Int32Array(n));
  const en = S.enabled;
  for (let s = 0; s < n; s++) {
    if (busyMode === 'day') {
      score[s] = (en[0] ? D.nCalls[s * 3] : 0) + (en[1] ? D.nCalls[s * 3 + 1] : 0) + (en[2] ? D.nCalls[s * 3 + 2] : 0);
    } else {
      callsSplit(D, s, t0, t1, _sp);
      score[s] = (en[0] ? _sp[0] : 0) + (en[1] ? _sp[1] : 0) + (en[2] ? _sp[2] : 0);
    }
  }
  // top 8
  const top = [];
  for (let s = 0; s < n; s++) {
    const v = score[s];
    if (v <= 0) continue;
    if (top.length < 7 || v > top[top.length - 1][1]) {
      top.push([s, v]); top.sort((a, b) => b[1] - a[1]); if (top.length > 7) top.pop();
    }
  }
  const box = $('busy');
  const sig = top.map((x) => x[0] + ':' + x[1]).join('|') + busyMode + en.join('');
  if (sig === A._busySig) return;
  A._busySig = sig;
  box.innerHTML = '';
  const mx = top.length ? top[0][1] : 1;
  top.forEach(([s, v], i) => {
    const b = el('button');
    let bar = '';
    const sp = [0, 0, 0];
    if (busyMode === 'day') for (let c = 0; c < 3; c++) sp[c] = en[c] ? D.nCalls[s * 3 + c] : 0;
    else { callsSplit(D, s, t0, t1, sp); for (let c = 0; c < 3; c++) if (!en[c]) sp[c] = 0; }
    const tot = sp[0] + sp[1] + sp[2] || 1;
    bar = CATS.map((c, k) => `<i style="width:${sp[k] / mx * 100}%;background:${c.color}"></i>`).join('');
    b.innerHTML = `<span class="rk">${i + 1}</span><span class="nm">${esc(M.st.name[s])}</span><span class="v num">${fmtInt(v)}</span><span class="m">${bar}</span>`;
    b.onclick = () => A.selectStation(s, { fly: true });
    box.append(b);
  });
}

// ====================================================================== tooltip
const tipEl = () => $('tooltip');
export function showTip(x, y, html) {
  const t = tipEl();
  t.innerHTML = html; t.style.display = 'block';
  const w = t.offsetWidth, h = t.offsetHeight;
  const W = window.innerWidth, H = window.innerHeight;
  t.style.left = Math.min(W - w - 8, x + 16) + 'px';
  t.style.top = Math.min(H - h - 8, Math.max(60, y + 14)) + 'px';
}
export function hideTip() { tipEl().style.display = 'none'; }

export function trainTip(A, tr) {
  const c = CATS[tr.cat], M = A.M;
  const st = {};
  let next = '';
  if (trainState(M, tr, A.S.t, st)) {
    const i = st.moving ? st.seg + 1 : st.stop;
    if (i < tr.st.length) next = `<div class="s">${st.moving ? 'Next' : 'At'}: <b>${esc(M.st.name[tr.st[i]])}</b> · ${hm(st.moving ? tr.arr[i] : tr.dep[i])}</div>`;
  }
  return `<div class="h" style="--c:${c.color}"><i></i>${esc(tr.brand)} ${esc(tr.num)}</div><div class="s">${esc(tripLabel(M, tr))}</div>${next}`;
}
export function stationTip(A, s) {
  const M = A.M, D = A.D;
  let html = `<div class="h"><i style="--c:#fff;background:#fff"></i>${esc(M.st.name[s])}</div><div class="s">${esc([M.st.commune[s], M.st.dept[s]].filter(Boolean).join(' · ') || M.st.cc[s])} · ${fmtInt(D.callsTotal[s])} trains / day</div>`;
  if (A.S.mode === 'access' && A.router) {
    const R = A.router;
    if (s === R.origin) html += '<div class="s" style="color:#fff">Origin</div>';
    else {
      const t = R.time(s);
      if (!(t < Infinity)) html += '<div class="s">Not reachable by rail that day</div>';
      else {
        const b = BANDS[bandOf(t)];
        const legs = A.S.journey || R.journey(s);
        const rides = legs.filter((l) => l.type === 'ride').length;
        html += `<div class="big2" style="color:${b.color}">${dur(t)}</div><div class="s">${Math.max(0, rides - 1)} transfer${rides - 1 === 1 ? '' : 's'} · arrive ${hm(R.earliest[s])}${R.includeWait ? '' : ' · leave ' + hm(R.startDep[s])}</div><div class="jr">`;
        let prevArr = R.T;
        for (const l of legs) {
          const wait = l.dep - prevArr;
          if (l.type === 'ride') {
            const tr = D.trips[l.trip];
            html += `<div><span class="t">${hm(l.dep)}</span><span>${esc(M.st.name[l.from])} <span class="w">→</span> ${esc(M.st.name[l.to])}<br><span class="w">${esc(tr.brand)} ${esc(tr.num)} · ${hm(l.arr)}${wait > 0 && l !== legs[0] ? ' · wait ' + durShort(wait) : ''}</span></span></div>`;
          } else {
            html += `<div><span class="t">${hm(l.dep)}</span><span class="w">Walk to ${esc(M.st.name[l.to])} · ${durShort(l.arr - l.dep)}</span></div>`;
          }
          prevArr = l.arr;
        }
        html += '</div>';
      }
    }
  }
  return html;
}
export function edgeTip(A, e) {
  const M = A.M, code = M.edges.code[e];
  const L = M.lines[code];
  const f = A.flowFull;
  const v = [f[0][e], f[1][e], f[2][e]];
  const tot = v[0] + v[1] + v[2];
  return `<div class="h"><i style="--c:#9db0cc;background:#9db0cc"></i>${esc(L.n || 'Line ' + L.c)}</div><div class="s">${L.g ? 'High-speed line · ' : ''}RFN line ${L.c}</div>` +
    `<div class="big2">${fmtInt(tot)} <span style="font:12px var(--font);color:var(--text-2)">trains / day</span></div>` +
    (tot ? `<div class="s">${CATS.map((c, i) => `<span style="color:${c.color}">●</span> ${c.name} ${v[i]}`).join('  ')}</div>` : '<div class="s">No scheduled passenger service</div>');
}

// ====================================================================== details (right)
let detail = null; // {type, id, refs}
const right = () => $('right');

export function closeDetail(A) {
  right().hidden = true; right().innerHTML = '';
  $('app').classList.remove('has-right');
  detail = null;
  A.setInsets();
}
function openDetail(A) {
  right().hidden = false;
  $('app').classList.add('has-right');
  A.setInsets();
}

function routeLength(M, tr) {
  let m = 0;
  for (const l of tr.legs) m += getLeg(M, l).len;
  return m;
}

export function showTrain(A, ti) {
  const M = A.M, D = A.D, tr = D.trips[ti], c = CATS[tr.cat];
  const km = routeLength(M, tr) / 1000;
  const durS = tr.end - tr.start;
  const nStops = tr.fl.reduce((a, f) => a + (f === 3 ? 0 : 1), 0);
  const o = M.st.name[tr.st[0]], d = M.st.name[tr.st[tr.st.length - 1]];
  const box = right();
  box.innerHTML = '';
  const card = el('div', { class: 'card', style: { '--c': c.color } });
  const hd = el('div', { class: 'dh' });
  hd.innerHTML = `<button class="x" aria-label="Close">×</button><span class="badge"><i></i>${esc(tr.brand)} · ${esc(tr.num)}</span><h3>${esc(o)} <span style="color:var(--muted)">→</span> ${esc(d)}</h3><div class="sub">${esc([tr.rshort, tr.rlong].filter(Boolean).join(' · ') || 'Scheduled passenger service')} · ${tr.o === -1 ? 'started the previous evening' : tr.o === 1 ? 'next-day service' : dayLabel(D)}</div>`;
  hd.querySelector('.x').onclick = () => A.deselect();
  card.append(hd);
  card.append(el('div', { class: 'kv', html: `<div><small>Departs</small><b>${hm(tr.start)}</b></div><div><small>Arrives</small><b>${hm(tr.end)}</b></div><div><small>Duration</small><b>${dur(durS)}</b></div>` }));
  const pr = el('div', { class: 'progress', html: `<div class="pt"><span id="pgText">—</span><span class="num" id="pgSpeed"></span></div><div class="pb"><i id="pgBar"></i></div>` });
  card.append(pr);
  const act = el('div', { class: 'actions' });
  const follow = el('button', { class: 'chip', text: 'Follow train', onclick: () => A.toggleFollow() });
  if (A.prevStation >= 0) act.append(el('button', { class: 'chip', text: '← ' + M.st.name[A.prevStation], onclick: () => A.selectStation(A.prevStation, {}) }));
  act.append(follow, el('button', { class: 'chip', text: 'Zoom to route', onclick: () => A.zoomToTrip(ti) }),
    el('span', { class: 'chip', style: { cursor: 'default', border: '0', background: 'none', color: 'var(--muted)' }, text: `${fmtInt(km)} km · ${nStops} stops · avg ${fmtInt(km / (durS / 3600))} km/h` }));
  card.append(act);
  const tt = el('div', { class: 'tt', id: 'tt' });
  const rows = [];
  for (let i = 0; i < tr.st.length; i++) {
    const s = tr.st[i];
    const pass = tr.fl[i] === 3;
    const noBoard = tr.fl[i] & 1, noAlight = tr.fl[i] & 2;
    const dwell = tr.dep[i] - tr.arr[i];
    const row = el('div', { class: 'stop' + (pass ? ' pass' : '') + (i === 0 || i === tr.st.length - 1 ? ' end' : '') });
    let tm = '';
    if (i === 0) tm = `<b>${hm(tr.dep[i])}</b>`;
    else if (i === tr.st.length - 1) tm = `<b>${hm(tr.arr[i])}</b>`;
    else if (dwell >= 60) tm = `<b>${hm(tr.arr[i])}</b><s>${hm(tr.dep[i])}</s>`;
    else tm = `<b>${hm(tr.arr[i])}</b>`;
    const meta = pass ? 'Passes without stopping' : [dwell >= 60 && i > 0 && i < tr.st.length - 1 ? `Stops ${durShort(dwell)}` : '', noBoard && i > 0 && i < tr.st.length - 1 ? 'Set-down only' : '', noAlight && i > 0 && i < tr.st.length - 1 ? 'Pick-up only' : ''].filter(Boolean).join(' · ');
    row.innerHTML = `<div class="tm">${tm}</div><div class="rail"></div><div class="nm"><button class="st">${esc(M.st.name[s])}</button>${meta ? `<div class="meta">${meta}</div>` : ''}<div class="cx"></div></div>`;
    row.querySelector('.st').onclick = () => A.selectStation(s, { fly: true, keepTrip: true });
    if (!pass && i > 0 && !noAlight) {
      const list = connectionsAt(D, tr, i);
      if (list.total) {
        const btn = el('button', { class: 'conn-btn', html: `↔ ${list.total >= 40 ? '40+' : list.total} connection${list.total === 1 ? '' : 's'}` });
        btn.onclick = () => {
          const cx = row.querySelector('.cx');
          if (cx.firstChild) { cx.innerHTML = ''; btn.classList.remove('open'); return; }
          btn.classList.add('open');
          cx.append(connList(A, tr, i, list.items));
        };
        row.querySelector('.cx').before(btn);
      }
    }
    rows.push(row); tt.append(row);
  }
  card.append(tt);
  box.append(card);
  detail = { type: 'train', id: ti, rows, follow };
  openDetail(A);
  updateDetailLive(A, true);
}

/** onward connections at stop i of trip tr: departures of other trains [arr+5 min, arr+90 min] */
function connectionsAt(D, tr, i) {
  const s = tr.st[i];
  const a = tr.arr[i];
  const dl = D.deps[s];
  const items = [];
  let k = lowerIdx(dl.t, a + MIN_TRANSFER);
  let total = 0;
  for (; k < dl.t.length && dl.t[k] <= a + 5400; k++) {
    const ref = dl.ref[k];
    const ti = ref >> 8;
    if (ti === tr.i) continue;
    const t2 = D.trips[ti];
    // skip the same train continuing (same number)
    if (t2.num === tr.num && t2.brand === tr.brand) continue;
    total++;
    if (items.length < 12) items.push({ ti, idx: ref & 255, t: dl.t[k] });
  }
  return { total, items };
}
function connList(A, tr, i, items) {
  const M = A.M, D = A.D;
  const box = el('div', { class: 'conns' });
  for (const it of items) {
    const t2 = D.trips[it.ti], c = CATS[t2.cat];
    const b = el('button', { style: { '--c': c.color } });
    b.innerHTML = `<span class="t">${hm(it.t)}</span><span class="d"></span><span class="l">${esc(t2.brand)} ${esc(t2.num)} → ${esc(M.st.name[t2.st[t2.st.length - 1]])}</span><span class="w">+${durShort(it.t - tr.arr[i])}</span>`;
    b.onclick = () => A.selectTrip(it.ti, { fly: false });
    box.append(b);
  }
  return box;
}

export function showStation(A, s) {
  const M = A.M, D = A.D;
  const box = right();
  box.innerHTML = '';
  const nc = [D.nCalls[s * 3], D.nCalls[s * 3 + 1], D.nCalls[s * 3 + 2]];
  const tot = nc[0] + nc[1] + nc[2];
  const card = el('div', { class: 'card', style: { '--c': '#ffffff' } });
  const hd = el('div', { class: 'dh' });
  const segTxt = { A: 'National interest station', B: 'Regional interest station', C: 'Local interest station' }[M.st.seg[s]] || 'Passenger station';
  hd.innerHTML = `<button class="x" aria-label="Close">×</button><span class="badge" style="--c:#cfe0ff"><i></i>STATION · UIC ${esc(M.st.uic[s])}</span><h3>${esc(M.st.name[s])}</h3><div class="sub">${esc([M.st.commune[s], M.st.dept[s]].filter(Boolean).join(', ') || M.st.cc[s])} · ${segTxt}</div>`;
  hd.querySelector('.x').onclick = () => A.deselect();
  card.append(hd);
  card.append(el('div', { class: 'kv', html: `<div><small>Trains / day</small><b>${fmtInt(tot)}</b></div><div><small>Mix</small><b style="font-size:12px">${CATS.map((c, i) => `<span style="color:${c.color}">${nc[i]}</span>`).join(' · ')}</b></div><div><small>Busiest hour</small><b id="bh">—</b></div>` }));
  // hourly histogram
  const hours = new Int32Array(24);
  const cl = D.calls[s];
  for (let i = 0; i < cl.length; i++) { const t = (cl[i] >> 2) - 86400; if (t >= 0 && t < 86400) hours[(t / 3600) | 0]++; }
  const mx = Math.max(1, ...hours);
  const bh = hours.indexOf(Math.max(...hours));
  card.querySelector('#bh').textContent = String(bh).padStart(2, '0') + ':00';
  const hist = el('div', { class: 'hist', title: 'Train calls per hour' });
  for (let h = 0; h < 24; h++) hist.append(el('i', { style: { height: Math.max(2, hours[h] / mx * 36) + 'px' }, title: `${String(h).padStart(2, '0')}:00 · ${hours[h]} calls` }));
  card.append(hist);
  card.append(el('div', { class: 'hist-l', html: '<span>00</span><span>06</span><span>12</span><span>18</span><span>24</span>' }));
  const act = el('div', { class: 'actions' });
  if (A.S.mode !== 'access') act.append(el('button', { class: 'chip on', text: 'Travel times from here →', onclick: () => A.accessFrom(s) }));
  else act.append(el('button', { class: 'chip', text: 'Origin of the travel-time map', style: { cursor: 'default' } }));
  act.append(el('button', { class: 'chip', text: 'Zoom to station', onclick: () => A.flyToStation(s) }));
  card.append(act);
  const tabs = el('div', { class: 'tabs', html: '<button data-m="dep" class="on">Departures</button><button data-m="arr">Arrivals</button>' });
  card.append(tabs);
  const board = el('div', { class: 'board', id: 'board' });
  card.append(board);
  box.append(card);
  detail = { type: 'station', id: s, mode: 'dep', hours, hist, lastT: -1e9 };
  tabs.querySelectorAll('button').forEach((b) => b.onclick = () => {
    detail.mode = b.dataset.m; detail.lastT = -1e9;
    tabs.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    updateDetailLive(A, true);
  });
  openDetail(A);
  updateDetailLive(A, true);
}

const _st = {};
export function updateDetailLive(A, force) {
  if (!detail) return;
  const { M, D, S } = A;
  if (detail.type === 'train') {
    const tr = D.trips[detail.id];
    const rows = detail.rows;
    const t = S.t;
    let cur = -1, doneUpTo = -1, text = '', speed = '', frac = 0;
    if (t < tr.start) { text = `Departs in ${dur(tr.start - t)} · ${hm(tr.start)}`; }
    else if (t > tr.end) { text = `Arrived ${hm(tr.end)} · journey complete`; doneUpTo = rows.length; frac = 1; }
    else if (trainState(M, tr, t, _st)) {
      if (_st.moving) {
        const i = _st.seg;
        doneUpTo = i; // rows <= i done
        const a = M.st.name[tr.st[i]], b = M.st.name[tr.st[i + 1]];
        text = `<b>${esc(a)}</b> → <b>${esc(b)}</b> · arrives ${hm(tr.arr[i + 1])}`;
        const leg = getLeg(M, tr.legs[i]);
        const secs = Math.max(1, tr.arr[i + 1] - tr.dep[i]);
        speed = Math.round(leg.len / secs * 3.6) + ' km/h';
        frac = (i + _st.u) / (tr.st.length - 1);
      } else {
        const j = _st.stop;
        cur = j; doneUpTo = j - 1;
        text = j === tr.st.length - 1 ? `Arrived at <b>${esc(M.st.name[tr.st[j]])}</b>` : `At <b>${esc(M.st.name[tr.st[j]])}</b> · departs ${hm(tr.dep[j])}`;
        frac = j / (tr.st.length - 1);
      }
    }
    for (let i = 0; i < rows.length; i++) {
      rows[i].classList.toggle('done', i <= doneUpTo);
      rows[i].classList.toggle('cur', i === cur);
    }
    $('pgText').innerHTML = text;
    $('pgSpeed').textContent = speed;
    $('pgBar').style.width = (frac * 100).toFixed(1) + '%';
    // keep the active stop in view
    const key = cur >= 0 ? cur : doneUpTo;
    if (key !== detail.lastKey && key >= 0 && rows[Math.min(rows.length - 1, key + 1)]) {
      detail.lastKey = key;
      const host = $('tt'), r = rows[Math.min(rows.length - 1, key)];
      host.scrollTo({ top: r.offsetTop - host.clientHeight / 3, behavior: force ? 'auto' : 'smooth' });
    }
    if (detail.follow) detail.follow.classList.toggle('on', !!S.follow);
  } else if (detail.type === 'station') {
    if (!force && Math.abs(S.t - detail.lastT) < 60) return;
    detail.lastT = S.t;
    const s = detail.id, list = detail.mode === 'dep' ? D.deps[s] : D.arrs[s];
    const board = $('board');
    const now = S.t;
    const hrNow = Math.floor(now / 3600);
    [...detail.hist.children].forEach((b, h) => b.classList.toggle('now', h === hrNow));
    const i0 = Math.max(0, lowerIdx(list.t, now) - 3);
    let html = '';
    let sep = false, count = 0;
    for (let k = i0; k < list.t.length && count < 60; k++) {
      const t = list.t[k];
      if (t >= 86400 + 4 * 3600) break;
      const ref = list.ref[k], tr = D.trips[ref >> 8], c = CATS[tr.cat];
      if (!sep && t >= now) { html += '<div class="sep">now · ' + hm(now) + '</div>'; sep = true; }
      const far = detail.mode === 'dep' ? tr.st[tr.st.length - 1] : tr.st[0];
      const nextI = (ref & 255) + (detail.mode === 'dep' ? 1 : -1);
      const via = tr.st[Math.max(0, Math.min(tr.st.length - 1, nextI))];
      html += `<button data-ti="${tr.i}" style="--c:${c.color}" class="${t < now ? 'past' : ''}"><span class="t">${hm(t)}${t >= 86400 ? '<sup style="color:var(--muted)">+1</sup>' : ''}</span><span class="d"></span><span class="to">${detail.mode === 'dep' ? '' : 'from '}${esc(M.st.name[far])}<small>${esc(tr.brand)} ${esc(tr.num)}${via !== far ? ' · ' + (detail.mode === 'dep' ? 'next ' : 'prev ') + esc(M.st.name[via]) : ''}</small></span></button>`;
      count++;
    }
    if (!sep) html += '<div class="sep">no more services today</div>';
    board.innerHTML = html;
    board.querySelectorAll('button').forEach((b) => b.onclick = () => A.selectTrip(+b.dataset.ti, { fly: false, fromStation: s }));
    const sepEl = board.querySelector('.sep');
    if (sepEl) board.scrollTop = Math.max(0, sepEl.offsetTop - 80);
  }
}
export function detailType() { return detail ? detail.type : null; }
export function resetDetail() { detail = null; }

// ====================================================================== hint
let hintTimer = 0;
export function hint(html, ms = 5000) {
  const h = $('hint');
  h.innerHTML = html; h.classList.add('on');
  clearTimeout(hintTimer);
  if (ms) hintTimer = setTimeout(() => h.classList.remove('on'), ms);
}
export function hideHint() { $('hint').classList.remove('on'); }

// ====================================================================== search
export function initSearch(A) {
  const q = $('q'), res = $('results');
  let items = [], act = -1;
  const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const run = () => {
    const v = norm(q.value.trim());
    items = [];
    if (v.length >= 1) {
      const M = A.M, D = A.D;
      const st = [];
      for (let s = 0; s < M.st.n; s++) {
        const n = norm(M.st.name[s]);
        const p = n.startsWith(v) ? 0 : n.split(/[\s-]+/).some((w) => w.startsWith(v)) ? 1 : n.includes(v) ? 2 : -1;
        if (p >= 0) st.push([p, -D.callsTotal[s], s]);
      }
      st.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      for (const [, , s] of st.slice(0, 8)) items.push({ type: 's', s, label: M.st.name[s], sub: `${fmtInt(D.callsTotal[s])} trains / day` });
      if (/^\d+/.test(v)) {
        const seen = new Set();
        for (const t of D.trips) {
          if (t.o !== 0 || !t.num.startsWith(v) || seen.has(t.num)) continue;
          seen.add(t.num);
          items.push({ type: 't', ti: t.i, label: `${t.brand} ${t.num}`, sub: tripLabel(A.M, t), cat: t.cat });
          if (seen.size >= 6) break;
        }
      }
    }
    act = items.length ? 0 : -1;
    res.innerHTML = '';
    items.forEach((it, i) => {
      const b = el('button', { class: i === act ? 'act' : '', role: 'option' });
      b.innerHTML = it.type === 's'
        ? `<span style="color:#cfe0ff">◉</span><span>${esc(it.label)}</span><small>${esc(it.sub)}</small>`
        : `<span style="color:${CATS[it.cat].color}">▮</span><span>${esc(it.label)}<br><small style="margin:0">${esc(it.sub)}</small></span>`;
      b.onmousedown = (e) => { e.preventDefault(); pick(it); };
      res.append(b);
    });
    res.classList.toggle('open', items.length > 0);
  };
  const pick = (it) => {
    res.classList.remove('open'); q.blur(); q.value = '';
    if (it.type === 's') A.selectStation(it.s, { fly: true }); else A.selectTrip(it.ti, { fly: true });
  };
  q.addEventListener('input', run);
  q.addEventListener('focus', run);
  q.addEventListener('blur', () => setTimeout(() => res.classList.remove('open'), 120));
  q.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      act = (act + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % Math.max(1, items.length);
      [...res.children].forEach((c, i) => c.classList.toggle('act', i === act));
    } else if (e.key === 'Enter' && items[act]) pick(items[act]);
    else if (e.key === 'Escape') { q.value = ''; q.blur(); }
  });
}

// ====================================================================== collapsible cards
export function initCollapsible() {
  document.querySelectorAll('#left .card').forEach((card) => {
    if (card.dataset.col) return;
    card.dataset.col = '1';
    card.addEventListener('click', (e) => {
      const h = e.target.closest('h2');
      if (!h || !card.contains(h) || e.target.closest('.seg') || e.target.closest('button')) return;
      card.classList.toggle('collapsed');
    });
  });
}
export function setCollapsed(id, v) { const c = $(id); if (c) c.classList.toggle('collapsed', v); }
