#!/usr/bin/env python3
"""Verification v1.2.0 (ontologie + regles + cycle de vie + verdict).
Usage : python3 tests/verif_v1.py   (rdflib >= 7, owlrl)
Ancienne description : Verification v1.1.0 : execute les VRAIES regles de rules/ (depot) sur l'exemple
reel et sur des variantes de derive construites en memoire. Aucun acces cluster."""
import glob, os, sys
from rdflib import Graph, Literal, URIRef, Namespace, RDF, RDFS, OWL
from rdflib.namespace import XSD
import owlrl

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + "/"
OUT = os.environ.get("SYLVATWIN_VERIF_OUT", "/tmp/sylvatwin-verif/"); os.makedirs(OUT, exist_ok=True)
C = Namespace("https://w3id.org/sylvatwin/core#")
W = "https://w3id.org/sylvatwin/res/my-workload-kubeadm-capd/"
M = "https://w3id.org/sylvatwin/res/management-cluster/"
R = lambda s: URIRef(W + s)
DEP_UDM, DEP_NRF, DEP_BSF = R("sylvatwin-5gc/Deployment/udm"), R("sylvatwin-5gc/Deployment/nrf"), R("sylvatwin-5gc/Deployment/bsf")
POD_UDM, POD_BSF = R("sylvatwin-5gc/Pod/udm-7cf6c5b78d-rw6fk"), R("sylvatwin-5gc/Pod/bsf-78db7b6587-8wkqn")
NODE = R("_/Node/my-workload-kubeadm-capd-control-plane-6w58l")
SEC = R("sylvatwin-5gc/Secret/udm-keys")
NF = lambda n: R("sylvatwin-5gc/NetworkFunction/" + n)
KS = URIRef(M + "sylvatwin-flux/Kustomization.kustomize.toolkit.fluxcd.io/sylvatwin-5gc")
MACH = URIRef(M + "my-workload-kubeadm-capd/Machine.cluster.x-k8s.io/my-workload-kubeadm-capd-control-plane-6w58l")
CAPI = URIRef(M + "my-workload-kubeadm-capd/Cluster.cluster.x-k8s.io/my-workload-kubeadm-capd")
WLC = URIRef("https://w3id.org/sylvatwin/res/my-workload-kubeadm-capd")

def q(path): return open(REPO + "rules/" + path).read()
def short(t):
    s = str(t)
    for a, b in [(W, "wl:"), (M, "mg:"), ("https://w3id.org/sylvatwin/res/_/", "glob:"), (str(C), ":")]:
        s = s.replace(a, b)
    return s

ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("  [OK]    " if cond else "  [ECHEC] ") + name + (("  -> " + detail) if detail else ""))

def base(tbox=False):
    g = Graph()
    if tbox: g.parse(REPO + "sylvatwin-core-v1.ttl")
    g.parse(REPO + "sylvatwin-core-v1-example.ttl")
    return g

def judge(g):
    """Applique 01..08, puis 10, puis 11 (ordre du README). Renvoie le graphe des derives."""
    drifts = Graph()
    for f in sorted(glob.glob(REPO + "rules/derives/0*.rq")):
        for t in g.query(open(f).read()): drifts.add(t)
    g2 = g + drifts
    for t in g2.query(q("derives/10-function-impact-direct.rq")): drifts.add(t)
    g3 = g + drifts
    for t in g3.query(q("derives/11-function-impact-dependance.rq")): drifts.add(t)
    return drifts

def sel(g, path): return [tuple(short(x) if x is not None else None for x in r) for r in g.query(q(path))]
def types(d): return sorted({short(o) for s, o in d.subject_objects(RDF.type)})
def nf_impacts(d):
    out = set()
    for i in d.subjects(RDF.type, C.FunctionImpactDrift):
        out.add((short(d.value(i, C.affectsFunction)), str(d.value(i, C.impactPath))))
    return sorted(out)

def inconsistent(g):
    g = Graph() + g
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    err = URIRef("http://www.daml.org/2002/03/agents/agent-ont#ErrorMessage")
    return [str(o) for s in g.subjects(RDF.type, err) for o in g.objects(s, None) if isinstance(o, Literal)]

