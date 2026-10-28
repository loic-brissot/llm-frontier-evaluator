// "Midnight atlas": a dark, low-contrast cartographic style on free OpenFreeMap (OpenMapTiles schema) vector tiles.
// Everything is deliberately quiet so that the data layer is the loudest thing on the map.

const FONT = ['Noto Sans Regular'], FONT_BOLD = ['Noto Sans Bold'], FONT_IT = ['Noto Sans Italic'];
const NAME = ['coalesce', ['get', 'name:fr'], ['get', 'name:latin'], ['get', 'name']];
export const LABEL_ANCHOR = 'water-name';
const zoomW = (...p) => ['interpolate', ['exponential', 1.3], ['zoom'], ...p];

export const BASEMAP_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';

/** The first label layer is `LABEL_ANCHOR`; the accident layer is inserted just below it. */
export function buildStyle({ theme, data }) {
  const t = theme.map;
  const base = [
    { id: 'bg', type: 'background', paint: { 'background-color': t.land } },
    { id: 'landcover', type: 'fill', source: 'ofm', 'source-layer': 'landcover', maxzoom: 14,
      paint: { 'fill-color': ['match', ['get', 'class'], ['wood', 'forest'], t.wood, ['grass', 'farmland'], t.grass, ['sand', 'rock', 'ice'], t.rock, t.land], 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.55, 12, 0.9] } },
    { id: 'landuse', type: 'fill', source: 'ofm', 'source-layer': 'landuse', minzoom: 6,
      paint: { 'fill-color': ['match', ['get', 'class'], ['residential', 'suburb', 'neighbourhood'], t.urban, ['industrial', 'commercial', 'retail'], t.industrial, ['cemetery', 'pitch', 'playground', 'stadium'], t.park, t.land], 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0.5, 13, 0.95] } },
    { id: 'park', type: 'fill', source: 'ofm', 'source-layer': 'park', minzoom: 7, paint: { 'fill-color': t.park, 'fill-opacity': 0.8 } },
    { id: 'dep-fill', type: 'fill', source: 'deps', paint: {
      'fill-color': ['interpolate', ['linear'], ['coalesce', ['feature-state', 't'], 0], 0, theme.choro[0], 0.5, theme.choro[1], 1, theme.choro[2]],
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.8, 7, 0.6, 9.5, 0.2, 11, 0] } },
    { id: 'water', type: 'fill', source: 'ofm', 'source-layer': 'water', paint: { 'fill-color': t.water } },
    { id: 'waterway', type: 'line', source: 'ofm', 'source-layer': 'waterway', minzoom: 8, paint: { 'line-color': t.water, 'line-width': zoomW(8, 0.4, 14, 2.5) } },
    { id: 'building', type: 'fill', source: 'ofm', 'source-layer': 'building', minzoom: 13.5, paint: { 'fill-color': t.building, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 13.5, 0, 15, 0.9] } },
    { id: 'rail', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 9, filter: ['==', ['get', 'class'], 'rail'],
      paint: { 'line-color': t.rail, 'line-width': zoomW(9, 0.4, 16, 1.4), 'line-dasharray': [3, 2] } },
    { id: 'road-path', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 14, filter: ['in', ['get', 'class'], ['literal', ['path', 'pedestrian', 'track']]],
      paint: { 'line-color': t.roadMinor, 'line-width': zoomW(14, 0.4, 18, 1.4), 'line-dasharray': [2, 1.5], 'line-opacity': 0.8 } },
    { id: 'road-minor', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 10.5, filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'busway']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': t.roadMinor, 'line-width': zoomW(10.5, 0.3, 14, 1.2, 18, 9) } },
    { id: 'road-secondary', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 7.5, filter: ['in', ['get', 'class'], ['literal', ['secondary', 'tertiary']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': t.roadMid, 'line-width': zoomW(7.5, 0.3, 12, 1.1, 18, 14) } },
    { id: 'road-primary', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 5.5, filter: ['in', ['get', 'class'], ['literal', ['primary', 'trunk']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': t.roadMajor, 'line-width': zoomW(5.5, 0.35, 12, 1.5, 18, 17) } },
    { id: 'road-motorway', type: 'line', source: 'ofm', 'source-layer': 'transportation', minzoom: 4.5, filter: ['==', ['get', 'class'], 'motorway'],
      layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': t.roadMotorway, 'line-width': zoomW(4.5, 0.4, 12, 2, 18, 20) } },
    { id: 'country-border', type: 'line', source: 'ofm', 'source-layer': 'boundary', filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1]],
      paint: { 'line-color': t.border, 'line-width': 0.8, 'line-dasharray': [4, 2] } },
    { id: 'road-name', type: 'symbol', source: 'ofm', 'source-layer': 'transportation_name', minzoom: 13.2,
      filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor', 'service']]],
      layout: { 'symbol-placement': 'line', 'text-field': NAME, 'text-font': FONT, 'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10, 17, 13], 'text-max-angle': 30, 'symbol-spacing': 300 },
      paint: { 'text-color': t.roadLabel, 'text-halo-color': t.land, 'text-halo-width': 1.4 } },
    { id: 'dep-line', type: 'line', source: 'deps', paint: {
      'line-color': t.depLine, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.55, 9, 0.8, 13, 0.55],
      'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.5, 9, 0.9, 14, 1.4] } },
    { id: 'dep-hover', type: 'line', source: 'deps', paint: { 'line-color': '#ffffff', 'line-width': 2, 'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.95, 0] } },
  ];
  const labels = [
    { id: 'water-name', type: 'symbol', source: 'ofm', 'source-layer': 'water_name', minzoom: 5, filter: ['==', ['geometry-type'], 'Point'],
      layout: { 'text-field': NAME, 'text-font': FONT_IT, 'text-size': 11, 'text-letter-spacing': 0.15 }, paint: { 'text-color': t.waterLabel, 'text-halo-color': t.water, 'text-halo-width': 1 } },
    { id: 'place-village', type: 'symbol', source: 'ofm', 'source-layer': 'place', minzoom: 9.5, filter: ['in', ['get', 'class'], ['literal', ['village', 'suburb', 'hamlet', 'neighbourhood', 'quarter']]],
      layout: { 'text-field': NAME, 'text-font': FONT, 'text-size': ['interpolate', ['linear'], ['zoom'], 9.5, 10, 14, 12.5], 'text-padding': 4 },
      paint: { 'text-color': t.placeSmall, 'text-halo-color': t.land, 'text-halo-width': 1.5 } },
    { id: 'place-town', type: 'symbol', source: 'ofm', 'source-layer': 'place', minzoom: 6.5, filter: ['==', ['get', 'class'], 'town'],
      layout: { 'text-field': NAME, 'text-font': FONT, 'text-size': ['interpolate', ['linear'], ['zoom'], 6.5, 10, 12, 14], 'text-padding': 4 },
      paint: { 'text-color': t.placeMid, 'text-halo-color': t.land, 'text-halo-width': 1.6 } },
    { id: 'place-city', type: 'symbol', source: 'ofm', 'source-layer': 'place', minzoom: 3, filter: ['==', ['get', 'class'], 'city'],
      layout: { 'text-field': NAME, 'text-font': FONT_BOLD, 'text-size': ['interpolate', ['linear'], ['zoom'], 4, 11, 8, 14, 12, 19], 'text-padding': 6, 'text-letter-spacing': 0.02 },
      paint: { 'text-color': t.placeBig, 'text-halo-color': t.land, 'text-halo-width': 1.8 } },
  ];
  labels.push(
    { id: 'mask', type: 'fill', source: 'mask', paint: { 'fill-color': t.land, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.82, 8, 0.7, 12, 0.5] } });
  return {
    version: 8,
    glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    sources: {
      ofm: { type: 'vector', url: 'https://tiles.openfreemap.org/planet', attribution: BASEMAP_ATTRIBUTION },
      deps: { type: 'geojson', data: data.deps, promoteId: 'i' },
      mask: { type: 'geojson', data: data.mask },
      hl: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    },
    layers: [...base, ...labels],
  };
}
