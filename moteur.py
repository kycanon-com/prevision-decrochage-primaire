# -*- coding: utf-8 -*-
"""
Moteur de calcul de la plateforme : a partir des chiffres bruts d'une annee t, calcule les variables,
l'indice de risque (IRD), la prevision du taux d'abandon en t+1, son intervalle a 80 %, la probabilite
d'alerte et la priorite des 47 provinces du decoupage en vigueur.

Les formules sont celles du pipeline src/step04_analyse_v2.py (version a 47 provinces, noyau L11) :
memes variables, memes modeles, memes parametres, meme ponderation des provinces scindees,
et la prevision toujours ramenee dans son propre intervalle.

Ce module ne depend pas de Streamlit : il se teste seul (verifier_moteur.py).
"""
from io import BytesIO

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# =============================================================================
# Parametres (identiques au pipeline)
# =============================================================================
ANNEE_BASE_ECOLES = 2017       # les ecoles perdues se comptent depuis 2017-18
SEUIL_ALERTE = 15.0            # evenement d'alerte : abandon >= 15 % l'annee suivante

# noyau L11 : six determinants documentes, aucun derive du taux d'abandon
NOYAU = ["taux_redoublement", "tap_T", "ecart_achevement_gf", "part_cm2", "pression_entree",
         "pdi_pour_100_enfants_6_11"]
LIBELLES_NOYAU = {
    "taux_redoublement": "Taux de redoublement (signe inversé à l'échelle provinciale : redoubler et "
                         "abandonner se substituent)",
    "tap_T": "Taux d'achèvement du primaire",
    "ecart_achevement_gf": "Écart d'achèvement garçons - filles",
    "part_cm2": "Part du CM2 dans l'effectif",
    "pression_entree": "Nouveaux inscrits au CP1 pour 100 élèves",
    "pdi_pour_100_enfants_6_11": "Déplacés internes pour 100 enfants de 6-11 ans",
}

DIMENSIONS = {
    "D1_abandon": {"poids": 0.375, "libelle": "Abandon en cours de cycle",
                   "vars": ["taux_abandon", "taux_abandon_moy3"]},
    "D2_exclusion": {"poids": 0.35, "libelle": "Exclusion scolaire et non-achèvement",
                     "vars": ["ecoles_publiques_perdues_depuis_2017", "deficit_scolarisation", "deficit_achevement"]},
    "D4_choc": {"poids": 0.275, "libelle": "Choc sécuritaire (déplacés internes)",
                "vars": ["pdi_pour_100_enfants_6_11"]},
}
# poids estimes sur la cible (carnet 02), arrondis au quart de point ; pour les reestimer, rejouer le carnet 02
DIMS = list(DIMENSIONS)

PRIORITES = ["P1 - intervention immédiate", "P2 - surveillance renforcée", "P3 - vigilance",
             "P4 - suivi de routine"]
SEUILS_IRD = [70, 55, 40]
PARTS_PROBA = [5 / 45, 12 / 45, 20 / 45]     # bras probabilite : les 5, 12 et 20 plus probables (sur 45)

COLONNES_IDENTITE = ["pcode_prov_old", "province_old", "pcode_reg_old", "region_old"]
COLONNES_47 = ["annee", "pcode_prov_new", "province_new", "pcode_reg_new", "region_new", "pcode_prov_old",
               "type_lien", "effectif", "methode_effectif"]

# les 12 chiffres bruts a fournir pour chaque ancienne province : nom -> (libelle, minimum, maximum)
COLONNES_SAISIE = {
    "effectif": ("Effectif total du primaire (élèves)", 1, None),
    "effectif_cm2": ("Effectif du CM2 (élèves)", 0, None),
    "nouv_cp1_T": ("Nouveaux inscrits au CP1 (élèves)", 0, None),
    "taux_abandon": ("Taux d'abandon (%)", 0, 100),
    "taux_redoublement": ("Taux de redoublement (%)", 0, 100),
    "tap_T": ("Taux d'achèvement du primaire, total (%)", 0, 250),
    "tap_G": ("Taux d'achèvement du primaire, garçons (%)", 0, 250),
    "tap_F": ("Taux d'achèvement du primaire, filles (%)", 0, 250),
    "tbs_T": ("Taux brut de scolarisation, total (%)", 0, 250),
    "ecoles_public": ("Nombre d'écoles publiques", 0, None),
    "pdi": ("Personnes déplacées internes (nombre)", 0, None),
    "pop611_T": ("Population des 6-11 ans", 1, None),
}
TOLERANCE_SOMME = 0.01    # les deux moities d'une province scindee doivent retomber sur son effectif a 1 % pres


