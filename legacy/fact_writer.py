#!/usr/bin/env python3
"""
SylvaTwin PoC — FACT-WRITER (embryon de la contribution C2)
============================================================
Role : maintenir le graphe semantique synchronise avec les deux sources :
  - COTE DESIRED : les manifestes YAML du dossier ./git-desired (joue le role de Git)
  - COTE ACTUAL  : le cluster Kubernetes, observe en TEMPS REEL via la Watch API

PRINCIPE ARCHITECTURAL STRICT (invariant de la these) :
  Ce programme n'ecrit QUE des faits bruts (triplets). Il ne compare rien,
  ne detecte rien, ne juge rien. Toute la logique de detection vit dans
  les requetes SPARQL (voir detect.py).

Sortie : ./sylvatwin-graph.ttl  (TBox + ABox vivante, ouvrable dans Protege)

Usage :
  python3 fact_writer.py            # se connecte au cluster courant (kubeconfig)
  Ctrl+C pour arreter.
"""
import os
import sys
import glob
import threading
import time
from datetime import datetime, timezone

import yaml
from rdflib import Graph, Namespace, Literal, RDF, URIRef
from rdflib.namespace import XSD
from kubernetes import client, config, watch

# ----------------------------------------------------------------- config
NS = Namespace("https://w3id.org/sylvatwin/k8s#")
HERE = os.path.dirname(os.path.abspath(__file__))
GIT_DIR = os.path.join(HERE, "git-desired")          # le "depot Git" local
TBOX_FILE = os.path.join(HERE, "sylvatwin-slice-v0.ttl")
GRAPH_FILE = os.path.join(HERE, "sylvatwin-graph.ttl")  # le jumeau (sortie)

graph = Graph()
graph.bind("", NS)
lock = threading.Lock()      # plusieurs watchers ecrivent -> un seul a la fois


# ----------------------------------------------------------------- helpers
def iri(kind: str, name: str) -> URIRef:
    """Nom d'individu : 'pod', 'webapp-7d9f-x4k2' -> :pod_webapp_7d9f_x4k2
    (tirets remplaces par des underscores : convention sans-tiret du projet)."""
    safe = name.replace("-", "_").replace(".", "_")
    return NS[f"{kind}_{safe}"] if kind else NS[safe]


def now_literal() -> Literal:
    return Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)


def set_single(subject: URIRef, prop: URIRef, value) -> None:
    """Propriete mono-valuee : remplace l'ancienne valeur (idempotent)."""
    graph.remove((subject, prop, None))
    graph.add((subject, prop, value))


def set_multi(subject: URIRef, prop: URIRef, values) -> None:
    """Propriete multi-valuee (ex: offersLabel) : remplace l'ensemble."""
    graph.remove((subject, prop, None))
    for v in values:
        graph.add((subject, prop, v))


def remove_individual(subject: URIRef) -> None:
    """Un objet supprime du cluster disparait du graphe (choix v0 documente)."""
    graph.remove((subject, None, None))
    graph.remove((None, None, subject))


def save() -> None:
    graph.serialize(destination=GRAPH_FILE, format="turtle")


def log(source: str, msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{source:7}] {msg}", flush=True)


# ----------------------------------------------------- COTE DESIRED (Git)
def sync_desired() -> None:
    """Lit tous les manifestes du 'depot Git' et ecrit les faits desired_*.
    Rappel : on n'ecrit ICI que desiredReplicas et requiresNodeLabel."""
    with lock:
        for path in glob.glob(os.path.join(GIT_DIR, "*.yaml")):
            for doc in yaml.safe_load_all(open(path)):
                if not doc or doc.get("kind") != "Deployment":
                    continue
                name = doc["metadata"]["name"]
                subj = iri("", name)
                graph.add((subj, RDF.type, NS.Deployment))
                spec = doc.get("spec", {})
                set_single(subj, NS.desiredReplicas,
                           Literal(int(spec.get("replicas", 1)), datatype=XSD.integer))
                selector = (spec.get("template", {}).get("spec", {})
                            .get("nodeSelector", {}) or {})
                set_multi(subj, NS.requiresNodeLabel,
                          [Literal(f"{k}={v}") for k, v in selector.items()])
                log("GIT", f"desired : {name} replicas={spec.get('replicas')} "
                           f"nodeSelector={selector}")
        save()


