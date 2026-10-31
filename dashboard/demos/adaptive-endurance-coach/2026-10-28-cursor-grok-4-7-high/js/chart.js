/** SVG performance chart and workout profiles. */

function colorFor(iv) {
  const mid = ((iv.i0 ?? 0) + (iv.i1 ?? iv.i0 ?? 0)) / 2;
  const maps = {
    swim: ["#1c3c4c", "#3c86ae", "#9fd7ff", "#e7f6ff"],
    run: ["#4a2a22", "#c46b45", "#ffb088", "#ffe1d2"],
    strength: ["#3a3148", "#8d74b8", "#d7c4ff", "#f3edff"],
    bike: ["#3a4624", "#8eae3c", "#dff25a", "#f4ffc4"],
  };
  const stops = maps[iv.modality] || maps.bike;
  if (mid < 0.62) return stops[0];
  if (mid < 0.84) return stops[1];
  if (mid < 1.05) return stops[2];
  return stops[3];
}

function sumSec(intervals) {
  return intervals.reduce((total, iv) => total + (iv.sec || 0), 0);
}

export function renderProfile(intervals, opts = {}) {
  const mini = !!opts.mini;
  const w = mini ? 160 : 960;
  const h = mini ? 48 : 250;
  const pad = mini
    ? { l: 0, r: 0, t: 2, b: 2 }
    : { l: 36, r: 12, t: 16, b: 28 };
  if (!intervals?.length) {
    return `<svg class="profile-svg ${mini ? "is-mini" : ""}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Rest">
      <line x1="${pad.l}" y1="${h / 2}" x2="${w - pad.r}" y2="${h / 2}" stroke="rgba(244,241,230,0.25)" stroke-dasharray="3 4"/>
    </svg>`;
  }
  const total = Math.max(1, sumSec(intervals));
  const strength = intervals.every((iv) => iv.modality === "strength");
  const peak = Math.max(...intervals.map((iv) => Math.max(iv.i0 ?? 0, iv.i1 ?? 0)), strength ? 1 : 1.2);
  const yMax = strength ? 1 : Math.max(1.25, peak * 1.08);
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const xAt = (sec) => pad.l + (sec / total) * plotW;
  const yAt = (intensity) => pad.t + (1 - Math.max(0, intensity) / yMax) * plotH;
  const base = yAt(0);
  let cursor = 0;
  const shapes = [];
  for (const iv of intervals) {
    const x0 = xAt(cursor);
    cursor += iv.sec;
    const x1 = xAt(cursor);
    const y0 = yAt(iv.i0 ?? 0);
    const y1 = yAt(iv.i1 ?? iv.i0 ?? 0);
    shapes.push(
      `<polygon points="${x0.toFixed(1)},${base.toFixed(1)} ${x0.toFixed(1)},${y0.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${base.toFixed(1)}" fill="${colorFor(iv)}"/>`,
    );
  }
  const threshold = !strength && !mini
    ? `<line x1="${pad.l}" y1="${yAt(1)}" x2="${w - pad.r}" y2="${yAt(1)}" stroke="rgba(230,194,122,0.85)" stroke-dasharray="3 4"/>
       <text x="${w - pad.r}" y="${yAt(1) - 6}" text-anchor="end" class="svg-faint">threshold</text>`
    : "";
  const axis = mini
    ? ""
    : [0, 0.25, 0.5, 0.75, 1].map((frac) => {
        const sec = total * frac;
        const min = Math.round(sec / 60);
        return `<text x="${xAt(sec)}" y="${h - 8}" text-anchor="${frac === 0 ? "start" : frac === 1 ? "end" : "middle"}" class="svg-faint">${min}m</text>`;
      }).join("");
  return `<svg class="profile-svg ${mini ? "is-mini" : ""}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Workout profile">
    <rect x="0" y="0" width="${w}" height="${h}" fill="transparent"/>
    ${threshold}
    ${shapes.join("")}
    ${axis}
  </svg>`;
}

function escapeXml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

