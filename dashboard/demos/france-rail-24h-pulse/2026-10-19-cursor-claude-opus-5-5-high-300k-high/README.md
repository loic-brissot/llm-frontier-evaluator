# Rail Pulse France

Interactive 24-hour animated map and accessibility atlas of French passenger rail (TGV, Intercités, TER),
built from SNCF open data for one reference weekday (Tuesday 20 October 2026).

## Run

Static site, no build step:

```sh
python3 -m http.server 8000   # then open http://localhost:8000
```

## Views

- **Live pulse**: every scheduled train animated along real RFN track geometry, coloured and sized by category,
  with comet trails, a 24 h scrubbable timeline, live counts per category, the 24 h traffic profile and the busiest stations.
  Click a category in the legend to show or hide it; hover over it to highlight it.
- **Corridor flows**: cumulative 24 h train count on every RFN section; line weight and luminance scale with traffic.
- **Accessibility**: click any station to colour all stations by the shortest rail travel time
  (<1 h, 1–2 h, 2–3 h, 3–5 h, >5 h). It uses a Connection Scan over all ~69k scheduled hops, with minimum change times,
  walking and urban transfers. Use "Fastest of the day" or "Leave at" the current clock time; hover over or pin a city to see the itinerary.
- **Selection**: click a train for its stop-by-stop timetable, route path, live status and scheduled connections at every stop.
  Click a station for its departure/arrival board, hourly profile, served routes and direct connections.

Keyboard: `space` play/pause, `←/→` ±5 min (`shift` ±1 h), `1/2/3` switch views, `/` search, `esc` close.

## Rebuild the data

```sh
python3 -m venv .venv && .venv/bin/pip install numpy scipy
.venv/bin/python scripts/build_data.py 20261020    # service day (YYYYMMDD)
```

The pipeline filters rail services running on the chosen day (plus after-midnight runs from the previous evening).
It builds a routable graph from the exploited RFN sections, stitching section ends that stop short of junctions.
It snaps stations to their RFN lines and routes every stop-to-stop hop with Dijkstra. Hops without RFN geometry,
mostly abroad, fall back to straight lines. It then aggregates per-section daily traffic.
Sources and licences: `data/ATTRIBUTION.txt`.
