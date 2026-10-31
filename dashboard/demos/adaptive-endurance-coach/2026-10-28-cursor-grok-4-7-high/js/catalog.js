/** Disciplines, events, and the athlete the studio opens with. */

export const DISCIPLINES = [
  {
    id: "triathlon",
    name: "Triathlon",
    line: "Swim, bike, and run. Bricks appear when the week can hold them.",
  },
  {
    id: "running",
    name: "Running",
    line: "Daniels paces from your VDOT, easy through repetition.",
  },
  {
    id: "cycling",
    name: "Cycling",
    line: "Coggan power, from aerobic base to race-specific work.",
  },
  {
    id: "cross",
    name: "Cross-training",
    line: "Cycling, running, and easy full-body strength.",
  },
];

export const EVENTS = {
  triathlon: [
    { id: "sprint", name: "Sprint", taperWeeks: 1, peakWeeks: 1, intensity: "high", longBikeMin: 120, longRunMin: 70, raceMin: 75, goal: "Race" },
    { id: "olympic", name: "Olympic", taperWeeks: 2, peakWeeks: 2, intensity: "mixed", longBikeMin: 165, longRunMin: 90, raceMin: 150, goal: "Race" },
    { id: "seventy3", name: "70.3", taperWeeks: 2, peakWeeks: 3, intensity: "steady", longBikeMin: 270, longRunMin: 125, raceMin: 330, goal: "Race" },
    { id: "ironman", name: "Ironman", taperWeeks: 3, peakWeeks: 2, intensity: "steady", longBikeMin: 360, longRunMin: 160, raceMin: 690, goal: "Race" },
  ],
  running: [
    { id: "5k", name: "5K", taperWeeks: 1, peakWeeks: 2, intensity: "high", longRunMin: 75, raceMin: 22, goal: "Race" },
    { id: "10k", name: "10K", taperWeeks: 1, peakWeeks: 2, intensity: "high", longRunMin: 100, raceMin: 45, goal: "Race" },
    { id: "half", name: "Half marathon", taperWeeks: 2, peakWeeks: 2, intensity: "mixed", longRunMin: 140, raceMin: 100, goal: "Race" },
    { id: "marathon", name: "Marathon", taperWeeks: 3, peakWeeks: 2, intensity: "steady", longRunMin: 180, raceMin: 200, goal: "Race" },
  ],
  cycling: [
    { id: "crit", name: "Criterium", taperWeeks: 1, peakWeeks: 2, intensity: "high", longBikeMin: 150, raceMin: 60, goal: "Race" },
    { id: "tt", name: "Time trial", taperWeeks: 1, peakWeeks: 2, intensity: "threshold", longBikeMin: 180, raceMin: 50, goal: "Race" },
    { id: "fondo", name: "Gran fondo", taperWeeks: 2, peakWeeks: 2, intensity: "steady", longBikeMin: 300, raceMin: 300, goal: "Race" },
    { id: "century", name: "Century", taperWeeks: 2, peakWeeks: 1, intensity: "steady", longBikeMin: 360, raceMin: 390, goal: "Race" },
  ],
  cross: [
    { id: "foundation", name: "Foundation block", taperWeeks: 1, peakWeeks: 1, intensity: "mixed", longBikeMin: 180, longRunMin: 90, raceMin: 40, goal: "Benchmark" },
    { id: "combo", name: "Half + fondo", taperWeeks: 2, peakWeeks: 2, intensity: "mixed", longBikeMin: 240, longRunMin: 130, raceMin: 150, goal: "Goal day" },
  ],
};

export function disciplineById(id) {
  return DISCIPLINES.find((d) => d.id === id) || DISCIPLINES[0];
}

export function eventById(discipline, eventId) {
  const list = EVENTS[discipline] || EVENTS.triathlon;
  return list.find((e) => e.id === eventId) || list[0];
}

export const RACE_DISTANCES = [
  { id: "1500", name: "1,500 m", meters: 1500 },
  { id: "mile", name: "Mile", meters: 1609.344 },
  { id: "5k", name: "5K", meters: 5000 },
  { id: "10k", name: "10K", meters: 10000 },
  { id: "15k", name: "15K", meters: 15000 },
  { id: "half", name: "Half marathon", meters: 21097.5 },
  { id: "marathon", name: "Marathon", meters: 42195 },
];

export function defaultProfile() {
  return {
    name: "Alex Rivera",
    discipline: "triathlon",
    eventId: "olympic",
    start: "2026-11-02",
    race: "2027-02-21",
    weightKg: 70,
    ftpW: 265,
    runMode: "race",
    vo2max: 52,
    raceDistanceId: "10k",
    raceTime: "42:30",
    lthr: 168,
    swimMode: "pace",
    cssPace: "1:38",
    t200: "3:05",
    t400: "6:28",
    weeklyHours: 10,
    sessionsPerWeek: 8,
    rampCap: 5,
  };
}

export function emptyAdaptations() {
  return { sessionEdits: {}, illnesses: [], availability: [] };
}
