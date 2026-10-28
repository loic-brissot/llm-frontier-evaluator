// Tiny inline icon set (stroke icons, 20px grid).
import { svg } from "./format.js";
const P = {
  pin: "M10 18s6-5.2 6-9.5A6 6 0 0 0 4 8.5C4 12.8 10 18 10 18Zm0-7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  leaf: "M4 16C4 8 9 4 17 4c0 8-4 13-11 13m-2-1 6-6",
  ruler: "M3 14.5 14.5 3 17 5.5 5.5 17 3 14.5Zm3-3 1.8 1.8m.7-4.5 1.8 1.8m.7-4.5 1.8 1.8",
  girth: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm0-3.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
  layers: "m10 3 7 4-7 4-7-4 7-4Zm-7 7 7 4 7-4m-14 3 7 4 7-4",
  sprout: "M10 17V9m0 0c0-3 2-5 6-5 0 3-2 5-6 5Zm0 3c0-2.5-1.5-4-5-4 0 2.5 1.5 4 5 4Z",
  star: "m10 2.5 2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5L2.8 7.8l5-.7L10 2.5Z",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12Zm4.5-1.5L17 17",
  check: "m4 10.5 4 4 8-9",
  x: "M5 5l10 10M15 5 5 15",
  ext: "M8 4H4v12h12v-4m-5-8h5v5m0-5L9 11",
  copy: "M7 7V4h9v9h-3M4 7h9v9H4V7Z",
  tree: "M10 2.5a5.5 5.5 0 0 0-3.6 9.6A4.5 4.5 0 0 0 10 13.5V18m0-4.5A4.5 4.5 0 0 0 13.6 12 5.5 5.5 0 0 0 10 2.5Z",
  eye: "M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Zm8 2a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  bulb: "M7.5 14.5h5M8 17h4m-2-14a5 5 0 0 0-3 9c.6.5 1 1.2 1 2h4c0-.8.4-1.5 1-2a5 5 0 0 0-3-9Z",
  chev: "m6 8 4 4 4-4",
  pinfill: "M10 18s6-5.2 6-9.5A6 6 0 0 0 4 8.5C4 12.8 10 18 10 18Z",
  rotate: "M4 10a6 6 0 0 1 10.5-4M16 10a6 6 0 0 1-10.5 4M14.5 3v3h-3M5.5 17v-3h3",
  home: "M3 9.5 10 3l7 6.5V17h-4.5v-5h-5v5H3V9.5Z",
};
export const icon = (name, attrs = {}) =>
  svg("svg", { viewBox: "0 0 20 20", "aria-hidden": "true", fill: "none", stroke: "currentColor", "stroke-width": "1.7", "stroke-linecap": "round", "stroke-linejoin": "round", ...attrs }, svg("path", { d: P[name] }));
