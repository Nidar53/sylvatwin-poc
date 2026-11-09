# Verdict daté

`01-verdict.rq` qualifie chaque dérive ouverte de l'historique. Le vocabulaire est défini dans `sylvatwin-verdict-v1.ttl`.

| Verdict | Quand |
|---|---|
| `UnknownVerdict` | Un cluster n'est pas `ok`, ou sa dernière synchronisation réussie est plus vieille que l'horizon de validité (paramètre `__VALIDITY__`, en secondes). |
| `SuspectedViolation` | L'âge de la dérive est inférieur à son horizon de convergence : Flux devrait la corriger. |
| `ConfirmedViolation` | L'âge est supérieur ou égal à l'horizon, ou il n'y a pas d'horizon : ressource hors Git, Kustomization suspendue, mauvais placement, incohérence entre NF, référence cassée. |

**Limite connue.** Une `ConvergenceDrift` reçoit l'horizon de Flux (`interval` + `timeout`) alors que Flux ne la corrige pas. L'horizon juste serait plutôt `progressDeadlineSeconds` du Deployment, qui n'est pas encore modélisé.

## Calcul de durée

`__SECONDS__(a, b)` est remplacé par l'exécuteur par l'expression de `seconds.sparql` (où `$A` et `$B` deviennent les deux variables), une expression **SPARQL 1.1 standard**, qui donne le nombre de secondes entre deux `xsd:dateTime`. Le calcul passe par `YEAR`, `MONTH`, `DAY`, `HOURS`, `MINUTES` et `SECONDS`, via le jour julien. Ainsi, rdflib et Oxigraph donnent le même résultat sans arithmétique de durées, que SPARQL 1.1 ne prend pas en charge partout.
