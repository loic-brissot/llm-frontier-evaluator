#!/usr/bin/env python3
"""Join BAAC 2024 four tables -> compact JSON for atlas. Metro France only."""
import csv, json, collections, re

def clean(v):
    return (v or "").strip().strip('"')

def read(name):
    with open(f"data_raw/{name}", encoding="utf-8", errors="ignore") as f:
        return list(csv.DictReader(f, delimiter=";"))

caract = read("caract-2024.csv"); lieux = read("lieux-2024.csv")
veh = read("vehicules-2024.csv"); usa = read("usagers-2024.csv")

# lieux: one row per accident in theory but duplicates exist (multi-locations?) keep first
lieux_by = {}
for r in lieux:
    lieux_by.setdefault(clean(r["Num_Acc"]), r)

veh_by = collections.defaultdict(list)
for r in veh:
    veh_by[clean(r["Num_Acc"])].append(r)

usa_by = collections.defaultdict(list)
for r in usa:
    usa_by[clean(r["Num_Acc"])].append(r)

# catv -> mode index: 0 Pieton,1 Velo,2 EDPM,3 2RM,4 Voiture/VU,5 Poids lourd/TC,6 Autre
def catv_mode(catv):
    c = clean(catv)
    try: n=int(c)
    except: return 6
    if n==1 or n==80: return 1  # bicyclette + VAE
    if n in (50,60): return 2  # EDP motor / non motor
    if n in (2,30,31,32,33,34,41,42,43): return 3
    if n in (7,10,3): return 4  # VL, VU, voiturette
    if n in (13,14,15,16,17,20,21,37,38,39,40): return 5
    return 6

CATV_LABEL={0:"Indéterminable",1:"Bicyclette",2:"Cyclomoteur <50",3:"Voiturette",7:"Voiture (VL)",10:"Véhicule utilitaire",13:"Poids lourd ≤7,5t",14:"Poids lourd >7,5t",15:"PL + remorque",16:"Tracteur routier",17:"Tracteur + semi",20:"Engin spécial",21:"Tracteur agricole",30:"Scooter <50",31:"Moto ≤125",32:"Scooter ≤125",33:"Moto >125",34:"Scooter >125",35:"Quad léger",36:"Quad lourd",37:"Autobus",38:"Autocar",39:"Train",40:"Tramway",41:"3RM ≤50",42:"3RM ≤125",43:"3RM >125",50:"EDPM à moteur (trottinette élec.)",60:"EDP sans moteur (trottinette, skate…)",80:"Vélo à assistance électrique",99:"Autre véhicule"}
def catv_label(c):
    try: return CATV_LABEL.get(int(clean(c)), f"Catégorie {clean(c)}")
    except: return "Indéterminable"

SECU={0:"Aucun équipement",1:"Ceinture",2:"Casque",3:"Dispositif enfant",4:"Gilet réfléchissant",5:"Airbag",6:"Gants",7:"Gants + airbag",8:"Autre",9:"Non déterminable"}
CHOC={0:"Aucun",1:"Avant",2:"Avant droit",3:"Avant gauche",4:"Arrière",5:"Arrière droit",6:"Arrière gauche",7:"Côté droit",8:"Côté gauche",9:"Chocs multiples"}
MANV={1:"Sans changement de direction",2:"Même sens, même file",3:"Entre 2 files",4:"Marche arrière",5:"À contresens",9:"Insertion",10:"Demi-tour",11:"Change de file à gauche",12:"Change de file à droite",15:"Tournant à gauche",16:"Tournant à droite",17:"Dépassement à gauche",18:"Dépassement à droite",19:"Traversée de chaussée",20:"Stationnement",21:"Évitement",22:"Ouverture de porte",23:"Arrêté",24:"En stationnement",25:"Sur trottoir",26:"Autre manœuvre",0:"Manoeuvre inconnue"}

