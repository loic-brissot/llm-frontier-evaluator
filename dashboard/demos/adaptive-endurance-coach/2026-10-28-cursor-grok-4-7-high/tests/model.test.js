import assert from "node:assert/strict";
import { defaultProfile, emptyAdaptations } from "../js/catalog.js";
import { formatPace } from "../js/format.js";
import {
  cogganTSS,
  cssFromTest,
  formLabel,
  paceSecPerKmFromVO2Frac,
  repetitionIntensity,
  runningPaces,
  simulateLoads,
  stressOf,
  swimStress,
  vdotFromRace,
  velocityFromVO2,
} from "../js/physio.js";
import { buildStudio } from "../js/plan.js";
import { sessionsToIcs, workoutToZwo } from "../js/export.js";

function approx(actual, expected, tol, label) {
  assert.ok(Math.abs(actual - expected) <= tol, `${label}: got ${actual}, expected ${expected} ± ${tol}`);
}

function clockToSec(label) {
  const [m, s] = label.split(":")[0] === undefined ? [0, 0] : label.replace("/km", "").split(":").map(Number);
  return m * 60 + s;
}

// —— Physiology ——
{
  const ftp = 250;
  const hour = [{ sec: 3600, i0: 1, i1: 1, modality: "bike" }];
  const tss = cogganTSS(hour);
  approx(tss.tss, 100, 0.01, "1h at FTP");
  approx(tss.iff, 1, 0.001, "IF at FTP");

  const steady = simulateLoads(Array.from({ length: 30 }, () => 60), 60, 60);
  approx(steady[29].ctl, 60, 0.001, "CTL holds when TSS equals CTL");
  approx(steady[29].atl, 60, 0.001, "ATL holds when TSS equals ATL");
  approx(steady[29].tsb, 0, 0.001, "TSB is CTL − ATL");

  const step = simulateLoads([102], 60, 60);
  approx(step[0].ctl, 60 + (102 - 60) / 42, 1e-9, "CTL recurrence");
  approx(step[0].atl, 60 + (102 - 60) / 7, 1e-9, "ATL recurrence");
  approx(step[0].tsb, step[0].ctl - step[0].atl, 1e-9, "TSB identity");
}

{
  const vdot = vdotFromRace(5000, 19 * 60 + 57);
  approx(vdot, 50, 0.15, "VDOT of a 19:57 5K");
  const paces = runningPaces(50);
  const sec = (label) => {
    const [m, s] = formatPace(label).replace("/km", "").split(":").map(Number);
    return m * 60 + s;
  };
  approx(sec(paces.threshold), clockToSec("4:15"), 2, "T pace at VDOT 50");
  approx(sec(paces.easy[1]), clockToSec("4:54"), 3, "fast E pace");
  approx(sec(paces.easy[0]), clockToSec("5:34"), 3, "slow E pace");
  approx(sec(paces.marathon), clockToSec("4:30"), 3, "M pace");
  approx(sec(paces.interval), clockToSec("3:55"), 3, "I pace");
  approx(sec(paces.repetition), clockToSec("3:38"), 3, "R pace");
  approx(repetitionIntensity(50) > 1, true, 0, "reps faster than threshold");
  const predicted = vdotFromRace(10000, 41 * 60 + 21);
  approx(predicted, 50, 0.4, "10K equivalence near VDOT 50");
  assert.ok(velocityFromVO2(50) > 200, "velocity from VO2");
  assert.equal(paceSecPerKmFromVO2Frac(50, 0.88) > 0, true);
}

{
  const css = cssFromTest(150, 320);
  approx(css, 200 / 170, 1e-9, "CSS from 200/400");
  const hour = [{ sec: 3600, i0: 1, i1: 1, modality: "swim" }];
  approx(swimStress(hour).tss, 100, 0.01, "1h at CSS is 100 sTSS");
  const easy = swimStress([{ sec: 3600, i0: 0.8, i1: 0.8 }]);
  approx(easy.tss, 0.8 ** 3 * 100, 0.01, "cubic swim stress");
}

