// access.js — time-dependent earliest-arrival Dijkstra for accessibility isochrones
"use strict";
var A = window.A = window.A || {};

A.MIN_TRANSFER = 150; // seconds minimum connection time at intermediate stations

// Run earliest-arrival search from originIdx departing at time t0 (seconds).
// Returns Float32Array dist (earliest arrival sec per station), Infinity if unreachable.
A.runAccess = function(originIdx, t0){
  const N = A.stWX.length;
  const dist = new Float64Array(N); for(let i=0;i<N;i++) dist[i]=Infinity;
  const prev = new Int32Array(N); prev.fill(-1);     // previous station for path
  const prevTrip = new Int32Array(N); prevTrip.fill(-1);
  dist[originIdx] = t0;
  // binary heap of [time, idx]
  const heap = new Float64Array(N*2); // packed: even=time, odd=idx
  let hsz = 0;
  const push = (t,i)=>{ let p=hsz*2; heap[p]=t; heap[p+1]=i; hsz++; let c=hsz-1;
    while(c>0){ let pa=(c-1)>>1; if(heap[2*pa]<=heap[2*c]) break;
      [heap[2*pa],heap[2*c]]=[heap[2*c],heap[2*pa]]; [heap[2*pa+1],heap[2*c+1]]=[heap[2*c+1],heap[2*pa+1]]; c=pa; } };
  const pop = ()=>{ const top=[heap[0],heap[1]]; hsz--; if(hsz>0){
    heap[0]=heap[2*hsz]; heap[1]=heap[2*hsz+1]; let c=0;
    while(true){ let l=2*c+1,r=l+1,s=c; if(l<hsz&&heap[2*l]<heap[2*s])s=l; if(r<hsz&&heap[2*r]<heap[2*s])s=r;
      if(s===c)break; [heap[2*s],heap[2*c]]=[heap[2*c],heap[2*s]]; [heap[2*s+1],heap[2*c+1]]=[heap[2*c+1],heap[2*s+1]]; c=s; } }
    return top; };
  push(t0, originIdx);

  while(hsz>0){
    const [t, s] = pop();
    if(t > dist[s]) continue;
    const dep = A.departures[s];
    if(!dep) continue;
    const len = dep.length/3;
    // find first departure >= t (with transfer wait if not origin)
    const need = (s===originIdx) ? t : t + A.MIN_TRANSFER;
    // binary search
    let lo=0, hi=len-1, first=len;
    while(lo<=hi){ const mid=(lo+hi)>>1; if(dep[mid*3]>=need){first=mid;hi=mid-1;} else lo=mid+1; }
    for(let i=first;i<len;i++){
      const dtime = dep[i*3];
      // optional: skip if departure too far in future? no — keep earliest arrivals
      const next = dep[i*3+1] | 0;
      const arr = dep[i*3+2];
      if(arr < dist[next]){
        dist[next] = arr; prev[next] = s; prevTrip[next] = dep[i*3+1]; // store trip via next? we store next idx; trip idx not kept in 3-tuple
        push(arr, next);
      }
      // continue scanning: later departures from this station may give earlier arrival to OTHER stations
    }
  }
  A._prev = prev;
  return dist;
};

// bucket travel time (seconds) -> 0..4 (or -1 unreachable)
A.bucket = function(sec){
  if(!isFinite(sec)) return -1;
  const dt = sec - (A._accessT0||0);
  if(dt < 0) return -1;
  if(dt < 3600) return 0;        // <1h
  if(dt < 7200) return 1;        // 1-2h
  if(dt < 10800) return 2;       // 2-3h
  if(dt < 18000) return 3;       // 3-5h
  return 4;                      // >5h
};
A.bucketColor = ['#00e676','#aeea00','#ffd600','#ff9100','#ff3d00'];
A.bucketLabel = ['< 1 h','1–2 h','2–3 h','3–5 h','> 5 h'];

// compute accessibility for a station at time t0; store A.accessDist + bucket per station
A.computeAccess = function(originIdx, t0){
  A._accessT0 = t0;
  const dist = A.runAccess(originIdx, t0);
  A.accessDist = dist;
  A.accessBucket = new Int8Array(dist.length);
  A.accessCounts = [0,0,0,0,0,0]; // 5 buckets + unreachable
  for(let i=0;i<dist.length;i++){
    if(i===originIdx){ A.accessBucket[i]=0; A.accessCounts[0]++; continue; }
    const b = A.bucket(dist[i]);
    A.accessBucket[i]=b;
    if(b<0) A.accessCounts[5]++; else A.accessCounts[b]++;
  }
  A.accessOrigin = originIdx;
};
