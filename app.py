# -*- coding: utf-8 -*-
"""
Plateforme de prevision du decrochage scolaire au primaire (Burkina Faso, 47 provinces du decoupage en vigueur).

Lancer en local :  streamlit run app.py
Deploiement     :  voir DEPLOIEMENT.md
"""
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from scipy.stats import spearmanr

import moteur as M

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "donnees"
PUBLIE_45 = DONNEES / "annees_publiees.csv"            # chiffres des annees ajoutees (45 anciennes provinces)
PUBLIE_47 = DONNEES / "effectifs_47_publies.csv"       # effectifs des 47 provinces pour ces annees

st.set_page_config(page_title="Prévision du décrochage scolaire", page_icon="📊", layout="wide")

COULEURS_PRIORITE = {M.PRIORITES[0]: "#b2182b", M.PRIORITES[1]: "#ef8a62",
                     M.PRIORITES[2]: "#fddbc7", M.PRIORITES[3]: "#d1e5f0"}
LIBELLES = {
    "rang_IRD": "Rang", "province_new": "Province", "region_new": "Région", "IRD": "Indice de risque",
    "priorite": "Priorité", "taux_abandon": "Abandon t (%)", "prevision": "Abandon prévu t+1 (%)",
    "prevision_bas80": "Bas 80 %", "prevision_haut80": "Haut 80 %", "proba_alerte": "Probabilité d'alerte (%)",
    "signalee_alerte": "Signalée", "eleves_decrocheurs_prevus": "Élèves décrocheurs prévus",
    "source_risque": "Source des taux", "zone_crise": "Zone de crise", "evolution_IRD": "Évolution de l'indice"}


# =============================================================================
# Donnees
# =============================================================================
@st.cache_data
def charger_base():
    return (pd.read_csv(DONNEES / "panel_base.csv", dtype={"pcode_prov_old": str}),
            pd.read_csv(DONNEES / "effectifs_47.csv", dtype={"pcode_prov_old": str, "pcode_prov_new": str}))


@st.cache_data
def charger_carte():
    return json.loads((DONNEES / "carte_47.json").read_text(encoding="utf-8"))


def donnees_publiees():
    """Historique officiel + annees publiees par l'administrateur."""
    base, eff47 = charger_base()
    if PUBLIE_45.exists() and PUBLIE_47.exists():
        ajout = pd.read_csv(PUBLIE_45, dtype={"pcode_prov_old": str})
        ajout47 = pd.read_csv(PUBLIE_47, dtype={"pcode_prov_old": str, "pcode_prov_new": str})
        for annee in sorted(ajout.annee.unique()):
            base = M.ajouter_annee(base, ajout[ajout.annee == annee])
            eff47 = M.ajouter_annee(eff47, ajout47[ajout47.annee == annee])
    return base, eff47


@st.cache_data(show_spinner="Entraînement des modèles et calcul des prévisions…")
def calculer(panel, eff47):
    return M.prevoir(panel, eff47)


def mot_de_passe_admin():
    try:
        return st.secrets["MOT_DE_PASSE_ADMIN"]
    except Exception:                       # aucun secret configure : publication desactivee
        return None


def vers_excel(df):
    tampon = BytesIO()
    df.to_excel(tampon, index=False)
    return tampon.getvalue()


# =============================================================================
# Affichage
# =============================================================================
def couleur_continue(v, vmin, vmax):
    x = 0.0 if vmax == vmin else float(np.clip((v - vmin) / (vmax - vmin), 0, 1))
    debut, fin = np.array([255, 237, 160]), np.array([128, 0, 38])
    r, g, b = (debut + x * (fin - debut)).astype(int)
    return f"rgb({r},{g},{b})"


