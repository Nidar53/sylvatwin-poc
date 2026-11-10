# CYCLE DE VIE 3b/4 — Horizon de convergence PROPRE aux ConvergenceDrift (et aux
# FunctionImpactDrift qu'elles causent) : progressDeadlineSeconds du Deployment
# concerne (600 s si absent, valeur par defaut Kubernetes), PAS l'horizon Flux.
#
# PIEGE rdflib 7.6 : meme remarque que 03-horizon.ru (HAVING obligatoire).
#
# Justification (correction du 10/11/2026) : une ConvergenceDrift signifie que
# la SPEC est conforme a Git (Flux n'a rien a re-appliquer) mais que Kubernetes
# n'arrive pas a faire converger le Deployment lui-meme. C'est Kubernetes, pas
# Flux, qui decide quand déclarer la progression en echec.
PREFIX :    <https://w3id.org/sylvatwin/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
DELETE { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?old . } }
INSERT { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?h . } }
WHERE {
  {
    SELECT ?d (MAX(?hk) AS ?h) WHERE {
      { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d a :ConvergenceDrift ; :affects ?res . } }
      UNION
      { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d :causedBy ?o . ?o a :ConvergenceDrift ; :affects ?res . } }
      GRAPH <https://w3id.org/sylvatwin/graph/facts> { ?res a :Deployment . }
      GRAPH <https://w3id.org/sylvatwin/graph/facts> {
        OPTIONAL { ?res :progressDeadlineSeconds ?pd }
      }
      BIND (COALESCE(?pd, 600.0) AS ?hk)
    } GROUP BY ?d HAVING (COUNT(?res) > 0)
  }
  OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?old } }
}
