/* ═══════════════════════════════════════════════════════════════
   export.js — structured workout export
   · .ics  calendar events (any session)
   · .zwo  Zwift structured workout XML (bike & run sessions)
   ═══════════════════════════════════════════════════════════════ */
'use strict';

const Exporter = (() => {

  const escXML = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                               .replace(/"/g, '&quot;');
  const escICS = s => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;')
                               .replace(/,/g, '\\,').replace(/\n/g, '\\n');

  function download(filename, content, mime) {
    const blob = new Blob([content], { type: mime || 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
  }

  /* ── .ics ───────────────────────────────────────────────── */
  const icsDate = d =>
    `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;

  function describe(session, profile) {
    const lines = [`${session.name} · ${session.durMin} min · TSS ${session.tss}`];
    session.segments.forEach(g => {
      const sp = g.sport || session.sport;
      const dur = g.durMin < 1 ? Math.round(g.durMin * 60) + 's' : g.durMin + 'min';
      let tgt = g.label;
      if (sp === 'bike') tgt = `${g.label} @ ${Math.round(g.intensity * profile.ftp)}W (${Math.round(g.intensity * 100)}% FTP)`;
      if (sp === 'run')  tgt = `${g.label} @ ${Physio.fmtPace(profile.run.thresholdPaceSec / g.intensity)}/km`;
      if (sp === 'swim') tgt = `${g.label} @ ${Physio.fmtPace(profile.swim.cssSecPer100 / g.intensity)}/100m`;
      lines.push(`- ${dur} ${tgt}`);
    });
    return lines.join('\n');
  }

  function toICS(sessionsWithDates, profile, calName) {
    let out = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//APEX LAB//Training Planner//EN',
               `X-WR-CALNAME:${escICS(calName)}`];
    for (const { date, session } of sessionsWithDates) {
      const weekend = date.getDay() === 0 || date.getDay() === 6;
      const hh = session.isRace ? 8 : weekend ? 9 : 7;
      const dt = `${icsDate(date)}T${String(hh).padStart(2, '0')}0000`;
      out.push('BEGIN:VEVENT',
        `UID:${session.id}-${icsDate(date)}@apexlab`,
        `DTSTAMP:${dt}`,
        `DTSTART:${dt}`,
        `DURATION:PT${Math.max(15, session.durMin)}M`,
        `SUMMARY:${escICS(session.name)}`,
        `DESCRIPTION:${escICS(describe(session, profile))}`,
        'END:VEVENT');
    }
    out.push('END:VCALENDAR');
    return out.join('\r\n');
  }

  /* ── .zwo (Zwift) ───────────────────────────────────────── */
  function toZWO(session, profile) {
    const sp = session.sport;
    const name = escXML(session.name);
    let body = '';
    const r3 = v => Math.round(v * 1000) / 1000;
    const sec = m => Math.round(m * 60);

    let i = 0;
    const segs = session.segments;
    while (i < segs.length) {
      const g = segs[i];
      const s = m => Math.max(5, sec(m));
      if (g.kind === 'wu') {
        body += `\t\t<Warmup Duration="${s(g.durMin)}" PowerLow="${r3(g.i0)}" PowerHigh="${r3(g.i1)}"/>\n`;
        i++;
      } else if (g.kind === 'cd') {
        body += `\t\t<Cooldown Duration="${s(g.durMin)}" PowerLow="${r3(g.i1)}" PowerHigh="${r3(g.i0)}"/>\n`;
        i++;
      } else if (g.reps && g.rep === 1) {                    // gather the whole set
        const on = g.durMin, onI = g.intensity;
        const off = segs[i + 1]?.kind === 'recover' ? segs[i + 1].durMin : 3;
        const offI = segs[i + 1]?.intensity ?? 0.55;
        body += `\t\t<IntervalsT Repeat="${g.reps}" OnDuration="${s(on)}" OffDuration="${s(off)}" OnPower="${r3(onI)}" OffPower="${r3(offI)}"/>\n`;
        i += (g.reps - 1) * 2 + 1;
      } else {
        body += `\t\t<SteadyState Duration="${s(g.durMin)}" Power="${r3(g.intensity)}"/>\n`;
        i++;
      }
    }

    const sportTag = sp === 'run' ? 'run' : 'bike';
    const note = sp === 'run'
      ? 'Power values are fractions of threshold PACE — follow pace targets in description.'
      : `Power values are fractions of FTP (${profile.ftp} W).`;
    return `<workout_file>
\t<author>APEX LAB</author>
\t<name>${name}</name>
\t<description>${escXML(describe(session, profile))}\n${escXML(note)}</description>
\t<sportType>${sportTag}</sportType>
\t<workout>
${body}\t</workout>
</workout_file>`;
  }

  return { download, toICS, toZWO, describe };
})();
