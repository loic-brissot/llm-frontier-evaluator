/**
 * Periodized plan, Banister load, and adaptation.
 * Weekly hours and session counts are ceilings. The ramp cap is a ceiling too:
 * a week uses less of the athlete's availability when using all of it would
 * spike chronic load.
 */

import { EVENTS, RACE_DISTANCES, eventById } from "./catalog.js";
import {
  addDaysISO,
  clamp,
  diffDays,
  eachDate,
  formatDay,
  parseClock,
  signed,
  weekdayMon,
} from "./format.js";
import {
  cssFromTest,
  cueForInterval,
  formLabel,
  hrCue,
  hrZones,
  powerZones,
  runningPaces,
  simulateLoads,
  stressOf,
  swimZones,
  vdotFromRace,
  wkgBand,
} from "./physio.js";
import { buildWorkout } from "./workouts.js";

const PHASE_NAME = {
  base: "Base",
  build: "Build",
  peak: "Peak",
  taper: "Taper",
  recovery: "Recovery",
};

function volumeFraction(phase, pos, count, fromEnd) {
  if (phase === "recovery") return 0.58;
  if (phase === "taper") {
    if (fromEnd <= 0) return 0.46;
    if (fromEnd === 1) return 0.66;
    return 0.8;
  }
  if (phase === "peak") return 0.95;
  if (phase === "build") return 1;
  const t = count <= 1 ? 1 : pos / Math.max(1, count - 1);
  return 0.86 + 0.12 * t;
}

function desiredRamp(phase, rampCap, pos) {
  if (phase === "recovery") return -Math.max(2.2, rampCap * 0.45);
  if (phase === "taper") return -2.5;
  if (phase === "peak") return Math.min(rampCap, 1.5);
  if (phase === "build") return Math.max(2, rampCap - 0.55);
  return Math.min(rampCap, 2.2 + pos * 0.45);
}

function naturalRate(phase) {
  return { base: 47, build: 56, peak: 57, recovery: 40, taper: 50 }[phase] || 48;
}

function tssCeiling(phase) {
  return { base: 56, build: 70, peak: 72, recovery: 46, taper: 62 }[phase] || 60;
}

export function sanitizeProfile(input) {
  const p = { ...input };
  p.name = String(p.name || "Athlete").slice(0, 48);
  if (!EVENTS[p.discipline]) p.discipline = "triathlon";
  const event = eventById(p.discipline, p.eventId);
  p.eventId = event.id;
  p.weightKg = clamp(Number(p.weightKg) || 70, 40, 160);
  p.ftpW = clamp(Number(p.ftpW) || 200, 60, 550);
  p.lthr = clamp(Math.round(Number(p.lthr) || 160), 110, 210);
  p.vo2max = clamp(Number(p.vo2max) || 45, 20, 90);
  p.weeklyHours = clamp(Number(p.weeklyHours) || 8, 3, 25);
  p.sessionsPerWeek = clamp(Math.round(Number(p.sessionsPerWeek) || 6), 3, 12);
  p.rampCap = clamp(Number(p.rampCap) || 5, 2, 8);
  if (p.runMode !== "vo2") p.runMode = "race";
  if (p.swimMode !== "test") p.swimMode = "pace";
  if (!RACE_DISTANCES.some((d) => d.id === p.raceDistanceId)) p.raceDistanceId = "10k";
  p.raceTime = String(p.raceTime || "45:00");
  p.cssPace = String(p.cssPace || "1:45");
  p.t200 = String(p.t200 || "3:20");
  p.t400 = String(p.t400 || "7:00");
  p.start = String(p.start || "");
  p.race = String(p.race || "");
  return p;
}

export function derivePhysiology(profile) {
  const ftp = profile.ftpW;
  const wkg = ftp / profile.weightKg;
  let vdot = null;
  let vdotSource = "";
  if (profile.runMode === "vo2") {
    vdot = profile.vo2max;
    vdotSource = "Entered VO₂max, used as VDOT";
  } else {
    const dist = RACE_DISTANCES.find((d) => d.id === profile.raceDistanceId);
    const sec = parseClock(profile.raceTime);
    if (dist && sec) {
      vdot = vdotFromRace(dist.meters, sec);
      vdotSource = `${dist.name} ${profile.raceTime}`;
    }
  }
  let cssMps = null;
  let cssSource = "";
  if (profile.swimMode === "test") {
    const t200 = parseClock(profile.t200);
    const t400 = parseClock(profile.t400);
    if (t200 && t400) {
      cssMps = cssFromTest(t200, t400);
      cssSource = `200 m ${profile.t200} · 400 m ${profile.t400}`;
    }
  } else {
    const sec = parseClock(profile.cssPace);
    if (sec > 0) {
      cssMps = 100 / sec;
      cssSource = `${profile.cssPace} /100m`;
    }
  }
  if (!(vdot > 15 && vdot < 95)) {
    return { ok: false, error: "Running input needs a plausible race time or VO₂max." };
  }
  if (!(cssMps > 0.45 && cssMps < 2.3)) {
    return { ok: false, error: "Swim CSS needs a plausible pace, or a 200 m and 400 m trial." };
  }
  const paces = runningPaces(vdot);
  return {
    ok: true,
    ftp,
    wkg,
    wkgBand: wkgBand(wkg),
    weightKg: profile.weightKg,
    vdot,
    vdotSource,
    paces,
    lthr: profile.lthr,
    hr: hrZones(profile.lthr),
    power: powerZones(ftp),
    cssMps,
    cssSec: 100 / cssMps,
    cssSource,
    swim: swimZones(cssMps),
  };
}

function assignPhases(n, event) {
  if (n <= 1) return ["taper"];
  if (n === 2) return ["build", "taper"];
  if (n === 3) return ["build", "peak", "taper"];
  let taper = event.taperWeeks;
  let peak = event.peakWeeks;
  while (taper + peak >= n - 1) {
    if (peak > 1) peak -= 1;
    else if (taper > 1) taper -= 1;
    else break;
  }
  const pre = Math.max(1, n - taper - peak);
  let build = 0;
  if (pre >= 8) build = Math.max(2, Math.round(pre * 0.36));
  else if (pre >= 5) build = Math.max(2, Math.round(pre * 0.4));
  else if (pre >= 3) build = 1;
  build = Math.min(build, pre - (pre > 2 ? 1 : 0));
  const base = pre - build;
  const phases = [];
  for (let i = 0; i < base; i++) phases.push("base");
  for (let i = 0; i < build; i++) phases.push("build");
  for (let i = 0; i < peak; i++) phases.push("peak");
  for (let i = 0; i < taper; i++) phases.push("taper");
  while (phases.length < n) phases.unshift("base");
  let load = 0;
  for (let i = 0; i < pre && i < phases.length; i++) {
    if (phases[i] === "peak" || phases[i] === "taper") break;
    load += 1;
    if (load % 4 === 0) {
      if (i < pre - 1) phases[i] = "recovery";
      else if (i > 0 && phases[i - 1] !== "recovery") phases[i - 1] = "recovery";
    }
  }
  return phases.slice(0, n);
}

