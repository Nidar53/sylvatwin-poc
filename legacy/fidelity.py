#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fidelity.py — MESURER SI LE JUMEAU DIT VRAI.

Tous les autres outils supposent que le graphe decrit correctement le cluster.
Celui-ci verifie cette supposition. C'est l'instrument de mesure, pas une piece
de la machine : il est volontairement EXTERIEUR au jumeau, et il interroge
l'API Kubernetes directement pour avoir une reference independante.

    le graphe dit X   <-- fidelity.py compare -->   l'API dit Y

Les quatre mesures
------------------
  M1  COMPLETUDE DE POPULATION
      Quelle part des ressources du cluster existe dans le graphe ?
      Signale aussi les FANTOMES : des individus que le graphe garde alors
      que la ressource a disparu du cluster.

  M2  EXACTITUDE SEMANTIQUE
      Pour chaque individu present des deux cotes, les faits ecrits
      correspondent-ils a la realite ? On recalcule les triplets attendus
      depuis l'API et on les compare un a un.

  M3  COHERENCE LOGIQUE
      Le graphe respecte-t-il ses propres axiomes ? Un Pod sur deux noeuds,
      un partOf qui pointe vers un Node, un individu sans type : autant
      d'incoherences qui ne viennent pas du cluster mais d'un bug du
      fact-writer. C'est la derive DU JUMEAU, pas du cluster.

  M4  LATENCE DE PROPAGATION  (option --latency)
      Combien de temps entre un changement reel et son apparition dans le
      graphe ? Mesure active : pose une etiquette temoin sur un noeud,
      chronometre, puis nettoie derriere elle.

Cadre de reference
------------------
M1, M2 et M3 instancient les dimensions de qualite des donnees liees de
Zaveri et al. (completude de population, exactitude semantique, coherence).
M4 n'y figure pas : ces dimensions ont ete definies pour des jeux de donnees
publies, pas pour un graphe synchronise en continu.

Usage
-----
    python3 fidelity.py                 # M1, M2, M3 — lecture seule
    python3 fidelity.py --latency       # + M4 — MODIFIE le cluster
    python3 fidelity.py --json rapport.json

Prerequis : kubectl configure sur le cluster observe.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict

try:
    from rdflib import Graph, Literal
    from rdflib.namespace import RDF
except ImportError:
    sys.exit("Il manque rdflib :  pip install rdflib")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import compile_intent as ci

GRAPH_FILE = os.path.join(HERE, "sylvatwin-graph.ttl")
TBOX_FILE = os.path.join(HERE, "sylvatwin-slice-v0.ttl")
REPORT_FILE = os.path.join(HERE, "sylvatwin-fidelity.json")

PROBE_KEY = "sylvatwin.orange.com/probe"


