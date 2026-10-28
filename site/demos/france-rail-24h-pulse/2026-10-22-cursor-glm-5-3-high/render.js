// render.js — static layer, train animation, overlays
"use strict";
var A = window.A = window.A || {};

A.resize = function(){
  const c = A.canvas, dpr = Math.min(window.devicePixelRatio||1, 2);
  const w = window.innerWidth, h = window.innerHeight;
  c.width = w*dpr; c.height = h*dpr; c.style.width=w+'px'; c.style.height=h+'px';
  A.ctx = c.getContext('2d'); A.ctx.setTransform(dpr,0,0,dpr,0,0);
  A.dpr = dpr; A.vw = w; A.vh = h;
  if(!A.staticCanvas){ A.staticCanvas = document.createElement('canvas'); }
  A.staticCanvas.width = w*dpr; A.staticCanvas.height = h*dpr;
  A.sctx = A.staticCanvas.getContext('2d'); A.sctx.setTransform(dpr,0,0,dpr,0,0);
  if(!A.isoCanvas){ A.isoCanvas = document.createElement('canvas'); }
  A.isoCanvas.width = w*dpr; A.isoCanvas.height = h*dpr;
  A.ico = A.isoCanvas.getContext('2d'); A.ico.setTransform(dpr,0,0,dpr,0,0);
  A.updateStationScreen();
  A.drawStatic();
  if(A.accessOrigin!=null) A.drawIso();
};

A.drawStatic = function(){
  const g = A.sctx, W=A.vw, H=A.vh;
  g.clearRect(0,0,W,H);
  const bg = g.createRadialGradient(W*0.5, H*0.42, 0, W*0.5, H*0.5, Math.max(W,H)*0.75);
  bg.addColorStop(0, '#0a1426'); bg.addColorStop(0.6,'#070d1a'); bg.addColorStop(1,'#03070f');
  g.fillStyle = bg; g.fillRect(0,0,W,H);
  A.drawGraticule(g);
  A.drawFrance(g);
  if(A.mode==='corridor') A.drawCorridor(g); else A.drawRFN(g);
  A.drawStationsStatic(g, A.mode==='corridor');
  A.drawStationLabels(g);
};

A.drawStationLabels = function(g){
  if(A.T.scale < 28) return; // only when zoomed in
  g.save();
  g.font = '600 11px Rajdhani, sans-serif';
  g.textBaseline = 'middle';
  for(let i=0;i<A.stations.length;i++){
    const calls = A.stCalls[i];
    if(calls < 240) continue;
    const x=A.stPx[i], y=A.stPy[i];
    if(x<-40||x>A.vw+40||y<-20||y>A.vh+20) continue;
    const nm = A.stations[i].name;
    const lbl = nm.replace(/^Paris /,'').replace(/^Lyon /,'').replace(/^Bordeaux /,'').replace(/^Marseille /,'');
    g.fillStyle = 'rgba(0,0,0,0.55)';
    g.fillRect(x+7, y-7, g.measureText(lbl).width+6, 14);
    g.fillStyle = calls>=400 ? '#eaf4ff' : '#9fc4f0';
    g.fillText(lbl, x+10, y);
  }
  g.restore();
};

A.drawGraticule = function(g){
  g.save(); g.strokeStyle='rgba(54,163,255,0.05)'; g.lineWidth=1;
  for(let lon=-6; lon<=9; lon++){ const x=A.sx(A.wX(lon)); g.beginPath(); g.moveTo(x,0); g.lineTo(x,A.vh); g.stroke(); }
  for(let lat=42; lat<=51; lat++){ const y=A.sy(A.wY(lat)); g.beginPath(); g.moveTo(0,y); g.lineTo(A.vw,y); g.stroke(); }
  g.restore();
};

A.drawFrance = function(g){
  const polys = A.france.coordinates;
  g.save(); g.fillStyle='#0b1830'; g.strokeStyle='rgba(54,163,255,0.22)'; g.lineWidth=1;
  for(const poly of polys){
    g.beginPath();
    for(let r=0;r<poly.length;r++){
      const ring=poly[r];
      for(let i=0;i<ring.length;i++){ const x=A.sx(A.wX(ring[i][0])),y=A.sy(A.wY(ring[i][1])); if(i===0)g.moveTo(x,y); else g.lineTo(x,y); }
    }
    g.closePath(); g.fill(); g.stroke();
  }
  g.restore();
};

