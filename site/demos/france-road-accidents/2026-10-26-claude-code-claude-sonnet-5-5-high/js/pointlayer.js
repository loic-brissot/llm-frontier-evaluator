// A MapLibre custom WebGL layer that draws every accident as one GPU point sprite.
// Positions are mercator (0..1) split into float32 hi/lo parts so street-level zoom stays sub-pixel exact.

const VERT = `
precision highp float;
attribute vec2 a_hi; attribute vec2 a_lo; attribute vec2 a_cls; attribute float a_vis;
uniform vec2 u_cHi; uniform vec2 u_cLo; uniform float u_world; uniform vec2 u_half; uniform float u_dpr; uniform float u_zoom;
uniform float u_colorBy; uniform float u_pass; uniform float u_ghost; uniform float u_scale;
uniform vec3 u_sevCol[4]; uniform vec3 u_modeCol[8];
varying vec4 v_color; varying float v_R; varying float v_pad; varying float v_ring; varying float v_shape;
void main() {
  bool vis = a_vis > 0.5;
  if (vis != (u_pass > 0.5)) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); gl_PointSize = 0.0; return; }
  vec2 d = (a_hi - u_cHi) + (a_lo - u_cLo);
  vec2 px = d * u_world;
  gl_Position = vec4(px.x / u_half.x, -px.y / u_half.y, 0.0, 1.0);
  float sev = a_cls.x, mode = a_cls.y;
  float zt = clamp((u_zoom - 4.6) / 12.4, 0.0, 1.0);
  float r = (0.7 + 5.9 * pow(zt, 1.45)) * u_scale;
  float k = sev > 2.5 ? 1.55 : (sev > 1.5 ? 1.22 : 1.0);
  r *= mix(1.0, k, smoothstep(6.0, 10.5, u_zoom));
  vec3 col;
  if (u_colorBy < 0.5) {
    int si = int(sev + 0.5);
    col = si == 0 ? u_sevCol[0] : (si == 1 ? u_sevCol[1] : (si == 2 ? u_sevCol[2] : u_sevCol[3]));
  } else {
    int mi = int(mode + 0.5);
    col = u_modeCol[mi];
  }
  float alpha = mix(0.62, 0.96, smoothstep(0.0, 0.5, zt));
  if (vis) { v_color = vec4(col, alpha); }
  else { v_color = vec4(vec3(0.62, 0.68, 0.8), u_ghost * mix(0.7, 1.0, zt)); r *= 0.85; }
  float pad = 1.5;
  v_R = r * u_dpr; v_pad = pad * u_dpr;
  v_ring = (vis && sev > 2.5 && zt > 0.12) ? 1.0 : 0.0;
  v_shape = (vis && u_colorBy > 0.5 && zt > 0.3) ? (mode < 0.5 ? 1.0 : (mode < 1.5 ? 2.0 : (mode < 2.5 ? 3.0 : 0.0))) : 0.0;
  gl_PointSize = 2.0 * (r + pad) * u_dpr;
}`;

const FRAG = `
precision highp float;
varying vec4 v_color; varying float v_R; varying float v_pad; varying float v_ring; varying float v_shape;
void main() {
  vec2 p = (gl_PointCoord * 2.0 - 1.0) * (v_R + v_pad);   // device px from centre
  float dist;
  if (v_shape < 0.5) dist = length(p);
  else if (v_shape < 1.5) dist = (abs(p.x) + abs(p.y)) * 0.80 + 0.0;                          // diamond
  else if (v_shape < 2.5) { vec2 q = vec2(p.x, -p.y + v_R * 0.15); dist = max(abs(q.x) * 0.866 + q.y * 0.5, -q.y) * 1.12; } // triangle
  else dist = max(abs(p.x), abs(p.y)) * 1.05;                                                  // square
  float edge = clamp(v_R + 0.5 - dist, 0.0, 1.0);
  if (edge <= 0.0) discard;
  vec4 c = v_color;
  float a = c.a * edge;
  vec3 rgb = c.rgb;
  if (v_ring > 0.5) {
    float ringW = max(1.0, v_R * 0.28);
    float t = smoothstep(v_R - ringW - 0.5, v_R - ringW + 0.5, dist);
    rgb = mix(rgb, vec3(1.0), t * 0.92);
    a = mix(a, edge, t);
  }
  gl_FragColor = vec4(rgb * a, a);
}`;

function compile(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}

