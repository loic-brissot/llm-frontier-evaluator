// app.js — bootstrap
"use strict";
var A = window.A = window.A || {};

(async function(){
  A.canvas = document.getElementById('map');
  A.initSprites();
  await A.loadAll();
  // fit to station bounds
  let minLon=99,maxLon=-99,minLat=99,maxLat=-99;
  for(let i=0;i<A.stLon.length;i++){
    if(A.stLon[i]<minLon)minLon=A.stLon[i]; if(A.stLon[i]>maxLon)maxLon=A.stLon[i];
    if(A.stLat[i]<minLat)minLat=A.stLat[i]; if(A.stLat[i]>maxLat)maxLat=A.stLat[i];
  }
  A.resize();
  A.fitBounds(minLon,minLat,maxLon,maxLat,0.06);
  A.drawStatic();
  // UI
  A.buildLegend();
  A.buildBusiest();
  A.drawProfile();
  A.drawProfileMarker();
  A.syncTimeline();
  A._lastStatMin = -1;
  A.attachPointer();
  A.attachTimeline();
  // sync play button icon with initial playing state
  document.getElementById('play').innerHTML = A.playing?'&#10073;&#10073;':'&#9654;';
  window.addEventListener('resize', ()=>{ A.resize(); });
  document.getElementById('load').style.display='none';
  requestAnimationFrame(A.frame);
})();
