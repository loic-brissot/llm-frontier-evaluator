// Colour tokens shared by CSS-in-JS consumers (GL layer, SVG charts). CSS custom properties mirror them in style.css.
export const THEME = {
  bg: '#080a0f',
  sev: ['#8d93a0', '#3987e5', '#c98500', '#e8456b'],            // unharmed, slight, hospitalised, killed
  sevNames: ['Unharmed', 'Slightly injured', 'Hospitalised', 'Killed'],
  mode: ['#d55181', '#008300', '#d95926', '#c98500', '#3987e5', '#9085e9', '#199e70', '#8d93a0'],
  map: { land: '#0b0e14', water: '#06080c', wood: '#0d1411', grass: '#0c110f', rock: '#10131a', urban: '#10151d', industrial: '#0f131a', park: '#0d1612', building: '#141a24',
    rail: '#252d3a', roadMinor: '#212a38', roadMid: '#2c3748', roadMajor: '#394559', roadMotorway: '#475670', border: '#3b4558', roadLabel: '#6b7589', waterLabel: '#3d4658',
    placeSmall: '#7b8496', placeMid: '#98a1b2', placeBig: '#c8cfdb', depLine: '#66758f' },
  choro: ['#0a0d13', '#17222f', '#3f6a7d'],
  ramp: ['#4b5873', '#9a4f73', '#ff5a82'],                       // share of severe outcomes: calm → deadly
};

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const toHex = (c) => '#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
/** Piecewise-linear colour ramp through THEME.ramp, t in 0..1 */
export function ramp(t, stops = THEME.ramp) {
  t = Math.max(0, Math.min(1, t));
  const k = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(k)), f = k - i;
  const a = hex(stops[i]), b = hex(stops[i + 1]);
  return toHex(a.map((v, j) => v + (b[j] - v) * f));
}