A.drawRFN = function(g){
  g.save(); g.lineCap='round'; g.lineJoin='round';
  g.strokeStyle='rgba(70,120,180,0.22)'; g.lineWidth=Math.max(0.5, A.T.scale*0.012);
  for(const r of A.rfn){
    const w=r.w, n=w.length/2;
    g.beginPath(); g.moveTo(A.sx(w[0]),A.sy(w[1]));
    for(let i=1;i<n;i++) g.lineTo(A.sx(w[i*2]),A.sy(w[i*2+1]));
    g.stroke();
  }
  g.restore();
};

A.drawCorridor = function(g){
  g.save(); g.lineCap='round'; g.lineJoin='round';
  const mf=A.maxFlow;
  for(const c of A.corridor){
    if(!c.w||c.f<=0) continue;
    const t=Math.pow(c.f/mf,0.45);
    g.lineWidth=0.6+t*5.5;
    const r=Math.round(40+t*215), gg=Math.round(120+t*135), b=Math.round(200+t*55);
    g.strokeStyle=`rgba(${r},${gg},${b},${0.25+t*0.65})`;
    if(t>0.6){ g.shadowColor=`rgba(${r},${gg},${b},0.7)`; g.shadowBlur=6*t; } else g.shadowBlur=0;
    const w=c.w, n=w.length/2;
    g.beginPath(); g.moveTo(A.sx(w[0]),A.sy(w[1]));
    for(let i=1;i<n;i++) g.lineTo(A.sx(w[i*2]),A.sy(w[i*2+1]));
    g.stroke();
  }
  g.shadowBlur=0; g.restore();
};

A.drawStationsStatic = function(g, majorOnly){
  const N=A.stWX.length;
  g.save();
  for(let i=0;i<N;i++){
    const calls=A.stCalls[i];
    if(majorOnly && calls<60) continue;
    if(!majorOnly && calls<6) continue;
    const x=A.stPx[i], y=A.stPy[i];
    if(x<-20||x>A.vw+20||y<-20||y>A.vh+20) continue;
    let spr, sz;
    if(calls>=300){ spr=A.sprites.stBig; sz=14; }
    else if(calls>=80){ spr=A.sprites.stMed; sz=11; }
    else { spr=A.sprites.stSmall; sz=8; }
    g.drawImage(spr, x-sz/2, y-sz/2, sz, sz);
  }
  g.restore();
};

A.drawIso = function(){
  const g=A.ico; g.clearRect(0,0,A.vw,A.vh);
  if(A.accessOrigin==null||A.accessBucket==null) return;
  const N=A.stWX.length;
  g.save();
  for(let b=0;b<5;b++){
    const col=A.bucketColor[b];
    g.fillStyle=A.hexA(col,0.9); g.shadowColor=col; g.shadowBlur=8;
    for(let i=0;i<N;i++){
      if(A.accessBucket[i]!==b) continue;
      const x=A.stPx[i], y=A.stPy[i];
      if(x<-20||x>A.vw+20||y<-20||y>A.vh+20) continue;
      const rad=Math.max(2.2, Math.min(6, 2+Math.sqrt(A.stCalls[i])*0.18));
      g.beginPath(); g.arc(x,y,rad,0,Math.PI*2); g.fill();
    }
  }
  g.shadowBlur=0;
  const o=A.accessOrigin;
  g.strokeStyle='#fff'; g.lineWidth=2; g.shadowColor='#fff'; g.shadowBlur=14;
  g.beginPath(); g.arc(A.stPx[o],A.stPy[o],7,0,Math.PI*2); g.stroke();
  g.beginPath(); g.arc(A.stPx[o],A.stPy[o],11,0,Math.PI*2); g.stroke();
  g.shadowBlur=0; g.restore();
};

// ---- main frame ----
A.frame = function(now){
  if(!A.lastT) A.lastT = now;
  const dt = (now - A.lastT)/1000; A.lastT = now;
  if(A.playing && A.mode!=='access'){
    A.clock += dt * A.speed;
    if(A.clock >= 86400) A.clock -= 86400;
    A.syncTimeline();
  }
  const ctx = A.ctx;
  ctx.clearRect(0,0,A.vw,A.vh);
  ctx.drawImage(A.staticCanvas, 0, 0, A.vw, A.vh);
  if(A.mode==='access' && A.accessOrigin!=null) ctx.drawImage(A.isoCanvas, 0,0,A.vw,A.vh);
  if(A.mode==='live') A.drawTrains(A.clock);
  A.drawSelection(ctx);
  A.drawHover(ctx);
  A.updateLiveStats();
  requestAnimationFrame(A.frame);
};

