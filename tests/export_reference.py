#!/usr/bin/env python3
"""Exporte, pour le test de conformite de l'operateur (barriere 2), les 10
variantes de derive et les derives calculees par rdflib (moteur de reference).

Usage : python3 tests/export_reference.py <dossier_sortie>
Produit, pour chaque variante V :
  V.facts.nt     : faits (exemple reel modifie), N-Triples
  V.drifts.tsv   : derives rdflib, une ligne "type<TAB>iri_stable" (triees),
                   detectedAt exclu (horodatage), FunctionImpactDrift avec
                   affectsFunction et impactPath
"""
import os, sys
sys.argv = [sys.argv[0]] + sys.argv[1:]
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sylvatwin-reference"
os.makedirs(out, exist_ok=True)
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "verif_v1.py")).read()
# on charge seulement les definitions (variantes + juge), pas les verifications
exec(src.split("# ================================================================== 1")[0])
from rdflib import RDF
VARIANTES = ["base", "S0A-nrf", "S0B-udm", "S1-ok", "S1-retire", "S2", "S4-plmn", "S4-slice",
             "S5-suspend", "S5-retard", "S6-machine-sans-node", "S6-node-sans-machine"]
def lines(d):
    rows = set()
    for s, t in d.subject_objects(RDF.type):
        extra = ""
        if str(t).endswith("FunctionImpactDrift"):
            extra = "\t" + str(d.value(s, C.affectsFunction)) + "\t" + str(d.value(s, C.impactPath))
        rows.add(str(t).split("#")[1] + "\t" + str(s) + extra)
    for s, o in d.subject_objects(C.affects):
        rows.add("affects\t" + str(s) + "\t" + str(o))
    return sorted(rows)
for v in VARIANTES:
    g = base() if v == "base" else variant(v)
    g.serialize(os.path.join(out, v + ".facts.nt"), format="nt")
    open(os.path.join(out, v + ".drifts.tsv"), "w").write("\n".join(lines(judge(g))) + "\n")
    print(v, len(g), "faits ->", len(lines(judge(g))), "lignes de derives")

# --- Reference du cycle de vie + verdict (scenario S0-A sur nrf, 3 cycles) ---
# Ecrit verdict-sequence.tsv : "t<TAB>classe_derive<TAB>classe_verdict" (triees)
# et facts-t60.nt, facts-t500.nt, facts-t600.nt. Meme parametres que la section 7
# de verif_v1.py (horizon de validite 600 s).
exec(src[src.index("from rdflib import Dataset"):src.index("# S0-A sur nrf")])
from rdflib import Dataset
seq = []
ds = Dataset()
for t, v in [(60, "S0A-nrf"), (500, "S0A-nrf"), (600, None)]:
    f = facts_at(v, t)
    f.serialize(os.path.join(out, f"facts-t{t}.nt"), format="nt")
    for d, c in sorted(cycle(ds, f, now_at(t))):
        seq.append(f"{t}\t{d}\t{c}")
    nres = len(list(ds.graph(HIST).subject_objects(C.resolvedAt)))
    seq.append(f"{t}\tresolues\t{nres}")
open(os.path.join(out, "verdict-sequence.tsv"), "w").write("\n".join(seq) + "\n")
print("verdict-sequence :", seq)
