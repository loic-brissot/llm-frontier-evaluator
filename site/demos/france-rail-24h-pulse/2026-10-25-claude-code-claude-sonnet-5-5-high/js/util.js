// Small helpers shared by all modules.

export const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
export const lerp = (a, b, t) => a + (b - a) * t;
export const smooth = (u) => u * u * (3 - 2 * u);

export const CATS = [
  { key: 'tgv', name: 'TGV', long: 'High-speed · TGV, OUIGO, ICE, Lyria', color: '#ff4d94', rgb: [255, 77, 148] },
  { key: 'ic', name: 'Intercités', long: 'Intercity · day & night', color: '#ffb020', rgb: [255, 176, 32] },
  { key: 'ter', name: 'TER', long: 'Regional · TER & tram-train', color: '#3fd0ff', rgb: [63, 208, 255] },
];

// Travel-time classes of the accessibility mode (seconds), brightest = closest.
export const BANDS = [
  { max: 3600, label: '< 1 h', color: '#fff07a' },
  { max: 7200, label: '1 – 2 h', color: '#8fe388' },
  { max: 10800, label: '2 – 3 h', color: '#34c3b4' },
  { max: 18000, label: '3 – 5 h', color: '#3f8be0' },
  { max: Infinity, label: '> 5 h', color: '#8a5bd6' },
];
export const bandOf = (sec) => (sec < 3600 ? 0 : sec < 7200 ? 1 : sec < 10800 ? 2 : sec < 18000 ? 3 : 4);

export function pad2(n) { return n < 10 ? '0' + n : '' + n; }

/** seconds since service-day midnight -> "HH:MM" (wraps beyond 24 h). */
export function hm(sec) {
  let s = Math.round(sec / 60);
  s = ((s % 1440) + 1440) % 1440;
  return pad2((s / 60) | 0) + ':' + pad2(s % 60);
}
export function hms(sec) {
  let s = Math.floor(sec);
  s = ((s % 86400) + 86400) % 86400;
  return pad2((s / 3600) | 0) + ':' + pad2(((s % 3600) / 60) | 0) + ':' + pad2(s % 60);
}
/** duration in seconds -> "2 h 05" / "42 min" */
export function dur(sec) {
  const m = Math.round(sec / 60);
  if (m < 60) return m + ' min';
  return ((m / 60) | 0) + ' h ' + pad2(m % 60);
}
export function durShort(sec) {
  const m = Math.round(sec / 60);
  if (m < 60) return m + '′';
  return ((m / 60) | 0) + 'h' + pad2(m % 60);
}

export function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) {
    for (const k in props) {
      const v = props[k];
      if (k === 'class') e.className = v;
      else if (k === 'html') e.innerHTML = v;
      else if (k === 'text') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') { for (const sk in v) { if (sk.startsWith('--')) e.style.setProperty(sk, v[sk]); else e.style[sk] = v[sk]; } }
      else if (v !== false && v != null) e.setAttribute(k, v);
    }
  }
  for (const c of kids) if (c != null) e.append(c);
  return e;
}

export function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** largest index i in sorted array a (length n) with a[i] <= x, or -1 */
export function upperIdx(a, x, n = a.length) {
  let lo = 0, hi = n - 1, r = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (a[m] <= x) { r = m; lo = m + 1; } else hi = m - 1;
  }
  return r;
}
/** first index i with a[i] >= x (n if none) */
export function lowerIdx(a, x, n = a.length) {
  let lo = 0, hi = n;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (a[m] < x) lo = m + 1; else hi = m;
  }
  return lo;
}

export function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export function rgba(rgb, a) { return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`; }
export function mix(a, b, t) {
  return [Math.round(lerp(a[0], b[0], t)), Math.round(lerp(a[1], b[1], t)), Math.round(lerp(a[2], b[2], t))];
}
/** piecewise-linear colour ramp over stops [[t, rgb], ...] */
export function ramp(stops, t) {
  t = clamp(t, 0, 1);
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1], [t1, c1] = stops[i];
      return mix(c0, c1, (t - t0) / (t1 - t0 || 1));
    }
  }
  return stops[stops.length - 1][1];
}

export function fmtInt(n) { return Math.round(n).toLocaleString('en-US'); }