A.drawTrains = function(t){
  const ctx = A.ctx, M = A.tripCount;
  const show = [A.showTGV, A.showIC, A.showTER];
  const sprites = [A.sprites.TGV, A.sprites.IC, A.sprites.TER];
  const sizes = [10, 9, 7.5];
  ctx.save();
  for(let tr=0; tr<M; tr++){
    let f=A.tripFirst[tr], l=A.tripLast[tr];
    let te=t;
    if(t<f && l>=86400) te=t+86400;     // night train continuing past midnight
    if(te<f || te>l) continue;
    const cat = A.tripCat[tr];
    if(!show[cat]) continue;
    const s0 = A.tripSeg0[tr], n = A.tripSegN[tr];
    let lo=0, hi=n-1, idx=-1;
    while(lo<=hi){ const mid=(lo+hi)>>1; if(A.segDep[s0+mid]<=te){idx=mid;lo=mid+1;} else hi=mid-1; }
    if(idx<0) continue;
    const dep=A.segDep[s0+idx], arr=A.segArr[s0+idx];
    const ia=A.segA[s0+idx], ib=A.segB[s0+idx];
    if(ia===65535||ib===65535) continue;
    let frac = arr>dep ? (te-dep)/(arr-dep) : 0;
    if(frac<0)frac=0; if(frac>1)frac=1;
    const x = A.stPx[ia]+(A.stPx[ib]-A.stPx[ia])*frac;
    const y = A.stPy[ia]+(A.stPy[ib]-A.stPy[ia])*frac;
    if(x<-30||x>A.vw+30||y<-30||y>A.vh+30) continue;
    const spr = (cat===0 && A.tripOUIGO[tr]) ? A.sprites.OUIGO : sprites[cat];
    const sz = sizes[cat];
    ctx.drawImage(spr, x-sz/2, y-sz/2, sz, sz);
  }
  ctx.restore();
};

A.drawSelection = function(ctx){
  if(A.selTrip!=null){
    const tr = A.selTrip, s0 = A.tripSeg0[tr], n = A.tripSegN[tr];
    const cat = A.tripCat[tr];
    const col = cat===0?'#ff5436':cat===1?'#36a3ff':'#2ee59d';
    ctx.save();
    ctx.strokeStyle=col; ctx.lineWidth=2.4; ctx.lineCap='round'; ctx.lineJoin='round';
    ctx.shadowColor=col; ctx.shadowBlur=10;
    ctx.beginPath(); let started=false;
    for(let i=0;i<n;i++){
      const ia=A.segA[s0+i], ib=A.segB[s0+i];
      if(ia===65535||ib===65535) continue;
      if(!started){ ctx.moveTo(A.stPx[ia],A.stPy[ia]); started=true; }
      ctx.lineTo(A.stPx[ib],A.stPy[ib]);
    }
    ctx.stroke(); ctx.shadowBlur=0;
    ctx.fillStyle='#fff';
    const stops = A.tripStops(tr);
    for(const s of stops){
      const x=A.stPx[s.idx], y=A.stPy[s.idx];
      if(x<-20||x>A.vw+20||y<-20||y>A.vh+20) continue;
      ctx.beginPath(); ctx.arc(x,y,3,0,Math.PI*2); ctx.fill();
    }
    ctx.restore();
  }
  if(A.selStation!=null){
    const i=A.selStation;
    ctx.save();
    ctx.strokeStyle = A.mode==='access'?'#fff':'#36a3ff'; ctx.lineWidth=2;
    ctx.shadowColor=ctx.strokeStyle; ctx.shadowBlur=12;
    ctx.beginPath(); ctx.arc(A.stPx[i],A.stPy[i],8,0,Math.PI*2); ctx.stroke();
    ctx.restore();
  }
};

A.drawHover = function(ctx){
  if(A.hoverStation==null) return;
  const i=A.hoverStation;
  ctx.save(); ctx.strokeStyle='rgba(255,255,255,0.7)'; ctx.lineWidth=1.5;
  ctx.beginPath(); ctx.arc(A.stPx[i],A.stPy[i],6,0,Math.PI*2); ctx.stroke();
  ctx.restore();
};

// stops of a trip: [{idx, arr, dep, name}]
A.tripStops = function(tr){
  const s0 = A.tripSeg0[tr], n = A.tripSegN[tr];
  const out = [];
  if(n<=0) return out;
  out.push({idx:A.segA[s0], arr:A.segDep[s0], dep:A.segDep[s0], name:A.stName(A.segA[s0])});
  for(let i=0;i<n;i++){
    out.push({idx:A.segB[s0+i], arr:A.segArr[s0+i], dep:A.segDep[s0+i+1]||A.segArr[s0+i], name:A.stName(A.segB[s0+i])});
  }
  return out;
};

A.stName = function(i){ return A.stations[i] ? A.stations[i].name : '?'; };