function buildSkeleton(profile, event) {
  const dates = eachDate(profile.start, profile.race);
  const weeks = [];
  let cursor = 0;
  while (cursor < dates.length) {
    const start = dates[cursor];
    const startDay = weekdayMon(start);
    let endIdx = cursor;
    while (endIdx + 1 < dates.length && weekdayMon(dates[endIdx + 1]) !== 0) endIdx += 1;
    // A plan that starts mid-week stays one week until Sunday; the next week starts Monday.
    if (cursor === 0 && startDay !== 0) {
      while (endIdx + 1 < dates.length && weekdayMon(dates[endIdx]) !== 6) endIdx += 1;
    }
    const slice = dates.slice(cursor, endIdx + 1);
    weeks.push({ dates: slice, start: slice[0], end: slice[slice.length - 1] });
    cursor = endIdx + 1;
  }
  const phases = assignPhases(weeks.length, event);
  const taperIndexes = weeks.map((_, i) => i).filter((i) => phases[i] === "taper");
  return weeks.map((week, index) => {
    const phase = phases[index];
    const same = phases.map((p, i) => (p === phase ? i : -1)).filter((i) => i >= 0);
    const pos = Math.max(0, same.indexOf(index));
    const fromEnd = phase === "taper" ? taperIndexes[taperIndexes.length - 1] - index : 0;
    return {
      index,
      ...week,
      phase,
      phaseName: PHASE_NAME[phase],
      phasePos: pos,
      phaseCount: same.length,
      taperFromEnd: fromEnd,
      trainingDates: week.dates.filter((d) => d !== profile.race),
      notes: [],
      minuteCap: 0,
    };
  });
}

function minMinutes(item) {
  if (item.role === "shakeout") return 20;
  if (item.role === "opener") return 25;
  if (item.role === "strength") return 36;
  if (item.sport === "swim" || item.role === "recovery") return 30;
  if (item.sport === "run") return 30;
  return 40;
}

function maxMinutes(item, event) {
  if (item.role === "strength") return 48;
  if (item.role === "opener" || item.role === "shakeout") return 42;
  if (item.role === "recovery") return 50;
  if (item.sport === "swim") return item.role === "intensity" || item.role === "opener" ? 50 : 72;
  if (item.sport === "run" && item.role === "long") return event.longRunMin || 120;
  if (item.sport === "bike" && item.role === "long") return event.longBikeMin || 180;
  if (item.sport === "run") return 80;
  if (item.sport === "brick") return 140;
  if (item.sport === "bike") return item.role === "intensity" || item.role === "intensity2" ? 110 : 140;
  return 90;
}

const WEIGHT = {
  long: 1.8,
  brick: 1.45,
  intensity: 1.05,
  intensity2: 1,
  endurance: 0.92,
  strength: 0.55,
  recovery: 0.5,
  opener: 0.48,
  shakeout: 0.38,
};

function allocateMinutes(items, budgetMin, event) {
  if (!items.length) return [];
  const caps = items.map((item) => maxMinutes(item, event));
  const mins = items.map((item) => minMinutes(item));
  let used = mins.reduce((s, n) => s + n, 0);
  if (used > budgetMin) {
    const f = budgetMin / used;
    return mins.map((n) => Math.max(18, Math.round(n * f)));
  }
  let leftover = budgetMin - used;
  let guard = 0;
  while (leftover > 1 && guard++ < 8) {
    const room = mins.map((n, i) => Math.max(0, caps[i] - n));
    const weights = items.map((item, i) => (room[i] > 0.5 ? WEIGHT[item.role] || 1 : 0));
    const wsum = weights.reduce((s, w) => s + w, 0);
    if (wsum <= 0) break;
    let consumed = 0;
    for (let i = 0; i < items.length; i++) {
      if (weights[i] <= 0) continue;
      const add = Math.min(room[i], (leftover * weights[i]) / wsum);
      mins[i] += add;
      consumed += add;
    }
    leftover -= consumed;
    if (consumed < 0.5) break;
  }
  const rounded = mins.map((n, i) => Math.min(caps[i], Math.max(minMinutes(items[i]), Math.round(n))));
  return rounded;
}

function hardRole(role) {
  return role === "intensity" || role === "intensity2" || role === "long" || role === "brick" || role === "opener";
}

function canShare(existing, item) {
  if (existing.length >= 2) return false;
  if (existing.some((row) => hardRole(row.role) && hardRole(item.role))) return false;
  return true;
}

function prefScore(item, day) {
  const byRole = {
    long: [5, 6, 4, 3, 2, 1, 0],
    intensity: [1, 3, 2, 4, 5, 0, 6],
    intensity2: [3, 1, 4, 2, 0, 5, 6],
    strength: [0, 4, 2, 5, 3, 1, 6],
    opener: [2, 1, 3, 4, 0, 5, 6],
    shakeout: [5, 4, 3, 2, 1, 0, 6],
    brick: [5, 4, 6, 3, 2, 1, 0],
    recovery: [0, 6, 4, 2, 3, 1, 5],
  };
  const bySport = { swim: [0, 2, 4, 1, 3, 5, 6], run: [4, 6, 2, 3, 0, 1, 5], bike: [1, 5, 3, 2, 4, 6, 0] };
  const list = byRole[item.role] || bySport[item.sport] || [2, 4, 1, 3, 0, 5, 6];
  const idx = list.indexOf(day);
  return idx < 0 ? 5 : idx;
}