{
  const runHour = [{ sec: 3600, i0: 1, i1: 1, modality: "run" }];
  approx(stressOf(runHour).tss, 100, 0.01, "1h at threshold pace is 100 rTSS");
  const mixed = stressOf([
    { sec: 1800, i0: 1, i1: 1, modality: "bike" },
    { sec: 1800, i0: 1, i1: 1, modality: "run" },
  ]);
  approx(mixed.tss, 100, 0.05, "brick sums sport stress");
}

assert.equal(formLabel(18).key, "peak");
assert.equal(formLabel(-4).name, "Neutral");

// —— Plan ——
const studio = buildStudio(defaultProfile(), emptyAdaptations());
assert.equal(studio.ok, true, studio.error);
const plan = studio.original;
assert.equal(plan.dates[0], "2026-11-02");
assert.equal(plan.dates.at(-1), "2027-02-21");
assert.equal(plan.dates.length, 112);
assert.equal(plan.weeks.length, 16);
assert.ok(plan.raceMorning.tsb >= 8 && plan.raceMorning.tsb <= 28, `race morning TSB ${plan.raceMorning.tsb}`);
assert.ok(plan.stats.peakCtl > plan.startLoad.ctl, "CTL rises into the race");

const phases = plan.weeks.map((week) => week.phase);
assert.ok(phases.includes("base") && phases.includes("build") && phases.includes("peak") && phases.includes("taper") && phases.includes("recovery"), phases.join(","));
assert.equal(phases.at(-1), "taper");

for (const week of plan.weeks) {
  if (week.phase === "base" || week.phase === "build" || week.phase === "peak") {
    assert.ok(week.ramp <= defaultProfile().rampCap + 0.9, `${week.phase} week ${week.index + 1} ramp ${week.ramp.toFixed(2)}`);
  }
  const training = week.sessions.filter((s) => s.role !== "race");
  assert.ok(week.hours <= defaultProfile().weeklyHours + 0.15, `hours ${week.hours}`);
  assert.ok(training.length <= defaultProfile().sessionsPerWeek, `sessions ${training.length}`);
  for (const session of week.sessions) {
    if (session.role === "race") continue;
    assert.equal(session.date === "2027-02-21", false);
    assert.ok(session.intervals.length > 0, session.name);
    const sec = session.intervals.reduce((total, iv) => total + iv.sec, 0);
    assert.ok(Math.abs(sec / 60 - session.minutes) < 0.2, session.name);
  }
}

const race = plan.sessions.find((s) => s.role === "race");
assert.ok(race && race.date === "2027-02-21");
assert.ok(plan.sessions.some((s) => s.sport === "swim"));
assert.ok(plan.sessions.some((s) => s.sport === "bike"));
assert.ok(plan.sessions.some((s) => s.sport === "run"));

const bike = plan.sessions.find((s) => s.sport === "bike" && s.role === "intensity");
assert.ok(bike.tss > 20 && bike.tss < 180, `bike tss ${bike.tss}`);
assert.ok(bike.intervals.some((iv) => iv.i0 >= 0.85), "intensity has a real work target");

console.log("\nWEEK  PHASE      HRS   TSS   CTL   ATL    TSB   RAMP");
for (const week of plan.weeks) {
  console.log(
    String(week.index + 1).padStart(2, " "),
    week.phase.padEnd(10, " "),
    week.hours.toFixed(1).padStart(5, " "),
    String(Math.round(week.trainingTSS)).padStart(5, " "),
    week.ctlEnd.toFixed(1).padStart(6, " "),
    week.atlEnd.toFixed(1).padStart(6, " "),
    week.tsbEnd.toFixed(1).padStart(6, " "),
    week.ramp.toFixed(1).padStart(6, " "),
  );
}
console.log("\n" + plan.narrative);
console.log(`race morning CTL ${plan.raceMorning.ctl.toFixed(1)} ATL ${plan.raceMorning.atl.toFixed(1)} TSB ${plan.raceMorning.tsb.toFixed(1)}`);

