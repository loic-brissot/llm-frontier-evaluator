# Atlas Ferroviaire — France 24H

Interactive 24-hour animated map & accessibility atlas of the French passenger rail network (TGV, Intercités, TER), styled as a national railway control centre.

## Run

```bash
python3 -m http.server 8000
# open http://localhost:8000
```
Or simply open `index.html` in a browser — no build step, no dependencies.

## Features
- **24h timeline** — scrub or play (×24 to ×480); every scheduled train is positioned along its route, coloured/sized by category; legend filters/isolates TGV / Intercités / TER.
- **Accessibility mode** — click any station: a Dijkstra search over the rail graph (route-nodes + 8 min transfer edges) colours all stations by shortest rail travel time (<1h, 1–2h, 2–3h, 3–5h, >5h).
- **Corridor flow view** — line width & luminance scale with cumulative 24h trains per RFN segment; ranked corridors in the sidebar.
- **Live statistics** — active trains by category at the simulated clock, 24h traffic profile chart (also the timeline backdrop), busiest stations.
- **Details** — click a train for its stop-by-stop timetable, highlighted route and scheduled connections (≤75 min); click a station for its departure board, lines served, and one-click accessibility origin.

## Data
Designed around the open GTFS / RFN datasets (Licence Ouverte / ODbL):
- transport.data.gouv.fr — *Horaires SNCF* (GTFS): https://transport.data.gouv.fr/datasets/horaires-sncf
- SNCF Open Data — *HORAIRES SNCF*, *Formes des lignes du RFN*, *Liste des gares*, *Gares de voyageurs*: https://ressources.data.sncf.com

This standalone build embeds a representative, georeferenced dataset structured like GTFS (`routes` → generated `trips` → `stop_times`, ~110 stations with real coordinates and real corridor routings), so it works fully offline. To use the official feed, replace the `S` / `R` tables in `index.html` with parsed `stops.txt` / `routes.txt` / `trips.txt` / `stop_times.txt` from the GTFS above — all rendering, accessibility (Dijkstra) and flow logic consume that same shape.