# ---------------------------------------------------------------- variantes
def variant(name):
    g = base()
    if name == "S0A-nrf":            # kubectl scale deploy/nrf --replicas=0
        g.set((DEP_NRF, C.observedSpecReplicas, Literal(0))); g.set((DEP_NRF, C.actualReplicas, Literal(0)))
        g.remove((R("sylvatwin-5gc/Pod/nrf-57b6849ccd-wflfd"), None, None))
    elif name == "S0B-udm":          # spec 1, 0 pret (pod Pending)
        g.set((DEP_UDM, C.actualReplicas, Literal(0)))
        g.remove((POD_UDM, C.runsOn, None)); g.set((POD_UDM, C.podPhase, Literal("Pending")))
    elif name.startswith("S1"):      # nodeSelector zone=a ajoute dans bsf.yaml
        req = URIRef(str(DEP_BSF) + "/nodeSelector/sylvatwin.orange.com%2Fzone")
        g.add((DEP_BSF, C.requiresNodeLabel, req)); g.add((req, RDF.type, C.Label))
        g.add((req, C.hasKey, Literal("sylvatwin.orange.com/zone"))); g.add((req, C.hasValue, Literal("a")))
        if name == "S1-ok":
            lab = URIRef(str(NODE) + "/label/sylvatwin.orange.com%2Fzone")
            g.add((NODE, C.hasLabel, lab)); g.add((lab, RDF.type, C.Label))
            g.add((lab, C.hasKey, Literal("sylvatwin.orange.com/zone"))); g.add((lab, C.hasValue, Literal("a")))
    elif name == "S2":               # kubectl delete secret udm-keys : triplets SORTANTS du Secret retires
        g.remove((SEC, None, None))
    elif name == "S4-plmn":          # MNC du NRF change a 71 (ConfigMap patchee)
        p = URIRef("https://w3id.org/sylvatwin/res/_/PLMN/999-71")
        g.remove((NF("nrf"), C.hasPlmn, None)); g.add((NF("nrf"), C.hasPlmn, p))
        g.add((p, RDF.type, C.PLMN)); g.add((p, C.mcc, Literal("999"))); g.add((p, C.mnc, Literal("71")))
    elif name == "S4-slice":         # SMF sert en plus SST 2, pas l'AMF
        s2 = URIRef("https://w3id.org/sylvatwin/res/_/Slice/sst-2")
        g.add((s2, RDF.type, C.Slice)); g.add((s2, C.sst, Literal(2))); g.add((NF("smf"), C.servesSlice, s2))
    elif name == "S5-suspend":       # flux suspend kustomization sylvatwin-5gc
        g.set((KS, C.suspended, Literal(True)))
    elif name == "S5-retard":        # nouveau commit vu par la source, pas encore applique
        g.set((KS, C.desiredRevision, Literal("test@sha1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")))
    elif name == "S6-machine-sans-node":
        g.remove((MACH, C.machineHasNode, None))
    elif name == "S6-node-sans-machine":
        n2 = R("_/Node/noeud-ajoute-hors-capi")
        g.add((n2, RDF.type, C.Node)); g.add((n2, C.uid, Literal("00000000-0000-0000-0000-000000000000")))
        g.add((n2, C.resourceInCluster, WLC))
    return g

# ================================================================== 1
print("== 1. Chargement rdflib")
t = Graph().parse(REPO + "sylvatwin-core-v1.ttl"); e = Graph().parse(REPO + "sylvatwin-core-v1-example.ttl")
cls = set(t.subjects(RDF.type, OWL.Class)); op = set(t.subjects(RDF.type, OWL.ObjectProperty)); dp = set(t.subjects(RDF.type, OWL.DatatypeProperty))
check("TBox", True, f"{len(t)} triplets, {len(cls)} classes, {len(op)} object props, {len(dp)} data props")
check("Exemple", True, f"{len(e)} triplets")
for ann, nom in [(RDFS.comment, "rdfs:comment"), (C.usedInScenario, ":usedInScenario"), (C.writtenBy, ":writtenBy")]:
    manque = [short(x) for x in cls | op | dp if (x, ann, None) not in t]
    check(f"chaque terme a {nom}", not manque, ", ".join(sorted(manque)))
