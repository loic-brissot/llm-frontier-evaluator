/* ═══════════════════════════════════════════════════════════════
   planner.js — periodized plan generator + live adaptation engine
   Mesocycles: Base → Build → Peak → Taper, 3:1 load/recovery,
   weekly ramp-rate cap, taper solved to target race-day TSB.
   ═══════════════════════════════════════════════════════════════ */
'use strict';

const Planner = (() => {
  const { clamp } = Physio;

  const RAMP_CAP = 5;              // max CTL gain per loading week (TSS/day)
  const TSB_TARGET = 8;            // desired race-day form
  const PHASE_RATE = { base: 55, build: 65, peak: 64, recovery: 55, taper: 55 };
  const RECOVERY_FACTOR = 0.58;
  const RACE_TSS = { triathlon: 180, running: 150, cycling: 250, cross: 100 };

  /* ─────────────────────────────────────────────────────────
     WORKOUT TEMPLATE LIBRARY
     Intensities: bike = fraction of FTP · run = fraction of
     threshold speed · swim = fraction of CSS speed.
     Blocks: wu | ss | set (repeats) | cd | str (strength set)
     ───────────────────────────────────────────────────────── */
  const T = {
    /* ── cycling ── */
    bike_recovery:  { sport: 'bike', name: 'Recovery Spin', blocks: [
      { k: 'wu', dur: 5, i0: 0.40, i1: 0.50 },
      { k: 'ss', dur: 40, i: 0.52, label: 'Very easy Z1 spin, high cadence', scalable: true },
      { k: 'cd', dur: 5, i0: 0.50, i1: 0.40 } ] },
    bike_endurance: { sport: 'bike', name: 'Endurance Ride', blocks: [
      { k: 'wu', dur: 10, i0: 0.45, i1: 0.65 },
      { k: 'ss', dur: 60, i: 0.68, label: 'Steady Z2 endurance', scalable: true },
      { k: 'cd', dur: 5, i0: 0.60, i1: 0.45 } ] },
    bike_tempo:     { sport: 'bike', name: 'Tempo Ride', blocks: [
      { k: 'wu', dur: 12, i0: 0.45, i1: 0.70 },
      { k: 'set', reps: 2, on: 20, off: 5, onI: 0.82, offI: 0.55, label: 'Tempo', scalable: true },
      { k: 'cd', dur: 8, i0: 0.60, i1: 0.45 } ] },
    bike_sweetspot: { sport: 'bike', name: 'Sweet Spot 3×12', blocks: [
      { k: 'wu', dur: 12, i0: 0.45, i1: 0.75 },
      { k: 'set', reps: 3, on: 12, off: 4, onI: 0.90, offI: 0.55, label: 'Sweet spot', scalable: true },
      { k: 'cd', dur: 8, i0: 0.60, i1: 0.45 } ] },
    bike_threshold: { sport: 'bike', name: 'Threshold 2×20', blocks: [
      { k: 'wu', dur: 15, i0: 0.45, i1: 0.80 },
      { k: 'set', reps: 2, on: 20, off: 6, onI: 0.98, offI: 0.55, label: 'FTP intervals', scalable: true },
      { k: 'cd', dur: 8, i0: 0.60, i1: 0.45 } ] },
    bike_vo2:       { sport: 'bike', name: 'VO₂max 5×4', blocks: [
      { k: 'wu', dur: 15, i0: 0.45, i1: 0.80 },
      { k: 'set', reps: 5, on: 4, off: 4, onI: 1.13, offI: 0.55, label: 'VO₂max', scalable: true },
      { k: 'cd', dur: 10, i0: 0.60, i1: 0.45 } ] },
    bike_long:      { sport: 'bike', name: 'Long Endurance Ride', blocks: [
      { k: 'wu', dur: 15, i0: 0.45, i1: 0.65 },
      { k: 'ss', dur: 120, i: 0.70, label: 'Z2 with tempo finish', scalable: true },
      { k: 'set', reps: 2, on: 10, off: 5, onI: 0.84, offI: 0.65, label: 'Tempo finish' },
      { k: 'cd', dur: 10, i0: 0.60, i1: 0.45 } ] },
    bike_openers:   { sport: 'bike', name: 'Race Openers', blocks: [
      { k: 'wu', dur: 12, i0: 0.45, i1: 0.65 },
      { k: 'set', reps: 4, on: 3, off: 4, onI: 1.00, offI: 0.50, label: 'Race-pace openers', scalable: true },
      { k: 'cd', dur: 8, i0: 0.55, i1: 0.45 } ] },

    /* ── running ── */
    run_recovery:   { sport: 'run', name: 'Recovery Jog', blocks: [
      { k: 'wu', dur: 5, i0: 0.60, i1: 0.72 },
      { k: 'ss', dur: 25, i: 0.76, label: 'Very easy shuffle', scalable: true },
      { k: 'cd', dur: 5, i0: 0.72, i1: 0.60 } ] },
    run_easy:       { sport: 'run', name: 'Easy Run + Strides', blocks: [
      { k: 'wu', dur: 8, i0: 0.60, i1: 0.80 },
      { k: 'ss', dur: 35, i: 0.84, label: 'Easy aerobic', scalable: true },
      { k: 'set', reps: 4, on: 0.33, off: 1, onI: 1.10, offI: 0.65, label: 'Strides' },
      { k: 'cd', dur: 5, i0: 0.75, i1: 0.60 } ] },
    run_tempo:      { sport: 'run', name: 'Marathon-Pace Run', blocks: [
      { k: 'wu', dur: 12, i0: 0.62, i1: 0.85 },
      { k: 'ss', dur: 25, i: 0.955, label: 'Marathon pace', scalable: true },
      { k: 'cd', dur: 8, i0: 0.80, i1: 0.62 } ] },
    run_threshold:  { sport: 'run', name: 'Threshold Cruise 2×15', blocks: [
      { k: 'wu', dur: 15, i0: 0.62, i1: 0.88 },
      { k: 'set', reps: 2, on: 15, off: 3, onI: 1.00, offI: 0.70, label: 'Threshold', scalable: true },
      { k: 'cd', dur: 10, i0: 0.78, i1: 0.62 } ] },
    run_intervals:  { sport: 'run', name: 'VO₂ Intervals 6×3', blocks: [
      { k: 'wu', dur: 15, i0: 0.62, i1: 0.88 },
      { k: 'set', reps: 6, on: 3, off: 2, onI: 1.075, offI: 0.65, label: 'VO₂ intervals', scalable: true },
      { k: 'cd', dur: 10, i0: 0.78, i1: 0.62 } ] },
    run_reps:       { sport: 'run', name: 'Speed Reps 10×400', blocks: [
      { k: 'wu', dur: 15, i0: 0.62, i1: 0.88 },
      { k: 'set', reps: 10, on: 1.5, off: 2, onI: 1.15, offI: 0.60, label: 'Repetition pace', scalable: true },
      { k: 'cd', dur: 10, i0: 0.75, i1: 0.60 } ] },
    run_long:       { sport: 'run', name: 'Long Run', blocks: [
      { k: 'wu', dur: 10, i0: 0.62, i1: 0.80 },
      { k: 'ss', dur: 75, i: 0.85, label: 'Easy-steady aerobic', scalable: true },
      { k: 'ss', dur: 15, i: 0.94, label: 'Progression finish' },
      { k: 'cd', dur: 5, i0: 0.75, i1: 0.60 } ] },
    run_openers:    { sport: 'run', name: 'Easy + Race-Pace Touches', blocks: [
      { k: 'wu', dur: 10, i0: 0.62, i1: 0.82 },
      { k: 'set', reps: 4, on: 2, off: 2, onI: 1.00, offI: 0.68, label: 'Race-pace touches', scalable: true },
      { k: 'cd', dur: 8, i0: 0.75, i1: 0.60 } ] },

    /* ── swimming ── */
    swim_tech:      { sport: 'swim', name: 'Technique & Drills', blocks: [
      { k: 'wu', dur: 10, i0: 0.70, i1: 0.80 },
      { k: 'set', reps: 8, on: 1.5, off: 0.5, onI: 0.84, offI: 0.60, label: 'Drill 50s', scalable: true },
      { k: 'cd', dur: 6, i0: 0.75, i1: 0.65 } ] },
    swim_css:       { sport: 'swim', name: 'CSS Set 10×100', blocks: [
      { k: 'wu', dur: 12, i0: 0.70, i1: 0.88 },
      { k: 'set', reps: 10, on: 1.8, off: 0.33, onI: 1.00, offI: 0.60, label: '100s at CSS', scalable: true },
      { k: 'cd', dur: 8, i0: 0.75, i1: 0.65 } ] },
    swim_threshold: { sport: 'swim', name: 'Threshold 5×400', blocks: [
      { k: 'wu', dur: 12, i0: 0.70, i1: 0.88 },
      { k: 'set', reps: 5, on: 7, off: 1, onI: 0.99, offI: 0.60, label: '400s at CSS', scalable: true },
      { k: 'cd', dur: 8, i0: 0.75, i1: 0.65 } ] },
    swim_sprint:    { sport: 'swim', name: 'Sprint 12×50', blocks: [
      { k: 'wu', dur: 12, i0: 0.70, i1: 0.88 },
      { k: 'set', reps: 12, on: 0.9, off: 0.75, onI: 1.10, offI: 0.55, label: 'Fast 50s', scalable: true },
      { k: 'cd', dur: 8, i0: 0.75, i1: 0.65 } ] },

    /* ── strength ── */
    strength_a:     { sport: 'strength', name: 'Foundational Strength A', blocks: [
      { k: 'str', dur: 10, label: 'Movement prep · hip hinge & band activation' },
      { k: 'str', dur: 14, label: 'Goblet squat 3×8 · RPE 7' },
      { k: 'str', dur: 14, label: 'Romanian deadlift 3×8 · RPE 7' },
      { k: 'str', dur: 12, label: 'Split squat 3×6/side · controlled tempo' },
      { k: 'str', dur: 10, label: 'Side plank + pallof press 3 rounds' } ] },
    strength_b:     { sport: 'strength', name: 'Foundational Strength B', blocks: [
      { k: 'str', dur: 10, label: 'Movement prep · shoulder & t-spine' },
      { k: 'str', dur: 14, label: 'Trap-bar deadlift 3×6 · RPE 7' },
      { k: 'str', dur: 12, label: 'Step-up 3×8/side' },
      { k: 'str', dur: 12, label: 'Half-kneeling press 3×8/side' },
      { k: 'str', dur: 10, label: 'Dead bug + glute bridge 3 rounds' } ] },
  };

  /* brick (triathlon): bike straight into run */
  T.brick = { sport: 'brick', name: 'Brick · Bike → Run', blocks: [
    { k: 'wu', dur: 10, i0: 0.45, i1: 0.65, sport: 'bike' },
    { k: 'set', reps: 3, on: 15, off: 3, onI: 0.85, offI: 0.60, label: 'Bike · race effort', sport: 'bike', scalable: true },
    { k: 'ss', dur: 15, i: 0.92, label: 'Run off the bike · steady', sport: 'run' },
    { k: 'cd', dur: 5, i0: 0.75, i1: 0.60, sport: 'run' } ] };
  T.brick_race = { sport: 'brick', name: 'Race-Pace Brick', blocks: [
    { k: 'wu', dur: 10, i0: 0.45, i1: 0.65, sport: 'bike' },
    { k: 'set', reps: 2, on: 20, off: 4, onI: 0.90, offI: 0.62, label: 'Bike · race power', sport: 'bike', scalable: true },
    { k: 'set', reps: 3, on: 6, off: 2, onI: 0.97, offI: 0.72, label: 'Run · race pace', sport: 'run' },
    { k: 'cd', dur: 5, i0: 0.75, i1: 0.60, sport: 'run' } ] };

  /* ─────────────────────────────────────────────────────────
     WEEKLY SESSION MENUS  { tpl, share } — ordered so the
     first N entries for N sessions/week keep a sport mix.
     ───────────────────────────────────────────────────────── */
  const MENUS = {
    cycling: {
      base:     [['bike_long', .30], ['bike_sweetspot', .22], ['bike_endurance', .18], ['bike_tempo', .16], ['bike_recovery', .14], ['bike_endurance', .10]],
      build:    [['bike_long', .28], ['bike_threshold', .22], ['bike_sweetspot', .18], ['bike_vo2', .14], ['bike_endurance', .18], ['bike_recovery', .10]],
      peak:     [['bike_long', .26], ['bike_vo2', .22], ['bike_threshold', .24], ['bike_endurance', .18], ['bike_openers', .10]],
      taper:    [['bike_openers', .24], ['bike_endurance', .30], ['bike_long', .22], ['bike_recovery', .14], ['bike_recovery', .10]],
      recovery: [['bike_endurance', .40], ['bike_recovery', .32], ['bike_recovery', .28], ['bike_endurance', .20]],
    },
    running: {
      base:     [['run_long', .32], ['run_tempo', .22], ['run_easy', .20], ['run_easy', .16], ['run_recovery', .10]],
      build:    [['run_long', .30], ['run_threshold', .24], ['run_intervals', .20], ['run_easy', .16], ['run_recovery', .10]],
      peak:     [['run_long', .28], ['run_intervals', .24], ['run_threshold', .22], ['run_easy', .16], ['run_openers', .10]],
      taper:    [['run_openers', .24], ['run_easy', .28], ['run_long', .22], ['run_recovery', .16], ['run_recovery', .10]],
      recovery: [['run_easy', .38], ['run_recovery', .32], ['run_recovery', .30], ['run_easy', .20]],
    },
    triathlon: {
      base:     [['swim_css', .11], ['bike_long', .19], ['run_long', .16], ['bike_sweetspot', .14], ['run_tempo', .12], ['swim_tech', .09], ['bike_endurance', .10], ['run_easy', .09]],
      build:    [['brick', .17], ['bike_long', .16], ['run_long', .13], ['swim_css', .11], ['bike_threshold', .13], ['run_threshold', .12], ['swim_threshold', .10], ['run_easy', .08]],
      peak:     [['brick_race', .18], ['bike_long', .14], ['run_intervals', .13], ['swim_css', .11], ['bike_vo2', .13], ['run_long', .13], ['swim_sprint', .09], ['run_openers', .09]],
      taper:    [['swim_css', .14], ['bike_openers', .20], ['run_openers', .18], ['bike_endurance', .18], ['run_easy', .12], ['swim_tech', .10], ['bike_recovery', .08]],
      recovery: [['swim_tech', .20], ['bike_endurance', .26], ['run_easy', .22], ['bike_recovery', .16], ['run_recovery', .16]],
    },
    cross: {
      base:     [['strength_a', .13], ['bike_long', .20], ['run_long', .17], ['bike_sweetspot', .14], ['run_easy', .12], ['strength_b', .12], ['bike_endurance', .12]],
      build:    [['strength_a', .13], ['bike_long', .18], ['run_threshold', .15], ['bike_threshold', .15], ['run_long', .15], ['strength_b', .11], ['bike_sweetspot', .13]],
      peak:     [['bike_long', .18], ['run_intervals', .15], ['strength_a', .13], ['bike_vo2', .16], ['run_long', .15], ['strength_b', .10], ['run_easy', .13]],
      taper:    [['bike_openers', .20], ['run_openers', .18], ['bike_endurance', .20], ['strength_a', .14], ['run_easy', .14], ['bike_recovery', .14]],
      recovery: [['bike_endurance', .24], ['run_easy', .22], ['strength_a', .20], ['bike_recovery', .18], ['run_recovery', .16]],
    },
  };

  // weekday assignment: biggest session first → weekend priority
  const DAY_PRIORITY = [6, 5, 3, 1, 4, 2, 0];   // Sun Sat Thu Tue Fri Wed Mon

  /* ── expand a template to flat segments, scaled to target TSS ── */
  function expandWorkout(tpl, targetTSS) {
    const nominal = segmentsOf(tpl.blocks, 1);
    const nominalTSS = Physio.tssFromSegments(tpl.sport, nominal);
    const scale = clamp(targetTSS / Math.max(1, nominalTSS), 0.35, 3.2);
    const segments = segmentsOf(tpl.blocks, scale);
    const tss = Physio.tssFromSegments(tpl.sport, segments);
    const durMin = segments.reduce((s, g) => s + g.durMin, 0);
    return { segments, tss: Math.round(tss), durMin: Math.round(durMin) };
  }
  function segmentsOf(blocks, scale) {
    const out = [];
    for (const b of blocks) {
      const sport = b.sport || null;
      if (b.k === 'wu' || b.k === 'cd') {
        out.push({ kind: b.k, durMin: b.dur, i0: b.i0, i1: b.i1,
                   intensity: (b.i0 + b.i1) / 2, label: b.k === 'wu' ? 'Warm-up' : 'Cool-down', sport });
      } else if (b.k === 'ss') {
        const dur = Math.round((b.scalable ? b.dur * scale : b.dur) * 2) / 2;
        out.push({ kind: 'work', durMin: dur, intensity: b.i, label: b.label || 'Steady', sport });
      } else if (b.k === 'set') {
        const on = Math.round((b.scalable ? b.on * scale : b.on) * 2) / 2;
        for (let r = 0; r < b.reps; r++) {
          out.push({ kind: 'work', durMin: on, intensity: b.onI, reps: b.reps, rep: r + 1,
                     label: b.label || 'Interval', sport });
          if (r < b.reps - 1)
            out.push({ kind: 'recover', durMin: b.off, intensity: b.offI, label: 'Recovery', sport });
        }
      } else if (b.k === 'str') {
        out.push({ kind: 'strength', durMin: b.dur, intensity: 0.55, label: b.label, sport: 'strength' });
      }
    }
    return out;
  }

  /* ── phase layout across the macrocycle ──
     Taper/peak are anchored to DISTANCE FROM RACE (measured at each
     week's final day) so partial weeks after a mid-plan regeneration
     still receive a full-length taper. */
  function phaseLayout(nWeeks, totalDays) {
    const taperW = nWeeks >= 12 ? 2 : 1;
    const peakW  = nWeeks >= 10 ? 2 : (nWeeks >= 6 ? 1 : 0);
    const taperDays = taperW * 7, peakDays = peakW * 7;
    const daysLeftAtEnd = w => totalDays - 1 - Math.min(totalDays - 1, w * 7 + 6);

    let lead = 0;
    while (lead < nWeeks && daysLeftAtEnd(lead) >= taperDays + peakDays) lead++;
    const buildW = Math.round(lead * 0.5);
    const baseW = lead - buildW;

    const phases = [];
    for (let w = 0; w < nWeeks; w++) {
      const left = daysLeftAtEnd(w);
      if (left < taperDays) { phases.push('taper'); continue; }
      if (left < taperDays + peakDays) { phases.push('peak'); continue; }
      const i = w < baseW ? w : w - baseW;
      phases.push(i % 4 === 3 ? 'recovery' : (w < baseW ? 'base' : 'build'));
    }
    if (!phases.length) phases.push('taper');
    return phases;
  }

  /* ── main plan builder ──────────────────────────────────── */
  function buildPlan(profile, opts = {}) {
    const start = opts.startDate, race = opts.raceDate;
    const hours = opts.hours ?? profile.weeklyHours;
    const nSess = opts.sessions ?? profile.sessionsPerWeek;
    const disc  = opts.discipline ?? profile.discipline;
    const raceTSS = RACE_TSS[disc] || 150;

    const totalDays = Math.round((race - start) / 86400000) + 1;
    const nWeeks = Math.max(1, Math.ceil(totalDays / 7));
    const phases = phaseLayout(nWeeks, totalDays);

    let ctl0 = opts.ctl0 ?? (hours * 55 / 7) * 0.9;
    let atl0 = opts.atl0 ?? ctl0;

    /* weekly desired TSS (taper scaled by f, solved below) */
    const desiredTSS = f => {
      let ctl = ctl0;
      return phases.map((ph, w) => {
        let tss;
        if (ph === 'taper') {
          tss = f * 7 * ctl;                       // volume ∝ current fitness
        } else {
          const localIdx = phases.slice(0, w + 1).filter(p => p === ph).length - 1;
          const progression = ph === 'recovery' ? RECOVERY_FACTOR : 0.96 + 0.04 * localIdx;
          tss = hours * PHASE_RATE[ph] * progression;
        }
        // ramp-rate cap: weekly CTL gain ≤ RAMP_CAP
        const gain = (1 - Math.exp(-7 / 42));
        const maxAvg = ctl + RAMP_CAP / gain;
        if (ph !== 'taper') tss = Math.min(tss, 7 * maxAvg);
        ctl += (tss / 7 - ctl) * gain;
        return tss;
      });
    };

    /* ── build sessions + PMC for a given taper factor ──
       Solved on the REAL day-by-day distribution (clustered sessions,
       rest days) — not an even weekly spread — so race-day form is exact. */
    let sessionSeq = 0;
    const raceNames = { triathlon: '🏁 RACE · Triathlon', running: '🏁 RACE · Run',
                        cycling: '🏁 RACE · Cycling', cross: '🏁 GOAL EVENT' };
    function assemble(taperF, withSessions) {
      const weekly = desiredTSS(taperF);
      const days = [];
      for (let w = 0; w < nWeeks; w++) {
        const ph = phases[w];
        const daysThisWeek = Math.min(7, totalDays - w * 7);
        for (let d = 0; d < daysThisWeek; d++)
          days.push({ date: new Date(start.getTime() + (w * 7 + d) * 86400000), sessions: [], tss: 0 });
        if (!withSessions) {                       // fast even-spread probe
          days.forEach((dd, i) => { if (Math.floor(i / 7) === w && i < totalDays - 1) dd.tss = weekly[w] / 7; });
          continue;
        }
        const menu = MENUS[disc][ph] || MENUS[disc].base;
        const picks = menu.slice(0, Math.min(nSess, menu.length));
        const shareSum = picks.reduce((s, p) => s + p[1], 0);
        picks.forEach(([tplId, share], i) => {
          const tpl = T[tplId];
          const wk = expandWorkout(tpl, weekly[w] * share / shareSum);
          const s = {
            id: `s${sessionSeq++}`, tplId, sport: tpl.sport, name: tpl.name,
            phase: ph, ...wk, status: 'planned',
          };
          const idx = Math.min(DAY_PRIORITY[i % DAY_PRIORITY.length], daysThisWeek - 1);
          days[w * 7 + idx].sessions.push(s);
        });
      }
      if (withSessions) {
        days[days.length - 1].sessions.push({
          id: `s${sessionSeq++}`, tplId: 'race', sport: 'race', name: raceNames[disc],
          phase: 'taper', segments: [], tss: raceTSS, durMin: 0, status: 'planned', isRace: true,
        });
      }
      for (const d of days) d.tss = d.sessions.length
        ? d.sessions.reduce((s, x) => s + (x.status === 'skipped' ? 0 : x.tss), 0) : d.tss;
      /* race-day form is measured on the start line, before the race
         effort itself lands in the model */
      const pmcInput = days.map(d => d.tss);
      pmcInput[pmcInput.length - 1] = 0;
      const pmcSeries = Physio.pmc(pmcInput, ctl0, atl0);
      pmcSeries[pmcSeries.length - 1].tss = days[days.length - 1].tss;
      return { days, pmcSeries };
    }

    /* solve taper factor f so race-morning TSB ≈ target.
       Two-stage: coarse probe on the fast spread model, final solve on
       the real session distribution. */
    const solveOn = withSessions => {
      let lo = 0.20, hi = 1.10;
      for (let i = 0; i < (withSessions ? 9 : 16); i++) {
        const mid = (lo + hi) / 2;
        (assemble(mid, withSessions).pmcSeries.at(-1).tsb > TSB_TARGET) ? lo = mid : hi = mid;
      }
      return (lo + hi) / 2;
    };
    let taperF = solveOn(false);
    sessionSeq = 0;
    taperF = solveOn(true);                        // exact pass
    sessionSeq = 0;
    const { days, pmcSeries } = assemble(taperF, true);

    const weeks = phases.map((ph, w) => {
      const wDays = days.slice(w * 7, w * 7 + 7);
      return {
        idx: w, phase: ph, start: wDays[0].date,
        tss: Math.round(wDays.reduce((s, d) => s + d.tss, 0)),
        hours: Math.round(wDays.reduce((s, d) => s + d.sessions.reduce((a, x) => a + x.durMin, 0), 0) / 6) / 10,
        ctlEnd: pmcSeries[Math.min(pmcSeries.length - 1, w * 7 + 6)]?.ctl ?? 0,
      };
    });

    return {
      profile, discipline: disc, start, race, days, weeks, pmc: pmcSeries,
      ctl0, atl0, taperF,
      peakCTL: Math.max(...pmcSeries.map(p => p.ctl)),
      raceTSB: pmcSeries[pmcSeries.length - 1].tsb,
      totalTSS: Math.round(days.reduce((s, d) => s + d.tss, 0)),
    };
  }

  /* ─────────────────────────────────────────────────────────
     ADAPTATION ENGINE
     events: {type:'session', id, status} | {type:'illness', start, days}
             | {type:'availability', hours, sessions}
     ───────────────────────────────────────────────────────── */
  function buildAdapted(plan, profile, events, today) {
    const days = plan.days.map(d => ({
      ...d, sessions: d.sessions.map(s => ({ ...s })),
    }));
    const byId = {};
    days.forEach(d => d.sessions.forEach(s => { byId[s.id] = s; }));

    const notes = [];
    let illnessEnd = null;
    for (const ev of events) {
      if (ev.type === 'session' && byId[ev.id]) {
        const s = byId[ev.id];
        if (s.tss0 === undefined) { s.tss0 = s.tss; s.dur0 = s.durMin; }
        s.status = ev.status;
        if (ev.status === 'skipped')          { s.tss = 0; s.durMin = s.dur0; }
        else if (ev.status === 'shortened')   { s.tss = Math.round(s.tss0 * 0.6);  s.durMin = Math.round(s.dur0 * 0.6); }
        else if (ev.status === 'overreached') { s.tss = Math.round(s.tss0 * 1.25); s.durMin = Math.round(s.dur0 * 1.25); }
        else                                  { s.tss = s.tss0; s.durMin = s.dur0; }
        notes.push(`${s.name} → ${ev.status}`);
      }
      if (ev.type === 'illness') {
        const end = new Date(ev.start.getTime() + (ev.days - 1) * 86400000);
        illnessEnd = illnessEnd && illnessEnd > end ? illnessEnd : end;
        for (const d of days)
          if (d.date >= ev.start && d.date <= end) {
            d.sessions.forEach(s => { s.status = 'skipped'; });
            d.illness = true;
          }
        notes.push(`Illness: ${ev.days} days from ${iso(ev.start)}`);
      }
    }
    for (const d of days) d.tss = d.sessions.reduce((s, x) => s + (x.status === 'skipped' ? 0 : x.tss), 0);

    /* where does the re-plan start? */
    let adaptIdx = days.findIndex(d => sameDay(d.date, today));
    if (adaptIdx < 0) adaptIdx = days.findIndex(d => d.date > today);
    if (adaptIdx < 0) adaptIdx = days.length;
    if (illnessEnd && illnessEnd >= today) {                       // mid-illness
      const after = days.findIndex(d => d.date > illnessEnd);
      if (after > adaptIdx) adaptIdx = after;
    }

    /* PMC over history as it actually unfolded */
    const hist = days.slice(0, adaptIdx);
    const histPMC = Physio.pmc(hist.map(d => d.tss), plan.ctl0, plan.atl0);
    const ctlNow = histPMC.length ? histPMC[histPMC.length - 1].ctl : plan.ctl0;
    const atlNow = histPMC.length ? histPMC[histPMC.length - 1].atl : plan.atl0;

    /* regenerate the remainder with ramp cap + taper re-solve */
    const avail = [...events].reverse().find(e => e.type === 'availability');
    let future = { days: [], pmc: [], weeks: [] };
    if (adaptIdx < days.length) {
      future = buildPlan(profile, {
        startDate: days[adaptIdx].date, raceDate: plan.race,
        ctl0: ctlNow, atl0: atlNow,
        hours: avail ? avail.hours : profile.weeklyHours,
        sessions: avail ? avail.sessions : profile.sessionsPerWeek,
        discipline: plan.discipline,
      });
      if (avail) notes.push(`Availability → ${avail.hours} h/wk · ${avail.sessions} sessions`);
    }

    const mergedDays = hist.concat(future.days);
    const mergedPMC = histPMC.concat(future.pmc);
    return {
      ...plan, days: mergedDays, pmc: mergedPMC,
      weeks: hist.length ? weeksFromDays(mergedDays, mergedPMC) : future.weeks,
      peakCTL: Math.max(...mergedPMC.map(p => p.ctl), 0),
      raceTSB: mergedPMC[mergedPMC.length - 1]?.tsb ?? 0,
      totalTSS: Math.round(mergedDays.reduce((s, d) => s + d.tss, 0)),
      notes,
    };
  }

  function weeksFromDays(days, pmcSeries) {
    const weeks = [];
    for (let w = 0; w * 7 < days.length; w++) {
      const wDays = days.slice(w * 7, w * 7 + 7);
      const ph = wDays.flatMap(d => d.sessions).find(s => s.phase)?.phase || 'base';
      weeks.push({
        idx: w, phase: ph, start: wDays[0].date,
        tss: Math.round(wDays.reduce((s, d) => s + d.tss, 0)),
        hours: Math.round(wDays.reduce((s, d) => s + d.sessions.reduce((a, x) => a + x.durMin, 0), 0) / 6) / 10,
        ctlEnd: pmcSeries[Math.min(pmcSeries.length - 1, w * 7 + 6)]?.ctl ?? 0,
      });
    }
    return weeks;
  }

  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const sameDay = (a, b) => iso(a) === iso(b);

  return { TEMPLATES: T, MENUS, buildPlan, buildAdapted, expandWorkout, iso, sameDay, RAMP_CAP, TSB_TARGET };
})();
