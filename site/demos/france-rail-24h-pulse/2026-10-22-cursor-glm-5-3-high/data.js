// data.js — load JSON, build typed-array indices, precompute traffic profile
"use strict";
var A = window.A = window.A || {};

A.loadAll = async function(){
  const lp = document.getElementById('lp');
  const step = (m)=>{ if(lp) lp.textContent = m; };
  step('chargement des gares…');
  const [stations, trips, rfn, corridor, departures, meta, france] = await Promise.all([
    fetch('data/stations.json').then(r=>r.json()),
    fetch('data/trips.json').then(r=>r.json()),
    fetch('data/rfn.json').then(r=>r.json()),
    fetch('data/corridor.json').then(r=>r.json()),
    fetch('data/departures.json').then(r=>r.json()),
    fetch('data/meta.json').then(r=>r.json()),
    fetch('data/france.geojson').then(r=>r.json()),
  ]);
  A.meta = meta;

  // ---- stations ----
  step('indexation des gares…');
  const N = stations.length;
  A.stations = stations; // [{u,name,lat,lon,calls,tgv,ic,ter}]
  A.uicIdx = new Map();
  A.stLon = new Float32Array(N);
  A.stLat = new Float32Array(N);
  A.stWX = new Float32Array(N);
  A.stWY = new Float32Array(N);
  A.stPx = new Float32Array(N);
  A.stPy = new Float32Array(N);
  A.stCalls = new Int32Array(N);
  for(let i=0;i<N;i++){
    const s = stations[i];
    A.uicIdx.set(s.u, i);
    A.stLon[i]=s.lon; A.stLat[i]=s.lat;
    A.stWX[i]=A.wX(s.lon); A.stWY[i]=A.wY(s.lat);
    A.stCalls[i]=s.calls||0;
  }
  A.updateStationScreen();

  // ---- trips -> typed arrays ----
  step('indexation des trains…');
  const M = trips.length;
  A.tripCat = new Uint8Array(M);     // 0 TGV,1 IC,2 TER
  A.tripOUIGO = new Uint8Array(M);
  A.tripNum = new Int32Array(M);
  A.tripHead = new Array(M);
  A.tripFirst = new Float32Array(M);
  A.tripLast = new Float32Array(M);
  A.tripSeg0 = new Uint32Array(M);  // offset into seg arrays
  A.tripSegN = new Uint16Array(M);
  // first pass: count segments
  let totSeg = 0;
  for(let t=0;t<M;t++){ const n = trips[t].s.length-1; A.tripSegN[t]=n; totSeg += n; }
  A.segDep = new Float32Array(totSeg);
  A.segArr = new Float32Array(totSeg);
  A.segA  = new Uint16Array(totSeg);
  A.segB  = new Uint16Array(totSeg);
  let off = 0;
  for(let t=0;t<M;t++){
    const tr = trips[t];
    A.tripCat[t] = tr.c==='TGV'?0:tr.c==='IC'?1:2;
    A.tripOUIGO[t] = tr.o?1:0;
    A.tripNum[t] = tr.n||0;
    A.tripHead[t] = tr.h||'';
    const stops = tr.s;
    A.tripSeg0[t] = off;
    let first = 1e9, last = -1;
    for(let i=0;i<stops.length-1;i++){
      const a = stops[i], b = stops[i+1];
      const ia = A.uicIdx.get(a[0]), ib = A.uicIdx.get(b[0]);
      const dep = a[2], arr = b[1];
      A.segDep[off]=dep; A.segArr[off]=arr;
      A.segA[off]= ia==null?65535:ia; A.segB[off]= ib==null?65535:ib;
      if(dep<first) first=dep; if(arr>last) last=arr;
      off++;
    }
    A.tripFirst[t]=first; A.tripLast[t]=last;
  }
  A.tripCount = M;

  // ---- rfn static network (project polylines once into world coords) ----
  step('réseau ferré national…');
  A.rfn = rfn.map(r=>{
    const p = new Float32Array(r.p.length*2);
    for(let i=0;i<r.p.length;i++){ p[i*2]=A.wX(r.p[i][0]); p[i*2+1]=A.wY(r.p[i][1]); }
    return {c:r.c, w:p};
  });

  // ---- corridor (flow) ----
  A.corridor = corridor.map(r=>{
    const p = r.p ? new Float32Array(r.p.length*2) : null;
    if(r.p) for(let i=0;i<r.p.length;i++){ p[i*2]=A.wX(r.p[i][0]); p[i*2+1]=A.wY(r.p[i][1]); }
    return {c:r.c, f:r.f||0, cats:r.cats||{TGV:0,IC:0,TER:0}, w:p};
  });
  A.maxFlow = 1;
  for(const c of A.corridor) if(c.f>A.maxFlow) A.maxFlow=c.f;

  // ---- departures graph (accessibility) ----
  step("graphe d\u2019accessibilit\u00e9\u2026");
  A.departures = departures.map(arr => {
    // arr: [[dep,nextIdx,arr,tripIdx],...] -> flat Float32Array [dep,next,arr,...]
    const f = new Float32Array(arr.length*3);
    for(let i=0;i<arr.length;i++){ f[i*3]=arr[i][0]; f[i*3+1]=arr[i][1]; f[i*3+2]=arr[i][2]; }
    return f;
  });

  // ---- france outline ----
  A.france = france; // MultiPolygon

  // ---- traffic profile: active trains per minute per category ----
  step('profil de trafic…');
  A.computeProfile();

  step('prêt');
  return {stations:N, trips:M};
};

A.updateStationScreen = function(){
  for(let i=0;i<A.stWX.length;i++){
    A.stPx[i] = A.sx(A.stWX[i]);
    A.stPy[i] = A.sy(A.stWY[i]);
  }
};

A.computeProfile = function(){
  const MINS = 1440;
  // diff arrays per category
  const diff = [new Int32Array(MINS+1), new Int32Array(MINS+1), new Int32Array(MINS+1)];
  for(let t=0;t<A.tripCount;t++){
    const cat = A.tripCat[t];
    const f = A.tripFirst[t], l = A.tripLast[t];
    if(f>=1e8) continue;
    let m0 = Math.floor(f/60), m1 = Math.floor(l/60);
    if(m0<0)m0=0; if(m1>=MINS)m1=MINS-1;
    diff[cat][m0]++; diff[cat][m1+1]--;
  }
  const prof = new Int32Array(MINS);
  const pc = [new Int32Array(MINS),new Int32Array(MINS),new Int32Array(MINS)];
  let acc=[0,0,0];
  for(let m=0;m<MINS;m++){
    for(let c=0;c<3;c++){ acc[c]+=diff[c][m]; pc[c][m]=acc[c]; prof[m]+=acc[c]; }
  }
  A.profile = prof; A.profileCat = pc;
  A.maxProf = 1; for(let m=0;m<MINS;m++) if(prof[m]>A.maxProf) A.maxProf=prof[m];
};