export class PointLayer {
  constructor({ hi, lo, sev, mode, vis }) {
    this.id = 'accidents'; this.type = 'custom'; this.renderingMode = '2d';
    this.hi = hi; this.lo = lo; this.n = sev.length;
    this.cls = new Uint8Array(this.n * 2);
    for (let i = 0; i < this.n; i++) { this.cls[2 * i] = sev[i]; this.cls[2 * i + 1] = mode[i]; }
    this.vis = vis; this.visDirty = true;
    // random draw order for national-scale views (colours then reflect true proportions); severity order when zoomed in
    this.perm = new Uint32Array(this.n);
    for (let i = 0; i < this.n; i++) this.perm[i] = i;
    let seed = 2463534242;
    const rnd = () => { seed ^= seed << 13; seed >>>= 0; seed ^= seed >>> 17; seed ^= seed << 5; seed >>>= 0; return seed / 4294967296; };
    for (let i = this.n - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); const t = this.perm[i]; this.perm[i] = this.perm[j]; this.perm[j] = t; }
    this.colorBy = 0; this.ghost = 0.0; this.scale = 1;
    this.sevCol = new Float32Array(12); this.modeCol = new Float32Array(24);
  }
  setPalette(sev, mode) {
    const f = (arr, out) => arr.forEach((h, i) => { out[3 * i] = parseInt(h.slice(1, 3), 16) / 255; out[3 * i + 1] = parseInt(h.slice(3, 5), 16) / 255; out[3 * i + 2] = parseInt(h.slice(5, 7), 16) / 255; });
    f(sev, this.sevCol); f(mode, this.modeCol); this.repaint();
  }
  setColorBy(v) { this.colorBy = v; this.repaint(); }
  setGhost(v) { this.ghost = v; this.repaint(); }
  touchVis() { this.visDirty = true; this.repaint(); }
  repaint() { if (this.map) this.map.triggerRepaint(); }

  onAdd(map, gl) {
    this.map = map;
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    this.prog = prog;
    this.loc = {};
    for (const a of ['a_hi', 'a_lo', 'a_cls', 'a_vis']) this.loc[a] = gl.getAttribLocation(prog, a);
    for (const u of ['u_cHi', 'u_cLo', 'u_world', 'u_half', 'u_dpr', 'u_zoom', 'u_colorBy', 'u_pass', 'u_ghost', 'u_scale', 'u_sevCol', 'u_modeCol']) this.loc[u] = gl.getUniformLocation(prog, u);
    const mk = (data, usage = gl.STATIC_DRAW) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage); return b; };
    this.bHi = mk(this.hi); this.bLo = mk(this.lo); this.bCls = mk(this.cls); this.bVis = mk(this.vis, gl.DYNAMIC_DRAW);
    this.bPerm = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.bPerm); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.perm, gl.STATIC_DRAW);
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao); this.bindAttribs(gl); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.bPerm); gl.bindVertexArray(null);
  }

  bindAttribs(gl) {
    const L = this.loc;
    const set = (loc, buf, size, type) => { gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, type, false, 0, 0); };
    set(L.a_hi, this.bHi, 2, gl.FLOAT); set(L.a_lo, this.bLo, 2, gl.FLOAT);
    set(L.a_cls, this.bCls, 2, gl.UNSIGNED_BYTE); set(L.a_vis, this.bVis, 1, gl.UNSIGNED_BYTE);
  }

  render(gl) {
    const map = this.map, L = this.loc, canvas = map.getCanvas();
    if (this.visDirty) { gl.bindBuffer(gl.ARRAY_BUFFER, this.bVis); gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.vis); this.visDirty = false; }
    const c = map.getCenter(), z = map.getZoom();
    const cx = (c.lng + 180) / 360, s = Math.sin((c.lat * Math.PI) / 180), cy = 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
    const hx = Math.fround(cx), hy = Math.fround(cy);
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    gl.useProgram(this.prog);
    gl.uniform2f(L.u_cHi, hx, hy); gl.uniform2f(L.u_cLo, cx - hx, cy - hy);
    gl.uniform1f(L.u_world, 512 * Math.pow(2, z)); gl.uniform2f(L.u_half, cw / 2, ch / 2);
    gl.uniform1f(L.u_dpr, canvas.width / cw); gl.uniform1f(L.u_zoom, z);
    gl.uniform1f(L.u_colorBy, this.colorBy); gl.uniform1f(L.u_ghost, this.ghost); gl.uniform1f(L.u_scale, this.scale);
    gl.uniform3fv(L.u_sevCol, this.sevCol); gl.uniform3fv(L.u_modeCol, this.modeCol);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.disable(gl.STENCIL_TEST);
    gl.bindVertexArray(this.vao);
    const shuffled = z < 9.2;
    const draw = () => (shuffled ? gl.drawElements(gl.POINTS, this.n, gl.UNSIGNED_INT, 0) : gl.drawArrays(gl.POINTS, 0, this.n));
    if (this.ghost > 0) { gl.uniform1f(L.u_pass, 0); draw(); }
    gl.uniform1f(L.u_pass, 1); draw();
    gl.bindVertexArray(null);
  }

  onRemove(map, gl) {
    for (const b of [this.bHi, this.bLo, this.bCls, this.bVis, this.bPerm]) gl.deleteBuffer(b);
    gl.deleteProgram(this.prog);
  }
}