function placeItems(items, dates, raceDate) {
  const occ = new Map(dates.map((date) => [date, []]));
  const rank = { long: 0, brick: 1, intensity: 2, intensity2: 3, strength: 4, opener: 5, shakeout: 6, endurance: 7, recovery: 8 };
  const ordered = [...items].sort((a, b) => (rank[a.role] ?? 9) - (rank[b.role] ?? 9));
  for (const item of ordered) {
    const scored = dates
      .map((date) => {
        const existing = occ.get(date);
        let score = prefScore(item, weekdayMon(date));
        if (existing.length) score += canShare(existing, item) ? 18 : 1000;
        if (raceDate && hardRole(item.role) && date === addDaysISO(raceDate, -1)) score += 70;
        if (item.role === "shakeout" && date === dates[dates.length - 1]) score -= 12;
        return { date, score };
      })
      .sort((a, b) => a.score - b.score);
    const date = scored[0].date;
    occ.get(date).push(item);
    item.date = date;
  }
  return ordered;
}

function fitCount(items, count, discipline, phase) {
  const list = items.map((item) => ({ ...item }));
  const padSport = () => {
    if (discipline === "running") return "run";
    if (discipline === "cycling") return "bike";
    if (discipline === "cross") {
      if (!list.some((item) => item.sport === "strength")) return "strength";
      const bikes = list.filter((item) => item.sport === "bike").length;
      const runs = list.filter((item) => item.sport === "run").length;
      return bikes <= runs ? "bike" : "run";
    }
    const tally = { swim: 0, bike: 0, run: 0 };
    for (const item of list) if (tally[item.sport] != null) tally[item.sport] += 1;
    return Object.entries(tally).sort((a, b) => a[1] - b[1])[0][0];
  };
  while (list.length < count) {
    const sport = padSport();
    list.push({ sport, role: sport === "strength" ? "strength" : "endurance" });
  }
  const dropRank = (item) => {
    if (phase === "taper" || phase === "recovery") {
      return { intensity: 0, intensity2: 0, long: 1, brick: 1, endurance: 3, recovery: 4, strength: 5, opener: 8, shakeout: 9 }[item.role] ?? 3;
    }
    return { recovery: 0, endurance: 1, shakeout: 1, intensity2: 2, brick: 3, opener: 4, strength: 5, long: 7, intensity: 8 }[item.role] ?? 3;
  };
  while (list.length > count) {
    let idx = -1;
    let best = Infinity;
    for (let i = 0; i < list.length; i++) {
      const role = list[i].role;
      const n = list.filter((item) => item.role === role).length;
      if ((role === "long" || role === "intensity") && n <= 1 && phase !== "taper" && phase !== "recovery") continue;
      if (role === "strength" && n <= 1 && discipline === "cross" && phase !== "taper") continue;
      if (role === "shakeout" && phase === "taper" && n <= 1) continue;
      const rank = dropRank(list[i]);
      if (rank < best) {
        best = rank;
        idx = i;
      }
    }
    if (idx < 0) list.splice(list.length - 1, 1);
    else list.splice(idx, 1);
  }
  return list;
}

function preferredItems(discipline, phase, weekIndex) {
  if (discipline === "cycling") {
    if (phase === "taper") {
      return [
        { sport: "bike", role: "opener" },
        { sport: "bike", role: "endurance" },
        { sport: "bike", role: "endurance" },
        { sport: "bike", role: "shakeout" },
        { sport: "bike", role: "recovery" },
      ];
    }
    if (phase === "recovery") {
      return [
        { sport: "bike", role: "long" },
        { sport: "bike", role: "endurance" },
        { sport: "bike", role: "endurance" },
        { sport: "bike", role: "recovery" },
        { sport: "bike", role: "opener" },
      ];
    }
    const items = [
      { sport: "bike", role: "long" },
      { sport: "bike", role: "intensity" },
      { sport: "bike", role: "endurance", touches: "spinups" },
      { sport: "bike", role: "endurance" },
      { sport: "bike", role: "recovery" },
      { sport: "bike", role: "endurance" },
    ];
    if (phase === "build" || phase === "peak") items.splice(2, 0, { sport: "bike", role: "intensity2" });
    return items;
  }
  if (discipline === "running") {
    if (phase === "taper") {
      return [
        { sport: "run", role: "opener" },
        { sport: "run", role: "endurance" },
        { sport: "run", role: "shakeout" },
        { sport: "run", role: "endurance" },
        { sport: "run", role: "recovery" },
      ];
    }
    if (phase === "recovery") {
      return [
        { sport: "run", role: "long" },
        { sport: "run", role: "endurance", touches: "strides" },
        { sport: "run", role: "endurance" },
        { sport: "run", role: "recovery" },
      ];
    }
    const items = [
      { sport: "run", role: "long" },
      { sport: "run", role: "intensity" },
      { sport: "run", role: "endurance", touches: "strides" },
      { sport: "run", role: "endurance" },
      { sport: "run", role: "recovery" },
      { sport: "run", role: "endurance" },
    ];
    if (phase === "build" || phase === "peak") items.splice(2, 0, { sport: "run", role: "intensity2" });
    return items;
  }
  if (discipline === "cross") {
    if (phase === "taper") {
      return [
        { sport: "bike", role: "opener" },
        { sport: "run", role: "shakeout" },
        { sport: "strength", role: "strength" },
        { sport: "bike", role: "endurance" },
        { sport: "run", role: "endurance" },
      ];
    }
    if (phase === "recovery") {
      return [
        { sport: "bike", role: "endurance" },
        { sport: "run", role: "endurance", touches: "strides" },
        { sport: "strength", role: "strength" },
        { sport: "bike", role: "recovery" },
        { sport: "run", role: "endurance" },
      ];
    }
    const items = [
      { sport: "bike", role: "long" },
      { sport: "run", role: "long" },
      { sport: "strength", role: "strength" },
      { sport: "bike", role: "intensity" },
      { sport: "run", role: phase === "base" ? "endurance" : "intensity", touches: phase === "base" ? "strides" : undefined },
      { sport: "bike", role: "endurance" },
      { sport: "run", role: "endurance" },
      { sport: "strength", role: "strength" },
    ];
    return items;
  }
  if (phase === "taper") {
    return [
      { sport: "swim", role: "opener" },
      { sport: "bike", role: "opener" },
      { sport: "run", role: "shakeout" },
      { sport: "swim", role: "endurance" },
      { sport: "bike", role: "endurance" },
      { sport: "run", role: "endurance" },
    ];
  }
  if (phase === "recovery") {
    return [
      { sport: "swim", role: "endurance" },
      { sport: "bike", role: "endurance" },
      { sport: "run", role: "endurance", touches: "strides" },
      { sport: "swim", role: "endurance" },
      { sport: "bike", role: "recovery" },
      { sport: "run", role: "endurance" },
    ];
  }
  const items = [
    { sport: "swim", role: "endurance" },
    { sport: "bike", role: "long" },
    { sport: "run", role: "long" },
    { sport: "bike", role: "intensity" },
    { sport: "run", role: "endurance", touches: "strides" },
    { sport: "bike", role: "endurance" },
    { sport: "swim", role: phase === "base" ? "endurance" : "intensity" },
    { sport: "run", role: phase === "base" ? "endurance" : "intensity" },
  ];
  if (phase === "peak" || (phase === "build" && weekIndex % 2 === 1)) items.push({ sport: "brick", role: "brick" });
  return items;
}

