/** Date and number formatting that stays on the local calendar (no UTC shifts). */

export function parseISO(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function fmtISO(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function addDays(date, n) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  d.setDate(d.getDate() + n);
  return d;
}

export function addDaysISO(iso, n) {
  return fmtISO(addDays(parseISO(iso), n));
}

export function diffDays(aIso, bIso) {
  const ms = parseISO(bIso) - parseISO(aIso);
  return Math.round(ms / 86400000);
}

export function eachDate(startIso, endIso) {
  const out = [];
  let cur = parseISO(startIso);
  const end = parseISO(endIso);
  while (cur <= end) {
    out.push(fmtISO(cur));
    cur = addDays(cur, 1);
  }
  return out;
}

/** Monday = 0 … Sunday = 6 */
export function weekdayMon(iso) {
  return (parseISO(iso).getDay() + 6) % 7;
}

export function startOfWeekMonday(iso) {
  return addDaysISO(iso, -weekdayMon(iso));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function formatDay(iso) {
  const d = parseISO(iso);
  return `${WEEKDAYS[weekdayMon(iso)]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function formatShort(iso) {
  const d = parseISO(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function formatRange(a, b) {
  const da = parseISO(a);
  const db = parseISO(b);
  if (da.getMonth() === db.getMonth()) {
    return `${da.getDate()}–${db.getDate()} ${MONTHS[da.getMonth()]}`;
  }
  return `${formatShort(a)} – ${formatShort(b)}`;
}

export function weekdayName(iso) {
  return WEEKDAYS[weekdayMon(iso)];
}

export function parseClock(str) {
  if (str == null) return null;
  const raw = String(str).trim();
  if (!raw) return null;
  const parts = raw.split(":").map((p) => Number(p));
  if (parts.some((n) => !Number.isFinite(n) || n < 0)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + Math.round(parts[2]);
  if (parts.length === 2) return parts[0] * 60 + Math.round(parts[1]);
  if (parts.length === 1) return Math.round(parts[0]);
  return null;
}

export function formatClock(seconds, { hours = false } = {}) {
  if (!Number.isFinite(seconds)) return "–";
  let s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  if (hours || h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function formatPace(secPerKm) {
  if (!Number.isFinite(secPerKm) || secPerKm <= 0) return "–";
  return `${formatClock(secPerKm)}/km`;
}

export function formatSwimPace(secPer100) {
  if (!Number.isFinite(secPer100) || secPer100 <= 0) return "–";
  return `${formatClock(secPer100)}/100m`;
}

export function formatDuration(minutes) {
  if (!Number.isFinite(minutes)) return "–";
  const m = Math.round(minutes);
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h <= 0) return `${rem} min`;
  if (rem === 0) return `${h} h`;
  return `${h} h ${rem} min`;
}

export function formatHM(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function signed(n, digits = 0) {
  if (!Number.isFinite(n)) return "–";
  const v = digits ? n.toFixed(digits) : String(Math.round(n));
  return n > 0 ? `+${v}` : v;
}

export function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

export function uid(prefix = "id") {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-3)}`;
}
