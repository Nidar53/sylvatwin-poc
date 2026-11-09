# CYCLE DE VIE 2/3 — Marquer resolues les derives connues absentes de ce cycle.
# Garde P3 : on ne declare resolue une derive que si TOUS les clusters lies a ses
# ressources ont ete observes avec succes a ce cycle ; sinon on ne sait pas.
# Version minimale : garde GLOBALE (aucun cluster en echec a ce cycle). Une garde
# par cluster demanderait de garder les :affects dans <history> (phase 2 complete).
PREFIX :    <https://w3id.org/sylvatwin/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
INSERT { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :resolvedAt ?now . } }
WHERE {
  BIND ("__NOW__"^^xsd:dateTime AS ?now)
  GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :firstDetectedAt ?f . }
  FILTER NOT EXISTS { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :resolvedAt ?r } }
  FILTER NOT EXISTS { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d a ?t } }
  # garde P3 globale : aucun cluster observe en echec a ce cycle
  FILTER NOT EXISTS {
    GRAPH <https://w3id.org/sylvatwin/graph/facts> {
      ?kc a :KubernetesCluster ; :observationStatus ?st . FILTER (?st != "ok") }
  }
}