new = [x for x in cls | op | dp if (x, C.layer, None) in t]
manque = [short(x) for x in cls | op | dp if (x, C.layer, None) not in t and (x, C.usedInScenario, None) in t and any(str(o) in ("S3","S4","S5","S6") for o in t.objects(x, C.usedInScenario)) and (x, C.writtenBy, Literal("greffier")) in t and str(x).split("#")[1] not in ("desiredRevision","managedBy")]
check("termes v1.1.0 annotes :layer", not manque, ", ".join(manque))
v0 = Graph().parse(REPO + "legacy/sylvatwin-slice-v0.ttl")
check("ancienne ontologie v0 chargeable avec v1 (espaces distincts)", len(t + v0) == len(t) + len(v0))
k8s = [short(x) for x in t.subjects(C.k8sSource, None)]
check("sources Kubernetes documentees (:k8sSource)", len(k8s) > 30, f"{len(k8s)} termes")

# ================================================================== 2
print("== 2. Coherence OWL 2 RL (owlrl) — exemple et variantes")
check("exemple reel", not inconsistent(base(True)))
for v in ["S0A-nrf","S0B-udm","S1-retire","S2","S4-plmn","S4-slice","S5-suspend","S5-retard","S6-machine-sans-node","S6-node-sans-machine"]:
    g = variant(v); g.parse(REPO + "sylvatwin-core-v1.ttl")
    err = inconsistent(g); check(f"variante {v}", not err, " | ".join(err)[:200])
    variant(v).serialize(OUT + f"v2-variante-{v}.ttl", format="turtle")
neg = base(True); neg.add((NF("udm"), RDF.type, C.Deployment))
check("test negatif : une NF typee aussi Deployment -> incoherence detectee", inconsistent(neg))
neg = base(True); neg.add((KS, RDF.type, C.Pod))
check("test negatif : une Kustomization typee aussi Pod -> incoherence detectee", inconsistent(neg))

# ================================================================== 3
print("== 3. Questions de competence sur l'exemple REEL (aucune derive attendue)")
g = base()
for f in ["cq/CQ1-replicas.rq","cq/CQ2-placement.rq","cq/CQ4-secret.rq","cq/CQ6-plmn.rq","cq/CQ7-tranche.rq","cq/CQ8-flux.rq","cq/CQ9-machine-node.rq"]:
    r = sel(g, f); check(f"{f} : vide", r == [], str(r))
r = sel(g, "cq/CQ3-chaine.rq"); check("CQ3 : 3 chaines Pod -> RS -> Deployment -> Node (udm, nrf, bsf)", len(r) == 3, "; ".join(x[0].split("/")[-1] + "->" + x[2].split("/")[-1] for x in r))
r = sel(g, "cq/CQ5-nf-touchee.rq")
udm = sorted({(x[1].split("/")[-1], x[2]) for x in r if x[0] == short(DEP_UDM)})
check("CQ5 : ressource Deployment/udm -> NF udm (direct)", udm == [("udm","direct")], str(udm))
nrf = sorted({(x[1].split("/")[-1], x[2]) for x in r if x[0] == short(DEP_NRF)})
check("CQ5 : Deployment/nrf -> nrf (direct) + amf, bsf, smf, udm (dependance)",
      nrf == [("amf","dependance"),("bsf","dependance"),("nrf","direct"),("smf","dependance"),("udm","dependance")], str(nrf))
r = sel(g, "cq/CQ10-bout-en-bout.rq")
r = [x for x in r if x[0] == short(NF("udm"))]
check("CQ10 : NF udm -> Git -> Kustomization -> workload -> Pod -> Node -> Machine -> Cluster CAPI",
      len(r) == 1 and all(r[0]), " | ".join(str(c) for c in (r[0] if r else [])))
check("juge sur l'exemple reel : aucune derive", len(judge(base())) == 0)

