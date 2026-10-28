// Pan / zoom camera over Lambert-93 world coordinates (metres, y up).
import { clamp } from './util.js';

export class Camera {
  constructor(host) {
    this.host = host;
    this.W = 1; this.H = 1;
    this.cx = 650000; this.cy = 570000; this.scale = 0.0006;
    this.tcx = this.cx; this.tcy = this.cy; this.tscale = this.scale;
    this.fitScale = 0.0006;
    this.minScale = 0.0003; this.maxScale = 0.08;
    this.inset = { left: 0, right: 0, top: 0, bottom: 0 }; // regions covered by UI panels
    this.version = 0;          // bumps whenever the transform changed
    this.onChange = () => {};
    this.dragging = false;
    this.follow = null;        // function () => {x,y} | null
    this._pointers = new Map();
    this._bind();
  }

  resize(W, H) { this.W = W; this.H = H; this.version++; }

  // screen centre of the usable (not covered by panels) region
  get ox() { return (this.inset.left - this.inset.right) / 2; }
  get oy() { return (this.inset.top - this.inset.bottom) / 2; }

  sx(x) { return (x - this.cx) * this.scale + this.W / 2 + this.ox; }
  sy(y) { return this.H / 2 + this.oy - (y - this.cy) * this.scale; }
  wx(sx) { return (sx - this.W / 2 - this.ox) / this.scale + this.cx; }
  wy(sy) { return this.cy - (sy - this.H / 2 - this.oy) / this.scale; }

  fit(bbox, pad = 24) {
    const w = this.W - this.inset.left - this.inset.right - 2 * pad;
    const h = this.H - this.inset.top - this.inset.bottom - 2 * pad;
    const s = Math.min(w / (bbox[2] - bbox[0]), h / (bbox[3] - bbox[1]));
    return { x: (bbox[0] + bbox[2]) / 2, y: (bbox[1] + bbox[3]) / 2, s };
  }
  setHome(bbox) {
    const f = this.fit(bbox);
    this.fitScale = f.s;
    this.minScale = f.s * 0.7;
    this.maxScale = f.s * 90;
    this.home = f;
    this.jump(f.x, f.y, f.s);
  }
  jump(x, y, s) {
    this.cx = this.tcx = x; this.cy = this.tcy = y; this.scale = this.tscale = clamp(s, this.minScale, this.maxScale);
    this.version++;
  }
  flyTo(x, y, s) {
    this.tcx = x; this.tcy = y; this.tscale = clamp(s ?? this.tscale, this.minScale, this.maxScale);
  }
  flyToBBox(bbox, pad = 60) {
    const f = this.fit(bbox, pad);
    this.flyTo(f.x, f.y, Math.min(f.s, this.fitScale * 40));
  }
  goHome() { this.follow = null; this.flyTo(this.home.x, this.home.y, this.home.s); }

  zoomAt(sx, sy, factor) {
    const wx = (sx - this.W / 2 - this.ox) / this.tscale + this.tcx;
    const wy = this.tcy - (sy - this.H / 2 - this.oy) / this.tscale;
    const ns = clamp(this.tscale * factor, this.minScale, this.maxScale);
    this.tcx = wx - (sx - this.W / 2 - this.ox) / ns;
    this.tcy = wy + (sy - this.H / 2 - this.oy) / ns;
    this.tscale = ns;
  }

  /** advance the smoothing; returns true while something moves */
  update(dt) {
    if (this.follow && !this.dragging) {
      const p = this.follow();
      if (p) { this.tcx = p.x; this.tcy = p.y; }
    }
    const k = 1 - Math.exp(-dt * 11);
    const ds = Math.log(this.tscale / this.scale);
    const dx = this.tcx - this.cx, dy = this.tcy - this.cy;
    const moving = Math.abs(ds) > 1e-4 || Math.abs(dx) * this.scale > 0.05 || Math.abs(dy) * this.scale > 0.05;
    if (!moving) {
      if (this.cx !== this.tcx || this.cy !== this.tcy || this.scale !== this.tscale) {
        this.cx = this.tcx; this.cy = this.tcy; this.scale = this.tscale; this.version++;
        return true;
      }
      return false;
    }
    this.scale = Math.exp(Math.log(this.scale) + ds * k);
    this.cx += dx * k; this.cy += dy * k;
    this.version++;
    return true;
  }

  _bind() {
    const h = this.host;
    h.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = h.getBoundingClientRect();
      const f = Math.exp(-clamp(e.deltaY, -240, 240) * (e.ctrlKey ? 0.01 : 0.0022));
      this.zoomAt(e.clientX - r.left, e.clientY - r.top, f);
    }, { passive: false });
    h.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      h.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY });
      this.moved = 0;
      if (this._pointers.size === 2) this._pinch = this._pinchState();
    });
    h.addEventListener('pointermove', (e) => {
      const p = this._pointers.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      if (this._pointers.size === 1) {
        this.moved += Math.abs(dx) + Math.abs(dy);
        if (this.moved > 4) {
          this.dragging = true;
          this.follow = null;
          this.cx = this.tcx -= dx / this.scale;
          this.cy = this.tcy += dy / this.scale;
          this.version++;
          this.onChange();
        }
      } else if (this._pointers.size === 2 && this._pinch) {
        const s = this._pinchState();
        const r = h.getBoundingClientRect();
        this.zoomAt(s.cx - r.left, s.cy - r.top, s.d / this._pinch.d);
        this.cx = this.tcx; this.cy = this.tcy; this.scale = this.tscale;
        this.cx -= 0; this._pinch = s;
        this.version++;
        this.onChange();
      }
    });
    const up = (e) => {
      this._pointers.delete(e.pointerId);
      this._pinch = null;
      if (this._pointers.size === 0) setTimeout(() => { this.dragging = false; }, 0);
    };
    h.addEventListener('pointerup', up);
    h.addEventListener('pointercancel', up);
  }
  _pinchState() {
    const [a, b] = [...this._pointers.values()];
    return { cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) || 1 };
  }
}
