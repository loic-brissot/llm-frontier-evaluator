/**
 * Structured workouts. Every session is a sequence of blocks with an exact
 * intensity relative to that sport's threshold (FTP, Daniels T pace, or CSS).
 */

import { repetitionIntensity, runIntensity } from "./physio.js";

function iv(kind, modality, sec, i0, i1, label, extra = {}) {
  return {
    kind,
    modality,
    sec: Math.max(0, Math.round(sec)),
    i0,
    i1: i1 == null ? i0 : i1,
    label,
    ...extra,
  };
}

function steady(kind, modality, sec, intensity, label, extra) {
  return iv(kind, modality, sec, intensity, intensity, label, extra);
}

function ramp(kind, modality, sec, i0, i1, label, extra) {
  return iv(kind, modality, sec, i0, i1, label, extra);
}

function sumSec(list) {
  return list.reduce((s, item) => s + item.sec, 0);
}

function scaleList(list, factor) {
  if (!(factor > 0) || !list.length) return list.map((item) => ({ ...item }));
  return list.map((item) => {
    const floor = item.kind === "rest" ? 12 : 20;
    return { ...item, sec: Math.max(floor, Math.round(item.sec * factor)) };
  });
}

/**
 * Glue warm-up, main set, and cool-down so the sum matches the session clock.
 * `fit: "scale"` stretches the main set. `fit: "pad"` keeps repeats exact and
 * fills leftover time with easy swimming, riding, or running.
 */
function assemble(totalSec, wu, main, cd, meta, fit = "scale") {
  let warm = wu.map((item) => ({ ...item }));
  let cool = cd.map((item) => ({ ...item }));
  let fixed = sumSec(warm) + sumSec(cool);
  if (fixed > totalSec * 0.72 && totalSec > 0) {
    const f = Math.max(0.35, (totalSec * 0.42) / Math.max(1, fixed));
    warm = scaleList(warm, f);
    cool = scaleList(cool, f);
    fixed = sumSec(warm) + sumSec(cool);
  }
  const mainTarget = Math.max(30, Math.round(totalSec) - fixed);
  const mainSum = Math.max(1, sumSec(main));
  let body;
  if (fit === "pad") {
    const pad = mainTarget - mainSum;
    const modality = main[0]?.modality || warm[0]?.modality || "bike";
    const easy = modality === "swim" ? 0.8 : modality === "run" ? 0.78 : 0.62;
    if (pad >= 180) {
      const label = modality === "swim" ? "Aerobic" : modality === "run" ? "Easy" : "Settle";
      body = [steady("work", modality, pad, easy, label), ...main.map((item) => ({ ...item }))];
    } else if (pad > 0 && warm.length) {
      warm[warm.length - 1] = { ...warm[warm.length - 1], sec: warm[warm.length - 1].sec + pad };
      body = main.map((item) => ({ ...item }));
    } else if (pad < -20) {
      body = scaleList(main, mainTarget / mainSum);
    } else {
      body = main.map((item) => ({ ...item }));
    }
  } else {
    body = scaleList(main, mainTarget / mainSum);
  }
  let intervals = [...warm, ...body, ...cool];
  let delta = Math.round(totalSec) - sumSec(intervals);
  if (intervals.length && delta !== 0) {
    const flexible = new Set(["Settle", "Steady", "Aerobic", "Endurance", "Easy", "Recovery spin", "Recovery", "Warm-up", "Cool-down"]);
    const mapped = intervals.map((item, index) => ({ index, sec: item.sec, label: item.label }));
    const pool = (fit === "pad" ? mapped.filter((row) => flexible.has(row.label)) : mapped).sort((a, b) => b.sec - a.sec);
    const host = pool[0] || mapped.sort((a, b) => b.sec - a.sec)[0];
    if (host) {
      intervals[host.index] = {
        ...intervals[host.index],
        sec: Math.max(15, intervals[host.index].sec + delta),
      };
    }
  }
  return { ...meta, intervals };
}

