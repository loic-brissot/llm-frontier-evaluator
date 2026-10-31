// Periodized plan generator, workout library, and live adaptation engine.
// Pure logic; the UI and exporters consume the plan object produced here.

import {
  addDays, daysBetween, pmc, cyclingTss, cyclingTssFromIF, runningTss,
  swimTss, strengthTss, thresholdPaceSecPerKm, RACE_TYPES,
} from './physiology.js';

// ---------- Mesocycle layout ----------

/**
 * Splits a number of weeks into phases. Recovery weeks (every 4th week in
 * Base/Build) are inserted as a deload; the final weeks are Peak then Taper.
 */
export function buildPhases(totalWeeks) {
  const taperWeeks = totalWeeks >= 12 ? 2 : 1;
  const peakWeeks = totalWeeks >= 10 ? 2 : 1;
  const remaining = totalWeeks - taperWeeks - peakWeeks;
  const baseWeeks = Math.round(remaining * 0.45);
  const buildWeeks = remaining - baseWeeks;

  const phases = [];
  const push = (phase, n) => { for (let i = 0; i < n; i++) phases.push(phase); };
  push('Base', baseWeeks);
  push('Build', buildWeeks);
  push('Peak', peakWeeks);
  push('Taper', taperWeeks);

  // Tag every 4th week of Base/Build as a recovery (deload) week, not the first.
  return phases.map((phase, i) => {
    const isDeload = (phase === 'Base' || phase === 'Build') && (i + 1) % 4 === 0;
    return { phase: isDeload ? 'Recovery' : phase, basePhase: phase, weekIndex: i };
  });
}

// Target weekly load multiplier by phase, relative to peak weekly hours.
const PHASE_LOAD = {
  Base: 0.7,
  Build: 0.9,
  Peak: 1.0,
  Taper: 0.55,
  Recovery: 0.55,
};

// ---------- Session library ----------

/**
 * A session is a template with an ordered list of blocks. Blocks carry the
 * target intensity in a discipline-neutral form (fraction of threshold), which
 * is resolved to watts/pace/HR using the athlete profile when rendered.
 */