def carte_svg(resultat, mode):
    carte = charger_carte()
    r = resultat.set_index("pcode_prov_new")
    if mode == "Priorité":
        couleur = {k: COULEURS_PRIORITE[r.at[k, "priorite"]] for k in r.index}
        legende = "".join(f'<span style="display:inline-block;width:12px;height:12px;background:{c};'
                          f'border:1px solid #888;margin:0 4px 0 12px"></span>{p}'
                          for p, c in COULEURS_PRIORITE.items())
    else:
        col = "prevision" if mode.startswith("Abandon") else "IRD"
        vmin, vmax = r[col].min(), r[col].max()
        couleur = {k: couleur_continue(r.at[k, col], vmin, vmax) for k in r.index}
        legende = (f'{vmin:.1f} <span style="display:inline-block;width:160px;height:12px;vertical-align:middle;'
                   f'background:linear-gradient(90deg,rgb(255,237,160),rgb(128,0,38))"></span> {vmax:.1f}')
    legende += ('<br><span style="display:inline-block;width:22px;border-top:2px dashed #222;'
                'vertical-align:middle;margin-right:6px"></span>contour pointillé : province issue d\'une scission, '
                'taux hérités de l\'ancienne province')
    formes = []
    for code, geo in carte["provinces"].items():
        if code not in r.index:
            continue
        x = r.loc[code]
        bulle = (f"{x.province_new} ({x.region_new})\n{x.priorite}\nIndice : {x.IRD:.1f} (rang {x.rang_IRD})\n"
                 f"Abandon t : {x.taux_abandon:.1f} %\nPrévu t+1 : {x.prevision:.1f} % "
                 f"[{x.prevision_bas80:.1f} ; {x.prevision_haut80:.1f}]\n"
                 f"Élèves décrocheurs prévus : {int(x.eleves_decrocheurs_prevus):,}".replace(",", " ")
                 + (f"\nTaux hérités de {x.province_old} (aucun taux publié par commune)" if x.scindee else ""))
        trait = 'stroke="#222" stroke-width="1.4" stroke-dasharray="3,2"' if x.scindee else \
                'stroke="#555" stroke-width="0.5"'
        formes.append(f'<path d="{geo["path"]}" fill="{couleur[code]}" {trait}><title>{bulle}</title></path>')
    return (f'<div style="font-family:sans-serif;font-size:13px">'
            f'<svg viewBox="0 0 {carte["largeur"]} {carte["hauteur"]}" style="width:100%;max-height:560px">'
            f'{"".join(formes)}</svg><div style="margin-top:6px;line-height:1.8">{legende}</div></div>')


