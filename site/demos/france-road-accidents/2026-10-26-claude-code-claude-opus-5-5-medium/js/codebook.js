// BAAC codebook (ONISR, format 2019+), translated to English.
// Source: "Description des bases de données annuelles des accidents corporels".
export const CODES = {
  lum: { 1: 'Daylight', 2: 'Dusk or dawn', 3: 'Night, no street lighting', 4: 'Night, street lighting off', 5: 'Night, street lighting on' },
  agg: { 1: 'Outside built-up area', 2: 'Built-up area' },
  int: { 1: 'Not at an intersection', 2: 'X intersection', 3: 'T intersection', 4: 'Y intersection', 5: 'Intersection, 5+ branches', 6: 'Roundabout', 7: 'Square', 8: 'Level crossing', 9: 'Other intersection' },
  atm: { '-1': 'Not specified', 1: 'Normal', 2: 'Light rain', 3: 'Heavy rain', 4: 'Snow / hail', 5: 'Fog / smoke', 6: 'Strong wind / storm', 7: 'Dazzling sun', 8: 'Overcast', 9: 'Other' },
  col: { '-1': 'Not specified', 1: 'Two vehicles, head-on', 2: 'Two vehicles, rear-end', 3: 'Two vehicles, side impact', 4: 'Three+ vehicles, chain collision', 5: 'Three+ vehicles, multiple collisions', 6: 'Other collision', 7: 'No collision' },
  catr: { 1: 'Motorway', 2: 'National road', 3: 'Departmental road', 4: 'Communal road', 5: 'Off public network', 6: 'Car park open to traffic', 7: 'Urban metropolitan road', 9: 'Other' },
  circ: { '-1': '—', 1: 'One-way', 2: 'Two-way', 3: 'Divided carriageway', 4: 'Variable-assignment lanes' },
  vosp: { '-1': '—', 0: 'None', 1: 'Cycle track', 2: 'Cycle lane', 3: 'Reserved lane' },
  prof: { '-1': '—', 1: 'Flat', 2: 'Slope', 3: 'Hilltop', 4: 'Bottom of hill' },
  plan: { '-1': '—', 1: 'Straight', 2: 'Left-hand curve', 3: 'Right-hand curve', 4: 'S-bend' },
  surf: { '-1': '—', 1: 'Normal', 2: 'Wet', 3: 'Puddles', 4: 'Flooded', 5: 'Snow', 6: 'Mud', 7: 'Icy', 8: 'Oil / grease', 9: 'Other' },
  infra: { '-1': '—', 0: 'None', 1: 'Tunnel', 2: 'Bridge / overpass', 3: 'Interchange ramp', 4: 'Railway', 5: 'Laid-out junction', 6: 'Pedestrian zone', 7: 'Toll zone', 8: 'Road works', 9: 'Other' },
  situ: { '-1': '—', 0: 'None', 1: 'On carriageway', 2: 'On emergency lane', 3: 'On hard shoulder', 4: 'On pavement', 5: 'On cycle track', 6: 'On other special lane', 8: 'Other' },
  catv: { '-1': 'Unknown', 0: 'Undeterminable', 1: 'Bicycle', 2: 'Moped < 50 cm³', 3: 'Microcar (voiturette)', 7: 'Passenger car', 10: 'Light utility vehicle 1.5–3.5 t', 13: 'Truck 3.5–7.5 t', 14: 'Truck > 7.5 t', 15: 'Truck > 3.5 t + trailer', 16: 'Road tractor', 17: 'Road tractor + semi-trailer', 20: 'Special vehicle', 21: 'Agricultural tractor', 30: 'Scooter < 50 cm³', 31: 'Motorcycle 50–125 cm³', 32: 'Scooter 50–125 cm³', 33: 'Motorcycle > 125 cm³', 34: 'Scooter > 125 cm³', 35: 'Light quad ≤ 50 cm³', 36: 'Heavy quad > 50 cm³', 37: 'Bus', 38: 'Coach', 39: 'Train', 40: 'Tram', 41: '3-wheeler ≤ 50 cm³', 42: '3-wheeler 50–125 cm³', 43: '3-wheeler > 125 cm³', 50: 'Motorised personal transporter (e-scooter…)', 60: 'Non-motorised personal transporter', 80: 'E-bike (VAE)', 99: 'Other vehicle' },
  obs: { '-1': '—', 0: 'None', 1: 'Parked vehicle', 2: 'Tree', 3: 'Metal crash barrier', 4: 'Concrete barrier', 5: 'Other barrier', 6: 'Building, wall, bridge pier', 7: 'Sign post / emergency phone', 8: 'Pole', 9: 'Street furniture', 10: 'Parapet', 11: 'Island, refuge, bollard', 12: 'Kerb', 13: 'Ditch, embankment, rock face', 14: 'Other obstacle on carriageway', 15: 'Other obstacle on pavement', 16: 'Left road, no obstacle', 17: 'Culvert head' },
  obsm: { '-1': '—', 0: 'None', 1: 'Pedestrian', 2: 'Vehicle', 4: 'Rail vehicle', 5: 'Domestic animal', 6: 'Wild animal', 9: 'Other' },
  choc: { '-1': '—', 0: 'None', 1: 'Front', 2: 'Front right', 3: 'Front left', 4: 'Rear', 5: 'Rear right', 6: 'Rear left', 7: 'Right side', 8: 'Left side', 9: 'Multiple (rollover)' },
  manv: { '-1': '—', 0: 'Unknown', 1: 'Going straight', 2: 'Same direction, same lane', 3: 'Between two lanes', 4: 'Reversing', 5: 'Wrong way', 6: 'Crossing central reservation', 7: 'In bus lane, same direction', 8: 'In bus lane, opposite direction', 9: 'Merging', 10: 'U-turn', 11: 'Changing lane to the left', 12: 'Changing lane to the right', 13: 'Swerving left', 14: 'Swerving right', 15: 'Turning left', 16: 'Turning right', 17: 'Overtaking on the left', 18: 'Overtaking on the right', 19: 'Crossing the carriageway', 20: 'Parking manoeuvre', 21: 'Avoiding manoeuvre', 22: 'Opening a door', 23: 'Stopped (not parked)', 24: 'Parked with occupants', 25: 'Riding on the pavement', 26: 'Other manoeuvre' },
  motor: { '-1': '—', 0: 'Unknown', 1: 'Combustion', 2: 'Hybrid electric', 3: 'Electric', 4: 'Hydrogen', 5: 'Human-powered', 6: 'Other' },
  catu: { 1: 'Driver', 2: 'Passenger', 3: 'Pedestrian' },
  grav: { '-1': 'Unknown', 1: 'Unharmed', 2: 'Killed', 3: 'Hospitalised', 4: 'Slightly injured' },
  sexe: { '-1': '—', 1: 'Male', 2: 'Female' },
  trajet: { '-1': '—', 0: '—', 1: 'Home ↔ work', 2: 'Home ↔ school', 3: 'Shopping', 4: 'Professional use', 5: 'Leisure', 9: 'Other' },
  secu: { '-1': null, 0: 'No equipment', 1: 'Seat belt', 2: 'Helmet', 3: 'Child restraint', 4: 'Reflective vest', 5: 'Airbag (2/3-wheeler)', 6: 'Gloves', 7: 'Gloves + airbag', 8: 'Not determinable', 9: 'Other' },
  locp: { '-1': null, 0: null, 1: '> 50 m from a crossing', 2: '< 50 m from a crossing', 3: 'On crossing, no lights', 4: 'On crossing with lights', 5: 'On the pavement', 6: 'On the hard shoulder', 7: 'On a refuge', 8: 'On a service lane', 9: 'Unknown' },
  actp: { '-1': null, 0: null, 1: 'Moving towards the vehicle', 2: 'Moving away from the vehicle', 3: 'Crossing', 4: 'Hidden', 5: 'Playing / running', 6: 'With an animal', 9: 'Other', A: 'Getting in/out of a vehicle', B: 'Unknown' },
  etatp: { '-1': null, 1: 'Alone', 2: 'Accompanied', 3: 'In a group' },
};

export const label = (dict, v, fallback = '—') => {
  const r = CODES[dict][v];
  return r === undefined ? fallback : r;
};