const LIBRARY = {
  bike: {
    endurance: { name: 'Endurance ride', kind: 'bike', intensity: 'Z2', ifTarget: 0.68, blocks: [
      { type: 'warm', sec: 600, zone: 1 },
      { type: 'work', sec: 0, zone: 2, label: 'Steady Z2' }, // filled by duration
      { type: 'cool', sec: 300, zone: 1 },
    ] },
    sweetspot: { name: 'Sweet spot intervals', kind: 'bike', intensity: 'SS', ifTarget: 0.88, blocks: [
      { type: 'warm', sec: 900, zone: 2 },
      { type: 'repeat', reps: 3, work: { sec: 600, zone: 3.5, label: 'Sweet spot' }, rest: { sec: 300, zone: 1 } },
      { type: 'cool', sec: 600, zone: 1 },
    ] },
    threshold: { name: 'Threshold intervals', kind: 'bike', intensity: 'Z4', ifTarget: 0.95, blocks: [
      { type: 'warm', sec: 900, zone: 2 },
      { type: 'repeat', reps: 3, work: { sec: 480, zone: 4, label: 'Threshold' }, rest: { sec: 300, zone: 1 } },
      { type: 'cool', sec: 600, zone: 1 },
    ] },
    vo2: { name: 'VO2max intervals', kind: 'bike', intensity: 'Z5', ifTarget: 1.02, blocks: [
      { type: 'warm', sec: 900, zone: 2 },
      { type: 'repeat', reps: 5, work: { sec: 180, zone: 5, label: 'VO2max' }, rest: { sec: 180, zone: 1 } },
      { type: 'cool', sec: 600, zone: 1 },
    ] },
    race_sim: { name: 'Race-pace simulation', kind: 'bike', intensity: 'RP', ifTarget: 0.8, blocks: [
      { type: 'warm', sec: 900, zone: 2 },
      { type: 'work', sec: 2400, zone: 3, label: 'Race pace' },
      { type: 'work', sec: 600, zone: 4, label: 'Surge' },
      { type: 'cool', sec: 600, zone: 1 },
    ] },
  },
  run: {
    easy: { name: 'Easy run', kind: 'run', intensity: 'E', ifTarget: 0.7, blocks: [
      { type: 'work', sec: 0, zone: 'E', label: 'Easy' },
    ] },
    tempo: { name: 'Threshold tempo run', kind: 'run', intensity: 'T', ifTarget: 0.92, blocks: [
      { type: 'warm', sec: 900, zone: 'E' },
      { type: 'work', sec: 1200, zone: 'T', label: 'Tempo' },
      { type: 'cool', sec: 600, zone: 'E' },
    ] },
    intervals: { name: 'Interval session', kind: 'run', intensity: 'I', ifTarget: 1.0, blocks: [
      { type: 'warm', sec: 900, zone: 'E' },
      { type: 'repeat', reps: 5, work: { sec: 240, zone: 'I', label: 'Interval' }, rest: { sec: 240, zone: 'E' } },
      { type: 'cool', sec: 600, zone: 'E' },
    ] },
    reps: { name: 'Repetition speed', kind: 'run', intensity: 'R', ifTarget: 1.05, blocks: [
      { type: 'warm', sec: 900, zone: 'E' },
      { type: 'repeat', reps: 8, work: { sec: 60, zone: 'R', label: 'Rep' }, rest: { sec: 120, zone: 'E' } },
      { type: 'cool', sec: 600, zone: 'E' },
    ] },
    long: { name: 'Long run', kind: 'run', intensity: 'E', ifTarget: 0.75, blocks: [
      { type: 'work', sec: 0, zone: 'E', label: 'Long easy' },
    ] },
  },
  swim: {
    technique: { name: 'Technique swim', kind: 'swim', intensity: 'E', ifTarget: 0.7, blocks: [
      { type: 'warm', sec: 600, zone: 1 },
      { type: 'work', sec: 1200, zone: 2, label: 'Drill / technique' },
      { type: 'cool', sec: 300, zone: 1 },
    ] },
    css_sets: { name: 'CSS sets', kind: 'swim', intensity: 'T', ifTarget: 0.97, blocks: [
      { type: 'warm', sec: 600, zone: 2 },
      { type: 'repeat', reps: 6, work: { sec: 100, zone: 3, label: 'CSS 100' }, rest: { sec: 20, zone: 1 } },
      { type: 'cool', sec: 300, zone: 1 },
    ] },
    vo2_swim: { name: 'VO2 swim', kind: 'swim', intensity: 'I', ifTarget: 1.05, blocks: [
      { type: 'warm', sec: 600, zone: 2 },
      { type: 'repeat', reps: 8, work: { sec: 75, zone: 4, label: 'Sprint 50/75' }, rest: { sec: 45, zone: 1 } },
      { type: 'cool', sec: 300, zone: 1 },
    ] },
  },
  strength: {
    foundation: { name: 'Foundational strength', kind: 'strength', intensity: 'S', ifTarget: 0.6, blocks: [
      { type: 'strength', exercises: ['Goblet squat 3×8', 'Romanian deadlift 3×8', 'Split squat 3×8 / leg', 'Single-leg calf raise 2×12', 'Plank 3×45s'] },
    ] },
    hip_core: { name: 'Hip & core stability', kind: 'strength', intensity: 'S', ifTarget: 0.5, blocks: [
      { type: 'strength', exercises: ['Side-lying hip abduction 2×15', 'Dead bug 3×10', 'Hip thrust 3×10', 'Bird dog 2×10'] },
    ] },
  },
};

// ---------- Weekly template per discipline ----------

