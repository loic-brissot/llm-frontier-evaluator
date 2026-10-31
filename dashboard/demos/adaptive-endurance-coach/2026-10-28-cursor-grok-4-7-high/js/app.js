import { DISCIPLINES, EVENTS, RACE_DISTANCES, defaultProfile, disciplineById, emptyAdaptations, eventById } from "./catalog.js";
import { renderPMC, renderProfile } from "./chart.js";
import { downloadText, sessionsToIcs, slug, workoutToZwo } from "./export.js";
import {
  addDaysISO,
  diffDays,
  esc,
  fmtISO,
  formatClock,
  formatDay,
  formatDuration,
  formatHM,
  formatPace,
  formatRange,
  formatSwimPace,
  parseClock,
  signed,
  uid,
} from "./format.js";
import { buildStudio, groupPrescription, lineCue } from "./plan.js";
import { formLabel, predictSeconds } from "./physio.js";

const ZONE_COLORS = ["#6d7568", "#8aa56a", "#dff25a", "#e6c27a", "#ffb088", "#ff5c39", "#d7c4ff"];
const SPORT_NAME = { swim: "Swim", bike: "Bike", run: "Run", strength: "Strength", brick: "Brick", race: "Race" };

const state = {
  view: "load",
  profile: defaultProfile(),
  adaptations: emptyAdaptations(),
  studio: null,
  error: "",
  formError: "",
  selectedId: null,
  overlay: true,
  showCtl: true,
  showAtl: true,
  showTsb: true,
};

function todayISO() {
  return fmtISO(new Date());
}

function model() {
  return state.studio?.adapted || null;
}

function recompute() {
  const next = buildStudio(state.profile, state.adaptations);
  if (next.ok) {
    state.studio = next;
    state.error = "";
    ensureSelection();
  } else {
    state.error = next.error;
  }
}

function ensureSelection() {
  const sessions = model()?.sessions || [];
  if (state.selectedId && sessions.some((s) => s.id === state.selectedId)) return;
  const pick = sessions.find((s) => s.kind === "sweet" || s.role === "intensity") || sessions.find((s) => s.role !== "race");
  state.selectedId = pick?.id || sessions[0]?.id || null;
}

function persist() {
  try {
    localStorage.setItem("apogee.v1", JSON.stringify({
      view: state.view,
      profile: state.profile,
      adaptations: state.adaptations,
      overlay: state.overlay,
    }));
  } catch {
    /* private mode */
  }
}

function boot() {
  try {
    const raw = localStorage.getItem("apogee.v1");
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved.profile) state.profile = { ...defaultProfile(), ...saved.profile };
      if (saved.adaptations) {
        state.adaptations = {
          ...emptyAdaptations(),
          ...saved.adaptations,
          sessionEdits: saved.adaptations.sessionEdits || {},
          illnesses: saved.adaptations.illnesses || [],
          availability: saved.adaptations.availability || [],
        };
      }
      if (saved.view) state.view = saved.view;
      if (typeof saved.overlay === "boolean") state.overlay = saved.overlay;
    }
  } catch {
    /* ignore broken storage */
  }
  recompute();
  renderShell();
  bind();
  paint();
}

function renderShell() {
  document.getElementById("app").innerHTML = `
    <header class="top" id="top"></header>
    <div class="shell">
      <nav id="nav"></nav>
      <main id="main"></main>
    </div>
  `;
}

function paint() {
  renderHeader();
  renderNav();
  renderMain();
}

function renderHeader() {
  const studio = state.studio;
  const plan = model();
  const morning = plan?.raceMorning;
  const form = morning ? formLabel(morning.tsb) : null;
  const days = plan ? diffDays(todayISO(), studio.profile.race) : null;
  const dayLabel = days == null ? "—" : days > 0 ? `${days} days` : days === 0 ? "Today" : "Raced";
  document.getElementById("top").innerHTML = `
    <div class="brand">
      <div class="brand-mark">Apogee</div>
      <div class="brand-sub">Physiological studio</div>
    </div>
    <div class="identity-mini">
      <strong>${esc(state.profile.name || "Athlete")}</strong>
      <span> · ${esc(studio ? `${disciplineById(studio.profile.discipline).name} · ${studio.event.name}` : "Set a profile")}</span>
      ${state.studio?.active ? `<span class="adapted-dot" title="Adapted plan"></span>` : ""}
    </div>
    <div class="metrics">
      <div class="metric"><b>${esc(dayLabel)}</b><i>${esc(studio?.event.goal || "Race")}</i></div>
      <div class="metric lime"><b>${morning ? morning.ctl.toFixed(0) : "—"}</b><i>CTL</i></div>
      <div class="metric gilt"><b>${morning ? signed(morning.tsb, 0) : "—"}</b><i>${esc(form?.name || "Form")}</i></div>
    </div>
  `;
}

function renderNav() {
  const items = [
    ["profile", "01", "Profile"],
    ["zones", "02", "Zones"],
    ["plan", "03", "Plan"],
    ["load", "04", "Load"],
  ];
  document.getElementById("nav").innerHTML = items.map(([id, num, label]) => `
    <button class="nav-btn ${state.view === id ? "is-on" : ""}" data-view="${id}"><em>${num}</em><span>${label}</span></button>
  `).join("");
}

