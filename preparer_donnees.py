# -*- coding: utf-8 -*-
"""
A lancer en local avant chaque deploiement (et apres chaque reprise de l'analyse) :
    python preparer_donnees.py

Extrait des fichiers du projet ce dont la plateforme a besoin, dans plateforme/donnees/ :
  - panel_base.csv        historique officiel, 45 anciennes provinces x 2017-2024, 12 chiffres bruts
  - effectifs_47.csv      effectifs des 47 provinces en vigueur et methode de chaque chiffre
  - carte_47.json         contours simplifies des 47 provinces (COD-AB, Data Pack)
  - tableau_de_bord.html  le tableau de bord de l'analyse, affiche tel quel
"""
import json
import math
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ICI = Path(__file__).resolve().parent
V2 = ICI.parent
SORTIE = ICI / "donnees"
SORTIE.mkdir(exist_ok=True)
CLASSEUR = V2 / "work" / "Donnees_traitees_Defi1.xlsx"
GEOJSON_ZIP = (V2.parents[1] / "DataPack_DCB_2026" / "DataPack_DCB_2026" / "04_Cartographie_SIG"
               / "COD-AB_limites_administratives" / "bfa_admin_boundaries.geojson.zip")

from moteur import COLONNES_47, COLONNES_IDENTITE, COLONNES_SAISIE  # noqa: E402

# --- historique officiel des 45 anciennes provinces
panel = pd.read_excel(CLASSEUR, sheet_name="03_PANEL_province_annee")
base = panel[COLONNES_IDENTITE + ["annee"] + list(COLONNES_SAISIE)].sort_values(["pcode_prov_old", "annee"])
base.to_csv(SORTIE / "panel_base.csv", index=False, encoding="utf-8")
print(f"panel_base.csv   : {base.shape[0]} lignes, annees {base.annee.min()}-{base.annee.max()}")

# --- effectifs des 47 provinces
p47 = pd.read_excel(CLASSEUR, sheet_name="03_panel_47_provinces")[COLONNES_47].sort_values(["pcode_prov_new", "annee"])
p47.to_csv(SORTIE / "effectifs_47.csv", index=False, encoding="utf-8")
print(f"effectifs_47.csv : {p47.shape[0]} lignes, {p47.pcode_prov_new.nunique()} provinces")

# --- carte des 47 provinces : projection plane et simplification des contours
with zipfile.ZipFile(GEOJSON_ZIP) as z:
    nom = next(n for n in z.namelist() if n.endswith("admin2.geojson"))
    geo = json.loads(z.read(nom).decode("utf-8"))

LARGEUR, PAS_PX = 800, 1.0
# contours exterieurs de chaque province, convertis tout de suite en tableaux (memoire limitee)
anneaux = []
for f in geo.pop("features"):
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    anneaux.append((f["properties"]["adm2_pcode"], f["properties"]["adm2_name"],
                    [np.asarray(poly[0], dtype=np.float32) for poly in polys]))
del geo
tous = np.concatenate([a for _, _, ps in anneaux for a in ps])
lon_min, lat_min = tous.min(0)
lon_max, lat_max = tous.max(0)
del tous
cos_lat = math.cos(math.radians((lat_min + lat_max) / 2))
echelle = LARGEUR / ((lon_max - lon_min) * cos_lat)
hauteur = int(round((lat_max - lat_min) * echelle))

carte = {"largeur": LARGEUR, "hauteur": hauteur, "provinces": {}}
for code, nom_prov, polys in anneaux:
    morceaux = []
    for a in polys:
        x = (a[:, 0] - lon_min) * cos_lat * echelle
        y = (lat_max - a[:, 1]) * echelle
        # simplification : points ramenes sur une grille de 1 px, doublons consecutifs retires
        xy = np.round(np.column_stack([x, y]) / PAS_PX) * PAS_PX
        garde = np.r_[True, np.any(np.diff(xy, axis=0) != 0, axis=1)]
        xy = xy[garde]
        if len(xy) >= 4:
            morceaux.append("M" + "L".join(f"{u:g},{v:g}" for u, v in xy) + "Z")
    carte["provinces"][code] = {"nom": nom_prov, "path": "".join(morceaux)}
(SORTIE / "carte_47.json").write_text(json.dumps(carte, ensure_ascii=False), encoding="utf-8")
manquantes = set(p47.pcode_prov_new) - set(carte["provinces"])
print(f"carte_47.json    : {len(carte['provinces'])} provinces, "
      f"{(SORTIE / 'carte_47.json').stat().st_size // 1024} ko ; codes sans contour : {manquantes or 'aucun'}")

# --- tableau de bord de l'analyse
shutil.copy(V2 / "site_en_ligne" / "index.html", SORTIE / "tableau_de_bord.html")
print("tableau_de_bord.html copie")

# --- l'ancienne carte a 45 provinces n'est plus utilisee
(SORTIE / "carte.json").unlink(missing_ok=True)
