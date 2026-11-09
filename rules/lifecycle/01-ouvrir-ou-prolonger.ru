# CYCLE DE VIE 1/3 — Ouvrir une derive nouvelle, ou prolonger une derive connue.
# Entree : graphe <…/graph/drifts> (derives du cycle courant, IRI stables).
# Sortie : graphe <…/graph/history>. ?now est fourni par l'executeur (meme valeur
# pour tout le cycle) via la ligne "BIND(... AS ?now)" ci-dessous, reecrite.
PREFIX :    <https://w3id.org/sylvatwin/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
DELETE { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :lastDetectedAt ?old ; :resolvedAt ?res . } }
INSERT { GRAPH <https://w3id.org/sylvatwin/graph/history> {
           ?d a ?type ; :lastDetectedAt ?now ; :firstDetectedAt ?first . } }
WHERE {
  BIND ("__NOW__"^^xsd:dateTime AS ?now)
  GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d a ?type . }
  FILTER (STRSTARTS(STR(?type), "https://w3id.org/sylvatwin/core#"))
  OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :firstDetectedAt ?f0 } }
  OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :lastDetectedAt ?old } }
  OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :resolvedAt ?res } }
  # une derive resolue puis revenue repart de zero (nouvelle occurrence)
  BIND (IF(BOUND(?f0) && !BOUND(?res), ?f0, ?now) AS ?first)
}