def annee_label(a):
    return f"{a}-{str(a + 1)[-2:]}"          # 2024 -> "2024-25"


def est_scindee(type_lien):
    return type_lien.astype(str).str.contains("scind", case=False)


# =============================================================================
# 1. Variables et passage aux 47 provinces
# =============================================================================
def variables_45(panel):
    """Variables calculees au niveau de l'ancienne province (puis heritees par les moities)."""
    p = panel.copy()
    ecoles_base = p[p.annee == ANNEE_BASE_ECOLES].set_index("pcode_prov_old").ecoles_public
    p["ecoles_publiques_perdues_depuis_2017"] = 100 * (1 - p.ecoles_public / p.pcode_prov_old.map(ecoles_base))
    p["pdi_pour_100_enfants_6_11"] = 100 * p.pdi / p.pop611_T
    return p


def construire_47(panel, effectifs_47):
    """Projette les 45 anciennes provinces sur les 47 en vigueur (meme regle que le pipeline).

    Les moities de Soum et de Tapoa recoivent leur effectif propre ; le CM2 et les nouveaux entrants
    sont repartis selon leur part d'effectif ; tout le reste (taux d'abandon, redoublement,
    achevement...) est herite de l'ancienne province. Chaque moitie porte un poids egal a sa part,
    pour que l'ancienne province compte une seule fois dans l'apprentissage.
    """
    ref = effectifs_47.drop(columns=["methode_effectif"], errors="ignore")
    out = variables_45(panel).merge(ref, on=["annee", "pcode_prov_old"], how="inner", suffixes=("_old45", ""))
    scinde = est_scindee(out.type_lien)
    part = (100 * out.effectif / out.effectif_old45).map(lambda v: round(float(v), 1)) / 100.0
    # comme dans les carnets : l'effectif de la moitie = part x effectif de l'ancienne province, de sorte que les
    # ratios (part du CM2, pression d'entree) restent ceux de l'ancienne province ; l'effectif propre (somme des
    # communes) est conserve a part pour les volumes d'eleves.
    out["effectif_propre"] = out["effectif"].astype(float)
    out["effectif"] = out["effectif"].astype(float)
    out.loc[scinde, "effectif"] = out.loc[scinde, "effectif_old45"] * part[scinde]
    for col in ("effectif_cm2", "nouv_cp1_T"):
        out[col] = out[col].astype(float)
        out.loc[scinde, col] = out.loc[scinde, col] * part[scinde]
    out["poids"] = np.where(scinde, part, 1.0)
    out["scindee"] = scinde
    return out.drop(columns=[c for c in out.columns if c.endswith("_old45")])


def comme_les_carnets(p):
    """Fait passer le panel par un fichier CSV, comme le font les carnets (le carnet 02 relit le panel ecrit par le
    carnet 01). Cette lecture arrondit les decimales au dernier chiffre pres ; le boosting a erreur absolue y est
    sensible, et sans ce passage les previsions s'ecarteraient jusqu'a un point de celles des carnets."""
    from io import StringIO
    return pd.read_csv(StringIO(p.to_csv(sep=";", decimal=",", index=False)), sep=";", decimal=",")


