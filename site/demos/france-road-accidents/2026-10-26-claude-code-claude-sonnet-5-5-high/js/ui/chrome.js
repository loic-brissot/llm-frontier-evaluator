// Map chrome: active-filter strip, legend, place search, scenes menu, method dialog.
import { h, fmt, pct, esc, debounce, plural } from '../util.js';
import { icon } from '../icons.js';
import { FILTERS, NOPP } from '../engine.js';
import { pairName } from './matrix.js';

// ---- active filters strip -------------------------------------------------------------------------
function hourRanges(set) {
  const on = Array.from({ length: 24 }, (_, i) => set.has(i));
  if (on.every(Boolean)) return 'all day';
  let start = on.findIndex((v, i) => v && !on[(i + 23) % 24]);
  if (start < 0) start = 0;
  const out = [];
  for (let k = 0; k < 24; k++) {
    const i = (start + k) % 24;
    if (on[i] && (k === 0 || !on[(i + 23) % 24])) { let len = 1; while (on[(i + len) % 24] && len < 24) len++; out.push(len === 1 ? `${i}h` : `${i}h–${(i + len - 1) % 24}h`); }
  }
  return out.join(', ');
}

export function ActiveBar({ engine, meta, theme, onChange }) {
  const L = meta.labels, el = h('div', { class: 'activebar', hidden: true });
  const names = {
    year: ['Year', (v) => String(2022 + v)], dow: ['Day', (v) => L.dow[v]], lum: ['Light', (v) => L.lum[v]], atm: ['Weather', (v) => L.atm[v]], road: ['Road', (v) => L.road[v]],
    vma: ['Limit', (v) => (v === 0 ? 'unknown' : v === 8 ? 'other' : L.vma[v])], vosp: ['Cycling infra', (v) => L.vosp[v]], sev: ['Worst injury', (v) => theme.sevNames[v]],
    wmode: ['Victim', (v) => meta.modes[v].label], agg: ['Area', (v) => L.agg[v]], int: ['Junction', (v) => L.int[v]], surf: ['Surface', (v) => L.surf[v]], dep: ['Département', (v) => meta.deps[v].name],
  };
  const chip = (label, value, clear) => h('span', { class: 'achip' }, h('em', label), value, h('button', { type: 'button', 'aria-label': `Clear ${label}`, html: icon('close', 11), onclick: clear }));
  return {
    el,
    update() {
      const chips = [];
      for (const f of FILTERS) {
        if (!engine.counts[f.key]) continue;
        const vals = []; for (let v = 0; v < f.n; v++) if (engine.masks[f.key][v]) vals.push(v);
        let text;
        if (f.key === 'hour') text = hourRanges(new Set(vals));
        else { const [, fn] = names[f.key]; text = vals.length > 3 ? `${vals.slice(0, 2).map(fn).join(', ')} +${vals.length - 2}` : vals.map(fn).join(', '); }
        chips.push(chip(f.key === 'hour' ? 'Hour' : names[f.key][0], text, () => { engine.clear(f.key); onChange(); }));
      }
      if (engine.pairCount) {
        const cs = []; engine.pairMask.forEach((v, c) => v && cs.push(c));
        const text = cs.length <= 2 ? cs.map((c) => { const n = pairName(meta, c); return `${n.victim} × ${n.opp}`; }).join(' · ') : `${cs.length} pairs`;
        chips.push(chip('Collision', text, () => { engine.setPairs([]); onChange(); }));
      }
      el.hidden = !chips.length;
      el.replaceChildren(...chips, ...(chips.length > 1 ? [h('button', { type: 'button', class: 'link', onclick: () => { engine.clearAll(); onChange(); } }, 'Clear all')] : []));
    },
  };
}

// ---- legend ---------------------------------------------------------------------------------------------
export function Legend({ engine, meta, theme, onToggle }) {
  const el = h('div', { class: 'legend' });
  return {
    el,
    update(R, colorBy) {
      if (colorBy === 'sev') {
        const items = [3, 2, 1].map((sv) => h('button', { type: 'button', class: 'lg' + (engine.has('sev', sv) ? ' on' : engine.counts.sev ? ' dim' : ''), onclick: () => onToggle('sev', sv) },
          h('i', { class: 'swatch' + (sv === 3 ? ' ring' : ''), style: { background: theme.sev[sv] } }), h('span', theme.sevNames[sv]), h('b', fmt(R.sevAcc[sv]))));
        el.replaceChildren(h('p', { class: 'eyebrow' }, 'Worst injury in each accident'), h('div', { class: 'lg-row' }, items), h('p', { class: 'lg-note' }, 'One dot = one accident · ringed dots are fatal · ', h('span', { class: 'lg-unh' }, h('i', { class: 'swatch', style: { background: theme.sev[0] } }), `${fmt(R.people[0])} people were unharmed (no accident is unharmed overall)`)));
      } else {
        const hs = R.hist.wmode, any = engine.counts.wmode > 0;
        const items = meta.modes.map((m, i) => {
          const n = hs[i * 4] + hs[i * 4 + 1] + hs[i * 4 + 2] + hs[i * 4 + 3];
          return h('button', { type: 'button', class: 'lg' + (engine.has('wmode', i) ? ' on' : any ? ' dim' : '') + (n ? '' : ' zero'), onclick: () => onToggle('wmode', i) },
            h('i', { class: 'swatch shape-' + i, style: { background: theme.mode[i] } }), h('span', m.label), h('b', fmt(n)));
        });
        el.replaceChildren(h('p', { class: 'eyebrow' }, 'Transport mode of the most severely hurt victim'), h('div', { class: 'lg-row wrap' }, items), h('p', { class: 'lg-note' }, 'Click a mode to isolate it · at street level pedestrians ◆, cyclists ▲ and e-scooters ■ get their own shape'));
      }
    },
  };
}