function repeatTitle(intervals, label, prefix) {
  const works = intervals.filter((item) => item.kind === "work" && item.label === label);
  if (!works.length) return null;
  const sec = works[0].sec;
  if (sec < 90) return `${prefix} ${works.length}×${sec}s`;
  return `${prefix} ${works.length}×${Math.max(1, Math.round(sec / 60))}`;
}

function biasWork(intervals, bias, cap) {
  if (!bias) return intervals;
  return intervals.map((item) => {
    if (item.kind !== "work") return item;
    const i0 = Math.min(cap, item.i0 + bias);
    const i1 = Math.min(cap, item.i1 + bias);
    return { ...item, i0, i1 };
  });
}

function bikeKind(spec, event) {
  if (spec.role === "opener" || spec.role === "shakeout") return "opener";
  if (spec.phase === "recovery" && (spec.role === "intensity" || spec.role === "intensity2")) return "touch";
  if (spec.role === "recovery") return "recovery";
  if (spec.role === "long") return "long";
  if (spec.role === "endurance") return spec.touches === "spinups" ? "spinups" : "endurance";
  const variant = (spec.weekIndex + (spec.role === "intensity2" ? 1 : 0)) % 3;
  if (event.intensity === "steady") return variant === 2 && spec.phase === "peak" ? "vo2short" : "sweet";
  if (event.intensity === "threshold") return variant === 1 ? "overunder" : "threshold";
  if (event.intensity === "high") return variant === 1 ? "anaerobic" : "vo2";
  return ["sweet", "threshold", "vo2"][variant];
}

function runKind(spec, event) {
  if (spec.role === "opener" || spec.role === "shakeout") return "opener";
  if (spec.phase === "recovery" && (spec.role === "intensity" || spec.role === "intensity2")) return "easy";
  if (spec.role === "long") return "long";
  if (spec.role === "endurance" || spec.role === "recovery") return spec.touches === "strides" ? "strides" : "easy";
  const variant = (spec.weekIndex + (spec.role === "intensity2" ? 1 : 0)) % 3;
  if (event.intensity === "steady") {
    if (spec.phase === "peak") return variant === 0 ? "marathon" : "tempo";
    return variant === 2 ? "cruise" : "tempo";
  }
  if (event.intensity === "high") return ["vo2", "rep", "cruise"][variant];
  if (event.intensity === "threshold") return variant === 2 ? "vo2" : "cruise";
  return ["cruise", "vo2", "tempo"][variant];
}

function swimKind(spec, event) {
  if (spec.role === "opener" || spec.role === "shakeout") return "opener";
  if (spec.phase === "recovery" || spec.role === "recovery" || spec.role === "endurance") {
    return spec.weekIndex % 2 === 0 ? "aerobic" : "drill";
  }
  if (spec.role === "long") return "aerobic";
  const variant = spec.weekIndex % 3;
  if (event.intensity === "steady") return variant === 2 ? "css" : "aerobic";
  if (event.intensity === "high") return variant === 1 ? "speed" : "css";
  return ["css", "tempo", "speed"][variant];
}

