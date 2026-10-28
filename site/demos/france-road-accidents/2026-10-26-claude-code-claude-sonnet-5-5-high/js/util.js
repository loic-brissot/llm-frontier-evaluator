// Small DOM / formatting helpers shared by every panel.

export const NS = 'http://www.w3.org/2000/svg';

/** h('div.class#id', {attr}, ...children) – children may be strings, nodes or arrays. */
export function h(tag, attrs, ...kids) {
  const m = /^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i.exec(tag);
  const el = document.createElement(m[1] || 'div');
  for (const t of (m[2].match(/[.#][\w-]+/g) || [])) t[0] === '.' ? el.classList.add(t.slice(1)) : (el.id = t.slice(1));
  return fill(el, attrs, kids);
}
export function s(tag, attrs, ...kids) {
  return fill(document.createElementNS(NS, tag), attrs, kids);
}
function fill(el, attrs, kids) {
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs) || typeof attrs === 'string')) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'style' && typeof v === 'object') { for (const [p, val] of Object.entries(v)) (p.startsWith('--') ? el.style.setProperty(p, val) : (el.style[p] = val)); }
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.setAttribute('class', v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  const add = (c) => { if (c == null || c === false) return; if (Array.isArray(c)) c.forEach(add); else el.append(c instanceof Node ? c : document.createTextNode(String(c))); };
  kids.forEach(add);
  return el;
}

const nf = new Intl.NumberFormat('en-US');
export const fmt = (n) => nf.format(Math.round(n));
export const fmtCompact = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? (n / 1e3).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, '') + 'k' : fmt(n));
export const pct = (x, d = 1) => (isFinite(x) ? (x * 100).toFixed(d) + '%' : '—');
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const plural = (n, one, many = one + 's') => (n === 1 ? one : many);

export function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
/** Leading + trailing throttle: runs at most once per `ms`, always with the latest call. */
export function throttleTime(fn, ms) {
  let last = 0, timer = 0;
  return (...a) => {
    const now = performance.now(), wait = ms - (now - last);
    if (wait <= 0) { last = now; fn(...a); } else if (!timer) timer = setTimeout(() => { timer = 0; last = performance.now(); fn(...a); }, wait);
  };
}
export function throttleRaf(fn) { let q = false, last; return (...a) => { last = a; if (q) return; q = true; requestAnimationFrame(() => { q = false; fn(...last); }); }; }

// ---- tooltip --------------------------------------------------------------------------------
let tip;
export function initTip() { tip = document.getElementById('tip'); }
export function showTip(html, x, y) {
  tip.innerHTML = html; tip.classList.add('on');
  const w = tip.offsetWidth, hh = tip.offsetHeight, W = innerWidth, H = innerHeight;
  let tx = x + 16, ty = y + 18;
  if (tx + w > W - 8) tx = x - w - 16;
  if (ty + hh > H - 8) ty = y - hh - 14;
  tip.style.transform = `translate(${Math.max(8, tx)}px, ${Math.max(8, ty)}px)`;
}
export function hideTip() { tip?.classList.remove('on'); }
/** Attach a live tooltip to an element; `content` returns an HTML string (or falsy to hide). */
export function tooltip(el, content) {
  const f = (e) => { const c = content(e); c ? showTip(c, e.clientX, e.clientY) : hideTip(); };
  el.addEventListener('pointerenter', f); el.addEventListener('pointermove', f); el.addEventListener('pointerleave', hideTip);
  el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); const c = content({ clientX: r.x + r.width / 2, clientY: r.y }); if (c) showTip(c, r.x + r.width / 2, r.y); });
  el.addEventListener('blur', hideTip);
}

export function dateLabel(year, month, day) {
  return `${day} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][month - 1]} ${year}`;
}