def preparer(p):
    """Variables de l'indice et du modele (identiques a prepare() du pipeline)."""
    p = p.sort_values(["pcode_prov_new", "annee"]).reset_index(drop=True)
    g = p.groupby("pcode_prov_new")
    net = lambda s: s.replace([np.inf, -np.inf], np.nan)
    p["deficit_scolarisation"] = 100 - p.tbs_T.clip(upper=100)
    p["deficit_achevement"] = 100 - p.tap_T.clip(upper=100)
    p["taux_abandon_moy3"] = g.taux_abandon.transform(lambda s: s.rolling(3, min_periods=1).mean())
    p["part_cm2"] = net(p.effectif_cm2 / p.effectif * 100)
    p["ecart_achevement_gf"] = p.tap_G - p.tap_F
    p["pression_entree"] = net(p.nouv_cp1_T / p.effectif * 100)
    p["y_next"] = g.taux_abandon.shift(-1)
    p["alerte"] = (p.y_next >= SEUIL_ALERTE).astype(float).where(p.y_next.notna())
    p["cible"] = p.annee + 1
    p["n_annees_crise"] = g.taux_abandon.transform(lambda s: (s >= 25).cumsum())
    p["zone_crise"] = (p.ecoles_publiques_perdues_depuis_2017 > 25) | (p.n_annees_crise > 0)
    return p


# =============================================================================
# 2. Indice de risque (rangs percentiles dans l'annee, sur les 47 lignes)
# =============================================================================
def calculer_ird(p):
    out = p[["pcode_prov_new", "annee"]].copy()
    for k, d in DIMENSIONS.items():
        rangs = [p.groupby("annee")[v].transform(lambda s: 100 * s.fillna(s.median()).rank(pct=True, method="average"))
                 .fillna(50) for v in d["vars"]]
        out[k] = np.mean(rangs, axis=0)
    out["IRD"] = sum(out[k] * d["poids"] for k, d in DIMENSIONS.items()) / sum(d["poids"] for d in DIMENSIONS.values())
    out["rang_IRD"] = out.groupby("annee").IRD.rank(ascending=False, method="min").astype(int)
    return out


# =============================================================================
# 3. Modeles (ponderes)
# =============================================================================
def gbm(**kw):
    return GradientBoostingRegressor(n_estimators=300, learning_rate=0.03, max_depth=3, subsample=0.8,
                                     min_samples_leaf=5, random_state=1, **kw)


def medianes(tr):
    return tr[NOYAU].median().fillna(0.0)


def prevision_t1(data, cur):
    # moyenne du niveau historique de la province et d'un boosting pondere sur le noyau L11
    niveau = cur.pcode_prov_new.map(data.groupby("pcode_prov_new").taux_abandon.mean()) \
                .fillna(data.taux_abandon.mean()).values
    m = medianes(data)
    boost = gbm(loss="absolute_error").fit(data[NOYAU].fillna(m), data.y_next, sample_weight=data.poids.values) \
                                      .predict(cur[NOYAU].fillna(m))
    return np.clip((niveau + boost) / 2, 0, 100)


def intervalle_80(data, cur):
    # bornes 10 % / 90 % apprises sans la derniere annee, elargies d'une correction mesuree sur elle, par regime
    derniere = data.cible.max()
    app, cal = data[data.cible < derniere], data[data.cible == derniere]
    m = medianes(app)
    bas = gbm(loss="quantile", alpha=0.10).fit(app[NOYAU].fillna(m), app.y_next, sample_weight=app.poids.values)
    haut = gbm(loss="quantile", alpha=0.90).fit(app[NOYAU].fillna(m), app.y_next, sample_weight=app.poids.values)
    corr = {}
    for regime, masque in (("stables", ~cal.zone_crise.values), ("crise", cal.zone_crise.values)):
        c = cal[masque]
        X = c[NOYAU].fillna(m)
        depassement = np.maximum(bas.predict(X) - c.y_next.values, c.y_next.values - haut.predict(X))
        corr[regime] = float(np.quantile(depassement, 0.8)) if len(c) >= 8 else 4.0
    q = np.where(cur.zone_crise.values, corr["crise"], corr["stables"])
    X = cur[NOYAU].fillna(m)
    return np.clip(bas.predict(X) - q, 0, 100), np.clip(haut.predict(X) + q, 0, 100), corr