def afficher_prevision(resultat, infos, cle):
    t, t1 = infos["annee_donnees"], infos["annee_prevue"]
    n = resultat.priorite.str[:2].value_counts()
    taux_moyen = np.average(resultat.prevision, weights=resultat.effectif.clip(lower=1))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Provinces P1 / P2", f"{n.get('P1', 0)} / {n.get('P2', 0)}")
    c2.metric(f"Abandon moyen prévu {M.annee_label(t1)}", f"{taux_moyen:.1f} %")
    c3.metric("Élèves décrocheurs prévus", f"{int(resultat.eleves_decrocheurs_prevus.sum()):,}".replace(",", " "))
    c4.metric("Provinces en alerte", int(resultat.signalee_alerte.sum()))

    gauche, droite = st.columns([3, 2])
    with gauche:
        mode = st.radio("Colorer la carte selon", ["Priorité", f"Abandon prévu {M.annee_label(t1)}",
                                                   f"Indice de risque {M.annee_label(t)}"],
                        horizontal=True, key=f"mode_{cle}")
        components.html(carte_svg(resultat, mode), height=660)
        st.caption("Survolez une province pour voir ses chiffres.")
    with droite:
        st.markdown("**Les 15 provinces les plus exposées**")
        top = resultat.head(15)[["province_new", "priorite", "IRD", "taux_abandon", "prevision"]]
        st.dataframe(top.rename(columns=LIBELLES), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.1f")
                                    for c in ["Indice de risque", "Abandon t (%)", "Abandon prévu t+1 (%)"]})

    st.markdown("**Les 47 provinces**")
    colonnes = ["rang_IRD", "province_new", "region_new", "priorite", "IRD", "evolution_IRD", "taux_abandon",
                "prevision", "prevision_bas80", "prevision_haut80", "proba_alerte", "signalee_alerte",
                "eleves_decrocheurs_prevus", "zone_crise", "source_risque"]
    tableau = resultat[colonnes].copy()
    tableau["proba_alerte"] = 100 * tableau.proba_alerte
    st.dataframe(tableau.rename(columns=LIBELLES), hide_index=True, width="stretch", height=420,
                 column_config={
                     **{LIBELLES[c]: st.column_config.NumberColumn(format="%.1f")
                        for c in ["IRD", "evolution_IRD", "taux_abandon", "prevision", "prevision_bas80",
                                  "prevision_haut80"]},
                     LIBELLES["proba_alerte"]: st.column_config.ProgressColumn(format="%.0f", min_value=0,
                                                                               max_value=100),
                     LIBELLES["eleves_decrocheurs_prevus"]: st.column_config.NumberColumn(format="%d")})
    st.download_button("Télécharger toutes les colonnes (Excel)", vers_excel(resultat),
                       file_name=f"prevision_{M.annee_label(t1)}.xlsx", key=f"dl_{cle}")
    st.caption(f"Modèles réentraînés sur {infos['n_lignes_apprentissage']} lignes province × année "
               f"({infos['annees_apprentissage']}), poids total {infos['poids_apprentissage']:.0f}. "
               "Détails : page « Méthode et sources ».")


def bilan_prevision_precedente(panel_avant, eff_avant, lignes):
    """Compare la prevision qui avait ete faite pour l'annee chargee aux chiffres reels saisis."""
    if panel_avant.annee.max() != lignes.annee.iloc[0] - 1:
        return
    prevu, _ = calculer(panel_avant, eff_avant)
    # une ligne par ancienne province : les taux observes ne sont publies qu'a ce niveau
    prevu = prevu.sort_values("poids", ascending=False).drop_duplicates("pcode_prov_old")
    m = prevu[["pcode_prov_old", "province_old", "prevision", "prevision_bas80", "prevision_haut80"]].merge(
        lignes[["pcode_prov_old", "taux_abandon"]], on="pcode_prov_old")
    ecart = (m.prevision - m.taux_abandon).abs()
    dedans = ((m.taux_abandon >= m.prevision_bas80) & (m.taux_abandon <= m.prevision_haut80)).mean()
    with st.expander(f"Bilan : la prévision faite pour {M.annee_label(int(lignes.annee.iloc[0]))} face aux chiffres "
                     "saisis (45 anciennes provinces)"):
        a, b, c = st.columns(3)
        a.metric("Erreur absolue moyenne", f"{ecart.mean():.1f} points")
        b.metric("Corrélation de rang", f"{spearmanr(m.prevision, m.taux_abandon).correlation:.2f}")
        c.metric("Dans l'intervalle à 80 %", f"{100 * dedans:.0f} %")
        st.dataframe(m.assign(ecart=m.taux_abandon - m.prevision).sort_values("ecart", key=abs, ascending=False)
                     .rename(columns={"province_old": "Province", "prevision": "Prévu", "taux_abandon": "Observé",
                                      "ecart": "Écart", "prevision_bas80": "Bas 80 %",
                                      "prevision_haut80": "Haut 80 %"}).drop(columns="pcode_prov_old"),
                     hide_index=True, width="stretch")


# =============================================================================
# Pages
# =============================================================================
def page_prevision():
    panel, eff47 = donnees_publiees()
    resultat, infos = calculer(panel, eff47)
    st.header(f"Prévision {M.annee_label(infos['annee_prevue'])}")
    officiel = infos["annee_donnees"] <= charger_base()[0].annee.max()
    st.caption(f"À partir des données {M.annee_label(infos['annee_donnees'])} "
               + ("(données officielles)" if officiel else "(année ajoutée par l'administrateur)")
               + " · 47 provinces du découpage en vigueur")
    afficher_prevision(resultat, infos, "publie")