# ================================================================== 4
print("== 4. Juge (rules/derives) sur les variantes de derive")
attendus = {
  "S0A-nrf":   (["SpecDrift"], [("nrf","direct"),("amf","dependance"),("bsf","dependance"),("smf","dependance"),("udm","dependance")]),
  "S0B-udm":   (["ConvergenceDrift"], [("udm","direct")]),
  "S1-ok":     ([], []),
  "S1-retire": (["PlacementDrift"], [("bsf","direct")]),   # + infrastructure ? non : la PlacementDrift concerne aussi le Node -> voir ci-dessous
  "S2":        (["BrokenReferenceDrift"], [("udm","direct")]),
  "S4-plmn":   (["InterNFConsistencyDrift"], []),
  "S4-slice":  (["InterNFConsistencyDrift"], []),
  "S5-suspend":(["GitOpsSyncDrift"], "flux-toutes"),
  "S5-retard": (["GitOpsSyncDrift"], "flux-toutes"),
  "S6-machine-sans-node": (["MachineNodeMismatchDrift"], "infra-toutes"),
  "S6-node-sans-machine": (["MachineNodeMismatchDrift"], []),
}
toutes = ["amf","bsf","nrf","smf","udm"]
for v, (types_att, imp_att) in attendus.items():
    d = judge(variant(v))
    base_types = sorted(t.split(":")[-1] for t in types(d) if t != ":FunctionImpactDrift")
    imp = nf_impacts(d)
    imp_s = sorted((a.split("/")[-1], b) for a, b in imp)
    print(f"  --- {v}")
    check(f"{v} : derives produites = {types_att}", base_types == sorted(types_att), str(base_types))
    if imp_att == "flux-toutes":
        check(f"{v} : les 5 NF de l'exemple touchees via flux", sorted(a for a, b in imp_s if b == "flux") == toutes, str(imp_s))
    elif imp_att == "infra-toutes":
        check(f"{v} : NF touchees via infrastructure (pods sur le Node de la Machine)",
              sorted(a for a, b in imp_s if b == "infrastructure") == sorted(["bsf","nrf","udm"]), str(imp_s))
    elif v == "S1-retire":
        direct = sorted((a, b) for a, b in imp_s if b == "direct")
        check(f"{v} : NF bsf touchee (direct)", direct == [("bsf","direct")], str(imp_s))
        check(f"{v} : pas de faux positif 'infrastructure' (nrf, udm n'exigent pas le label)", imp_s == [("bsf","direct")], str(imp_s))
    else:
        check(f"{v} : NF touchees = {imp_att}", imp_s == sorted(imp_att), str(imp_s))
    # verifier que chaque FunctionImpactDrift a une cause qui existe
    orph = [i for i in d.subjects(RDF.type, C.FunctionImpactDrift) if (d.value(i, C.causedBy), RDF.type, None) not in d]
    check(f"{v} : chaque FunctionImpactDrift :causedBy une derive existante", not orph)
    d.serialize(OUT + f"v2-derives-{v}.ttl", format="turtle")

# S2 : la regle par uid survit a l'inference ; la regle par type non
g2 = variant("S2"); g2.parse(REPO + "sylvatwin-core-v1.ttl"); owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g2)
check("S2 apres inference OWL : CQ4 (test sur :uid) detecte toujours", len(sel(g2, "cq/CQ4-secret.rq")) == 1)

# Greffier/juge : aucune classe "juge" dans l'exemple ecrit par le greffier
juge_cls = {x for x in t.subjects(C.writtenBy, Literal("juge"))}
viol = [(short(s), short(o)) for s, p, o in e if (p == RDF.type and o in juge_cls) or p in juge_cls]
check("greffier/juge : l'exemple (faits observes) ne contient aucun terme 'juge'", not viol, str(viol))


# ================================================================== 6 (v1.2.0)
print("== 6. Garde de portee P3 (cluster injoignable / hors portee)")
def unreachable(g, kc=WLC):
    g.set((kc, C.observationStatus, Literal("unreachable"))); return g
for v in ["S2", "S6-machine-sans-node"]:
    d = judge(variant(v)); n_ok = len(d)
    g = variant(v)
    if v == "S2": g = unreachable(g)
    else: g = unreachable(g, WLC)
    d2 = judge(g)
    base_t = sorted(t.split(":")[-1] for t in types(d2) if t != ":FunctionImpactDrift")
    check(f"P3 {v} : derive detectee si cluster ok", n_ok > 0)
    check(f"P3 {v} : AUCUNE derive si le cluster est 'unreachable' (pas de faux positif)", base_t == [], str(base_t))
g = variant("S2")
for sc in list(g.objects(WLC, C.hasObservationScope)):
    if (sc, C.scopeKind, Literal("Secret")) in g: g.remove((WLC, C.hasObservationScope, sc))
check("P3 S2 : aucune derive si les Secrets sont hors portee", len(judge(g)) == 0)

