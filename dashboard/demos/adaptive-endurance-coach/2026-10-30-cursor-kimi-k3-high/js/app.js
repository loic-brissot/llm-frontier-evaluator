/* ═══════════════════════════════════════════════════════════════
   app.js — state, UI wiring, rendering
   ═══════════════════════════════════════════════════════════════ */
'use strict';

const App = (() => {
  const $ = id => document.getElementById(id);
  const state = { profile: null, plan: null, adapted: null, events: [], showOriginal: true };

  const PHASE_COLOR = { base: '#60a5fa', build: '#a78bfa', peak: '#f472b6', taper: '#34d399', recovery: '#64748b' };
  const PHASE_LABEL = { base: 'BASE', build: 'BUILD', peak: 'PEAK', taper: 'TAPER', recovery: 'RECOVERY' };

  /* ── profile ────────────────────────────────────────────── */
  function readProfile() {
    const raceSec = Physio.parseClock($('inRace').value);
    const vo2 = parseFloat($('inVo2').value) || 50;
    const vdot = raceSec > 0 ? Physio.vdotFromRace(10000, raceSec) : vo2;
    const weight = parseFloat($('inWeight').value) || 70;
    const p = {
      weight,
      ftp: parseFloat($('inFtp').value) || 250,
      vo2max: vo2, vdot,
      lthr: parseFloat($('inLthr').value) || 168,
      cssSec: Physio.parseClock($('inCss').value) || 105,
      weeklyHours: parseFloat($('inHours').value) || 8,
      sessionsPerWeek: parseInt($('inSessions').value) || 6,
      discipline: state.profile?.discipline || 'triathlon',
      startDate: new Date($('inStart').value + 'T00:00:00'),
      raceDate: new Date($('inRace2').value + 'T00:00:00'),
    };
    p.run = Physio.runZones(vdot);
    p.swim = Physio.swimZones(p.cssSec);
    p.powerZones = Physio.cogganZones(p.ftp);
    p.hrZones = Physio.hrZones(p.lthr);
    return p;
  }

  /* ── rebuild everything ─────────────────────────────────── */
  function rebuild(clearEvents = true) {
    state.profile = readProfile();
    if (clearEvents) state.events = [];
    const t0 = performance.now();
    state.plan = Planner.buildPlan(state.profile, {
      startDate: state.profile.startDate, raceDate: state.profile.raceDate,
    });
    state.adapted = state.events.length
      ? Planner.buildAdapted(state.plan, state.profile, state.events, new Date())
      : state.plan;
    console.debug(`plan built in ${(performance.now() - t0).toFixed(1)}ms`);
    renderAll();
  }

  function reAdapt() {
    state.adapted = state.events.length
      ? Planner.buildAdapted(state.plan, state.profile, state.events, new Date())
      : state.plan;
    renderAll();
  }

  /* ── master render ──────────────────────────────────────── */
  function renderAll() {
    renderRaceChip(); renderVdotCard(); renderZones();
    renderKPIs(); renderPMC(); renderCalendar(); renderEvents();
    const avail = [...state.events].reverse().find(e => e.type === 'availability');
    $('adHours').value = avail?.hours ?? state.profile.weeklyHours;
    $('adSessions').value = avail?.sessions ?? state.profile.sessionsPerWeek;
  }

  function renderRaceChip() {
    const p = state.profile;
    const weeks = Math.max(1, Math.round((p.raceDate - p.startDate) / (7 * 86400000)));
    $('raceChip').innerHTML = `🏁 <b>${p.raceDate.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</b><em>${weeks}-week macrocycle</em>`;
    $('planSummary').textContent =
      `${weeks} weeks · ${p.weeklyHours} h/wk · ${p.sessionsPerWeek} sessions/wk · ramp cap ≤ ${Planner.RAMP_CAP} CTL/wk · taper solved for race-day TSB +${Planner.TSB_TARGET}`;
  }

  /* ── VDOT card with equivalent performances ─────────────── */
  function renderVdotCard() {
    const p = state.profile;
    const eq = [['5K', 5000], ['10K', 10000], ['Half', 21097.5], ['Marathon', 42195]]
      .map(([n, d]) => {
        let lo = 300, hi = 20000;
        for (let i = 0; i < 40; i++) {
          const mid = (lo + hi) / 2;
          (Physio.vdotFromRace(d, mid) > p.vdot) ? lo = mid : hi = mid;
        }
        const t = (lo + hi) / 2;
        const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = Math.round(t % 60);
        return `<div class="eq"><span>${n}</span><b>${h ? h + ':' + String(m).padStart(2, '0') : m}:${String(s).padStart(2, '0')}</b></div>`;
      }).join('');
    $('vdotCard').innerHTML = `
      <div class="vdot-top"><span>VDOT</span><b>${p.vdot.toFixed(1)}</b><em>${p.run.zones ? Physio.fmtPace(p.run.thresholdPaceSec) + '/km threshold' : ''}</em></div>
      <div class="eq-row">${eq}</div>`;
    $('wkgOut').textContent = (p.ftp / p.weight).toFixed(1) + ' W/kg';
  }

  /* ── zone tables ────────────────────────────────────────── */
  function renderZones() {
    const p = state.profile, d = p.discipline;
    const tables = [];
    if (d === 'cycling' || d === 'triathlon' || d === 'cross') {
      tables.push(zoneTable('Coggan Power Zones', `${p.ftp} W FTP · ${(p.ftp / p.weight).toFixed(1)} W/kg`,
        p.powerZones.map(z => [`Z${z.n}`, z.name,
          z.hiW === null ? `> ${z.loW} W` : `${z.loW}–${z.hiW} W`,
          `${Math.round(z.lo * 100)}–${z.hi > 10 ? '—' : Math.round(z.hi * 100)}%`])));
    }
    if (d === 'running' || d === 'triathlon' || d === 'cross') {
      tables.push(zoneTable('Daniels Running Zones', `VDOT ${p.vdot.toFixed(1)}`,
        p.run.zones.map(z => [z.key, z.name,
          `${Physio.fmtPace(z.loSec)}–${Physio.fmtPace(z.hiSec)}/km`, z.desc])));
    }
    if (d === 'triathlon') {
      tables.push(zoneTable('Swim Pace Zones', `CSS ${Physio.fmtPace(p.cssSec)}/100m`,
        p.swim.zones.map(z => [z.key, z.name,
          `${Physio.fmtPace(z.loSec)}–${Physio.fmtPace(z.hiSec)}/100m`, z.desc])));
    }
    tables.push(zoneTable('Heart-Rate Zones', `LTHR ${p.lthr} bpm`,
      p.hrZones.map(z => [`Z${z.n}`, z.name,
        z.loBpm === null ? `< ${z.hiBpm} bpm` : `${z.loBpm}–${z.hiBpm} bpm`,
        `${Math.round(z.lo * 100)}–${Math.round(z.hi * 100)}%`])));
    $('zonesPanel').innerHTML = `<div class="side-title">Individualised Zones</div>` + tables.join('');
  }
  const zoneTable = (title, sub, rows) => `
    <details class="zone-block" open>
      <summary>${title}<em>${sub}</em></summary>
      <table class="zone-tbl">
        ${rows.map(r => `<tr><td class="zk">${r[0]}</td><td>${r[1]}</td><td class="zv">${r[2]}</td><td class="zd">${r[3]}</td></tr>`).join('')}
      </table>
    </details>`;

  /* ── KPI cards ──────────────────────────────────────────── */
  function renderKPIs() {
    const a = state.adapted, p = state.profile;
    const today = new Date();
    const ti = a.days.findIndex(d => Planner.sameDay(d.date, today));
    const tsbNow = ti >= 0 ? a.pmc[ti].tsb : null;
    const adapted = state.events.length > 0;
    const delta = adapted ? a.raceTSB - state.plan.raceTSB : 0;
    const kpi = (label, val, sub, cls = '') =>
      `<div class="kpi ${cls}"><div class="kpi-val">${val}</div><div class="kpi-lbl">${label}</div><div class="kpi-sub">${sub}</div></div>`;
    $('kpiRow').innerHTML =
      kpi('peak fitness (CTL)', a.peakCTL.toFixed(0), adapted ? `plan ${state.plan.peakCTL.toFixed(0)}` : 'as planned') +
      kpi('race-day form (TSB)', `${a.raceTSB >= 0 ? '+' : ''}${a.raceTSB.toFixed(1)}`,
          adapted ? `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} vs plan` : `target +${Planner.TSB_TARGET}`,
          Math.abs(a.raceTSB - Planner.TSB_TARGET) <= 7 ? 'kpi-good' : 'kpi-warn') +
      kpi('total load', a.totalTSS.toLocaleString() + ' TSS',
          `${a.weeks.length} weeks · ${a.days.filter(d => d.sessions.length).length} sessions`) +
      kpi('weekly ramp cap', `≤ ${Planner.RAMP_CAP} CTL`, 'Banister-safe progression') +
      `<div class="kpi kpi-gauge" id="gaugeBox"></div>`;
    Charts.gauge($('gaugeBox'), tsbNow ?? a.pmc[0].tsb);
  }

  /* ── PMC ────────────────────────────────────────────────── */
  function renderPMC() {
    Charts.pmc($('pmcChart'), $('pmcTip'),
      state.events.length ? state.plan : null,
      state.adapted, state.adapted.days.map(d => d.date),
      { showOriginal: state.showOriginal && state.events.length > 0 });
  }

  /* ── calendar ───────────────────────────────────────────── */
  function renderCalendar() {
    const a = state.adapted;
    const today = new Date();
    let html = '';
    a.weeks.forEach(w => {
      const wDays = a.days.slice(w.idx * 7, w.idx * 7 + 7);
      const col = PHASE_COLOR[w.phase];
      html += `<div class="week">
        <div class="week-meta" style="--pc:${col}">
          <div class="week-num">W${w.idx + 1}</div>
          <div class="week-phase">${PHASE_LABEL[w.phase]}</div>
          <div class="week-stats">${w.tss}<span>TSS</span></div>
          <div class="week-stats">${w.hours}<span>h</span></div>
          <div class="week-ctl">CTL ${w.ctlEnd.toFixed(0)}</div>
        </div>
        <div class="week-days">`;
      wDays.forEach(d => {
        const isToday = Planner.sameDay(d.date, today);
        const isRace = d.date.getTime() === a.race.getTime();
        html += `<div class="day ${isToday ? 'day-today' : ''} ${d.illness ? 'day-ill' : ''} ${isRace ? 'day-race' : ''}">
          <div class="day-num">${d.date.toLocaleDateString('en-GB', { weekday: 'narrow' })} ${d.date.getDate()}</div>`;
        d.sessions.forEach(s => {
          const col2 = Charts.SPORT_COLOR[s.sport] || '#94a3b8';
          html += `<button class="sess status-${s.status}" style="--sc:${col2}" data-sid="${s.id}" data-date="${Planner.iso(d.date)}">
            <i class="dot"></i><span class="sess-name">${s.name}</span>
            <span class="sess-tss">${s.status === 'skipped' ? '—' : s.tss}</span></button>`;
        });
        if (d.illness) html += `<div class="ill-tag">🤒 ill</div>`;
        html += `</div>`;
      });
      html += `</div></div>`;
    });
    $('calendar').innerHTML = html;
    $('calendar').querySelectorAll('.sess').forEach(btn =>
      btn.addEventListener('click', () => openSession(btn.dataset.date, btn.dataset.sid)));
  }

  /* ── session modal ──────────────────────────────────────── */
  function openSession(dateISO, sid) {
    const a = state.adapted;
    const day = a.days.find(d => Planner.iso(d.date) === dateISO);
    const s = day?.sessions.find(x => x.id === sid);
    if (!s) return;
    const p = state.profile;
    const durH = Math.floor(s.durMin / 60), durM = s.durMin % 60;
    const sportCol = Charts.SPORT_COLOR[s.sport] || '#94a3b8';
    const canZwo = s.sport === 'bike' || s.sport === 'run';

    $('modalBody').innerHTML = `
      <div class="modal-head" style="--sc:${sportCol}">
        <div class="modal-sport">${s.sport.toUpperCase()}${s.phase ? ` · ${PHASE_LABEL[s.phase]}` : ''}</div>
        <h3>${s.name}</h3>
        <div class="modal-meta">
          <span>${day.date.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}</span>
          ${s.durMin ? `<span>${durH ? durH + 'h ' : ''}${durM ? durM + 'min' : ''}</span>` : ''}
          <span>TSS ${s.tss}</span>
          ${s.durMin && s.sport !== 'strength' && !s.isRace ? `<span>IF ${(Math.sqrt(s.tss / (s.durMin / 60)) / 10).toFixed(2)}</span>` : ''}
        </div>
      </div>
      ${s.isRace ? `<div class="race-note">🏁 All the work is done. Trust the taper — target form TSB +${Planner.TSB_TARGET} on the start line.</div>` : `
      <div class="profile-wrap" id="modalProfile"></div>
      <table class="seg-tbl">
        <thead><tr><th>#</th><th>Segment</th><th>Duration</th><th>Target</th></tr></thead>
        <tbody>${Charts.segmentRows(s, p)}</tbody>
      </table>
      <div class="modal-actions">
        <button class="btn" id="mIcs">📅 .ics</button>
        ${canZwo ? `<button class="btn" id="mZwo">⬇ .zwo (Zwift)</button>` : ''}
        <span class="modal-sep"></span>
        <span class="modal-mark-lbl">mark as:</span>
        <button class="btn btn-mini" data-mark="completed">✓ done</button>
        <button class="btn btn-mini" data-mark="shortened">◐ shortened</button>
        <button class="btn btn-mini" data-mark="skipped">✗ skipped</button>
        <button class="btn btn-mini btn-danger" data-mark="overreached">▲ over-reached</button>
      </div>`}`;
    if (!s.isRace) {
      Charts.workoutProfile($('modalProfile'), s, p);
      $('mIcs').onclick = () => Exporter.download(`${s.name.replace(/\W+/g, '_')}.ics`,
        Exporter.toICS([{ date: day.date, session: s }], p, 'APEX LAB'), 'text/calendar');
      if (canZwo) $('mZwo').onclick = () => Exporter.download(`${s.name.replace(/\W+/g, '_')}.zwo`,
        Exporter.toZWO(s, p), 'application/xml');
      $('modalBody').querySelectorAll('[data-mark]').forEach(b => b.onclick = () => {
        pushEvent({ type: 'session', id: s.id, status: b.dataset.mark });
        closeModal();
      });
    }
    $('modalBackdrop').classList.add('open');
  }
  const closeModal = () => $('modalBackdrop').classList.remove('open');

  /* ── adaptation events ──────────────────────────────────── */
  function pushEvent(ev) {
    state.events.push(ev);
    reAdapt();
  }
  function renderEvents() {
    const el = $('eventsList');
    if (!state.events.length) { el.innerHTML = `<em class="no-ev">plan unchanged — everything on track</em>`; return; }
    el.innerHTML = state.events.map((ev, i) => {
      const txt = ev.type === 'illness' ? `🤒 illness · ${ev.days}d from ${ev.start.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`
        : ev.type === 'availability' ? `📆 availability → ${ev.hours}h / ${ev.sessions}sessions`
        : `session → ${ev.status}`;
      return `<span class="ev-chip">${txt}<button data-i="${i}">✕</button></span>`;
    }).join('');
    el.querySelectorAll('button').forEach(b => b.onclick = () => {
      state.events.splice(+b.dataset.i, 1); reAdapt();
    });
  }

  /* ── wiring ─────────────────────────────────────────────── */
  function init() {
    /* default dates: next Monday → +16 weeks, race Sunday */
    const now = new Date();
    const start = new Date(now);
    start.setDate(now.getDate() + ((8 - now.getDay()) % 7 || 7));
    const race = new Date(start.getTime() + (16 * 7 - 1) * 86400000);
    $('inStart').value = Planner.iso(start);
    $('inRace2').value = Planner.iso(race);

    document.querySelectorAll('.sidebar input').forEach(inp =>
      inp.addEventListener('change', () => rebuild(true)));

    $('disciplineTabs').querySelectorAll('.tab').forEach(t => t.onclick = () => {
      $('disciplineTabs').querySelector('.active').classList.remove('active');
      t.classList.add('active');
      state.profile = state.profile || {};
      state.profile.discipline = t.dataset.disc;
      rebuild(true);
    });

    $('toggleOriginal').onchange = e => { state.showOriginal = e.target.checked; renderPMC(); };

    $('btnIllness').onclick = () => {
      const days = parseInt(prompt('Illness duration (days) starting today:', '6'));
      if (!days || days < 1) return;
      pushEvent({ type: 'illness', start: new Date(), days: Math.min(days, 30) });
    };
    $('btnAvail').onclick = () => pushEvent({
      type: 'availability',
      hours: parseFloat($('adHours').value) || state.profile.weeklyHours,
      sessions: parseInt($('adSessions').value) || state.profile.sessionsPerWeek,
    });
    $('btnResetEvents').onclick = () => { state.events = []; reAdapt(); };

    $('btnExportAll').onclick = () => {
      const pairs = [];
      state.adapted.days.forEach(d => d.sessions.forEach(s => {
        if (s.status !== 'skipped') pairs.push({ date: d.date, session: s });
      }));
      Exporter.download('apex_training_plan.ics',
        Exporter.toICS(pairs, state.profile, 'APEX LAB Training Plan'), 'text/calendar');
    };

    $('modalClose').onclick = closeModal;
    $('modalBackdrop').addEventListener('click', e => { if (e.target === $('modalBackdrop')) closeModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

    rebuild(true);
  }

  document.addEventListener('DOMContentLoaded', init);
  return { state };
})();
