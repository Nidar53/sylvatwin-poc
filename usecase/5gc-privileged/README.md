# AMF et UPF : fichiers préparés, NON DÉPLOYÉS

**Ce dossier n'est référencé par AUCUNE Kustomization Flux.** Il ne tourne pas.
Il ne doit être appliqué qu'après une validation écrite de l'administrateur du serveur partagé.

Ces deux fonctions touchent le noyau partagé du serveur :
- les nœuds CAPD sont des conteneurs Docker ;
- tous les pods partagent donc le noyau de l'hôte « pas-la-friteuse ».

## AMF : besoin de SCTP

- Il ouvre un serveur **SCTP** (protocole NGAP, port 38412) vers les antennes (gNB). C'est obligatoire dans le code v2.7.2 :
  - `src/amf/init.c` appelle `ngap_open()` ;
  - `src/amf/context.c` arrête l'AMF avec « No amf.ngap.address » s'il n'y a pas d'adresse NGAP ;
  - `src/amf/ngap-sctp.c` et `lib/sctp/ogs-lksctp.c` appellent `socket(..., IPPROTO_SCTP)`.
- Il utilise le module noyau **`sctp`**. Ce module est déjà chargé sur l'hôte depuis l'incident du 22/10 : il ne serait pas chargé une nouvelle fois, mais le SCTP du noyau partagé serait **utilisé activement**.
- Il ne demande **aucune** capacité Linux, aucun périphérique et aucun privilège. Sa PodSecurity reste **restricted** : seul le module noyau pose question.
- Choix de prudence : NGAP lié à **127.0.0.1** (`ngap.server.address`). Le serveur SCTP n'est donc joignable que depuis l'intérieur du pod, tant qu'aucun gNB n'est déployé.

## UPF : besoin de tun et de NET_ADMIN

- Il ouvre **`/dev/net/tun`** et crée une interface `ogstun` par `ioctl(TUNSETIFF)`. Puis il lui donne une adresse (`ogs_tun_set_ip`, dans `lib/tun/linux-setup.c` et `src/upf/gtp-path.c`).
- Il faut :
  - la capacité **`NET_ADMIN`** ;
  - l'accès au **périphérique `/dev/net/tun`** du nœud (volume `hostPath` de type `CharDevice`) ;
  - une PodSecurity **`privileged`** pour ce namespace, car `restricted` et `baseline` refusent `NET_ADMIN` et `hostPath` ;
  - l'exécution en **root** dans le conteneur pour créer l'interface.
- L'`entrypoint.sh` de l'image ferait en plus `sysctl -w net.ipv6.conf.all.disable_ipv6=0`, `echo 1 > /proc/sys/net/ipv4/ip_forward` et `iptables -t nat -A POSTROUTING ... MASQUERADE`. **Ce manifeste contourne volontairement l'entrypoint** (`command:` direct). Il ne fait **ni NAT, ni forwarding, ni sysctl** : aucune sortie vers Internet.
- Le module `tun` est **compilé dans le noyau** de l'hôte : rien à charger. `/dev/net/tun` existe déjà dans le nœud CAPD (`crw-rw-rw- 10,200`).
- Effet limité au **namespace réseau du pod** : l'interface `ogstun` naît et meurt avec le pod. **[SUPPOSÉ]** Rien n'est créé dans le namespace réseau du nœud ni de l'hôte. C'est le comportement standard de TUNSETIFF dans un namespace réseau, mais je ne l'ai pas testé ici.
- GTP-U et PFCP liés à **127.0.0.1**, comme pour le SMF : l'UPF n'est joignable par personne en dehors de son pod.
  - Conséquence : **SMF et UPF ne pourraient pas s'associer** (pods différents).
  - Pour une association réelle, il faudrait les lier à l'IP du pod (`dev: eth0`) et ouvrir UDP 8805 et 2152 dans la NetworkPolicy. Ce serait un **deuxième palier de validation**.

## Déploiement, après validation seulement

```bash
kubectl --kubeconfig $WL_KC apply -f namespace.yaml   # namespace sylvatwin-5gc-priv (PodSecurity privileged pour l'UPF)
kubectl --kubeconfig $WL_KC apply -k .
```
