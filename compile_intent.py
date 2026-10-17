#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compile_intent.py — LE COMPILATEUR D'INTENTION (v2, avec tracabilite).

Role
----
Lire les manifestes Git et fabriquer, tout seul, les contraintes verifiables.
Tu n'ecris plus une requete par erreur : un champ ajoute dans le YAML produit
une contrainte sans qu'une ligne de code change.

    champ YAML  ->  contrainte SHACL  ->  violation = derive

Nouveaute de cette version : LA TRACABILITE
-------------------------------------------
Chaque contrainte generee declare les proprietes du graphe qu'elle LIT :

    :C_webapp_placement_1  :readsProperty :runsOn , :offersLabel .

C'est ce qui rend le verdict datable. Une requete SPARQL ecrite a la main ne
sait pas dire quelles proprietes elle consulte ; une contrainte compilee le
sait par construction, puisque c'est le compilateur qui l'a assemblee.

verdict.py exploite cette annotation pour calculer l'age de chaque verdict.

Usage
-----
    python3 compile_intent.py            # compile -> sylvatwin-shapes.ttl
    python3 compile_intent.py --validate # compile puis valide (sans datage)
    python3 compile_intent.py --show     # affiche le Turtle genere

Pour le verdict date, utiliser verdict.py.
"""

import argparse
import glob
import os
import sys

try:
    import yaml
except ImportError:
    sys.exit("Il manque PyYAML :  pip install pyyaml")

try:
    from rdflib import Graph, Namespace, Literal, BNode
    from rdflib.namespace import RDF, XSD
    from rdflib.collection import Collection
except ImportError:
    sys.exit("Il manque rdflib :  pip install rdflib")


HERE = os.path.dirname(os.path.abspath(__file__))
GIT_DIR = os.path.join(HERE, "git-desired")
TBOX_FILE = os.path.join(HERE, "sylvatwin-slice-v0.ttl")
GRAPH_FILE = os.path.join(HERE, "sylvatwin-graph.ttl")
SHAPES_FILE = os.path.join(HERE, "sylvatwin-shapes.ttl")

SH = Namespace("http://www.w3.org/ns/shacl#")

# Renseigne par setup(). Declare ici pour que les regles s'y referent.
NS = None


# --------------------------------------------------------------------------
# Le point de rencontre : les URI doivent etre EXACTEMENT celles ecrites par
# le fact-writer (v1 Python ou v2 operateur Go), sinon les contraintes ne
# ciblent rien.
# --------------------------------------------------------------------------
def detect_namespace(*candidates):
    """Lit le prefixe ':' depuis la TBox, plutot que de le coder en dur."""
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        g = Graph()
        try:
            g.parse(path, format="turtle")
        except Exception:
            continue
        for prefix, ns in g.namespaces():
            if prefix == "":
                return Namespace(str(ns))
    sys.exit(
        "Impossible de lire le prefixe ':'.\n"
        "Cherche dans : %s\nUtilise --tbox pour indiquer le bon fichier."
        % ", ".join(p for p in candidates if p)
    )


def setup(tbox=TBOX_FILE, graph=GRAPH_FILE):
    """Initialise le namespace. A appeler avant toute compilation."""
    global NS
    NS = detect_namespace(tbox, graph)
    return NS


def slug(name):
    return name.replace("-", "_").replace(".", "_")


def iri(kind, name):
    """Reproduit a l'identique l'assainissement du fact-writer."""
    return NS[f"{kind}_{slug(name)}"] if kind else NS[slug(name)]


# --------------------------------------------------------------------------
# Lecture du cote DESIRED. On ne garde que les champs que la TBox v0 sait
# exprimer. Chaque champ retenu devient une ou plusieurs contraintes.
# --------------------------------------------------------------------------
def read_intents(git_dir):
    intents = []
    for path in sorted(glob.glob(os.path.join(git_dir, "*.yaml"))):
        with open(path, "r", encoding="utf-8") as f:
            for doc in yaml.safe_load_all(f):
                if not doc or doc.get("kind") != "Deployment":
                    continue
                meta = doc.get("metadata", {})
                spec = doc.get("spec", {})
                pod_spec = spec.get("template", {}).get("spec", {})
                intents.append({
                    "source": os.path.basename(path),
                    "name": meta.get("name"),
                    "namespace": meta.get("namespace", "default"),
                    "replicas": spec.get("replicas"),
                    "nodeSelector": pod_spec.get("nodeSelector") or {},
                })
    return intents


# --------------------------------------------------------------------------
# Outils de construction de formes.
#
# Toutes les formes sont NOMMEES (pas de noeuds anonymes) : le fichier
# genere reste lisible, et le rapport de validation renvoie une URI stable
# que verdict.py peut retrouver pour lire :readsProperty.
# --------------------------------------------------------------------------
def _constraint(shapes, parent, cid, path, message, reads, field=None, drift=None):
    """
    Cree une contrainte de propriete nommee et declare :
      - ce qu'elle lit        (:readsProperty) -> permet de dater son verdict
      - d'ou elle vient       (:derivedFromField) -> permet de proposer un patch
      - ce qu'elle revele     (:detectsDrift) -> relie au vocabulaire Drift v0

    Ces trois annotations font de la contrainte une entite du jumeau, et non
    un detail d'implementation du validateur.
    """
    node = NS[cid]
    shapes.add((parent, SH.property, node))
    shapes.add((node, RDF.type, NS.Constraint))
    shapes.add((node, SH.path, path))
    shapes.add((node, SH.message, Literal(message, lang="fr")))
    for p in reads:
        shapes.add((node, NS.readsProperty, p))
    if field:
        shapes.add((node, NS.derivedFromField, Literal(field)))
    if drift:
        shapes.add((node, NS.detectsDrift, NS[drift]))
    return node


def _seq_path(shapes, props):
    """Chemin de sequence SHACL : ( :runsOn :offersLabel )."""
    head = BNode()
    Collection(shapes, head, list(props))
    return head


def _inverse_path(shapes, prop):
    """Chemin inverse SHACL : [ sh:inversePath :partOf ]."""
    b = BNode()
    shapes.add((b, SH.inversePath, prop))
    return b


# --------------------------------------------------------------------------
# LES REGLES DE COMPILATION — une fonction par type de champ YAML.
# C'est ici qu'on ajoute une regle quand la TBox s'enrichit.
# --------------------------------------------------------------------------

def compile_existence(shapes, node, intent):
    """
    REGLE R0 — champ source : metadata.name

    Ce qui est declare dans Git doit exister dans le cluster.

    Comble un angle mort du SPARQL ecrit a la main : une requete qui joint
    desiredReplicas et actualReplicas ne retourne RIEN si un cote manque.
    Un Deployment supprime a la main reste donc invisible. SHACL cible un
    noeud NOMME : il le valide meme sans aucun triplet.
    """
    name = intent["name"]
    cid = "C_%s_existence" % slug(name)

    shapes.add((node, SH["class"], NS.Deployment))
    shapes.add((node, SH.message, Literal(
        "Le Deployment %s est declare dans Git mais absent du cluster." % name,
        lang="fr")))

    c = _constraint(
        shapes, node, cid, NS.actualReplicas,
        "Le Deployment %s n'a aucun etat observe." % name,
        [NS.actualReplicas],
        field="metadata.name", drift="ConfigurationDrift",
    )
    shapes.add((c, SH.minCount, Literal(1)))

    return [("R0", "metadata.name", "presence du Deployment", ["actualReplicas"])]


def compile_replicas(shapes, node, intent):
    """
    REGLE R1 — champ source : spec.replicas

    Produit DEUX contraintes la ou l'expert n'en avait ecrit qu'une.

      R1a : actualReplicas == N          -> equivalent de Q0
      R1b : exactement N Pods :partOf    -> NOUVEAU, personne ne l'avait ecrit.
            Attrape un Pod Pending ou disparu, cas que Q0 rate parce que le
            controleur annonce encore N replicas.
    """
    name, n = intent["name"], intent["replicas"]
    if n is None:
        return []

    c1 = _constraint(
        shapes, node, "C_%s_replicas" % slug(name), NS.actualReplicas,
        "Derive de configuration : %s doit avoir %d replicas." % (name, n),
        [NS.actualReplicas],
        field="spec.replicas", drift="ConfigurationDrift",
    )
    shapes.add((c1, SH.minCount, Literal(1)))
    shapes.add((c1, SH.hasValue, Literal(n)))

    c2 = _constraint(
        shapes, node, "C_%s_cardinalite" % slug(name),
        _inverse_path(shapes, NS.partOf),
        "Derive de cardinalite : %s doit avoir exactement %d Pods observes."
        % (name, n),
        [NS.partOf],
        field="spec.replicas", drift="ConfigurationDrift",
    )
    shapes.add((c2, SH.minCount, Literal(n)))
    shapes.add((c2, SH.maxCount, Literal(n)))

    return [
        ("R1a", "spec.replicas", "actualReplicas == %d  (= Q0)" % n,
         ["actualReplicas"]),
        ("R1b", "spec.replicas", "exactement %d Pods :partOf  (NOUVEAU)" % n,
         ["partOf"]),
    ]


def compile_node_selector(shapes, node, intent):
    """
    REGLE R2 — champ source : spec.template.spec.nodeSelector

    L'equivalent genere de Q1. Forme produite :

        :Shape_webapp
            sh:targetNode :webapp ;
            sh:property :C_webapp_placement_disktype .

        :C_webapp_placement_disktype
            sh:path [ sh:inversePath :partOf ] ;      # tous ses Pods
            sh:node :P_webapp_placement_disktype ;
            :readsProperty :partOf .

        :P_webapp_placement_disktype
            sh:property [ sh:path ( :runsOn :offersLabel ) ;
                          sh:hasValue "disktype=ssd" ] ;
            :readsProperty :runsOn , :offersLabel .

    Le chemin de sequence traverse le Pod jusqu'au Node et lit ses
    etiquettes. C'est litteralement le FILTER NOT EXISTS de Q1, exprime a
    l'endroit plutot qu'a l'envers.
    """
    name = intent["name"]
    produced = []

    for k, v in sorted(intent["nodeSelector"].items()):
        label = "%s=%s" % (k, v)
        key = "%s_placement_%s" % (slug(name), slug(k))

        # La forme interne : ce que doit respecter CHAQUE Pod.
        pod_shape = NS["P_%s" % key]
        shapes.add((pod_shape, RDF.type, SH.NodeShape))
        inner = _constraint(
            shapes, pod_shape, "C_%s_pod" % key,
            _seq_path(shapes, [NS.runsOn, NS.offersLabel]),
            "Derive de placement : ce Pod de %s tourne sur un noeud qui "
            "n'offre pas '%s'." % (name, label),
            [NS.runsOn, NS.offersLabel],
            field="nodeSelector.%s" % k, drift="PlacementDrift",
        )
        shapes.add((inner, SH.hasValue, Literal(label)))

        # La forme externe : appliquer la precedente a tous les Pods du
        # Deployment, en remontant le chemin inverse de :partOf.
        outer = _constraint(
            shapes, NS["Shape_%s" % slug(name)], "C_%s" % key,
            _inverse_path(shapes, NS.partOf),
            "Derive de placement sur %s : contrainte '%s' non satisfaite."
            % (name, label),
            [NS.partOf, NS.runsOn, NS.offersLabel],
            field="nodeSelector.%s" % k, drift="PlacementDrift",
        )
        shapes.add((outer, SH.node, pod_shape))

        produced.append(
            ("R2", "nodeSelector.%s" % k,
             "tout Pod sur un Node offrant '%s'  (= Q1)" % label,
             ["partOf", "runsOn", "offersLabel"])
        )
    return produced


RULES = [compile_existence, compile_replicas, compile_node_selector]


# --------------------------------------------------------------------------
def compile_all(intents):
    shapes = Graph()
    shapes.bind("sh", SH)
    shapes.bind("", NS)
    shapes.bind("xsd", XSD)

    catalogue = []
    for intent in intents:
        if not intent["name"]:
            continue
        node = NS["Shape_%s" % slug(intent["name"])]
        shapes.add((node, RDF.type, SH.NodeShape))
        shapes.add((node, SH.targetNode, iri("", intent["name"])))

        for rule in RULES:
            for entry in rule(shapes, node, intent):
                catalogue.append(entry)

    return shapes, catalogue


def print_catalogue(catalogue, git_dir, n_intents, out):
    print("=== COMPILATION DE L'INTENTION ===")
    print("Source  : %s  (%d Deployment)" % (git_dir, n_intents))
    print("Sortie  : %s" % out)
    print()
    print("  %-6s %-26s %-44s %s" % ("REGLE", "CHAMP YAML", "CONTRAINTE", "LIT"))
    print("  " + "-" * 110)
    for rid, field, desc, reads in catalogue:
        print("  %-6s %-26s %-44s %s" % (rid, field, desc, ",".join(reads)))
    print()
    fields = len({c[1] for c in catalogue})
    print("%d champs lus  ->  %d contraintes generees." % (fields, len(catalogue)))
    print("Aucune de ces contraintes n'a ete ecrite a la main.")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Compile les manifestes Git en contraintes SHACL.")
    ap.add_argument("--git-dir", default=GIT_DIR)
    ap.add_argument("--graph", default=GRAPH_FILE)
    ap.add_argument("--tbox", default=TBOX_FILE)
    ap.add_argument("--out", default=SHAPES_FILE)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    setup(args.tbox, args.graph)

    intents = read_intents(args.git_dir)
    if not intents:
        sys.exit("Aucun Deployment trouve dans %s" % args.git_dir)

    shapes, catalogue = compile_all(intents)
    shapes.serialize(destination=args.out, format="turtle")
    print_catalogue(catalogue, args.git_dir, len(intents), args.out)

    if args.show:
        print()
        print(shapes.serialize(format="turtle"))

    if args.validate:
        from pyshacl import validate
        data = Graph()
        data.parse(args.graph, format="turtle")
        conforms, _, text = validate(data_graph=data, shacl_graph=shapes,
                                     advanced=True)
        print()
        print("=== VALIDATION (sans datage) ===")
        print("conforme" if conforms else text[:2000])
        print()
        print("Pour un verdict DATE, utiliser :  python3 verdict.py check")
    return 0


if __name__ == "__main__":
    sys.exit(main())