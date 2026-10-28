// MapLibre map: basemap, department choropleth + outlines, the GPU accident layer, hover/selection highlights.
import { PointLayer } from './pointlayer.js';
import { buildStyle, LABEL_ANCHOR } from './basemap.js';
import { PointGrid, mercatorColumns } from './data.js';

export const FRANCE_BOUNDS = [[-5.4, 41.0], [9.9, 51.4]];
const EMPTY = { type: 'FeatureCollection', features: [] };

export class MapView {
  constructor({ container, data, engine, theme }) {
    this.data = data; this.engine = engine; this.theme = theme;
    this.insets = { left: 0, right: 0, top: 0, bottom: 0 };
    this.handlers = {};
    const { lon, lat, sev, wmode } = data.acc;
    const m = mercatorColumns(lon, lat);
    this.merc = m;
    this.grid = new PointGrid(m.mx, m.my);
    this.layer = new PointLayer({ hi: m.hi, lo: m.lo, sev, mode: wmode, vis: engine.vis });
    this.layer.setPalette(theme.sev, theme.mode);
    this.layer.setGhost(0.07);

    const style = buildStyle({ theme, data });
    this.map = new maplibregl.Map({
      container, attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
      minZoom: 4.2, maxZoom: 18.6, maxBounds: [[-28, 32], [28, 62]], renderWorldCopies: false, fadeDuration: 0,
      bounds: FRANCE_BOUNDS, fitBoundsOptions: { padding: 24 }, canvasContextAttributes: { antialias: false }, style,
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'Data: <a href="https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024" target="_blank" rel="noopener">ONISR BAAC 2022–24</a> · <a href="https://geo.api.gouv.fr" target="_blank" rel="noopener">Etalab</a> (Licence Ouverte)' }), 'bottom-right');
    this.ready = new Promise((res) => this.map.on('load', res)).then(() => this.onLoad());
  }

  on(ev, fn) { this.handlers[ev] = fn; }
  emit(ev, ...a) { this.handlers[ev]?.(...a); }

  onLoad() {
    const map = this.map;
    map.addLayer(this.layer, LABEL_ANCHOR);
    this.setChoroVisible(false);
    document.querySelector('.maplibregl-ctrl-attrib')?.removeAttribute('open');
    document.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show');
    const zr = ['interpolate', ['linear'], ['zoom'], 5, 3, 10, 7, 14, 11, 17, 16];
    map.addLayer({ id: 'cluster-fill', type: 'circle', source: 'hl', filter: ['==', ['get', 'k'], 'cluster'],
      paint: { 'circle-radius': ['get', 'rpx'], 'circle-color': '#ffffff', 'circle-opacity': 0.07, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.2, 'circle-stroke-opacity': 0.7, 'circle-pitch-alignment': 'viewport' } });
    map.addLayer({ id: 'hover-ring', type: 'circle', source: 'hl', filter: ['==', ['get', 'k'], 'hover'],
      paint: { 'circle-radius': zr, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.4, 'circle-stroke-opacity': 0.95 } });
    map.addLayer({ id: 'sel-halo', type: 'circle', source: 'hl', filter: ['==', ['get', 'k'], 'sel'],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 11, 10, 14, 16, 22], 'circle-color': ['get', 'c'], 'circle-opacity': 0.18, 'circle-blur': 0.6 } });
    map.addLayer({ id: 'sel-ring', type: 'circle', source: 'hl', filter: ['==', ['get', 'k'], 'sel'],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 7, 10, 9, 16, 15], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2, 'circle-stroke-opacity': 1 } });

    let raf = 0;
    const view = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => this.emit('view')); };
    map.on('move', view); map.on('moveend', () => this.emit('viewend'));
    map.on('mousemove', (e) => this.hoverAt(e));
    map.on('mouseout', () => this.emit('hover', null, null));
    map.on('click', (e) => this.emit('click', e));
    this.emit('view');
  }

  // ---- geometry helpers -----------------------------------------------------------------
  setInsets(i) { Object.assign(this.insets, i); }
  /** Bounds of the part of the map not covered by floating panels. */
  regionBounds() {
    const c = this.map.getCanvas(), w = c.clientWidth, h = c.clientHeight, { left, right, top, bottom } = this.insets;
    const nw = this.map.unproject([left, top]), se = this.map.unproject([Math.max(left + 40, w - right), Math.max(top + 40, h - bottom)]);
    return [nw.lng, se.lat, se.lng, nw.lat];
  }
  regionCenterPx() {
    const c = this.map.getCanvas(), { left, right, top, bottom } = this.insets;
    return [(left + c.clientWidth - right) / 2, (top + c.clientHeight - bottom) / 2];
  }
  mercatorAt(pt) {
    const ll = this.map.unproject(pt);
    const s = Math.sin((ll.lat * Math.PI) / 180);
    return [(ll.lng + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)];
  }
  mercPerPx() { return 1 / (512 * Math.pow(2, this.map.getZoom())); }

  /** Visible accidents within `px` screen pixels of a point, nearest first. */
  pick(pt, px) {
    const [x, y] = this.mercatorAt([pt.x, pt.y]), r = px * this.mercPerPx(), vis = this.engine.vis;
    const found = this.grid.query(x, y, r, (i) => vis[i] === 1);
    const out = [];
    for (let k = 0; k < found.length; k += 2) out.push([found[k], found[k + 1]]);
    out.sort((a, b) => a[1] - b[1]);
    return out;
  }

  hoverAt(e) {
    if (this._hoverRaf) { this._lastEvt = e; return; }
    this._lastEvt = e;
    this._hoverRaf = requestAnimationFrame(() => {
      this._hoverRaf = 0;
      const ev = this._lastEvt;
      const hits = this.pick(ev.point, Math.max(6, this.layerRadiusPx() + 3));
      let best = null;
      if (hits.length) { // prefer the most severe among the closest few
        const near = hits[0][1];
        const cand = hits.filter((h) => h[1] <= near * 1.6 + 1e-12).slice(0, 8);
        const sev = this.data.acc.sev;
        best = cand.reduce((a, b) => (sev[b[0]] > sev[a[0]] ? b : a))[0];
      }
      this.emit('hover', best, ev);
    });
  }
  layerRadiusPx() {
    const zt = Math.min(1, Math.max(0, (this.map.getZoom() - 4.6) / 12.4));
    return 0.7 + 5.9 * Math.pow(zt, 1.45);
  }

  // ---- highlights -----------------------------------------------------------------------
  lonlat(i) { return [this.data.acc.lon[i], this.data.acc.lat[i]]; }
  setHighlights({ hover = null, selected = null, selectedColor = '#fff', cluster = null }) {
    const f = [];
    if (hover != null) f.push({ type: 'Feature', properties: { k: 'hover' }, geometry: { type: 'Point', coordinates: this.lonlat(hover) } });
    if (selected != null) f.push({ type: 'Feature', properties: { k: 'sel', c: selectedColor }, geometry: { type: 'Point', coordinates: this.lonlat(selected) } });
    if (cluster) f.push({ type: 'Feature', properties: { k: 'cluster', rpx: cluster.rpx }, geometry: { type: 'Point', coordinates: cluster.center } });
    this.map.getSource('hl')?.setData({ type: 'FeatureCollection', features: f });
  }

  setChoropleth(values01) {
    const m = this.map;
    for (let i = 0; i < values01.length; i++) m.setFeatureState({ source: 'deps', id: i }, { t: values01[i] });
  }
  setChoroVisible(v) { this.map.setLayoutProperty('dep-fill', 'visibility', v ? 'visible' : 'none'); }
  setDepHover(i) {
    if (this._depHover === i) return;
    if (this._depHover != null) this.map.setFeatureState({ source: 'deps', id: this._depHover }, { hover: false });
    this._depHover = i;
    if (i != null) this.map.setFeatureState({ source: 'deps', id: i }, { hover: true });
  }
  depAt(pt) {
    const f = this.map.queryRenderedFeatures(pt, { layers: ['dep-fill'] });
    return f.length ? f[0].properties.i : null;
  }

  // ---- camera ---------------------------------------------------------------------------
  /** Fit bounds into the region not covered by panels. */
  fit(bounds, opts = {}) {
    const { left, right, top, bottom } = this.insets, pad = opts.pad ?? 24;
    this.map.fitBounds(bounds, { padding: { left: left + pad, right: right + pad, top: top + pad, bottom: bottom + pad }, duration: opts.duration ?? 900, maxZoom: opts.maxZoom ?? 16, essential: true });
  }
  flyTo(lonlat, zoom, duration = 1200) {
    const [cx, cy] = this.regionCenterPx(), c = this.map.getCanvas();
    this.map.flyTo({ center: lonlat, zoom, duration, offset: [cx - c.clientWidth / 2, cy - c.clientHeight / 2], essential: true });
  }
  resetView(duration = 1000) { this.fit(FRANCE_BOUNDS, { duration, pad: 8 }); }

  setColorBy(v) { this.layer.setColorBy(v); }
}
