// Physiology core: zones, stress scores, and the Banister / PMC model.
// Pure functions only, no DOM access, so they can be unit-tested under Node.

export const DISCIPLINES = {
  triathlon: { id: 'triathlon', label: 'Triathlon', sports: ['swim', 'bike', 'run'] },
  running: { id: 'running', label: 'Running', sports: ['run'] },
  cycling: { id: 'cycling', label: 'Cycling', sports: ['bike'] },
  cross: { id: 'cross', label: 'Cross-training', sports: ['bike', 'run', 'strength'] },
};

// Race distances (metres for swim/run, km for bike) used for the goal.
export const RACE_TYPES = {
  sprint_tri: { label: 'Sprint triathlon', discipline: 'triathlon', weeks: 10, durationMin: 90 },
  olympic_tri: { label: 'Olympic triathlon', discipline: 'triathlon', weeks: 14, durationMin: 150 },
  half_ironman: { label: 'Half Ironman 70.3', discipline: 'triathlon', weeks: 18, durationMin: 300 },
  ironman: { label: 'Ironman 140.6', discipline: 'triathlon', weeks: 24, durationMin: 540 },
  '5k': { label: '5K', discipline: 'running', weeks: 8, durationMin: 25 },
  '10k': { label: '10K', discipline: 'running', weeks: 10, durationMin: 50 },
  half_marathon: { label: 'Half marathon', discipline: 'running', weeks: 14, durationMin: 105 },
  marathon: { label: 'Marathon', discipline: 'running', weeks: 18, durationMin: 240 },
  criterium: { label: 'Road race / gran fondo', discipline: 'cycling', weeks: 12, durationMin: 180 },
  century: { label: 'Century / 100 mi', discipline: 'cycling', weeks: 14, durationMin: 330 },
  general: { label: 'General fitness block', discipline: 'cross', weeks: 12, durationMin: 60 },
};

// ---------- Basic conversions ----------