def page_mise_a_jour():
    panel, eff47 = donnees_publiees()
    suivante = int(panel.annee.max()) + 1
    st.header("Mettre à jour une année")
    st.markdown(f"""
Chargez les chiffres d'une nouvelle année scolaire **t** (réels ou estimés) : la plateforme calcule les variables,
réentraîne les modèles avec cette année et affiche immédiatement la prévision **t+1** des 47 provinces.

Dernière année connue : **{M.annee_label(suivante - 1)}**. Année attendue : **{M.annee_label(suivante)}**.
""")

    st.subheader("1. Télécharger le modèle Excel")
    st.markdown(f"""
Le classeur est **pré-rempli avec {M.annee_label(suivante - 1)}** : remplacez les valeurs.
- Feuille **saisie** : les 45 provinces de l'ancien découpage (celui des annuaires DGESS), 12 chiffres chacune.
- Feuille **provinces_scindees** *(facultative)* : l'effectif propre de Djelgodji, Karo-Peli, Dyamongou et
  Gobnangou. Laissée vide, la plateforme reprend les parts de l'année précédente.
- Feuille **notice** : la description de chaque colonne.
""")
    st.dataframe(pd.DataFrame([{"colonne": c, "contenu": lib} for c, (lib, _, _) in M.COLONNES_SAISIE.items()]),
                 hide_index=True)
    st.download_button(f"Télécharger le modèle {M.annee_label(suivante)}", M.creer_modele_excel(panel, eff47, suivante),
                       file_name=f"saisie_{M.annee_label(suivante)}.xlsx")

    st.subheader("2. Charger le fichier rempli")
    fichier = st.file_uploader("Classeur Excel (.xlsx)", type=["xlsx"])
    if fichier is None:
        return
    lignes, lignes47, erreurs, avertissements = M.lire_saisie(fichier, panel, eff47)
    if erreurs:
        st.error(f"Le fichier contient {len(erreurs)} erreur(s) ; rien n'a été calculé.")
        for e in erreurs[:50]:
            st.markdown(f"- {e}")
        return
    for a in avertissements:
        st.warning(a)
    annee = int(lignes.annee.iloc[0])
    st.success(f"Fichier valide : 45 anciennes provinces et 47 provinces en vigueur, année {M.annee_label(annee)}.")

    st.subheader(f"3. Prévision {M.annee_label(annee + 1)}")
    nouveau, nouveau47 = M.ajouter_annee(panel, lignes), M.ajouter_annee(eff47, lignes47)
    resultat, infos = calculer(nouveau, nouveau47)
    bilan_prevision_precedente(panel[panel.annee < annee], eff47[eff47.annee < annee], lignes)
    afficher_prevision(resultat, infos, "simulation")

    st.subheader("4. Publier pour tous les visiteurs")
    attendu = mot_de_passe_admin()
    if attendu is None:
        st.info("Publication désactivée : aucun mot de passe administrateur n'est configuré sur le serveur "
                "(voir DEPLOIEMENT.md). La prévision ci-dessus reste visible dans votre session.")
        return
    saisi = st.text_input("Mot de passe administrateur", type="password")
    if st.button(f"Publier {M.annee_label(annee)} et la prévision {M.annee_label(annee + 1)}"):
        if saisi != attendu:
            st.error("Mot de passe incorrect.")
            return
        for fichier_publie, nouvelles in ((PUBLIE_45, lignes), (PUBLIE_47, lignes47)):
            deja = pd.read_csv(fichier_publie, dtype=str) if fichier_publie.exists() else None
            if deja is not None:
                deja["annee"] = deja.annee.astype(int)
                nouvelles = pd.concat([deja[deja.annee < annee], nouvelles.astype({"annee": int})])
            nouvelles.to_csv(fichier_publie, index=False, encoding="utf-8")
        st.success(f"{M.annee_label(annee)} publiée : la page « Prévision » affiche désormais "
                   f"{M.annee_label(annee + 1)}.")