# ------------------------------------------------- COTE ACTUAL (Watch API)
def on_deployment(event) -> None:
    dep = event["object"]
    subj = iri("", dep.metadata.name)
    with lock:
        if event["type"] == "DELETED":
            # on ne supprime que les faits actual_* (le desired vit dans Git)
            graph.remove((subj, NS.actualReplicas, None))
        else:
            graph.add((subj, RDF.type, NS.Deployment))
            replicas = dep.status.replicas or 0
            set_single(subj, NS.actualReplicas,
                       Literal(int(replicas), datatype=XSD.integer))
            set_single(subj, NS.observedAt, now_literal())
        save()
    log("WATCH", f"{event['type']:8} Deployment/{dep.metadata.name} "
                 f"actualReplicas={dep.status.replicas}")


def on_pod(event) -> None:
    pod = event["object"]
    subj = iri("pod", pod.metadata.name)
    with lock:
        if event["type"] == "DELETED":
            remove_individual(subj)
        else:
            graph.add((subj, RDF.type, NS.Pod))
            app = (pod.metadata.labels or {}).get("app")
            if app:                                   # partOf via le label app
                set_single(subj, NS.partOf, iri("", app))
            if pod.spec.node_name:                    # runsOn via spec.nodeName
                set_single(subj, NS.runsOn, iri("node", pod.spec.node_name))
            set_single(subj, NS.observedAt, now_literal())
        save()
    log("WATCH", f"{event['type']:8} Pod/{pod.metadata.name} "
                 f"node={pod.spec.node_name}")


def on_node(event) -> None:
    node = event["object"]
    subj = iri("node", node.metadata.name)
    with lock:
        if event["type"] == "DELETED":
            remove_individual(subj)
        else:
            graph.add((subj, RDF.type, NS.Node))
            labels = node.metadata.labels or {}
            set_multi(subj, NS.offersLabel,
                      [Literal(f"{k}={v}") for k, v in labels.items()])
            set_single(subj, NS.observedAt, now_literal())
        save()
    log("WATCH", f"{event['type']:8} Node/{node.metadata.name} "
                 f"labels={len(node.metadata.labels or {})}")


def watcher(list_func, handler, name, **kwargs) -> None:
    """Boucle de watch robuste : se reconnecte si le flux est coupe."""
    while True:
        try:
            w = watch.Watch()
            for event in w.stream(list_func, timeout_seconds=0, **kwargs):
                handler(event)
        except Exception as exc:                      # noqa: BLE001 (PoC)
            log(name, f"watch interrompu ({exc.__class__.__name__}), "
                      f"reconnexion dans 2 s")
            time.sleep(2)


# ----------------------------------------------------------------- main
def main() -> None:
    # 1) charger la TBox pour que le fichier de sortie soit complet
    if os.path.exists(TBOX_FILE):
        graph.parse(TBOX_FILE, format="turtle")
        log("INIT", f"TBox chargee ({len(graph)} triplets)")
    else:
        log("INIT", "ATTENTION : sylvatwin-slice-v0.ttl introuvable, "
                    "le graphe ne contiendra que la ABox")

    # 2) cote desired (Git)
    sync_desired()

    # 3) cote actual : connexion au cluster + 3 watchers temps reel
    config.load_kube_config()                 # utilise ~/.kube/config
    v1, apps = client.CoreV1Api(), client.AppsV1Api()
    threads = [
        threading.Thread(target=watcher, daemon=True, name="deploy",
                         args=(apps.list_deployment_for_all_namespaces,
                               on_deployment, "DEPLOY")),
        threading.Thread(target=watcher, daemon=True, name="pods",
                         args=(v1.list_pod_for_all_namespaces, on_pod, "PODS")),
        threading.Thread(target=watcher, daemon=True, name="nodes",
                         args=(v1.list_node, on_node, "NODES")),
    ]
    for t in threads:
        t.start()
    log("INIT", f"Fact-writer demarre. Graphe : {GRAPH_FILE}")
    log("INIT", "Le graphe se met a jour a chaque evenement du cluster. Ctrl+C pour arreter.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        with lock:
            save()
        log("STOP", "Graphe sauvegarde. Au revoir.")


if __name__ == "__main__":
    main()
