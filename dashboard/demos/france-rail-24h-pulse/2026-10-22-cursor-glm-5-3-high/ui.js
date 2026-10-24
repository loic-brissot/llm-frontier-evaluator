// ui.js — timeline, stats, legend, details, pointer interactions
"use strict";
var A = window.A = window.A || {};

A.showTGV = true; A.showIC = true; A.showTER = true;
A.clock = 8*3600;       // start at 08:00
A.speed = 900;
A.playing = true;
A.mode = 'live';

A.fmtTime = function(sec){
  sec = Math.floor(sec); if(sec<0)sec+=86400; if(sec>=86400)sec-=86400;
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
  return String(h).padStart(2,'0')+':'+String(m).padStart(2,'0');
};

A.buildLegend = function(){
  const el = document.getElementById('legend');
  const cats = [['TGV','TGV / OUIGO',A.meta?A.meta.cats.TGV:0,'#ff5436'],
                ['IC','Intercités',A.meta?A.meta.cats.IC:0,'#36a3ff'],
                ['TER','TER',A.meta?A.meta.cats.TER:0,'#2ee59d']];
  el.innerHTML = '';
  for(const [k,nm,ct,col] of cats){
    const row = document.createElement('div');
    row.className = 'legend-row';
    row.innerHTML = `<div class="dot" style="background:${col};color:${col}"></div>
      <div class="nm">${nm}</div><div class="ct mono">${(ct||0).toLocaleString('fr')}</div>`;
    row.onclick = ()=>{
      const on = row.classList.toggle('off');
      if(k==='TGV') A.showTGV = !on; if(k==='IC') A.showIC = !on; if(k==='TER') A.showTER = !on;
    };
    el.appendChild(row);
  }
};

A.buildBusiest = function(){
  const el = document.getElementById('busiest');
  const sorted = A.stations.slice().sort((a,b)=>(b.calls||0)-(a.calls||0)).slice(0,10);
  el.innerHTML = sorted.map((s,i)=>
    `<div class="b-row" data-u="${s.u}"><span class="rk mono">${i+1}</span>
     <span class="nm">${s.name}</span><span class="v mono">${s.calls}</span></div>`).join('');
  el.querySelectorAll('.b-row').forEach(r=>{
    r.onclick = ()=>{ const idx = A.uicIdx.get(r.dataset.u); if(idx!=null) A.selectStation(idx); };
    r.style.cursor='pointer';
  });
};

A.drawProfile = function(){
  const cv = document.getElementById('profile');
  const dpr = Math.min(window.devicePixelRatio||1,2);
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W*dpr; cv.height = H*dpr;
  const g = cv.getContext('2d'); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  const prof = A.profile, mp = A.maxProf;
  // gridlines
  g.strokeStyle='rgba(54,163,255,0.08)'; g.lineWidth=1;
  for(let i=0;i<4;i++){ const y=H*(i/3); g.beginPath(); g.moveTo(0,y); g.lineTo(W,y); g.stroke(); }
  // filled area
  g.beginPath(); g.moveTo(0,H);
  for(let m=0;m<1440;m++){ const x=m/1439*W; const y=H - (prof[m]/mp)*H*0.92; g.lineTo(x,y); }
  g.lineTo(W,H); g.closePath();
  const grd = g.createLinearGradient(0,0,0,H);
  grd.addColorStop(0,'rgba(54,163,255,0.55)'); grd.addColorStop(1,'rgba(54,163,255,0.02)');
  g.fillStyle=grd; g.fill();
  g.strokeStyle='rgba(120,180,255,0.7)'; g.lineWidth=1.2; g.beginPath();
  for(let m=0;m<1440;m++){ const x=m/1439*W; const y=H-(prof[m]/mp)*H*0.92; if(m===0)g.moveTo(x,y); else g.lineTo(x,y); }
  g.stroke();
  A._profCanvas = cv;
};

A.updateLiveStats = function(){
  if(!A.profileCat) return;
  const m = Math.floor(A.clock/60) % 1440;
  if(m === A._lastStatMin) return;
  A._lastStatMin = m;
  const tgv = A.profileCat[0][m], ic = A.profileCat[1][m], ter = A.profileCat[2][m];
  document.getElementById('stTGV').textContent = tgv;
  document.getElementById('stIC').textContent = ic;
  document.getElementById('stTER').textContent = ter;
  document.getElementById('stTot').textContent = tgv+ic+ter;
  A.drawProfileMarker();
};

