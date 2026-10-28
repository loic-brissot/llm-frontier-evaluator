// Application orchestrator: state, animation loop, input handling.
import { CATS, BANDS, clamp } from './util.js';
import { loadStatic, loadDay, computeFlow, trainState } from './data.js';
import { Camera } from './camera.js';
import { Renderer } from './render.js';
import { Router } from './csa.js';
import * as UI from './ui.js';

const $ = (id) => document.getElementById(id);
const FRANCE_BBOX = [95000, 35000, 1290000, 1130000];

const S = {
  mode: 'live', day: 'tue', t: 7.75 * 3600, playing: true, speed: 240,
  enabled: [true, true, true], hoverCat: -1,
  selTrip: -1, selStation: -1, hoverTrip: -1, hoverStation: -1, hoverEdge: -1, hoverCode: -1,
  showTrains: false, flowMode: 'full', origin: -1, journey: null, follow: false, selPos: null,
};

const A = { S, M: null, D: null, cam: null, rend: null, router: null, scrubbing: false, prevStation: -1, flowDirty: true, flowTot: null, flowFull: null };
window.__atlas = A; // handy for debugging in the console

let baseDirty = true, lastCamVersion = -1, seenCamVersion = -1;

// ------------------------------------------------------------------ boot
async function boot() {
  const bar = $('loadBar');
  const M = await loadStatic((p) => { bar.style.width = (p * 55) + '%'; });
  A.M = M;
  const cam = new Camera($('stage'));
  A.cam = cam;
  const rend = new Renderer(M, $('base'), $('dyn'), cam);
  A.rend = rend;
  resize();
  cam.setHome(FRANCE_BBOX);
  window.addEventListener('resize', () => { resize(); });
  bar.style.width = '70%';
  await applyDay(S.day, true);
  bar.style.width = '100%';

  UI.initTimeline(A);
  UI.initDays(A);
  UI.initBusy(A);
  UI.initSearch(A);
  UI.initCollapsible();
  UI.initAbout();
  UI.markDay(A);
  UI.markMode(A);
  bindInput();
  setMode('live', {}, true);
  A.setInsets();
  cam.setHome(FRANCE_BBOX);
  requestAnimationFrame(frame);
  // intro: ease in from slightly farther out
  cam.jump(cam.home.x, cam.home.y, cam.home.s * 0.72);
  cam.goHome();
  if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) S.playing = false;
  setTimeout(() => $('loader').classList.add('done'), 250);
  UI.hint('Drag to pan · scroll to zoom · <b>click</b> a train or a station for its timetable', 7000);
}

async function applyDay(key, first) {
  const D = await loadDay(A.M, key);
  S.day = key;
  A.D = D;
  D.flowFull = computeFlow(A.M, D, null);
  A.flowFull = D.flowFull;
  A.rend.setDay(D);
  A.rend.invalidatePlain();
  const wait = A.router ? A.router.includeWait : false;
  A.router = new Router(A.M, D);
  A.router.includeWait = wait;
  A.flowDirty = true;
  if (!first) {
    S.selTrip = -1; S.selStation = -1; S.hoverTrip = -1; S.hoverStation = -1; S.journey = null; S.follow = false; A.cam.follow = null;
    UI.closeDetail(A);
    UI.markDay(A);
    UI.drawScrub(A);
    UI.buildProfile(A);
    A._busySig = '';
    setMode(S.mode, { origin: S.origin }, true);
  } else {
    UI.buildProfile(A);
  }
  if (S.origin < 0) S.origin = defaultOrigin();
  baseDirty = true;
}

function defaultOrigin() {
  const M = A.M;
  const i = M.st.name.indexOf('Lyon Part Dieu');
  return i >= 0 ? i : A.rend.rank.indexOf(0);
}

// ------------------------------------------------------------------ layout
A.setInsets = () => {
  const cam = A.cam;
  const old = cam.ox;
  const vw = window.innerWidth;
  cam.inset.left = vw > 900 ? 362 : 0;
  cam.inset.right = !$('right').hidden && vw > 900 ? 392 : 0;
  cam.inset.top = 58; cam.inset.bottom = 104;
  const d = cam.ox - old;
  if (d) { cam.cx += d / cam.scale; cam.tcx += d / cam.tscale; cam.version++; }
  baseDirty = true;
};
function resize() {
  const W = window.innerWidth, H = window.innerHeight;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  A.rend.resize(W, H, dpr);
  A.cam.resize(W, H);
  if (A.cam.home) { A.setInsets(); }
  baseDirty = true;
  if (A.D) UI.drawScrub(A);
}

