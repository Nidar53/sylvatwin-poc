#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verdict.py — LE VERDICT DATE.

Le probleme
-----------
detect.py ne regarde pas le cluster. Il regarde une PHOTO du cluster, le
fichier sylvatwin-graph.ttl. Quand l'operateur tourne, la photo a deux
secondes. Quand il est eteint, la photo a sept heures — et le systeme
repond quand meme "aucune derive".

C'est faux. Il ne sait rien du cluster. Il decrit une vieille photo.
ArgoCD a le meme defaut. Kyverno aussi.

La proposition
--------------
Un verdict de conformite n'est pas un booleen mais un couple
(verdict, horizon de validite). Trois reponses au lieu de deux :

    CONFORME   verifie, et l'information est encore fraiche
    VIOLE      derive constatee sur information fraiche
    INCONNU    l'information est trop vieille pour qu'on y croie

Et le point qui fait que ce n'est pas "juste un timestamp" : chaque
contrainte perime a SA vitesse. Une etiquette de noeud (offersLabel)
change une fois par mois ; le placement d'un pod (runsOn) change a chaque
eviction. Un verdict de placement vieux de cinq minutes est deja douteux
quand un verdict sur une etiquette materielle tient encore une heure.

Cette vitesse se mesure : c'est ce que fait la commande 'observe'.

Comment l'age est calcule
-------------------------
1. compile_intent.py annote chaque contrainte avec :readsProperty.
2. Pour chaque propriete p, l'age = now - min(observedAt) parmi les
   individus qui portent p. (Le fait le plus vieux de ce type : choix
   conservateur.)
3. L'age d'un verdict = le maximum des ages des proprietes qu'il lit.
   Le maillon le plus faible decide.
4. Si age > tau(p) pour l'une d'elles, le verdict passe a INCONNU,
   que SHACL ait dit conforme ou viole.

C'est la tracabilite du compilateur qui rend l'etape 1 possible. Une
requete SPARQL ecrite a la main ne sait pas dire quelles proprietes elle
consulte ; une contrainte compilee le sait par construction.

Commandes
---------
    python3 verdict.py check                       verdict date, maintenant
    python3 verdict.py observe --duration 300      mesure les vitesses
    python3 verdict.py horizons                    calcule les horizons tau
    python3 verdict.py demo                        l'experience complete,
                                                   sans cluster
Prerequis :
    pip install pyshacl rdflib pyyaml
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

try:
    from rdflib import Graph, Namespace, Literal, URIRef
    from rdflib.namespace import RDF, XSD
except ImportError:
    sys.exit("Il manque rdflib :  pip install rdflib")

try:
    from pyshacl import validate
except ImportError:
    sys.exit("Il manque pyshacl :  pip install pyshacl")

HERE = os.path.dirname(os.path.abspath(__file__))

# compile_intent.py est a cote de ce fichier : on l'importe depuis la, quel
# que soit le dossier depuis lequel la commande est lancee.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import compile_intent as ci

GRAPH_FILE = os.path.join(HERE, "sylvatwin-graph.ttl")
TBOX_FILE = os.path.join(HERE, "sylvatwin-slice-v0.ttl")
GIT_DIR = os.path.join(HERE, "git-desired")
SHAPES_FILE = os.path.join(HERE, "sylvatwin-shapes.ttl")
CHANGES_FILE = os.path.join(HERE, "sylvatwin-changes.json")
HORIZONS_FILE = os.path.join(HERE, "sylvatwin-horizons.json")
VERDICTS_FILE = os.path.join(HERE, "sylvatwin-verdicts.ttl")

SH = Namespace("http://www.w3.org/ns/shacl#")

CONFORME, VIOLE, INCONNU = "CONFORME", "VIOLE", "INCONNU"

# Horizons de repli, en secondes, si aucune mesure n'a encore ete faite.
# Ordres de grandeur volontairement contrastes : c'est l'hypothese que la
# commande 'observe' est censee confirmer ou refuter.
DEFAULT_HORIZONS = {
    "offersLabel": 3600.0,      # etiquette materielle : change rarement
    "actualReplicas": 60.0,     # nombre de pods : change souvent
    "partOf": 300.0,            # appartenance : change au redeploiement
    "runsOn": 120.0,            # placement : change a chaque eviction
}