def probabilite_alerte(data, cur):
    m = medianes(data)
    modele = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=4000))
    modele.fit(data[NOYAU].fillna(m), data.alerte, logisticregression__sample_weight=data.poids.values)
    proba = modele.predict_proba(cur[NOYAU].fillna(m))[:, 1]
    part = float(np.clip(proba.mean(), 0.05, 0.60))       # on signale autant de provinces que le modele en attend
    seuil = float(np.quantile(proba, 1 - part)) - 1e-12
    coefficients = dict(zip(NOYAU, modele.named_steps["logisticregression"].coef_[0]))
    return proba, part, seuil, coefficients


# =============================================================================
# 4. Prevision complete pour l'annee t+1
# =============================================================================
def prevoir(panel, effectifs_47):
    """panel brut des 45 anciennes provinces + effectifs des 47 -> (table des 47 provinces, infos)."""
    p = comme_les_carnets(preparer(construire_47(panel, effectifs_47)))
    I = calculer_ird(p)
    t = int(p.annee.max())
    data = p[p.y_next.notna() & p.taux_abandon.notna()]            # paires (t, t+1) observees
    cur = p[p.annee == t].copy()

    cur["prevision"] = prevision_t1(data, cur)
    cur["prevision_bas80_brut"], cur["prevision_haut80_brut"], corr = intervalle_80(data, cur)
    # la prevision est toujours dans son intervalle (meme regle que le pipeline)
    cur["prevision_bas80"] = np.minimum(cur.prevision_bas80_brut, cur.prevision)
    cur["prevision_haut80"] = np.maximum(cur.prevision_haut80_brut, cur.prevision)
    cur["proba_alerte"], part, seuil, coefficients = probabilite_alerte(data, cur)
    cur["signalee_alerte"] = cur.proba_alerte >= seuil
    cur["eleves_decrocheurs_prevus"] = (cur.prevision / 100 * cur.effectif_propre).round()

    r = cur.merge(I[I.annee == t], on=["pcode_prov_new", "annee"])
    precedent = I[I.annee == t - 1].set_index("pcode_prov_new").IRD
    r["evolution_IRD"] = r.IRD - r.pcode_prov_new.map(precedent)

    # priorite : indice au-dessus de 70 / 55 / 40, ou probabilite dans les parts 5/45, 12/45, 20/45 les plus fortes
    seuils_proba = [float(np.quantile(r.proba_alerte.values, 1 - q)) for q in PARTS_PROBA]
    def priorite(indice, proba):
        for label, s_ird, s_proba in zip(PRIORITES, SEUILS_IRD, seuils_proba):
            if indice >= s_ird or proba >= s_proba:
                return label
        return PRIORITES[-1]
    r["priorite"] = [priorite(i, pr) for i, pr in zip(r.IRD, r.proba_alerte)]
    r["source_risque"] = np.where(r.scindee, "taux hérités de " + r.province_old.astype(str) +
                                  " ; effectif propre", "province DGESS")

    colonnes = ["rang_IRD", "pcode_prov_new", "province_new", "region_new", "pcode_prov_old", "province_old",
                "scindee", "source_risque", "methode_effectif", "poids", "IRD", "priorite", *DIMS, "evolution_IRD",
                "taux_abandon", *NOYAU, "tbs_T", "ecoles_publiques_perdues_depuis_2017", "zone_crise", "effectif_propre",
                "prevision", "prevision_bas80", "prevision_haut80", "prevision_bas80_brut", "prevision_haut80_brut",
                "proba_alerte", "signalee_alerte", "eleves_decrocheurs_prevus"]
    r = r.merge(effectifs_47[effectifs_47.annee == t][["pcode_prov_new", "methode_effectif"]], on="pcode_prov_new",
                how="left")
    resultat = r[colonnes].sort_values(["IRD", "province_new"], ascending=[False, True]).reset_index(drop=True)
    infos = {"annee_donnees": t, "annee_prevue": t + 1, "n_lignes_apprentissage": len(data),
             "poids_apprentissage": float(data.poids.sum()),
             "annees_apprentissage": f"{annee_label(int(data.annee.min()))} à {annee_label(int(data.annee.max()))}",
             "part_signalee": part, "seuil_alerte": seuil, "correction_intervalle": corr,
             "seuils_proba_priorite": seuils_proba, "coefficients_alerte": coefficients,
             "historique_ird": I,
             "historique": p[["annee", "pcode_prov_new", "taux_abandon", "effectif_propre"]]
             .merge(I[["pcode_prov_new", "annee", "IRD"]], on=["pcode_prov_new", "annee"])}
    return resultat, infos


