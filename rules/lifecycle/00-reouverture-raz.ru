# CYCLE DE VIE 0/5 — REOUVERTURE : une derive RESOLUE (:resolvedAt) qui reapparait ce cycle est une
# nouvelle occurrence : on supprime TOUS ses anciens :firstDetectedAt avant que 01 n'ecrive le nouveau
# (sinon une derive qui revient cumule une date par occurrence, et le verdict en emet un par date,
# avec le meme identifiant : correction du 14/11/2026, diagnostic docs/DIAGNOSTIC-SUSPENSION-2026-11-14.md).
# S'execute AVANT 01 (qui supprime ensuite :resolvedAt). OPTIONAL hors du GRAPH (piege rdflib, voir 05).
PREFIX :    <https://w3id.org/sylvatwin/core#>
DELETE { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :firstDetectedAt ?f0 . } }
WHERE {
  GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d a ?type . }
  FILTER (STRSTARTS(STR(?type), "https://w3id.org/sylvatwin/core#"))
  GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :resolvedAt ?r . ?d :firstDetectedAt ?f0 . }
}