// Adaptation: skip, illness, availability.
const skip = plan.sessions.find((s) => s.role === "intensity" && s.weekIndex >= 4 && s.weekIndex <= 8);
const adaptations = {
  sessionEdits: { [skip.id]: { mode: "skip" } },
  illnesses: [{ id: "ill", from: "2026-12-14", days: 7 }],
  availability: [{ id: "av", from: "2027-01-11", weeklyHours: 6, sessionsPerWeek: 5 }],
};
const adaptedStudio = buildStudio(defaultProfile(), adaptations);
assert.equal(adaptedStudio.ok, true);
const adapted = adaptedStudio.adapted;
const skipped = adapted.sessions.find((s) => s.id === skip.id);
assert.equal(skipped.status, "skipped");
assert.equal(skipped.tss, 0);
const before = plan.sessions.filter((s) => s.date < skip.date && s.date < "2026-12-14");
for (const session of before) {
  const twin = adapted.sessions.find((s) => s.id === session.id);
  assert.ok(twin, session.id);
  approx(twin.tss, session.tss, 0.1, `frozen ${session.id}`);
}
for (const date of adapted.dates) {
  if (date >= "2026-12-14" && date <= "2026-12-20") {
    const tss = adapted.sessions.filter((s) => s.date === date && s.role !== "race").reduce((total, s) => total + s.tss, 0);
    assert.equal(tss, 0, date);
  }
}
for (const week of adapted.weeks) {
  if (week.start >= "2027-01-11" && week.phase !== "taper") {
    assert.ok(week.hours <= 6.3, `availability hours ${week.hours} ${week.start}`);
    const n = week.sessions.filter((s) => s.role !== "race" && s.status !== "dropped" && s.status !== "illness" && s.status !== "skipped").length;
    assert.ok(n <= 5, `availability sessions ${n}`);
  }
  if (week.phase === "base" || week.phase === "build" || week.phase === "peak") {
    assert.ok(week.ramp <= 8.5, `adapted ramp ${week.ramp}`);
  }
}
assert.ok(adapted.raceMorning.tsb > 0, `adapted race TSB ${adapted.raceMorning.tsb}`);

const running = buildStudio({ ...defaultProfile(), discipline: "running", eventId: "marathon", sessionsPerWeek: 6 }, emptyAdaptations());
assert.equal(running.ok, true);
assert.ok(running.original.sessions.every((s) => s.sport === "run" || s.sport === "race"));
assert.ok(running.original.raceMorning.tsb > 0);

const cycling = buildStudio({ ...defaultProfile(), discipline: "cycling", eventId: "fondo" }, emptyAdaptations());
assert.equal(cycling.ok, true);
assert.ok(cycling.original.sessions.every((s) => s.sport === "bike" || s.sport === "race"));

const cross = buildStudio({ ...defaultProfile(), discipline: "cross", eventId: "foundation", sessionsPerWeek: 7 }, emptyAdaptations());
assert.equal(cross.ok, true);
assert.ok(cross.original.sessions.some((s) => s.sport === "strength"));
assert.ok(cross.original.sessions.some((s) => s.sport === "bike"));
assert.ok(cross.original.sessions.some((s) => s.sport === "run"));

const sample = plan.sessions.find((s) => s.sport === "bike" && s.intervals.length > 4);
const zwo = workoutToZwo(sample, studio.profile, studio.phys);
assert.match(zwo, /<workout_file>/);
assert.match(zwo, /<workout>/);
const ics = sessionsToIcs(plan.sessions.filter((s) => s.tss > 0).slice(0, 3), studio.profile);
assert.match(ics, /BEGIN:VCALENDAR/);
assert.equal((ics.match(/BEGIN:VEVENT/g) || []).length, 3);

console.log("\nAll model tests passed.");
