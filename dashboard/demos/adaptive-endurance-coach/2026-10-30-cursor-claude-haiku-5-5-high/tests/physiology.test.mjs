import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  powerZones, runningPaceZones, vdotFromRace, cssFromTimes, swimZones,
  cyclingTss, runningTss, swimTss, pmc, thresholdPaceSecPerKm, readiness,
  daysBetween, addDays,
} from '../src/physiology.js';

const close = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg ?? ''} expected ${b} ±${tol}, got ${a}`);

test('Coggan power zones are contiguous and scale with FTP', () => {
  const z = powerZones(250);
  assert.equal(z.length, 7);
  assert.equal(z[3].name, 'Lactate Threshold');
  // Zone 4 is 91–105% of FTP.
  assert.equal(z[3].minW, Math.round(0.91 * 250));
  assert.equal(z[3].maxW, Math.round(1.05 * 250));
  assert.equal(z[6].maxW, null);
});

test('VDOT from a 20:00 5K is ~49.8 (Daniels reference table)', () => {
  const v = vdotFromRace(5000, 20 * 60);
  close(v, 49.8, 0.3, 'VDOT');
});

test('VDOT from a 3:30 marathon is ~44.5 (Daniels table)', () => {
  // A 3:30 marathon is VDOT ~44-45 in Daniels' tables, not 50.
  const v = vdotFromRace(42195, 3 * 3600 + 30 * 60);
  close(v, 44.5, 0.5, 'VDOT marathon');
});

test('VDOT round-trips: pace zones at VDOT 50 bracket a 20:00 5K pace', () => {
  // 5K 20:00 -> VDOT ~49.8. Threshold pace should be ~4:15 and interval ~3:50.
  const z = runningPaceZones(49.8);
  const T = z.find((x) => x.z === 'T');
  const I = z.find((x) => x.z === 'I');
  close(thresholdPaceSecPerKm(49.8), 4 * 60 + 15, 8, 'threshold ~4:15/km');
  close(I.fastSecPerKm, 3 * 60 + 50, 8, 'interval ~3:50/km');
  assert.ok(T.fastSecPerKm < T.slowSecPerKm);
});

test('Easy band is slower than threshold and internally ordered (fast < slow)', () => {
  const z = runningPaceZones(50).find((x) => x.z === 'E');
  assert.ok(z.fastSecPerKm > thresholdPaceSecPerKm(50), 'easy should be slower than threshold');
  assert.ok(z.fastSecPerKm < z.slowSecPerKm, 'fast end must be quicker than slow end');
});

test('Pace zones are ordered E < M < T < I < R (faster)', () => {
  const z = runningPaceZones(55);
  const mid = (x) => (x.fastSecPerKm + x.slowSecPerKm) / 2;
  for (let i = 1; i < z.length; i++) assert.ok(mid(z[i]) < mid(z[i - 1]), `zone ${z[i].z} should be faster`);
});

test('CSS from 400/200 times matches the formula', () => {
  // T400 = 6:00 (360 s), T200 = 2:50 (170 s) -> CSS = 200/190 m/s
  const css = cssFromTimes(360, 170);
  close(css, 200 / 190, 1e-9, 'CSS');
  close(100 / css, 95, 1e-9, 'css sec/100m');
});

test('CSS returns null for non-positive differential', () => {
  assert.equal(cssFromTimes(170, 170), null);
});

test('Swim zones are derived from CSS', () => {
  const z = swimZones(200 / 190);
  const thr = z.find((x) => x.z === 3);
  close(thr.fastSecPer100m, 95, 1e-6, 'threshold lower');
});

test('Cycling TSS for one hour at FTP is 100', () => {
  const t = cyclingTss({ seconds: 3600, np: 250, ftp: 250 });
  close(t, 100, 1e-9, 'TSS');
});

test('Cycling TSS for 2 h at IF 0.75 is 112.5', () => {
  const t = cyclingTss({ seconds: 7200, np: 0.75 * 250, ftp: 250 });
  close(t, 2 * 0.75 * 0.75 * 100, 1e-6, 'TSS');
});

test('Running rTSS for one hour at threshold pace is 100', () => {
  const t = runningTss({ seconds: 3600, paceSecPerKm: 250, thresholdPaceSecPerKm: 250 });
  close(t, 100, 1e-9, 'rTSS');
});

test('Swim sTSS for one hour at CSS is 100', () => {
  const t = swimTss({ seconds: 3600, cssMps: 1.2, actualMps: 1.2 });
  close(t, 100, 1e-9, 'sTSS');
});

test('Swim sTSS scales with IF cubed', () => {
  const t = swimTss({ seconds: 3600, cssMps: 1.0, actualMps: 0.9 });
  close(t, 0.9 ** 3 * 100, 1e-9, 'sTSS IF^3');
});

test('PMC EWMA recursion matches the spec exactly', () => {
  const series = pmc([100, 0, 0, 0], { ctl: 0, atl: 0 });
  close(series[0].ctl, 100 / 42, 1e-12, 'CTL day1');
  close(series[0].atl, 100 / 7, 1e-12, 'ATL day1');
  close(series[1].ctl, (100 / 42) * (41 / 42), 1e-12, 'CTL day2');
  close(series[0].tsb, series[0].ctl - series[0].atl, 1e-12, 'TSB');
});

test('Constant load converges CTL to the load', () => {
  const series = pmc(Array(400).fill(80));
  close(series[399].ctl, 80, 0.01, 'CTL steady state');
  close(series[399].atl, 80, 0.01, 'ATL steady state');
  close(series[399].tsb, 0, 0.01, 'TSB steady state');
});

test('ATL reacts faster than CTL to a load spike', () => {
  const series = pmc([...Array(42).fill(50), 200, ...Array(6).fill(0)]);
  const spike = series[42];
  assert.ok(spike.atl > spike.ctl, 'ATL should lead CTL after a spike');
});

test('Readiness buckets follow TSB', () => {
  assert.equal(readiness({ tsb: 25 }), 'fresh');
  assert.equal(readiness({ tsb: 10 }), 'race-ready');
  assert.equal(readiness({ tsb: -5 }), 'neutral');
  assert.equal(readiness({ tsb: -20 }), 'fatigued');
  assert.equal(readiness({ tsb: -40 }), 'overreached');
});

test('Date helpers are timezone-safe', () => {
  assert.equal(daysBetween('2026-01-01', '2026-01-31'), 30);
  assert.equal(addDays('2026-02-27', 2), '2026-03-01');
});