// ------------------------------------------------------------------ actions
A.dirtyDyn = () => {};
A.dirtyBase = () => { baseDirty = true; };
A.togglePlay = () => { S.playing = !S.playing; UI.updateClock(A); };
A.setSpeed = (v) => { S.speed = v; A.markSpeed(); if (!S.playing) { S.playing = true; } };
A.setTime = (t) => { S.t = ((t % 86400) + 86400) % 86400; accessDirty = true; uiTick(true); };
A.toggleCat = (i, only) => {
  if (only) {
    const sole = S.enabled.every((e, k) => (k === i ? e : !e));
    S.enabled = sole ? [true, true, true] : CATS.map((_, k) => k === i);
  } else {
    S.enabled[i] = !S.enabled[i];
    if (!S.enabled.some(Boolean)) S.enabled = [true, true, true];
  }
  UI.catStates(A);
  if (S.mode === 'flow') refreshFlow(true);
  A._busySig = '';
  UI.updateBusy(A);
  baseDirty = true;
};
A.toggleWait = () => { A.router.includeWait = !A.router.includeWait; $('chipWait').classList.toggle('on', A.router.includeWait); recomputeAccess(); };
A.toggleShowTrains = () => { S.showTrains = !S.showTrains; $('chipTrains').classList.toggle('on', S.showTrains); };
A.setFlowMode = (m) => {
  S.flowMode = m;
  document.querySelectorAll('#flowMode button').forEach((b) => b.classList.toggle('on', b.dataset.m === m));
  if (m === 'cum' && S.t < 600) S.t = 600;
  refreshFlow(true);
};
A.setDay = (key) => { if (key !== S.day) { $('loader').classList.remove('done'); applyDay(key).then(() => setTimeout(() => $('loader').classList.add('done'), 150)); } };
A.setMode = (m, o) => setMode(m, o);

function setMode(m, opts = {}, force) {
  if (m === S.mode && !force) return;
  S.mode = m;
  S.hoverEdge = -1; S.hoverCode = -1; S.journey = null; S.hoverStation = -1;
  S.showTrains = false;
  UI.markMode(A);
  UI.buildMainCard(A);
  UI.hideHint();
  if (m === 'access') {
    if (opts.origin != null && opts.origin >= 0) S.origin = opts.origin;
    if (S.origin < 0) S.origin = defaultOrigin();
    if (S.playing && !force) { S.playing = false; }
    S.selStation = S.origin; S.selTrip = -1;
    UI.showStation(A, S.origin);
    recomputeAccess();
    UI.hint('<b>Click any station</b> to compute rail travel times from it · hover for the itinerary · scrub the clock to change the departure time', 9000);
  } else {
    if (m === 'flow') {
      refreshFlow(true);
      UI.hint('Line <b>weight</b> and <b>brightness</b> scale with the number of trains over 24 hours · hover a line for details', 8000);
    }
    if (S.selStation >= 0 && UI.detailType() === 'station') UI.showStation(A, S.selStation);
  }
  UI.updateMainCard(A, true);
  UI.catStates(A);
  UI.setCollapsed('cardBusy', m !== 'live' && window.innerHeight < 860);
  baseDirty = true;
}

function refreshFlow(force) {
  const { M, D } = A;
  let counts, tot;
  if (S.flowMode === 'full') {
    counts = D.flowFull; tot = A.perDay;
  } else {
    counts = computeFlow(M, D, S.t);
    tot = [0, 0, 0];
    for (const t of D.trips) if (t.o !== 1 && t.start <= S.t && t.end >= 0 && t.start >= 0) tot[t.cat]++;
  }
  A.flowTot = tot;
  A.rend.setFlow(counts, S.enabled);
  A.flowDirty = true;
  A._flowT = S.t;
  baseDirty = true;
  if (force) UI.updateMainCard(A, true);
}

let accessDirty = false, lastAccessRun = 0;
function recomputeAccess() {
  if (S.origin < 0) return;
  A.router.run(S.origin, S.t);
  A.rend.setAccess(A.router);
  accessDirty = false;
  lastAccessRun = performance.now();
  baseDirty = true;
  UI.updateMainCard(A, true);
  if (S.hoverStation >= 0) S.journey = A.router.journey(S.hoverStation);
}