def page_tableau_de_bord():
    st.caption("Tableau de bord de l'analyse publiée (données officielles 2017-18 à 2024-25).")
    components.html((DONNEES / "tableau_de_bord.html").read_text(encoding="utf-8"), height=1500, scrolling=True)


def page_methode():
    panel, eff47 = donnees_publiees()
    resultat, infos = calculer(panel, eff47)
    st.header("Méthode et sources")
    st.markdown(f"""
### Ce que fait la plateforme
Elle **décrit** la situation de l'année t avec un indice de risque, et **anticipe** l'année t+1 avec deux
modèles : une prévision du taux d'abandon et une probabilité d'alerte. Les deux ne se croisent qu'à la règle de
priorité. Les calculs sont ceux de l'analyse publiée ; la plateforme les rejoue à chaque nouvelle année.

### Unité : les 47 provinces du découpage en vigueur
Les annuaires de la DGESS publient les taux sur les **45 provinces de l'ancien découpage**. Deux d'entre elles ont
été scindées : le **Soum** en Djelgodji et Karo-Peli, la **Tapoa** en Dyamongou et Gobnangou.
- Leurs **effectifs** sont connus par commune (annuaires régionaux de l'INSD) : chaque moitié a son effectif
  propre, et la somme des deux retombe exactement sur le total DGESS. Le CM2 et les nouveaux inscrits au CP1 sont
  répartis selon la part d'effectif de chaque moitié.
- Leurs **taux** (abandon, redoublement, achèvement, scolarisation) ne sont publiés par aucune source à l'échelle
  de la commune : les deux moitiés **héritent des taux de l'ancienne province**. Leur indice et leur prévision
  sont donc presque identiques. Les petits écarts entre deux moitiés viennent seulement de la répartition des
  effectifs, pas d'une information propre. Sur la carte, ces quatre provinces ont un contour pointillé.
- Pour qu'une province scindée ne compte pas double dans l'apprentissage, chaque moitié reçoit un **poids égal à
  sa part d'effectif** (les 43 autres provinces ont un poids de 1).

### Indice de risque de décrochage (IRD)
Trois dimensions, chacune en rang percentile parmi les provinces de l'année :
abandon en cours de cycle (35 %) · exclusion scolaire et non-achèvement (47,5 %) · choc sécuritaire (17,5 %).

### Prévision du taux d'abandon de l'année suivante
Moyenne de deux termes : le **niveau propre de la province** (moyenne de son taux d'abandon passé) et un modèle de
**boosting de gradient** sur six variables, le noyau dit L11 :
""")
    st.dataframe(pd.DataFrame([{"variable": k, "signification": v} for k, v in M.LIBELLES_NOYAU.items()]),
                 hide_index=True, width="stretch")
    corr = infos["correction_intervalle"]
    st.markdown(f"""
Aucune de ces variables n'est dérivée du taux d'abandon. À l'échelle d'une province, le **redoublement** est associé à
*moins* d'abandon l'année suivante : redoubler et abandonner se substituent dans le décompte des flux d'élèves. Ce
signe est mesuré, pas présenté comme une confirmation de la littérature.

**Intervalle à 80 %** : bornes à 10 % et 90 % (boosting quantile), élargies d'une correction mesurée sur la dernière
année connue, séparément pour les provinces stables ({corr['stables']:.1f} points) et en crise
({corr['crise']:.1f} points). La prévision affichée est toujours ramenée dans son intervalle.

### Probabilité d'alerte
Régression logistique sur les mêmes six variables ; l'alerte est un abandon d'au moins 15 % l'année suivante. On
signale autant de provinces que le modèle en attend sur l'année (part bornée entre 5 et 60 %). Cette probabilité est
fiable **comme rang** (qui passe avant qui), moins comme niveau.

### Priorité
P1 / P2 / P3 si l'indice dépasse 70 / 55 / 40, **ou** si la probabilité d'alerte est parmi les plus fortes
(parts 5/45, 12/45 et 20/45 des provinces) ; sinon P4.

### Fiabilité mesurée (analyse publiée, années 2022 à 2024, apprentissage sur les seules années antérieures)
| | Indicateur | Valeur |
|---|---|---|
| Prévision | erreur absolue moyenne | 11,1 points |
| Prévision | corrélation de rang avec l'observé | 0,32 |
| Alerte | aire sous la courbe (AUC) | 0,84 |

À titre de comparaison, le seul niveau historique de la province, sans modèle, obtient 11,2 points d'erreur et 0,33 de
corrélation de rang : le modèle apporte surtout la probabilité d'alerte, et la prévision reste prudente. La
prévision ne porte que sur l'année suivante ; au-delà de deux ans, la précision s'effondre.

### Sources
- DGESS / MENAPLN : annuaires statistiques de l'enseignement primaire (effectifs, taux d'abandon, de redoublement,
  d'achèvement et de scolarisation, écoles).
- INSD : annuaires statistiques régionaux (effectifs par commune), projections de population (6-11 ans).
- CONASUR : personnes déplacées internes.
- COD-AB (OCHA) : limites des 47 provinces, pour la carte.

### Vérification
Sur les données officielles, la plateforme redonne les résultats de l'analyse publiée à 10⁻¹⁴ près : indice des
376 lignes province × année, prévision, intervalle, probabilité et priorité des 47 provinces (script
`verifier_moteur.py`).
""")