# ==========================================================================
# ACCES A LA REFERENCE : l'API Kubernetes, via kubectl.
# ==========================================================================
def kube(*args):
    """Appelle kubectl et renvoie le JSON. Sortie propre en cas d'echec."""
    cmd = ["kubectl"] + list(args) + ["-o", "json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        sys.exit("kubectl introuvable. Cet outil a besoin d'un acces au cluster.")
    except subprocess.TimeoutExpired:
        sys.exit("kubectl n'a pas repondu en 60s. Le cluster est-il demarre ?")
    if out.returncode != 0:
        sys.exit("kubectl a echoue :\n%s" % out.stderr.strip())
    return json.loads(out.stdout)


def kube_apply_label(node, key, value):
    arg = "%s=%s" % (key, value) if value is not None else "%s-" % key
    r = subprocess.run(["kubectl", "label", "node", node, arg, "--overwrite"],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def read_cluster(namespace=None):
    """L'etat reel, reduit aux faits que la TBox v0 sait exprimer."""
    scope = ["-n", namespace] if namespace else ["-A"]

    nodes, deployments, pods = {}, {}, {}

    for n in kube("get", "nodes")["items"]:
        nodes[n["metadata"]["name"]] = {
            "labels": set("%s=%s" % (k, v)
                          for k, v in (n["metadata"].get("labels") or {}).items()),
        }

    for d in kube("get", "deployments", *scope)["items"]:
        deployments[d["metadata"]["name"]] = {
            "replicas": int((d.get("status") or {}).get("replicas") or 0),
        }

    # Pod -> ReplicaSet -> Deployment, comme resolveOwnerDeployment en Go.
    rs_owner = {}
    for rs in kube("get", "replicasets", *scope)["items"]:
        for ref in rs["metadata"].get("ownerReferences") or []:
            if ref.get("kind") == "Deployment":
                rs_owner[rs["metadata"]["name"]] = ref["name"]

    for p in kube("get", "pods", *scope)["items"]:
        owner = ""
        for ref in p["metadata"].get("ownerReferences") or []:
            if ref.get("kind") == "ReplicaSet":
                owner = rs_owner.get(ref["name"], "")
        if not owner:
            owner = (p["metadata"].get("labels") or {}).get("app", "")
        pods[p["metadata"]["name"]] = {
            "node": (p.get("spec") or {}).get("nodeName") or "",
            "owner": owner,
            "phase": (p.get("status") or {}).get("phase", ""),
        }

    return {"nodes": nodes, "deployments": deployments, "pods": pods}


# ==========================================================================
# M1 — COMPLETUDE DE POPULATION
# ==========================================================================
def m1_population(g, ns, cluster):
    rows = []
    missing_all, ghost_all = [], []

    families = [
        ("Node", ns.Node, "nodes", "node"),
        ("Deployment", ns.Deployment, "deployments", ""),
        ("Pod", ns.Pod, "pods", "pod"),
    ]

    for label, cls, key, prefix in families:
        real = set(cluster[key].keys())
        expected = {str(ci.iri(prefix, n)): n for n in real}
        in_graph = {str(s) for s in g.subjects(RDF.type, cls)}

        present = set(expected) & in_graph
        missing = [expected[u] for u in set(expected) - in_graph]
        ghosts = [u.split("#")[-1] for u in in_graph - set(expected)]

        score = (len(present) / len(expected)) if expected else 1.0
        rows.append({"famille": label, "cluster": len(real),
                     "graphe": len(in_graph), "presents": len(present),
                     "manquants": sorted(missing), "fantomes": sorted(ghosts),
                     "score": score})
        missing_all += [(label, m) for m in missing]
        ghost_all += [(label, x) for x in ghosts]

    total_exp = sum(r["cluster"] for r in rows)
    total_ok = sum(r["presents"] for r in rows)
    return {
        "score": (total_ok / total_exp) if total_exp else 1.0,
        "rows": rows, "missing": missing_all, "ghosts": ghost_all,
    }


# ==========================================================================
# M2 — EXACTITUDE SEMANTIQUE
#
# On reconstruit les triplets que le graphe DEVRAIT contenir, depuis l'API,
# et on compte ceux qui y sont vraiment. Ce n'est pas un diff de fichiers :
# c'est une verification fait par fait.
# ==========================================================================
def m2_accuracy(g, ns, cluster):
    expected, wrong = [], []

    def check(subj, pred, obj, label):
        expected.append(label)
        if (subj, pred, obj) not in g:
            found = list(g.objects(subj, pred))
            wrong.append({
                "fait": label,
                "attendu": str(obj),
                "dans_le_graphe": [str(f) for f in found] or ["(absent)"],
            })

    # Deployments : actualReplicas
    for name, d in cluster["deployments"].items():
        subj = ci.iri("", name)
        if (subj, RDF.type, ns.Deployment) not in g:
            continue
        check(subj, ns.actualReplicas, Literal(d["replicas"]),
              "%s actualReplicas = %d" % (name, d["replicas"]))

    # Pods : runsOn et partOf
    for name, p in cluster["pods"].items():
        subj = ci.iri("pod", name)
        if (subj, RDF.type, ns.Pod) not in g:
            continue
        if p["node"]:
            check(subj, ns.runsOn, ci.iri("node", p["node"]),
                  "%s runsOn %s" % (name, p["node"]))
        if p["owner"]:
            check(subj, ns.partOf, ci.iri("", p["owner"]),
                  "%s partOf %s" % (name, p["owner"]))

    # Nodes : chaque etiquette reelle doit etre dans le graphe
    for name, n in cluster["nodes"].items():
        subj = ci.iri("node", name)
        if (subj, RDF.type, ns.Node) not in g:
            continue
        for lab in n["labels"]:
            check(subj, ns.offersLabel, Literal(lab),
                  "%s offersLabel %s" % (name, lab))

    total = len(expected)
    ok = total - len(wrong)
    return {"score": (ok / total) if total else 1.0,
            "attendus": total, "corrects": ok, "divergences": wrong}


# ==========================================================================
# M3 — COHERENCE LOGIQUE
#
# Chaque verification correspond a un axiome OWL. On les evalue directement
# plutot que par un raisonneur : le resultat est le meme pour ces axiomes-la,
# et le diagnostic est plus lisible. Les axiomes correspondants sont indiques,
# pour que tu puisses les ajouter a la TBox et les faire verifier par Protege.
# ==========================================================================
def m3_consistency(g, ns):
    checks = []

    def record(name, axiom, violations):
        checks.append({"regle": name, "axiome": axiom,
                       "violations": violations, "ok": not violations})

    # runsOn fonctionnelle : un Pod ne tourne que sur UN noeud.
    v = []
    for pod in set(g.subjects(RDF.type, ns.Pod)):
        nodes = list(g.objects(pod, ns.runsOn))
        if len(nodes) > 1:
            v.append("%s runsOn %d noeuds" % (str(pod).split("#")[-1], len(nodes)))
    record("un Pod sur un seul Node", ":runsOn a owl:FunctionalProperty", v)

    # partOf fonctionnelle
    v = []
    for pod in set(g.subjects(RDF.type, ns.Pod)):
        deps = list(g.objects(pod, ns.partOf))
        if len(deps) > 1:
            v.append("%s partOf %d deployments" % (str(pod).split("#")[-1], len(deps)))
    record("un Pod dans un seul Deployment", ":partOf a owl:FunctionalProperty", v)

    # Classes disjointes
    v = []
    classes = [("Pod", ns.Pod), ("Node", ns.Node), ("Deployment", ns.Deployment)]
    for i, (n1, c1) in enumerate(classes):
        for n2, c2 in classes[i + 1:]:
            both = set(g.subjects(RDF.type, c1)) & set(g.subjects(RDF.type, c2))
            for x in both:
                v.append("%s est a la fois %s et %s"
                         % (str(x).split("#")[-1], n1, n2))
    record("classes disjointes", ":Pod owl:disjointWith :Node", v)

    # Codomaine de runsOn : la cible doit etre un Node
    v = []
    for _, _, o in g.triples((None, ns.runsOn, None)):
        if (o, RDF.type, ns.Node) not in g:
            v.append("runsOn pointe vers %s, qui n'est pas un Node"
                     % str(o).split("#")[-1])
    record("runsOn vise un Node", ":runsOn rdfs:range :Node", sorted(set(v)))

    # Codomaine de partOf
    v = []
    for _, _, o in g.triples((None, ns.partOf, None)):
        if (o, RDF.type, ns.Deployment) not in g:
            v.append("partOf pointe vers %s, qui n'est pas un Deployment"
                     % str(o).split("#")[-1])
    record("partOf vise un Deployment", ":partOf rdfs:range :Deployment",
           sorted(set(v)))

    # Tout individu porte un type
    v = []
    typed = set(g.subjects(RDF.type, None))
    for s in set(g.subjects(None, None)):
        if s not in typed and str(s).startswith(str(ns)):
            v.append(str(s).split("#")[-1])
    record("tout individu est type", "(bonne pratique)", sorted(set(v))[:10])

    total = len(checks)
    passed = sum(1 for c in checks if c["ok"])
    return {"score": passed / total if total else 1.0,
            "checks": checks, "passed": passed, "total": total}


# ==========================================================================
# M4 — LATENCE DE PROPAGATION  (mesure active)
# ==========================================================================
def m4_latency(graph_path, ns, node, rounds, timeout):
    print()
    print("=== M4 — LATENCE DE PROPAGATION ===")
    print("Mesure ACTIVE : pose une etiquette temoin sur %s, chronometre son"
          % node)
    print("apparition dans le graphe, puis nettoie. %d mesure(s)." % rounds)
    print()

    delays_add, delays_del = [], []
    subj = ci.iri("node", node)

    def wait_for(label, present, deadline):
        """Attend que l'etiquette apparaisse (ou disparaisse) du graphe."""
        while time.time() < deadline:
            g = Graph()
            try:
                g.parse(graph_path, format="turtle")
            except Exception:
                time.sleep(0.2)
                continue
            there = (subj, ns.offersLabel, Literal(label)) in g
            if there == present:
                return time.time()
            time.sleep(0.2)
        return None

    for i in range(rounds):
        value = "r%d" % int(time.time())
        label = "%s=%s" % (PROBE_KEY, value)

        t0 = time.time()
        ok, err = kube_apply_label(node, PROBE_KEY, value)
        if not ok:
            print("  echec de l'etiquetage : %s" % err)
            break
        t1 = wait_for(label, True, t0 + timeout)
        if t1 is None:
            print("  %d/%d  AJOUT   : non propage en %ds" % (i + 1, rounds, timeout))
        else:
            delays_add.append(t1 - t0)
            print("  %d/%d  AJOUT   : %.2fs" % (i + 1, rounds, t1 - t0))

        t2 = time.time()
        kube_apply_label(node, PROBE_KEY, None)
        t3 = wait_for(label, False, t2 + timeout)
        if t3 is None:
            print("  %d/%d  RETRAIT : non propage en %ds" % (i + 1, rounds, timeout))
        else:
            delays_del.append(t3 - t2)
            print("  %d/%d  RETRAIT : %.2fs" % (i + 1, rounds, t3 - t2))

    def stats(xs):
        if not xs:
            return None
        s = sorted(xs)
        return {"n": len(s), "min": s[0], "median": s[len(s) // 2], "max": s[-1],
                "mean": sum(s) / len(s)}

    res = {"ajout": stats(delays_add), "retrait": stats(delays_del),
           "timeout_s": timeout, "node": node}

    print()
    for nom, st in (("ajout", res["ajout"]), ("retrait", res["retrait"])):
        if st:
            print("  %-9s n=%d  min %.2fs  median %.2fs  max %.2fs"
                  % (nom, st["n"], st["min"], st["median"], st["max"]))
        else:
            print("  %-9s aucune mesure aboutie" % nom)

    print()
    print("  La mediane est ta latence typique ; le max est ce qu'un relecteur")
    print("  regardera. Compare-les a la periode de resynchronisation de")
    print("  l'operateur : une latence proche de la periode signifie que le")
    print("  changement n'a ete vu qu'au resync suivant, pas par l'evenement.")
    return res


# ==========================================================================
# RAPPORT
# ==========================================================================
def bar(score, width=22):
    full = int(round(score * width))
    return "[" + "#" * full + "." * (width - full) + "]"


def report(m1, m2, m3, graph_triples):
    print()
    print("=== FIDELITE DU JUMEAU ===")
    print("Graphe : %d triplets" % graph_triples)
    print()
    print("  %-28s %6s  %s" % ("DIMENSION", "SCORE", ""))
    print("  " + "-" * 62)
    print("  %-28s %5.1f%%  %s" % ("M1 completude population",
                                   m1["score"] * 100, bar(m1["score"])))
    print("  %-28s %5.1f%%  %s" % ("M2 exactitude semantique",
                                   m2["score"] * 100, bar(m2["score"])))
    print("  %-28s %5.1f%%  %s" % ("M3 coherence logique",
                                   m3["score"] * 100, bar(m3["score"])))

    print()
    print("--- M1 : detail par famille ---")
    print("  %-14s %8s %8s %9s" % ("", "CLUSTER", "GRAPHE", "COUVERTS"))
    for r in m1["rows"]:
        print("  %-14s %8d %8d %8.0f%%"
              % (r["famille"], r["cluster"], r["graphe"], r["score"] * 100))
    if m1["missing"]:
        print()
        print("  MANQUANTS — dans le cluster, absents du graphe :")
        for fam, name in m1["missing"][:10]:
            print("    %s %s" % (fam, name))
        if len(m1["missing"]) > 10:
            print("    ... et %d autre(s)" % (len(m1["missing"]) - 10))
    if m1["ghosts"]:
        print()
        print("  FANTOMES — dans le graphe, disparus du cluster :")
        for fam, name in m1["ghosts"][:10]:
            print("    %s %s" % (fam, name))
        if len(m1["ghosts"]) > 10:
            print("    ... et %d autre(s)" % (len(m1["ghosts"]) - 10))
        print("    Un fantome signifie que le jumeau n'a pas vu une")
        print("    suppression. Sur un graphe reconstruit a chaque")
        print("    reconciliation, cela ne devrait jamais arriver.")

    print()
    print("--- M2 : %d fait(s) verifie(s), %d correct(s) ---"
          % (m2["attendus"], m2["corrects"]))
    if m2["divergences"]:
        print("  DIVERGENCES :")
        for d in m2["divergences"][:10]:
            print("    %s" % d["fait"])
            print("      graphe : %s" % ", ".join(d["dans_le_graphe"]))
        if len(m2["divergences"]) > 10:
            print("    ... et %d autre(s)" % (len(m2["divergences"]) - 10))
    else:
        print("  aucune divergence.")

    print()
    print("--- M3 : %d/%d axiomes respectes ---" % (m3["passed"], m3["total"]))
    for c in m3["checks"]:
        mark = "ok  " if c["ok"] else "ECHEC"
        print("  %-5s %-32s %s" % (mark, c["regle"], c["axiome"]))
        for v in c["violations"][:5]:
            print("          -> %s" % v)

    print()
    print("Lecture : M1 et M2 mesurent si le jumeau dit vrai sur le cluster.")
    print("M3 mesure s'il est coherent avec lui-meme — un echec ici vient")
    print("d'un bug du fact-writer, pas d'une derive du cluster.")


def main():
    ap = argparse.ArgumentParser(
        description="Mesure la fidelite du jumeau face au cluster reel.")
    ap.add_argument("--graph", default=GRAPH_FILE)
    ap.add_argument("--tbox", default=TBOX_FILE)
    ap.add_argument("--namespace", default=None,
                    help="restreindre a un namespace (defaut : tous)")
    ap.add_argument("--latency", action="store_true",
                    help="mesurer aussi la latence — MODIFIE le cluster")
    ap.add_argument("--latency-node", default=None,
                    help="noeud a etiqueter pour M4 (defaut : le premier)")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--json", default=REPORT_FILE)
    args = ap.parse_args()

    if not os.path.exists(args.graph):
        sys.exit("Graphe introuvable : %s\nLance l'operateur d'abord." % args.graph)

    ns = ci.setup(args.tbox, args.graph)

    g = Graph()
    g.parse(args.graph, format="turtle")

    print("Interrogation de l'API Kubernetes...")
    cluster = read_cluster(args.namespace)
    print("  %d Node(s), %d Deployment(s), %d Pod(s) dans le cluster"
          % (len(cluster["nodes"]), len(cluster["deployments"]),
             len(cluster["pods"])))

    m1 = m1_population(g, ns, cluster)
    m2 = m2_accuracy(g, ns, cluster)
    m3 = m3_consistency(g, ns)
    report(m1, m2, m3, len(g))

    m4 = None
    if args.latency:
        node = args.latency_node or sorted(cluster["nodes"])[0]
        m4 = m4_latency(args.graph, ns, node, args.rounds, args.timeout)

    out = {"graph_triples": len(g),
           "m1_population": m1, "m2_accuracy": m2, "m3_consistency": m3,
           "m4_latency": m4}
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print()
    print("Rapport ecrit dans %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