function notesFor(sport, kind) {
  const table = {
    endurance: "Stay conversational. The adaptation is in the minutes, held steadily.",
    spinups: "Mostly aerobic, with a few short openings so the top end does not go quiet.",
    sweet: "Sweet spot sits just under threshold. Hold the watt target; let heart rate arrive late.",
    threshold: "These are threshold repeats. Start the recovery when the rep ends, not before.",
    overunder: "The over-geared minute is the stress. The under-geared minute is how you stay there.",
    vo2: "Stop the set if the last rep falls off the target. Failed reps are not extra fitness.",
    vo2short: "Short enough to stay crisp. This is a reminder of the intensity, not a new block of load.",
    anaerobic: "Full recovery between efforts. These tax the anaerobic battery, not the aerobic one.",
    long: "The long session is the week's spine. The finish is specific; the middle should still feel like you could continue.",
    recovery: "Genuine recovery. If it feels like training, it is too hard.",
    opener: "Keep the efforts short and the recoveries honest. You are waking the system up, not loading it.",
    touch: "A little neuromuscular contact, then back to easy.",
    easy: "Easy is a target, not a leftover. Most of the week should feel like this.",
    strides: "Strides are quick, not hard. Float the recovery.",
    cruise: "Cruise intervals accumulate time at threshold without asking for it all at once.",
    tempo: "Tempo is controlled. You should finish knowing you could have continued.",
    marathon: "Goal pace, in pieces you can hold. Practice the rhythm you want on race day.",
    rep: "Short, fast, and fully recovered. Form is the point.",
    aerobic: "Smooth and long enough to matter. Count strokes, not courage.",
    drill: "Drills before the steady swimming. The pace stays aerobic.",
    css: "Hold CSS. The rest is short on purpose — that is the threshold stimulus.",
    speed: "Fast, but not a sprint you fall apart on. Leave the wall with a length you can repeat.",
    strength: "RPE 6, two repetitions in reserve. This is tissue preparation, not a hypertrophy block.",
    brick: "The first minutes of the run are for settling, not for the watch.",
    race: "Execute the pacing you trained. The warm-up is part of the result.",
  };
  return table[kind] || table[sport] || "Hold the targets as written.";
}

function bikeWorkout(spec, phys, event) {
  const total = spec.minutes * 60;
  const biasCap = 1.45;
  const kind = bikeKind(spec, event);
  const wu = ramp("warmup", "bike", 12 * 60, 0.42, 0.68, "Warm-up");
  const cd = ramp("cooldown", "bike", 8 * 60, 0.58, 0.42, "Cool-down");
  let main = [];
  let title = "Endurance ride";

  if (kind === "endurance" || kind === "spinups") {
    main = [steady("work", "bike", 40 * 60, 0.68, "Endurance", { cadence: 90 })];
    if (kind === "spinups") {
      for (let i = 0; i < 6; i++) {
        main.push(steady("work", "bike", 12, 1.55, "Spin-up"));
        main.push(steady("recovery", "bike", 90, 0.55, "Easy"));
      }
      title = "Endurance with spin-ups";
    } else title = "Endurance ride";
  } else if (kind === "long") {
    const finish = spec.phase === "build" || spec.phase === "peak";
    const finishI = event.intensity === "steady" ? 0.8 : event.intensity === "high" ? 0.9 : 0.86;
    main = [steady("work", "bike", 50 * 60, 0.67, "Endurance", { cadence: 88 })];
    if (finish) main.push(steady("work", "bike", 20 * 60, finishI, "Tempo finish"));
    title = finish ? "Long ride · tempo finish" : "Long ride";
  } else if (kind === "recovery") {
    main = [steady("work", "bike", 30 * 60, 0.52, "Recovery", { cadence: 95 })];
    title = "Recovery spin";
  } else if (kind === "sweet") {
    const work = spec.phase === "base" ? 10 * 60 : 15 * 60;
    const n = spec.phase === "peak" ? 2 : 3;
    const pct = event.intensity === "steady" ? 0.88 : 0.91;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "bike", work, pct, "Sweet spot"));
      main.push(steady("recovery", "bike", 5 * 60, 0.5, "Recovery"));
    }
    title = "Sweet spot";
  } else if (kind === "threshold") {
    const work = event.intensity === "threshold" ? 12 * 60 : 8 * 60;
    const n = event.intensity === "threshold" ? 3 : 4;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "bike", work, 0.98, "Threshold"));
      main.push(steady("recovery", "bike", 4 * 60, 0.5, "Recovery"));
    }
    title = "Threshold";
  } else if (kind === "overunder") {
    const n = 3;
    for (let s = 0; s < n; s++) {
      for (let k = 0; k < 3; k++) {
        main.push(steady("work", "bike", 2 * 60, 0.92, "Under"));
        main.push(steady("work", "bike", 2 * 60, 1.05, "Over"));
      }
      main.push(steady("recovery", "bike", 6 * 60, 0.48, "Recovery"));
    }
    title = `Over-unders ${n}×12`;
  } else if (kind === "vo2" || kind === "vo2short") {
    const work = kind === "vo2short" ? 2 * 60 : 3 * 60;
    const n = kind === "vo2short" ? 5 : 5;
    const intensity = kind === "vo2short" ? 1.12 : 1.16;
    main.push(steady("work", "bike", 60, 1.05, "Primer"));
    main.push(steady("recovery", "bike", 120, 0.5, "Easy"));
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "bike", work, intensity, "VO₂"));
      main.push(steady("recovery", "bike", kind === "vo2short" ? 120 : 180, 0.48, "Recovery"));
    }
    title = "VO₂";
  } else if (kind === "anaerobic") {
    const n = 8;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "bike", 60, 1.4, "Anaerobic"));
      main.push(steady("recovery", "bike", 120, 0.45, "Recovery"));
    }
    title = `Anaerobic ${n}×1`;
  } else if (kind === "touch") {
    for (let i = 0; i < 4; i++) {
      main.push(steady("work", "bike", 60, 1.05, "Touch"));
      main.push(steady("recovery", "bike", 120, 0.5, "Easy"));
    }
    title = "Neuromuscular touch";
  } else {
    for (let i = 0; i < 4; i++) {
      main.push(steady("work", "bike", 75, 1.12, "Opener"));
      main.push(steady("recovery", "bike", 120, 0.5, "Easy"));
    }
    title = "Openers 4×75s";
  }

  const built = assemble(total, [wu], main, [cd], {
    title,
    note: notesFor("bike", kind),
    kind,
  }, kind === "sweet" || kind === "threshold" || kind === "vo2" || kind === "vo2short" || kind === "anaerobic" || kind === "overunder" ? "pad" : "scale");
  built.intervals = biasWork(built.intervals, spec.intensityBias || 0, biasCap);
  const titled =
    repeatTitle(built.intervals, "Sweet spot", "Sweet spot") ||
    repeatTitle(built.intervals, "Threshold", "Threshold") ||
    repeatTitle(built.intervals, "VO₂", "VO₂") ||
    repeatTitle(built.intervals, "Anaerobic", "Anaerobic") ||
    repeatTitle(built.intervals, "Opener", "Openers");
  if (titled && kind !== "long" && kind !== "endurance" && kind !== "spinups") built.title = titled;
  if (kind === "overunder") built.title = "Over-unders";
  return built;
}