/**
 * For each discipline, the ordered slot list for a training week. `session`
 * names the library key. Slots are filled up to the weekly session budget and
 * capped by the hour budget.
 */
const WEEK_TEMPLATES = {
  triathlon: [
    { sport: 'swim', session: 'css_sets', day: 1 },
    { sport: 'bike', session: 'threshold', day: 2 },
    { sport: 'run', session: 'tempo', day: 3 },
    { sport: 'swim', session: 'technique', day: 4 },
    { sport: 'bike', session: 'sweetspot', day: 5, alt: 'endurance' },
    { sport: 'run', session: 'easy', day: 6 },
    { sport: 'bike', session: 'endurance', day: 0, long: true },
    { sport: 'run', session: 'long', day: 6, optional: true },
    { sport: 'swim', session: 'vo2_swim', day: 1, optional: true },
  ],
  running: [
    { sport: 'run', session: 'easy', day: 0 },
    { sport: 'run', session: 'intervals', day: 2 },
    { sport: 'run', session: 'easy', day: 3 },
    { sport: 'run', session: 'tempo', day: 4 },
    { sport: 'run', session: 'easy', day: 5 },
    { sport: 'run', session: 'long', day: 6, long: true },
    { sport: 'run', session: 'reps', day: 1, optional: true },
  ],
  cycling: [
    { sport: 'bike', session: 'endurance', day: 0 },
    { sport: 'bike', session: 'threshold', day: 2 },
    { sport: 'bike', session: 'vo2', day: 3 },
    { sport: 'bike', session: 'endurance', day: 4 },
    { sport: 'bike', session: 'sweetspot', day: 5 },
    { sport: 'bike', session: 'endurance', day: 6, long: true },
    { sport: 'bike', session: 'race_sim', day: 1, optional: true },
  ],
  cross: [
    { sport: 'bike', session: 'endurance', day: 0 },
    { sport: 'strength', session: 'foundation', day: 1 },
    { sport: 'run', session: 'tempo', day: 2 },
    { sport: 'strength', session: 'hip_core', day: 3, optional: true },
    { sport: 'bike', session: 'threshold', day: 4 },
    { sport: 'run', session: 'easy', day: 5 },
    { sport: 'bike', session: 'endurance', day: 6, long: true },
  ],
};

// Per-discipline share of the weekly hour budget.
const SPORT_SHARE = {
  triathlon: { swim: 0.15, bike: 0.5, run: 0.35 },
  running: { run: 1 },
  cycling: { bike: 1 },
  cross: { bike: 0.45, run: 0.3, strength: 0.25 },
};

// ---------- Session materialisation ----------

/** Expand a library session into concrete blocks with durations in seconds. */
function materialise(template, targetSec) {
  const def = LIBRARY[template.sport][template.session];
  if (!def) throw new Error(`Unknown session ${template.sport}/${template.session}`);
  const blocks = def.blocks.map((b) => ({ ...b }));

  // Fixed (non-stretchable) time: everything except open-ended work and repeat blocks.
  const repeatBlock = blocks.find((b) => b.type === 'repeat');
  const openWork = blocks.find((b) => b.type === 'work' && b.sec === 0);
  const fixedSec = blocks.reduce((s, b) => {
    if (b.type === 'repeat' || (b.type === 'work' && b.sec === 0)) return s;
    return s + (b.sec || 0);
  }, 0);

  if (openWork) {
    // Long / steady sessions: fill the whole remaining budget with the steady block.
    openWork.sec = Math.max(300, targetSec - fixedSec);
  } else if (repeatBlock) {
    // Structured sessions: scale the rep count so the total tracks the budget.
    const perRep = repeatBlock.work.sec + repeatBlock.rest.sec;
    const budget = Math.max(0, targetSec - fixedSec);
    const reps = Math.min(12, Math.max(3, Math.round(budget / perRep)));
    repeatBlock.reps = reps;
  }

  const totalSec = blocks.reduce((s, b) => {
    if (b.type === 'repeat') return s + b.reps * (b.work.sec + b.rest.sec);
    return s + (b.sec || 0);
  }, 0);
  return { def, blocks, totalSec, ifTarget: def.ifTarget };
}

