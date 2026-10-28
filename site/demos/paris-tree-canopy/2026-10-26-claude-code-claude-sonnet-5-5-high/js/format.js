// Small formatting + DOM helpers shared by every module.

const nf = new Intl.NumberFormat("en-GB");
const nf1 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

export const fmt = (n) => nf.format(Math.round(n));
export const fmt1 = (n) => nf1.format(n);
export const fmt2 = (n) => nf2.format(n);
export const pct = (x, d = 0) => (x * 100).toFixed(d) + "%";
export const compact = (n) =>
  n >= 10000 ? Math.round(n / 1000) + "k" : n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(Math.round(n));

/** Only http(s) URLs from the open-data files are ever put into href / src. */
export const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/** Hyperscript helper. Text is always inserted through textContent / text nodes (data is untrusted). */
export function h(tag, props, ...kids) {
  const el = tag.startsWith("svg:")
    ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4))
    : document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") el.setAttribute("class", v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  append(el, kids);
  return el;
}

export function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

export const svg = (tag, props, ...kids) => h("svg:" + tag, props, ...kids);

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

/** Statistics from a histogram of integer values (index = value, ignoring index 0 = unknown). */
export function histStats(counts, from = 1) {
  let n = 0, sum = 0;
  for (let v = from; v < counts.length; v++) {
    n += counts[v];
    sum += counts[v] * v;
  }
  if (!n) return { n: 0, mean: NaN, median: NaN, p10: NaN, p90: NaN };
  const q = (p) => {
    const target = p * n;
    let acc = 0;
    for (let v = from; v < counts.length; v++) {
      acc += counts[v];
      if (acc >= target) return v;
    }
    return counts.length - 1;
  };
  return { n, mean: sum / n, median: q(0.5), p10: q(0.1), p90: q(0.9) };
}

export const ARR_LABEL = (i) => (i < 20 ? `${i + 1}${i === 0 ? "er" : "e"} arrondissement` : null);