const PHASE_COLOR = {
  base: "rgba(143,176,122,0.16)",
  build: "rgba(223,242,90,0.13)",
  peak: "rgba(230,194,122,0.16)",
  taper: "rgba(159,215,255,0.14)",
  recovery: "rgba(167,163,148,0.12)",
};

export function renderPMC(view) {
  const W = 1000;
  const H = 460;
  const m = { l: 46, r: 16, t: 34, b: 32 };
  const rows = view.adapted;
  const n = rows.length;
  const plotW = W - m.l - m.r;
  const plotH = H - m.t - m.b;
  let minY = 0;
  let maxY = 20;
  const consider = view.overlay ? rows.concat(view.original || []) : rows;
  for (const row of consider) {
    minY = Math.min(minY, row.tsb);
    maxY = Math.max(maxY, row.ctl, row.atl, Math.max(0, row.tsb));
  }
  minY = Math.min(-8, Math.floor(minY / 5) * 5);
  maxY = Math.ceil((maxY * 1.08) / 5) * 5;
  const x = (i) => m.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v) => m.t + (1 - (v - minY) / (maxY - minY)) * plotH;
  const yTicks = [];
  const step = niceStep(maxY - minY);
  for (let v = Math.ceil(minY / step) * step; v <= maxY + 0.1; v += step) yTicks.push(v);

  const grid = yTicks
    .map((v) => {
      const yy = y(v);
      const label = `${v > 0 ? "+" : ""}${Math.round(v)}`;
      return `<line x1="${m.l}" y1="${yy}" x2="${W - m.r}" y2="${yy}" stroke="rgba(244,241,230,${v === 0 ? 0.28 : 0.08})"/>
        <text x="${m.l - 8}" y="${yy + 3}" text-anchor="end" class="svg-faint">${label}</text>`;
    })
    .join("");

  const bands = phaseBands(rows, x, m, H);
  const illness = (view.illness || [])
    .map((range) => {
      const a = rows.findIndex((row) => row.date >= range.start);
      const b = rows.findIndex((row) => row.date > range.end);
      if (a < 0) return "";
      const end = b < 0 ? n - 1 : Math.max(a, b - 1);
      const x0 = x(a);
      const x1 = x(end);
      return `<rect x="${x0}" y="${m.t}" width="${Math.max(2, x1 - x0)}" height="${plotH}" fill="url(#hatch)"/>`;
    })
    .join("");

  const tsbPos = view.showTsb === false ? "" : signedArea(rows, x, y, 1);
  const tsbNeg = view.showTsb === false ? "" : signedArea(rows, x, y, -1);
  const ctl = view.showCtl === false ? "" : linePath(rows, x, y, "ctl");
  const atl = view.showAtl === false ? "" : linePath(rows, x, y, "atl");
  const original = view.overlay && view.original?.length
    ? `${view.showCtl === false ? "" : `<path d="${linePath(view.original, x, y, "ctl")}" class="pmc-ghost pmc-ghost-ctl"/>`}
       ${view.showAtl === false ? "" : `<path d="${linePath(view.original, x, y, "atl")}" class="pmc-ghost pmc-ghost-atl"/>`}`
    : "";

  const months = monthTicks(rows, x, H);
  const raceIdx = rows.findIndex((row) => row.date === view.race);
  const race = raceIdx >= 0
    ? `<line x1="${x(raceIdx)}" y1="${m.t - 16}" x2="${x(raceIdx)}" y2="${H - m.b}" stroke="#e6c27a" stroke-width="1.25"/>
       <text x="${x(raceIdx)}" y="${m.t - 20}" text-anchor="middle" class="svg-race">${escapeXml(view.goal || "Race")}</text>`
    : "";
  const todayIdx = rows.findIndex((row) => row.date === view.today);
  const today = todayIdx >= 0
    ? `<line x1="${x(todayIdx)}" y1="${m.t}" x2="${x(todayIdx)}" y2="${H - m.b}" stroke="rgba(244,241,230,0.45)" stroke-dasharray="2 3"/>
       <text x="${x(todayIdx) + 4}" y="${m.t + 12}" class="svg-faint">Today</text>`
    : "";

  const svg = `<svg class="pmc-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Performance management chart of chronic load, acute load, and form">
    <defs>
      <filter id="ctlglow" x="-10%" y="-20%" width="120%" height="140%">
        <feGaussianBlur stdDeviation="2.4" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(32)">
        <line x1="0" y1="0" x2="0" y2="7" stroke="#ff5c39" stroke-width="2" opacity="0.28"/>
      </pattern>
    </defs>
    ${bands}
    ${grid}
    ${illness}
    ${tsbPos ? `<path d="${tsbPos}" class="pmc-tsb pmc-tsb-pos"/>` : ""}
    ${tsbNeg ? `<path d="${tsbNeg}" class="pmc-tsb pmc-tsb-neg"/>` : ""}
    ${original}
    ${atl ? `<path d="${atl}" class="pmc-line pmc-atl"/>` : ""}
    ${ctl ? `<path d="${ctl}" class="pmc-line pmc-ctl" filter="url(#ctlglow)"/>` : ""}
    ${race}
    ${today}
    ${months}
  </svg>`;

  return {
    svg,
    layout: { W, H, m, n, minY, maxY, x, y },
  };
}

