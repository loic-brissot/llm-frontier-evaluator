import { CAT_COLOR, DAY, fmtTime } from "./data.js";

const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const PAD_L = 26, PAD_R = 6, PAD_T = 16, PAD_B = 16;
const ORDER = [2, 1, 0]; // TER at the bottom, TGV on top

function fit(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h, dpr };
}

function renderBackground(M, state, w, h, dpr) {
  const off = document.createElement("canvas");
  off.width = Math.round(w * dpr);
  off.height = Math.round(h * dpr);
  const ctx = off.getContext("2d");
  ctx.scale(dpr, dpr);
  const pw = w - PAD_L - PAD_R, ph = h - PAD_T - PAD_B;
  const X = (b) => PAD_L + (b / 288) * pw;
  // night shading
  const night = [[0, 6], [22, 24]];
  for (const [a, b] of night) {
    ctx.fillStyle = "rgba(0,0,0,0.22)";
    ctx.fillRect(PAD_L + (a / 24) * pw, PAD_T, ((b - a) / 24) * pw, ph);
  }
  const stack = new Float32Array(288);
  let max = 1;
  for (let b = 0; b < 288; b++) {
    let s = 0;
    for (let c = 0; c < 3; c++) if (state.catOn[c]) s += M.profile[c][b];
    max = Math.max(max, s);
  }
  const nice = Math.ceil(max / 250) * 250;
  const Y = (v) => PAD_T + ph - (v / nice) * ph;
  // grid
  ctx.strokeStyle = "rgba(120,170,230,0.08)";
  ctx.fillStyle = "rgba(127,147,173,0.8)";
  ctx.font = "9.5px ui-monospace, Menlo, monospace";
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let v = 0; v <= nice; v += nice / 2) {
    ctx.beginPath();
    ctx.moveTo(PAD_L, Math.round(Y(v)) + 0.5);
    ctx.lineTo(w - PAD_R, Math.round(Y(v)) + 0.5);
    ctx.stroke();
    if (v > 0) ctx.fillText(String(v), PAD_L - 4, Y(v));
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let hh = 0; hh <= 24; hh += 1) {
    const x = PAD_L + (hh / 24) * pw;
    ctx.strokeStyle = hh % 6 === 0 ? "rgba(120,170,230,0.16)" : "rgba(120,170,230,0.06)";
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, PAD_T);
    ctx.lineTo(Math.round(x) + 0.5, PAD_T + ph);
    ctx.stroke();
    if (hh % 2 === 0 && hh < 24) ctx.fillText(`${String(hh).padStart(2, "0")}h`, x, PAD_T + ph + 3);
  }
  // stacked areas
  for (const c of ORDER) {
    if (!state.catOn[c]) continue;
    const top = new Float32Array(288);
    for (let b = 0; b < 288; b++) top[b] = stack[b] + M.profile[c][b];
    const grad = ctx.createLinearGradient(0, PAD_T, 0, PAD_T + ph);
    grad.addColorStop(0, rgb(CAT_COLOR[c], 0.75));
    grad.addColorStop(1, rgb(CAT_COLOR[c], 0.18));
    ctx.beginPath();
    ctx.moveTo(X(0), Y(stack[0]));
    for (let b = 0; b < 288; b++) ctx.lineTo(X(b + 0.5), Y(top[b]));
    ctx.lineTo(X(288), Y(top[287]));
    ctx.lineTo(X(288), Y(stack[287]));
    for (let b = 287; b >= 0; b--) ctx.lineTo(X(b + 0.5), Y(stack[b]));
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.beginPath();
    for (let b = 0; b < 288; b++) (b ? ctx.lineTo : ctx.moveTo).call(ctx, X(b + 0.5), Y(top[b]));
    ctx.strokeStyle = rgb(CAT_COLOR[c], 0.95);
    ctx.lineWidth = 1.2;
    ctx.stroke();
    stack.set(top);
  }
  return { off, nice, Y, X, pw, ph };
}