// ---- place search (geo.api.gouv.fr) ---------------------------------------------------------------------
export function Search({ meta, onPick }) {
  const input = h('input', { type: 'search', placeholder: 'Search a commune or département…', 'aria-label': 'Search a commune or département', autocomplete: 'off', spellcheck: 'false' });
  const list = h('ul', { class: 'sresults', hidden: true, role: 'listbox' });
  const el = h('div', { class: 'search' }, h('span', { class: 'sico', html: icon('search', 15) }), input, list);
  let seq = 0;
  const run = debounce(async () => {
    const q = input.value.trim(), my = ++seq;
    if (q.length < 2) { list.hidden = true; return; }
    try {
      const [c, d] = await Promise.all([
        fetch(`https://geo.api.gouv.fr/communes?nom=${encodeURIComponent(q)}&fields=nom,code,centre,departement,population&boost=population&limit=6`).then((r) => r.json()),
        fetch(`https://geo.api.gouv.fr/departements?nom=${encodeURIComponent(q)}&fields=nom,code`).then((r) => r.json()),
      ]);
      if (my !== seq) return;
      const items = [
        ...d.filter((x) => meta.deps.some((y) => y.code === x.code)).slice(0, 2).map((x) => ({ label: x.nom, sub: `Département ${x.code}`, dep: meta.deps.findIndex((y) => y.code === x.code) })),
        ...c.filter((x) => x.centre && meta.deps.some((y) => y.code === x.departement.code)).map((x) => ({ label: x.nom, sub: `${x.departement.nom}${x.population ? ' · ' + fmt(x.population) + ' inh.' : ''}`, lonlat: x.centre.coordinates })),
      ];
      list.replaceChildren(...items.map((it) => h('li', { role: 'option', onclick: () => { input.value = it.label; list.hidden = true; onPick(it); } }, h('b', it.label), h('span', it.sub))));
      if (!items.length) list.replaceChildren(h('li', { class: 'none' }, 'No match'));
      list.hidden = false;
    } catch { list.replaceChildren(h('li', { class: 'none' }, 'Search needs a network connection')); list.hidden = false; }
  }, 220);
  input.addEventListener('input', run);
  input.addEventListener('keydown', (e) => { if (e.key === 'Escape') { list.hidden = true; input.blur(); } if (e.key === 'Enter') list.querySelector('li:not(.none)')?.click(); });
  document.addEventListener('pointerdown', (e) => { if (!el.contains(e.target)) list.hidden = true; });
  return { el };
}

// ---- scenes ---------------------------------------------------------------------------------------------
export function Scenes({ scenes, onPick }) {
  const pop = h('div', { class: 'popover scenes', hidden: true, role: 'menu' },
    h('p', { class: 'eyebrow' }, 'Scenes — guided starting points'),
    scenes.map((sc) => h('button', { type: 'button', class: 'scene', role: 'menuitem', onclick: () => { pop.hidden = true; onPick(sc); } }, h('b', sc.title), h('span', sc.blurb))));
  const btn = h('button', { type: 'button', class: 'btn ghost', 'aria-haspopup': 'true', onclick: (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; } }, h('span', { html: icon('spark', 15) }), 'Scenes');
  document.addEventListener('pointerdown', (e) => { if (!pop.contains(e.target) && !btn.contains(e.target)) pop.hidden = true; });
  return { el: h('div', { class: 'scenes-wrap' }, btn, pop) };
}