function materialize(spec, phys, event, profile) {
  const built = buildWorkout(spec, phys, event);
  const stress = stressOf(built.intervals);
  const minutes = stress.seconds / 60;
  return {
    id: spec.id,
    date: spec.date,
    sport: spec.sport,
    role: spec.role,
    phase: spec.phase,
    weekIndex: spec.weekIndex,
    name: built.title,
    note: built.note,
    kind: built.kind,
    minutes,
    tss: stress.tss,
    iff: stress.iff,
    intervals: built.intervals,
    status: spec.role === "race" ? "race" : "planned",
    rebalanced: null,
    spec,
    plannedMinutes: minutes,
    plannedTSS: stress.tss,
    plannedName: built.title,
  };
}

function rematerialize(session, minutes, phys, event, profile, specPatch = {}) {
  const spec = { ...session.spec, ...specPatch, minutes: Math.max(15, Math.round(minutes)) };
  const next = materialize(spec, phys, event, profile);
  next.id = session.id;
  next.plannedMinutes = session.plannedMinutes;
  next.plannedTSS = session.plannedTSS;
  next.plannedName = session.plannedName;
  next.rebalanced = session.rebalanced;
  next.status = "planned";
  return next;
}

function sumBy(list, fn) {
  return list.reduce((total, item) => total + fn(item), 0);
}

function alignWeek(sessions, targetTSS, minuteCap, phys, event, profile) {
  const scalable = (s) => ["endurance", "long", "recovery", "brick"].includes(s.role) && s.status === "planned";
  let current = sessions;
  for (let pass = 0; pass < 4; pass++) {
    const tss = sumBy(current, (s) => s.tss);
    const minutes = sumBy(current, (s) => s.minutes);
    const diff = tss - targetTSS;
    if (Math.abs(diff) < Math.max(8, targetTSS * 0.02)) break;
    if (diff > 0) {
      const pool = current.filter(scalable);
      const poolTSS = sumBy(pool, (s) => s.tss);
      if (poolTSS < 8) break;
      const cut = Math.min(diff, poolTSS * 0.4);
      current = current.map((s) => {
        if (!scalable(s)) return s;
        const share = s.tss / poolTSS;
        const nextMin = Math.max(minMinutes(s), s.minutes * (1 - (cut * share) / Math.max(s.tss, 1)));
        if (s.minutes - nextMin < 3) return s;
        const next = rematerialize(s, nextMin, phys, event, profile);
        next.rebalanced = "cut";
        return next;
      });
    } else {
      if (minutes >= minuteCap - 6) break;
      const room = minuteCap - minutes;
      const pool = current.filter((s) => scalable(s) && s.minutes < maxMinutes(s, event) - 4);
      if (!pool.length || room < 8) break;
      const poolMin = sumBy(pool, (s) => s.minutes) || 1;
      current = current.map((s) => {
        if (!pool.includes(s)) return s;
        const add = Math.min(maxMinutes(s, event) - s.minutes, room * (s.minutes / poolMin));
        if (add < 4) return s;
        const next = rematerialize(s, s.minutes + add, phys, event, profile);
        next.rebalanced = "extended";
        return next;
      });
    }
  }
  let guard = 0;
  while (sumBy(current, (s) => (s.role === "race" ? 0 : s.minutes)) > minuteCap + 8 && guard++ < 4) {
    const training = current.filter((s) => s.role !== "race");
    const over = sumBy(training, (s) => s.minutes) - minuteCap;
    const pool = current.filter((s) => scalable(s) || s.role === "intensity" || s.role === "intensity2" || s.role === "opener");
    const poolMin = sumBy(pool, (s) => s.minutes) || 1;
    if (!pool.length || over <= 0) break;
    current = current.map((s) => {
      if (!pool.includes(s)) return s;
      const nextMin = Math.max(minMinutes(s) * 0.85, s.minutes - over * (s.minutes / poolMin));
      if (s.minutes - nextMin < 2) return s;
      const next = rematerialize(s, nextMin, phys, event, profile);
      next.rebalanced = "cut";
      return next;
    });
  }
  return current;
}

function weekBudget(week, hoursAvail, rampCap, ctl) {
  const trainDays = Math.max(1, week.trainingDates.length);
  const span = week.dates.length / 7;
  const frac = volumeFraction(week.phase, week.phasePos, week.phaseCount, week.taperFromEnd);
  const hourCap = hoursAvail * frac * span;
  const ramp = desiredRamp(week.phase, rampCap, week.phasePos);
  let target = trainDays * (ctl + 6 * ramp);
  const maxTSS = Math.max(0, hourCap * tssCeiling(week.phase));
  target = Math.min(Math.max(target, trainDays * 12), maxTSS);
  const hours = Math.min(hourCap, target / naturalRate(week.phase));
  return { hours: Math.max(0, hours), hourCap, targetTSS: Math.max(0, target), ramp };
}

function makeSessions(items, week, profile, phys, event, seqStart = 0) {
  const counters = {};
  return items.map((item) => {
    const key = `${item.date}:${item.sport}:${item.role}`;
    counters[key] = (counters[key] || 0) + 1;
    const spec = {
      id: `${item.date}:${item.sport}:${item.role}:${counters[key]}`,
      date: item.date,
      sport: item.sport,
      role: item.role,
      minutes: item.minutes,
      phase: week.phase,
      weekIndex: week.index,
      touches: item.touches || null,
      intensityBias: 0,
      discipline: profile.discipline,
    };
    return materialize(spec, phys, event, profile);
  });
}

