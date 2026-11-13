# Règles SylvaTwin (le « juge »)

Ces règles s'appliquent à `sylvatwin-core-v1.ttl` (v1.1.0). L'opérateur (le « greffier ») écrit seulement des faits observés. **Toute la détection est ici.**

Deux familles de fichiers :

- `cq/` : requêtes `SELECT` qui répondent aux questions de compétence. Elles sont lisibles et n'écrivent rien.
- `derives/` : requêtes `CONSTRUCT` qui produisent les individus `Drift`. Elles s'exécutent dans cet ordre :
  1. `01` à `08` sur le graphe observé ;
  2. `10` sur le graphe enrichi par les dérives de l'étape 1 ;
  3. `11` sur le graphe enrichi par l'étape 2.

| Fichier | Scénario | Classe produite |
|---|---|---|
| CQ1 / 01, 02 | S0 replicas | SpecDrift (cas A), ConvergenceDrift (cas B) |
| CQ2 / 03 | S1 placement | PlacementDrift |
| CQ3 | chaîne Pod → ReplicaSet → Deployment → Node | — |
| CQ4 / 04 | S2 Secret absent | BrokenReferenceDrift |
| CQ5 / 10, 11 | S3 NF touchée (inter-couches) | FunctionImpactDrift (`:causedBy`, `:impactPath`) |
| CQ6, CQ7 / 05, 06 | S4 PLMN et tranches entre NF | InterNFConsistencyDrift |
| CQ8 / 07 | S5 Flux bloqué ou suspendu | GitOpsSyncDrift |
| CQ9 / 08 | S6 Machine ↔ Node | MachineNodeMismatchDrift |
| CQ10 | chaîne Git → Flux → Pod → Node → Machine pour une NF | — |

## Points d'attention

- **IRI des dérives.** Elles sont stables : `https://w3id.org/sylvatwin/drift/<Classe>/<IRI de la ressource encodée>`. La même dérive garde donc la même IRI d'un cycle à l'autre.
- **`detectedAt`.** Il vaut `NOW()` à l'exécution. Le verdict daté (`legacy/sylvatwin-verdict-tbox.ttl`) n'est pas encore branché sur ces règles.
- **Pas de temporisation.** Un ConvergenceDrift transitoire (déploiement en cours) est signalé.
- **Pas de raisonneur requis.** Les règles n'utilisent que les types écrits par le greffier.

## Forme des IRI de dérive

Une IRI de dérive se construit ainsi :

```
https://w3id.org/sylvatwin/drift/<Classe>/<chemin de la ressource sans le préfixe .../res/>
```

Exemples :

- `drift/BrokenReferenceDrift/my-workload-kubeadm-capd/sylvatwin-5gc/Secret/udm-keys`
- `drift/FunctionImpactDrift/BrokenReferenceDrift/…/Secret/udm-keys/my-workload-kubeadm-capd/sylvatwin-5gc/NetworkFunction/udm`

## v1.2.0 : portée, cycle de vie et verdict

- **Garde P3 (portée d'observation).** Les règles `04` (S2) et `08` (S6) ne concluent à l'absence d'un objet que si deux conditions sont réunies :
  - le cluster est `:observationStatus "ok"` ;
  - le type (et le namespace) fait partie d'une `:ObservationScope` observée.
- **`lifecycle/`** : quatre requêtes SPARQL Update, exécutées après `derives/`. Elles tiennent l'historique dans le graphe nommé `…/graph/history` : `firstDetectedAt`, `lastDetectedAt`, `resolvedAt` et `convergenceHorizon`.
- **`verdict/01-verdict.rq`** : classe chaque dérive en `SuspectedViolation`, `ConfirmedViolation` ou `UnknownVerdict` (vocabulaire défini dans `sylvatwin-verdict-v1.ttl`).
- **Graphes nommés** : ils servent seulement à séparer les faits (`…/graph/facts`), les dérives du cycle (`…/graph/drifts`) et l'historique (`…/graph/history`). L'Option C reste inchangée : désiré et observé sont portés par le même individu.

## Formes SPARQL à éviter (portabilité)

Constaté le 09/11/2026 avec rdflib 7.6, en comparant chaque `DELETE … WHERE` à la requête `SELECT` qui a le même `WHERE`. Deux constructions donnent des résultats différents :

- `OPTIONAL { … } FILTER(!BOUND(?x))` placé **à l'intérieur** d'un bloc `GRAPH` ;
- `FILTER NOT EXISTS` imbriqué dans un `MINUS`.

Les règles placent donc leurs `OPTIONAL` en dehors des blocs `GRAPH`. Le test de conformité rdflib/Oxigraph de l'opérateur rejoue toutes les règles pour le vérifier.

## Vérification

`python3 tests/verif_v1.py`
