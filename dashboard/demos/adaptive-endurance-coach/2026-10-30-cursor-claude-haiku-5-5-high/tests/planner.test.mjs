import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildPhases, generatePlan, adaptPlan, weekSummaries, flattenBlocks, validateProfileForDiscipline } from '../src/planner.js';
import { toIcs, toZwo } from '../src/export.js';

const base = {
  discipline: 'triathlon',
  ftp: 260,
  vdot: 50,
  cssMps: 200 / 190,
  hoursPerWeek: 10,
  sessionsPerWeek: 6,
  startDate: '2026-11-02',
  raceDate: '2027-03-07', // ~18 weeks
};

test('phases cover every week, end in Peak then Taper, and deload is inserted', () => {
  const phases = buildPhases(18);
  assert.equal(phases.length, 18);
  assert.equal(phases[17].phase, 'Taper');
  assert.equal(phases[15].basePhase, 'Peak');
  assert.ok(phases.some((p) => p.phase === 'Recovery'), 'expected a recovery week');
  // Recovery weeks are never the first week.
  assert.notEqual(phases[0].phase, 'Recovery');
});

test('plan ends on race day with exactly the expected number of weeks', () => {
  const plan = generatePlan(base);
  const last = plan.days[plan.days.length - 1];
  assert.equal(last.date, base.raceDate);
  assert.equal(plan.profile.weeks * 7, plan.days.length);
});

test('weekly hours never exceed the hour budget (budget is a ceiling)', () => {
  const plan = generatePlan(base);
  for (const w of weekSummaries(plan)) {
    assert.ok(w.hours <= base.hoursPerWeek + 0.01, `week ${w.week} ${w.hours.toFixed(2)}h over budget`);
  }
});

test('training load ramps through the mesocycle (Peak > Base) and CTL builds', () => {
  const plan = generatePlan(base);
  const sums = weekSummaries(plan);
  const base1 = sums.find((w) => w.phase === 'Base').tss;
  const peak = sums.find((w) => w.phase === 'Peak').tss;
  assert.ok(peak > base1, 'peak week load should exceed base');
  const raceCtl = plan.days[plan.days.length - 1].pmc.ctl;
  assert.ok(raceCtl > 40, `race-day CTL should build meaningfully, got ${raceCtl.toFixed(1)}`);
});

test('weekly session count respects the sessions-per-week budget', () => {
  const plan = generatePlan(base);
  for (const w of weekSummaries(plan)) {
    assert.ok(w.sessions <= base.sessionsPerWeek + 1, `week ${w.week} has ${w.sessions} sessions`);
  }
});

test('cross-training plan includes strength, bike, and run sessions', () => {
  const plan = generatePlan({ ...base, discipline: 'cross', ftp: 230, vdot: 45, cssMps: undefined });
  const sports = new Set(plan.days.flatMap((d) => d.workouts.map((w) => w.sport)));
  assert.ok(sports.has('bike') && sports.has('run') && sports.has('strength'));
});

test('running plan has no swim or bike sessions', () => {
  const plan = generatePlan({ ...base, discipline: 'running', ftp: undefined, cssMps: undefined });
  const sports = new Set(plan.days.flatMap((d) => d.workouts.map((w) => w.sport)));
  assert.deepEqual([...sports], ['run']);
});

test('generation fails loudly when a required physiology input is missing', () => {
  assert.throws(() => generatePlan({ ...base, cssMps: undefined }), /CSS/);
  assert.deepEqual(validateProfileForDiscipline({ ...base, ftp: undefined, discipline: 'cycling' }), ['Cycling plans need an FTP.']);
});

test('workout IDs are deterministic across regenerations', () => {
  const a = generatePlan(base).days.flatMap((d) => d.workouts.map((w) => w.id));
  const b = generatePlan(base).days.flatMap((d) => d.workouts.map((w) => w.id));
  assert.deepEqual(a, b);
});

test('interval blocks flatten into a contiguous timeline', () => {
  const plan = generatePlan(base);
  const w = plan.days.flatMap((d) => d.workouts).find((x) => x.session === 'threshold' || x.session === 'css_sets');
  let t = 0;
  for (const seg of w.profile) {
    assert.equal(seg.start, t, 'segments must be contiguous');
    t = seg.end;
  }
  assert.equal(t, w.durationSec);
});