function runWorkout(spec, phys, event) {
  const total = spec.minutes * 60;
  const vdot = phys.vdot;
  const easy = runIntensity(vdot, 0.7);
  const midEasy = runIntensity(vdot, 0.72);
  const marathon = runIntensity(vdot, 0.82);
  const tempo = runIntensity(vdot, 0.84);
  const threshold = 1;
  const interval = runIntensity(vdot, 0.975);
  const rep = repetitionIntensity(vdot);
  const kind = runKind(spec, event);
  const wu = ramp("warmup", "run", 10 * 60, easy * 0.92, easy, "Warm-up");
  const cd = ramp("cooldown", "run", 6 * 60, easy, easy * 0.9, "Cool-down");
  let main = [];
  let title = "Easy run";

  if (kind === "easy" || kind === "strides") {
    main = [steady("work", "run", 30 * 60, midEasy, "Easy")];
    if (kind === "strides") {
      for (let i = 0; i < 6; i++) {
        main.push(steady("work", "run", 20, rep, "Stride"));
        main.push(steady("recovery", "run", 60, easy * 0.9, "Float"));
      }
      title = "Easy run + strides";
    } else title = "Easy run";
  } else if (kind === "long") {
    const specific = spec.phase === "build" || spec.phase === "peak";
    main = [steady("work", "run", 40 * 60, midEasy, "Easy")];
    if (specific && event.intensity !== "high") {
      const finishI = event.intensity === "steady" ? marathon : tempo;
      main.push(steady("work", "run", 15 * 60, finishI, event.intensity === "steady" ? "Marathon pace" : "Steady"));
      title = event.intensity === "steady" ? "Long run · marathon-pace finish" : "Long run · steady finish";
    } else if (specific) {
      for (let i = 0; i < 4; i++) {
        main.push(steady("work", "run", 20, rep, "Stride"));
        main.push(steady("recovery", "run", 50, easy, "Float"));
      }
      title = "Long run + strides";
    } else title = "Long run";
  } else if (kind === "cruise") {
    const work = spec.phase === "peak" ? 8 * 60 : 6 * 60;
    const n = spec.phase === "base" ? 4 : 5;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "run", work, threshold, "Threshold"));
      main.push(steady("recovery", "run", 2 * 60, easy, "Jog"));
    }
    title = "Cruise intervals";
  } else if (kind === "tempo") {
    main = [
      steady("work", "run", 8 * 60, easy, "Settle"),
      steady("work", "run", 20 * 60, tempo, "Tempo"),
    ];
    title = "Tempo run";
  } else if (kind === "marathon") {
    const n = 3;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "run", 12 * 60, marathon, "Marathon pace"));
      main.push(steady("recovery", "run", 3 * 60, easy, "Easy"));
    }
    title = "Marathon pace";
  } else if (kind === "vo2") {
    const n = spec.phase === "peak" ? 5 : 5;
    const work = event.id === "5k" ? 3 * 60 : 3.5 * 60;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "run", work, interval, "Interval"));
      main.push(steady("recovery", "run", 3 * 60, easy * 0.95, "Jog"));
    }
    title = "Intervals";
  } else if (kind === "rep") {
    const n = 8;
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "run", 45, rep, "Repetition"));
      main.push(steady("recovery", "run", 75, easy * 0.92, "Recover"));
    }
    title = `Repetitions ${n}×45s`;
  } else {
    main = [steady("work", "run", 8 * 60, easy, "Easy")];
    for (let i = 0; i < 4; i++) {
      main.push(steady("work", "run", 20, rep * 0.98, "Stride"));
      main.push(steady("recovery", "run", 50, easy, "Float"));
    }
    title = "Shakeout + strides";
  }

  const lock = ["cruise", "vo2", "rep", "marathon"].includes(kind);
  const built = assemble(total, [wu], main, [cd], {
    title,
    note: notesFor("run", kind),
    kind,
  }, lock ? "pad" : "scale");
  built.intervals = biasWork(built.intervals, spec.intensityBias || 0, 1.28);
  const titled =
    repeatTitle(built.intervals, "Threshold", "Cruise intervals") ||
    repeatTitle(built.intervals, "Interval", "Intervals") ||
    repeatTitle(built.intervals, "Repetition", "Repetitions") ||
    repeatTitle(built.intervals, "Marathon pace", "Marathon pace");
  if (titled) built.title = titled;
  return built;
}

