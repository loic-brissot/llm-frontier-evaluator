/** Calendar (.ics) and Zwift workout (.zwo) export. */

import { cueForInterval, hrCue } from "./physio.js";
import { addDaysISO, parseISO } from "./format.js";

function xmlEscape(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cdata(value) {
  return String(value ?? "").replace(/]]>/g, "]]&gt;");
}

function powerOf(iv) {
  const a = Math.max(0, iv.i0 ?? 0);
  const b = Math.max(0, iv.i1 ?? a);
  return [Number(a.toFixed(3)), Number(b.toFixed(3))];
}

function sportType(session) {
  if (session.sport === "run") return "run";
  if (session.sport === "bike" || session.sport === "brick") return "bike";
  return "other";
}

/**
 * Collapse a repeating work/recovery pair into IntervalsT.
 * Everything else becomes Warmup, Cooldown, Ramp, or SteadyState.
 */
function zwoBody(intervals, phys) {
  const chunks = [];
  let i = 0;
  const same = (a, b) =>
    a &&
    b &&
    a.kind === b.kind &&
    a.label === b.label &&
    Math.abs(a.sec - b.sec) <= 1 &&
    Math.abs((a.i0 ?? 0) - (b.i0 ?? 0)) < 0.015 &&
    Math.abs((a.i1 ?? 0) - (b.i1 ?? 0)) < 0.015 &&
    Math.abs((a.i0 ?? 0) - (a.i1 ?? a.i0 ?? 0)) < 0.015 &&
    Math.abs((b.i0 ?? 0) - (b.i1 ?? b.i0 ?? 0)) < 0.015;

  while (i < intervals.length) {
    const a = intervals[i];
    const b = intervals[i + 1];
    if (
      b &&
      a.kind === "work" &&
      (b.kind === "recovery" || b.kind === "rest") &&
      Math.abs((a.i0 ?? 0) - (a.i1 ?? 0)) < 0.015 &&
      Math.abs((b.i0 ?? 0) - (b.i1 ?? 0)) < 0.015
    ) {
      let n = 1;
      while (same(intervals[i + n * 2], a) && same(intervals[i + n * 2 + 1], b)) n += 1;
      if (n >= 2) {
        const on = powerOf(a)[0];
        const off = powerOf(b)[0];
        const cadence = a.cadence ? ` Cadence="${a.cadence}"` : "";
        chunks.push(
          `    <IntervalsT Repeat="${n}" OnDuration="${a.sec}" OffDuration="${b.sec}" OnPower="${on}" OffPower="${off}"${cadence}>`,
        );
        const cue = cueForInterval(a, phys);
        const hr = hrCue(a, phys.lthr);
        chunks.push(`      <textevent timeoffset="0" message="${xmlEscape([a.label, cue, hr].filter(Boolean).join(" · "))}"/>`);
        chunks.push("    </IntervalsT>");
        i += n * 2;
        continue;
      }
    }
    const [lo, hi] = powerOf(a);
    const cadence = a.cadence ? ` Cadence="${a.cadence}"` : "";
    const cue = cueForInterval(a, phys);
    const hr = hrCue(a, phys.lthr);
    const message = xmlEscape([a.label, cue, hr].filter(Boolean).join(" · "));
    if (a.kind === "warmup" && Math.abs(lo - hi) >= 0.02) {
      chunks.push(`    <Warmup Duration="${a.sec}" PowerLow="${Math.min(lo, hi)}" PowerHigh="${Math.max(lo, hi)}"${cadence}>`);
      chunks.push(`      <textevent timeoffset="0" message="${message}"/>`);
      chunks.push("    </Warmup>");
    } else if (a.kind === "cooldown" && Math.abs(lo - hi) >= 0.02) {
      // Zwift cooldowns descend from PowerHigh to PowerLow.
      chunks.push(`    <Cooldown Duration="${a.sec}" PowerLow="${Math.min(lo, hi)}" PowerHigh="${Math.max(lo, hi)}">`);
      chunks.push(`      <textevent timeoffset="0" message="${message}"/>`);
      chunks.push("    </Cooldown>");
    } else if (Math.abs(lo - hi) >= 0.02) {
      chunks.push(`    <Ramp Duration="${a.sec}" PowerLow="${lo}" PowerHigh="${hi}"${cadence}>`);
      chunks.push(`      <textevent timeoffset="0" message="${message}"/>`);
      chunks.push("    </Ramp>");
    } else {
      chunks.push(`    <SteadyState Duration="${a.sec}" Power="${lo}"${cadence}>`);
      chunks.push(`      <textevent timeoffset="0" message="${message}"/>`);
      chunks.push("    </SteadyState>");
    }
    i += 1;
  }
  return chunks.join("\n");
}