export function drawProfile(canvas, M, state, cache, force = false) {
  const { ctx, w, h, dpr } = fit(canvas);
  const key = `${state.catOn.join()}|${w}x${h}@${dpr}`;
  if (force || cache.profileKey !== key) {
    cache.profileBg = renderBackground(M, state, w, h, dpr);
    cache.profileKey = key;
  }
  const bg = cache.profileBg;
  ctx.clearRect(0, 0, w, h);
  ctx.drawImage(bg.off, 0, 0, w, h);
  const pw = bg.pw, ph = bg.ph;
  const xt = (t) => PAD_L + (t / DAY) * pw;
  // elapsed overlay
  const x = xt(state.t);
  ctx.fillStyle = "rgba(143,227,255,0.05)";
  ctx.fillRect(PAD_L, PAD_T, x - PAD_L, ph);
  if (cache.hoverT != null) {
    const hx = xt(cache.hoverT);
    ctx.strokeStyle = "rgba(255,255,255,0.25)";
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, PAD_T);
    ctx.lineTo(hx, PAD_T + ph);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  // cursor
  const glow = ctx.createLinearGradient(x - 14, 0, x + 14, 0);
  glow.addColorStop(0, "rgba(143,227,255,0)");
  glow.addColorStop(0.5, "rgba(143,227,255,0.25)");
  glow.addColorStop(1, "rgba(143,227,255,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(x - 14, PAD_T - 4, 28, ph + 4);
  ctx.strokeStyle = "#e8fbff";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x, PAD_T - 4);
  ctx.lineTo(x, PAD_T + ph);
  ctx.stroke();
  ctx.fillStyle = "#e8fbff";
  ctx.beginPath();
  ctx.arc(x, PAD_T - 4, 3.5, 0, Math.PI * 2);
  ctx.fill();

  const tRead = cache.hoverT != null ? cache.hoverT : state.t;
  const b = Math.min(287, Math.floor(tRead / 300));
  const vals = [0, 1, 2].map((c) => (state.catOn[c] ? M.profile[c][b] : 0));
  const el = document.getElementById("tl-readout");
  const txt = `${fmtTime(tRead)} · ${vals[0] + vals[1] + vals[2]} trains · TGV ${vals[0]} · IC ${vals[1]} · TER ${vals[2]}`;
  if (el.textContent !== txt) el.textContent = txt;
}

export function drawStationHours(canvas, M, s, state) {
  if (!canvas) return;
  const { ctx, w, h } = fit(canvas);
  const hours = Array.from({ length: 24 }, () => [0, 0, 0]);
  for (let b = 0; b < 144; b++) {
    for (let c = 0; c < 3; c++) hours[Math.floor(b / 6)][c] += M.S.bins[(s * 144 + b) * 3 + c];
  }
  const max = Math.max(1, ...hours.map((x) => x[0] + x[1] + x[2]));
  const bw = (w - 4) / 24;
  const ph = h - 14;
  ctx.clearRect(0, 0, w, h);
  const curH = Math.floor(state.t / 3600);
  hours.forEach((v, i) => {
    let y = ph;
    for (const c of ORDER) {
      if (!state.catOn[c]) continue;
      const hh = (v[c] / max) * (ph - 4);
      ctx.fillStyle = rgb(CAT_COLOR[c], i === curH ? 1 : 0.6);
      ctx.fillRect(2 + i * bw + 1, y - hh, bw - 2, hh);
      y -= hh;
    }
  });
  ctx.fillStyle = "rgba(127,147,173,0.9)";
  ctx.font = "9px ui-monospace, Menlo, monospace";
  ctx.textAlign = "center";
  for (let i = 0; i < 24; i += 3) ctx.fillText(`${i}h`, 2 + i * bw + bw / 2, h - 2);
  ctx.textAlign = "right";
  ctx.fillText(`peak ${max} trains/h`, w - 2, 9);
}