# =============================================================================
# 5. Modele Excel de saisie : creation, lecture, controle
# =============================================================================
def creer_modele_excel(panel, effectifs_47, annee):
    """Classeur a remplir pour l'annee `annee`, pre-rempli avec les chiffres de l'annee precedente."""
    derniere = int(panel.annee.max())
    saisie = panel[panel.annee == derniere][["pcode_prov_old", "province_old", "region_old"]
                                            + list(COLONNES_SAISIE)].copy()
    saisie.insert(0, "annee", annee)
    e = effectifs_47[(effectifs_47.annee == derniere) & est_scindee(effectifs_47.type_lien)]
    scindees = e[["pcode_prov_new", "province_new", "pcode_prov_old", "effectif"]].copy()
    scindees = scindees.merge(panel[panel.annee == derniere][["pcode_prov_old", "province_old"]], on="pcode_prov_old")
    scindees.insert(0, "annee", annee)
    notice = pd.DataFrame(
        [{"feuille": "saisie", "colonne": "annee", "contenu": f"Année scolaire t (début) : {annee} = "
          f"{annee_label(annee)}. Ne pas modifier.", "contrainte": "identique sur toutes les lignes"},
         {"feuille": "saisie", "colonne": "pcode_prov_old / province_old / region_old",
          "contenu": "Les 45 provinces de l'ancien découpage, celui des annuaires DGESS. Ne pas modifier.",
          "contrainte": "les 45 codes, une fois chacun"}]
        + [{"feuille": "saisie", "colonne": c, "contenu": lib,
            "contrainte": f"nombre >= {mn}" + (f" et <= {mx}" if mx is not None else "")}
           for c, (lib, mn, mx) in COLONNES_SAISIE.items()]
        + [{"feuille": "provinces_scindees", "colonne": "effectif",
            "contenu": "Effectif propre de chacune des 4 provinces issues de Soum et de Tapoa (somme des communes, "
                       "annuaires régionaux INSD). FACULTATIF : laissez les deux cases d'une même ancienne province "
                       "vides pour reprendre les parts de l'année précédente.",
            "contrainte": "les deux moitiés doivent faire l'effectif de l'ancienne province (feuille saisie), à 1 % près"},
           {"feuille": "", "colonne": "IMPORTANT",
            "contenu": f"Les valeurs pré-remplies sont celles de {annee_label(derniere)}. Remplacez-les par les "
                       "chiffres de l'année t (annuaire statistique DGESS, CONASUR, projections INSD), réels ou estimés.",
            "contrainte": ""}])
    tampon = BytesIO()
    with pd.ExcelWriter(tampon, engine="openpyxl") as w:
        saisie.to_excel(w, sheet_name="saisie", index=False)
        scindees.to_excel(w, sheet_name="provinces_scindees", index=False)
        notice.to_excel(w, sheet_name="notice", index=False)
        for feuille in w.sheets.values():
            for colonne in feuille.columns:
                feuille.column_dimensions[colonne[0].column_letter].width = 22
    return tampon.getvalue()