function renderMain() {
  const main = document.getElementById("main");
  const scroll = main.scrollTop;
  if (!state.studio) {
    main.innerHTML = `<p class="banner">${esc(state.error || "The profile needs a start date, a race day, and usable thresholds.")}</p>`;
    return;
  }
  const banner = state.error ? `<p class="banner">${esc(state.error)} The last valid plan is still on screen.</p>` : "";
  if (state.view === "profile") main.innerHTML = banner + profileView();
  else if (state.view === "zones") main.innerHTML = banner + zonesView();
  else if (state.view === "plan") main.innerHTML = banner + planView();
  else main.innerHTML = banner + loadView();
  main.scrollTop = scroll;
  syncAllSliders();
  if (state.view === "load") mountChart();
}

function profileView() {
  const p = state.profile;
  return `
    <div class="profile-layout">
      <form id="profile-form" data-run="${esc(p.runMode)}" data-swim="${esc(p.swimMode)}">
        <div class="kicker">01 — Athlete</div>
        <h2>Thresholds, then the calendar.</h2>
        <p class="lede">Zones and workout targets are computed from these baselines. Weekly hours are a ceiling. The ramp cap will use less when more would spike load.</p>
        <div class="group">
          <div class="kicker group-label">Identity</div>
          <label class="field"><span>Name</span><input name="name" type="text" value="${esc(p.name)}" autocomplete="off"></label>
          <div class="choices">
            ${DISCIPLINES.map((d) => `
              <button type="button" class="choice ${p.discipline === d.id ? "is-on" : ""}" data-discipline="${d.id}">
                <b>${esc(d.name)}</b><small>${esc(d.line)}</small>
              </button>`).join("")}
          </div>
          <label class="field" style="margin-top:12px"><span>Event</span>
            <select name="eventId">
              ${(EVENTS[p.discipline] || []).map((event) => `<option value="${event.id}" ${event.id === p.eventId ? "selected" : ""}>${esc(event.name)}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="group">
          <div class="kicker group-label">Calendar</div>
          <div class="split">
            <label><span>Start</span><input name="start" type="date" value="${esc(p.start)}"></label>
            <label><span>Race day</span><input name="race" type="date" value="${esc(p.race)}"></label>
          </div>
        </div>
        <div class="group">
          <div class="kicker group-label">Thresholds</div>
          <div class="split three">
            <label><span>FTP watts</span><input name="ftpW" type="number" min="60" max="550" step="1" value="${esc(p.ftpW)}"></label>
            <label><span>Weight kg</span><input name="weightKg" type="number" min="40" max="160" step="0.1" value="${esc(p.weightKg)}"></label>
            <label><span>Threshold HR</span><input name="lthr" type="number" min="110" max="210" step="1" value="${esc(p.lthr)}"></label>
          </div>
          <p class="hint">Watt targets move with FTP. Training stress does not — TSS is a ratio of normalized work to threshold.</p>
          <div class="modes" style="margin-top:14px">
            <button type="button" class="mode-btn ${p.runMode === "race" ? "is-on" : ""}" data-run-mode="race">Recent race</button>
            <button type="button" class="mode-btn ${p.runMode === "vo2" ? "is-on" : ""}" data-run-mode="vo2">VO₂max</button>
          </div>
          <div class="race-fields split">
            <label><span>Distance</span>
              <select name="raceDistanceId">
                ${RACE_DISTANCES.map((d) => `<option value="${d.id}" ${d.id === p.raceDistanceId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}
              </select>
            </label>
            <label><span>Time</span><input name="raceTime" type="text" value="${esc(p.raceTime)}" placeholder="42:30"></label>
          </div>
          <label class="field vo2-field"><span>VO₂max, used as VDOT</span><input name="vo2max" type="number" min="20" max="90" step="0.1" value="${esc(p.vo2max)}"></label>
          <div class="modes">
            <button type="button" class="mode-btn ${p.swimMode === "pace" ? "is-on" : ""}" data-swim-mode="pace">CSS pace</button>
            <button type="button" class="mode-btn ${p.swimMode === "test" ? "is-on" : ""}" data-swim-mode="test">200 / 400 test</button>
          </div>
          <label class="field pace-field"><span>CSS /100m</span><input name="cssPace" type="text" value="${esc(p.cssPace)}" placeholder="1:38"></label>
          <div class="test-fields split">
            <label><span>200 m</span><input name="t200" type="text" value="${esc(p.t200)}" placeholder="3:05"></label>
            <label><span>400 m</span><input name="t400" type="text" value="${esc(p.t400)}" placeholder="6:28"></label>
          </div>
          <p class="hint">CSS (m/s) = (400 − 200) / (T400 − T200).</p>
        </div>
        <div class="group">
          <div class="kicker group-label">Availability</div>
          ${slider("weeklyHours", "Hours / week", p.weeklyHours, 3, 25, 0.5)}
          ${slider("sessionsPerWeek", "Sessions / week", p.sessionsPerWeek, 3, 12, 1)}
          ${slider("rampCap", "Ramp cap, CTL / week", p.rampCap, 2, 8, 0.5)}
          <button type="button" class="text-btn" data-act="reset-athlete">Restore the sample athlete</button>
        </div>
      </form>
      <aside class="sheet" id="readout">${readoutHTML()}</aside>
    </div>
  `;
}

function slider(name, label, value, min, max, step) {
  const shown = step < 1 ? Number(value).toFixed(1) : String(value);
  return `
    <div class="slider">
      <div class="slider-head"><span class="kicker">${esc(label)}</span><output>${esc(shown)}</output></div>
      <input type="range" name="${name}" min="${min}" max="${max}" step="${step}" value="${esc(value)}">
    </div>
  `;
}

function readoutHTML() {
  const studio = state.studio;
  if (!studio) return `<p>${esc(state.error || "")}</p>`;
  const phys = studio.phys;
  const plan = studio.adapted;
  const morning = plan.raceMorning;
  const form = formLabel(morning.tsb);
  const preds = [5000, 10000, 21097.5, 42195].map((meters, i) => {
    const name = ["5K", "10K", "Half", "Marathon"][i];
    return `${name} ${formatHM(predictSeconds(phys.vdot, meters))}`;
  }).join(" · ");
  return `
    <div class="kicker">${esc(studio.event.goal)} sheet</div>
    <h1>${esc(studio.profile.name)}</h1>
    <div class="event-line">${esc(disciplineById(studio.profile.discipline).name)} · ${esc(studio.event.name)} · ${plan.weeks.length} weeks</div>
    <div class="stat-grid">
      <div><span>FTP</span><b>${phys.ftp} W · ${phys.wkg.toFixed(2)} W/kg</b></div>
      <div><span>${esc(phys.wkgBand)}</span><b>power band</b></div>
      <div><span>VDOT · ${esc(phys.vdotSource)}</span><b>${phys.vdot.toFixed(1)}</b></div>
      <div><span>Threshold HR</span><b>${phys.lthr} bpm</b></div>
      <div><span>CSS · ${esc(phys.cssSource)}</span><b>${formatSwimPace(phys.cssSec)} · ${phys.cssMps.toFixed(2)} m/s</b></div>
      <div><span>${esc(form.name)}</span><b>TSB ${signed(morning.tsb, 0)}</b></div>
    </div>
    ${spark(plan.pmc)}
    <p class="narrative">${esc(plan.narrative)}</p>
    <p class="formula">${esc(preds)}</p>
  `;
}

function spark(pmc) {
  if (!pmc?.length) return "";
  const w = 360;
  const h = 72;
  const values = pmc.map((row) => row.ctl);
  const max = Math.max(...values);
  const min = Math.min(...values) * 0.92;
  const x = (i) => (i / Math.max(1, pmc.length - 1)) * w;
  const y = (v) => h - ((v - min) / (max - min || 1)) * (h - 10) - 4;
  const d = values.map((v, i) => `${i ? "L" : "M"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}"/></svg>`;
}

function zonesView() {
  const phys = state.studio.phys;
  const paces = phys.paces;
  const paceCards = [
    ["E", "Easy", `${formatPace(paces.easy[0]).replace("/km", "")}–${formatPace(paces.easy[1])}`, "63–74% VO₂"],
    ["M", "Marathon", formatPace(paces.marathon), "82% VO₂"],
    ["T", "Threshold", formatPace(paces.threshold), "88% VO₂"],
    ["I", "Interval", formatPace(paces.interval), "97.5% VO₂"],
    ["R", "Repetition", `${formatPace(paces.repetition)} · ${formatClock(paces.repetition400)}/400`, "106% vVO₂"],
  ];
  return `
    <div class="kicker">02 — Zones</div>
    <h1>Four rulers, one athlete.</h1>
    <p class="lede">Coggan power from FTP. Daniels paces from the oxygen-cost curve. Friel heart-rate zones from threshold HR. Swim paces from critical speed.</p>
    ${zoneBlock("Cycling power", `${phys.ftp} W · ${phys.wkg.toFixed(2)} W/kg · ${phys.wkgBand}`, phys.power, (zone) => wattLabel(zone), (zone) => pctLabel(zone), 1.7)}
    <section class="zone-block">
      <div class="zone-head">
        <div>
          <div class="kicker">Running pace</div>
          <h2>VDOT ${phys.vdot.toFixed(1)}</h2>
          <p>${esc(phys.vdotSource)}. Easy through repetition, derived from the Daniels oxygen curve. Repetition sits above VO₂max, at 106% of vVO₂.</p>
        </div>
      </div>
      <div class="pace-row">
        ${paceCards.map(([id, name, pace, frac]) => `<div><span>${id} · ${esc(name)}</span><b>${esc(pace)}</b><small>${esc(frac)}</small></div>`).join("")}
      </div>
    </section>
    ${zoneBlock("Heart rate · bike", `Threshold ${phys.lthr} bpm · Friel`, phys.hr.bike, hrLabel, pctLabel, 1.15)}
    ${zoneBlock("Heart rate · run", `Same threshold, run cut-points`, phys.hr.run, hrLabel, pctLabel, 1.15)}
    ${zoneBlock("Swim pace", `${formatSwimPace(phys.cssSec)} · ${phys.cssMps.toFixed(2)} m/s`, phys.swim, swimLabel, (zone) => pctLabel(zone, "CSS"), 0.55, 0.7)}
    <p class="formula">
      IF = NP / FTP &nbsp;·&nbsp; TSS = hours × IF² × 100<br>
      rTSS uses the same shape against threshold pace.<br>
      CSS = (400 − 200) / (T₄₀₀ − T₂₀₀) &nbsp;·&nbsp; sTSS = IF³ × hours × 100, IF = speed / CSS<br>
      CTLₜ = CTLₜ₋₁ + (TSSₜ − CTLₜ₋₁) / 42 &nbsp;·&nbsp; ATLₜ = ATLₜ₋₁ + (TSSₜ − ATLₜ₋₁) / 7 &nbsp;·&nbsp; TSB = CTL − ATL
    </p>
  `;
}

function zoneBlock(kicker, title, zones, abs, pct, span, origin = 0) {
  const ruler = zones.map((zone, index) => {
    const hi = zone.hi == null ? origin + span : zone.hi;
    const lo = Math.max(zone.lo, origin);
    const width = Math.max(2, ((Math.min(hi, origin + span) - lo) / span) * 100);
    return `<i style="width:${width}%;background:${ZONE_COLORS[index % ZONE_COLORS.length]}" title="${esc(zone.name)}"></i>`;
  }).join("");
  const rows = zones.map((zone, index) => `
    <tr>
      <td><i class="swatch" style="background:${ZONE_COLORS[index % ZONE_COLORS.length]}"></i>${esc(zone.id)}</td>
      <td>${esc(zone.name)}</td>
      <td class="num">${esc(abs(zone))}</td>
      <td class="num">${esc(pct(zone))}</td>
    </tr>
  `).join("");
  return `
    <section class="zone-block">
      <div class="zone-head">
        <div><div class="kicker">${esc(kicker)}</div><h2>${esc(title)}</h2></div>
      </div>
      <div class="ruler">${ruler}</div>
      <table class="zone-table">
        <thead><tr><th>Zone</th><th>Name</th><th>Target</th><th>Range</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>
  `;
}

function wattLabel(zone) {
  if (zone.openLow) return `< ${zone.absHi} W`;
  if (zone.hi == null) return `${zone.absLo} W+`;
  return `${zone.absLo}–${zone.absHi} W`;
}
function hrLabel(zone) {
  if (zone.openLow) return `< ${zone.absHi} bpm`;
  if (zone.hi == null) return `${zone.absLo}+ bpm`;
  return `${zone.absLo}–${zone.absHi} bpm`;
}
function swimLabel(zone) {
  return `${formatSwimPace(zone.absHi)} – ${formatSwimPace(zone.absLo)}`;
}
function pctLabel(zone, unit = "FTP") {
  if (zone.openLow) return `< ${Math.round(zone.hi * 100)}% ${unit}`;
  if (zone.hi == null) return `> ${Math.round(zone.lo * 100)}%`;
  return `${Math.round(zone.lo * 100)}–${Math.round(zone.hi * 100)}%`;
}

function planView() {
  const plan = model();
  const counts = {};
  for (const week of plan.weeks) counts[week.phaseName] = (counts[week.phaseName] || 0) + 1;
  const summary = Object.entries(counts).map(([name, n]) => `${name} ${n}`).join(" · ");
  return `
    <div class="plan-head">
      <div>
        <div class="kicker">03 — Plan</div>
        <h1>${plan.weeks.length} weeks to ${esc(state.studio.event.goal.toLowerCase())}.</h1>
        <div class="phase-count">${esc(summary)}</div>
      </div>
      <button type="button" class="export" data-act="ics-plan">Download calendar</button>
    </div>
    <div class="plan-layout">
      <div class="weeks">
        ${plan.weeks.map((week) => weekHTML(week, plan)).join("")}
      </div>
      <aside class="stage" id="stage">${stageHTML()}</aside>
    </div>
  `;
}

function weekHTML(week, plan) {
  const raceWeek = week.dates.includes(state.studio.profile.race);
  const tsb = raceWeek ? plan.raceMorning.tsb : week.tsbEnd;
  return `
    <article class="week" data-phase="${week.phase}">
      <div class="week-meta">
        <div class="week-index">${String(week.index + 1).padStart(2, "0")}</div>
        <div>
          <div class="week-phase">${esc(week.phaseName)}</div>
          <div class="week-dates">${esc(formatRange(week.start, week.end))}</div>
        </div>
        <div class="week-stats">
          <span>${week.hours.toFixed(1)} h</span>
          <span>${Math.round(week.trainingTSS)} TSS</span>
          <span>${signed(week.ramp, 1)} CTL</span>
          <span>${raceWeek ? "morning " : ""}${signed(tsb, 0)}</span>
        </div>
      </div>
      <div class="week-track">
        ${week.sessions.map((session) => clipHTML(session)).join("")}
      </div>
      ${(week.notes || []).map((note) => `<p class="week-note">${esc(note)}</p>`).join("")}
    </article>
  `;
}

function clipHTML(session) {
  const width = Math.round(Math.max(118, Math.min(230, (session.minutes || 28) * 1.45)));
  const status = session.status && session.status !== "planned" && session.status !== "race" ? session.status : "";
  return `
    <button type="button" class="clip ${session.id === state.selectedId ? "is-on" : ""}" data-select="${esc(session.id)}" data-sport="${esc(session.sport)}" data-status="${esc(session.status)}" style="width:${width}px">
      <span class="clip-kicker">${esc(SPORT_NAME[session.sport] || session.sport)} · ${session.minutes ? `${Math.round(session.minutes)}m` : esc(status || "rest")}</span>
      <span class="clip-name">${esc(session.name)}</span>
      <span class="clip-profile">${renderProfile(session.intervals, { mini: true })}</span>
      <span class="clip-tss">${session.tss ? `${Math.round(session.tss)} TSS` : esc(status || "—")}</span>
    </button>
  `;
}

function wasLine(now, then, withSign = false) {
  if (!state.studio?.active) return "";
  if (Number(now).toFixed(0) === Number(then).toFixed(0)) return "";
  const text = withSign ? signed(then, 0) : Number(then).toFixed(0);
  return ` · was ${text}`;
}

function profileTags(intervals) {
  if (!intervals?.length) return "";
  const total = intervals.reduce((sum, iv) => sum + iv.sec, 0) || 1;
  let cursor = 0;
  const tags = [];
  for (const iv of intervals) {
    const start = cursor;
    cursor += iv.sec;
    const share = iv.sec / total;
    if (share < 0.2 || iv.sec < 180) continue;
    if (iv.kind !== "work" && iv.kind !== "strength") continue;
    const mid = ((iv.i0 ?? 0) + (iv.i1 ?? iv.i0 ?? 0)) / 2;
    const ink = mid >= 0.84 ? "#14160f" : "#f4f1e6";
    const left = ((start + iv.sec / 2) / total) * 100;
    tags.push(`<b style="left:${left.toFixed(1)}%;color:${ink}">${esc(iv.label)}</b>`);
  }
  return tags.length ? `<div class="profile-tags">${tags.join("")}</div>` : "";
}

function structureKey(profile) {
  return `${profile.discipline}|${profile.eventId}|${profile.start}|${profile.race}`;
}

function stageHTML() {
  const session = model()?.sessions.find((s) => s.id === state.selectedId);
  if (!session) return `<p class="lede">Select a session.</p>`;
  const phys = state.studio.phys;
  const changed = session.plannedName && (session.plannedName !== session.name || Math.abs((session.plannedTSS || 0) - session.tss) > 1);
  const lines = groupPrescription(session.intervals || []).map((line) => {
    const head = line.parts[0];
    const rest = line.parts[1];
    const dur = formatClock(head.sec);
    const label = line.reps > 1 && rest
      ? `${line.reps} × ${dur} ${head.label} / ${formatClock(rest.sec)} ${rest.label.toLowerCase()}`
      : line.reps > 1
        ? `${line.reps} × ${dur} ${head.label}`
        : `${dur} ${head.label}`;
    const cue = `${lineCue(head, phys)}${rest ? ` / ${lineCue(rest, phys)}` : ""}`;
    return `<li><span class="when">${esc(label)}</span><span class="cue">${esc(cue)}</span></li>`;
  }).join("");
  const locked = session.role === "race";
  return `
    <div class="kicker">${esc(formatDay(session.date))} · ${esc(SPORT_NAME[session.sport] || session.sport)} · ${esc(session.phase)}</div>
    <h2>${esc(session.name)}</h2>
    <div class="stage-meta">${esc(formatDuration(session.minutes || 0))} · ${Math.round(session.tss)} TSS · IF ${Number(session.iff || 0).toFixed(2)}</div>
    <div class="profile-frame">${renderProfile(session.intervals)}${profileTags(session.intervals)}</div>
    ${lines ? `<ol class="rx">${lines}</ol>` : `<p class="lede">${esc(session.note || "")}</p>`}
    <p class="lede" style="margin-top:12px">${esc(session.note || "")}</p>
    ${changed ? `<p class="delta-line">Planned ${esc(session.plannedName)} · ${Math.round(session.plannedTSS)} TSS → now ${Math.round(session.tss)} TSS</p>` : ""}
    <div class="stage-actions">
      ${locked ? "" : `
        <button type="button" class="action" data-act="skip" data-id="${esc(session.id)}">Skip</button>
        <button type="button" class="action" data-act="shorten" data-id="${esc(session.id)}">Shorten by half</button>
        <button type="button" class="action is-hot" data-act="overreach" data-id="${esc(session.id)}">Over-reached</button>
        <button type="button" class="text-btn" data-act="restore" data-id="${esc(session.id)}">Restore</button>
      `}
    </div>
    <div class="exports">
      <button type="button" class="export" data-act="ics-one" data-id="${esc(session.id)}">Export .ics</button>
      ${session.intervals?.length ? `<button type="button" class="export" data-act="zwo" data-id="${esc(session.id)}">Export .zwo</button>` : ""}
    </div>
  `;
}

function loadView() {
  const studio = state.studio;
  const plan = studio.adapted;
  const morning = plan.raceMorning;
  const form = formLabel(morning.tsb);
  const base = studio.original.raceMorning;
  return `
    <div class="kicker">04 — Load</div>
    <div class="load-head">
      <h1>Form, aimed at ${esc(studio.event.goal.toLowerCase())} morning.</h1>
    </div>
    <div class="hero">
      <div>
        <div class="kicker">${esc(studio.event.goal)}-morning TSB</div>
        <div class="hero-num ${morning.tsb < 0 ? "neg" : ""}">${signed(morning.tsb, 0)}</div>
        <div class="hero-name">${esc(form.name)}${wasLine(morning.tsb, base.tsb, true)}</div>
      </div>
      <div class="compare">
        <div><span>Chronic load</span><b>${morning.ctl.toFixed(0)}${wasLine(morning.ctl, base.ctl)}</b></div>
        <div><span>Acute load</span><b>${morning.atl.toFixed(0)}${wasLine(morning.atl, base.atl)}</b></div>
        <div><span>Peak CTL</span><b>${plan.stats.peakCtl.toFixed(0)} · ${esc(formatDay(plan.stats.peakCtlDate))}</b></div>
      </div>
    </div>
    <p class="narrative">${esc(plan.narrative)}</p>
    <div class="pmc-frame" id="pmc"></div>
    <div class="legend">
      <button type="button" class="toggle ${state.showCtl ? "is-on" : ""}" data-act="series" data-series="showCtl"><i class="sw ctl"></i> CTL · 42-day</button>
      <button type="button" class="toggle ${state.showAtl ? "is-on" : ""}" data-act="series" data-series="showAtl"><i class="sw atl"></i> ATL · 7-day</button>
      <button type="button" class="toggle ${state.showTsb ? "is-on" : ""}" data-act="series" data-series="showTsb"><i class="sw tsb"></i> TSB</button>
      <button type="button" class="toggle ${state.overlay && studio.active ? "is-on" : ""}" data-act="overlay" ${studio.active ? "" : "disabled"}><i class="sw ghost"></i> Original plan</button>
    </div>
    <div class="console">
      <section class="panel">
        <h3>Interventions</h3>
        <p>Skip, shorten, or over-reach a session on the plan. The days after recalibrate inside the ramp cap, and the taper is solved again for race morning.</p>
        ${interventionList()}
        ${state.studio.active ? `<button type="button" class="text-btn" data-act="reset-adapt">Clear adaptations</button>` : ""}
      </section>
      <section class="panel">
        <h3>Illness</h3>
        <p>Zero the days, then damp the return so the lost work is not crammed back in.</p>
        <div class="split">
          <label><span class="kicker">From</span><input id="ill-from" type="date" value="${esc(studio.profile.start)}"></label>
          <label><span class="kicker">Days</span>
            <select id="ill-days"><option>3</option><option selected>5</option><option>7</option><option>10</option><option>14</option></select>
          </label>
        </div>
        <button type="button" class="action" data-act="add-illness" style="margin-top:10px">Simulate illness</button>
      </section>
      <section class="panel">
        <h3>Availability</h3>
        <p>From a date forward, change the hour and session ceilings. Earlier weeks stay as trained.</p>
        <label class="field"><span>From</span><input id="avail-from" type="date" value="${esc(studio.profile.start)}"></label>
        ${slider("availHours", "Hours", 8, 3, 25, 0.5)}
        ${slider("availSessions", "Sessions", 6, 3, 12, 1)}
        <button type="button" class="action" data-act="add-availability">Apply availability</button>
        <p class="inline-error" id="form-error">${esc(state.formError)}</p>
      </section>
    </div>
    <p class="formula">CTLₜ = CTLₜ₋₁ + (TSSₜ − CTLₜ₋₁) / 42<br>ATLₜ = ATLₜ₋₁ + (TSSₜ − ATLₜ₋₁) / 7<br>TSBₜ = CTLₜ − ATLₜ</p>
  `;
}

function interventionList() {
  const edits = Object.entries(state.adaptations.sessionEdits || {});
  const items = [];
  for (const [id, edit] of edits) {
    const session = state.studio.original.sessions.find((s) => s.id === id);
    items.push(`<li><span>${esc(edit.mode)} · ${esc(session ? `${formatDay(session.date)} ${session.plannedName}` : id)}</span><button type="button" class="text-btn" data-act="restore" data-id="${esc(id)}">Undo</button></li>`);
  }
  state.adaptations.illnesses.forEach((ill, index) => {
    items.push(`<li><span>Illness · ${esc(formatDay(ill.from))} · ${esc(ill.days)} days</span><button type="button" class="text-btn" data-remove="illness" data-index="${index}">Remove</button></li>`);
  });
  state.adaptations.availability.forEach((row, index) => {
    items.push(`<li><span>From ${esc(formatDay(row.from))} · ${esc(row.weeklyHours)} h · ${esc(row.sessionsPerWeek)} sessions</span><button type="button" class="text-btn" data-remove="availability" data-index="${index}">Remove</button></li>`);
  });
  if (!items.length) return `<p class="hint">Nothing has been moved yet.</p>`;
  return `<ul class="log">${items.join("")}</ul>`;
}

function mountChart() {
  const host = document.getElementById("pmc");
  if (!host || !state.studio) return;
  const picture = renderPMC({
    adapted: state.studio.adapted.pmc,
    original: state.studio.original.pmc,
    overlay: state.overlay && state.studio.active,
    race: state.studio.profile.race,
    goal: state.studio.event.goal,
    today: todayISO(),
    showCtl: state.showCtl,
    showAtl: state.showAtl,
    showTsb: state.showTsb,
    illness: (state.adaptations.illnesses || []).map((ill) => ({
      start: ill.from,
      end: addDaysISO(ill.from, Number(ill.days) - 1),
    })),
  });
  host.innerHTML = `${picture.svg}<div class="cross" hidden></div><div class="tip" hidden></div>`;
  host._layout = picture.layout;
  host._rows = state.studio.adapted.pmc;
  host._original = state.studio.original.pmc;
}

function onChartMove(event) {
  const host = event.target.closest?.("#pmc");
  if (!host || !host._layout) return;
  const tip = host.querySelector(".tip");
  const cross = host.querySelector(".cross");
  const rect = host.getBoundingClientRect();
  const layout = host._layout;
  const rel = (event.clientX - rect.left) / rect.width;
  const vbX = rel * layout.W;
  if (vbX < layout.m.l || vbX > layout.W - layout.m.r) {
    tip.hidden = true;
    cross.hidden = true;
    return;
  }
  const span = layout.W - layout.m.l - layout.m.r;
  let index = Math.round(((vbX - layout.m.l) / span) * (layout.n - 1));
  index = Math.max(0, Math.min(layout.n - 1, index));
  const row = host._rows[index];
  const orig = host._original?.[index];
  const form = formLabel(row.tsb);
  const left = ((layout.x(index) / layout.W) * rect.width);
  cross.hidden = false;
  cross.style.left = `${left}px`;
  tip.hidden = false;
  const showOrig = state.overlay && state.studio.active && orig;
  tip.innerHTML = `
    <b>${esc(formatDay(row.date))}</b>
    <em>${esc(row.phase)} · ${esc(form.name)}</em>
    <table>
      <tr><td>TSS</td><td>${Math.round(row.tss)}</td>${showOrig ? `<td>${Math.round(orig.tss)}</td>` : ""}</tr>
      <tr><td>CTL</td><td>${row.ctl.toFixed(1)}</td>${showOrig ? `<td>${orig.ctl.toFixed(1)}</td>` : ""}</tr>
      <tr><td>ATL</td><td>${row.atl.toFixed(1)}</td>${showOrig ? `<td>${orig.atl.toFixed(1)}</td>` : ""}</tr>
      <tr><td>TSB</td><td>${signed(row.tsb, 1)}</td>${showOrig ? `<td>${signed(orig.tsb, 1)}</td>` : ""}</tr>
    </table>
  `;
  const tipW = 210;
  let tipLeft = left + 14;
  if (tipLeft + tipW > rect.width) tipLeft = left - tipW - 8;
  tip.style.left = `${Math.max(8, tipLeft)}px`;
  tip.style.top = "48px";
}

function hideChartTip(event) {
  const host = document.getElementById("pmc");
  if (!host) return;
  if (event && event.relatedTarget && host.contains(event.relatedTarget)) return;
  host.querySelector(".tip")?.setAttribute("hidden", "");
  host.querySelector(".cross")?.setAttribute("hidden", "");
}

function readProfileForm() {
  const form = document.getElementById("profile-form");
  if (!form) return;
  const value = (name) => form.querySelector(`[name="${name}"]`)?.value;
  const p = state.profile;
  const before = structureKey(p);
  p.name = value("name") ?? p.name;
  p.eventId = value("eventId") || p.eventId;
  p.start = value("start") || p.start;
  p.race = value("race") || p.race;
  for (const key of ["ftpW", "weightKg", "lthr", "vo2max", "weeklyHours", "sessionsPerWeek", "rampCap"]) {
    const n = Number(value(key));
    if (Number.isFinite(n)) p[key] = n;
  }
  p.raceDistanceId = value("raceDistanceId") || p.raceDistanceId;
  const raceTime = value("raceTime");
  if (raceTime && parseClock(raceTime)) p.raceTime = raceTime.trim();
  const cssPace = value("cssPace");
  if (cssPace && parseClock(cssPace)) p.cssPace = cssPace.trim();
  const t200 = value("t200");
  const t400 = value("t400");
  if (t200 && parseClock(t200)) p.t200 = t200.trim();
  if (t400 && parseClock(t400)) p.t400 = t400.trim();
  if (structureKey(p) !== before) state.adaptations.sessionEdits = {};
}

function syncSlider(input) {
  if (!input || input.type !== "range") return;
  const min = Number(input.min);
  const max = Number(input.max);
  const val = Number(input.value);
  const pct = ((val - min) / (max - min)) * 100;
  input.style.setProperty("--p", `${pct}%`);
  const out = input.parentElement?.querySelector("output");
  if (out) out.textContent = Number(input.step) < 1 ? val.toFixed(1) : String(Math.round(val));
}

function syncAllSliders() {
  document.querySelectorAll('input[type="range"]').forEach(syncSlider);
}

function refreshAfterEdit(options = {}) {
  recompute();
  persist();
  renderHeader();
  if (state.view === "profile" && !options.rebuildForm) {
    const readout = document.getElementById("readout");
    if (readout) readout.innerHTML = readoutHTML();
    return;
  }
  const main = document.getElementById("main");
  const scroll = main ? main.scrollTop : 0;
  renderMain();
  if (main) document.getElementById("main").scrollTop = scroll;
}

function setSessionEdit(id, mode) {
  if (!id) return;
  if (mode) state.adaptations.sessionEdits[id] = { mode };
  else delete state.adaptations.sessionEdits[id];
  refreshAfterEdit();
}

function bind() {
  const app = document.getElementById("app");
  app.addEventListener("click", (event) => {
    const view = event.target.closest("[data-view]");
    if (view) {
      state.view = view.dataset.view;
      persist();
      renderNav();
      renderMain();
      return;
    }
    const discipline = event.target.closest("[data-discipline]");
    if (discipline) {
      state.profile.discipline = discipline.dataset.discipline;
      state.adaptations.sessionEdits = {};
      const events = EVENTS[state.profile.discipline];
      if (!events.some((item) => item.id === state.profile.eventId)) state.profile.eventId = events[0].id;
      refreshAfterEdit({ rebuildForm: true });
      return;
    }
    const runMode = event.target.closest("[data-run-mode]");
    if (runMode) {
      state.profile.runMode = runMode.dataset.runMode;
      document.getElementById("profile-form").dataset.run = state.profile.runMode;
      document.querySelectorAll("[data-run-mode]").forEach((btn) => btn.classList.toggle("is-on", btn.dataset.runMode === state.profile.runMode));
      refreshAfterEdit();
      return;
    }
    const swimMode = event.target.closest("[data-swim-mode]");
    if (swimMode) {
      state.profile.swimMode = swimMode.dataset.swimMode;
      document.getElementById("profile-form").dataset.swim = state.profile.swimMode;
      document.querySelectorAll("[data-swim-mode]").forEach((btn) => btn.classList.toggle("is-on", btn.dataset.swimMode === state.profile.swimMode));
      refreshAfterEdit();
      return;
    }
    const select = event.target.closest("[data-select]");
    if (select) {
      state.selectedId = select.dataset.select;
      document.querySelectorAll(".clip").forEach((clip) => clip.classList.toggle("is-on", clip.dataset.select === state.selectedId));
      const stage = document.getElementById("stage");
      if (stage) stage.innerHTML = stageHTML();
      return;
    }
    const act = event.target.closest("[data-act]");
    if (act) handleAction(act);
    const remove = event.target.closest("[data-remove]");
    if (remove) {
      const index = Number(remove.dataset.index);
      state.adaptations[remove.dataset.remove === "illness" ? "illnesses" : "availability"].splice(index, 1);
      refreshAfterEdit();
    }
  });
  let profileTimer = 0;
  const queueProfile = () => {
    clearTimeout(profileTimer);
    profileTimer = setTimeout(() => {
      readProfileForm();
      refreshAfterEdit();
    }, 60);
  };
  app.addEventListener("input", (event) => {
    syncSlider(event.target);
    if (event.target.closest("#profile-form")) queueProfile();
  });
  app.addEventListener("change", (event) => {
    if (event.target.closest("#profile-form")) queueProfile();
  });
  app.addEventListener("submit", (event) => event.preventDefault());
  app.addEventListener("mousemove", onChartMove);
  app.addEventListener("mouseout", (event) => {
    if (event.target.closest?.("#pmc") && !event.relatedTarget?.closest?.("#pmc")) hideChartTip(event);
  });
}

function handleAction(node) {
  const act = node.dataset.act;
  const id = node.dataset.id;
  if (act === "skip" || act === "shorten" || act === "overreach") setSessionEdit(id, act === "shorten" ? "shorten" : act === "overreach" ? "overreach" : "skip");
  else if (act === "restore") setSessionEdit(id, null);
  else if (act === "reset-adapt") {
    state.adaptations = emptyAdaptations();
    state.formError = "";
    refreshAfterEdit();
  } else if (act === "reset-athlete") {
    state.profile = defaultProfile();
    state.adaptations = emptyAdaptations();
    state.error = "";
    refreshAfterEdit({ rebuildForm: true });
  } else if (act === "overlay") {
    if (!state.studio.active) return;
    state.overlay = !state.overlay;
    persist();
    renderMain();
  } else if (act === "series") {
    const key = node.dataset.series;
    state[key] = !state[key];
    renderMain();
  } else if (act === "ics-plan") {
    const sessions = model().sessions.filter((s) => s.tss > 0 && s.status !== "dropped");
    downloadText(`${slug(state.profile.name)}-plan.ics`, sessionsToIcs(sessions, state.studio.profile, state.studio.phys), "text/calendar");
  } else if (act === "ics-one") {
    const session = model().sessions.find((s) => s.id === id);
    if (session) downloadText(`${slug(session.name)}.ics`, sessionsToIcs([session], state.studio.profile, state.studio.phys), "text/calendar");
  } else if (act === "zwo") {
    const session = model().sessions.find((s) => s.id === id);
    if (session) downloadText(`${slug(session.name)}.zwo`, workoutToZwo(session, state.studio.profile, state.studio.phys), "application/xml");
  } else if (act === "add-illness") {
    const from = document.getElementById("ill-from")?.value;
    const days = Number(document.getElementById("ill-days")?.value || 5);
    const { start, race } = state.studio.profile;
    if (!from || from > race || addDaysISO(from, days - 1) < start) {
      state.formError = "Illness has to overlap the plan.";
      const slot = document.getElementById("form-error");
      if (slot) slot.textContent = state.formError;
      return;
    }
    state.formError = "";
    state.adaptations.illnesses.push({ id: uid("ill"), from, days });
    refreshAfterEdit();
  } else if (act === "add-availability") {
    const from = document.getElementById("avail-from")?.value;
    const hours = Number(document.querySelector('[name="availHours"]')?.value);
    const sessions = Number(document.querySelector('[name="availSessions"]')?.value);
    const { start, race } = state.studio.profile;
    if (!from || from < start || from > race) {
      state.formError = "Pick a date inside the plan.";
      const slot = document.getElementById("form-error");
      if (slot) slot.textContent = state.formError;
      return;
    }
    state.formError = "";
    state.adaptations.availability.push({
      id: uid("avail"),
      from,
      weeklyHours: hours,
      sessionsPerWeek: sessions,
    });
    refreshAfterEdit();
  }
}

boot();