# ================================================================== 7 cycle de vie + verdict
print("== 7. Cycle de vie (SPARQL Update) et verdict date, sur rdflib (Dataset)")
from rdflib import Dataset
import datetime as dt
HIST = URIRef("https://w3id.org/sylvatwin/graph/history"); FACTS = URIRef("https://w3id.org/sylvatwin/graph/facts"); DRIFTS = URIRef("https://w3id.org/sylvatwin/graph/drifts"); TBOX = URIRef("https://w3id.org/sylvatwin/graph/tbox")
SECONDS = open(REPO + "rules/verdict/seconds.sparql").read().strip()
def seconds_expr(a, b): return SECONDS.replace("$A", a).replace("$B", b)
def prep(q, now, validity=600):
    q = q.replace("__NOW__", now).replace("__VALIDITY__", str(float(validity)))
    import re
    return re.sub(r"__SECONDS__\((\?\w+),\s*(\?\w+)\)", lambda m: seconds_expr(m.group(1), m.group(2)), q)
LC = sorted(glob.glob(REPO + "rules/lifecycle/*.ru")); VQ = open(REPO + "rules/verdict/01-verdict.rq").read()
def cycle(ds, facts, now, validity=600):
    """Un cycle du juge : faits -> derives (01..11) -> cycle de vie -> verdicts.
    Renvoie {(classe de derive, classe de verdict)}."""
    for g in (FACTS, DRIFTS):
        ds.remove_graph(ds.graph(g))
    tg = ds.graph(TBOX)  # la TBox est chargee une fois (comme le controleur au demarrage) : lifecycle/05 la lit
    if len(tg) == 0: tg.parse(REPO + "sylvatwin-core-v1.ttl")
    fg = ds.graph(FACTS)
    for t in facts: fg.add(t)
    dg = ds.graph(DRIFTS)
    for t in judge(facts): dg.add(t)
    for f in LC:
        ds.update(prep(open(f).read(), now, validity))
    out = set()
    for row in ds.query(prep(VQ, now, validity)):
        s_, p_, o_ = row
        if p_ == RDF.type and str(o_).startswith(str(C)):
            out.add((str(s_).split("/verdict/")[1].split("/")[0], str(o_).split("#")[1]))
    return out