function prescribeWeek(week, ctl, profile, phys, event, hoursAvail, sessionsAvail, rampCap) {
  const notes = [];
  const budget = weekBudget(week, hoursAvail, rampCap, ctl);
  week.minuteCap = budget.hours * 60;
  week.targetTSS = budget.targetTSS;
  const trainDays = week.trainingDates;
  let count = trainDays.length ? Math.max(1, Math.round(sessionsAvail * (week.dates.length / 7))) : 0;
  count = Math.min(count, trainDays.length * 2);
  const byTime = Math.max(1, Math.floor((budget.hours * 60) / 30));
  if (count > byTime) {
    notes.push(`Session count is ${byTime} rather than ${count}: the hours would otherwise split into scraps.`);
    count = byTime;
  }
  if (!trainDays.length) count = 0;
  const items = count ? fitCount(preferredItems(profile.discipline, week.phase, week.index), count, profile.discipline, week.phase) : [];
  const minutes = allocateMinutes(items, Math.max(0, budget.hours * 60), event);
  items.forEach((item, i) => {
    item.minutes = minutes[i];
  });
  const placed = trainDays.length ? placeItems(items, trainDays, profile.race) : [];
  let sessions = makeSessions(placed, week, profile, phys, event);
  if (week.dates.includes(profile.race)) {
    const spec = {
      id: `${profile.race}:race:race:1`,
      date: profile.race,
      sport: "race",
      role: "race",
      minutes: event.raceMin,
      phase: "taper",
      weekIndex: week.index,
      intensityBias: 0,
      discipline: profile.discipline,
    };
    sessions.push(materialize(spec, phys, event, profile));
  }
  const training = sessions.filter((s) => s.role !== "race");
  const aligned = alignWeek(training, budget.targetTSS, budget.hours * 60, phys, event, profile);
  sessions = [...aligned, ...sessions.filter((s) => s.role === "race")];
  const usedH = sumBy(sessions.filter((s) => s.role !== "race"), (s) => s.minutes) / 60;
  if (budget.hourCap - usedH > 0.8 && week.phase !== "taper") {
    notes.push(`Availability is ${hoursAvail.toFixed(1)} h. This week uses ${usedH.toFixed(1)} h so the ramp stays inside +${rampCap} CTL.`);
  }
  week.notes.push(...notes);
  return sessions;
}

function generate(profile, phys, event, skeleton) {
  const start = startingLoad(profile.weeklyHours);
  let ctl = start.ctl;
  let atl = start.atl;
  const sessions = [];
  for (const week of skeleton) {
    const built = prescribeWeek(week, ctl, profile, phys, event, profile.weeklyHours, profile.sessionsPerWeek, profile.rampCap);
    sessions.push(...built);
    for (const date of week.dates) {
      const tss = built.filter((s) => s.date === date).reduce((total, s) => total + s.tss, 0);
      ctl = ctl + (tss - ctl) / 42;
      atl = atl + (tss - atl) / 7;
    }
  }
  return { sessions, start };
}

function stampPlanned(sessions) {
  for (const session of sessions) {
    session.plannedMinutes = session.minutes;
    session.plannedTSS = session.tss;
    session.plannedName = session.name;
    session.spec = { ...session.spec, minutes: Math.max(15, Math.round(session.minutes) || session.spec.minutes) };
    session.rebalanced = null;
  }
}

function raceMorningFrom(sessions, dates, race, start) {
  const daily = dates.map((date) => sumBy(sessions.filter((s) => s.date === date), (s) => s.tss));
  const series = simulateLoads(daily, start.ctl, start.atl);
  const idx = dates.indexOf(race);
  if (idx <= 0) return { ctl: start.ctl, atl: start.atl, tsb: start.ctl - start.atl };
  return series[idx - 1];
}

function ctlAtTaper(sessions, dates, skeleton, race, start) {
  const taper = skeleton.find((week) => week.phase === "taper");
  if (!taper) return raceMorningFrom(sessions, dates, race, start).ctl;
  const prev = addDaysISO(taper.start, -1);
  if (prev < dates[0]) return start.ctl;
  const daily = dates.map((date) => sumBy(sessions.filter((s) => s.date === date), (s) => s.tss));
  const series = simulateLoads(daily, start.ctl, start.atl);
  const idx = dates.indexOf(prev);
  return idx >= 0 ? series[idx].ctl : start.ctl;
}

function tuneTaper(sessions, skeleton, profile, phys, event, start) {
  const dates = skeleton.flatMap((week) => week.dates);
  const taperWeeks = skeleton.filter((week) => week.phase === "taper");
  const tunable = sessions.filter((s) => s.phase === "taper" && s.role !== "race" && s.status !== "illness" && s.status !== "skipped");
  if (!tunable.length) return sessions;
  const bases = new Map(tunable.map((s) => [s.id, s.minutes]));
  let best = null;
  let bestScore = -Infinity;
  for (let scale = 0.4; scale <= 1.2; scale += 0.05) {
    const trial = sessions.map((session) => {
      if (!bases.has(session.id)) return session;
      const cap = maxMinutes(session, event);
      const minutes = clamp(bases.get(session.id) * scale, minMinutes(session) * 0.8, cap);
      return rematerialize(session, minutes, phys, event, profile);
    });
    const morning = raceMorningFrom(trial, dates, profile.race, start);
    const entry = ctlAtTaper(trial, dates, skeleton, profile.race, start);
    const ctlLoss = entry - morning.ctl;
    let score = 0;
    score -= Math.abs(morning.tsb - 17) * 2.2;
    if (morning.tsb >= 12 && morning.tsb <= 24) score += 14;
    if (morning.tsb < 8) score -= 36;
    if (morning.tsb > 30) score -= 28;
    score -= Math.max(0, ctlLoss - 12) * 1.4;
    score -= Math.max(0, 1.5 - ctlLoss) * 2;
    let overHours = 0;
    for (const week of taperWeeks) {
      const minutes = sumBy(
        trial.filter((s) => week.dates.includes(s.date) && s.role !== "race"),
        (s) => s.minutes,
      );
      if (week.minuteCap && minutes > week.minuteCap + 12) overHours += minutes - week.minuteCap;
    }
    score -= overHours * 0.15;
    if (score > bestScore) {
      bestScore = score;
      best = trial;
    }
  }
  if (!best) return sessions;
  for (let i = 0; i < sessions.length; i++) {
    if (bases.has(sessions[i].id)) {
      best[i].rebalanced = Math.abs(best[i].minutes - bases.get(sessions[i].id)) > 4 ? "retuned" : sessions[i].rebalanced;
      sessions[i] = best[i];
    }
  }
  return sessions;
}

