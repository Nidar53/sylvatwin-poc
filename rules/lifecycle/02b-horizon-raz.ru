# CYCLE DE VIE 2b/5 — L'horizon est RECALCULE a chaque cycle : pour toute derive presente dans le graphe
# <drifts> de ce cycle, on supprime l'ancien :convergenceHorizon AVANT que 03 et 04 n'ecrivent le nouveau
# (03 : Flux, Kustomization non suspendue ; 04 : ConvergenceDrift). Une Kustomization suspendue (ou toute
# situation ou 03/04 n'ecrivent rien) donne donc "pas d'horizon" (confirmee tout de suite), que la derive soit
# nouvelle, rouverte ou deja ouverte ; 05 retire ensuite l'horizon des derives que rien ne corrigera.
# Les derives absentes du cycle (cluster injoignable, garde P3) gardent leur horizon : on ne sait rien de neuf.
# Correction du 14/11/2026 (docs/DIAGNOSTIC-SUSPENSION-2026-11-14.md).
PREFIX :    <https://w3id.org/sylvatwin/core#>
DELETE { GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?h . } }
WHERE {
  GRAPH <https://w3id.org/sylvatwin/graph/drifts> { ?d a ?type . }
  GRAPH <https://w3id.org/sylvatwin/graph/history> { ?d :convergenceHorizon ?h . }
}