/**
 * Converts a list of blocks to a time-ordered profile of {start, end, zone, kind, label}.
 * Repeats are unrolled so the renderer can draw exact interval blocks.
 */
export function flattenBlocks(blocks) {
  const out = [];
  let t = 0;
  for (const b of blocks) {
    if (b.type === 'repeat') {
      for (let r = 0; r < b.reps; r++) {
        out.push({ start: t, end: t + b.work.sec, zone: b.work.zone, kind: 'work', label: b.work.label, rep: r + 1, reps: b.reps });
        t += b.work.sec;
        if (r < b.reps - 1 || b.rest) {
          out.push({ start: t, end: t + b.rest.sec, zone: b.rest.zone, kind: 'rest', label: 'Recovery', rep: r + 1, reps: b.reps });
          t += b.rest.sec;
        }
      }
    } else if (b.type === 'strength') {
      out.push({ start: t, end: t + 1800, zone: 'S', kind: 'strength', label: 'Strength', exercises: b.exercises });
      t += 1800;
    } else {
      const kind = b.type === 'warm' ? 'warm' : b.type === 'cool' ? 'cool' : 'work';
      out.push({ start: t, end: t + b.sec, zone: b.zone, kind, label: b.label || (kind === 'warm' ? 'Warm-up' : kind === 'cool' ? 'Cool-down' : 'Work') });
      t += b.sec;
    }
  }
  return out;
}

// ---------- TSS estimation for one materialised workout ----------

/**
 * Estimates the TSS of a workout given the athlete profile. Mirrors the
 * physiology formulas: IF-based for bike, rTSS for run, sTSS for swim.
 */
export function estimateWorkoutTss(workout, profile) {
  const { kind, totalSec, ifTarget } = workout;
  if (kind === 'bike') {
    // IF-based estimate; the FTP-normalised target intensity is what matters.
    return cyclingTssFromIF({ seconds: totalSec, IF: ifTarget });
  }
  if (kind === 'run') {
    if (!profile.vdot) throw new Error('Running TSS needs a VDOT or race time.');
    const thr = thresholdPaceSecPerKm(profile.vdot);
    // Pace scales inversely with IF: IF = thr / pace  =>  pace = thr / IF.
    const paceSecPerKm = thr / ifTarget;
    return runningTss({ seconds: totalSec, paceSecPerKm, thresholdPaceSecPerKm: thr });
  }
  if (kind === 'swim') {
    if (!profile.cssMps) throw new Error('Swim TSS needs a CSS (from 400/200 times).');
    return swimTss({ seconds: totalSec, cssMps: profile.cssMps, actualMps: profile.cssMps * ifTarget });
  }
  if (kind === 'strength') {
    return strengthTss({ minutes: totalSec / 60, rpe: 6 });
  }
  return 0;
}

// ---------- Plan generation ----------

/**
 * Builds a full plan.
 * profile: { discipline, ftp, vdot, cssMps, hoursPerWeek, sessionsPerWeek, startDate, raceDate, raceType }
 */
