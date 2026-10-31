// SVG renderers: interval block profile and the Performance Management Chart.
// No dependencies; output is plain SVG strings injected into the DOM.

const NS = 'http://www.w3.org/2000/svg';

// Zone colour ramp (cool -> hot) shared across the app.
export const ZONE_COLORS = {
  1: '#5eead4', 2: '#38bdf8', 3: '#a3e635', 3.5: '#a3e635', 4: '#facc15',
  5: '#fb923c', 6: '#f43f5e', 7: '#c026d3',
  E: '#38bdf8', M: '#a3e635', T: '#facc15', I: '#fb923c', R: '#f43f5e', S: '#c084fc',
};

const colorFor = (zone) => ZONE_COLORS[zone] || '#94a3b8';

const fmtTime = (sec) => {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
};

/**
 * Interval block profile. `segments` is the flattened profile from the planner.
 * Height maps to the zone intensity (1 = bottom). Strength uses a flat band.
 */
export function renderIntervalProfile(segments, { width = 720, height = 180, ftp = null, label = 'Workout profile' } = {}) {
  if (!segments.length) return '';
  const total = segments[segments.length - 1].end;
  const pad = { l: 36, r: 12, t: 14, b: 26 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;

  const levelOf = (zone) => {
    const map = { 1: 0.2, 2: 0.32, 3: 0.44, 3.5: 0.5, 4: 0.62, 5: 0.76, 6: 0.88, 7: 1, E: 0.3, M: 0.45, T: 0.6, I: 0.78, R: 0.92, S: 0.4 };
    return map[zone] ?? 0.4;
  };

  const x = (t) => pad.l + (t / total) * innerW;
  const y = (lvl) => pad.t + innerH - lvl * innerH;

  let rects = '';
  for (const s of segments) {
    const lvl = levelOf(s.zone);
    const x0 = x(s.start);
    const w = Math.max(1, x(s.end) - x0 - 1);
    const y0 = y(lvl);
    const h = pad.t + innerH - y0;
    const c = colorFor(s.zone);
    const opacity = s.kind === 'rest' ? 0.35 : 0.9;
    rects += `<rect class="seg seg-${s.kind}" x="${x0.toFixed(2)}" y="${y0.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" rx="3" fill="${c}" fill-opacity="${opacity}"><title>${escapeText(s.label)} · ${fmtTime(s.end - s.start)} · zone ${s.zone}</title></rect>`;
  }

  // Time axis ticks every ~10 min (or appropriate interval).
  const step = total > 5400 ? 1800 : total > 2400 ? 600 : 300;
  let ticks = '';
  for (let t = 0; t <= total; t += step) {
    ticks += `<line x1="${x(t)}" x2="${x(t)}" y1="${pad.t + innerH}" y2="${pad.t + innerH + 4}" stroke="#334155"/>`;
    ticks += `<text x="${x(t)}" y="${height - 6}" text-anchor="middle" class="axis">${fmtTime(t)}</text>`;
  }

  const ftpLine = `<text x="${pad.l + 4}" y="${pad.t + 10}" class="axis">${escapeText(label)}${ftp ? ` · FTP ${ftp}W` : ''}</text>`;

  return `<svg class="profile" viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="${escapeText(label)}">
    <defs><linearGradient id="gridfade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#1e293b"/><stop offset="1" stop-color="#0b1120"/></linearGradient></defs>
    <rect x="0" y="0" width="${width}" height="${height}" rx="12" fill="url(#gridfade)"/>
    ${[0.25, 0.5, 0.75, 1].map((l) => `<line x1="${pad.l}" x2="${width - pad.r}" y1="${y(l)}" y2="${y(l)}" stroke="#1e293b" stroke-dasharray="2 4"/>`).join('')}
    ${rects}
    <line x1="${pad.l}" x2="${width - pad.r}" y1="${pad.t + innerH}" y2="${pad.t + innerH}" stroke="#334155"/>
    ${ticks}
    ${ftpLine}
  </svg>`;
}

/**
 * Performance Management Chart. `series` is an array of day points with
 * ctl/atl/tsb (planned), and optionally adaptedCtl/adaptedAtl/adaptedTsb for overlay.
 */
export function renderPmc(series, { width = 980, height = 340, showAdapted = false, markers = [], ghost = null } = {}) {
  if (!series.length) return '';
  const pad = { l: 44, r: 16, t: 18, b: 30 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;

  const getVals = (accessor) => series.map(accessor).filter((v) => Number.isFinite(v));
  const allVals = [
    ...getVals((p) => p.ctl), ...getVals((p) => p.atl), ...getVals((p) => p.tsb),
    ...(showAdapted ? getVals((p) => p.adaptedCtl) : []),
    ...(showAdapted ? getVals((p) => p.adaptedAtl) : []),
    ...(showAdapted ? getVals((p) => p.adaptedTsb) : []),
  ];
  const max = Math.max(20, Math.ceil(Math.max(...allVals) / 10) * 10);
  const min = Math.min(-30, Math.floor(Math.min(...allVals) / 10) * 10);
  const n = series.length;

  const x = (i) => pad.l + (i / Math.max(1, n - 1)) * innerW;
  const y = (v) => pad.t + ((max - v) / (max - min)) * innerH;

  const path = (accessor) => series.map((p, i) => {
    const v = accessor(p);
    if (!Number.isFinite(v)) return null;
    return `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  }).filter(Boolean).join(' ');

  // Horizontal gridlines and y labels.
  let grid = '';
  for (let v = min; v <= max; v += 20) {
    grid += `<line x1="${pad.l}" x2="${width - pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="${v === 0 ? '#475569' : '#1e293b'}" stroke-dasharray="${v === 0 ? '' : '3 5'}"/>`;
    grid += `<text x="${pad.l - 8}" y="${y(v) + 4}" text-anchor="end" class="axis">${v}</text>`;
  }

  // X axis: month labels at the first point of each month.
  let xlabels = '';
  let lastMonth = null;
  series.forEach((p, i) => {
    const m = p.date ? p.date.slice(0, 7) : null;
    if (m && m !== lastMonth) {
      lastMonth = m;
      xlabels += `<line x1="${x(i)}" x2="${x(i)}" y1="${pad.t}" y2="${pad.t + innerH}" stroke="#1e293b"/>`;
      xlabels += `<text x="${x(i) + 4}" y="${height - 8}" class="axis">${monthLabel(m)}</text>`;
    }
  });

  // Phase band markers across the top.
  let bands = '';
  for (const m of markers) {
    const x0 = x(m.start);
    const x1 = x(m.end);
    bands += `<rect x="${x0}" y="${pad.t}" width="${Math.max(1, x1 - x0)}" height="6" fill="${m.color}" opacity="0.85"><title>${escapeText(m.label)}</title></rect>`;
  }

  // TSB area fill: positive (fresh) green, negative (fatigued) red, between 0 and the line.
  const tsbPts = series.map((p, i) => `${x(i).toFixed(1)},${y(p.tsb).toFixed(1)}`);
  const tsbArea = `M${x(0)},${y(0)} L${tsbPts.join(' L')} L${x(n - 1)},${y(0)} Z`;

  const ghostLines = ghost ? `
      <path d="${path((p) => p.originalCtl)}" fill="none" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.8"/>
      <path d="${path((p) => p.originalTsb)}" fill="none" stroke="#64748b" stroke-width="1.2" stroke-dasharray="2 4" opacity="0.6"/>` : '';

  const adapted = showAdapted ? `
      <path d="${path((p) => p.adaptedCtl)}" fill="none" stroke="#a78bfa" stroke-width="2.2"/>
      <path d="${path((p) => p.adaptedAtl)}" fill="none" stroke="#f472b6" stroke-width="1.6" stroke-dasharray="5 3" opacity="0.9"/>` : '';

  // Place the green/red gradient split exactly on the TSB = 0 line.
  const zeroFrac = (max - 0) / (max - min); // fraction from top where v = 0
  const zf = Math.min(1, Math.max(0, zeroFrac)).toFixed(4);

  return `<svg class="pmc" viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="Performance Management Chart">
    <defs>
      <linearGradient id="tsbFill" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="#34d399" stop-opacity="0.35"/>
        <stop offset="${zf}" stop-color="#34d399" stop-opacity="0.02"/>
        <stop offset="${zf}" stop-color="#f87171" stop-opacity="0.02"/>
        <stop offset="1" stop-color="#f87171" stop-opacity="0.35"/>
      </linearGradient>
      <linearGradient id="ctlFill" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="#38bdf8" stop-opacity="0.35"/>
        <stop offset="1" stop-color="#38bdf8" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${grid}
    ${xlabels}
    ${bands}
    <path d="${path((p) => p.ctl)}" fill="none" stroke="#38bdf8" stroke-width="2.4"/>
    <path d="${path((p) => p.atl)}" fill="none" stroke="#fb7185" stroke-width="1.8"/>
    <path d="${tsbArea}" fill="url(#tsbFill)" stroke="none" opacity="0.9"/>
    <path d="${path((p) => p.tsb)}" fill="none" stroke="#34d399" stroke-width="1.6"/>
    ${ghostLines}
    ${adapted}
  </svg>`;
}

function monthLabel(ym) {
  const [y, m] = ym.split('-');
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${names[Number(m) - 1]} ${y.slice(2)}`;
}

export function escapeText(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export { NS, fmtTime };