accidents=[]
skipped={"no_geo":0,"overseas":0}
for r in caract:
    dep=clean(r["dep"])
    if dep in ("971","972","973","974","976","975","977","978","986","987","988"): skipped["overseas"]+=1; continue
    try:
        lat=float(clean(r["lat"]).replace(",",".")); lon=float(clean(r["long"]).replace(",","."))
    except: skipped["no_geo"]+=1; continue
    if not (41.0<=lat<=51.6 and -5.5<=lon<=10.0): skipped["no_geo"]+=1; continue
    nid=clean(r["Num_Acc"])
    L=lieux_by.get(nid,{})
    vs=veh_by.get(nid,[]); us=usa_by.get(nid,[])
    # vehicles
    vehicles=[]
    veh_mode={}  # num_veh -> mode
    for v in vs:
        m=catv_mode(v["catv"]); veh_mode[clean(v["num_veh"])]=m
        vehicles.append({"num":clean(v["num_veh"]),"catv":catv_label(v["catv"]),"mode":m,"choc":CHOC.get(int(clean(v["choc"]) or 0),"—") if clean(v["choc"]).lstrip("-").isdigit() else "—","manv":MANV.get(int(clean(v["manv"])) if clean(v["manv"]).lstrip("-").isdigit() else -1,"—")})
    users=[]
    worst=1
    for u in us:
        try: grav=int(clean(u["grav"]))
        except: grav=1
        worst=max(worst,grav) if grav in (2,3,4) else worst
        # grav ordering for worst: killed 2 is worst; remap severity rank
        catu=int(clean(u["catu"])) if clean(u["catu"]).isdigit() else 1
        if catu==3: mode=0
        else: mode=veh_mode.get(clean(u["num_veh"]),6)
        try: birth=int(clean(u["an_nais"])); age=2024-birth if 1900<birth<=2024 else None
        except: age=None
        secu=[]
        for k in ("secu1","secu2","secu3"):
            try:
                s=int(clean(u[k]))
                if s>0 and s in SECU: secu.append(SECU[s])
            except: pass
        users.append({"role":{1:"Conducteur",2:"Passager",3:"Piéton"}.get(catu,"—"),"grav":grav,"sexe":{1:"Homme",2:"Femme"}.get(int(clean(u["sexe"])) if clean(u["sexe"]).lstrip("-").isdigit() else -1,"Non renseigné"),"age":age,"mode":mode,"secu":secu,"veh":clean(u["num_veh"])})
    # severity rank: 2 killed >3 hosp >4 slight >1 unharmed ; worst among users
    gravs=[u["grav"] for u in users]
    sev = 2 if 2 in gravs else (3 if 3 in gravs else (4 if 4 in gravs else 1))
    # victim modes present (injured/killed users)
    # hour
    hrmn=clean(r["hrmn"]); hour=int(hrmn.split(":")[0]) if ":" in hrmn else 0
    dow=None
    # compute weekday from date
    import datetime
    try: dow=datetime.date(int(clean(r["an"])),int(clean(r["mois"])),int(clean(r["jour"]))).weekday()
    except: dow=0
    def iv(d,k,default=-1):
        try: return int(clean(d.get(k,"")))
        except: return default
    accidents.append({
        "id":nid,"lat":round(lat,5),"lon":round(lon,5),"dep":dep,"com":clean(r["com"]),"adr":clean(r["adr"])[:80],
        "date":f"{clean(r['jour']).zfill(2)}/{clean(r['mois']).zfill(2)}/{clean(r['an'])}","hour":hour,"dow":dow,
        "lum":iv(r,"lum"),"atm":iv(r,"atm"),"col":iv(r,"col"),"agg":iv(r,"agg"),"sev":sev,
        "catr":iv(L,"catr"),"vma":iv(L,"vma"),"vosp":iv(L,"vosp"),"infra":iv(L,"infra"),"surf":iv(L,"surf"),"circ":iv(L,"circ"),"nbv":iv(L,"nbv"),
        "vehicles":vehicles,"users":users,
        "nv":len(vehicles)
    })

print(f"kept {len(accidents)} skipped {skipped}")
json.dump(accidents, open("data/accidents.json","w"), ensure_ascii=False, separators=(",",":"))
# dept names
dept_names={}
try:
    import json as j
    for d in j.load(open("data/departements-pop.json")) if False else []: pass
except: pass
# stats
print(collections.Counter(a["sev"] for a in accidents))
print("size MB", __import__("os").path.getsize("data/accidents.json")/1e6)
