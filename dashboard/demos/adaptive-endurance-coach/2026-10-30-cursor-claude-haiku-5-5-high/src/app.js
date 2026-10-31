// UI controller: profile editor, zone computation, plan views, adaptation, export.

import {
  DISCIPLINES, RACE_TYPES, powerZones, hrZones, runningPaceZones, swimZones,
  vdotFromRace, cssFromTimes, cssSecPer100m, secPerKmToString, secPer100mToString,
  hmsToSeconds, thresholdPaceSecPerKm, readiness, addDays, daysBetween,
} from './physiology.js';
import { generatePlan, adaptPlan, weekSummaries, validateProfileForDiscipline } from './planner.js';
import { renderIntervalProfile, renderPmc, escapeText, ZONE_COLORS } from './render.js';
import { toIcs, toZwo } from './export.js';

// ---------- State ----------

const state = {
  profile: {
    name: 'Athlete',
    discipline: 'triathlon',
    raceType: 'olympic_tri',
    startDate: todayIso(),
    raceDate: addDays(todayIso(), 14 * 7),
    ftp: 255,
    weightKg: 72,
    vo2max: 56,
    raceMode: 'vo2',          // 'vo2' | 'race'
    racePreset: '5k',
    raceTimeSec: hmsToSeconds(0, 20, 30),
    lthr: 165,
    restingHr: 48,
    maxHr: 186,
    t400: 360,
    t200: 170,
    hoursPerWeek: 9,
    sessionsPerWeek: 6,
  },
  plan: null,
  adapted: null,
  statuses: {},
  illnessDays: [],
  availability: {},
  view: 'plan',
  selectedWorkoutId: null,
  mesoOffset: 0,
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

// ---------- Derived physiology ----------

function derived(p) {
  const vdot = p.raceMode === 'vo2'
    ? p.vo2max
    : vdotFromRace(RACE_PRESETS[p.racePreset].m, p.raceTimeSec);
  const css = cssFromTimes(p.t400, p.t200);
  return {
    vdot,
    power: powerZones(p.ftp),
    wkg: p.ftp / p.weightKg,
    hr: hrZones(p.lthr, p.restingHr, p.maxHr),
    run: runningPaceZones(vdot),
    thresholdPace: thresholdPaceSecPerKm(vdot),
    swim: css ? swimZones(css) : [],
    cssMps: css,
    cssPer100: css ? cssSecPer100m(css) : null,
  };
}

const RACE_PRESETS = {
  '5k': { label: '5K', m: 5000 },
  '10k': { label: '10K', m: 10000 },
  half: { label: 'Half marathon', m: 21097.5 },
  marathon: { label: 'Marathon', m: 42195 },
};

// ---------- Helpers ----------

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const fmt1 = (n) => (Number.isFinite(n) ? n.toFixed(1) : '–');
const fmt0 = (n) => (Number.isFinite(n) ? Math.round(n).toString() : '–');

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2400);
}