def now_at(sec): return (dt.datetime(2026, 11, 9, 12, 0, 0) + dt.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
def facts_at(v, sec):
    g = variant(v) if v else base()
    g.set((WLC, C.lastSyncTime, Literal(now_at(sec), datatype=XSD.dateTime)))
    g.set((URIRef("https://w3id.org/sylvatwin/res/management-cluster"), C.lastSyncTime, Literal(now_at(sec), datatype=XSD.dateTime)))
    return g
# S0-A sur nrf (Ks 2m + 5m = 420 s) : suspectee a t=60, confirmee a t=500, resolue a t=600
ds = Dataset()
r60 = cycle(ds, facts_at("S0A-nrf", 60), now_at(60)); check("verdict S0-A t=60 s : SpecDrift ET impacts NF suspectes (age 0 < 420)", r60 == {("SpecDrift", "SuspectedViolation"), ("FunctionImpactDrift", "SuspectedViolation")}, str(sorted(r60)))
r500 = cycle(ds, facts_at("S0A-nrf", 500), now_at(500)); check("verdict S0-A t=500 s : SpecDrift ET impacts NF confirmes (age 440 >= 420)", r500 == {("SpecDrift", "ConfirmedViolation"), ("FunctionImpactDrift", "ConfirmedViolation")}, str(sorted(r500)))
h = list(ds.graph(HIST).objects(None, C.convergenceHorizon)); check("horizon S0-A = 420 s (2m + 5m)", any(float(x) == 420.0 for x in h), str(h))
fd = list(ds.graph(HIST).objects(URIRef("https://w3id.org/sylvatwin/drift/SpecDrift/my-workload-kubeadm-capd/sylvatwin-5gc/Deployment/nrf"), C.firstDetectedAt))
check("firstDetectedAt conserve entre les cycles (= t=60)", [str(x) for x in fd] == [now_at(60)], str(fd))
r600 = cycle(ds, facts_at(None, 600), now_at(600)); res = list(ds.graph(HIST).subject_objects(C.resolvedAt))
check("S0-A t=600 s (Flux a corrige) : derive resolue, plus de verdict", r600 == set() and len(res) >= 1, str(sorted(r600)) + " resolues=" + str(len(res)))
# S2 (hors Git) : confirmee immediatement
ds = Dataset(); r = cycle(ds, facts_at("S2", 10), now_at(10))
check("verdict S2 t=10 s : BrokenReference confirmee immediatement (hors Git, pas d'horizon)", ("BrokenReferenceDrift", "ConfirmedViolation") in r, str(sorted(r)))
# S5 retard (Kustomization active, commit pas encore applique) : SUSPECTEE (Flux livrera)
ds = Dataset(); r = cycle(ds, facts_at("S5-retard", 10), now_at(10))
check("verdict S5-retard t=10 s : GitOpsSync suspectee (Ks active, horizon 420 s)", ("GitOpsSyncDrift", "SuspectedViolation") in r, str(sorted(r)))
# S1 placement : confirmee immediatement (Kubernetes n'evince pas)
ds = Dataset(); r = cycle(ds, facts_at("S1-retire", 10), now_at(10))
check("verdict S1 t=10 s : PlacementDrift confirmee immediatement", ("PlacementDrift", "ConfirmedViolation") in r, str(sorted(r)))
# S5 suspend : confirmee immediatement
ds = Dataset(); r = cycle(ds, facts_at("S5-suspend", 10), now_at(10))
check("verdict S5 t=10 s : GitOpsSync confirmee immediatement", ("GitOpsSyncDrift", "ConfirmedViolation") in r, str(sorted(r)))
# information perimee -> inconnu
ds = Dataset(); f = facts_at("S2", 10); f.set((WLC, C.lastSyncTime, Literal(now_at(-5000), datatype=XSD.dateTime)))
r = cycle(ds, f, now_at(10)); check("verdict inconnu si derniere synchro > horizon de validite", r and all(c == "UnknownVerdict" for _, c in r), str(sorted(r)))
# injoignable apres detection : pas de resolution
ds = Dataset(); cycle(ds, facts_at("S2", 10), now_at(10)); f = unreachable(facts_at("S2", 70)); f.remove((SEC, None, None))
r = cycle(ds, f, now_at(70)); res = list(ds.graph(HIST).subject_objects(C.resolvedAt))
check("P3 : cluster devenu injoignable -> derive NON resolue, verdict inconnu", not res and r and all(c == "UnknownVerdict" for _, c in r), str(sorted(r)) + f" resolues={len(res)}")

# ================================================================== 8 (v1.3.0, partie 3 et 2)
print("== 8. StaleConfigDrift (D4), horizon ConvergenceDrift (progressDeadlineSeconds), SCP, Watch temoin")

def with_stale_config(sec_started=0, sec_modified=300, sec_now=1000):
    """nrf : Pod demarre a sec_started, ConfigMap nrf-config modifiee a sec_modified.
    lastSyncTime fixe a sec_now (frais par rapport a sec_now) pour que le verdict
    ne soit pas 'inconnu' faute de preuve de fraicheur."""
    g = base()
    cm = R("sylvatwin-5gc/ConfigMap/nrf-config")
    g.add((cm, RDF.type, C.ConfigMap))
    g.add((cm, C.lastModifiedAt, Literal(now_at(sec_modified), datatype=XSD.dateTime)))
    g.add((DEP_NRF, C.mountsConfigMap, cm))
    pod = R("sylvatwin-5gc/Pod/nrf-57b6849ccd-wflfd")
    g.add((pod, C.startedAt, Literal(now_at(sec_started), datatype=XSD.dateTime)))
    g.set((WLC, C.lastSyncTime, Literal(now_at(sec_now), datatype=XSD.dateTime)))
    g.set((URIRef("https://w3id.org/sylvatwin/res/management-cluster"), C.lastSyncTime, Literal(now_at(sec_now), datatype=XSD.dateTime)))
    return g

g = with_stale_config(0, 300)
d = judge(g)
check("StaleConfigDrift : pod demarre AVANT la modif de la ConfigMap -> derive", len(list(d.subjects(RDF.type, C.StaleConfigDrift))) == 1)
check("StaleConfigDrift : impact sur la NF nrf (direct)", (NF("nrf"), "direct") in {(o, str(d.value(s, C.impactPath))) for s, o in d.subject_objects(C.affectsFunction)})
g2 = with_stale_config(300, 0)  # pod demarre APRES la modif : pas de derive
check("StaleConfigDrift : pod demarre APRES la modif -> pas de derive", len(list(judge(g2).subjects(RDF.type, C.StaleConfigDrift))) == 0)
# verdict : horizon infini (Flux ne redemarre jamais un pod) -> confirmee tout de suite
ds = Dataset(); r = cycle(ds, with_stale_config(0, 300, 10), now_at(10))
check("verdict StaleConfigDrift : confirmee immediatement (pas d'horizon)", ("StaleConfigDrift", "ConfirmedViolation") in r, str(sorted(r)))

# Horizon ConvergenceDrift = progressDeadlineSeconds du Deployment (PAS interval+timeout Flux)
def with_progress_deadline(pd_value=None, sec_now=10):
    g = variant("S0B-udm")
    if pd_value is not None:
        g.set((DEP_UDM, C.progressDeadlineSeconds, Literal(float(pd_value), datatype=XSD.decimal)))
    g.set((WLC, C.lastSyncTime, Literal(now_at(sec_now), datatype=XSD.dateTime)))
    g.set((URIRef("https://w3id.org/sylvatwin/res/management-cluster"), C.lastSyncTime, Literal(now_at(sec_now), datatype=XSD.dateTime)))
    return g
ds = Dataset(); cycle(ds, with_progress_deadline(90, 10), now_at(10))
h = list(ds.graph(HIST).objects(None, C.convergenceHorizon))
check("horizon ConvergenceDrift = progressDeadlineSeconds explicite (90 s, pas l'horizon Flux 420 s)", any(float(x) == 90.0 for x in h), str(h))
ds2 = Dataset(); cycle(ds2, with_progress_deadline(None, 10), now_at(10))  # absent -> defaut Kubernetes 600 s
h2 = list(ds2.graph(HIST).objects(None, C.convergenceHorizon))
check("horizon ConvergenceDrift = 600 s par defaut si progressDeadlineSeconds absent", any(float(x) == 600.0 for x in h2), str(h2))
ds3 = Dataset(); r90 = cycle(ds3, with_progress_deadline(90, 10), now_at(10))
check("verdict ConvergenceDrift suspectee a t=10 s (age < 90 s)", ("ConvergenceDrift", "SuspectedViolation") in r90, str(sorted(r90)))
r90b = cycle(ds3, with_progress_deadline(90, 200), now_at(200))
check("verdict ConvergenceDrift confirmee a t=200 s (age >= 90 s)", ("ConvergenceDrift", "ConfirmedViolation") in r90b, str(sorted(r90b)))

# SCP : classe presente, disjointe des autres NF
check("classe :SCP presente dans la TBox", (C.SCP, RDF.type, OWL.Class) in t)
check(":SCP sous-classe de :NetworkFunction", (C.SCP, RDFS.subClassOf, C.NetworkFunction) in t)

# Watch temoin et age de l'information (partie 2) : A_c(t) = t - u_c(t)
def with_witness(age_witness, theta=30.0, sec=10):
    g = variant("S2")
    g.set((WLC, C.witnessLeaseName, Literal("my-workload-kubeadm-capd-control-plane-6w58l")))
    g.set((WLC, C.lastWitnessRenewTime, Literal(now_at(sec - age_witness), datatype=XSD.dateTime)))
    g.set((WLC, C.freshnessHorizon, Literal(theta, datatype=XSD.decimal)))
    # le management aussi doit avoir une preuve de fraicheur (sinon il est, lui,
    # considere perime par le repli lastSyncTime absent -> verdict inconnu a tort)
    MG = URIRef("https://w3id.org/sylvatwin/res/management-cluster")
    g.set((MG, C.lastSyncTime, Literal(now_at(sec), datatype=XSD.dateTime)))
    return g
ds = Dataset(); r = cycle(ds, with_witness(5, 30, 10), now_at(10))
check("fraicheur : temoin recent (age 5s < theta 30s) -> verdict normal (pas inconnu)", ("BrokenReferenceDrift", "ConfirmedViolation") in r and not any(c == "UnknownVerdict" for _, c in r), str(sorted(r)))
ds2 = Dataset(); r2 = cycle(ds2, with_witness(60, 30, 10), now_at(10))
check("fraicheur : temoin perime (age 60s > theta 30s) -> verdict inconnu", r2 and all(c == "UnknownVerdict" for _, c in r2), str(sorted(r2)))

print("\nRESULTAT GLOBAL :", "TOUT OK" if ok else "ECHECS")
sys.exit(0 if ok else 1)
