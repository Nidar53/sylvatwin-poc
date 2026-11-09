# CYCLE DE VIE 3/4 — Horizon de convergence (secondes) des derives du cycle.
# Horizon = interval + timeout de la Kustomization (non suspendue) qui gere une
# ressource touchee par la derive (ou de la Kustomization touchee elle-meme).
# Plusieurs ressources gerees : on prend le MAXIMUM.
# Pourquoi interval + timeout : Flux re-applique au plus tard a chaque interval
# (doc Flux : "runs a server-side apply dry-run to detect and correct drift"), et
# une application dure au plus timeout.
# Les exclusions (horizon infini) sont dans 04-horizon-infini.ru : deux requetes
# simples plutot qu'une requete a MINUS imbriques (portabilite rdflib/Oxigraph).
PREFIX :    <https://w3id.org/sylvatwin/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
DELETE { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?old . } }
INSERT { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?h . } }
WHERE {
  {
    SELECT ?d (MAX(?hk) AS ?h) WHERE {
      # derive Kubernetes/Flux : ses ressources ; FunctionImpactDrift : celles de
      # sa derive d'origine (:causedBy). Une NF touchee n'attend pas plus (ni
      # moins) que la correction de la cause.
      { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d :affects ?res . } }
      UNION
      { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d :causedBy ?o . ?o :affects ?res . } }
      GRAPH <https://w3id.org/sylvatwin/graph/facts> {
        { ?res :managedBy ?k } UNION { ?res a :Kustomization . BIND (?res AS ?k) }
        ?k a :Kustomization ; :reconcileInterval ?i .
        OPTIONAL { ?k :reconcileTimeout ?t }
        OPTIONAL { ?k :suspended ?susp }
        FILTER (!BOUND(?susp) || ?susp = false)
      }
      BIND (?i + COALESCE(?t, 0) AS ?hk)
    } GROUP BY ?d
  }
  OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?old } }
}