export function workoutToZwo(session, profile, phys) {
  const description = [
    session.note,
    session.intervals.map((iv) => `${iv.label} ${iv.sec}s ${cueForInterval(iv, phys)}`).join(" | "),
    `Athlete ${profile.name}. Targets are fractions of threshold: FTP, Daniels T pace, or CSS.`,
  ].join("\n");
  const body = session.intervals.length
    ? zwoBody(session.intervals, phys)
    : `    <SteadyState Duration="60" Power="0.5"/>`;
  return `<?xml version="1.0" encoding="UTF-8"?>
<workout_file>
  <author>Apogee</author>
  <name>${xmlEscape(session.name)}</name>
  <description><![CDATA[${cdata(description)}]]></description>
  <sportType>${sportType(session)}</sportType>
  <tags>
    <tag name="APOGEE"/>
    <tag name="${xmlEscape(session.sport)}"/>
  </tags>
  <workout>
${body}
  </workout>
</workout_file>
`;
}

function icsStamp(iso, minutesFromMidnight) {
  const date = parseISO(iso);
  const h = Math.floor(minutesFromMidnight / 60);
  const m = minutesFromMidnight % 60;
  const y = date.getFullYear();
  const mo = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}${mo}${d}T${String(h).padStart(2, "0")}${String(m).padStart(2, "0")}00`;
}

function icsEscape(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function fold(line) {
  const out = [];
  let rest = line;
  while (rest.length > 73) {
    out.push(rest.slice(0, 73));
    rest = ` ${rest.slice(73)}`;
  }
  out.push(rest);
  return out.join("\r\n");
}

export function sessionsToIcs(sessions, profile, phys = null) {
  const events = sessions
    .filter((session) => session.status !== "dropped")
    .map((session) => {
      const startMin = session.sport === "swim" ? 6 * 60 : session.sport === "strength" ? 17 * 60 : 7 * 60;
      const dur = Math.max(session.minutes || 0, session.role === "race" ? 30 : 15);
      const crosses = startMin + dur >= 24 * 60;
      const untilDate = crosses ? addDaysISO(session.date, Math.floor((startMin + dur) / (24 * 60))) : session.date;
      const untilMin = crosses ? Math.round(startMin + dur) % (24 * 60) : Math.round(startMin + dur);
      const detail = phys
        ? session.intervals.slice(0, 8).map((iv) => `${iv.label}: ${cueForInterval(iv, phys)}`).join("\n")
        : "";
      const description = [
        session.note,
        `TSS ${Math.round(session.tss)} · IF ${Number(session.iff || 0).toFixed(2)}`,
        session.plannedName && session.plannedName !== session.name ? `Originally ${session.plannedName}` : "",
        detail,
      ].filter(Boolean).join("\n");
      return [
        "BEGIN:VEVENT",
        `UID:${icsEscape(session.id)}@apogee.studio`,
        `DTSTAMP:${icsStamp(session.date, 0)}`,
        `DTSTART:${icsStamp(session.date, startMin)}`,
        `DTEND:${icsStamp(untilDate, untilMin)}`,
        `SUMMARY:${icsEscape(`${session.name}`)}`,
        `DESCRIPTION:${icsEscape(description)}`,
        `CATEGORIES:${icsEscape(session.sport.toUpperCase())}`,
        "END:VEVENT",
      ].map(fold).join("\r\n");
    });
  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Apogee//Physiological Planning Studio//EN",
    "CALSCALE:GREGORIAN",
    `X-WR-CALNAME:${icsEscape(`${profile.name} · Apogee`)}`,
    ...events,
    "END:VCALENDAR",
    "",
  ].join("\r\n");
}

export function downloadText(filename, contents, mime) {
  const blob = new Blob([contents], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function slug(value) {
  return String(value || "workout")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}
