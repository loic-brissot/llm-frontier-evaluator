// Calendar (.ics) and structured workout (.zwo) exporters.

const pad = (n) => String(n).padStart(2, '0');

const escapeXml = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;');

/** ICS all-day event for a planned workout. */
export function toIcs(plan, { prodId = '-//Endurance Studio//Planner//EN' } = {}) {
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    `PRODID:${prodId}`,
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
  ];
  const stamp = icsStamp(new Date());
  for (const day of plan.days) {
    if (day.rest) continue;
    for (const w of day.workouts) {
      const d = day.date.replace(/-/g, '');
      const minutes = Math.round(w.durationSec / 60);
      const desc = [
        `${w.name} (${minutes} min)`,
        `Estimated TSS: ${Math.round(w.tss)}`,
        `Phase: ${day.phase} · Week ${day.week}`,
        '',
        ...w.profile.map((b) => `${fmtMin(b.start)}–${fmtMin(b.end)}  ${b.label} [${b.zone}]`),
      ].join('\\n');
      lines.push(
        'BEGIN:VEVENT',
        `UID:${w.id}@endurance-studio`,
        `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${d}`,
        `SUMMARY:${foldIcs(`${sportEmoji(w.sport)} ${w.name} · ${minutes}′`)}`,
        `DESCRIPTION:${foldIcs(desc)}`,
        'END:VEVENT',
      );
    }
  }
  lines.push('END:VCALENDAR');
  return lines.join('\r\n');
}

function icsStamp(d) {
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
}

function fmtMin(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m}:${pad(s)}` : `${m}′`;
}

// Sports emoji intentionally omitted from ICS text for client compatibility.
function sportEmoji() { return ''; }

// RFC 5545: escape commas/semicolons, fold long lines at 75 octets.
function foldIcs(text) {
  const escaped = text.replace(/\\n/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;');
  const out = [];
  let line = escaped;
  while (line.length > 75) {
    out.push(line.slice(0, 75));
    line = ' ' + line.slice(75);
  }
  out.push(line);
  return out.join('\r\n');
}

/**
 * Zwift/TrainingPeaks-compatible .zwo workout.
 * Power targets are fractions of FTP (`%`); run/swim sessions are exported with
 * a Zwift-compatible power proxy (IF) since .zwo is a power-based format.
 */
export function toZwo(workout, profile) {
  const ftp = profile.ftp || 250;
  const steps = [];
  for (const b of workout.blocks) {
    if (b.type === 'repeat') {
      steps.push(`    <IntervalsT Repeat="${b.reps}" OnDuration="${b.work.sec}" OffDuration="${b.rest.sec}" OnPower="${pctOf(b.work.zone)}" OffPower="${pctOf(b.rest.zone)}" Name="${escapeXml(b.work.label)}"/>`);
    } else if (b.type === 'warm') {
      steps.push(`    <Warmup Duration="${b.sec}" PowerLow="0.45" PowerHigh="0.7"/>`);
    } else if (b.type === 'cool') {
      steps.push(`    <Cooldown Duration="${b.sec}" PowerLow="0.7" PowerHigh="0.4"/>`);
    } else if (b.type === 'work') {
      steps.push(`    <SteadyState Duration="${b.sec}" Power="${pctOf(b.zone)}" Name="${escapeXml(b.label || 'Work')}"/>`);
    }
  }
  return `<?xml version="1.0" encoding="UTF-8"?>
<workout_file>
  <author>Endurance Studio</author>
  <name>${escapeXml(workout.name)}</name>
  <description>${escapeXml(`Estimated TSS ${Math.round(workout.tss)} · FTP ${ftp}W`)}</description>
  <sportType>${workout.kind === 'run' ? 'run' : 'bike'}</sportType>
  <!-- .zwo is a power-based format. Run/swim targets are exported as IF-relative
       steps and should be interpreted against threshold pace / CSS, not watts. -->
  <tags/>
  <workout>
${steps.join('\n')}
  </workout>
</workout_file>
`;

  function pctOf(zone) {
    const map = { 1: 0.5, 2: 0.65, 3: 0.82, 3.5: 0.88, 4: 0.97, 5: 1.12, 6: 1.3, 7: 1.6, 'E': 0.65, 'T': 0.88, 'I': 1.0, 'R': 1.1, 'S': 0.6 };
    return (map[zone] ?? 0.65).toFixed(2);
  }
}