// ---- method dialog ---------------------------------------------------------------------------------------
export function About({ meta }) {
  const q = meta.quality;
  const dlg = h('dialog', { class: 'about', 'aria-labelledby': 'about-title' });
  dlg.innerHTML = `
  <form method="dialog"><button class="icon-btn close" aria-label="Close">${icon('close', 18)}</button></form>
  <p class="eyebrow">Method &amp; sources</p>
  <h2 id="about-title">How to read this observatory</h2>
  <div class="about-grid">
    <section><h3>What is mapped</h3>
      <p>Every <b>injury road accident</b> (accident corporel) recorded by the police and gendarmerie in <b>metropolitan France</b> in <b>2022, 2023 and 2024</b>: <b>${fmt(meta.n)}</b> accidents involving ${fmt(meta.nVeh)} vehicles and ${fmt(meta.nUsers)} people, joined from the four BAAC tables (<i>caractéristiques</i>, <i>lieux</i>, <i>véhicules</i>, <i>usagers</i>). An accident enters the file only if at least one person was hurt.</p>
      <p>Of the ${fmt(q.raw_accidents)} accidents in the three files, ${fmt(q.raw_accidents - q.metropolitan_accidents)} happened overseas and are left out; ${fmt(q.metropolitan_accidents - q.mapped_accidents)} metropolitan records were dropped for coordinates implausibly far (> 6 km) from their declared département; ${fmt(q.swapped_coordinates_fixed)} records with swapped latitude/longitude were repaired.</p></section>
    <section><h3>Severity</h3>
      <p>Each person is <i>unharmed</i>, <i>slightly injured</i>, <i>hospitalised</i> (more than 24 h) or <i>killed</i> (within 30 days). The colour of an accident is its <b>worst</b> outcome. Because the file only contains accidents with a victim, no accident is “unharmed” as a whole; unharmed people appear in the records and in the people count. ONISR warns that the “hospitalised” label is not comparable with years before 2018 and is no longer a certified indicator.</p></section>
    <section><h3>Who hits whom</h3>
      <p>Each <b>victim</b> (injured or killed person) is assigned a mode from their vehicle category: pedestrian; bicycle (incl. e-bikes); e-scooter (motorised EDP); moped, scooter, motorcycle or three-wheeler; car (incl. light quadricycles); van (1.5–3.5 t); heavy vehicle (lorries, tractor units, buses, coaches); other (tractors, quads, trams, trains, non-motorised EDP…).</p>
      <p>The <b>opposing party</b> is the other road user in the same accident: for a pedestrian, the vehicle that struck them (as coded in BAAC); for an occupant, the <i>heaviest</i> other vehicle involved, or a pedestrian struck by their vehicle. With no other party: a recorded animal, else a fixed obstacle, else “nothing” (loss of control, rollover, running off the road). ${fmt(q.single_party_users_with_unlisted_vehicle)} people report hitting a vehicle that is not in the file (typically one that fled); they are counted under “other vehicle”.</p></section>
    <section><h3>Reading the numbers</h3>
      <p>These are <b>counts of recorded injuries, not risks</b>: the data holds no information on how many people cycle, walk or drive where and when. A cell with many victims can simply be a popular way to travel. Percentages describe severity <i>given</i> an accident, not the chance of one.</p>
      <p>Coordinates are entered by the police and some are approximate (street or commune level); the rate by département uses INSEE resident population, which ignores tourists and commuters. “Cycling infrastructure” is the road's declared reserved lane (<i>voie spéciale</i>) at the site, whether or not the accident happened on it. Since 2023 about one accident in five lists several roads (a junction): road category and speed-limit filters use the first road listed, cycling infrastructure counts as present if <i>any</i> listed road has it, and every road appears in the accident's record. Colours in the matrix are the share of victims killed, gently pulled toward the overall rate when a cell has few victims so that tiny samples do not look alarming; counts and exact figures are always in the tooltips and the table view.</p></section>
    <section><h3>Controls</h3>
      <p><b>Map</b> – hover a dot for a summary, click for its full record; click in a crowded area to inspect the cluster. <b>Matrix</b> – click cells, row or column headers to filter everything. <b>Filters</b> – click or drag across bars; several selections combine within a chart, and different charts combine with AND. Every chart shows counts under all <i>other</i> filters. <b>Follow map view</b> restricts the summary, matrix and charts to the area you see.</p></section>
    <section><h3>Sources &amp; licences</h3>
      <ul>
        <li>ONISR, <a href="https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024" target="_blank" rel="noopener">Bases de données annuelles des accidents corporels de la circulation routière</a> – Licence Ouverte / Etalab.</li>
        <li>Etalab, <a href="https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/latest/geojson/departements-100m.geojson" target="_blank" rel="noopener">Contours administratifs</a> (départements, 100 m).</li>
        <li><a href="https://geo.api.gouv.fr" target="_blank" rel="noopener">API Découpage administratif</a> – département/commune names, INSEE population, place search.</li>
        <li>Basemap: <a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a>, © OpenMapTiles, data © OpenStreetMap contributors. Rendering: MapLibre GL JS.</li>
      </ul></section>
  </div>`;
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  return { el: dlg, open: () => dlg.showModal() };
}