export const secPerKmToString = (s) => {
  if (!Number.isFinite(s)) return '–';
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m}:${String(r).padStart(2, '0')}`;
};

export const secPer100mToString = (s) => secPerKmToString(s);

export const hmsToSeconds = (h, m, s) => (h || 0) * 3600 + (m || 0) * 60 + (s || 0);

// ---------- Power zones (Coggan, 7 zones) ----------

export const COGGAN_ZONES = [
  { z: 1, name: 'Active Recovery', lo: 0, hi: 0.55 },
  { z: 2, name: 'Endurance', lo: 0.56, hi: 0.75 },
  { z: 3, name: 'Tempo', lo: 0.76, hi: 0.9 },
  { z: 4, name: 'Lactate Threshold', lo: 0.91, hi: 1.05 },
  { z: 5, name: 'VO2max', lo: 1.06, hi: 1.2 },
  { z: 6, name: 'Anaerobic Capacity', lo: 1.21, hi: 1.5 },
  { z: 7, name: 'Neuromuscular Power', lo: 1.51, hi: 2.5 },
];

export function powerZones(ftp) {
  return COGGAN_ZONES.map((zone) => ({
    ...zone,
    minW: Math.round(zone.lo * ftp),
    maxW: zone.z === 7 ? null : Math.round(zone.hi * ftp),
  }));
}

// ---------- Heart-rate zones (Karvonen on heart-rate reserve, anchored to LTHR) ----------
// Five-zone model anchored to lactate-threshold HR (LTHR), the usual coaching convention.

export const HR_ZONE_DEFS = [
  { z: 1, name: 'Recovery', lo: 0.65, hi: 0.81 },
  { z: 2, name: 'Aerobic', lo: 0.81, hi: 0.89 },
  { z: 3, name: 'Tempo', lo: 0.89, hi: 0.93 },
  { z: 4, name: 'Threshold', lo: 0.93, hi: 0.99 },
  { z: 5, name: 'VO2max', lo: 0.99, hi: 1.06 },
];

export function hrZones(lthr, restingHr = 50, maxHr = null) {
  const hrr = maxHr ? maxHr - restingHr : null;
  return HR_ZONE_DEFS.map((zone) => {
    const minBpm = Math.round(lthr * zone.lo);
    const maxBpm = Math.round(lthr * zone.hi);
    return { ...zone, minBpm, maxBpm, hrrMin: hrr ? Math.round(restingHr + hrr * zone.lo) : null };
  });
}

// ---------- Running pace zones (Daniels VDOT) ----------

// Daniels' VDOT via the velocity-oxygen-cost formulas.
// vo2 cost of running at velocity v (m/min)
const vo2Cost = (v) => -4.6 + 0.182258 * v + 0.000104 * v * v;
// fraction of VO2max sustainable for duration t (min)
const pctMax = (t) => 0.8 + 0.1894393 * Math.exp(-0.012778 * t) + 0.2989558 * Math.exp(-0.1932605 * t);

/** VDOT from a race of `distanceM` metres run in `timeS` seconds. */
export function vdotFromRace(distanceM, timeS) {
  const tMin = timeS / 60;
  const v = distanceM / tMin;
  return vo2Cost(v) / pctMax(tMin);
}

/** VDOT from a VO2max estimate (direct input). */
export const vdotFromVo2max = (vo2max) => vo2max;

/** Velocity (m/min) for a target VO2 demand. Inverts vo2Cost. */
function velocityForVo2(vo2) {
  // 0.000104 v^2 + 0.182258 v - (4.6 + vo2) = 0
  const a = 0.000104;
  const b = 0.182258;
  const c = -(4.6 + vo2);
  return (-b + Math.sqrt(b * b - 4 * a * c)) / (2 * a);
}

/**
 * Daniels pace zones in seconds per km for a VDOT value.
 *
 * Each zone is a band of %VDOT (Daniels, Running Formula). The %VDOT is the
 * fraction of VO2max the runner can sustain for that pace, so the VO2 demand
 * of a pace is `fraction * VDOT`, and the pace is the inverse of `vo2Cost`.
 */
export function runningPaceZones(vdot) {
  const defs = [
    { z: 'E', name: 'Easy', lo: 0.65, hi: 0.79 },
    { z: 'M', name: 'Marathon', lo: 0.75, hi: 0.84 },
    { z: 'T', name: 'Threshold', lo: 0.83, hi: 0.88 },
    { z: 'I', name: 'Interval', lo: 0.95, hi: 1.0 },
    { z: 'R', name: 'Repetition', lo: 1.05, hi: 1.1 },
  ];
  return defs.map((d) => {
    const vFast = velocityForVo2(d.hi * vdot);
    const vSlow = velocityForVo2(d.lo * vdot);
    return {
      ...d,
      fastSecPerKm: 60000 / vFast,
      slowSecPerKm: 60000 / vSlow,
    };
  });
}

/** Threshold pace (sec/km) used as the reference for rTSS. */
export function thresholdPaceSecPerKm(vdot) {
  const t = runningPaceZones(vdot).find((z) => z.z === 'T');
  return (t.fastSecPerKm + t.slowSecPerKm) / 2;
}

// ---------- Swim zones (CSS) ----------

/** CSS in m/s from a 400 and 200 time (seconds). */
export function cssFromTimes(t400, t200) {
  const d = t400 - t200;
  if (d <= 0) return null;
  return (400 - 200) / d;
}

/** CSS pace in sec/100m. */
export const cssSecPer100m = (cssMps) => 100 / cssMps;

/** Swim zones relative to CSS pace (sec/100m). */
export function swimZones(cssMps) {
  if (!cssMps) return [];
  const base = 100 / cssMps;
  const defs = [
    { z: 1, name: 'Recovery', lo: 1.2, hi: 1.3 },
    { z: 2, name: 'Endurance', lo: 1.1, hi: 1.2 },
    { z: 3, name: 'Threshold (CSS)', lo: 1.0, hi: 1.05 },
    { z: 4, name: 'VO2 / Speed', lo: 0.9, hi: 0.98 },
    { z: 5, name: 'Sprint', lo: 0.8, hi: 0.9 },
  ];
  return defs.map((d) => ({
    ...d,
    fastSecPer100m: base * d.lo,
    slowSecPer100m: base * d.hi,
  }));
}

// ---------- Stress scores ----------

/** Coggan normalised power (30 s rolling avg, 4th power mean) from a 1 Hz power array. */
export function normalizedPower(samples) {
  if (samples.length < 30) return samples.length ? mean(samples) : 0;
  const rolling = [];
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    sum += samples[i];
    if (i >= 30) sum -= samples[i - 30];
    if (i >= 29) rolling.push(sum / 30);
  }
  const fourth = rolling.reduce((a, p) => a + p ** 4, 0) / rolling.length;
  return fourth ** 0.25;
}

export const mean = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0);

/** Cycling TSS = (seconds * NP * IF) / (FTP * 3600) * 100 with IF = NP / FTP. */
export function cyclingTss({ seconds, np, ftp }) {
  if (!ftp || !seconds) return 0;
  const IF = np / ftp;
  return ((seconds * np * IF) / (ftp * 3600)) * 100;
}

/** Simple cycling TSS from a target intensity factor and duration (no power file). */
export function cyclingTssFromIF({ seconds, IF }) {
  return (seconds * IF * IF) / 3600 * 100;
}

/**
 * Running rTSS. Pace-based intensity factor against threshold pace.
 * IF_run = threshold pace / actual pace (speed-based), with a VO2-cost correction.
 * rTSS = seconds * IF^2 / 3600 * 100.
 */
export function runningTss({ seconds, paceSecPerKm, thresholdPaceSecPerKm: thr }) {
  if (!paceSecPerKm || !thr || !seconds) return 0;
  const IF = thr / paceSecPerKm; // faster pace -> smaller sec/km -> higher IF
  return (seconds * IF * IF) / 3600 * 100;
}

/** Swim stress: sTSS = IF^3 * hours * 100, where IF = CSS / actual speed. */
export function swimTss({ seconds, cssMps, actualMps }) {
  if (!cssMps || !actualMps || !seconds) return 0;
  const IF = actualMps / cssMps;
  return IF ** 3 * (seconds / 3600) * 100;
}

/** Strength / resistance stress proxy (session RPE based, comparable scale). */
export function strengthTss({ minutes, rpe = 6 }) {
  // sRPE load = RPE * minutes, scaled so an hour at RPE 6 ~ 45 TSS-equivalent.
  return (rpe * minutes) * (45 / (6 * 60));
}

// ---------- Banister / Performance Management Chart ----------

/**
 * Daily load series -> CTL/ATL/TSB.
 * Uses the exact recursive EWMA from the spec:
 *   CTL_t = CTL_{t-1} + (TSS_t - CTL_{t-1}) / 42
 *   ATL_t = ATL_{t-1} + (TSS_t - ATL_{t-1}) / 7
 *   TSB_t = CTL_t - ATL_t
 * `tss` is an array indexed by day. `seed` optionally gives the starting CTL/ATL.
 */
export function pmc(tss, seed = { ctl: 0, atl: 0 }) {
  let ctl = seed.ctl;
  let atl = seed.atl;
  return tss.map((t) => {
    ctl = ctl + (t - ctl) / 42;
    atl = atl + (t - atl) / 7;
    return { ctl, atl, tsb: ctl - atl, tss: t };
  });
}

/** Days from ISO date string a to b (b - a). */
export function daysBetween(a, b) {
  const da = Date.parse(a + 'T00:00:00Z');
  const db = Date.parse(b + 'T00:00:00Z');
  return Math.round((db - da) / 86400000);
}

export function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Projected race-day readiness from a PMC endpoint. */
export function readiness(point) {
  if (!point) return 'unknown';
  if (point.tsb > 20) return 'fresh';
  if (point.tsb > 5) return 'race-ready';
  if (point.tsb > -10) return 'neutral';
  if (point.tsb > -30) return 'fatigued';
  return 'overreached';
}
