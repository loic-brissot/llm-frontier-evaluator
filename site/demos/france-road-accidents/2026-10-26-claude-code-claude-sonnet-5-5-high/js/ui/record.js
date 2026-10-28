// Record tab: the full relational record of one accident (site → vehicles → users) or a list for a local cluster.
import { h, s, fmt, pct, plural, tooltip, esc } from '../util.js';
import { MODE_ICON, OPP_ICON, icon, iconBody } from '../icons.js';
import { pairName } from './matrix.js';
import { NOPP } from '../engine.js';

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const SEV_WORD = ['unharmed', 'slightly injured', 'hospitalised', 'killed'];
const SEV_TITLE = ['No injury', 'Slight injuries', 'Hospitalised', 'Fatal accident'];
const IMPACT = { 2: [0, -17], 3: [9, -16], 4: [-9, -16], 5: [0, 17], 6: [9, 16], 7: [-9, 16], 8: [11, 0], 9: [-11, 0] }; // by stored choc value (raw+1)

const SMALL = new Set(['de', 'du', 'des', 'la', 'le', 'les', 'et', 'sur', 'sous', 'aux', 'au', 'en', 'à', 'lès', 'lez', 'l', 'd']);
/** BAAC addresses are mostly ALL CAPS; turn them into readable French title case, leaving mixed-case text alone. */
export function prettyAddress(t) {
  const letters = t.replace(/[^A-Za-zÀ-ÿ]/g, '');
  if (!letters || letters !== letters.toUpperCase()) return t;
  return t.toLowerCase().replace(/[a-zà-ÿ0-9]+/g, (w, off, str) => {
    if (/^[a-z]\d+$/.test(w) || /^(rn|rd|ra|n|d|a)\d+[a-z]?$/.test(w)) return w.toUpperCase();
    if (off > 0 && SMALL.has(w) && !/^[(]/.test(str[off - 1] || '')) return w;
    return w[0].toUpperCase() + w.slice(1);
  });
}
const dateOf = (a, i) => `${DOW[a.dow[i]]} ${a.day[i]} ${MONTH[a.month[i] - 1]} ${2022 + a.year[i]}`;
const timeOf = (a, i) => `${String(a.hour[i]).padStart(2, '0')}:${String(a.minute[i]).padStart(2, '0')}`;

function impactDiagram(choc, color) {
  const pos = IMPACT[choc];
  const svg = s('svg', { class: 'impact', width: 44, height: 56, viewBox: '-22 -28 44 56', role: 'img', 'aria-label': 'Initial point of impact' },
    s('rect', { x: -8, y: -19, width: 16, height: 38, rx: 6, class: 'ibody' }), s('path', { d: 'M-6 -13h12M-6 13h12', class: 'iline' }));
  if (pos) svg.append(s('circle', { cx: pos[0], cy: pos[1], r: 7, fill: color, opacity: 0.25 }), s('circle', { cx: pos[0], cy: pos[1], r: 3.2, fill: color }));
  else if (choc === 10) svg.append(s('rect', { x: -12, y: -23, width: 24, height: 46, rx: 9, fill: 'none', stroke: color, 'stroke-width': 1.5, 'stroke-dasharray': '3 2' }));
  return svg;
}

export function Record({ engine, data, meta, theme, loadText, onClose, onOpen, onZoom }) {
  const { acc: A, rel: Rl } = data, L = meta.labels;
  const root = h('div', { class: 'record' });
  const empty = h('div', { class: 'rec-empty' },
    h('div', { class: 'big', html: icon('pin', 28) }), h('h3', 'Inspect an accident'),
    h('p', 'Click any dot on the map to open its full record: where it happened, the road, every vehicle involved and every person — role, age, sex, safety equipment and injury.'),
    h('p', 'Click in a crowded area to inspect the whole local cluster.'));
  root.append(empty);

  const lab = (key, v) => (L[key] ? L[key][v] : '') ;
  const known = (v) => v && !/^(Not recorded|—)$/.test(v);
  const dl = (rows) => h('dl', { class: 'dl' }, rows.filter(Boolean).flatMap(([k, v]) => [h('dt', k), h('dd', v)]));

  function show(i) {
    const sev = A.sev[i], color = theme.sev[sev];
    const head = h('header', { class: 'rec-head' },
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Back to overview', title: 'Close', html: icon('close', 16), onclick: onClose }),
      h('p', { class: 'eyebrow' }, h('i', { class: 'dot', style: { background: color } }), SEV_TITLE[sev], h('span', { class: 'mono' }, '#' + Number(A.id[i]))),
      h('h2', { class: 'rec-title' }, '…'), h('p', { class: 'rec-sub' }, `${dateOf(A, i)} · ${timeOf(A, i)}`));
    const place = h('p', { class: 'rec-place' });
    const comName = meta.communes[A.com[i]]?.[1] || `Commune ${meta.communes[A.com[i]]?.[0] || ''}`;
    const dep = meta.deps[A.dep[i]];
    place.textContent = `${comName} · ${dep.name} (${dep.code})`;

    const chips = h('div', { class: 'chips' }, [lab('lum', A.lum[i]), lab('atm', A.atm[i]), lab('agg', A.agg[i]), lab('int', A.int[i]), lab('col', A.col[i])].filter(known).map((t) => h('span', { class: 'chip' }, t)));

    // ---- road & site --------------------------------------------------------------------------
    const lanes = A.nbv[i] ? `${A.nbv[i]} ${plural(A.nbv[i], 'lane')}` : '';
    const site = h('section', { class: 'card rec-sec' }, h('h3', h('span', { html: icon('road', 15) }), 'Location & road'),
      dl([
        ['Road', lab('road', A.road[i])], ['Speed limit', A.vma_raw[i] ? A.vma_raw[i] + ' km/h' : ''], ['Lanes', lanes],
        ['Traffic', known(lab('circ', A.circ[i])) ? lab('circ', A.circ[i]) : ''], ['Cycling infrastructure', known(lab('vosp', A.vosp[i])) ? lab('vosp', A.vosp[i]) : ''],
        ['Gradient', known(lab('prof', A.prof[i])) ? lab('prof', A.prof[i]) : ''], ['Alignment', known(lab('plan', A.plan[i])) ? lab('plan', A.plan[i]) : ''],
        ['Surface', known(lab('surf', A.surf[i])) ? lab('surf', A.surf[i]) : ''], ['Structure', known(lab('infra', A.infra[i])) && lab('infra', A.infra[i]) !== 'None' ? lab('infra', A.infra[i]) : ''],
        ['Position', known(lab('situ', A.situ[i])) && lab('situ', A.situ[i]) !== 'None' ? lab('situ', A.situ[i]) : ''],
        ['Coordinates', h('span', { class: 'mono' }, `${A.lat[i].toFixed(5)}, ${A.lon[i].toFixed(5)}`)],
      ].map((r) => (r[1] ? r : null))));
    const otherRoads = h('div', { class: 'other-roads', hidden: true });
    site.append(otherRoads);

    // ---- vehicles & users -----------------------------------------------------------------------
    const v0 = A.vstart[i], v1 = A.vstart[i + 1], u0 = A.ustart[i], u1 = A.ustart[i + 1];
    const byVeh = new Map();
    for (let u = u0; u < u1; u++) { const v = Rl.u_veh[u]; (byVeh.get(v) || byVeh.set(v, []).get(v)).push(u); }
    const letter = (v) => String.fromCharCode(65 + Math.floor(Rl.v_num[v] / 100));
    const cards = [];
    for (let v = v0; v < v1; v++) {
      const users = byVeh.get(v) || [];
      const occupants = users.filter((u) => Rl.u_catu[u] !== 3), peds = users.filter((u) => Rl.u_catu[u] === 3);
      const mode = Rl.v_mode[v];
      const facts = dl([
        ['Initial impact', known(lab('choc', Rl.v_choc[v])) && lab('choc', Rl.v_choc[v]) !== 'None' ? lab('choc', Rl.v_choc[v]) : ''],
        ['Manoeuvre', known(lab('manv', Rl.v_manv[v])) && lab('manv', Rl.v_manv[v]) !== 'Unknown' ? lab('manv', Rl.v_manv[v]) : ''],
        ['Fixed obstacle hit', known(lab('obs', Rl.v_obs[v])) && lab('obs', Rl.v_obs[v]) !== 'None' ? lab('obs', Rl.v_obs[v]) : ''],
        ['Mobile obstacle hit', known(lab('obsm', Rl.v_obsm[v])) && !['None', 'Pedestrian', 'Vehicle'].includes(lab('obsm', Rl.v_obsm[v])) ? lab('obsm', Rl.v_obsm[v]) : lab('obsm', Rl.v_obsm[v]) === 'Pedestrian' ? 'Pedestrian' : ''],
        ['Direction', known(lab('senc', Rl.v_senc[v])) && lab('senc', Rl.v_senc[v]) !== 'Unknown' ? lab('senc', Rl.v_senc[v]) : ''],
        ['Engine', known(lab('motor', Rl.v_motor[v])) && lab('motor', Rl.v_motor[v]) !== 'Unknown' ? lab('motor', Rl.v_motor[v]) : ''],
        Rl.v_occ[v] ? ['Passengers (transit)', String(Rl.v_occ[v])] : null,
      ]);
      const vc = theme.mode[mode];
      const card = h('article', { class: 'veh' },
        h('header', h('span', { class: 'vbadge', style: { background: vc } }, letter(v)), h('span', { class: 'vico', html: icon(MODE_ICON[mode], 18) }),
          h('div', { class: 'vt' }, h('b', L.catv[Rl.v_cat[v]] || 'Vehicle'), h('em', occupants.length ? `${occupants.length} ${plural(occupants.length, 'occupant')}` : 'driver fled or unknown')),
          Rl.v_choc[v] >= 2 ? impactDiagram(Rl.v_choc[v], theme.sev[3]) : null),
        facts, h('div', { class: 'users' }, occupants.map((u) => userRow(u, null)), peds.length ? h('p', { class: 'struck' }, `Pedestrian${peds.length > 1 ? 's' : ''} struck by vehicle ${letter(v)}`) : null, peds.map((u) => userRow(u, null))));
      cards.push(card);
    }

    function userRow(u) {
      const sv = Rl.u_sev[u], ped = Rl.u_catu[u] === 3, c = sv === 255 ? '#667' : theme.sev[sv];
      const sex = ['', 'Man', 'Woman'][Rl.u_sex[u]] || '', age = Rl.u_age[u] === 255 ? '' : `${Rl.u_age[u]} y`;
      const eq = [Rl.u_secu1[u], Rl.u_secu2[u], Rl.u_secu3[u]].filter((x) => x > 0);
      const eqLabels = [...new Set(eq.map((x) => L.secu[x]))].filter((t, _, arr) => arr.length === 1 || t !== 'None');
      const chips = [];
      if (!ped) {
        if (!eq.length) chips.push(h('span', { class: 'chip faint' }, 'Equipment not recorded'));
        for (const t of eqLabels) chips.push(h('span', { class: 'chip' + (t === 'None' ? ' warn' : t === 'Undeterminable' ? ' faint' : '') }, t === 'None' ? 'No safety equipment' : t === 'Undeterminable' ? 'Equipment undeterminable' : t));
      } else {
        for (const t of [L.actp[Rl.u_actp[u]], L.locp[Rl.u_locp[u]], L.etatp[Rl.u_etatp[u]]]) if (t && !/^(Not recorded|N\/A|Unknown|—)$/.test(t)) chips.push(h('span', { class: 'chip' }, t));
      }
      if (Rl.u_trajet[u]) chips.push(h('span', { class: 'chip faint' }, L.trajet[Rl.u_trajet[u]]));
      return h('div', { class: 'user' },
        h('i', { class: 'sevdot', style: { background: c } }),
        h('div', { class: 'ub' },
          h('div', { class: 'ur' }, h('b', ped ? 'Pedestrian' : L.catu[Rl.u_catu[u]]), h('span', [sex, age].filter(Boolean).join(', ') || 'age / sex unknown'), h('span', { class: 'grow' }), h('span', { class: 'uout', style: { color: sv === 1 ? theme.sev[1] : sv === 255 ? '' : c } }, sv === 255 ? 'unknown' : L.grav[sv])),
          chips.length ? h('div', { class: 'chips tight' }, chips) : null));
    }

    // ---- headline ---------------------------------------------------------------------------------
    const nm = pairName(meta, A.wmode[i] * NOPP + A.wopp[i]);
    const counts = [[3, A.n_kil[i]], [2, A.n_hos[i]], [1, A.n_slt[i]], [0, A.n_unh[i]]].filter(([, n]) => n)
      .map(([sv, n]) => h('span', { class: 'cnt', style: { color: sv === 0 ? 'var(--ink-2)' : theme.sev[sv] } }, `${n} ${SEV_WORD[sv]}`));
    const summary = h('p', { class: 'rec-lede' }, h('span', { class: 'mono-ico', style: { color: theme.mode[A.wmode[i]] }, html: icon(MODE_ICON[A.wmode[i]], 18) }),
      h('span', h('b', nm.victim), ' × ', h('b', nm.opp), ` — ${A.nusr[i]} ${plural(A.nusr[i], 'person', 'people')} involved: `, counts.flatMap((x, k) => (k ? [' · ', x] : [x]))));

    const actions = h('div', { class: 'rec-actions' }, h('button', { type: 'button', class: 'btn', onclick: () => onZoom(i) }, h('span', { html: icon('pin', 14) }), 'Zoom to site'));
    const vehHead = h('h3', { class: 'sec-title' }, `${v1 - v0} ${plural(v1 - v0, 'vehicle')} · ${u1 - u0} ${plural(u1 - u0, 'person', 'people')}`);
    root.replaceChildren(head, place, summary, chips, actions, site, vehHead, ...cards);
    root.scrollTop = 0;

    loadText().then((get) => {
      const t = get(i);
      head.querySelector('.rec-title').textContent = prettyAddress(t.adr || t.voie || 'Location not described');
      if (t.adr && t.voie && t.voie !== t.adr && !/^\d+$/.test(t.voie)) site.querySelector('dl').prepend(...dl([['Road name', prettyAddress(t.voie)]]).childNodes);
      else if (/^\d+$/.test(t.voie)) site.querySelector('dl').prepend(...dl([['Road number', t.voie]]).childNodes);
      if (t.others.length) {
        otherRoads.hidden = false;
        otherRoads.replaceChildren(h('h4', 'Other roads at this junction'), ...t.others.map(([voie, vma, vosp, nbv, circ, catr]) => h('div', { class: 'orow' },
          h('b', prettyAddress(voie) || 'unnamed road'), h('span', [vma > 0 ? `${vma} km/h` : '', nbv ? `${nbv} ${plural(nbv, 'lane')}` : '', vosp === 1 ? 'cycle track' : vosp === 2 ? 'cycle lane' : vosp === 3 ? 'reserved lane' : ''].filter(Boolean).join(' · ') || '—'))));
      }
    });
  }

  function showCluster(ids, info) {
    const sevCount = [0, 0, 0, 0], pairs = new Map();
    for (const i of ids) { sevCount[A.sev[i]]++; const c = A.wmode[i] * NOPP + A.wopp[i]; pairs.set(c, (pairs.get(c) || 0) + 1); }
    const order = ids.slice().sort((a, b) => A.sev[b] - A.sev[a] || a - b);
    const top = [...pairs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
    const n = ids.length;
    const bar = h('div', { class: 'sbar thin' }, [3, 2, 1].map((sv) => sevCount[sv] ? h('i', { style: { flexGrow: sevCount[sv], background: theme.sev[sv] } }) : null));
    const head = h('header', { class: 'rec-head' },
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Back to overview', html: icon('close', 16), onclick: onClose }),
      h('p', { class: 'eyebrow' }, 'Local cluster'),
      h('h2', { class: 'rec-title' }, `${fmt(n)} ${plural(n, 'accident')} within ${info.radiusLabel}`),
      h('p', { class: 'rec-sub' }, `${fmt(sevCount[3])} fatal · ${fmt(sevCount[2])} hospitalised · ${fmt(sevCount[1])} slight`));
    const shown = order.slice(0, 150);
    const list = h('div', { class: 'clist' }, shown.map((i) => {
      const nm = pairName(meta, A.wmode[i] * NOPP + A.wopp[i]);
      const b = h('button', { type: 'button', class: 'crow', onclick: () => onOpen(i), onpointerenter: () => info.onHover?.(i), onpointerleave: () => info.onHover?.(null) },
        h('i', { class: 'sevdot', style: { background: theme.sev[A.sev[i]] } }),
        h('span', { class: 'cd' }, h('b', `${nm.victim} × ${nm.opp}`), h('em', `${dateOf(A, i)} · ${timeOf(A, i)}`)),
        h('span', { class: 'cn' }, `${A.nusr[i]} ${plural(A.nusr[i], 'person', 'people')}`));
      return b;
    }));
    const pairsEl = h('div', { class: 'cpairs' }, top.map(([c, k]) => { const nm = pairName(meta, c); return h('span', { class: 'chip' }, h('span', { style: { color: theme.mode[Math.floor(c / NOPP)] }, html: icon(MODE_ICON[Math.floor(c / NOPP)], 13) }), `${nm.victim} × ${nm.opp} `, h('b', k)); }));
    const actions = h('div', { class: 'rec-actions' }, h('button', { type: 'button', class: 'btn', onclick: info.onZoom }, h('span', { html: icon('zoomIn', 14) }), 'Zoom to cluster'));
    root.replaceChildren(head, bar, pairsEl, actions, h('h3', { class: 'sec-title' }, order.length > shown.length ? `Worst ${shown.length} of ${fmt(n)} — zoom in to see the rest` : 'Accidents, worst first'), list);
    root.scrollTop = 0;
  }

  return {
    el: root,
    show, showCluster,
    clear() { root.replaceChildren(empty); },
  };
}
