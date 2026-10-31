/**
 * Physiological models used by the studio.
 *
 * Banister / Coggan impulse-response:
 *   CTL_t = CTL_{t-1} + (TSS_t - CTL_{t-1}) / 42
 *   ATL_t = ATL_{t-1} + (TSS_t - ATL_{t-1}) / 7
 *   TSB_t = CTL_t - ATL_t
 *
 * Coggan cycling: IF = NP / FTP
 *   TSS = seconds * NP * IF / (FTP * 3600) * 100
 *
 * Daniels running: oxygen cost inverted to pace, stress scaled to threshold pace.
 * Critical swim speed: CSS = (400 - 200) / (T400 - T200)
 *   sTSS = IF^3 * hours * 100, IF = speed / CSS
 */

import { formatClock, formatPace, formatSwimPace } from "./format.js";

const A_VO2 = 0.000104;
const B_VO2 = 0.182258;

/** Velocity in m/min from a VO2 cost (ml/kg/min). */
export function velocityFromVO2(vo2) {
  const c = -4.6 - vo2;
  const disc = B_VO2 * B_VO2 - 4 * A_VO2 * c;
  if (disc <= 0) return 0;
  return (-B_VO2 + Math.sqrt(disc)) / (2 * A_VO2);
}

/** Daniels VDOT from a race distance (m) and time (s). */
export function vdotFromRace(distanceM, seconds) {
  const tMin = seconds / 60;
  if (!(distanceM > 0) || !(tMin > 0)) return null;
  const v = distanceM / tMin;
  const vo2 = -4.6 + 0.182258 * v + 0.000104 * v * v;
  const pct =
    0.8 +
    0.1894393 * Math.exp(-0.012778 * tMin) +
    0.2989558 * Math.exp(-0.1932605 * tMin);
  if (pct <= 0) return null;
  return vo2 / pct;
}