A.drawProfileMarker = function(){
  const cv = A._profCanvas; if(!cv) return;
  A.drawProfile();
  const g = cv.getContext('2d'), W=cv.clientWidth, H=cv.clientHeight, dpr=Math.min(window.devicePixelRatio||1,2);
  g.setTransform(dpr,0,0,dpr,0,0);
  const x = (A.clock/86399)*W;
  g.strokeStyle='rgba(255,255,255,0.85)'; g.lineWidth=1.2;
  g.beginPath(); g.moveTo(x,0); g.lineTo(x,H); g.stroke();
  g.fillStyle='#fff'; g.beginPath(); g.arc(x,2,2.5,0,Math.PI*2); g.fill();
};

A.syncTimeline = function(){
  const f = A.clock/86399;
  document.getElementById('tlFill').style.width = (f*100)+'%';
  document.getElementById('tlKnob').style.left = (f*100)+'%';
  document.getElementById('clk').textContent = A.fmtTime(A.clock);
};

// ---- mode switching ----
A.setMode = function(mode){
  A.mode = mode;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.mode===mode));
  A.selTrip = null;
  const hint = document.getElementById('modehint');
  if(mode==='live') hint.textContent = 'Cliquez un train ou une gare · molette = zoom · glisser = déplacer';
  if(mode==='corridor') hint.textContent = 'Épaisseur et luminance des lignes = trafic cumulé 24 h';
  if(mode==='access') hint.textContent = 'Cliquez une gare pour calculer les isochrones d\u2019accès';
  document.getElementById('isoSec').style.display = mode==='access' ? '' : 'none';
  document.getElementById('bottom').classList.toggle('hidden', false);
  if(mode==='access' && A.accessOrigin==null){
    // pre-select a central hub with rich national coverage
    const pref = ['Lyon Part Dieu','Paris Gare de Lyon','Dijon Ville','Strasbourg'];
    let pick = -1;
    for(const nm of pref){ const i = A.stations.findIndex(s=>s.name===nm); if(i>=0){ pick=i; break; } }
    if(pick<0) pick = 0;
    A.selectStation(pick);
  }
  if(mode!=='access'){ A.accessOrigin=null; A.accessBucket=null; }
  A.drawStatic();
  A.closeRight();
};

A.findStationByName = function(q){
  q = q.toUpperCase();
  let best=null, bi=0;
  for(let i=0;i<A.stations.length;i++){
    const n = A.stations[i].name.toUpperCase();
    if(n===q) return i;
    if(n.startsWith(q) && bi<2){ best=i; bi=2; }
    if(n.includes(q) && bi<1){ best=i; bi=1; }
  }
  return best;
};

// ---- selection ----
A.selectStation = function(idx){
  A.selStation = idx; A.selTrip = null;
  if(A.mode==='access'){
    A.computeAccess(idx, A.clock);
    A.drawIso();
    A.showAccessLegend();
  }
  A.showDetailsStation(idx);
  A.openRight();
};

A.selectTrip = function(tr){
  A.selTrip = tr; A.selStation = null;
  A.showDetailsTrip(tr);
  A.openRight();
};

A.openRight = function(){ document.getElementById('right').classList.add('open'); };
A.closeRight = function(){ document.getElementById('right').classList.remove('open'); A.selTrip=null; A.selStation=null; };

A.showDetailsStation = function(idx){
  const s = A.stations[idx];
  const tag = s.tgv>0&&s.ic>0&&s.ter>0 ? 'tgv' : s.tgv>0?'tgv':s.ic>0?'ic':'ter';
  let html = `<div class="d-tag ${tag}">GARE</div>
    <div class="d-title">${s.name}</div>
    <div class="d-sub">UIC ${s.u} · ${s.calls} courses / jour</div>
    <div class="d-mini">
      <span class="swatch" style="background:#ff5436"></span>TGV ${s.tgv} &nbsp;
      <span class="swatch" style="background:#36a3ff"></span>Intercités ${s.ic} &nbsp;
      <span class="swatch" style="background:#2ee59d"></span>TER ${s.ter}
    </div>`;
  if(A.mode==='access' && A.accessBucket){
    html += '<div class="d-mini" style="margin-top:6px">Temps d\u2019accès depuis cette gare à ' + A.fmtTime(A.clock) + ' :</div>';
    const labels = A.bucketLabel;
    for(let b=0;b<5;b++){
      html += `<div class="iso-row"><span class="sw" style="background:${A.bucketColor[b]}"></span>
        <span>${labels[b]}</span><span class="ct">${A.accessCounts[b]} gares</span></div>`;
    }
    html += `<div class="iso-row"><span class="sw" style="background:#3a4a66"></span>
      <span>Non accessible</span><span class="ct">${A.accessCounts[5]} gares</span></div>`;
  }
  document.getElementById('details').innerHTML = html;
};

