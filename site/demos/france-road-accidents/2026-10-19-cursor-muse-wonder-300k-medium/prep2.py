import csv, json, collections, datetime
def c(v): return (v or "").strip()
def read(n):
    with open(f"data_raw/{n}",encoding="utf-8",errors="ignore") as f: return list(csv.DictReader(f,delimiter=";"))
def iv(r,k,d=-1):
    try: return int(c(r.get(k,"")))
    except: return d
car=read("caract-2024.csv"); lieux=read("lieux-2024.csv"); veh=read("vehicules-2024.csv"); usa=read("usagers-2024.csv")
lb={}
for r in lieux: lb.setdefault(c(r["Num_Acc"]),r)
vb=collections.defaultdict(list)
for r in veh: vb[c(r["Num_Acc"])].append(r)
ub=collections.defaultdict(list)
for r in usa: ub[c(r["Num_Acc"])].append(r)
def mode(catv):
    n=iv({"x":catv},"x",-1) if False else (int(c(catv)) if c(catv).lstrip("-").isdigit() else -1)
    if n in (1,80): return 1
    if n in (50,60): return 2
    if n in (2,30,31,32,33,34,41,42,43): return 3
    if n in (7,10,3): return 4
    if n in (13,14,15,16,17,20,21,37,38,39,40): return 5
    return 6
out=[]
for r in car:
    dep=c(r["dep"])
    if dep in ("971","972","973","974","976","975","977","978"): continue
    try: lat=float(c(r["lat"]).replace(",",".")); lon=float(c(r["long"]).replace(",","."))
    except: continue
    if not (41<=lat<=51.6 and -5.5<=lon<=10): continue
    nid=c(r["Num_Acc"]); L=lb.get(nid,{})
    vmap={}; vs=[]
    for v in vb.get(nid,[]):
        m=mode(v["catv"]); vmap[c(v["num_veh"])]=m
        vs.append([iv(v,"catv"),m,iv(v,"choc"),iv(v,"manv")])
    us=[]; gravs=[]
    for u in ub.get(nid,[]):
        g=iv(u,"grav",1); gravs.append(g); catu=iv(u,"catu",1)
        md=0 if catu==3 else vmap.get(c(u["num_veh"]),6)
        birth=iv(u,"an_nais",-1); age=2024-birth if 1900<birth<=2024 else -1
        us.append([catu,g,iv(u,"sexe"),age,md,iv(u,"secu1"),c(u["num_veh"])])
    sev=2 if 2 in gravs else (3 if 3 in gravs else 4)
    h=c(r["hrmn"]); hour=int(h.split(":")[0]) if ":" in h else 0
    try: dow=datetime.date(iv(r,"an"),iv(r,"mois"),iv(r,"jour")).weekday()
    except: dow=0
    out.append({"i":nid,"x":round(lon,5),"y":round(lat,5),"d":dep,"h":hour,"w":dow,"m":iv(r,"mois"),"lum":iv(r,"lum"),"atm":iv(r,"atm"),"agg":iv(r,"agg"),"sev":sev,"catr":iv(L,"catr"),"vma":iv(L,"vma"),"vosp":iv(L,"vosp"),"adr":c(r["adr"])[:70],"com":c(r["com"]),"v":vs,"u":us})
json.dump(out,open("data/accidents.json","w"),ensure_ascii=False,separators=(",",":"))
import os; print(len(out), os.path.getsize("data/accidents.json")/1e6)
