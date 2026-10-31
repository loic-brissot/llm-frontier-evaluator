/* ═══════════════════════════════════════════════════════════════
   physiology.js — sports-science models
   · Daniels VDOT (running)        · Coggan power zones (cycling)
   · Friel HR zones                · Critical Swim Speed (swimming)
   · TSS / rTSS / sTSS stress scores
   ═══════════════════════════════════════════════════════════════ */
'use strict';

const Physio = (() => {

  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  /* ── formatting ─────────────────────────────────────────── */
  function fmtPace(sec) {                      // seconds → m:ss
    sec = Math.max(0, Math.round(sec));
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
  }
  function parseClock(str) {                   // "1:45" | "40:00" → seconds
    const p = String(str).trim().split(':').map(Number);
    if (p.some(isNaN)) return 0;
    return p.length === 1 ? p[0] : p[0] * 60 + p[1];
  }

  /* ── Daniels VDOT ───────────────────────────────────────── */
  // Oxygen cost of running at velocity v (m/min) for t minutes
  function vdotFromRace(distM, timeSec) {
    const t = timeSec / 60, v = distM / t;
    const cost = -4.60 + 0.182258 * v + 0.000104 * v * v;
    const fracMax = 0.8 + 0.1894393 * Math.exp(-0.012778 * t)
                        + 0.2989558 * Math.exp(-0.1932605 * t);
    return cost / fracMax;
  }
  // velocity (m/min) at which oxygen cost equals VDOT (≈ vVO2max)
  function vVO2(vdot) {
    const a = 0.000104, b = 0.182258, c = -(vdot + 4.60);
    return (-b + Math.sqrt(b * b - 4 * a * c)) / (2 * a);
  }

  // Daniels zone speeds as fractions of vVO2max
  const RUN_ZONE_DEFS = [
    { key: 'E', name: 'Easy',       lo: 0.70,  hi: 0.82,  desc: 'Aerobic base, recovery, long runs' },
    { key: 'M', name: 'Marathon',   lo: 0.82,  hi: 0.885, desc: 'Steady endurance / race simulation' },
    { key: 'T', name: 'Threshold',  lo: 0.885, hi: 0.945, desc: 'Comfortably hard · lactate threshold' },
    { key: 'I', name: 'Interval',   lo: 0.945, hi: 1.02,  desc: 'VO₂max · 3–5 min repetitions' },
    { key: 'R', name: 'Repetition', lo: 1.02,  hi: 1.12,  desc: 'Speed & running economy' },
  ];

  function runZones(vdot) {
    const vv = vVO2(vdot);                                  // m/min
    const pace = f => 60000 / (vv * f);                     // → sec/km
    return {
      vdot,
      thresholdPaceSec: pace(0.93),                          // reference for rTSS
      thresholdSpeed: vv * 0.93 / 60,                        // m/s
      zones: RUN_ZONE_DEFS.map(z => ({
        key: z.key, name: z.name, desc: z.desc,
        loSec: pace(z.hi),                                   // faster edge
        hiSec: pace(z.lo),                                   // slower edge
      })),
    };
  }
  function runZoneKey(intensity) {           // intensity = speed / threshold speed
    const f = 0.93 * intensity;              // → fraction of vVO2max
    for (const z of RUN_ZONE_DEFS) if (f >= z.lo && f < z.hi) return z.key;
    return f < RUN_ZONE_DEFS[0].lo ? 'E' : 'R';
  }

  /* ── Coggan 7-zone power model ──────────────────────────── */
  const COGGAN = [
    { n: 1, name: 'Active Recovery', lo: 0.00, hi: 0.55 },
    { n: 2, name: 'Endurance',       lo: 0.56, hi: 0.75 },
    { n: 3, name: 'Tempo',           lo: 0.76, hi: 0.90 },
    { n: 4, name: 'Lactate Threshold', lo: 0.91, hi: 1.05 },
    { n: 5, name: 'VO₂max',          lo: 1.06, hi: 1.20 },
    { n: 6, name: 'Anaerobic Capacity', lo: 1.21, hi: 1.50 },
    { n: 7, name: 'Neuromuscular',   lo: 1.51, hi: 99 },
  ];
  function cogganZones(ftp) {
    return COGGAN.map(z => ({
      ...z,
      loW: Math.round(z.lo * ftp),
      hiW: z.hi > 10 ? null : Math.round(z.hi * ftp),
    }));
  }
  function cogganZoneName(intensity) {
    for (const z of COGGAN) if (intensity >= z.lo && intensity <= z.hi) return z;
    return COGGAN[COGGAN.length - 1];
  }

  /* ── Friel heart-rate zones (% of LTHR) ─────────────────── */
  const HR_DEFS = [
    { n: 1, name: 'Recovery',  lo: 0.00, hi: 0.85 },
    { n: 2, name: 'Aerobic',   lo: 0.85, hi: 0.89 },
    { n: 3, name: 'Tempo',     lo: 0.90, hi: 0.94 },
    { n: 4, name: 'Threshold', lo: 0.95, hi: 1.00 },
    { n: 5, name: 'VO₂max+',   lo: 1.00, hi: 1.06 },
  ];
  function hrZones(lthr) {
    return HR_DEFS.map(z => ({
      ...z,
      loBpm: z.lo === 0 ? null : Math.round(z.lo * lthr),
      hiBpm: Math.round(z.hi * lthr),
    }));
  }

  /* ── Critical Swim Speed ────────────────────────────────── */
  // CSS (m/s) = (400 − 200) / (T400 − T200); input is pace per 100 m
  function swimZones(cssSecPer100) {
    const cssSpeed = 100 / cssSecPer100;                    // m/s
    const mk = (key, name, loF, hiF, desc) => ({           // f = fraction of CSS speed
      key, name, desc,
      loSec: cssSecPer100 / hiF,                            // faster edge (s/100m)
      hiSec: cssSecPer100 / loF,
    });
    return {
      cssSecPer100, cssSpeed,
      zones: [
        mk('S1', 'Recovery',   0.70, 0.82, 'Technique & easy aerobic'),
        mk('S2', 'Endurance',  0.82, 0.92, 'Aerobic volume'),
        mk('S3', 'Threshold',  0.92, 1.00, 'CSS sets · race-specific'),
        mk('S4', 'Sprint',     1.00, 1.12, 'Above CSS · speed & power'),
      ],
    };
  }

  /* ── Training stress scores ─────────────────────────────── */
  // Bike:  TSS = (s·NP·IF)/(FTP·3600)·100 → hr·IF²·100
  // Run:   rTSS = hr·IF²·100   (IF = speed / threshold speed)
  // Swim:  sTSS = IF³·hr·100   (IF = speed / CSS speed)
  function segmentTSS(sport, durMin, intensity) {
    const hr = durMin / 60;
    if (sport === 'strength') return hr * 45;               // moderate RPE-7 estimate
    if (sport === 'swim')     return Math.pow(intensity, 3) * hr * 100;
    return intensity * intensity * hr * 100;
  }
  function tssFromSegments(sport, segments) {
    return segments.reduce((s, g) => s + segmentTSS(sport, g.durMin, g.intensity), 0);
  }

  /* ── Banister impulse-response / PMC ────────────────────── */
  function pmc(dailyTss, ctl0 = 0, atl0 = 0) {
    let ctl = ctl0, atl = atl0;
    return dailyTss.map(tss => {
      ctl += (tss - ctl) / 42;
      atl += (tss - atl) / 7;
      return { tss, ctl, atl, tsb: ctl - atl };
    });
  }

  return {
    clamp, fmtPace, parseClock,
    vdotFromRace, vVO2, runZones, runZoneKey,
    cogganZones, cogganZoneName, hrZones, swimZones,
    segmentTSS, tssFromSegments, pmc,
  };
})();