function sortSessions(a, b) {
  if (a.date !== b.date) return a.date < b.date ? -1 : 1;
  const order = { swim: 0, strength: 1, bike: 2, brick: 3, run: 4, race: 5 };
  return (order[a.sport] ?? 9) - (order[b.sport] ?? 9);
}

function finalize(profile, phys, event, skeleton, sessions, start) {
  const dates = skeleton.flatMap((week) => week.dates);
  const phaseByDate = new Map();
  for (const week of skeleton) for (const date of week.dates) phaseByDate.set(date, week.phase);
  const dailyTSS = dates.map((date) => sumBy(sessions.filter((s) => s.date === date), (s) => s.tss));
  const series = simulateLoads(dailyTSS, start.ctl, start.atl);
  const pmc = series.map((row, i) => ({ ...row, date: dates[i], phase: phaseByDate.get(dates[i]) }));
  const weeks = skeleton.map((week) => {
    const ws = sessions.filter((s) => week.dates.includes(s.date)).sort(sortSessions);
    const end = pmc[dates.indexOf(week.end)];
    const prev = addDaysISO(week.start, -1);
    const prevRow = pmc.find((row) => row.date === prev);
    const ctlStart = prevRow ? prevRow.ctl : start.ctl;
    let ctlForRamp = end.ctl;
    if (week.dates.includes(profile.race) && dates.indexOf(profile.race) > 0) {
      ctlForRamp = pmc[dates.indexOf(profile.race) - 1].ctl;
    }
    const training = ws.filter((s) => s.role !== "race");
    const minutes = sumBy(training, (s) => s.minutes);
    return {
      ...week,
      sessions: ws,
      minutes,
      hours: minutes / 60,
      tss: sumBy(ws, (s) => s.tss),
      trainingTSS: sumBy(training, (s) => s.tss),
      ctlStart,
      ctlEnd: end.ctl,
      atlEnd: end.atl,
      tsbEnd: end.tsb,
      ramp: ctlForRamp - ctlStart,
    };
  });
  const raceIdx = dates.indexOf(profile.race);
  const raceMorning = raceIdx > 0 ? { ...pmc[raceIdx - 1] } : { ctl: start.ctl, atl: start.atl, tsb: start.ctl - start.atl, date: profile.race, tss: 0, phase: "taper" };
  let peakCtl = -Infinity;
  let peakCtlDate = dates[0];
  let minTsb = Infinity;
  let maxRamp = 0;
  for (const row of pmc) {
    if (row.date < profile.race && row.ctl >= peakCtl) {
      peakCtl = row.ctl;
      peakCtlDate = row.date;
    }
    if (row.date < profile.race && row.tsb < minTsb) minTsb = row.tsb;
  }
  for (const week of weeks) {
    if (week.phase !== "taper" && week.ramp > maxRamp) maxRamp = week.ramp;
  }
  const form = formLabel(raceMorning.tsb);
  const steep = weeks.reduce((best, week) => (week.ramp > best.ramp ? week : best), weeks[0]);
  const narrative = [
    `Chronic load starts near ${start.ctl.toFixed(0)}, estimated from ${Math.round(profile.weeklyHours * 0.62 * 10) / 10} h of recent aerobic training rather than from zero.`,
    `It reaches ${peakCtl.toFixed(0)} on ${formatDay(peakCtlDate)}.`,
    `${event.goal} morning is TSB ${signed(raceMorning.tsb, 0)} — ${form.name.toLowerCase()} — with CTL ${raceMorning.ctl.toFixed(0)} and ATL ${raceMorning.atl.toFixed(0)}.`,
    steep
      ? `The steepest weekly ramp is ${signed(steep.ramp, 1)} CTL in ${steep.phaseName.toLowerCase()} week ${steep.index + 1}, ${steep.ramp <= profile.rampCap + 0.2 ? "inside" : "pressing"} the +${profile.rampCap} cap.`
      : "",
    form.note,
  ].filter(Boolean).join(" ");
  return {
    profile,
    phys,
    event,
    dates,
    weeks,
    sessions: weeks.flatMap((week) => week.sessions),
    pmc,
    startLoad: start,
    raceMorning,
    stats: {
      peakCtl,
      peakCtlDate,
      minTsb,
      maxRamp,
      totalHours: sumBy(weeks, (week) => week.hours),
      totalTSS: sumBy(weeks, (week) => week.trainingTSS),
    },
    narrative,
  };
}

function availabilityOn(date, profile, rows) {
  let hours = profile.weeklyHours;
  let sessions = profile.sessionsPerWeek;
  const sorted = [...(rows || [])].sort((a, b) => String(a.from).localeCompare(String(b.from)));
  for (const row of sorted) {
    if (row.from && row.from <= date) {
      hours = clamp(Number(row.weeklyHours) || hours, 3, 25);
      sessions = clamp(Math.round(Number(row.sessionsPerWeek) || sessions), 3, 12);
    }
  }
  return { hours, sessions };
}

function illnessDateSet(illnesses, start, race) {
  const set = new Set();
  for (const ill of illnesses || []) {
    const days = clamp(Math.round(Number(ill.days) || 1), 1, 28);
    for (let i = 0; i < days; i++) {
      const date = addDaysISO(ill.from, i);
      if (date >= start && date <= race) set.add(date);
    }
  }
  return set;
}

function dampLevel(date, illnesses) {
  let level = 0;
  for (const ill of illnesses || []) {
    const days = clamp(Math.round(Number(ill.days) || 1), 1, 28);
    const end = addDaysISO(ill.from, days - 1);
    const after = diffDays(end, date);
    if (after >= 1 && after <= 4) level = Math.max(level, 2);
    else if (after >= 5 && after <= 11) level = Math.max(level, 1);
  }
  return level;
}

function firstTouch(adaptations, start, race) {
  const dates = [];
  for (const ill of adaptations.illnesses || []) if (ill.from) dates.push(ill.from);
  for (const row of adaptations.availability || []) if (row.from) dates.push(row.from);
  for (const id of Object.keys(adaptations.sessionEdits || {})) {
    const date = String(id).split(":")[0];
    if (date) dates.push(date);
  }
  const viable = dates.filter((date) => date >= start && date <= race).sort();
  return viable[0] || null;
}

function applySkip(session) {
  return {
    ...session,
    status: "skipped",
    tss: 0,
    minutes: 0,
    iff: 0,
    intervals: [],
    name: "Skipped",
    note: "Marked skipped. Later aerobic work can absorb a little of the gap, and only inside the ramp cap. The intensity is not repaid.",
  };
}