A.showDetailsTrip = function(tr){
  const cat = A.tripCat[tr];
  const catName = cat===0?(A.tripOUIGO[tr]?'OUIGO':'TGV'):cat===1?'Intercités':'TER';
  const tag = cat===0?'tgv':cat===1?'ic':'ter';
  const stops = A.tripStops(tr);
  let html = `<div class="d-tag ${tag}">${catName}</div>
    <div class="d-title">Train ${A.tripNum[tr]||'—'}</div>
    <div class="d-sub">${A.tripHead[tr]||''} · ${stops.length} arrêts</div>
    <div class="tt"><div class="th"><div>Heure</div><div>Gare</div><div>PK</div></div>`;
  const curSeg = A.currentSegIndex(tr);
  stops.forEach((s,i)=>{
    const cls = (curSeg!=null && (i===curSeg||i===curSeg+1)) ? 'cur' : '';
    html += `<div class="tr ${cls}"><div class="t">${A.fmtTime(s.arr)}</div>
      <div class="n">${s.name}</div><div class="p">${i+1}</div></div>`;
  });
  html += '</div>';
  document.getElementById('details').innerHTML = html;
};

A.currentSegIndex = function(tr){
  const s0=A.tripSeg0[tr], n=A.tripSegN[tr], t=A.clock;
  let lo=0,hi=n-1,idx=-1;
  while(lo<=hi){ const mid=(lo+hi)>>1; if(A.segDep[s0+mid]<=t){idx=mid;lo=mid+1;} else hi=mid-1; }
  return idx;
};

A.showAccessLegend = function(){
  const el = document.getElementById('isoLegend');
  let html='';
  for(let b=0;b<5;b++){
    html += `<div class="iso-row"><span class="sw" style="background:${A.bucketColor[b]}"></span>
      <span>${A.bucketLabel[b]}</span><span class="ct">${A.accessCounts[b]} gares</span></div>`;
  }
  el.innerHTML = html;
};

// ---- hit testing ----
A.findStationAt = function(px, py){
  let best=-1, bd=1e9;
  const r2 = (12/A.T.scale*60); // not used; use pixel radius
  const R = 9; // pixel radius
  for(let i=0;i<A.stPx.length;i++){
    const dx=A.stPx[i]-px, dy=A.stPy[i]-py;
    const d=dx*dx+dy*dy;
    if(d<R*R && d<bd){ bd=d; best=i; }
  }
  return best;
};

A.findTripAt = function(px, py){
  let best=-1, bd=1e9; const R=9, R2=R*R, t=A.clock;
  const show=[A.showTGV,A.showIC,A.showTER];
  for(let tr=0;tr<A.tripCount;tr++){
    if(t<A.tripFirst[tr]||t>A.tripLast[tr]) continue;
    if(!show[A.tripCat[tr]]) continue;
    const s0=A.tripSeg0[tr], n=A.tripSegN[tr];
    let lo=0,hi=n-1,idx=-1;
    while(lo<=hi){ const mid=(lo+hi)>>1; if(A.segDep[s0+mid]<=t){idx=mid;lo=mid+1;} else hi=mid-1; }
    if(idx<0) continue;
    const ia=A.segA[s0+idx], ib=A.segB[s0+idx];
    if(ia===65535||ib===65535) continue;
    const dep=A.segDep[s0+idx], arr=A.segArr[s0+idx];
    let frac=arr>dep?(t-dep)/(arr-dep):0; if(frac<0)frac=0; if(frac>1)frac=1;
    const x=A.stPx[ia]+(A.stPx[ib]-A.stPx[ia])*frac, y=A.stPy[ia]+(A.stPy[ib]-A.stPy[ia])*frac;
    const dx=x-px, dy=y-py, d=dx*dx+dy*dy;
    if(d<R2 && d<bd){ bd=d; best=tr; }
  }
  return best;
};

