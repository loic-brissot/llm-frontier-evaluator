/// <reference lib="webworker" />

type Conn = {
  f: number[];
  t: number[];
  d: number[];
  a: number[];
  trip: number[];
  pick: number[];
  drop: number[];
  cat: number[];
};

let conn: Conn | null = null;
let xfer: Int16Array = new Int16Array();
let foot: number[][] = [];
let nStations = 0;
const queue: { type: string; origin: number; mask: number; id: number }[] = [];

const ready: number[][] = [];
const keys: number[][] = [];

function ensure(n: number) {
  while (ready.length < n) {
    ready.push([]);
    keys.push([]);
  }
}

function bestLabel(station: number, dep: number): number | null {
  const R = ready[station];
  const K = keys[station];
  let chosen: number | null = null;
  for (let i = 0; i < R.length; i++) {
    if (R[i] <= dep) chosen = K[i];
    else break;
  }
  return chosen;
}

function insertFoot(station: number, arr: number, key: number, best: Int32Array, leave: Int16Array) {
  const dur = key + arr;
  if (dur < best[station]) {
    best[station] = dur;
    leave[station] = -key;
  }
  const R = ready[station];
  const K = keys[station];
  const rd = arr;
  for (let i = 0; i < R.length; i++) {
    if (R[i] <= rd && K[i] <= key) return;
  }
  let i = 0;
  while (i < R.length && R[i] < rd) i++;
  R.splice(i, 0, rd);
  K.splice(i, 0, key);
  let j = i + 1;
  while (j < R.length) {
    if (R[j] >= rd && K[j] >= key) {
      R.splice(j, 1);
      K.splice(j, 1);
    } else j++;
  }
  if (R.length > 64) {
    R.length = 64;
    K.length = 64;
  }
}

function insertTrain(
  station: number,
  arr: number,
  key: number,
  best: Int32Array,
  leave: Int16Array,
) {
  const dur = key + arr;
  if (dur < best[station]) {
    best[station] = dur;
    leave[station] = -key;
  }
  const rd = arr + xfer[station];
  const R = ready[station];
  const K = keys[station];
  for (let i = 0; i < R.length; i++) {
    if (R[i] <= rd && K[i] <= key) return;
  }
  let i = 0;
  while (i < R.length && R[i] < rd) i++;
  R.splice(i, 0, rd);
  K.splice(i, 0, key);
  let j = i + 1;
  while (j < R.length) {
    if (R[j] >= rd && K[j] >= key) {
      R.splice(j, 1);
      K.splice(j, 1);
    } else j++;
  }
  if (R.length > 64) {
    R.length = 64;
    K.length = 64;
  }
  const links = foot[station];
  if (!links) return;
  for (let k = 0; k < links.length; k += 2) {
    insertFoot(links[k], arr + links[k + 1], key, best, leave);
  }
}

function run(origin: number, mask: number) {
  const c = conn!;
  const n = nStations;
  const m = c.d.length;
  const best = new Int32Array(n);
  best.fill(1_000_000_000);
  const leave = new Int16Array(n);
  leave.fill(-32768);
  for (let i = 0; i < n; i++) {
    ready[i].length = 0;
    keys[i].length = 0;
  }
  let nTrips = 0;
  for (let i = 0; i < m; i++) if (c.trip[i] + 1 > nTrips) nTrips = c.trip[i] + 1;
  const tripKey = new Int32Array(nTrips);
  tripKey.fill(0x7fffffff);
  const footStart = new Int16Array(n);
  footStart.fill(-1);
  const links = foot[origin] || [];
  for (let k = 0; k < links.length; k += 2) footStart[links[k]] = links[k + 1];

  for (let i = 0; i < m; i++) {
    if (((1 << c.cat[i]) & mask) === 0) continue;
    const from = c.f[i];
    const to = c.t[i];
    const dep = c.d[i];
    const arr = c.a[i];
    const trip = c.trip[i];
    let key = tripKey[trip];
    let active = key !== 0x7fffffff;
    if (c.pick[i]) {
      if (from === origin) {
        const k0 = -dep;
        if (!active || k0 < key) {
          key = k0;
          active = true;
        }
      }
      const walk = footStart[from];
      if (walk >= 0) {
        const k1 = -dep + walk;
        if (!active || k1 < key) {
          key = k1;
          active = true;
        }
      }
      const lab = bestLabel(from, dep);
      if (lab !== null && (!active || lab < key)) {
        key = lab;
        active = true;
      }
      if (active) tripKey[trip] = key;
    }
    if (!active || !c.drop[i]) continue;
    insertTrain(to, arr, key, best, leave);
  }
  best[origin] = 0;
  leave[origin] = 0;
  const dur = new Int16Array(n);
  for (let i = 0; i < n; i++) dur[i] = best[i] > 30000 ? 32767 : best[i];
  return { dur, leave };
}

function answer(data: { type: string; origin: number; mask: number; id: number }) {
  if (data.type !== "query" || !conn) return;
  const { dur, leave } = run(data.origin, data.mask);
  self.postMessage({ type: "result", id: data.id, dur, leave }, [dur.buffer, leave.buffer]);
}

self.onmessage = (event: MessageEvent) => {
  const data = event.data;
  if (data.type === "init") {
    nStations = data.n;
    xfer = Int16Array.from(data.xfer as number[]);
    foot = data.foot as number[][];
    ensure(nStations);
    fetch(data.url as string)
      .then((res) => res.json())
      .then((json: Conn) => {
        conn = json;
        const pending = queue.splice(0, queue.length);
        for (const item of pending) answer(item);
        self.postMessage({ type: "ready" });
      });
    return;
  }
  if (!conn) {
    queue.push(data);
    return;
  }
  answer(data);
};