def lire_saisie(fichier, panel, effectifs_47):
    """Lit et controle un classeur rempli.

    Renvoie (lignes 45 a ajouter, lignes 47 a ajouter, erreurs, avertissements)."""
    erreurs, avertissements = [], []
    try:
        classeur = pd.read_excel(fichier, sheet_name=None)
    except Exception as e:                                   # fichier illisible
        return None, None, [f"Classeur illisible : {e}"], []
    if "saisie" not in classeur:
        return None, None, ["Feuille « saisie » absente du classeur."], []
    df = classeur["saisie"].dropna(how="all")

    manquantes = [c for c in ["annee", "pcode_prov_old"] + list(COLONNES_SAISIE) if c not in df.columns]
    if manquantes:
        return None, None, [f"Colonnes manquantes dans « saisie » : {', '.join(manquantes)}"], []

    # annee
    annees = pd.to_numeric(df.annee, errors="coerce").dropna().unique()
    if len(annees) != 1:
        return None, None, ["La colonne « annee » doit contenir une seule et même année sur toutes les lignes."], []
    annee = int(annees[0])
    derniere = int(panel.annee.max())
    if annee <= ANNEE_BASE_ECOLES:
        erreurs.append(f"Année {annee} invalide.")
    elif annee > derniere + 1:
        erreurs.append(f"L'année {annee_label(annee)} n'est pas la suivante de la dernière connue "
                       f"({annee_label(derniere)}) : il manquerait une année d'historique.")
    elif annee <= derniere:
        avertissements.append(f"L'année {annee_label(annee)} existe déjà : ses chiffres seront remplacés par ceux "
                              "du fichier, et les années suivantes ignorées.")

    # provinces
    codes_attendus = set(panel.pcode_prov_old)
    codes = df.pcode_prov_old.astype(str).str.strip()
    inconnus, absents = sorted(set(codes) - codes_attendus), sorted(codes_attendus - set(codes))
    doublons = sorted(codes[codes.duplicated()].unique())
    if inconnus:
        erreurs.append(f"Codes de province inconnus : {', '.join(inconnus)}")
    if absents:
        erreurs.append(f"Provinces absentes du fichier ({len(absents)}) : {', '.join(absents)}")
    if doublons:
        erreurs.append(f"Provinces en double : {', '.join(doublons)}")
    df["pcode_prov_old"] = codes

    # valeurs
    noms = panel.drop_duplicates("pcode_prov_old").set_index("pcode_prov_old").province_old
    nom = lambda i: noms.get(df.at[i, "pcode_prov_old"], df.at[i, "pcode_prov_old"])
    for c, (lib, mn, mx) in COLONNES_SAISIE.items():
        v = pd.to_numeric(df[c], errors="coerce")
        for i in df.index[v.isna()]:
            erreurs.append(f"{nom(i)} : « {c} » vide ou non numérique.")
        hors = v.notna() & ((v < mn) | ((v > mx) if mx is not None else False))
        for i in df.index[hors]:
            erreurs.append(f"{nom(i)} : « {c} » = {v[i]} hors de l'intervalle autorisé.")
        df[c] = v
    for col, lib in (("effectif_cm2", "l'effectif du CM2"), ("nouv_cp1_T", "le nombre de nouveaux inscrits au CP1")):
        for i in df.index[df[col] > df.effectif]:
            erreurs.append(f"{nom(i)} : {lib} dépasse l'effectif total.")
    if erreurs:
        return None, None, erreurs, avertissements

    identite = panel.drop_duplicates("pcode_prov_old")[COLONNES_IDENTITE]
    lignes = identite.merge(df[["pcode_prov_old"] + list(COLONNES_SAISIE)], on="pcode_prov_old")
    lignes.insert(len(COLONNES_IDENTITE), "annee", annee)

    # --- effectifs des 47 provinces
    lignes_47, err47, av47 = effectifs_annee_47(lignes, effectifs_47, classeur.get("provinces_scindees"))
    erreurs += err47
    avertissements += av47
    if erreurs:
        return None, None, erreurs, avertissements

    # avertissements : chiffres identiques a l'annee precedente, sauts brutaux
    precedente = panel[panel.annee == annee - 1].set_index("pcode_prov_old")
    if len(precedente):
        d = lignes.set_index("pcode_prov_old")
        identiques = [noms[k] for k in d.index if all(np.isclose(d.at[k, c], precedente.at[k, c], equal_nan=True)
                                                      for c in COLONNES_SAISIE)]
        if identiques:
            avertissements.append(f"{len(identiques)} province(s) ont exactement les chiffres de l'année précédente "
                                  f"(modèle non modifié ?) : {', '.join(identiques[:10])}"
                                  + (" …" if len(identiques) > 10 else ""))
        saut = (d.taux_abandon - precedente.taux_abandon.reindex(d.index)).abs()
        for k in saut[saut > 30].index:
            avertissements.append(f"{noms[k]} : le taux d'abandon varie de plus de 30 points en un an "
                                  f"({precedente.at[k, 'taux_abandon']:.1f} → {d.at[k, 'taux_abandon']:.1f}).")
    return lignes, lignes_47, [], avertissements


