# CYCLE DE VIE 3/4 — Horizon de convergence (secondes) des derives du cycle,
# fondees sur FLUX (interval + timeout d'une Kustomization non suspendue qui
# gere une ressource touchee, ou de la Kustomization touchee elle-meme).
# Plusieurs ressources gerees : on prend le MAXIMUM.
# EXCLUT ConvergenceDrift : son horizon vient de Kubernetes lui-meme
# (progressDeadlineSeconds du Deployment), pas de Flux. Voir 03b-horizon-
# convergence.ru. Correction du 10/11/2026 (campagne du 09/11 : une
# ConvergenceDrift recevait a tort l'horizon Flux).
# Les exclusions (horizon infini) sont dans 05-horizon-infini.ru : deux requetes
# simples plutot qu'une requete a MINUS imbriques (portabilite rdflib/Oxigraph).
# PIEGE rdflib 7.6 (constate le 10/11/2026) : un sous-SELECT avec GROUP BY qui ne
# matche RIEN, suivi d'un OPTIONAL externe, produit a tort une ligne (comme si le
# sous-select etait absent). HAVING (COUNT(...) > 0) force le sous-select a bien
# etre VIDE (pas "une ligne avec variables non liees") dans ce cas. Teste par un
# cas minimal isole ; verifie aussi en Oxigraph (conformity_test.go).
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
    } GROUP BY ?d HAVING (COUNT(?res) > 0)
  }
  MINUS { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d a :ConvergenceDrift } }
  MINUS { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d :causedBy ?oc . ?oc a :ConvergenceDrift } }
  OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?old } }
}