# ==========================================================================
# 1. MESURE DES VITESSES DE CHANGEMENT
# ==========================================================================
def cmd_observe(args):
    """
    Echantillonne le graphe et compte, par propriete, combien de faits
    changent. Sortie : sylvatwin-changes.json.

    A lancer pendant que le cluster vit (scale, evictions, redemarrages).
    Plus l'observation est longue, plus les horizons sont fiables.
    """
    if not os.path.exists(args.graph):
        sys.exit("Graphe introuvable : %s\nLance l'operateur d'abord." % args.graph)

    print("Observation de %s" % args.graph)
    print("Duree %ds, echantillon toutes les %ds. Ctrl+C pour arreter plus tot."
          % (args.duration, args.interval))
    print()

    counts, prev = {}, None
    pop_sum = {}          # somme du nombre de sujets porteurs, par propriete
    started = time.time()
    samples = 0

    # Proprietes exclues du comptage :
    #   observedAt : c'est l'horodatage lui-meme, il change a chaque resync.
    #   type       : rdf:type ne bouge que lorsqu'un individu nait ou meurt ;
    #                le compter ferait du bruit sur toutes les proprietes.
    def skip(p):
        name = str(p).split("#")[-1].split("/")[-1]
        return name in ("observedAt", "type")

    try:
        while time.time() - started < args.duration:
            g = Graph()
            try:
                g.parse(args.graph, format="turtle")
            except Exception:
                time.sleep(args.interval)
                continue

            cur = {(s, p, o) for s, p, o in g if not skip(p)}
            samples += 1

            # Combien d'individus portent chaque propriete, a cet instant.
            # Sert a ramener le taux a UN fait, voir plus bas.
            pop = {}
            for s, p, _ in cur:
                name = str(p).split("#")[-1].split("/")[-1]
                pop.setdefault(name, set()).add(s)
            for name, subjects in pop.items():
                pop_sum[name] = pop_sum.get(name, 0) + len(subjects)

            if prev is not None:
                for triple in (cur - prev) | (prev - cur):
                    name = str(triple[1]).split("#")[-1].split("/")[-1]
                    counts[name] = counts.get(name, 0) + 1
                elapsed = time.time() - started
                total = sum(counts.values())
                print("\r  %4ds  %3d echantillons  %4d changements"
                      % (elapsed, samples, total), end="", flush=True)

            prev = cur
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n  interrompu.")

    duration = time.time() - started
    # Nombre moyen d'individus porteurs, par propriete.
    population = {n: (pop_sum[n] / samples) for n in pop_sum} if samples else {}

    data = {"duration_s": duration, "samples": samples,
            "changes": counts, "population": population}
    with open(args.changes, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print()
    print()
    print("=== CHANGEMENTS OBSERVES en %.0fs ===" % duration)
    if not counts:
        print("  aucun changement : le cluster est reste stable.")
        print("  C'est un resultat valable — les horizons seront longs.")
    print("  %-20s %7s %9s %12s" % ("PROPRIETE", "CHANG.", "PORTEURS", "PAR FAIT /s"))
    print("  " + "-" * 54)
    for name, n in sorted(counts.items(), key=lambda x: -x[1]):
        pop = population.get(name, 1.0) or 1.0
        print("  %-20s %7d %9.1f %12.5f"
              % (name, n, pop, n / duration / pop))
    print()
    print("Lecture : 'par fait' ramene le taux a UN individu. Sans cela, un")
    print("cluster de 50 pods paraitrait 50 fois plus instable qu'un cluster")
    print("d'un seul pod, alors que chaque pod y est tout aussi stable.")
    print()
    print("Ecrit dans %s" % args.changes)
    print("Etape suivante :  python3 verdict.py horizons")
    return 0


def cmd_horizons(args):
    """
    Transforme les comptages en horizons de validite.

    lambda(p) = changements(p) / duree / porteurs(p)
                -> taux auquel UN fait de ce type change.
                Diviser par le nombre de porteurs est indispensable : sinon un
                cluster de 50 pods paraitrait 50 fois plus instable qu'un
                cluster d'un seul pod, alors que chaque pod y est aussi stable.

    tau(p)    = -ln(confiance) / lambda(p)
                -> duree pendant laquelle le verdict reste croyable.

    Avec une confiance de 0.9 : tau est le delai au bout duquel il y a 10 %
    de chances que le fait ait change. Modele de Poisson, le meme que celui
    de l'Age of Information.

    Condition de conception
    -----------------------
    Un jumeau qui se resynchronise toutes les R secondes porte un age qui
    oscille entre 0 et R. Si tau(p) < R, le verdict est perime avant la
    resynchronisation suivante : aucune conclusion ferme n'est jamais
    possible sur cette propriete. C'est ce que signale l'avertissement.
    """
    if not os.path.exists(args.changes):
        sys.exit("Pas de mesures. Lance d'abord :  python3 verdict.py observe")

    with open(args.changes, encoding="utf-8") as f:
        data = json.load(f)

    duration = data["duration_s"]
    counts = data["changes"]
    population = data.get("population", {})
    k = -math.log(args.confidence)
    R = args.resync

    horizons = {}
    trop_lent = []

    print("=== HORIZONS DE VALIDITE  (confiance %.0f%%) ===" % (args.confidence * 100))
    print("Observation : %.0fs. Periode de resynchronisation : %ds." % (duration, R))
    print()
    print("  %-20s %8s %11s %10s %10s" %
          ("PROPRIETE", "PORTEURS", "lambda/fait", "tau", "source"))
    print("  " + "-" * 64)

    names = set(counts) | set(DEFAULT_HORIZONS)
    for name in sorted(names):
        n = counts.get(name, 0)
        pop = population.get(name, 1.0) or 1.0
        if n > 0:
            lam = n / duration / pop
            tau = k / lam
            source = "mesure"
        else:
            # Aucun changement vu : on ne pretend pas savoir au-dela de ce
            # qu'on a observe. L'horizon est borne par la duree d'observation.
            tau = max(duration, DEFAULT_HORIZONS.get(name, 300.0))
            lam = 0.0
            source = "borne" if name in population else "defaut"
        horizons[name] = tau
        flag = "  <-- trop court" if tau < R else ""
        if tau < R:
            trop_lent.append((name, tau))
        print("  %-20s %8.1f %11.5f %9.0fs %10s%s"
              % (name, pop, lam, tau, source, flag))

    with open(args.horizons, "w", encoding="utf-8") as f:
        json.dump({"confidence": args.confidence, "resync_s": R,
                   "horizons": horizons}, f, indent=2)

    print()
    if trop_lent:
        print("DIAGNOSTIC — l'operateur est trop lent pour %d propriete(s) :"
              % len(trop_lent))
        for name, tau in trop_lent:
            print("  %s perime en %.0fs, mais la resynchronisation est de %ds."
                  % (name, tau, R))
        print()
        print("Consequence : sur ces proprietes, aucun verdict ferme n'est")
        print("jamais possible — la photo est deja perimee quand elle arrive.")
        print("Deux issues : resynchroniser plus vite CES proprietes-la, ou")
        print("accepter de ne jamais conclure dessus. C'est l'argument de la")
        print("resynchronisation adaptative, mesure sur ton propre cluster.")
        print()
        print("Si tu as secoue le cluster pendant l'observation (scale, labels,")
        print("suppression de pods), ces taux sont ceux d'un cluster sous stress,")
        print("pas d'un cluster en regime normal. Refais une observation SANS")
        print("rien toucher pour obtenir les horizons de reference.")
    else:
        print("Tous les horizons depassent la periode de resynchronisation (%ds)."
              % R)
        print("Le jumeau est assez rapide pour conclure sur toutes les proprietes.")
    print()
    print("Ecrit dans %s" % args.horizons)
    print("Etape suivante :  python3 verdict.py check")
    return 0


def load_horizons(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d["horizons"], True
    return dict(DEFAULT_HORIZONS), False


# ==========================================================================
# 2. AGE DES FAITS
# ==========================================================================
def property_ages(graph, ns, now=None):
    """
    Pour chaque propriete, l'age du fait le PLUS VIEUX de ce type.

    On lit :observedAt sur chaque individu. Un individu sans observedAt est
    ignore (cote desired : Git n'a pas d'horodatage d'observation).
    """
    now = now or datetime.now(timezone.utc)
    observed = {}
    for s, _, o in graph.triples((None, ns.observedAt, None)):
        try:
            dt = o.toPython()
        except Exception:
            continue
        if not isinstance(dt, datetime):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        observed[s] = dt

    ages = {}
    for s, p, _ in graph:
        if s not in observed:
            continue
        name = str(p).split("#")[-1].split("/")[-1]
        if name == "observedAt":
            continue
        age = (now - observed[s]).total_seconds()
        ages[name] = max(ages.get(name, 0.0), age)
    return ages, observed


# ==========================================================================
# 3. LE VERDICT DATE
# ==========================================================================
def dated_verdicts(graph, shapes, ns, horizons, now=None):
    """
    Valide le graphe, puis qualifie chaque contrainte par l'age des faits
    qui la soutiennent.

    Retourne une liste de dicts : contrainte, verdict, age, horizon,
    propriete limitante, message.
    """
    ages, observed = property_ages(graph, ns, now)

    conforms, report, _ = validate(
        data_graph=graph, shacl_graph=shapes, advanced=True)

    # Quelles contraintes ont ete violees, et sur quel noeud.
    violated = {}
    for res in report.subjects(RDF.type, SH.ValidationResult):
        src = report.value(res, SH.sourceShape)
        focus = report.value(res, SH.focusNode)
        msg = report.value(res, SH.resultMessage)
        if isinstance(src, URIRef):
            violated.setdefault(src, []).append((focus, str(msg) if msg else ""))

    results = []
    # Toutes les contraintes compilees, violees ou non.
    for c in sorted(set(shapes.subjects(ns.readsProperty, None)), key=str):
        reads = [str(p).split("#")[-1] for p in shapes.objects(c, ns.readsProperty)]
        msg = shapes.value(c, SH.message)
        field = shapes.value(c, ns.derivedFromField)
        drift = shapes.value(c, ns.detectsDrift)

        # Le maillon le plus faible : la propriete dont l'age ronge le plus
        # son horizon.
        worst_prop, worst_ratio, worst_age, worst_tau = None, 0.0, 0.0, None
        for p in reads:
            age = ages.get(p)
            tau = horizons.get(p, DEFAULT_HORIZONS.get(p, 300.0))
            if age is None:
                continue
            ratio = age / tau if tau else float("inf")
            if ratio >= worst_ratio:
                worst_prop, worst_ratio, worst_age, worst_tau = p, ratio, age, tau

        if worst_prop is None:
            verdict = INCONNU   # aucun fait observe du tout
            worst_age, worst_tau, worst_prop = float("nan"), None, "-"
        elif worst_ratio > 1.0:
            verdict = INCONNU   # information perimee : on ne conclut pas
        elif c in violated:
            verdict = VIOLE
        else:
            verdict = CONFORME

        results.append({
            "uri": c,
            "constraint": str(c).split("#")[-1],
            "verdict": verdict,
            "reads": reads,
            "limiting": worst_prop,
            "age_s": worst_age,
            "tau_s": worst_tau,
            "ratio": worst_ratio,
            "message": str(msg) if msg else "",
            "field": str(field) if field else None,
            "drift": drift,
            "focus": sorted({str(f).split("#")[-1]
                             for f, _ in violated.get(c, [])}),
            "focus_uris": sorted({f for f, _ in violated.get(c, [])}, key=str),
        })

    return results, conforms, observed


# ==========================================================================
# 3bis. LE VERDICT COMME INDIVIDU DU JUMEAU
#
# Un verdict affiche dans un terminal n'existe pas dans le jumeau. Materialise,
# il se requete, s'historise et se compare. C'est la difference entre un outil
# de diagnostic et un jumeau qui porte l'etat de sa propre analyse.
#
# Demande la TBox d'extension : sylvatwin-verdict-tbox.ttl
# ==========================================================================
VERDICT_CLASS = {
    CONFORME: "ConformVerdict",
    VIOLE: "ViolatedVerdict",
    INCONNU: "UnknownVerdict",
}


def materialize_verdicts(results, ns, graph_age, now=None):
    """Construit le graphe des verdicts, a ecrire a cote du graphe observe."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S")
    iso = Literal(now.isoformat(), datatype=XSD.dateTime)

    g = Graph()
    g.bind("", ns)
    g.bind("xsd", XSD)

    n = {CONFORME: 0, VIOLE: 0, INCONNU: 0}

    for r in results:
        n[r["verdict"]] += 1
        v = ns["verdict_%s_%s" % (r["constraint"], stamp)]

        g.add((v, RDF.type, ns.Verdict))
        g.add((v, RDF.type, ns[VERDICT_CLASS[r["verdict"]]]))
        g.add((v, ns.aboutConstraint, r["uri"]))
        g.add((v, ns.issuedAt, iso))

        if r["tau_s"] is not None:
            g.add((v, ns.validityHorizon,
                   Literal(round(r["tau_s"], 2), datatype=XSD.decimal)))
        if r["age_s"] == r["age_s"]:          # pas NaN
            g.add((v, ns.informationAge,
                   Literal(round(r["age_s"], 2), datatype=XSD.decimal)))
            if r["tau_s"]:
                g.add((v, ns.stalenessRatio,
                       Literal(round(r["ratio"], 3), datatype=XSD.decimal)))
        if r["limiting"] and r["limiting"] != "-":
            g.add((v, ns.limitedBy, ns[r["limiting"]]))

        for uri in r["focus_uris"]:
            g.add((v, ns.evidence, uri))
            g.add((v, ns.aboutResource, uri))

        # Compatibilite avec la TBox v0 : une violation fraiche produit aussi
        # l'individu Drift de la famille correspondante, exactement comme
        # detect.py --materialize le faisait. Les anciennes requetes SPARQL
        # continuent donc de fonctionner.
        #
        # Noter qu'un verdict INCONNU ne produit AUCUN Drift : on ne materialise
        # pas une derive qu'on n'a pas pu constater. C'est tout le point.
        if r["verdict"] == VIOLE and r["drift"] is not None:
            for uri in r["focus_uris"]:
                d = ns["drift_%s_%s" % (str(uri).split("#")[-1], stamp)]
                g.add((d, RDF.type, r["drift"]))
                g.add((d, ns.aboutResource, uri))
                g.add((d, ns.issuedAt, iso))
                g.add((v, ns.evidence, d))

    # L'etat du jumeau lui-meme.
    ts = ns["twinstate_%s" % stamp]
    g.add((ts, RDF.type, ns.TwinState))
    g.add((ts, ns.issuedAt, iso))
    g.add((ts, ns.conformCount, Literal(n[CONFORME])))
    g.add((ts, ns.violatedCount, Literal(n[VIOLE])))
    g.add((ts, ns.unknownCount, Literal(n[INCONNU])))
    g.add((ts, ns.decidable, Literal(n[INCONNU] == 0)))
    if graph_age is not None:
        g.add((ts, ns.graphAge,
               Literal(round(graph_age, 2), datatype=XSD.decimal)))

    return g


def print_verdicts(results, measured):
    print("=== VERDICT DATE ===")
    if not measured:
        print("(horizons par defaut — lance 'observe' puis 'horizons' pour les mesurer)")
    print()
    print("  %-10s %-34s %-16s %9s %9s" %
          ("VERDICT", "CONTRAINTE", "LIMITE PAR", "AGE", "HORIZON"))
    print("  " + "-" * 86)

    order = {VIOLE: 0, INCONNU: 1, CONFORME: 2}
    for r in sorted(results, key=lambda x: (order[x["verdict"]], x["constraint"])):
        age = "-" if r["age_s"] != r["age_s"] else "%.0fs" % r["age_s"]
        tau = "-" if r["tau_s"] is None else "%.0fs" % r["tau_s"]
        print("  %-10s %-34s %-16s %9s %9s" %
              (r["verdict"], r["constraint"], r["limiting"], age, tau))

    print()
    for r in results:
        if r["verdict"] == VIOLE:
            print("  VIOLE   : %s" % r["message"])
            for f in r["focus"]:
                print("            -> %s" % f)
    for r in results:
        if r["verdict"] == INCONNU:
            print("  INCONNU : %s" % r["constraint"])
            print("            l'information sur '%s' a %.0fs, horizon %s. "
                  "Aucune conclusion." %
                  (r["limiting"],
                   0 if r["age_s"] != r["age_s"] else r["age_s"],
                   "-" if r["tau_s"] is None else "%.0fs" % r["tau_s"]))

    n = {v: sum(1 for r in results if r["verdict"] == v)
         for v in (CONFORME, VIOLE, INCONNU)}
    print()
    print("%d conforme(s), %d violee(s), %d inconnue(s)."
          % (n[CONFORME], n[VIOLE], n[INCONNU]))

    if n[INCONNU]:
        print()
        print("ATTENTION : un systeme classique aurait repondu 'conforme' "
              "sur ces %d contraintes." % n[INCONNU])


def cmd_check(args):
    if not os.path.exists(args.graph):
        sys.exit("Graphe introuvable : %s" % args.graph)

    ns = ci.setup(args.tbox, args.graph)
    intents = ci.read_intents(args.git_dir)
    if not intents:
        sys.exit("Aucun Deployment dans %s" % args.git_dir)

    shapes, catalogue = ci.compile_all(intents)
    shapes.serialize(destination=args.shapes, format="turtle")
    print("%d contraintes compilees depuis %d manifeste(s)."
          % (len(catalogue), len(intents)))

    graph = Graph()
    graph.parse(args.graph, format="turtle")
    print("Graphe charge : %d triplets" % len(graph))
    print()

    horizons, measured = load_horizons(args.horizons)
    results, _, observed = dated_verdicts(graph, shapes, ns, horizons)

    graph_age = None
    if observed:
        newest = max(observed.values())
        graph_age = (datetime.now(timezone.utc) - newest).total_seconds()
        print("Photo la plus recente : %.0fs" % graph_age)
        print()
    print_verdicts(results, measured)

    if args.materialize:
        vg = materialize_verdicts(results, ns, graph_age)
        vg.serialize(destination=args.verdicts, format="turtle")
        print()
        print("%d triplets de verdict ecrits dans %s" % (len(vg), args.verdicts))
        print("Le jumeau porte maintenant l'etat de sa propre analyse.")
        print("Charge-le dans Protege avec sylvatwin-verdict-tbox.ttl.")
    return 0


# ==========================================================================
# 4. L'EXPERIENCE — sans cluster, pour verifier que tout tient
# ==========================================================================
#
# Point crucial du banc d'essai : la PHOTO et la VERITE sont deux choses
# distinctes. C'est tout l'interet du probleme. Un systeme qui ne regarde que
# la photo ne peut pas se tromper si la photo reflete toujours la verite —
# c'est l'erreur que fait un banc d'essai naif.
#
# Quand l'operateur meurt, la photo se FIGE. Le cluster, lui, continue de
# vivre. L'ecart entre les deux est precisement ce qu'on mesure.
#
SCENARIOS = [
    # (nom, age photo, ce que montre la photo, la verite du cluster)
    ("Photo fraiche, cluster sain",
     5,     False, False),
    ("Photo fraiche, etiquette retiree",
     5,     True,  True),
    ("Photo de 3 min, rien n'a bouge",
     180,   False, False),
    ("Operateur mort 7h, derive survenue depuis",
     25200, False, True),
    ("Operateur mort 7h, derive deja reparee",
     25200, True,  False),
    ("Operateur mort 7h, rien n'a bouge",
     25200, False, False),
]


def build_graph(ns, age_s, drifted, now=None):
    """
    Fabrique un graphe observe avec un age choisi.
    'drifted' decrit ce que montre LA PHOTO, pas la verite du cluster.
    """
    now = now or datetime.now(timezone.utc)
    obs = now.timestamp() - age_s
    stamp = datetime.fromtimestamp(obs, tz=timezone.utc).isoformat()

    g = Graph()
    g.bind("", ns)
    dep = ns["webapp"]
    g.add((dep, RDF.type, ns.Deployment))
    g.add((dep, ns.desiredReplicas, Literal(3)))
    g.add((dep, ns.actualReplicas, Literal(3)))
    g.add((dep, ns.requiresNodeLabel, Literal("disktype=ssd")))
    g.add((dep, ns.observedAt, Literal(stamp, datatype=XSD.dateTime)))

    node = ns["node_sylvatwin_worker2"]
    g.add((node, RDF.type, ns.Node))
    g.add((node, ns.offersLabel, Literal("kubernetes.io/hostname=sylvatwin-worker2")))
    if not drifted:
        g.add((node, ns.offersLabel, Literal("disktype=ssd")))
    g.add((node, ns.observedAt, Literal(stamp, datatype=XSD.dateTime)))

    for suffix in ("6zsbr", "bpnqk", "vzpfp"):
        pod = ns["pod_webapp_647d44fb8c_%s" % suffix]
        g.add((pod, RDF.type, ns.Pod))
        g.add((pod, ns.partOf, dep))
        g.add((pod, ns.runsOn, node))
        g.add((pod, ns.observedAt, Literal(stamp, datatype=XSD.dateTime)))
    return g


def classic_verdict(graph, shapes):
    """Le systeme actuel : un booleen, sans aucune notion d'age."""
    conforms, _, _ = validate(data_graph=graph, shacl_graph=shapes, advanced=True)
    return CONFORME if conforms else VIOLE


def cmd_demo(args):
    ns = ci.setup(args.tbox, args.graph)
    intents = ci.read_intents(args.git_dir)
    if not intents:
        sys.exit("Aucun Deployment dans %s" % args.git_dir)
    shapes, catalogue = ci.compile_all(intents)

    horizons, measured = load_horizons(args.horizons)

    print("=== EXPERIENCE : verdict classique vs verdict date ===")
    print()
    print("%d contraintes compilees. Horizons %s."
          % (len(catalogue), "mesures" if measured else "par defaut"))
    print("Horizon offersLabel = %.0fs, runsOn = %.0fs, actualReplicas = %.0fs"
          % (horizons.get("offersLabel", 0), horizons.get("runsOn", 0),
             horizons.get("actualReplicas", 0)))
    print()
    print("  %-42s %-11s %-11s %-11s %s" %
          ("SITUATION", "VERITE", "CLASSIQUE", "DATE", "JUGEMENT"))
    print("  " + "-" * 104)

    wrong_classic = wrong_dated = 0
    silent_dated = 0

    for label, age, photo_drifted, truth_drifted in SCENARIOS:
        g = build_graph(ns, age, photo_drifted)
        truth = VIOLE if truth_drifted else CONFORME

        classic = classic_verdict(g, shapes)

        results, _, _ = dated_verdicts(g, shapes, ns, horizons)
        # Le verdict global date : VIOLE s'il reste une violation croyable,
        # INCONNU si la moindre contrainte est perimee, CONFORME sinon.
        verdicts = {r["verdict"] for r in results}
        if VIOLE in verdicts:
            dated = VIOLE
        elif INCONNU in verdicts:
            dated = INCONNU
        else:
            dated = CONFORME

        c_bad = classic != truth
        d_bad = dated not in (truth, INCONNU)
        if c_bad:
            wrong_classic += 1
        if d_bad:
            wrong_dated += 1
        if dated == INCONNU:
            silent_dated += 1

        judge = []
        judge.append("classique FAUX" if c_bad else "classique ok")
        if dated == INCONNU:
            judge.append("date s'abstient")
        elif d_bad:
            judge.append("date FAUX")
        else:
            judge.append("date ok")

        print("  %-42s %-11s %-11s %-11s %s"
              % (label, truth, classic, dated, ", ".join(judge)))

    total = len(SCENARIOS)
    print()
    print("=== RESULTAT ===")
    print("  Affirmations fausses, systeme classique : %d / %d"
          % (wrong_classic, total))
    print("  Affirmations fausses, verdict date      : %d / %d"
          % (wrong_dated, total))
    print("  Abstentions du verdict date             : %d / %d"
          % (silent_dated, total))
    print()
    print("Le verdict date ne devine pas mieux : il refuse d'affirmer quand il")
    print("ne sait pas. C'est exactement ce qui manque a ArgoCD et a Kyverno.")
    print()
    print("A noter : les contraintes ne perdent pas leur validite ensemble.")
    print("Le placement perime avant l'etiquette materielle. C'est ce qui")
    print("distingue cette approche d'un simple horodatage global.")
    print()

    simulate_timeline(ns, shapes, horizons)
    return 0


# --------------------------------------------------------------------------
# LA METRIQUE : duree d'assurance erronee.
#
# GitOps mesure le temps de reconciliation. Personne ne mesure le temps
# pendant lequel le systeme a affirme "conforme" alors que le cluster etait
# en derive. C'est cette duree qu'on chiffre ici.
# --------------------------------------------------------------------------
def simulate_timeline(ns, shapes, horizons,
                      total=3600, t_death=600, t_drift=1200, step=60):
    print("=== SIMULATION : duree d'assurance erronee ===")
    print()
    print("  Scenario : l'operateur meurt a t=%ds. La derive reelle survient a"
          % t_death)
    print("  t=%ds. On interroge le systeme toutes les %ds pendant %ds."
          % (t_drift, step, total))
    print("  A partir de t=%ds la photo est FIGEE : elle montre encore un"
          % t_death)
    print("  cluster sain, pour toujours.")
    print()

    lie_classic = lie_dated = silent_dated = 0

    for t in range(0, total + 1, step):
        truth = VIOLE if t >= t_drift else CONFORME

        if t <= t_death:
            photo_age, photo_drifted = 2, (t >= t_drift)
        else:
            # Photo figee a l'instant de la mort de l'operateur.
            photo_age = t - t_death
            photo_drifted = t_death >= t_drift

        g = build_graph(ns, photo_age, photo_drifted)

        classic = classic_verdict(g, shapes)
        results, _, _ = dated_verdicts(g, shapes, ns, horizons)
        verdicts = {r["verdict"] for r in results}
        if INCONNU in verdicts:
            dated = INCONNU
        elif VIOLE in verdicts:
            dated = VIOLE
        else:
            dated = CONFORME

        if classic != truth:
            lie_classic += step
        if dated == INCONNU:
            silent_dated += step
        elif dated != truth:
            lie_dated += step

    print("  %-34s %10s" % ("", "DUREE"))
    print("  " + "-" * 46)
    print("  %-34s %9ds" % ("Mensonge du systeme classique", lie_classic))
    print("  %-34s %9ds" % ("Mensonge du verdict date", lie_dated))
    print("  %-34s %9ds" % ("Ignorance avouee du verdict date", silent_dated))
    print()
    print("  Lecture : le systeme classique a affirme 'conforme' pendant")
    print("  %d secondes alors que le cluster etait casse. Le verdict date" % lie_classic)
    print("  n'a jamais affirme de faux : il a dit 'je ne sais pas' pendant")
    print("  %ds." % silent_dated)
    print()
    print("  On echange du MENSONGE contre de l'IGNORANCE AVOUEE. C'est ce")
    print("  qui justifie l'etape suivante : resynchroniser chaque ressource")
    print("  a la vitesse de son propre horizon, pour reduire les deux.")
    return {"lie_classic": lie_classic, "lie_dated": lie_dated,
            "silent_dated": silent_dated}


# ==========================================================================
def main():
    ap = argparse.ArgumentParser(description="Verdict date de conformite.")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--graph", default=GRAPH_FILE)
        p.add_argument("--tbox", default=TBOX_FILE)
        p.add_argument("--git-dir", default=GIT_DIR)
        p.add_argument("--shapes", default=SHAPES_FILE)
        p.add_argument("--horizons", default=HORIZONS_FILE)
        p.add_argument("--changes", default=CHANGES_FILE)
        p.add_argument("--verdicts", default=VERDICTS_FILE)
        p.add_argument("--materialize", action="store_true",
                       help="ecrire les verdicts comme individus de "
                            "l'ontologie, dans sylvatwin-verdicts.ttl")
        return p

    common(sub.add_parser("check", help="verdict date, maintenant"))

    p = common(sub.add_parser("observe", help="mesurer les vitesses de changement"))
    p.add_argument("--duration", type=int, default=300)
    p.add_argument("--interval", type=int, default=5)

    p = common(sub.add_parser("horizons", help="calculer les horizons tau"))
    p.add_argument("--confidence", type=float, default=0.9)
    p.add_argument("--resync", type=int, default=30,
                   help="periode de resynchronisation de l'operateur, en s "
                        "(resyncPeriod du TwinSync ; 30 par defaut)")

    common(sub.add_parser("demo", help="l'experience complete, sans cluster"))

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1

    return {"check": cmd_check, "observe": cmd_observe,
            "horizons": cmd_horizons, "demo": cmd_demo}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())