/** Race time in seconds for a VDOT and distance. */
export function predictSeconds(vdot, distanceM) {
  if (!(vdot > 0) || !(distanceM > 0)) return null;
  let lo = 20;
  let hi = 10 * 3600;
  for (let i = 0; i < 48; i++) {
    const mid = (lo + hi) / 2;
    const got = vdotFromRace(distanceM, mid);
    if (got == null) return null;
    if (got > vdot) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

export function paceSecPerKmFromVO2Frac(vdot, frac) {
  const v = velocityFromVO2(vdot * frac);
  if (!(v > 0)) return null;
  return 1000 / (v / 60);
}

export function speedMpsFromVO2Frac(vdot, frac) {
  const v = velocityFromVO2(vdot * frac);
  return v / 60;
}

/**
 * Daniels pace table.
 * Fractions are of VDOT on the oxygen-cost curve and reproduce the published
 * pace chart (T at 88% is 4:15/km at VDOT 50; E at 63–74% is 5:34–4:54).
 * Repetition sits above VO2max, so it is a fraction of vVO2max rather than of oxygen cost.
 */
export function runningPaces(vdot) {
  const at = (frac) => paceSecPerKmFromVO2Frac(vdot, frac);
  const v100 = velocityFromVO2(vdot);
  const repV = v100 * 1.06;
  const repSecPerKm = 1000 / (repV / 60);
  const threshold = at(0.88);
  const interval = at(0.975);
  const marathon = at(0.82);
  return {
    vdot,
    fractions: {
      easy: [0.59, 0.74],
      easyTable: [0.63, 0.74],
      marathon: [0.75, 0.84],
      threshold: [0.86, 0.88],
      interval: [0.95, 1],
    },
    easy: [at(0.63), at(0.74)],
    easyFloor: at(0.59),
    marathon,
    marathonRange: [at(0.75), at(0.84)],
    threshold,
    thresholdRange: [at(0.86), at(0.88)],
    interval,
    intervalRange: [at(0.95), at(1)],
    repetition: repSecPerKm,
    repetition400: repSecPerKm * 0.4,
    thresholdSpeed: speedMpsFromVO2Frac(vdot, 0.88),
    intervalSpeed: speedMpsFromVO2Frac(vdot, 0.975),
    repetitionSpeed: repV / 60,
  };
}

/** Intensity relative to threshold pace (1.0 = T pace). */
export function runIntensity(vdot, vo2Frac) {
  const paces = runningPaces(vdot);
  const speed = speedMpsFromVO2Frac(vdot, vo2Frac);
  return paces.thresholdSpeed > 0 ? speed / paces.thresholdSpeed : 0;
}

export function repetitionIntensity(vdot) {
  const paces = runningPaces(vdot);
  return paces.thresholdSpeed > 0 ? paces.repetitionSpeed / paces.thresholdSpeed : 1.1;
}

export function powerZones(ftp) {
  const bands = [
    { id: "Z1", name: "Active recovery", lo: 0, hi: 0.55, openLow: true },
    { id: "Z2", name: "Endurance", lo: 0.56, hi: 0.75 },
    { id: "Z3", name: "Tempo", lo: 0.76, hi: 0.9 },
    { id: "Z4", name: "Lactate threshold", lo: 0.91, hi: 1.05 },
    { id: "Z5", name: "VO₂max", lo: 1.06, hi: 1.2 },
    { id: "Z6", name: "Anaerobic capacity", lo: 1.21, hi: 1.5 },
    { id: "Z7", name: "Neuromuscular", lo: 1.51, hi: null },
  ];
  return bands.map((b) => ({
    ...b,
    absLo: b.openLow ? 0 : Math.round(ftp * b.lo),
    absHi: b.hi == null ? null : Math.round(ftp * b.hi),
    unit: "W",
  }));
}

/** Friel threshold-HR zones. Bike and run use different cut points. */
export function hrZones(lthr) {
  const bike = [
    { id: "Z1", name: "Recovery", lo: 0, hi: 0.81, openLow: true },
    { id: "Z2", name: "Aerobic", lo: 0.81, hi: 0.89 },
    { id: "Z3", name: "Tempo", lo: 0.9, hi: 0.93 },
    { id: "Z4", name: "Sub-threshold", lo: 0.94, hi: 0.99 },
    { id: "Z5a", name: "Super-threshold", lo: 1, hi: 1.02 },
    { id: "Z5b", name: "Aerobic capacity", lo: 1.03, hi: 1.06 },
    { id: "Z5c", name: "Anaerobic", lo: 1.07, hi: null },
  ];
  const run = [
    { id: "Z1", name: "Recovery", lo: 0, hi: 0.85, openLow: true },
    { id: "Z2", name: "Aerobic", lo: 0.85, hi: 0.89 },
    { id: "Z3", name: "Tempo", lo: 0.9, hi: 0.94 },
    { id: "Z4", name: "Sub-threshold", lo: 0.95, hi: 0.99 },
    { id: "Z5a", name: "Super-threshold", lo: 1, hi: 1.02 },
    { id: "Z5b", name: "Aerobic capacity", lo: 1.03, hi: 1.06 },
    { id: "Z5c", name: "Anaerobic", lo: 1.07, hi: null },
  ];
  const map = (rows) =>
    rows.map((b) => ({
      ...b,
      absLo: b.openLow ? 0 : Math.round(lthr * b.lo),
      absHi: b.hi == null ? null : Math.round(lthr * b.hi),
      unit: "bpm",
    }));
  return { bike: map(bike), run: map(run) };
}

/** CSS in m/s from a 200 m and 400 m time trial, in seconds. */
export function cssFromTest(t200sec, t400sec) {
  const dt = t400sec - t200sec;
  if (!(dt > 0)) return null;
  return (400 - 200) / dt;
}

export function cssSecPer100(cssMps) {
  if (!(cssMps > 0)) return null;
  return 100 / cssMps;
}

/**
 * Swim pace zones as fractions of CSS speed.
 * Faster zones are higher fractions. Pace (s/100m) is the reciprocal.
 */
export function swimZones(cssMps) {
  const bands = [
    { id: "Z1", name: "Recovery", lo: 0.7, hi: 0.8 },
    { id: "Z2", name: "Endurance", lo: 0.8, hi: 0.88 },
    { id: "Z3", name: "Tempo", lo: 0.88, hi: 0.95 },
    { id: "Z4", name: "Threshold", lo: 0.95, hi: 1.02 },
    { id: "Z5", name: "VO₂", lo: 1.02, hi: 1.1 },
    { id: "Z6", name: "Speed", lo: 1.1, hi: 1.25 },
  ];
  return bands.map((b) => {
    const slow = cssSecPer100(cssMps * b.lo);
    const fast = cssSecPer100(cssMps * b.hi);
    return {
      ...b,
      absLo: fast,
      absHi: slow,
      unit: "/100m",
    };
  });
}

export function wkgBand(wkg) {
  const bands = [
    [2.5, "Novice"],
    [3.2, "Fair"],
    [3.8, "Moderate"],
    [4.4, "Good"],
    [5.1, "Very good"],
    [5.8, "Excellent"],
    [Infinity, "Exceptional"],
  ];
  for (const [hi, name] of bands) {
    if (wkg < hi) return name;
  }
  return "Exceptional";
}

function meanFourth(i0, i1) {
  if (Math.abs(i1 - i0) < 1e-8) return i0 ** 4;
  return (i1 ** 5 - i0 ** 5) / (5 * (i1 - i0));
}

function meanCube(i0, i1) {
  if (Math.abs(i1 - i0) < 1e-8) return i0 ** 3;
  return (i1 ** 4 - i0 ** 4) / (4 * (i1 - i0));
}

/** Whole-workout Coggan TSS. Intensities are fractions of threshold. */
export function cogganTSS(intervals) {
  let sec = 0;
  let acc4 = 0;
  for (const iv of intervals) {
    const dur = Math.max(0, iv.sec || 0);
    sec += dur;
    acc4 += dur * meanFourth(iv.i0 ?? 0, iv.i1 ?? iv.i0 ?? 0);
  }
  if (sec <= 0) return { tss: 0, iff: 0, seconds: 0 };
  const np = Math.pow(Math.max(acc4 / sec, 0), 0.25);
  const tss = (sec * np * np) / 3600 * 100;
  return { tss, iff: np, seconds: sec };
}

/** Swim stress summed across steady and ramped pieces. */
export function swimStress(intervals) {
  let sec = 0;
  let tss = 0;
  let acc3 = 0;
  for (const iv of intervals) {
    const dur = Math.max(0, iv.sec || 0);
    const m3 = meanCube(iv.i0 ?? 0, iv.i1 ?? iv.i0 ?? 0);
    sec += dur;
    acc3 += dur * m3;
    tss += m3 * (dur / 3600) * 100;
  }
  const iff = sec > 0 ? Math.pow(Math.max(acc3 / sec, 0), 1 / 3) : 0;
  return { tss, iff, seconds: sec };
}

export function strengthStress(intervals) {
  const sec = intervals.reduce((s, iv) => s + Math.max(0, iv.sec || 0), 0);
  return { tss: (sec / 60) * 0.42, iff: 0.45, seconds: sec };
}

function stressForMode(mode, items) {
  if (mode === "swim") return swimStress(items);
  if (mode === "strength") return strengthStress(items);
  return cogganTSS(items);
}

/**
 * One stress score for a session.
 * A single sport uses its own model over the whole workout (Coggan NP, cubic swim, or strength).
 * A brick or a triathlon race sums each sport's own stress.
 */
export function stressOf(intervals) {
  if (!intervals?.length) return { tss: 0, iff: 0, seconds: 0 };
  const groups = [];
  for (const iv of intervals) {
    const last = groups[groups.length - 1];
    if (!last || last.mode !== iv.modality) groups.push({ mode: iv.modality, items: [iv] });
    else last.items.push(iv);
  }
  if (groups.length === 1) return stressForMode(groups[0].mode, groups[0].items);
  let tss = 0;
  let sec = 0;
  for (const g of groups) {
    const part = stressForMode(g.mode, g.items);
    tss += part.tss;
    sec += part.seconds;
  }
  const hours = sec / 3600;
  const iff = hours > 0 ? Math.sqrt(Math.max(tss, 0) / hours / 100) : 0;
  return { tss, iff, seconds: sec };
}

/**
 * Loose heart-rate target from a threshold-relative intensity.
 * Threshold intensity (1.0) maps to threshold HR. The curve flattens above it.
 */
export function hrFraction(intensity) {
  const pts = [
    [0.45, 0.68],
    [0.55, 0.74],
    [0.65, 0.8],
    [0.75, 0.85],
    [0.88, 0.94],
    [1, 1],
    [1.08, 1.03],
    [1.15, 1.05],
    [1.3, 1.07],
  ];
  if (intensity <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    if (intensity <= x1) {
      const t = (intensity - x0) / (x1 - x0);
      return y0 + (y1 - y0) * t;
    }
  }
  return pts[pts.length - 1][1];
}

export function simulateLoads(dailyTSS, ctl0, atl0) {
  let ctl = ctl0;
  let atl = atl0;
  return dailyTSS.map((tss) => {
    const load = Number.isFinite(tss) ? tss : 0;
    ctl = ctl + (load - ctl) / 42;
    atl = atl + (load - atl) / 7;
    return { tss: load, ctl, atl, tsb: ctl - atl };
  });
}

export function formLabel(tsb) {
  if (tsb >= 25) return { key: "high", name: "Very fresh", note: "Freshness is high. Some fitness was given back to get here." };
  if (tsb >= 15) return { key: "peak", name: "Peak freshness", note: "The taper has done its job." };
  if (tsb >= 5) return { key: "ready", name: "Race ready", note: "Fatigue has eased and fitness is still in the system." };
  if (tsb >= -5) return { key: "neutral", name: "Neutral", note: "Load and freshness are balanced." };
  if (tsb >= -15) return { key: "productive", name: "Productive", note: "A useful training load. Not a day to race." };
  if (tsb >= -30) return { key: "loaded", name: "Carrying fatigue", note: "Acute load is ahead of fitness." };
  return { key: "over", name: "Overreached", note: "Acute load is too far ahead. The plan should back off." };
}

export function zoneWattLabel(zone, ftp) {
  if (zone.hi == null) return `${Math.round(ftp * zone.lo)} W+`;
  if (zone.openLow) return `< ${Math.round(ftp * zone.hi)} W`;
  return `${Math.round(ftp * zone.lo)}–${Math.round(ftp * zone.hi)} W`;
}

export function describeRunPace(seconds) {
  return formatPace(seconds);
}

export function cueForInterval(iv, phys) {
  const i0 = iv.i0 ?? 0;
  const i1 = iv.i1 ?? i0;
  const mid = (i0 + i1) / 2;
  if (iv.modality === "strength") {
    if (iv.kind === "rest") return "Rest";
    if (iv.kind === "warmup" || iv.kind === "cooldown") return "Easy";
    return "RPE 6 · two reps in reserve";
  }
  if (iv.kind === "rest") return iv.modality === "bike" ? `${Math.round(phys.ftp * mid)} W` : "Rest";
  if (iv.modality === "swim") {
    const a = formatSwimPace(phys.cssSec / i0);
    const b = formatSwimPace(phys.cssSec / i1);
    return Math.abs(i0 - i1) < 0.015 ? a : `${a} → ${b}`;
  }
  if (iv.modality === "bike") {
    const wa = Math.round(phys.ftp * i0);
    const wb = Math.round(phys.ftp * i1);
    return Math.abs(i0 - i1) < 0.015 ? `${wa} W` : `${wa} → ${wb} W`;
  }
  const pace = (intensity) => {
    const speed = phys.paces.thresholdSpeed * intensity;
    if (!(speed > 0)) return "–";
    return formatPace(1000 / speed);
  };
  const a = pace(i0);
  const b = pace(i1);
  return Math.abs(i0 - i1) < 0.015 ? a : `${a} → ${b}`;
}

export function hrCue(iv, lthr) {
  if (!lthr || iv.modality === "strength") return null;
  const mid = ((iv.i0 ?? 0) + (iv.i1 ?? iv.i0 ?? 0)) / 2;
  if (mid < 0.5 || mid > 1.2) return null;
  const f0 = hrFraction(iv.i0 ?? mid);
  const f1 = hrFraction(iv.i1 ?? mid);
  const a = Math.round(lthr * Math.min(f0, f1));
  const b = Math.round(lthr * Math.max(f0, f1));
  if (Math.abs(a - b) <= 2) return `${b} bpm`;
  return `${a}–${b} bpm`;
}

export function formatPct(frac) {
  return `${Math.round(frac * 100)}%`;
}

export function clockLabel(sec) {
  return formatClock(sec);
}
