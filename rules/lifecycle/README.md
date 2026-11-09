# Cycle de vie des dérives (SPARQL Update, exécuté par le juge)

Le graphe des faits est **reconstruit** à chaque cycle. L'historique des dérives est gardé dans un **graphe nommé** séparé : `https://w3id.org/sylvatwin/graph/history`. On n'utilise pas de graphes nommés pour le désiré et l'observé : l'Option C reste inchangée.

Graphes utilisés par le juge :

- `…/graph/facts` : les faits du cycle (écrits par le greffier), avec l'ontologie ;
- `…/graph/drifts` : les dérives du cycle courant (CONSTRUCT des `rules/derives`) ;
- `…/graph/history` : un individu par IRI stable de dérive, avec `firstDetectedAt`, `lastDetectedAt`, `resolvedAt` et `convergenceHorizon`.

Ordre d'exécution, après `rules/derives` :

1. `01-ouvrir-ou-prolonger.ru` : les dérives du cycle sont copiées dans `history`. On garde `firstDetectedAt` si l'IRI existe déjà, et on met à jour `lastDetectedAt`.
2. `02-resoudre.ru` : une dérive présente dans `history` mais absente du cycle reçoit `resolvedAt`, à condition que le cluster soit observé avec succès (garde P3). Si l'information n'est pas fraîche, la dérive n'est pas déclarée résolue.
3. `03-horizon.ru` : calcule `convergenceHorizon` = `interval` + `timeout` de la Kustomization (non suspendue) qui gère une ressource touchée.
4. `04-horizon-infini.ru` : retire cet horizon quand personne ne corrigera la dérive (hors Git, suspension, incohérence entre NF, référence cassée). Deux requêtes simples plutôt qu'une requête à `MINUS` imbriqués, pour que rdflib et Oxigraph donnent le même résultat.

Paramètre : `?now` est remplacé par l'exécuteur par un littéral `xsd:dateTime`, le **même** pour toutes les requêtes d'un cycle.