A.selectTrip = (ti, o = {}) => {
  const D = A.D, tr = D.trips[ti];
  A.prevStation = o.fromStation != null ? o.fromStation : -1;
  S.selTrip = ti; S.selStation = A.prevStation >= 0 ? A.prevStation : -1;
  S.follow = false; A.cam.follow = null;
  if (o.fly && (S.t < tr.start || S.t > tr.end)) A.setTime(tr.start + 120);
  UI.showTrain(A, ti);
  if (o.fly) A.zoomToTrip(ti);
};
A.selectStation = (s, o = {}) => {
  if (!o.keepTrip) { S.selTrip = -1; }
  else { /* keep the route drawn while looking at a stop */ }
  A.prevStation = -1;
  S.selStation = s;
  S.follow = false; A.cam.follow = null;
  UI.showStation(A, s);
  if (o.fly) A.flyToStation(s);
};
A.flyToStation = (s) => A.cam.flyTo(A.M.st.x[s], A.M.st.y[s], Math.max(A.cam.tscale, A.cam.fitScale * 7));
A.deselect = () => {
  S.selTrip = -1; S.selStation = S.mode === 'access' ? -1 : -1; S.follow = false; A.cam.follow = null;
  UI.closeDetail(A);
};
A.accessFrom = (s) => { S.origin = s; setMode('access', { origin: s }); };
A.toggleFollow = () => {
  S.follow = !S.follow;
  A.cam.follow = S.follow ? () => S.selPos : null;
  if (S.follow) A.cam.flyTo(S.selPos ? S.selPos.x : A.cam.tcx, S.selPos ? S.selPos.y : A.cam.tcy, Math.max(A.cam.tscale, A.cam.fitScale * 9));
};
A.zoomToTrip = (ti) => {
  const { M, D } = A, tr = D.trips[ti];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const s of tr.st) { x0 = Math.min(x0, M.st.x[s]); x1 = Math.max(x1, M.st.x[s]); y0 = Math.min(y0, M.st.y[s]); y1 = Math.max(y1, M.st.y[s]); }
  const pad = Math.max(8000, (x1 - x0 + y1 - y0) * 0.04);
  A.cam.flyToBBox([x0 - pad, y0 - pad, x1 + pad, y1 + pad], 80);
};
A.zoomToCode = (code) => {
  const M = A.M, E = M.edges;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const e of M.edgesOfCode[code]) { x0 = Math.min(x0, E.bbox[4 * e]); y0 = Math.min(y0, E.bbox[4 * e + 1]); x1 = Math.max(x1, E.bbox[4 * e + 2]); y1 = Math.max(y1, E.bbox[4 * e + 3]); }
  if (x0 < Infinity) A.cam.flyToBBox([x0, y0, x1, y1], 90);
};

// ------------------------------------------------------------------ input
const mouse = { x: -1, y: -1, inside: false, moved: false };
function bindInput() {
  const stage = $('stage');
  stage.addEventListener('pointermove', (e) => { const r = stage.getBoundingClientRect(); mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top; mouse.inside = true; mouse.moved = true; stage.classList.toggle('drag', A.cam.dragging); });
  stage.addEventListener('pointerleave', () => { mouse.inside = false; mouse.moved = true; });
  stage.addEventListener('click', (e) => {
    if (A.cam.moved > 4) return;
    const r = stage.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const tr = A.rend.pickTrain(x, y);
    if (tr >= 0) { A.selectTrip(tr, {}); return; }
    const st = A.rend.pickStation(x, y, S);
    if (st >= 0) {
      if (S.mode === 'access') { S.origin = st; S.selStation = st; S.selTrip = -1; UI.showStation(A, st); recomputeAccess(); UI.hideHint(); }
      else A.selectStation(st, {});
      return;
    }
    if (S.selTrip >= 0 || S.selStation >= 0) { if (S.mode === 'access') return; A.deselect(); }
  });
  document.querySelectorAll('#modes button').forEach((b) => b.onclick = () => setMode(b.dataset.mode));
  $('zin').onclick = () => A.cam.zoomAt(A.cam.W / 2 + A.cam.ox, A.cam.H / 2 + A.cam.oy, 1.7);
  $('zout').onclick = () => A.cam.zoomAt(A.cam.W / 2 + A.cam.ox, A.cam.H / 2 + A.cam.oy, 1 / 1.7);
  $('zhome').onclick = () => A.cam.goHome();
  window.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input') return;
    if (e.target.id === 'scrub' && e.key.startsWith('Arrow')) return;
    if (e.key === ' ') { e.preventDefault(); A.togglePlay(); }
    else if (e.key === '/') { e.preventDefault(); $('q').focus(); }
    else if (e.key === 'Escape') { A.deselect(); $('about').hidden = true; }
    else if (e.key === 'l' || e.key === 'L') setMode('live');
    else if (e.key === 'a' || e.key === 'A') setMode('access');
    else if (e.key === 'f' || e.key === 'F') setMode('flow');
    else if (e.key === '1' || e.key === '2' || e.key === '3') A.toggleCat(+e.key - 1, false);
    else if (e.key === 'ArrowRight') A.setTime(S.t + (e.shiftKey ? 3600 : 600));
    else if (e.key === 'ArrowLeft') A.setTime(S.t - (e.shiftKey ? 3600 : 600));
    else if (e.key === '+' || e.key === '=') $('zin').click();
    else if (e.key === '-') $('zout').click();
  });
}

