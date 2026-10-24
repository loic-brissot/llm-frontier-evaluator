# Qui percute qui ? — Observatoire des accidents corporels (BAAC 2024)

Atlas interactif des accidents corporels géolocalisés en France métropolitaine, dernière année validée publiée par l'ONISR (2024).

## Lancer

```bash
python3 -m http.server 8765
# ouvrir http://localhost:8765/
```

Un serveur HTTP est nécessaire (chargement `fetch` des JSON locaux). Aucune clé API : fond OpenStreetMap, contours Etalab.

## Refaire les données

```bash
python3 prep2.py   # joint data_raw/*.csv (4 tables BAAC) -> data/accidents.json
```

Sources téléchargées dans `data_raw/` depuis data.gouv.fr (dataset BAAC 2005–2024, Licence Ouverte) :
`caract-2024.csv`, `lieux-2024.csv`, `vehicules-2024.csv`, `usagers-2024.csv`, jointes sur `Num_Acc`.
Filtre : métropole (hors DROM), coordonnées dans l'emprise 41–51,6° N / −5,5–10° E → **51 055 accidents**.
`data/departements.geojson` : Etalab contours administratifs 100 m.
`data/dept_pop.json` : populations communales geo.api.gouv.fr agrégées par département (taux /100 000 hab.).

## Ce que montre l'atlas

- **Carte canvas** des 51 055 accidents (rendu rapide, zoom national → rue), colorée par gravité maximale (tué / hospitalisé / blessé léger) ou par mode de la victime la plus grave. Au niveau accident, « indemne » n'existe pas : la BAAC ne recense que des accidents corporels.
- **Matrice « qui percute qui »** : victimes (blessées/tuées) par mode — piéton, vélo/VAE, EDPM, deux-roues motorisé, voiture/utilitaire, poids lourd/TC — contre le véhicule opposé du même accident, y compris « Seul / sans tiers » et piétons percutés. Regroupement `catv` : vélo = 01+80 (VAE), EDPM = 50+60, 2RM = 02/30–34/41–43, voiture = 07/10/03, PL/TC = 13–17/20/21/37–40. Une paire par victime ; l'opposant est la première catégorie distincte parmi les autres véhicules. Cliquer une case filtre tout.
- **Filtres** : heure (double curseur), jour de semaine, lumière (`lum`), météo (`atm`), catégorie de route (`catr`), vitesse limite (`vma`), infrastructure cyclable (`vosp` : piste/bande cyclable), milieu.
- **Panneau « Dans la vue actuelle »** : accidents et personnes tuées dans l'emprise carte + filtres, parts mortelles/hospitalisées, distribution d'âge des victimes, paires dominantes.
- **Fiche accident** au clic (zoomer puis cliquer un point) : adresse, route, VMA, voie réservée, chaque véhicule (`catv`, point de choc) et chaque usager (rôle, mode, âge, sexe, équipement `secu1`, gravité).
- **Classement départemental** : accidents filtrés, taux /100 000 habitants et % mortels ; clic = zoom sur le département (contours Etalab sur la carte).

## Repères 2024 (sélection métropole)

- 67 724 victimes, 3 193 personnes tuées, 3 011 accidents mortels.
- Paire dominante : voiture × voiture (20 644 victimes), puis 2RM × voiture (10 838) et voiture seule (9 337).
- Nuit sans éclairage : 12,9 % d'accidents mortels, contre 5,2 % en plein jour.
- Taux les plus élevés : Paris (≈199 /100 000 hab.), Corse-du-Sud, Seine-Saint-Denis, Haute-Corse, Hauts-de-Seine — à lire avec prudence (exposition et trafic non pris en compte).

## Limites

Sous-déclaration des accidents légers sans tiers (vélo, EDPM) ; pas de mesure d'exposition (trafic, km parcourus) ; l'opposant « première catégorie distincte » simplifie les collisions multi-véhicules.