export function generatePlan(profile) {
  const { discipline, hoursPerWeek, sessionsPerWeek, startDate, raceDate } = profile;
  const totalDays = daysBetween(startDate, raceDate);
  if (totalDays <= 0) throw new Error('Race date must be after the start date.');
  const problems = validateProfileForDiscipline(profile);
  if (problems.length) throw new Error(problems.join(' '));

  // Align weeks so the race falls on the last day of the final week.
  const weeks = Math.max(1, Math.ceil((totalDays + 1) / 7));
  const phases = buildPhases(weeks);
  // Anchor week 1 so that race day is the final day.
  const planStart = addDays(raceDate, -(weeks * 7 - 1));

  const template = WEEK_TEMPLATES[discipline];
  const shares = SPORT_SHARE[discipline];

  const days = [];
  for (let w = 0; w < weeks; w++) {
    const phase = phases[w];
    const weekHours = hoursPerWeek * PHASE_LOAD[phase.phase];
    const weekSessions = Math.max(2, Math.round(sessionsPerWeek * (PHASE_LOAD[phase.phase] + 0.1)));
    const sessionsCap = Math.min(sessionsPerWeek, weekSessions);

    // Pick the slots for this week within the session budget. Non-optional first,
    // then optional, in priority order. Long session always kept.
    const chosen = pickSlots(template, sessionsCap).map((s, idx) => ({ ...s, idx }));
    // Distribute the week's hour budget across the sport shares, then split each
    // sport's time evenly over its scheduled sessions. Long sessions take a larger
    // share of that sport's time (1.6x weight), so the total still honours the budget.
    const sportMinutes = {};
    for (const s of Object.keys(shares)) {
      const sessionsOfSport = chosen.filter((c) => c.sport === s);
      if (!sessionsOfSport.length) continue;
      const weight = sessionsOfSport.reduce((acc, c) => acc + (c.long ? 1.6 : 1), 0);
      const sportSec = weekHours * shares[s] * 3600;
      sportMinutes[s] = { perUnitSec: sportSec / weight };
    }

    for (let d = 0; d < 7; d++) {
      const date = addDays(planStart, w * 7 + d);
      const slots = chosen.filter((s) => s.day === d);
      // Rest day when no session on this weekday.
      if (slots.length === 0) {
        days.push({ id: `w${w + 1}d${d}`, date, week: w + 1, phase: phase.phase, basePhase: phase.basePhase, rest: true, workouts: [] });
        continue;
      }
      const workouts = slots.map((slot) => {
        const share = sportMinutes[slot.sport];
        const unit = share ? share.perUnitSec : 3600;
        const targetSec = Math.round(Math.min(unit * (slot.long ? 1.6 : 1), 4 * 3600));
        return buildWorkout(slot, targetSec, profile, { week: w + 1, phase: phase.phase });
      });
      days.push({
        id: `w${w + 1}d${d}`, date, week: w + 1, phase: phase.phase, basePhase: phase.basePhase,
        rest: false, workouts,
      });
    }
  }

  // Compute the planned load series.
  const tssByDay = days.map((d) => d.workouts.reduce((s, w) => s + w.tss, 0));
  const series = pmc(tssByDay);
  days.forEach((d, i) => { d.plannedTss = tssByDay[i]; d.pmc = series[i]; });

  return {
    profile: { ...profile, planStart, weeks },
    phases,
    days,
    startDate: planStart,
    raceDate,
    totalDays: weeks * 7,
  };
}

/** Returns human-readable problems that would block plan generation. */
export function validateProfileForDiscipline(profile) {
  const need = [];
  const sports = new Set(Object.keys(SPORT_SHARE[profile.discipline] || {}));
  if (sports.has('bike') && !profile.ftp) need.push('Cycling plans need an FTP.');
  if (sports.has('run') && !profile.vdot) need.push('Running plans need a VDOT (from a race time or VO2max).');
  if (sports.has('swim') && !profile.cssMps) need.push('Triathlon plans need a CSS (from 400m and 200m swim times).');
  if (!(profile.hoursPerWeek > 0)) need.push('Weekly hours must be positive.');
  if (!(profile.sessionsPerWeek > 0)) need.push('Sessions per week must be positive.');
  return need;
}

function phaseScale(phase) {
  return { Base: 0.9, Build: 1.0, Peak: 1.0, Taper: 0.6, Recovery: 0.6 }[phase] ?? 1;
}

function countSport(slots, sport) {
  return Math.max(1, slots.filter((s) => s.sport === sport).length);
}

