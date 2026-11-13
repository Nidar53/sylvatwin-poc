# legacy/ — prototype v0 (espace `k8s#`), conserve pour comparaison

Rien ici n'est utilise par le controleur ni par les regles v1. Les scripts Python
(`detect.py`, `fact_writer.py`, `fidelity.py`, `compile_intent.py`, `verdict.py`)
et leurs donnees (`sylvatwin-*.json`, `git-desired/`, `argocd-app.yaml`,
`kind-config.yaml`) forment la chaine v0 ; `sylvatwin-shapes.ttl`,
`sylvatwin-verdict-tbox.ttl`, `sylvatwin-verdicts.ttl` sont ses ontologies/SHACL.
`sylvatwin-slice-v0.ttl` n'est importe par aucun `owl:imports` ; seul
`tests/verif_v1.py` le relit pour comparer v0 et v1.
Deplace le 13/11/2026 (phase C). Les chemins relatifs entre ces fichiers sont conserves.
