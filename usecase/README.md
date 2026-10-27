# Cas d'usage SylvaTwin : cœur 5G Open5GS (option b1)

Cœur 5G **partiel**, déployé par le Flux de Sylva (depuis le cluster de management) sur le cluster workload, dans le namespace `sylvatwin-5gc`. Il sert de terrain pour injecter des dérives de configuration.

## Ce qui tourne
| Fonction | Rôle | Sockets ouvertes |
|---|---|---|
| NRF, NSSF, AUSF, UDM, UDR, PCF, BSF | Plan de contrôle 5G (SBI HTTP/2) | TCP 7777 |
| SMF | Gestion des sessions | TCP 7777 ; UDP 8805 (PFCP) et UDP 2152 (GTP-U) **sur 127.0.0.1 seulement** |
| MongoDB | Base d'UDR et de PCF | TCP 27017 |

**Non exécutés** :
- l'AMF existe seulement en ConfigMap `amf-config`, car il ouvre SCTP ;
- aucun UPF, gNB ni UE.

Conséquence : **il n'y a ni enregistrement d'abonné ni trafic**.

## Paramètres communs
PLMN 999/70, S-NSSAI SST 1, DNN `internet`, TAC 1.

## Déploiement
1. `bootstrap/workload-deployer-rbac.yaml` : à appliquer une fois sur le workload. Il crée le compte de déploiement, limité à `sylvatwin-5gc`.
2. Créer le Secret `sylvatwin-flux/sylvatwin-5gc-kubeconfig` sur le management. Il contient le token de ce compte. **Ne jamais le commiter.**
3. `bootstrap/flux-management.yaml` : à appliquer sur le management. Il crée le GitRepository et la Kustomization (intervalle 2 min, prune).
4. Créer le Secret `udm-keys` **hors Git**, pour le scénario D3. On peut y mettre les clés SUCI d'exemple fournies dans l'image.

## Points techniques vérifiés
- L'image `gradiant/open5gs` définit `DB_URI=mongodb://mongo/open5gs`, et cette variable l'emporte sur `db_uri` du fichier. Elle est donc redéfinie dans `udr.yaml` et `pcf.yaml`.
- Le SMF v2.7.2 refuse de démarrer sans adresse GTP-U (`smf_context_validation`). Elle est liée à 127.0.0.1.