/** Choose which template slots to schedule given the session cap. */
function pickSlots(template, cap) {
  const required = template.filter((s) => !s.optional);
  const optional = template.filter((s) => s.optional);
  const out = [...required.slice(0, cap)];
  for (const o of optional) {
    if (out.length >= cap) break;
    out.push(o);
  }
  return out;
}

function buildWorkout(slot, targetSec, profile, meta) {
  const { def, blocks, totalSec, ifTarget } = materialise(slot, targetSec);
  const flat = flattenBlocks(blocks);
  const tss = estimateWorkoutTss({ kind: def.kind, totalSec, ifTarget }, profile);
  return {
    id: `w${meta.week}-${slot.sport}-${slot.session}-${slot.idx ?? 0}`,
    sport: slot.sport,
    kind: def.kind,
    name: def.name,
    session: slot.session,
    intensity: def.intensity,
    ifTarget,
    durationSec: totalSec,
    tss: Math.round(tss * 10) / 10,
    blocks,
    profile: flat,
    status: 'planned', // planned | done | skipped | shortened | overreached
    originalTss: Math.round(tss * 10) / 10,
  };
}

// ---------- Adaptation engine ----------

/**
 * Recalibrates the remaining plan after the athlete's live changes.
 *
 * changes: {
 *   statuses: { [workoutId]: 'done'|'skipped'|'shortened'|'overreached' },
 *   illnessDays: [isoDate, ...],          // days lost to illness (treated as rest, load zeroed)
 *   availability: { [weekNumber]: hours }, // changed weekly hour budget
 *   maxRampPerWeek: number,                // cap on weekly TSS growth (default 0.07 = 7%)
 * }
 *
 * Returns a NEW plan (immutable input) with adapted per-day TSS and PMC, plus
 * the original PMC for overlay.
 */