function applyIllness(session) {
  return {
    ...session,
    status: "illness",
    tss: 0,
    minutes: 0,
    iff: 0,
    intervals: [],
    name: "Illness",
    note: "No training stress. The return is damped so fitness is rebuilt instead of forced.",
  };
}

function applyDrop(session, why) {
  return {
    ...session,
    status: "dropped",
    tss: 0,
    minutes: 0,
    iff: 0,
    intervals: [],
    name: "Rest",
    note: why,
    rebalanced: "dropped",
  };
}

function adapt(originalSessions, skeleton, profile, phys, event, start, adaptations) {
  const touch = firstTouch(adaptations, profile.start, profile.race);
  if (!touch) return originalSessions;
  let sessions = structuredClone(originalSessions);
  const locked = new Set();
  const edits = adaptations.sessionEdits || {};
  sessions = sessions.map((session) => {
    const edit = edits[session.id];
    if (!edit || session.role === "race") return session;
    locked.add(session.id);
    if (edit.mode === "skip") return applySkip(session);
    if (edit.mode === "shorten") {
      const next = rematerialize(session, Math.max(18, session.spec.minutes * 0.5), phys, event, profile);
      next.status = "shortened";
      next.note = "Shortened to about half. The targets stay; there is simply less of the work.";
      return next;
    }
    if (edit.mode === "overreach") {
      const next = rematerialize(session, session.spec.minutes * 1.22, phys, event, profile, { intensityBias: 0.04 });
      next.status = "overreached";
      next.note = "Logged as over-reached. The rest of the week eases so the ramp does not run away.";
      return next;
    }
    return session;
  });
  const ill = illnessDateSet(adaptations.illnesses, profile.start, profile.race);
  sessions = sessions.map((session) => {
    if (!ill.has(session.date) || session.role === "race") return session;
    locked.add(session.id);
    return applyIllness(session);
  });

  let ctl = start.ctl;
  let atl = start.atl;
  const dates = skeleton.flatMap((week) => week.dates);
  const rebuilt = [];
  for (const week of skeleton) {
    const weekSessions = sessions.filter((s) => week.dates.includes(s.date));
    const weekTouches = week.end >= touch;
    let nextWeek = weekSessions;
    if (weekTouches) {
      nextWeek = rebalanceWeek(week, weekSessions, {
        ctl, profile, phys, event, locked, touch, adaptations, ill,
      });
    }
    rebuilt.push(...nextWeek);
    for (const date of week.dates) {
      const tss = nextWeek.filter((s) => s.date === date).reduce((total, s) => total + s.tss, 0);
      ctl = ctl + (tss - ctl) / 42;
      atl = atl + (tss - atl) / 7;
    }
  }
  // Preserve any session the filter might have dropped (it should not).
  const seen = new Set(rebuilt.map((s) => s.id));
  for (const session of sessions) if (!seen.has(session.id) && dates.includes(session.date)) rebuilt.push(session);
  tuneTaper(rebuilt, skeleton, profile, phys, event, start);
  return rebuilt;
}

function rebalanceWeek(week, weekSessions, ctx) {
  const { ctl, profile, phys, event, locked, touch, adaptations, ill } = ctx;
  week.notes = [];
  const focus = week.dates.find((date) => date >= touch) || week.start;
  const avail = availabilityOn(focus, profile, adaptations.availability);
  const level = Math.max(...week.dates.map((date) => dampLevel(date, adaptations.illnesses)));
  let rampCap = profile.rampCap;
  if (level === 2) rampCap = Math.min(rampCap, 2.5);
  else if (level === 1) rampCap = Math.min(rampCap, 3.5);
  const budget = weekBudget(week, avail.hours, rampCap, ctl);
  if (level === 2) budget.targetTSS *= 0.72;
  else if (level === 1) budget.targetTSS *= 0.86;
  const blocked = week.trainingDates.filter((date) => ill.has(date));
  if (blocked.length >= 3) budget.targetTSS *= 0.6;
  week.minuteCap = budget.hours * 60;
  week.targetTSS = budget.targetTSS;

  let sessions = weekSessions.map((s) => ({ ...s }));
  const isFree = (s) => !locked.has(s.id) && s.date >= touch && s.role !== "race" && s.status !== "illness" && s.status !== "skipped";

  if (level >= 1) {
    sessions = sessions.map((session) => {
      if (!isFree(session)) return session;
      if (!["intensity", "intensity2", "brick", "long"].includes(session.role)) return session;
      if (level === 1 && session.role === "long") return session;
      const sport = session.sport === "brick" || session.sport === "race" ? "bike" : session.sport;
      const next = rematerialize(session, Math.min(session.minutes, level === 2 ? 45 : session.minutes), phys, event, profile, {
        role: "endurance",
        sport,
        intensityBias: 0,
        touches: null,
      });
      next.rebalanced = "damped";
      next.note = level === 2
        ? "The first days back are aerobic only. Intensity waits until the ramp is quiet."
        : "Intensity is parked for this return week. Volume comes back before sharpness.";
      return next;
    });
  }

  const activeTraining = () => sessions.filter((s) => s.role !== "race" && s.status !== "dropped" && s.status !== "illness" && s.status !== "skipped" && !ill.has(s.date));
  let capCount = Math.max(1, Math.round(avail.sessions * (week.dates.length / 7)));
  capCount = Math.min(capCount, Math.max(1, week.trainingDates.length * 2));
  if (blocked.length) capCount = Math.min(capCount, Math.max(1, (week.trainingDates.length - blocked.length) * 2));

  const dropRank = (s) => ({ recovery: 0, endurance: 1, opener: 2, shakeout: 3, intensity2: 4, strength: 5, brick: 6, long: 7, intensity: 8 }[s.role] ?? 3);
  let guard = 0;
  while (activeTraining().length > capCount && guard++ < 12) {
    const pool = sessions.filter((s) => isFree(s) && s.status !== "dropped");
    if (!pool.length) break;
    pool.sort((a, b) => dropRank(a) - dropRank(b));
    const victim = pool[0];
    sessions = sessions.map((s) => (s.id === victim.id ? applyDrop(s, "Removed so the week fits the new session ceiling.") : s));
  }

  const usedDates = () => new Set(sessions.filter((s) => s.status !== "dropped" && s.status !== "illness" && s.role !== "race").map((s) => s.date));
  let addGuard = 0;
  while (activeTraining().length < capCount && addGuard++ < 8) {
    const empty = week.trainingDates.filter((date) => date >= touch && !ill.has(date) && !usedDates().has(date));
    const shared = week.trainingDates.filter((date) => {
      if (date < touch || ill.has(date)) return false;
      const n = sessions.filter((s) => s.date === date && s.status !== "dropped" && s.status !== "illness" && s.role !== "race").length;
      return n > 0 && n < 2;
    });
    const date = empty[0] || shared[0];
    if (!date) break;
    const discipline = profile.discipline;
    const sport = discipline === "running" ? "run" : discipline === "cycling" ? "bike" : discipline === "cross" ? (addGuard % 2 ? "run" : "bike") : (addGuard % 3 === 0 ? "swim" : addGuard % 3 === 1 ? "bike" : "run");
    const spec = {
      id: `extra:${date}:${sport}:endurance:${addGuard}`,
      date,
      sport,
      role: "endurance",
      minutes: 40,
      phase: week.phase,
      weekIndex: week.index,
      intensityBias: 0,
      discipline,
    };
    const created = materialize(spec, phys, event, profile);
    created.rebalanced = "added";
    created.note = "Added because weekly availability now has room for another aerobic session.";
    sessions.push(created);
  }

  const lockedTSS = sumBy(
    sessions.filter((s) => s.role !== "race" && !isFree(s)),
    (s) => s.tss,
  );
  const lockedMin = sumBy(
    sessions.filter((s) => s.role !== "race" && !isFree(s)),
    (s) => s.minutes,
  );
  const goal = Math.max(0, budget.targetTSS - lockedTSS);
  const minuteCap = Math.max(0, budget.hours * 60 - lockedMin);
  const free = sessions.filter((s) => isFree(s));
  const fixed = sessions.filter((s) => !isFree(s));
  const aligned = week.phase === "taper"
    ? alignWeek(free, sumBy(free, (s) => s.tss), minuteCap, phys, event, profile)
    : alignWeek(free, goal, minuteCap, phys, event, profile);
  if (level >= 1) week.notes.push("Return from illness: intensity is damped and the ramp cap is tighter.");
  if (blocked.length) week.notes.push(`${blocked.length} day${blocked.length === 1 ? "" : "s"} removed for illness. Missed load is not crammed into the days that remain.`);
  return [...fixed, ...aligned];
}