def page_administration():
    st.header("Administration")
    attendu = mot_de_passe_admin()
    if not (PUBLIE_45.exists() and PUBLIE_47.exists()):
        st.info("Aucune année ajoutée : la plateforme utilise les données officielles 2017-18 à 2024-25.")
        return
    ajout = pd.read_csv(PUBLIE_45, dtype={"pcode_prov_old": str})
    st.markdown("Années ajoutées : " + ", ".join(M.annee_label(int(a)) for a in sorted(ajout.annee.unique())))
    st.markdown("Pour rendre ces années permanentes, déposez les **deux** fichiers suivants dans le dossier "
                "`donnees/` du dépôt GitHub :")
    st.download_button("Télécharger annees_publiees.csv", PUBLIE_45.read_bytes(), file_name="annees_publiees.csv")
    st.download_button("Télécharger effectifs_47_publies.csv", PUBLIE_47.read_bytes(),
                       file_name="effectifs_47_publies.csv")
    if attendu is None:
        return
    saisi = st.text_input("Mot de passe administrateur", type="password", key="mdp_admin")
    if st.button("Retirer les années ajoutées (revenir aux données officielles)"):
        if saisi == attendu:
            PUBLIE_45.unlink(missing_ok=True)
            PUBLIE_47.unlink(missing_ok=True)
            st.success("Années retirées.")
        else:
            st.error("Mot de passe incorrect.")


# =============================================================================
st.sidebar.title("Décrochage scolaire")
st.sidebar.caption("Primaire · Burkina Faso · 47 provinces")
page = st.sidebar.radio("Page", ["Prévision", "Mettre à jour une année", "Méthode et sources",
                                 "Tableau de bord de l'analyse", "Administration"])
st.sidebar.markdown("---")
st.sidebar.caption("La prévision porte sur l'année scolaire suivant la dernière année chargée. "
                   "Les modèles sont réentraînés à chaque nouvelle année.")

if page == "Prévision":
    page_prevision()
elif page == "Mettre à jour une année":
    page_mise_a_jour()
elif page == "Méthode et sources":
    page_methode()
elif page == "Tableau de bord de l'analyse":
    page_tableau_de_bord()
else:
    page_administration()
