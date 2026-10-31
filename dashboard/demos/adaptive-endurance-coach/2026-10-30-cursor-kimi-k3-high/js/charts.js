/* ═══════════════════════════════════════════════════════════════
   charts.js — hand-rolled SVG visualisations
   · Performance Management Chart (CTL/ATL/TSB + daily TSS bars,
     original vs adapted overlay, hover crosshair)
   · Workout interval block profiles
   · Form (TSB) gauge
   ═══════════════════════════════════════════════════════════════ */
'use strict';

const Charts = (() => {

  const SPORT_COLOR = {
    bike: '#a78bfa', run: '#34d399', swim: '#38bdf8',
    strength: '#fbbf24', brick: '#f472b6', race: '#f43f5e',
  };

  const fmtDate = (d, opts) => d.toLocaleDateString('en-GB', opts || { day: 'numeric', month: 'short' });

  /* ─────────────────────────── PMC ─────────────────────────── */
  function pmc(el, tipEl, orig, adapt, dates, opts) {
    const W = 1060, H = 430, padL = 46, padR = 14, padT = 18, padB = 34;
    const n = dates.length;
    if (!n) { el.innerHTML = ''; return; }
    const iw = W - padL - padR, ih = H - padT - padB;

    const series = adapt || orig;
    const all = (orig ? orig.pmc : []).concat(adapt ? adapt.pmc : []);
    const yMax = Math.max(40, ...all.map(p => p.ctl), ...all.map(p => p.atl)) * 1.12;
    const yMin = Math.min(-15, ...all.map(p => p.tsb)) * 1.15;
    const x = i => padL + (i / Math.max(1, n - 1)) * iw;
    const y = v => padT + (1 - (v - yMin) / (yMax - yMin)) * ih;
    const y0 = y(0);

    const line = (data, key) => data.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ');
    const area = data => {
      const top = data.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.tsb).toFixed(1)}`).join(' ');
      return `${top} L${x(n - 1).toFixed(1)},${y0} L${x(0).toFixed(1)},${y0} Z`;
    };

    let s = `<svg viewBox="0 0 ${W} ${H}" class="pmc-svg" preserveAspectRatio="none">`;

    /* form zone bands */
    s += `<rect x="${padL}" y="${y(25)}" width="${iw}" height="${y(5) - y(25)}" class="band-fresh"/>`;
    s += `<rect x="${padL}" y="${y(-10)}" width="${iw}" height="${y(-25) - y(-10)}" class="band-risk"/>`;

    /* gridlines + y labels */
    for (let g = Math.ceil(yMin / 25) * 25; g <= yMax; g += 25) {
      s += `<line x1="${padL}" x2="${W - padR}" y1="${y(g)}" y2="${y(g)}" class="grid"/>`;
      s += `<text x="${padL - 8}" y="${y(g) + 4}" class="axis-lbl" text-anchor="end">${g}</text>`;
    }
    s += `<line x1="${padL}" x2="${W - padR}" y1="${y0}" y2="${y0}" class="grid grid-zero"/>`;

    /* month ticks */
    let lastMonth = -1;
    dates.forEach((d, i) => {
      if (d.getMonth() !== lastMonth) {
        lastMonth = d.getMonth();
        s += `<text x="${x(i)}" y="${H - 12}" class="axis-lbl">${d.toLocaleDateString('en-GB', { month: 'short' })}</text>`;
        s += `<line x1="${x(i)}" x2="${x(i)}" y1="${padT}" y2="${H - padB}" class="grid grid-month"/>`;
      }
    });

    /* daily TSS bars (adapted series) */
    const tssMax = Math.max(60, ...series.pmc.map(p => p.tss));
    series.pmc.forEach((p, i) => {
      if (!p.tss) return;
      const bh = (p.tss / tssMax) * ih * 0.30;
      s += `<rect x="${x(i) - 1.6}" y="${H - padB - bh}" width="3.2" height="${bh}" class="tss-bar"/>`;
    });

    /* original plan overlay (ghost) */
    if (orig && adapt && opts.showOriginal) {
      s += `<path d="${line(orig.pmc, 'ctl')}" class="ln ln-ghost-ctl"/>`;
      s += `<path d="${line(orig.pmc, 'atl')}" class="ln ln-ghost-atl"/>`;
    }

    /* TSB area + main lines */
    s += `<path d="${area(series.pmc)}" class="area-tsb"/>`;
    s += `<path d="${line(series.pmc, 'ctl')}" class="ln ln-ctl"/>`;
    s += `<path d="${line(series.pmc, 'atl')}" class="ln ln-atl"/>`;
    s += `<path d="${line(series.pmc, 'tsb')}" class="ln ln-tsb"/>`;

    /* today + race markers */
    const todayIdx = dates.findIndex(d => Planner.sameDay(d, new Date()));
    if (todayIdx >= 0) {
      s += `<line x1="${x(todayIdx)}" x2="${x(todayIdx)}" y1="${padT}" y2="${H - padB}" class="mark-today"/>`;
      s += `<text x="${x(todayIdx) + 5}" y="${padT + 12}" class="mark-lbl">today</text>`;
    }
    s += `<line x1="${x(n - 1)}" x2="${x(n - 1)}" y1="${padT}" y2="${H - padB}" class="mark-race"/>`;
    s += `<text x="${x(n - 1) - 5}" y="${padT + 12}" class="mark-lbl mark-race-lbl" text-anchor="end">🏁 race</text>`;

    /* hover crosshair */
    s += `<line id="pmcCross" x1="0" x2="0" y1="${padT}" y2="${H - padB}" class="cross" visibility="hidden"/>`;
    s += `<rect x="${padL}" y="${padT}" width="${iw}" height="${ih}" fill="transparent" class="pmc-hit"/>`;
    s += `</svg>`;
    el.innerHTML = s;

    /* interactivity */
    const svg = el.querySelector('svg');
    const hit = svg.querySelector('.pmc-hit');
    const cross = svg.querySelector('#pmcCross');
    const zone = v => v >= 15 ? 'Race / transition' : v >= 5 ? 'Fresh · optimal' :
                     v >= -10 ? 'Neutral · productive' : v >= -25 ? 'Fatigued · high risk' : 'Very fatigued';
    hit.addEventListener('mousemove', e => {
      const r = svg.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width * W;
      const i = Math.round((fx - padL) / iw * (n - 1));
      if (i < 0 || i >= n) return;
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i));
      cross.setAttribute('visibility', 'visible');
      const p = series.pmc[i], o = orig?.pmc[i];
      tipEl.innerHTML = `
        <div class="tip-date">${dates[i].toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</div>
        <div class="tip-row"><i class="sw sw-ctl"></i>CTL <b>${p.ctl.toFixed(1)}</b>${o && opts.showOriginal ? `<em>plan ${o.ctl.toFixed(1)}</em>` : ''}</div>
        <div class="tip-row"><i class="sw sw-atl"></i>ATL <b>${p.atl.toFixed(1)}</b>${o && opts.showOriginal ? `<em>plan ${o.atl.toFixed(1)}</em>` : ''}</div>
        <div class="tip-row"><i class="sw sw-tsb"></i>TSB <b>${p.tsb.toFixed(1)}</b> <em>${zone(p.tsb)}</em></div>
        <div class="tip-row"><i class="sw sw-tss"></i>TSS <b>${Math.round(p.tss)}</b></div>`;
      tipEl.style.display = 'block';
      const wrap = el.parentElement.getBoundingClientRect();
      tipEl.style.left = Math.min(e.clientX - wrap.left + 18, wrap.width - 210) + 'px';
      tipEl.style.top = (e.clientY - wrap.top - 10) + 'px';
    });
    hit.addEventListener('mouseleave', () => {
      cross.setAttribute('visibility', 'hidden');
      tipEl.style.display = 'none';
    });
  }

  /* ─────────────────── interval block profile ─────────────────── */
  function workoutProfile(el, session, profile) {
    const segs = session.segments;
    if (!segs.length) { el.innerHTML = ''; return; }
    const W = 760, H = 230, padB = 46, padT = 26;
    const total = segs.reduce((s, g) => s + g.durMin, 0);
    const iMax = 1.3;
    const ftp = profile.ftp;

    let x = 0;
    let s = `<svg viewBox="0 0 ${W} ${H}" class="profile-svg">`;
    /* threshold reference line */
    const thrY = padT + (1 - 1.0 / iMax) * (H - padT - padB);
    s += `<line x1="0" x2="${W}" y1="${thrY}" y2="${thrY}" class="thr-line"/>`;
    s += `<text x="${W - 4}" y="${thrY - 4}" class="thr-lbl" text-anchor="end">threshold</text>`;

    segs.forEach((g, idx) => {
      const w = Math.max(1.5, g.durMin / total * W);
      const h = g.intensity / iMax * (H - padT - padB);
      const yy = H - padB - h;
      const col = SPORT_COLOR[g.sport || session.sport] || '#a78bfa';
      const cls = g.kind === 'recover' || g.kind === 'wu' || g.kind === 'cd' ? 'seg-dim' : '';
      s += `<rect x="${x.toFixed(1)}" y="${yy.toFixed(1)}" width="${(w - 1).toFixed(1)}" height="${h.toFixed(1)}"
              rx="2" fill="${col}" class="seg ${cls}"/>`;
      if (w > 26) {
        s += `<text x="${(x + w / 2).toFixed(1)}" y="${H - padB + 14}" class="seg-dur" text-anchor="middle">${g.durMin < 1 ? Math.round(g.durMin * 60) + 's' : g.durMin + '′'}</text>`;
        if (w > 54 && g.kind !== 'strength')
          s += `<text x="${(x + w / 2).toFixed(1)}" y="${H - padB + 30}" class="seg-tgt" text-anchor="middle">${targetText(g, session.sport, profile)}</text>`;
      }
      if (g.reps && g.rep === 1)
        s += `<text x="${(x + 3).toFixed(1)}" y="${yy - 6}" class="seg-reps">×${g.reps}</text>`;
      x += w;
    });
    s += `</svg>`;
    el.innerHTML = s;
  }

  function targetText(g, sport, profile) {
    const sp = g.sport || sport;
    if (sp === 'bike') return `${Math.round(g.intensity * profile.ftp)}W`;
    if (sp === 'run')  return `${Physio.fmtPace(profile.run.thresholdPaceSec / g.intensity)}/km`;
    if (sp === 'swim') return `${Physio.fmtPace(profile.swim.cssSecPer100 / g.intensity)}/100m`;
    return '';
  }

  /* ─────────────────── segment table rows ─────────────────── */
  function segmentRows(session, profile) {
    const sportName = { bike: 'Bike', run: 'Run', swim: 'Swim', strength: 'Strength' };
    return session.segments.map((g, i) => {
      const sp = g.sport || session.sport;
      let target;
      if (sp === 'strength') target = g.label;
      else if (sp === 'bike') {
        const z = Physio.cogganZoneName(g.intensity);
        target = `<b>${Math.round(g.intensity * profile.ftp)} W</b> · ${Math.round(g.intensity * 100)}% FTP · Z${z.n} ${z.name}`;
      } else if (sp === 'run') {
        target = `<b>${Physio.fmtPace(profile.run.thresholdPaceSec / g.intensity)}/km</b> · ${Physio.runZoneKey(g.intensity)} pace`;
      } else if (sp === 'swim') {
        target = `<b>${Physio.fmtPace(profile.swim.cssSecPer100 / g.intensity)}/100m</b> · ${Math.round(g.intensity * 100)}% CSS`;
      }
      const label = sp === 'strength' ? `${sportName.strength}` :
        (g.kind === 'wu' ? 'Warm-up' : g.kind === 'cd' ? 'Cool-down' : g.kind === 'recover' ? 'Recover' : g.label);
      return `<tr class="row-${g.kind}">
        <td>${i + 1}</td>
        <td><i class="dot" style="background:${SPORT_COLOR[sp] || '#94a3b8'}"></i>${label}${g.reps ? ` <em class="rep-tag">${g.rep}/${g.reps}</em>` : ''}</td>
        <td>${g.durMin < 1 ? Math.round(g.durMin * 60) + ' s' : g.durMin + ' min'}</td>
        <td>${target}</td></tr>`;
    }).join('');
  }

  /* ─────────────────── TSB form gauge ─────────────────── */
  function gauge(el, tsb) {
    const v = Physio.clamp(tsb, -40, 40);
    const ang = (v + 40) / 80 * 180;                       // 0..180
    const rad = a => (a - 180) * Math.PI / 180;
    const px = a => 60 + 46 * Math.cos(rad(a));
    const py = a => 58 + 46 * Math.sin(rad(a));
    const col = v >= 5 ? '#34d399' : v >= -10 ? '#fbbf24' : '#f43f5e';
    el.innerHTML = `
      <svg viewBox="0 0 120 74" class="gauge-svg">
        <path d="M14,58 A46,46 0 0 1 106,58" class="gauge-bg"/>
        <path d="M${px(0)},${py(0)} A46,46 0 0 1 ${px(ang)},${py(ang)}" class="gauge-val" stroke="${col}" style="${ang > 180 ? '' : ''}"/>
        <line x1="60" y1="58" x2="${60 + 34 * Math.cos(rad(ang))}" y2="${58 + 34 * Math.sin(rad(ang))}" class="gauge-needle"/>
        <circle cx="60" cy="58" r="3.5" class="gauge-hub"/>
        <text x="60" y="48" text-anchor="middle" class="gauge-num" fill="${col}">${v.toFixed(0)}</text>
        <text x="14" y="72" class="gauge-lbl">−40</text>
        <text x="98" y="72" class="gauge-lbl">+40</text>
      </svg>
      <div class="gauge-cap">form (TSB)</div>`;
  }

  return { pmc, workoutProfile, segmentRows, gauge, SPORT_COLOR, fmtDate };
})();
