// Color system: validated categorical palette (genus), one-hue sequential ramps (height, girth),
// ordinal ramp (development stage). Every ramp flips its anchor in dark mode: more = lighter.
import { GENUS_SLOTS } from "./data.js";

export const CAT = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
export const OTHER = { light: "#a3a298", dark: "#7a7972" };
export const UNKNOWN = { light: "#c3c2b7", dark: "#4a4a46" };
export const GOLD = { fill: "#f4b92b", ink: "#4a2f00", ring: "#ffffff" };

// ---- OKLCH -> sRGB hex (Björn Ottosson)
function oklch(L, C, H) {
  const a = C * Math.cos((H * Math.PI) / 180), b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return (
    "#" +
    lin
      .map((v) => {
        v = Math.min(1, Math.max(0, v));
        v = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
        return Math.round(v * 255).toString(16).padStart(2, "0");
      })
      .join("")
  );
}

function ramp(hue, Ls, Cs, dark) {
  const steps = Ls.map((L, i) => oklch(L, Cs[i], hue));
  return dark ? steps.slice().reverse() : steps;
}

// Class breaks (value >= break moves to next class).
export const HEIGHT_BREAKS = [4, 8, 12, 16, 20];
export const GIRTH_BREAKS = [50, 100, 150, 200, 300];
export const HEIGHT_LABELS = ["< 4 m", "4–8 m", "8–12 m", "12–16 m", "16–20 m", "≥ 20 m"];
export const GIRTH_LABELS = ["< 50 cm", "50–100 cm", "100–150 cm", "150–200 cm", "200–300 cm", "≥ 300 cm"];

export const MODES = {
  genus: { label: "Genus", help: "Colour by botanical genus" },
  height: { label: "Height", help: "Colour by tree height" },
  girth: { label: "Girth", help: "Colour by trunk circumference" },
  stage: { label: "Stage", help: "Colour by development stage" },
};

const build = (dark) => {
  const k = dark ? "dark" : "light";
  const L6 = [0.9, 0.8, 0.69, 0.58, 0.47, 0.36];
  return {
    genus: [...CAT[k], OTHER[k]],
    height: [...ramp(140, L6, [0.07, 0.11, 0.14, 0.14, 0.12, 0.09], dark), UNKNOWN[k]],
    girth: [...ramp(55, L6, [0.07, 0.11, 0.14, 0.14, 0.12, 0.09], dark), UNKNOWN[k]],
    stage: [...ramp(255, [0.8, 0.66, 0.52, 0.38], [0.08, 0.12, 0.15, 0.13], dark), UNKNOWN[k]],
  };
};
export const COLORS = { light: build(false), dark: build(true) };

export function classOfHeight(v) {
  if (!v) return 6;
  let c = 0;
  while (c < 5 && v >= HEIGHT_BREAKS[c]) c++;
  return c;
}
export function classOfGirth(v) {
  if (!v) return 6;
  let c = 0;
  while (c < 5 && v >= GIRTH_BREAKS[c]) c++;
  return c;
}

/** Per-mode legend entries (labels) – counts are added by the caller. */
export function legendLabels(mode, D) {
  if (mode === "genus") return [...GENUS_SLOTS, "Other genera"];
  if (mode === "height") return [...HEIGHT_LABELS, "Unknown"];
  if (mode === "girth") return [...GIRTH_LABELS, "Unknown"];
  return [...D.stages];
}

/** Class index for every tree under the given color mode (Uint8Array, one byte per tree). */
export function classArray(mode, D) {
  const out = new Uint8Array(D.n);
  if (mode === "genus") for (let i = 0; i < D.n; i++) out[i] = D.slot[D.genus[i]];
  else if (mode === "height") for (let i = 0; i < D.n; i++) out[i] = classOfHeight(D.height[i]);
  else if (mode === "girth") for (let i = 0; i < D.n; i++) out[i] = classOfGirth(D.circ[i]);
  else for (let i = 0; i < D.n; i++) out[i] = D.stage[i];
  return out;
}

export const isDark = () => document.documentElement.dataset.theme === "dark";

/** Publish the data colours as CSS custom properties so DOM / SVG charts follow the theme. */
export function applyThemeVars(theme) {
  const root = document.documentElement.style, C = COLORS[theme];
  C.genus.forEach((c, i) => root.setProperty(`--c${i + 1}`, c));
  C.height.slice(0, 6).forEach((c, i) => root.setProperty(`--seq-${i + 1}`, c));
  C.stage.forEach((c, i) => root.setProperty(`--st-${i}`, c));
}