function updateHover() {
  const rend = A.rend;
  let tip = null;
  const stage = $('stage');
  S.hoverTrip = -1; S.hoverEdge = -1;
  let hs = -1;
  if (mouse.inside && !A.cam.dragging) {
    const tr = rend.pickTrain(mouse.x, mouse.y);
    if (tr >= 0) { S.hoverTrip = tr; tip = UI.trainTip(A, A.D.trips[tr]); }
    else {
      hs = rend.pickStation(mouse.x, mouse.y, S);
      if (hs >= 0) {
        if (S.mode === 'access' && A.router) {
          if (hs !== S.hoverStation) S.journey = A.router.journey(hs);
        } else S.journey = null;
        tip = UI.stationTip(A, hs);
      } else {
        S.journey = null;
        const e = rend.pickEdge(mouse.x, mouse.y);
        if (e >= 0) { S.hoverEdge = e; tip = UI.edgeTip(A, e); }
      }
    }
  } else S.journey = null;
  S.hoverStation = hs;
  stage.classList.toggle('pointer', tip != null && S.hoverEdge < 0);
  if (tip) UI.showTip(mouse.x, mouse.y, tip); else UI.hideTip();
}

// ------------------------------------------------------------------ loop
let last = performance.now(), uiAcc = 0, lastClockSec = -1, lastBase = 0, lastCamChange = 0, camPending = false;
function uiTick(force) {
  UI.updateClock(A);
  UI.updateProfile(A);
  if (force) { UI.updateMainCard(A); UI.updateBusy(A); UI.updateDetailLive(A, false); }
}
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  if (S.playing && !A.scrubbing) {
    S.t += dt * S.speed;
    if (S.t >= 86400) S.t -= 86400;
  }
  const camMoved = A.cam.update(dt);
  const camChanged = A.cam.version !== seenCamVersion;
  seenCamVersion = A.cam.version;
  // mode dependent recomputation (throttled)
  if (S.mode === 'access' && (accessDirty || Math.abs(S.t - A.router.T) >= 45) && now - lastAccessRun > 160) recomputeAccess();
  if (S.mode === 'flow' && S.flowMode === 'cum' && Math.abs(S.t - (A._flowT ?? -1e9)) >= 90 && now - (A._flowRun || 0) > 200) { A._flowRun = now; refreshFlow(); }
  if (baseDirty) { A.rend.drawBase(S); baseDirty = false; lastCamVersion = A.cam.version; lastBase = now; camPending = false; }
  else if (camChanged) {
    // moving camera: reuse the cached base bitmap, re-render at most every ~160 ms
    A.rend.transformBase();
    lastCamChange = now; camPending = true;
    if (now - lastBase > 160) { A.rend.drawBase(S); lastCamVersion = A.cam.version; lastBase = now; camPending = false; }
  } else if (camPending && now - lastCamChange > 70) {
    A.rend.drawBase(S); lastBase = now; camPending = false; lastCamVersion = A.cam.version;
  }
  if (mouse.moved || S.playing || camMoved || accessDirty) { updateHover(); mouse.moved = false; }
  A.rend.drawDyn(S, now);
  const sec = Math.floor(S.t);
  if (sec !== lastClockSec) { lastClockSec = sec; UI.updateClock(A); UI.updateProfile(A); }
  uiAcc += dt;
  if (uiAcc > 0.25) {
    uiAcc = 0;
    UI.updateMainCard(A);
    UI.updateBusy(A);
    UI.updateDetailLive(A, false);
  }
  requestAnimationFrame(frame);
}

boot().catch((e) => {
  console.error(e);
  $('loadMsg').textContent = 'Failed to load: ' + e.message;
});