def effectifs_annee_47(lignes, effectifs_47, feuille_scindees):
    """Effectifs des 47 provinces pour l'annee saisie.

    Provinces non scindees : l'effectif de la feuille « saisie ». Provinces scindees : l'effectif propre de la
    feuille « provinces_scindees » si les deux moities sont remplies (somme controlee), sinon les parts de
    l'annee precedente appliquees a l'effectif de l'ancienne province.
    """
    annee = int(lignes.annee.iloc[0])
    erreurs, avertissements = [], []
    modele = effectifs_47[effectifs_47.annee == effectifs_47.annee[effectifs_47.annee < annee].max()].copy()
    eff45 = lignes.set_index("pcode_prov_old").effectif
    modele["annee"] = annee
    modele["effectif"] = modele.effectif.astype(float)
    scinde = est_scindee(modele.type_lien)
    modele.loc[~scinde, "effectif"] = modele.loc[~scinde, "pcode_prov_old"].map(eff45).values
    modele.loc[~scinde, "methode_effectif"] = "1 ancienne = 1 nouvelle : valeur saisie"

    saisis = {}
    if feuille_scindees is not None and {"pcode_prov_new", "effectif"} <= set(feuille_scindees.columns):
        f = feuille_scindees.dropna(subset=["pcode_prov_new"])
        saisis = dict(zip(f.pcode_prov_new.astype(str).str.strip(), pd.to_numeric(f.effectif, errors="coerce")))

    for ancien, groupe in modele[scinde].groupby("pcode_prov_old"):
        total = float(eff45[ancien])
        valeurs = [saisis.get(k, np.nan) for k in groupe.pcode_prov_new]
        noms = " et ".join(groupe.province_new)
        if all(np.isnan(v) for v in valeurs):
            precedent = groupe.effectif / groupe.effectif.sum()
            modele.loc[groupe.index, "effectif"] = (precedent * total).round().values
            modele.loc[groupe.index, "methode_effectif"] = (
                f"estimation : parts {annee_label(annee - 1)} appliquées")
            avertissements.append(f"{noms} : effectifs propres non fournis, parts de l'année précédente reprises.")
        elif any(np.isnan(v) for v in valeurs) or any(v < 0 for v in valeurs):
            erreurs.append(f"{noms} : remplissez les deux effectifs (nombres positifs), ou laissez les deux vides.")
        elif abs(sum(valeurs) - total) > TOLERANCE_SOMME * total:
            erreurs.append(f"{noms} : la somme des effectifs ({sum(valeurs):,.0f}) ne correspond pas à l'effectif "
                           f"de l'ancienne province saisi dans « saisie » ({total:,.0f}).".replace(",", " "))
        else:
            modele.loc[groupe.index, "effectif"] = valeurs
            modele.loc[groupe.index, "methode_effectif"] = "effectif saisi (somme des communes contrôlée)"
    return modele[COLONNES_47], erreurs, avertissements


def ajouter_annee(table, lignes):
    """Ajoute (ou remplace) une annee dans le panel 45 ou la table 47 ; les annees posterieures sont retirees."""
    annee = int(lignes.annee.iloc[0])
    garde = table[table.annee < annee]
    return pd.concat([garde, lignes[garde.columns]], ignore_index=True)