// ---- pointer interactions ----
A.attachPointer = function(){
  const c = A.canvas;
  let drag=false, lx=0, ly=0, moved=false;
  c.addEventListener('mousedown', e=>{
    drag=true; moved=false; lx=e.clientX; ly=e.clientY; c.classList.add('dragging');
  });
  window.addEventListener('mousemove', e=>{
    if(drag){
      const dx=e.clientX-lx, dy=e.clientY-ly; lx=e.clientX; ly=e.clientY;
      if(Math.abs(dx)+Math.abs(dy)>2) moved=true;
      A.T.tx += dx; A.T.ty += dy; A.updateStationScreen(); A.drawStatic();
      if(A.accessOrigin!=null) A.drawIso();
    } else {
      A.handleHover(e.clientX, e.clientY);
    }
  });
  window.addEventListener('mouseup', e=>{
    if(drag && !moved){ A.handleClick(e.clientX, e.clientY); }
    drag=false; c.classList.remove('dragging');
  });
  c.addEventListener('wheel', e=>{
    e.preventDefault();
    const factor = e.deltaY<0 ? 1.18 : 1/1.18;
    A.zoomAt(e.clientX, e.clientY, factor);
  }, {passive:false});
  let tstart=null;
  c.addEventListener('touchstart', e=>{
    if(e.touches.length===1){ tstart={x:e.touches[0].clientX,y:e.touches[0].clientY,moved:false}; }
  });
  c.addEventListener('touchmove', e=>{
    if(e.touches.length===1 && tstart){
      const dx=e.touches[0].clientX-tstart.x, dy=e.touches[0].clientY-tstart.y;
      if(Math.abs(dx)+Math.abs(dy)>3) tstart.moved=true;
      A.T.tx+=dx; A.T.ty+=dy; tstart.x=e.touches[0].clientX; tstart.y=e.touches[0].clientY;
      A.updateStationScreen(); A.drawStatic(); if(A.accessOrigin!=null)A.drawIso();
    }
  }, {passive:true});
  c.addEventListener('touchend', e=>{
    if(tstart && !tstart.moved) A.handleClick(tstart.x, tstart.y);
    tstart=null;
  });
};

A.zoomAt = function(px, py, factor){
  const s = A.T.scale * factor;
  const wx = (px - A.T.tx)/A.T.scale;
  const wy = -(py - A.T.ty)/A.T.scale;
  A.T.scale = Math.max(8, Math.min(900, s));
  A.T.tx = px - wx*A.T.scale;
  A.T.ty = py + wy*A.T.scale;
  A.updateStationScreen(); A.drawStatic();
  if(A.accessOrigin!=null) A.drawIso();
};

A.handleHover = function(px, py){
  const i = A.findStationAt(px, py);
  if(i !== A.hoverStation){ A.hoverStation = i>=0?i:null; }
  const tip = document.getElementById('tip');
  if(i>=0){
    const s = A.stations[i];
    tip.style.display='block';
    tip.style.left = (px+14)+'px'; tip.style.top = (py+14)+'px';
    tip.innerHTML = `<div class="tn">${s.name}</div><div class="ts">UIC ${s.u} · ${s.calls} courses · TGV ${s.tgv} IC ${s.ic} TER ${s.ter}</div>`;
    A.canvas.style.cursor = 'pointer';
  } else {
    tip.style.display='none';
    A.canvas.style.cursor = A.canvas.classList.contains('dragging')?'grabbing':'grab';
  }
};

A.handleClick = function(px, py){
  const ti = A.findTripAt(px, py);
  if(ti>=0 && A.mode==='live'){ A.selectTrip(ti); return; }
  const si = A.findStationAt(px, py);
  if(si>=0){ A.selectStation(si); return; }
  A.closeRight();
};

// ---- timeline controls ----
A.attachTimeline = function(){
  const wrap = document.getElementById('tlWrap');
  let drag=false;
  const setFromX = (cx)=>{
    const r = wrap.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (cx-r.left)/r.width));
    A.clock = f*86399; A.syncTimeline(); A._lastStatMin=-1;
    if(A.mode==='access' && A.accessOrigin!=null){ A.computeAccess(A.accessOrigin, A.clock); A.drawIso(); A.showAccessLegend(); A.showDetailsStation(A.accessOrigin); }
  };
  wrap.addEventListener('mousedown', e=>{ drag=true; setFromX(e.clientX); });
  window.addEventListener('mousemove', e=>{ if(drag) setFromX(e.clientX); });
  window.addEventListener('mouseup', ()=>{ drag=false; });
  const tk = document.getElementById('tlTicks');
  let h=''; for(let i=0;i<=24;i+=3){ h+=`<div>${String(i).padStart(2,'0')}h</div>`; }
  tk.innerHTML = h;
  document.getElementById('play').onclick = ()=>{ A.playing = !A.playing; document.getElementById('play').innerHTML = A.playing?'&#10073;&#10073;':'&#9654;'; document.getElementById('play').style.opacity = A.playing?1:0.6; };
  document.getElementById('reset').onclick = ()=>{ A.clock = 0; A.syncTimeline(); A._lastStatMin=-1; };
  document.getElementById('closeRight').onclick = ()=>{ A.closeRight(); };
  document.querySelectorAll('.spd').forEach(b=>{
    b.onclick = ()=>{ document.querySelectorAll('.spd').forEach(x=>x.classList.remove('active')); b.classList.add('active'); A.speed = +b.dataset.spd; };
  });
  document.querySelectorAll('.tab').forEach(t=>{ t.onclick = ()=> A.setMode(t.dataset.mode); });
};