function swimWorkout(spec, phys, event) {
  const total = spec.minutes * 60;
  const kind = swimKind(spec, event);
  const wu = ramp("warmup", "swim", 6 * 60, 0.72, 0.8, "Warm-up");
  const cd = ramp("cooldown", "swim", 4 * 60, 0.75, 0.7, "Cool-down");
  let main = [];
  let title = "Aerobic swim";

  const rep = (n, workSec, workI, restSec, label) => {
    for (let i = 0; i < n; i++) {
      main.push(steady("work", "swim", workSec, workI, label));
      main.push(steady("rest", "swim", restSec, 0.35, "Rest"));
    }
  };

  const mainBudget = Math.max(60, total - 10 * 60);
  const fits = (piece, rest, desired) => Math.max(1, Math.min(desired, Math.floor((mainBudget + rest) / (piece + rest))));
  if (kind === "aerobic") {
    rep(spec.phase === "base" ? 4 : 6, 4 * 60, 0.86, 20, "Aerobic");
    title = "Aerobic swim";
  } else if (kind === "drill") {
    rep(4, 90, 0.75, 20, "Drill");
    rep(4, 150, 0.84, 15, "Swim");
    title = "Drill and aerobic";
  } else if (kind === "css") {
    const piece = 100 / phys.cssMps;
    const n = fits(piece, 15, spec.phase === "peak" ? 8 : 10);
    rep(n, piece, 1, 15, "CSS");
    title = `CSS ${n}×100`;
  } else if (kind === "tempo") {
    const piece = 200 / (phys.cssMps * 0.97);
    const n = fits(piece, 20, 5);
    rep(n, piece, 0.97, 20, "Tempo");
    title = `Tempo ${n}×200`;
  } else if (kind === "speed") {
    const piece = 50 / (phys.cssMps * 1.08);
    const n = fits(piece, 20, 12);
    rep(n, piece, 1.08, 20, "Speed");
    title = `Speed ${n}×50`;
  } else {
    const piece = 50 / (phys.cssMps * 1.02);
    const n = fits(piece, 20, 6);
    rep(n, piece, 1.02, 20, "Opener");
    title = `Swim openers ${n}×50`;
  }

  const built = assemble(total, [wu], main, [cd], {
    title,
    note: notesFor("swim", kind),
    kind,
  }, "pad");
  built.intervals = biasWork(built.intervals, spec.intensityBias || 0, 1.15);
  const cssCount = built.intervals.filter((item) => item.label === "CSS").length;
  const speedCount = built.intervals.filter((item) => item.label === "Speed").length;
  const tempoCount = built.intervals.filter((item) => item.label === "Tempo").length;
  const aerobicMin = built.intervals.filter((item) => item.label === "Aerobic").reduce((sum, item) => sum + item.sec, 0) / 60;
  const lead = aerobicMin >= 8 ? "Aerobic · " : "";
  if (cssCount) built.title = `${lead}CSS ${cssCount}×100`;
  if (speedCount) built.title = `${lead}Speed ${speedCount}×50`;
  if (tempoCount) built.title = `${lead}Tempo ${tempoCount}×200`;
  return built;
}

