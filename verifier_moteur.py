# -*- coding: utf-8 -*-
"""
Verifie le moteur de la plateforme :  python verifier_moteur.py
  1. sur l'historique officiel, il redonne les resultats deposes par le pipeline (47 provinces, noyau L11) :
     synthese 2025-26 et historique de l'indice 2017-2024
  2. le parcours administrateur (modele Excel -> saisie -> chargement -> prevision) redonne les memes resultats,
     effectifs des provinces scindees saisis ; et fonctionne quand ils sont laisses vides (parts reprises)
  3. les controles de saisie rejettent les fichiers errones
"""
from glob import glob
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

import moteur as M

ICI = Path(__file__).resolve().parent
DEPOTS = ICI.parent / "depots" / "04_analyse"
base = pd.read_csv(ICI / "donnees" / "panel_base.csv")
eff47 = pd.read_csv(ICI / "donnees" / "effectifs_47.csv")
synthese = pd.read_csv(glob(str(DEPOTS / "*synthese-province-v2*"))[0], sep=";", decimal=",").set_index("pcode_prov_new")
historique = pd.read_csv(glob(str(DEPOTS / "*historique-indice-risque*"))[0], sep=";", decimal=",")
echecs = []
TOL = 1e-9


def verdict(ok, texte):
    print(f"  {'OK ' if ok else 'ECHEC'} {texte}")
    if not ok:
        echecs.append(texte)


def comparer(resultat, infos, titre):
    print(f"\n--- {titre}")
    r = resultat.set_index("pcode_prov_new").loc[synthese.index]
    for ours, ref in [("IRD", "IRD"), ("prevision", "prev"), ("prevision_bas80", "prev_lo"),
                      ("prevision_haut80", "prev_hi"), ("proba_alerte", "p_alerte")]:
        ecart = float(np.nanmax(np.abs(r[ours] - synthese[ref])))
        verdict(ecart <= TOL, f"{ours:24s} ecart max {ecart:.2e}")
    verdict((r.priorite == synthese.priorite).all(), "priorite identique")
    h = infos["historique_ird"].merge(historique, on=["pcode_prov_new", "annee"], suffixes=("", "_ref"))
    verdict(len(h) == len(historique) == 376, f"historique de l'indice : {len(h)} lignes sur {len(historique)}")
    for c in ["D1_abandon", "D2_exclusion", "D4_choc", "IRD"]:
        ecart = float(np.abs(h[c] - h[c + "_ref"]).max())
        verdict(ecart <= TOL, f"historique {c:13s} ecart max {ecart:.2e}")
    verdict((h.rang_IRD == h.rang_IRD_ref).all(), "historique rang_IRD identique")
    dedans = ((r.prevision >= r.prevision_bas80) & (r.prevision <= r.prevision_haut80)).all()
    verdict(dedans, "toutes les previsions dans leur intervalle affiche")


# 1. historique officiel
resultat, infos = M.prevoir(base, eff47)
print(f"Prevision {M.annee_label(infos['annee_prevue'])} a partir de {M.annee_label(infos['annee_donnees'])} ; "
      f"{infos['n_lignes_apprentissage']} lignes, poids {infos['poids_apprentissage']:.1f}")
comparer(resultat, infos, "1. historique officiel vs depots du pipeline")
hors = resultat[(resultat.prevision < resultat.prevision_bas80_brut) | (resultat.prevision > resultat.prevision_haut80_brut)]
print("  provinces dont la prevision sortait de l'intervalle brut (ramenees dedans, comme dans le pipeline) :",
      ", ".join(hors.province_new) or "aucune")

# 2. parcours administrateur : on retire 2024 et on le ressaisit dans le modele Excel
avant, avant47 = base[base.annee < 2024], eff47[eff47.annee < 2024]
classeur = pd.read_excel(BytesIO(M.creer_modele_excel(avant, avant47, 2024)), sheet_name=None)
saisie, scindees = classeur["saisie"], classeur["provinces_scindees"]
assert len(saisie) == 45 and (saisie.annee == 2024).all() and len(scindees) == 4
vrai = base[base.annee == 2024].set_index("pcode_prov_old")
for c in M.COLONNES_SAISIE:
    saisie[c] = saisie.pcode_prov_old.map(vrai[c])
scindees["effectif"] = scindees.pcode_prov_new.map(eff47[eff47.annee == 2024].set_index("pcode_prov_new").effectif)


def charger(saisie, scindees):
    t = BytesIO()
    with pd.ExcelWriter(t) as w:
        saisie.to_excel(w, sheet_name="saisie", index=False)
        scindees.to_excel(w, sheet_name="provinces_scindees", index=False)
    return M.lire_saisie(BytesIO(t.getvalue()), avant, avant47)


lignes, lignes47, erreurs, avert = charger(saisie, scindees)
assert not erreurs, erreurs
print("\nAvertissements du chargement :", avert or "aucun")
res2, inf2 = M.prevoir(M.ajouter_annee(avant, lignes), M.ajouter_annee(avant47, lignes47))
comparer(res2, inf2, "2a. parcours administrateur, effectifs des moities saisis")

lignes, lignes47, erreurs, avert = charger(saisie, scindees.assign(effectif=np.nan))
print("\n--- 2b. effectifs des moities laisses vides")
verdict(not erreurs, f"fichier accepte {erreurs[:1]}")
estime = lignes47[M.est_scindee(lignes47.type_lien)]
verdict(estime.methode_effectif.str.startswith("estimation").all(), "methode « estimation » portee par les 4 moities")
somme = estime.groupby("pcode_prov_old").effectif.sum()
verdict((np.abs(somme - lignes.set_index("pcode_prov_old").effectif[somme.index]) <= 1).all(),
        "les moities estimees retombent sur l'effectif de l'ancienne province")
res3, _ = M.prevoir(M.ajouter_annee(avant, lignes), M.ajouter_annee(avant47, lignes47))
verdict(len(res3) == 47, "prevision calculee pour les 47 provinces")

# 3. controles de saisie
print("\n--- 3. controles de saisie")


def essai(saisie_mod, scindees_mod, attendu):
    _, _, err, _ = charger(saisie_mod, scindees_mod)
    verdict(any(attendu in e for e in err), f"rejet « {attendu} » : {err[:1]}")


essai(saisie.iloc[:-1], scindees, "Provinces absentes")
essai(saisie.assign(taux_redoublement=saisie.taux_redoublement.where(saisie.index != 0, 140)), scindees,
      "hors de l'intervalle")
essai(saisie.assign(tap_G=saisie.tap_G.astype(object).where(saisie.index != 3, "abc")), scindees, "non numérique")
essai(saisie.assign(nouv_cp1_T=saisie.effectif * 2), scindees, "nouveaux inscrits au CP1 dépasse")
essai(saisie.assign(annee=2026), scindees, "il manquerait une année")
essai(saisie.drop(columns="tap_F"), scindees, "Colonnes manquantes")
essai(saisie, scindees.assign(effectif=scindees.effectif * 1.5), "la somme des effectifs")
essai(saisie, scindees.assign(effectif=scindees.effectif.where(scindees.index != 0, np.nan)), "remplissez les deux")

print("\n" + ("TOUT EST CONFORME" if not echecs else f"{len(echecs)} ECHEC(S) : {echecs}"))
raise SystemExit(1 if echecs else 0)
