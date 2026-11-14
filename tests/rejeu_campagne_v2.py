#!/usr/bin/env python3
"""Rejeu (rdflib, regles du depot courant) des repetitions F1, F2, F3, K1, K3 de la campagne v2, aux DATES REELLES des cycles.
LIMITE (dite) : les faits complets de chaque cycle n'ont pas ete archives par le banc (seulement les identifiants de derive et le
verdict par cycle) ; les faits sont donc reconstruits a partir des variantes de verif_v1.py (S5-suspend, S5-retard, S0A-nrf, S2 + S0B-udm)
et d'un etat sain, selon la fenetre d'injection (marks.tsv). L'ordre des occurrences, leurs dates et les instants de cycle sont ceux de la campagne.
Usage : rejeu_campagne_v2.py DOSSIER_CAMPAGNE   (a lancer depuis le depot dont on veut tester les regles ; lecture seule)"""
import os, sys, json, datetime as dt
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "verif_v1.py")).read()
exec(src.split("# ================================================================== 1")[0])
exec(src[src.index("from rdflib import Dataset"):src.index("# S0-A sur nrf")])
camp = sys.argv[1]
P = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
def facts_real(v, t):
    if v == "K3":
        g = variant("S2"); g.set((DEP_UDM, C.actualReplicas, Literal(0))); g.remove((POD_UDM, C.runsOn, None)); g.set((POD_UDM, C.podPhase, Literal("Pending")))
    else: g = variant(v) if v else base()
    for r in (WLC, URIRef("https://w3id.org/sylvatwin/res/management-cluster")): g.set((r, C.lastSyncTime, Literal(iso(t), datatype=XSD.dateTime)))
    return g
VAR = {"F1": "S5-suspend", "F2": "S5-suspend", "F3": "S5-retard", "K1": "S0A-nrf", "K3": "K3"}
CLS = {"F1": ["GitOpsSyncDrift"], "F2": ["GitOpsSyncDrift"], "F3": ["GitOpsSyncDrift"], "K1": ["SpecDrift"], "K3": ["BrokenReferenceDrift", "ConvergenceDrift"]}
reps = []
for sc in VAR:
    for r in sorted(os.listdir(f"{camp}/{sc}")):
        mk = {l.split("\t")[1].split(" ")[0]: l.split("\t")[0] for l in open(f"{camp}/{sc}/{r}/marks.tsv").read().splitlines()}
        t0 = P(mk.get("t0_push_debut") or mk["t0"]); tr = P(mk["restauration_faite"])
        cyc = [json.loads(l) for l in open(f"{camp}/{sc}/{r}/sylvatwin/cycles.jsonl")]
        reps.append((t0, sc, r, tr, cyc))
reps.sort(key=lambda x: x[0])
ds = Dataset(); VQp = prep(VQ, "__X__")
def vtypes(now):
    vt = {}
    for s_, p_, o_ in ds.query(prep(VQ, now)):
        if p_ == RDF.type and str(o_).startswith(str(C)): vt.setdefault(str(s_), set()).add(str(o_).split("#")[1])
    return vt
print("scenario\trep\t1er cycle rejoue\tverdict final rejoue\tdoubles (max)\tenregistre par le banc (1er -> dernier)")
for t0, sc, r, tr, cyc in reps:
    seq = []; dmax = 0
    for c in cyc:
        t = P(c["t"])
        v = VAR[sc] if t0 < t <= tr else None
        f = facts_real(v, t); now = iso(t)
        cycle(ds, f, now)
        vt = vtypes(now)
        own = {k: x for k, x in vt.items() if any(f"/verdict/{k_}/" in k for k_ in CLS[sc])}
        if t0 < t <= tr:
            seq.append(sorted(set("+".join(sorted(x)) for x in own.values())))
            dmax = max(dmax, sum(1 for x in own.values() if len(x) > 1))
    first = seq[0] if seq else None; last = seq[-1] if seq else None
    rec = []
    for c in cyc:
        t = P(c["t"])
        if t0 < t <= tr:
            vv = sorted(set(v for i, v in c["ver"].items() if any(f"{k_}/" in i for k_ in CLS[sc]) and i.split("/")[0] in CLS[sc]))
            rec.append(vv)
    print(f"{sc}\t{r}\t{first}\t{last}\t{dmax}\t{rec[0] if rec else None} -> {rec[-1] if rec else None}")
