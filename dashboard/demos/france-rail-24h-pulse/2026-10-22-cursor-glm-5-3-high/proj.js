// proj.js — projection, transform, pan/zoom, sprite cache
"use strict";
var A = window.A = window.A || {};

// ---- projection ----
A.REF_LON = 2.4, A.REF_LAT = 46.6;
A.COS_REF = Math.cos(A.REF_LAT * Math.PI / 180);
// world coords: wx = (lon-refLon)*cosRef ; wy = (lat-refLat)  (north = +)
A.wX = function(lon){ return (lon - A.REF_LON) * A.COS_REF; };
A.wY = function(lat){ return (lat - A.REF_LAT); };

// transform: scale (px per world unit), tx,ty (px offset)
A.T = { scale: 60, tx: 0, ty: 0 };

A.sx = function(wx){ return A.T.tx + wx * A.T.scale; };
A.sy = function(wy){ return A.T.ty - wy * A.T.scale; };   // invert: north up
A.project = function(lon, lat){ return [A.sx(A.wX(lon)), A.sy(A.wY(lat))]; };

// inverse screen -> lon/lat (for hover)
A.unproject = function(px, py){
  const wx = (px - A.T.tx) / A.T.scale;
  const wy = -(py - A.T.ty) / A.T.scale;
  return [wx / A.COS_REF + A.REF_LON, wy + A.REF_LAT];
};

A.fitBounds = function(minLon, minLat, maxLon, maxLat, pad){
  pad = pad || 0.08;
  const wW = A.wX(maxLon) - A.wX(minLon);
  const wH = A.wY(maxLat) - A.wY(minLat);
  const W = A.canvas.clientWidth, H = A.canvas.clientHeight;
  const s = Math.min((W*(1-2*pad))/wW, (H*(1-2*pad))/wH);
  A.T.scale = s;
  A.T.tx = W/2 - ((A.wX(minLon)+A.wX(maxLon))/2) * s;
  A.T.ty = H/2 + ((A.wY(minLat)+A.wY(maxLat))/2) * s;  // + because sy inverts
};

// ---- sprite cache for glowing dots ----
A.sprites = {};
A.makeSprite = function(color, radius){
  const r = Math.max(2, radius);
  const size = Math.ceil(r * 6);
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  const cx = size/2;
  const grd = g.createRadialGradient(cx, cx, 0, cx, cx, size/2);
  grd.addColorStop(0, color);
  grd.addColorStop(0.25, color);
  grd.addColorStop(0.5, A.hexA(color, 0.5));
  grd.addColorStop(1, A.hexA(color, 0));
  g.fillStyle = grd;
  g.fillRect(0,0,size,size);
  return c;
};
A.hexA = function(hex, a){
  // hex #rrggbb -> rgba
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${a})`;
};
A.initSprites = function(){
  A.sprites.TGV = A.makeSprite('#ff5436', 4);
  A.sprites.IC  = A.makeSprite('#36a3ff', 4);
  A.sprites.TER = A.makeSprite('#2ee59d', 4);
  A.sprites.OUIGO = A.makeSprite('#ff2d9c', 4);
  A.sprites.stSmall = A.makeSprite('#6f9bd0', 2);
  A.sprites.stMed = A.makeSprite('#9fc4f0', 3);
  A.sprites.stBig = A.makeSprite('#dceaff', 4);
};