function strengthWorkout(spec) {
  const which = spec.weekIndex % 2 === 0 ? "A" : "B";
  const moves = which === "A"
    ? [
        ["Back squat", 3],
        ["Romanian deadlift", 3],
        ["Push-up or bench", 3],
        ["One-arm row", 3],
        ["Suitcase carry", 3],
        ["Dead bug", 2],
      ]
    : [
        ["Split squat", 3],
        ["Hip hinge", 3],
        ["Overhead press", 3],
        ["Row", 3],
        ["Side plank", 2],
      ];
  const main = [];
  for (const [name, sets] of moves) {
    for (let s = 0; s < sets; s++) {
      main.push(steady("strength", "strength", 40, 0.62, name));
      main.push(steady("rest", "strength", 70, 0.16, "Rest"));
    }
  }
  const built = assemble(
    spec.minutes * 60,
    [steady("warmup", "strength", 5 * 60, 0.28, "Prep")],
    main,
    [steady("cooldown", "strength", 3 * 60, 0.2, "Downregulate")],
    {
      title: `Foundation ${which}`,
      note: notesFor("strength", "strength"),
      kind: "strength",
    },
  );
  return built;
}

function brickWorkout(spec, phys, event) {
  const total = spec.minutes * 60;
  const bikeShare = 0.68;
  const bikeSec = Math.round(total * bikeShare);
  const runSec = Math.max(8 * 60, total - bikeSec - 4 * 60);
  const bikeI = spec.phase === "base" ? 0.75 : event.intensity === "steady" ? 0.8 : 0.86;
  const runI = spec.phase === "peak" ? runIntensity(phys.vdot, 0.8) : runIntensity(phys.vdot, 0.74);
  const intervals = [
    ramp("warmup", "bike", 8 * 60, 0.45, 0.7, "Bike warm-up"),
    steady("work", "bike", Math.max(10 * 60, bikeSec - 8 * 60), bikeI, "Bike tempo"),
    steady("transition", "bike", 4 * 60, 0.3, "Transition"),
    steady("work", "run", Math.round(runSec * 0.7), runI, "Run off the bike"),
    ramp("cooldown", "run", Math.max(4 * 60, Math.round(runSec * 0.3)), runI * 0.9, runIntensity(phys.vdot, 0.68), "Run settle"),
  ];
  const delta = Math.round(total) - sumSec(intervals);
  if (delta) {
    intervals[1] = { ...intervals[1], sec: Math.max(8 * 60, intervals[1].sec + delta) };
  }
  const biased = biasWork(intervals, spec.intensityBias || 0, 1.2);
  return {
    title: "Brick · tempo bike, settle run",
    note: notesFor("brick", "brick"),
    kind: "brick",
    intervals: biased,
  };
}