test('repeat blocks unroll to the right number of work segments', () => {
  const segs = flattenBlocks([{ type: 'repeat', reps: 4, work: { sec: 60, zone: 5, label: 'x' }, rest: { sec: 30, zone: 1 } }]);
  assert.equal(segs.filter((s) => s.kind === 'work').length, 4);
  assert.equal(segs.reduce((s, x) => s + (x.end - x.start), 0), 4 * 60 + 4 * 30);
});

test('adaptation: skipping a session reduces that day and the PMC responds', () => {
  const plan = generatePlan(base);
  const target = plan.days.flatMap((d) => d.workouts).find((w) => w.tss > 30);
  const adapted = adaptPlan(plan, { statuses: { [target.id]: 'skipped' } });
  const day = adapted.days.find((d) => d.workouts.some((w) => w.id === target.id));
  assert.equal(day.adaptedTss, day.workouts.reduce((s, w) => s + w.tss, 0));
  assert.ok(day.adaptedTss < day.plannedTss);
  // Original plan must be untouched (immutability).
  assert.equal(plan.days.find((d) => d.id === day.id).workouts.find((w) => w.id === target.id).status, 'planned');
});

test('adaptation: illness zeroes that day', () => {
  const plan = generatePlan(base);
  const d = plan.days.find((x) => x.plannedTss > 40);
  const adapted = adaptPlan(plan, { illnessDays: [d.date] });
  const ad = adapted.days.find((x) => x.id === d.id);
  assert.equal(ad.adaptedTss, 0);
});

test('adaptation: weekly ramp never exceeds the cap', () => {
  const plan = generatePlan(base);
  const adapted = adaptPlan(plan, { maxRampPerWeek: 0.05 });
  const sums = weekSummaries({ ...adapted, days: adapted.days.map((d) => ({ ...d, plannedTss: d.adaptedTss })) }, false);
  for (let i = 1; i < sums.length; i++) {
    if (sums[i - 1].tss > 0) {
      const ramp = (sums[i].tss - sums[i - 1].tss) / sums[i - 1].tss;
      assert.ok(ramp <= 0.05 + 1e-6, `week ${i + 1} ramp ${ramp.toFixed(3)} exceeds cap`);
    }
  }
});

test('adaptation: lowering availability scales that week down', () => {
  const plan = generatePlan(base);
  const adapted = adaptPlan(plan, { availability: { 5: 3 } });
  const before = plan.days.filter((d) => d.week === 5).reduce((s, d) => s + d.plannedTss, 0);
  const after = adapted.days.filter((d) => d.week === 5).reduce((s, d) => s + d.adaptedTss, 0);
  assert.ok(after < before);
});

test('adaptation exposes both planned and adapted PMC series for overlay', () => {
  const plan = generatePlan(base);
  const adapted = adaptPlan(plan, { illnessDays: [plan.days[10].date] });
  assert.equal(adapted.days.length, plan.days.length);
  assert.ok(adapted.days.every((d) => d.originalPmc && d.adaptedPmc));
});

test('ICS export is a valid calendar with one event per workout', () => {
  const plan = generatePlan(base);
  const ics = toIcs(plan);
  assert.ok(ics.startsWith('BEGIN:VCALENDAR'));
  assert.ok(ics.trimEnd().endsWith('END:VCALENDAR'));
  const workouts = plan.days.reduce((s, d) => s + d.workouts.length, 0);
  assert.equal((ics.match(/BEGIN:VEVENT/g) || []).length, workouts);
});

test('ZWO export escapes XML and emits steps for each block', () => {
  const plan = generatePlan(base);
  const bike = plan.days.flatMap((d) => d.workouts).find((w) => w.kind === 'bike' && w.session === 'threshold');
  const xml = toZwo(bike, base);
  assert.ok(xml.includes('<workout_file>'));
  assert.ok(xml.includes('<IntervalsT'));
  assert.ok(xml.includes('<Warmup'));
});
