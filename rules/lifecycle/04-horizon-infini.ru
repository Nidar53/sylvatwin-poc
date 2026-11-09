# CYCLE DE VIE 4/4 — Horizon INFINI : on retire l'horizon des derives que rien ne
# corrigera. Cas (un seul suffit) :
#   (a) une ressource touchee, vue dans le cluster, n'est geree par aucune
#       Kustomization (hors Git ; les Pods et Nodes ne sont jamais geres
#       directement : ils ne comptent pas) ;
#   (b) derive de type PlacementDrift (Kubernetes n'evince pas, Flux ne regarde pas
#       les noeuds), InterNFConsistency (conforme a Git), BrokenReference (la cible
#       manque : rien a re-appliquer cote Flux pour un Secret hors Git),
#       MachineNodeMismatch (hors perimetre Flux) ;
#   NB : GitOpsSyncDrift n'est PAS dans la liste : sur une Kustomization active,
#   Flux livrera (horizon = interval + timeout, calcule par 03) ; sur une
#   Kustomization SUSPENDUE, 03 n'ecrit pas d'horizon -> infini. (Correction du
#   10/11/2026, avant les scenarios : un push Git normal etait "confirme".)
#   (c) FunctionImpactDrift : memes cas, appliques a sa derive d'origine.
PREFIX :    <https://w3id.org/sylvatwin/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
DELETE { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?h . } }
WHERE {
  GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?h . }
  {
    { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d :affects ?r . } }
    UNION
    { GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d :causedBy ?o . ?o :affects ?r . } }
    GRAPH <https://w3id.org/sylvatwin/graph/facts> { ?r :uid ?u . }
    # OPTIONAL places HORS du bloc GRAPH : rdflib 7.6 evalue mal OPTIONAL + !BOUND
    # a l'interieur d'un GRAPH dans un DELETE (constate le 09/11/2026 : le SELECT
    # equivalent etait vide, le DELETE effacait quand meme). Forme portable.
    OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/facts> { ?r :managedBy ?m } }
    OPTIONAL { GRAPH <https://w3id.org/sylvatwin/graph/facts> { ?r a ?cl . FILTER (?cl IN (:Kustomization, :Pod, :Node)) } }
    FILTER (!BOUND(?m) && !BOUND(?cl))
  } UNION {
    GRAPH <https://w3id.org/sylvatwin/graph/drifts> {
      ?d a ?ty . FILTER (?ty IN (:PlacementDrift, :InterNFConsistencyDrift,
                                 :BrokenReferenceDrift, :MachineNodeMismatchDrift)) }
  } UNION {
    # FunctionImpactDrift dont la cause est d'un de ces types : horizon infini aussi
    GRAPH <https://w3id.org/sylvatwin/graph/drifts> {
      ?d :causedBy ?o2 . ?o2 a ?ty2 . FILTER (?ty2 IN (:PlacementDrift, :InterNFConsistencyDrift,
                                 :BrokenReferenceDrift, :MachineNodeMismatchDrift)) }
  }
}