export function groupPrescription(intervals) {
  const lines = [];
  let i = 0;
  const same = (a, b) =>
    a &&
    b &&
    a.kind === b.kind &&
    a.label === b.label &&
    a.modality === b.modality &&
    Math.abs(a.sec - b.sec) <= 2 &&
    Math.abs((a.i0 ?? 0) - (b.i0 ?? 0)) < 0.02 &&
    Math.abs((a.i1 ?? 0) - (b.i1 ?? 0)) < 0.02;
  while (i < intervals.length) {
    const a = intervals[i];
    const b = intervals[i + 1];
    if (b && (a.kind === "work" || a.kind === "strength") && (b.kind === "recovery" || b.kind === "rest")) {
      let n = 1;
      while (same(intervals[i + n * 2], a) && same(intervals[i + n * 2 + 1], b)) n += 1;
      if (n >= 2) {
        lines.push({ reps: n, parts: [a, b] });
        i += n * 2;
        continue;
      }
    }
    lines.push({ reps: 1, parts: [a] });
    i += 1;
  }
  return lines;
}

export function lineCue(part, phys) {
  const cue = cueForInterval(part, phys);
  const hr = hrCue(part, phys.lthr);
  return hr ? `${cue} · ${hr}` : cue;
}

function hasAdaptations(adaptations) {
  if (!adaptations) return false;
  const edits = adaptations.sessionEdits || {};
  return Object.keys(edits).length > 0 || (adaptations.illnesses || []).length > 0 || (adaptations.availability || []).length > 0;
}

function interventionLines(adaptations) {
  const lines = [];
  const edits = Object.values(adaptations?.sessionEdits || {});
  const skips = edits.filter((edit) => edit.mode === "skip").length;
  const shorts = edits.filter((edit) => edit.mode === "shorten").length;
  const overs = edits.filter((edit) => edit.mode === "overreach").length;
  if (skips) lines.push(`${skips} skipped`);
  if (shorts) lines.push(`${shorts} shortened`);
  if (overs) lines.push(`${overs} over-reached`);
  for (const ill of adaptations?.illnesses || []) {
    lines.push(`Illness from ${formatDay(ill.from)} · ${ill.days} days`);
  }
  for (const row of adaptations?.availability || []) {
    lines.push(`From ${formatDay(row.from)} · ${row.weeklyHours} h · ${row.sessionsPerWeek} sessions`);
  }
  return lines;
}

export function buildStudio(rawProfile, adaptations) {
  const profile = sanitizeProfile(rawProfile);
  if (!(profile.start && profile.race)) {
    return { ok: false, error: "Choose a start date and a race day." };
  }
  const span = diffDays(profile.start, profile.race);
  if (span < 0) return { ok: false, error: "Race day has to fall after the start date." };
  if (span > 400) return { ok: false, error: "This studio plans up to about a year." };
  const phys = derivePhysiology(profile);
  if (!phys.ok) return { ok: false, error: phys.error };
  const event = eventById(profile.discipline, profile.eventId);
  const skeleton = buildSkeleton(profile, event);
  const generated = generate(profile, phys, event, skeleton);
  tuneTaper(generated.sessions, skeleton, profile, phys, event, generated.start);
  stampPlanned(generated.sessions);
  const original = finalize(profile, phys, event, skeleton, generated.sessions, generated.start);
  const active = hasAdaptations(adaptations);
  let adapted = original;
  if (active) {
    const skel = structuredClone(skeleton);
    const sessions = adapt(generated.sessions, skel, profile, phys, event, generated.start, adaptations);
    adapted = finalize(profile, phys, event, skel, sessions, generated.start);
  }
  return {
    ok: true,
    profile,
    phys,
    event,
    active,
    original,
    adapted,
    delta: {
      ctl: adapted.raceMorning.ctl - original.raceMorning.ctl,
      tsb: adapted.raceMorning.tsb - original.raceMorning.tsb,
      peakCtl: adapted.stats.peakCtl - original.stats.peakCtl,
    },
    interventions: active ? interventionLines(adaptations) : [],
  };
}

function startingLoad(weeklyHours) {
  const ctl = (weeklyHours * 0.62 * 48) / 7;
  return { ctl, atl: ctl };
}