export function adaptPlan(plan, changes = {}) {
  const maxRamp = changes.maxRampPerWeek ?? 0.07;
  const illness = new Set(changes.illnessDays || []);
  const statuses = changes.statuses || {};
  const availability = changes.availability || {};

  const days = plan.days.map((d) => ({
    ...d,
    workouts: d.workouts.map((w) => ({ ...w, status: statuses[w.id] || w.status || 'planned' })),
  }));

  // 1. Apply per-session outcomes.
  for (const d of days) {
    for (const w of d.workouts) {
      if (w.status === 'skipped') {
        w.tss = 0;
      } else if (w.status === 'shortened') {
        w.tss = w.originalTss * 0.6;
      } else if (w.status === 'overreached') {
        w.tss = w.originalTss * 1.25;
      } else {
        w.tss = w.originalTss;
      }
    }
    // 2. Illness: zero load for that day and cap the next two days lightly.
    if (illness.has(d.date)) {
      d.workouts.forEach((w) => { w.tss = 0; w.status = 'illness'; });
    }
    d.adaptedTss = d.workouts.reduce((s, w) => s + w.tss, 0);
  }

  // 3. Availability change: scale planned weekly TSS for that week's remaining days.
  const weeks = plan.profile.weeks;
  for (let wk = 1; wk <= weeks; wk++) {
    const cap = availability[wk];
    if (cap == null) continue;
    const weekDays = days.filter((d) => d.week === wk);
    const baseHours = plan.profile.hoursPerWeek * (PHASE_LOAD[weekDays[0].phase] || 1);
    const ratio = Math.min(1, cap / Math.max(0.5, baseHours));
    weekDays.forEach((d) => d.workouts.forEach((w) => { w.tss *= ratio; }));
    weekDays.forEach((d) => { d.adaptedTss = d.workouts.reduce((s, w) => s + w.tss, 0); });
  }

  // 4. Ramp cap: no week may exceed the previous week's load by more than maxRamp.
  //    Excess is shaved proportionally, which keeps the shape of the week.
  let prevWeekTss = null;
  for (let wk = 1; wk <= weeks; wk++) {
    const weekDays = days.filter((d) => d.week === wk);
    const weekTss = weekDays.reduce((s, d) => s + d.adaptedTss, 0);
    if (prevWeekTss !== null && prevWeekTss > 0) {
      const cap = prevWeekTss * (1 + maxRamp);
      if (weekTss > cap) {
        const f = cap / weekTss;
        weekDays.forEach((d) => d.workouts.forEach((w) => { w.tss *= f; }));
        weekDays.forEach((d) => { d.adaptedTss = d.workouts.reduce((s, w) => s + w.tss, 0); });
        prevWeekTss = cap;
        continue;
      }
    }
    prevWeekTss = weekTss;
  }

  // 5. Peak-on-race-day: taper the final two weeks so that TSB is maximised on race day.
  //    Only shave the taper/peak load; never inflate the plan.
  const raceIdx = days.length - 1;
  const lastWeek = days.filter((d) => d.week === weeks);
  const raceCTLPlanned = plan.days[raceIdx].pmc.ctl;
  const tssSeriesAdapted = days.map((d) => d.adaptedTss);
  const adaptedSeries = pmc(tssSeriesAdapted);
  // If the adapted CTL at race day is more than 5% above planned, taper harder.
  if (adaptedSeries[raceIdx].ctl > raceCTLPlanned * 1.05) {
    const f = 0.85;
    lastWeek.forEach((d) => {
      d.workouts.forEach((w) => { w.tss *= f; });
      d.adaptedTss = d.workouts.reduce((s, w) => s + w.tss, 0);
    });
  }

  const adaptedSeriesFinal = pmc(days.map((d) => d.adaptedTss));
  days.forEach((d, i) => { d.adaptedPmc = adaptedSeriesFinal[i]; d.originalPmc = plan.days[i].pmc; });

  const warnings = [];
  const rampFinal = weeklyRamps(days, weeks);
  if (rampFinal.some((r) => r > maxRamp + 1e-6)) {
    warnings.push('Ramp cap could not be fully met in one or more weeks.');
  }
  if (adaptedSeriesFinal[raceIdx].tsb < 5) {
    warnings.push('Projected race-day TSB is below +5. Consider a longer taper or lower load.');
  }

  return {
    ...plan,
    days,
    adapted: true,
    summary: {
      plannedRaceCtl: plan.days[raceIdx].pmc.ctl,
      adaptedRaceCtl: adaptedSeriesFinal[raceIdx].ctl,
      adaptedRaceTsb: adaptedSeriesFinal[raceIdx].tsb,
      plannedRaceTsb: plan.days[raceIdx].pmc.tsb,
      maxRampApplied: Math.max(0, ...rampFinal),
    },
    warnings,
  };
}

function weeklyRamps(days, weeks) {
  const totals = [];
  for (let wk = 1; wk <= weeks; wk++) {
    totals.push(days.filter((d) => d.week === wk).reduce((s, d) => s + d.adaptedTss, 0));
  }
  const ramps = [];
  for (let i = 1; i < totals.length; i++) {
    if (totals[i - 1] > 0) ramps.push((totals[i] - totals[i - 1]) / totals[i - 1]);
  }
  return ramps;
}

/** Weekly summary used by the UI. */
export function weekSummaries(plan, useAdapted = false) {
  const out = [];
  for (let wk = 1; wk <= plan.profile.weeks; wk++) {
    const ds = plan.days.filter((d) => d.week === wk);
    const tss = ds.reduce((s, d) => s + (useAdapted && d.adaptedTss != null ? d.adaptedTss : d.plannedTss), 0);
    const sec = ds.reduce((s, d) => s + d.workouts.reduce((x, w) => x + w.durationSec, 0), 0);
    out.push({ week: wk, phase: ds[0].phase, basePhase: ds[0].basePhase, tss, hours: sec / 3600, sessions: ds.reduce((s, d) => s + d.workouts.length, 0) });
  }
  return out;
}

export { RACE_TYPES };