function download(name, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

// ---------- Profile editor ----------

function readProfileForm() {
  const v = (id) => $(`#${id}`).value;
  const n = (id) => parseFloat($(`#${id}`).value);
  const p = state.profile;
  p.name = v('name') || 'Athlete';
  p.discipline = v('discipline');
  p.raceType = v('raceType');
  p.startDate = v('startDate');
  p.raceDate = v('raceDate');
  p.ftp = n('ftp');
  p.weightKg = n('weightKg');
  p.vo2max = n('vo2max');
  p.raceMode = $('input[name="raceMode"]:checked').value;
  p.racePreset = v('racePreset');
  p.raceTimeSec = hmsToSeconds(n('raceH') || 0, n('raceM') || 0, n('raceS') || 0);
  p.lthr = n('lthr');
  p.restingHr = n('restingHr');
  p.maxHr = n('maxHr');
  p.t400 = hmsToSeconds(0, n('t400M') || 0, n('t400S') || 0);
  p.t200 = hmsToSeconds(0, n('t200M') || 0, n('t200S') || 0);
  p.hoursPerWeek = n('hoursPerWeek');
  p.sessionsPerWeek = n('sessionsPerWeek');
  return p;
}

function writeProfileForm() {
  const p = state.profile;
  const set = (id, val) => { $(`#${id}`).value = val; };
  set('name', p.name);
  set('discipline', p.discipline);
  set('raceType', p.raceType);
  set('startDate', p.startDate);
  set('raceDate', p.raceDate);
  set('ftp', p.ftp);
  set('weightKg', p.weightKg);
  set('vo2max', p.vo2max);
  set('racePreset', p.racePreset);
  const h = Math.floor(p.raceTimeSec / 3600);
  const m = Math.floor((p.raceTimeSec % 3600) / 60);
  const s = p.raceTimeSec % 60;
  set('raceH', h); set('raceM', m); set('raceS', s);
  set('lthr', p.lthr); set('restingHr', p.restingHr); set('maxHr', p.maxHr);
  set('t400M', Math.floor(p.t400 / 60)); set('t400S', p.t400 % 60);
  set('t200M', Math.floor(p.t200 / 60)); set('t200S', p.t200 % 60);
  set('hoursPerWeek', p.hoursPerWeek);
  set('sessionsPerWeek', p.sessionsPerWeek);
  $(`input[name="raceMode"][value="${p.raceMode}"]`).checked = true;
  syncRaceModeUi();
}

function syncRaceModeUi() {
  const mode = $('input[name="raceMode"]:checked').value;
  $('#vo2Field').classList.toggle('hidden', mode !== 'vo2');
  $('#raceField').classList.toggle('hidden', mode !== 'race');
}

function renderZones() {
  const p = readProfileForm();
  const d = derived(p);
  const pw = $('#powerZones');
  pw.innerHTML = d.power.map((z) => `
    <div class="zrow" style="--c:${ZONE_COLORS[z.z]}">
      <span class="zbadge">Z${z.z}</span>
      <span class="zname">${escapeText(z.name)}</span>
      <span class="zval">${z.maxW ? `${z.minW}–${z.maxW}` : `${z.minW}+`} <small>W</small></span>
    </div>`).join('');

  $('#wkg').textContent = `${fmt1(d.wkg)} W/kg`;
  $('#vdotVal').textContent = fmt1(d.vdot);

  $('#hrZones').innerHTML = d.hr.map((z) => `
    <div class="zrow" style="--c:${ZONE_COLORS[z.z]}">
      <span class="zbadge">Z${z.z}</span>
      <span class="zname">${escapeText(z.name)}</span>
      <span class="zval">${z.minBpm}–${z.maxBpm} <small>bpm</small></span>
    </div>`).join('');

  $('#runZones').innerHTML = d.run.map((z) => `
    <div class="zrow" style="--c:${ZONE_COLORS[z.z]}">
      <span class="zbadge">${z.z}</span>
      <span class="zname">${escapeText(z.name)}</span>
      <span class="zval">${secPerKmToString(z.fastSecPerKm)}–${secPerKmToString(z.slowSecPerKm)} <small>/km</small></span>
    </div>`).join('');

  $('#swimZones').innerHTML = d.swim.length
    ? d.swim.map((z) => `
    <div class="zrow" style="--c:${ZONE_COLORS[z.z === 3 ? 4 : z.z]}">
      <span class="zbadge">S${z.z}</span>
      <span class="zname">${escapeText(z.name)}</span>
      <span class="zval">${secPer100mToString(z.fastSecPer100m)}–${secPer100mToString(z.slowSecPer100m)} <small>/100m</small></span>
    </div>`).join('')
    : '<p class="muted">Enter 400 m and 200 m swim times to derive swim zones.</p>';

  $('#cssVal').textContent = d.cssPer100 ? `${secPer100mToString(d.cssPer100)} /100m` : '–';

  return d;
}

// ---------- Plan generation ----------

function buildPlanFromProfile() {
  const p = readProfileForm();
  const d = derived(p);
  const planProfile = {
    discipline: p.discipline,
    raceType: p.raceType,
    ftp: p.ftp,
    vdot: d.vdot,
    cssMps: d.cssMps,
    hoursPerWeek: p.hoursPerWeek,
    sessionsPerWeek: p.sessionsPerWeek,
    startDate: p.startDate,
    raceDate: p.raceDate,
  };
  const problems = validateProfileForDiscipline(planProfile);
  if (problems.length) {
    toast(problems[0]);
    return null;
  }
  if (daysBetween(p.startDate, p.raceDate) < 7) {
    toast('Race date must be at least a week after the start date.');
    return null;
  }
  try {
    state.plan = generatePlan(planProfile);
  } catch (e) {
    toast(e.message);
    return null;
  }
  state.adapted = null;
  state.statuses = {};
  state.illnessDays = [];
  state.availability = {};
  state.selectedWorkoutId = null;
  return state.plan;
}

function currentPlan() {
  return state.adapted || state.plan;
}

// Chart series: planned vs adapted, carrying both overlays.
function pmcSeries() {
  const plan = state.plan;
  if (!plan) return [];
  return plan.days.map((d, i) => {
    const a = state.adapted ? state.adapted.days[i] : null;
    return {
      date: d.date,
      ctl: d.pmc.ctl, atl: d.pmc.atl, tsb: d.pmc.tsb,
      originalCtl: d.pmc.ctl, originalTsb: d.pmc.tsb,
      adaptedCtl: a ? a.adaptedPmc.ctl : null,
      adaptedAtl: a ? a.adaptedPmc.atl : null,
      adaptedTsb: a ? a.adaptedPmc.tsb : null,
    };
  });
}

// ---------- Rendering: header / KPIs ----------

function renderKpis() {
  const plan = currentPlan();
  if (!plan) return;
  const series = plan.days.map((d) => (state.adapted ? d.adaptedPmc : d.pmc));
  const last = series[series.length - 1];
  const sums = weekSummaries(plan, !!state.adapted);
  const totalHours = sums.reduce((s, w) => s + w.hours, 0);
  const peakWeek = sums.reduce((a, b) => (b.tss > a.tss ? b : a));
  const planned = state.plan.days.map((d) => d.pmc);
  const plannedLast = planned[planned.length - 1];

  $('#kpiCtl').textContent = fmt0(last.ctl);
  $('#kpiCtlDelta').textContent = state.adapted ? `planned ${fmt0(plannedLast.ctl)}` : `race-day CTL`;
  $('#kpiTsb').textContent = (last.tsb >= 0 ? '+' : '') + fmt0(last.tsb);
  $('#kpiTsbState').textContent = readiness(last).replace('-', ' ');
  $('#kpiHours').textContent = fmt0(totalHours);
  $('#kpiPeak').textContent = fmt0(peakWeek.tss);
  $('#kpiPeakWeek').textContent = `week ${peakWeek.week} · ${peakWeek.phase}`;
  $('#kpiWeeks').textContent = plan.profile.weeks;
  $('#kpiRace').textContent = plan.raceDate;

  const warn = $('#warnings');
  warn.innerHTML = (state.adapted?.warnings || []).map((w) => `<div class="warn">⚠ ${escapeText(w)}</div>`).join('');
}

// ---------- Rendering: PMC ----------

function renderChart() {
  const series = pmcSeries();
  if (!series.length) return;
  const markers = phaseMarkers();
  $('#pmcChart').innerHTML = renderPmc(series, {
    showAdapted: !!state.adapted,
    ghost: !!state.adapted,
    markers,
  });
  const legend = `<span class="lg lg-ctl">CTL · fitness</span><span class="lg lg-atl">ATL · fatigue</span><span class="lg lg-tsb">TSB · form</span>${state.adapted ? '<span class="lg lg-ad">adapted CTL</span><span class="lg lg-ad2">adapted ATL</span><span class="lg lg-ghost">planned (ghost)</span>' : ''}`;
  $('#pmcLegend').innerHTML = legend;
}

function phaseMarkers() {
  const plan = state.plan;
  const colors = { Base: '#38bdf8', Build: '#a3e635', Peak: '#fb923c', Taper: '#c084fc', Recovery: '#64748b' };
  const out = [];
  let cur = null;
  plan.days.forEach((d, i) => {
    if (!cur || cur.label !== d.basePhase) {
      if (cur) cur.end = i - 1;
      cur = { label: d.basePhase, start: i, end: i, color: colors[d.basePhase] || '#64748b' };
      out.push(cur);
    }
    cur.end = i;
  });
  return out;
}

// ---------- Rendering: week calendar ----------

function renderWeeks() {
  const plan = currentPlan();
  const sums = weekSummaries(plan, !!state.adapted);
  const wrap = $('#weeks');
  wrap.innerHTML = sums.map((w) => {
    const days = plan.days.filter((d) => d.week === w.week);
    const cells = days.map((d) => {
      const dt = new Date(d.date + 'T00:00:00Z');
      const dow = dt.toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' });
      const dayNum = dt.getUTCDate();
      const items = d.workouts.map((wk) => {
        const adaptedClass = wk.status !== 'planned' ? ` st-${wk.status}` : '';
        const sel = state.selectedWorkoutId === wk.id ? ' sel' : '';
        return `<button class="wk sp-${wk.sport}${adaptedClass}${sel}" data-id="${wk.id}" title="${escapeText(wk.name)}">
          <span class="wk-name">${escapeText(wk.name)}</span>
          <span class="wk-meta">${Math.round(wk.durationSec / 60)}′ · ${Math.round(wk.tss)} TSS</span>
        </button>`;
      }).join('');
      const illness = d.workouts.some((wk) => wk.status === 'illness');
      return `<div class="day${d.rest ? ' rest' : ''}${illness ? ' ill' : ''}${d.date === plan.raceDate ? ' race' : ''}">
        <div class="dhead"><span>${dow}</span><b>${dayNum}</b></div>
        ${d.rest ? '<div class="restlbl">rest</div>' : items}
        ${d.date === plan.raceDate ? '<div class="racebadge">🏁 RACE</div>' : ''}
      </div>`;
    }).join('');
    return `<section class="week ph-${w.phase.toLowerCase()}">
      <header>
        <div class="wtitle"><span class="wnum">W${w.week}</span><span class="wphase">${w.phase}</span></div>
        <div class="wstats"><span>${w.hours.toFixed(1)} h</span><span>${Math.round(w.tss)} TSS</span><span>${w.sessions} sessions</span></div>
      </header>
      <div class="days">${cells}</div>
    </section>`;
  }).join('');
}

// ---------- Rendering: selected workout detail ----------

function findWorkout(id) {
  const plan = currentPlan();
  for (const d of plan.days) {
    for (const w of d.workouts) if (w.id === id) return { w, d };
  }
  return null;
}

function renderDetail() {
  const el = $('#detail');
  const hit = state.selectedWorkoutId && findWorkout(state.selectedWorkoutId);
  if (!hit) {
    el.innerHTML = `<div class="empty">
      <div class="empty-orb"></div>
      <h3>Select a session</h3>
      <p>Click any workout on the calendar to see its interval profile, exact targets, and export options.</p>
    </div>`;
    return;
  }
  const { w, d } = hit;
  const d2 = derived(readProfileForm());
  const targets = describeTargets(w, d2);
  el.innerHTML = `
    <div class="dtitle">
      <div>
        <div class="eyebrow">${escapeText(d.phase)} · Week ${d.week} · ${escapeText(d.date)}</div>
        <h3>${escapeText(w.name)}</h3>
      </div>
      <div class="dstats">
        <div><b>${Math.round(w.durationSec / 60)}′</b><span>duration</span></div>
        <div><b>${Math.round(w.tss)}</b><span>TSS</span></div>
        <div><b>${w.ifTarget.toFixed(2)}</b><span>IF</span></div>
      </div>
    </div>
    ${renderIntervalProfile(w.profile, { label: w.name, ftp: w.kind === 'bike' ? readProfileForm().ftp : null })}
    <div class="targets">${targets}</div>
    <div class="status-row">
      <span class="muted">Mark this session:</span>
      ${['planned', 'done', 'shortened', 'skipped', 'overreached'].map((s) => `
        <button class="chip ${w.status === s ? 'on' : ''}" data-status="${s}" data-id="${w.id}">${s}</button>`).join('')}
    </div>
    <div class="exports">
      <button class="btn ghost small" id="exportZwo" data-id="${w.id}">Export .zwo</button>
      <button class="btn ghost small" id="exportIcs" title="Exports the full plan as a calendar">Export plan .ics</button>
    </div>`;
}

function describeTargets(w, d) {
  const rows = [];
  const seen = new Set();
  for (const s of w.profile) {
    if (s.kind === 'rest' || s.kind === 'strength') continue;
    const key = `${s.kind}-${s.zone}-${s.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(targetFor(s, w, d));
  }
  if (w.kind === 'strength') {
    const ex = w.profile.find((s) => s.exercises)?.exercises || [];
    return `<div class="tgt-head">Session</div><ul class="exlist">${ex.map((e) => `<li>${escapeText(e)}</li>`).join('')}</ul>`;
  }
  return `<div class="tgt-head">Targets</div>${rows.join('')}`;
}

function targetFor(s, w, d) {
  const color = ZONE_COLORS[s.zone];
  let val = '';
  if (w.kind === 'bike') {
    // Fractional zones (3.5 = sweet spot) map onto the Coggan zone they sit in.
    const z = d.power.find((x) => x.z === Math.floor(s.zone)) || d.power[1];
    if (s.zone === 3.5) {
      // Sweet spot is 88–93% of FTP, which sits inside Coggan zone 3/4 boundary.
      const ftp = readProfileForm().ftp;
      val = `${Math.round(0.88 * ftp)}–${Math.round(0.93 * ftp)} W`;
    } else {
      val = z.maxW ? `${z.minW}–${z.maxW} W` : `${z.minW}+ W`;
    }
  } else if (w.kind === 'run') {
    const z = d.run.find((x) => x.z === s.zone) || d.run[0];
    val = `${secPerKmToString(z.fastSecPerKm)}–${secPerKmToString(z.slowSecPerKm)} /km`;
  } else if (w.kind === 'swim') {
    // Swim zones are numeric 1–5; the library uses the same numbering for blocks.
    const z = d.swim.find((x) => x.z === Math.round(Number(s.zone))) || d.swim.find((x) => x.z === 3);
    val = z ? `${secPer100mToString(z.fastSecPer100m)}–${secPer100mToString(z.slowSecPer100m)} /100m` : '–';
  }
  const mins = Math.round((s.end - s.start) / 60);
  return `<div class="trow" style="--c:${color}"><span class="tdot"></span><span>${escapeText(s.label)}</span><b>${escapeText(val)}</b><em>${mins}′</em></div>`;
}

// ---------- Adaptation ----------

function runAdaptation() {
  if (!state.plan) return;
  const availability = {};
  for (const [wk, v] of Object.entries(state.availability)) {
    if (v != null) availability[wk] = v;
  }
  const maxRamp = parseFloat($('#rampCap').value) / 100;
  state.adapted = adaptPlan(state.plan, {
    statuses: state.statuses,
    illnessDays: state.illnessDays,
    availability,
    maxRampPerWeek: maxRamp,
  });
  renderAll();
}

function setStatus(id, status) {
  if (status === 'planned') delete state.statuses[id];
  else state.statuses[id] = status;
  runAdaptation();
  toast(`Session marked ${status}. Plan recalibrated.`);
}

function resetAdaptation() {
  state.statuses = {};
  state.illnessDays = [];
  state.availability = {};
  state.adapted = null;
  renderAll();
  toast('Adaptations cleared.');
}

function renderAdaptPanel() {
  const plan = state.plan;
  if (!plan) return;
  const illList = $('#illList');
  illList.innerHTML = state.illnessDays.length
    ? state.illnessDays.map((d) => `<span class="pill">${d} <button data-ill="${d}" aria-label="remove">×</button></span>`).join('')
    : '<span class="muted">No illness days.</span>';

  const wkOpts = plan.profile.weeks;
  $('#availWeek').innerHTML = Array.from({ length: wkOpts }, (_, i) => `<option value="${i + 1}">Week ${i + 1}</option>`).join('');
  $('#availHours').value = state.availability[$('#availWeek').value] ?? '';

  const s = state.adapted?.summary;
  $('#adaptSummary').innerHTML = s
    ? `<div class="sumrow"><span>Race-day CTL</span><b>${fmt1(s.adaptedRaceCtl)}</b><em>planned ${fmt1(s.plannedRaceCtl)}</em></div>
       <div class="sumrow"><span>Race-day TSB</span><b>${s.adaptedRaceTsb >= 0 ? '+' : ''}${fmt1(s.adaptedRaceTsb)}</b><em>planned ${s.plannedRaceTsb >= 0 ? '+' : ''}${fmt1(s.plannedRaceTsb)}</em></div>
       <div class="sumrow"><span>Max weekly ramp</span><b>${(s.maxRampApplied * 100).toFixed(1)}%</b><em>cap ${$('#rampCap').value}%</em></div>`
    : '<p class="muted">Mark sessions or add changes to see the recalibrated plan.</p>';
}

// ---------- Global render ----------

function renderAll() {
  if (!state.plan) return;
  renderKpis();
  renderChart();
  renderWeeks();
  renderDetail();
  renderAdaptPanel();
  renderZones();
}

// ---------- Event wiring ----------

function wire() {
  // Zones update live as the profile is edited.
  $$('#profileForm input, #profileForm select').forEach((el) => {
    el.addEventListener('input', () => { renderZones(); });
    el.addEventListener('change', () => { renderZones(); });
  });
  $$('input[name="raceMode"]').forEach((el) => el.addEventListener('change', () => { syncRaceModeUi(); renderZones(); }));

  $('#generate').addEventListener('click', () => {
    if (buildPlanFromProfile()) {
      renderAll();
      $('#planSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
      toast('Plan generated.');
    }
  });

  $('#weeks').addEventListener('click', (e) => {
    const btn = e.target.closest('.wk');
    if (!btn) return;
    state.selectedWorkoutId = btn.dataset.id;
    renderWeeks();
    renderDetail();
  });

  $('#detail').addEventListener('click', (e) => {
    const st = e.target.closest('[data-status]');
    if (st) { setStatus(st.dataset.id, st.dataset.status); return; }
    if (e.target.closest('#exportZwo')) {
      const hit = findWorkout(state.selectedWorkoutId);
      if (hit) {
        const p = readProfileForm();
        download(`${slug(hit.w.name)}.zwo`, toZwo(hit.w, p), 'application/xml');
      }
      return;
    }
    if (e.target.closest('#exportIcs')) {
      download(`${slug(state.profile.name)}-plan.ics`, toIcs(currentPlan()), 'text/calendar');
    }
  });

  $('#addIll').addEventListener('click', () => {
    const d = $('#illDate').value;
    if (!d) return toast('Pick a date first.');
    if (!state.illnessDays.includes(d)) state.illnessDays.push(d);
    state.illnessDays.sort();
    runAdaptation();
  });
  $('#illList').addEventListener('click', (e) => {
    const b = e.target.closest('[data-ill]');
    if (!b) return;
    state.illnessDays = state.illnessDays.filter((x) => x !== b.dataset.ill);
    runAdaptation();
  });

  $('#availWeek').addEventListener('change', () => {
    $('#availHours').value = state.availability[$('#availWeek').value] ?? '';
  });
  $('#applyAvail').addEventListener('click', () => {
    const wk = $('#availWeek').value;
    const h = parseFloat($('#availHours').value);
    if (Number.isFinite(h) && h >= 0) state.availability[wk] = h;
    else delete state.availability[wk];
    runAdaptation();
  });

  $('#rampCap').addEventListener('input', (e) => {
    $('#rampCapVal').textContent = `${e.target.value}%`;
  });
  $('#rampCap').addEventListener('change', () => { if (state.adapted) runAdaptation(); });

  $('#resetAdapt').addEventListener('click', resetAdaptation);
  $('#exportAllIcs').addEventListener('click', () => {
    if (!currentPlan()) return toast('Generate a plan first.');
    download(`${slug(state.profile.name)}-plan.ics`, toIcs(currentPlan()), 'text/calendar');
  });
}

function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workout';
}

// ---------- Boot ----------

function boot() {
  writeProfileForm();
  wire();
  renderZones();
  // Generate a default plan so the page is never empty.
  if (buildPlanFromProfile()) renderAll();
}

boot();