function niceStep(span) {
  if (span > 140) return 40;
  if (span > 80) return 20;
  if (span > 40) return 10;
  return 5;
}

function linePath(rows, x, y, key) {
  return rows.map((row, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(2)} ${y(row[key]).toFixed(2)}`).join(" ");
}

function signedArea(rows, x, y, sign) {
  const zeroY = y(0);
  let d = "";
  let open = false;
  const close = (at) => {
    d += ` L ${x(at).toFixed(2)} ${zeroY.toFixed(2)} Z`;
    open = false;
  };
  for (let i = 0; i < rows.length; i++) {
    const v = rows[i].tsb;
    const prev = i > 0 ? rows[i - 1].tsb : v;
    if (i > 0 && prev * v < 0) {
      const t = Math.abs(prev) / (Math.abs(prev) + Math.abs(v));
      const xi = i - 1 + t;
      if ((sign > 0 && prev > 0) || (sign < 0 && prev < 0)) {
        d += ` L ${x(xi).toFixed(2)} ${zeroY.toFixed(2)}`;
        close(xi);
      }
      if ((sign > 0 && v > 0) || (sign < 0 && v < 0)) {
        d += `M ${x(xi).toFixed(2)} ${zeroY.toFixed(2)} L ${x(i).toFixed(2)} ${y(v).toFixed(2)}`;
        open = true;
      }
      continue;
    }
    const on = sign > 0 ? v >= 0 : v <= 0;
    if (!on) {
      if (open) close(i - 1);
      continue;
    }
    if (!open) {
      d += `M ${x(i).toFixed(2)} ${zeroY.toFixed(2)} `;
      open = true;
    }
    d += `L ${x(i).toFixed(2)} ${y(v).toFixed(2)} `;
  }
  if (open) close(rows.length - 1);
  return d;
}

function phaseBands(rows, x, m, H) {
  const bands = [];
  let start = 0;
  for (let i = 1; i <= rows.length; i++) {
    if (i === rows.length || rows[i].phase !== rows[start].phase) {
      const phase = rows[start].phase;
      const x0 = x(start);
      const x1 = x(Math.max(start, i - 1));
      bands.push(`<rect x="${x0}" y="${m.t}" width="${Math.max(1, x1 - x0)}" height="${H - m.t - m.b}" fill="${PHASE_COLOR[phase] || "transparent"}"/>`);
      if (x1 - x0 > 78) {
        bands.push(`<text x="${x0 + 6}" y="${m.t + 14}" class="svg-phase">${phase}</text>`);
      }
      start = i;
    }
  }
  return bands.join("");
}

function monthTicks(rows, x, H) {
  let last = "";
  const ticks = [];
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  rows.forEach((row, i) => {
    const key = row.date.slice(0, 7);
    if (key === last) return;
    last = key;
    const month = months[Number(row.date.slice(5, 7)) - 1];
    ticks.push(`<text x="${x(i)}" y="${H - 10}" class="svg-faint">${month}</text>`);
  });
  return ticks.join("");
}

export { PHASE_COLOR };