function raceWorkout(spec, phys, event) {
  const discipline = spec.discipline;
  const total = Math.max(20, event.raceMin) * 60;
  let intervals = [];
  let title = event.goal === "Race" ? `${event.name} race` : event.goal;

  if (discipline === "triathlon") {
    const splits = {
      sprint: [0.18, 0.52, 0.3],
      olympic: [0.18, 0.5, 0.32],
      seventy3: [0.12, 0.55, 0.33],
      ironman: [0.1, 0.57, 0.33],
    }[event.id] || [0.18, 0.5, 0.32];
    const swimI = event.intensity === "steady" ? 0.92 : 0.98;
    const bikeI = event.intensity === "steady" ? 0.72 : event.intensity === "high" ? 0.86 : 0.8;
    const runI = event.intensity === "steady"
      ? runIntensity(phys.vdot, 0.78)
      : event.intensity === "high"
        ? runIntensity(phys.vdot, 0.9)
        : runIntensity(phys.vdot, 0.84);
    intervals = [
      steady("work", "swim", total * splits[0], swimI, "Swim"),
      steady("work", "bike", total * splits[1], bikeI, "Bike"),
      steady("work", "run", total * splits[2], runI, "Run"),
    ];
    title = `${event.name} triathlon`;
  } else if (discipline === "running") {
    const frac = {
      "5k": runIntensity(phys.vdot, 0.99),
      "10k": runIntensity(phys.vdot, 0.93),
      half: runIntensity(phys.vdot, 0.86),
      marathon: runIntensity(phys.vdot, 0.82),
    }[event.id] || 1;
    const wu = Math.min(12 * 60, total * 0.18);
    intervals = [
      ramp("warmup", "run", wu, runIntensity(phys.vdot, 0.7), frac * 0.9, "Warm-up"),
      steady("work", "run", Math.max(60, total - wu), frac, "Race"),
    ];
    title = `${event.name} race`;
  } else if (discipline === "cycling") {
    const intensity = {
      crit: 0.9,
      tt: 0.99,
      fondo: 0.75,
      century: 0.7,
    }[event.id] || 0.8;
    const wu = Math.min(20 * 60, total * 0.12);
    intervals = [
      ramp("warmup", "bike", wu, 0.45, Math.min(0.75, intensity), "Warm-up"),
      steady("work", "bike", Math.max(60, total - wu), intensity, "Race"),
    ];
    title = `${event.name}`;
  } else {
    const wu = 8 * 60;
    intervals = [
      ramp("warmup", "bike", wu, 0.5, 0.75, "Warm-up"),
      steady("work", "bike", Math.max(10 * 60, (total - wu) * 0.55), 0.9, "Bike benchmark"),
      steady("work", "run", Math.max(8 * 60, (total - wu) * 0.45), runIntensity(phys.vdot, 0.9), "Run benchmark"),
    ];
    title = event.goal === "Benchmark" ? "Benchmark · bike and run" : `${event.name}`;
  }

  intervals = intervals.map((item) => ({ ...item, sec: Math.round(item.sec) }));
  return {
    title,
    note: notesFor("race", "race"),
    kind: "race",
    intervals,
  };
}

export function buildWorkout(spec, phys, event) {
  if (spec.role === "race") return raceWorkout(spec, phys, event);
  if (spec.sport === "strength") return strengthWorkout(spec);
  if (spec.sport === "brick") return brickWorkout(spec, phys, event);
  if (spec.sport === "swim") return swimWorkout(spec, phys, event);
  if (spec.sport === "run") return runWorkout(spec, phys, event);
  return bikeWorkout(spec, phys, event);
}
