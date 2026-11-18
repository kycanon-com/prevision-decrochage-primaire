# -*- coding: utf-8 -*-
"""
Plateforme de prevision du decrochage scolaire au primaire (Burkina Faso, 47 provinces du decoupage en vigueur).

Deux pages :
  - « Tableau de bord » : publique, une seule page dynamique (carte, chiffres cles, classement, evolution) ;
  - « Administration » : protegee par mot de passe, pour ajouter une annee de donnees.

Lancer en local :  streamlit run app.py
Deploiement     :  voir DEPLOIEMENT.md
"""
import hmac
import json
from io import BytesIO
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from scipy.stats import spearmanr

import carte as C
import moteur as M

ICI = Path(__file__).resolve().parent
FICHIERS_REQUIS = ["panel_base.csv", "effectifs_47.csv", "carte_47.json"]
# les donnees sont normalement dans donnees/ ; on les accepte aussi a la racine du depot
# (cas d'un depot GitHub fait en glissant les fichiers sans leur dossier)
DONNEES = next((d for d in (ICI / "donnees", ICI) if (d / "panel_base.csv").exists()), ICI / "donnees")
PUBLIEES = DONNEES / "annees_publiees_47.csv"          # chiffres des annees ajoutees (une ligne par province, 47)

st.set_page_config(page_title="Décrochage scolaire au primaire · Burkina Faso", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")

ROUGE = "#b2182b"
COULEURS_PRIORITE = {"P1": "#b2182b", "P2": "#ef8a62", "P3": "#fddbc7", "P4": "#d1e5f0"}
NOMS_PRIORITE = {"P1": "Intervention immédiate", "P2": "Surveillance renforcée", "P3": "Vigilance",
                 "P4": "Suivi de routine"}
NOUVELLES = ["Djelgodji", "Karo-Peli", "Dyamongou", "Gobnangou"]

st.markdown("""
<style>
  .block-container {padding-top: 2.6rem; padding-bottom: 2rem; max-width: 1400px;}
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none;}
  div[data-testid="stMetric"] {background: #fafafa; border: 1px solid #ececec; border-left: 4px solid #b2182b;
      border-radius: 6px; padding: 10px 14px;}
  div[data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #555;}
  h1 {font-size: 1.75rem !important; margin-bottom: 0.1rem;}
  .fiche {border: 1px solid #ececec; border-radius: 8px; padding: 14px 16px; background: #fff;}
  .fiche h3 {margin: 0 0 2px 0; font-size: 1.25rem;}
  .pastille {display:inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;
      border: 1px solid #00000022;}
  .fiche table {width: 100%; margin-top: 8px; border-collapse: collapse; font-size: 0.92rem;}
  .fiche td {padding: 3px 0; border-bottom: 1px solid #f0f0f0;}
  .fiche td:last-child {text-align: right; font-weight: 600;}
</style>
""", unsafe_allow_html=True)

MANQUANTS = [f for f in FICHIERS_REQUIS if not (DONNEES / f).exists()]
if MANQUANTS:
    st.error("La plateforme ne trouve pas ses fichiers de données : " + ", ".join(MANQUANTS) + ".")
    st.markdown("""
Ces fichiers doivent se trouver dans un dossier **`donnees`** à côté de `app.py`, dans le dépôt GitHub.

**Pour réparer** : sur github.com, ouvrir le dépôt → *Add file* → *Upload files* → glisser **le dossier `donnees`
lui-même** (depuis le dossier `plateforme` de l'ordinateur) → *Commit changes*. La plateforme redémarre seule en
une à deux minutes.
""")
    st.stop()


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


@st.cache_data
def positions_noms(noms_tuple):
    return C.positions_etiquettes(charger_carte(), dict(noms_tuple))


def donnees_publiees():
    """Historique officiel + annees publiees par l'administrateur (saisies a l'echelle des 47 provinces)."""
    base, eff47 = charger_base()
    propres = pd.DataFrame(columns=["pcode_prov_new"] + M.VALEURS_PROPRES + ["annee"])
    if PUBLIEES.exists():
        ajout = pd.read_csv(PUBLIEES, dtype={"pcode_prov_new": str})
        for annee in sorted(ajout.annee.unique()):
            l45, l47, pr = M.deriver_annee(ajout[ajout.annee == annee], base, eff47)
            base, eff47 = M.ajouter_annee(base, l45), M.ajouter_annee(eff47, l47)
            propres = pd.concat([propres[propres.annee < annee], pr], ignore_index=True)
    return base, eff47, propres


@st.cache_data(show_spinner="Calcul des prévisions…")
def calculer(panel, eff47, propres=None):
    return M.prevoir(panel, eff47, propres)


def mot_de_passe_admin():
    try:
        return st.secrets["MOT_DE_PASSE_ADMIN"]
    except Exception:                       # aucun secret configure : espace administrateur ferme
        return None


def vers_excel(df):
    tampon = BytesIO()
    df.to_excel(tampon, index=False)
    return tampon.getvalue()


def afficher_html(html, hauteur):
    """Affiche un bloc HTML autonome (st.iframe dans les versions recentes de Streamlit, components sinon)."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=hauteur)
    else:
        components.html(html, height=hauteur)


def nombre(v):
    return f"{int(round(v)):,}".replace(",", " ")


def code_priorite(texte):
    return texte[:2]


# =============================================================================
# Carte
# =============================================================================
def couleur_continue(v, vmin, vmax):
    x = 0.0 if vmax == vmin else float(np.clip((v - vmin) / (vmax - vmin), 0, 1))
    debut, fin = np.array([255, 237, 160]), np.array([128, 0, 38])
    r, g, b = (debut + x * (fin - debut)).astype(int)
    return f"rgb({r},{g},{b})"


def agreger_regions(resultat):
    """Une ligne par region (17) : moyennes ponderees par les effectifs, effectifs cumules, provinces par priorite."""
    r = resultat.assign(w=resultat.effectif_propre.clip(lower=1), p=resultat.priorite.map(code_priorite))
    lignes = []
    for nom, g in r.groupby("region_new"):
        ligne = {"region_new": nom, "provinces": len(g), "effectif": g.effectif_propre.sum(),
                 "eleves_decrocheurs_prevus": g.eleves_decrocheurs_prevus.sum(),
                 "en_alerte": int(g.signalee_alerte.sum()), "P1": int((g.p == "P1").sum()),
                 "P2": int((g.p == "P2").sum()), "P3": int((g.p == "P3").sum())}
        for c in ("IRD", "taux_abandon", "prevision", "prevision_bas80", "prevision_haut80"):
            ligne[c] = float(np.average(g[c], weights=g.w))
        lignes.append(ligne)
    reg = pd.DataFrame(lignes)
    s1, s2, s3 = M.SEUILS_IRD
    reg["priorite"] = reg.IRD.map(lambda v: "P1" if v >= s1 else "P2" if v >= s2 else "P3" if v >= s3 else "P4")
    reg["rang_IRD"] = reg.IRD.rank(ascending=False, method="min").astype(int)
    return reg.sort_values("rang_IRD").reset_index(drop=True)


@st.cache_data
def positions_regions(noms_tuple):
    carte = charger_carte()
    pseudo = {"largeur": carte["largeur"], "hauteur": carte["hauteur"],
              "provinces": {k: {"path": v["path"]} for k, v in carte["regions"].items()}}
    return C.positions_etiquettes(pseudo, dict(noms_tuple))


def carte_svg(resultat, mode, visibles, choisie, niveau="Provinces", regions=None):
    """Carte : au niveau des provinces (47 noms) ou des regions (17 noms). Les limites de region sont toujours tracees ;
    ce qui sort du filtre est palie."""
    carte = charger_carte()
    r = resultat.set_index("pcode_prov_new")
    par_region = niveau == "Régions"
    if par_region:
        R = regions.set_index("region_new")
        table, cle_de = R, r.region_new.to_dict()
        visibles_cles = set(r.loc[list(visibles)].region_new)
    else:
        table, cle_de, visibles_cles = r, {k: k for k in r.index}, set(visibles)
    if mode == "Priorité":
        couleur = {k: COULEURS_PRIORITE[code_priorite(table.at[k, "priorite"])] for k in table.index}
        legende = "".join(f'<span class="pt" style="background:{COULEURS_PRIORITE[p]}"></span>{NOMS_PRIORITE[p]}'
                          for p in COULEURS_PRIORITE)
    else:
        col = "prevision" if mode.startswith("Abandon") else "IRD"
        vmin, vmax = table[col].min(), table[col].max()
        couleur = {k: couleur_continue(table.at[k, col], vmin, vmax) for k in table.index}
        legende = (f'{vmin:.0f} {"%" if col == "prevision" else ""}<span class="degrade"></span>'
                   f'{vmax:.0f} {"%" if col == "prevision" else ""}')
    legende += ('<span class="trait"></span>pointillés : nouvelle province (taux de la province d\'origine)'
                if not par_region else "")
    legende += '<span class="epais"></span>limite de région'
    formes, textes = [], []
    for code, geo in carte["provinces"].items():
        if code not in r.index:
            continue
        x = r.loc[code]
        cle = cle_de[code]
        if par_region:
            g = table.loc[cle]
            bulle = (f"Région {cle} ({int(g.provinces)} provinces)\n{NOMS_PRIORITE[g.priorite]}\n"
                     f"Indice de risque moyen : {g.IRD:.0f} / 100 (rang {g.rang_IRD} sur {len(table)})\n"
                     f"Abandon actuel : {g.taux_abandon:.1f} %\nAbandon prévu : {g.prevision:.1f} %\n"
                     f"Provinces P1 / P2 / P3 : {g.P1} / {g.P2} / {g.P3}\n"
                     f"Élèves susceptibles d'abandonner : {nombre(g.eleves_decrocheurs_prevus)}")
            trait = 'stroke="#fff" stroke-width="0.3"'
        else:
            bulle = (f"{x.province_new} ({x.region_new})\n{NOMS_PRIORITE[code_priorite(x.priorite)]}\n"
                     f"Indice de risque : {x.IRD:.0f} / 100 (rang {x.rang_IRD} sur 47)\n"
                     f"Abandon actuel : {x.taux_abandon:.1f} %\n"
                     f"Abandon prévu : {x.prevision:.1f} % (entre {x.prevision_bas80:.1f} et {x.prevision_haut80:.1f})\n"
                     f"Élèves susceptibles d'abandonner : {nombre(x.eleves_decrocheurs_prevus)}")
            if code == choisie:
                trait = 'stroke="#000" stroke-width="2.6"'
            elif x.scindee:
                trait = 'stroke="#222" stroke-width="1.1" stroke-dasharray="3,2"'
            else:
                trait = 'stroke="#666" stroke-width="0.45"'
        actif = cle in visibles_cles if par_region else code in visibles
        formes.append(f'<path d="{geo["path"]}" fill="{couleur[cle]}" {trait} opacity="{1 if actif else 0.22}">'
                      f'<title>{bulle}</title></path>')
    contours = []
    for nom, geo in carte["regions"].items():
        choisi = par_region and nom == choisie
        contours.append(f'<path d="{geo["path"]}" fill="none" stroke="#111" stroke-width="{3 if choisi else 1.5}" '
                        f'stroke-linejoin="round" pointer-events="none"/>')
    if par_region:
        noms_r = {k: k for k in carte["regions"]}
        pos = positions_regions(tuple(sorted(noms_r.items())))
        etiquettes = noms_r
        taille = 12.5
    else:
        etiquettes = {k: r.at[k, "province_new"] for k in r.index}
        pos = positions_noms(tuple(sorted(etiquettes.items())))
        taille = C.FS
    for code, (tx, ty, ax, ay, deplace) in pos.items():
        if deplace:
            textes.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="#222" '
                          f'stroke-width="0.5"/><circle cx="{ax:.1f}" cy="{ay:.1f}" r="1.3" fill="#222"/>')
        if par_region:
            actif, gras = code in visibles_cles, (code == choisie)
        else:
            actif, gras = code in visibles, (code == choisie)
        textes.append(f'<text x="{tx:.1f}" y="{ty + 3:.1f}" text-anchor="middle" font-size="{taille}" '
                      f'font-weight="{700 if (gras or par_region) else 600}" opacity="{1 if actif else 0.5}">'
                      f'{etiquettes[code]}</text>')
    return f"""
<style>
  body {{margin:0; font-family: Arial, Helvetica, sans-serif; font-size: 13px; color:#222}}
  svg text {{fill:#000; stroke:#fff; stroke-width:1.5px; paint-order:stroke; pointer-events:none;
            font-family: Arial, Helvetica, sans-serif; text-rendering: geometricPrecision;}}
  svg path:hover {{stroke:#000; stroke-width:1.8px}}
  .pt {{display:inline-block; width:12px; height:12px; border:1px solid #888; margin:0 5px 0 14px; vertical-align:-1px}}
  .degrade {{display:inline-block; width:150px; height:11px; vertical-align:middle; margin:0 6px;
            background:linear-gradient(90deg,rgb(255,237,160),rgb(128,0,38))}}
  .trait {{display:inline-block; width:22px; border-top:2px dashed #222; vertical-align:middle; margin:0 6px 0 18px}}
  .epais {{display:inline-block; width:22px; border-top:3px solid #111; vertical-align:middle; margin:0 6px 0 18px}}
</style>
<svg viewBox="0 0 {carte["largeur"]} {carte["hauteur"]}" style="width:100%;max-height:640px">
{"".join(formes)}{"".join(contours)}{"".join(textes)}</svg>
<div style="margin-top:4px;line-height:1.9">{legende}</div>"""


def fiche_region(g, resultat, infos):
    p = g.priorite
    t, t1 = infos["annee_donnees"], infos["annee_prevue"]
    lignes = [
        (f"Indice de risque moyen {M.annee_label(t)}", f"{g.IRD:.0f} / 100 (rang {g.rang_IRD} sur 17)"),
        (f"Abandon {M.annee_label(t)}", f"{g.taux_abandon:.1f} %"),
        (f"Abandon prévu {M.annee_label(t1)}", f"{g.prevision:.1f} %"),
        ("Provinces P1 / P2 / P3", f"{g.P1} / {g.P2} / {g.P3}"),
        ("Provinces en alerte", f"{g.en_alerte} sur {g.provinces}"),
        ("Élèves dans le primaire", nombre(g.effectif)),
        (f"Élèves susceptibles d'abandonner {M.annee_label(t1)}", nombre(g.eleves_decrocheurs_prevus)),
    ]
    corps = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in lignes)
    provs = resultat[resultat.region_new == g.region_new].sort_values("IRD", ascending=False)
    liste = ", ".join(f"{x.province_new} ({code_priorite(x.priorite)})" for x in provs.itertuples())
    st.markdown(f'<div class="fiche"><h3>Région {g.region_new}</h3><span class="pastille" '
                f'style="background:{COULEURS_PRIORITE[p]};color:{"#fff" if p == "P1" else "#222"}">'
                f'{NOMS_PRIORITE[p]}</span><table>{corps}</table>'
                f'<p style="font-size:0.82rem;color:#555;margin:10px 0 0 0">Provinces : {liste}.</p></div>',
                unsafe_allow_html=True)


def evolution_regions(infos, regions, resultat, noms):
    """Abandon observe par region (moyenne ponderee par les effectifs), puis prevision de l'annee suivante."""
    h = infos["historique"].merge(resultat[["pcode_prov_new", "region_new"]], on="pcode_prov_new")
    h = h[h.region_new.isin(noms)]
    h = (h.assign(w=h.effectif_propre.clip(lower=1)).groupby(["region_new", "annee"])
         .apply(lambda g: np.average(g.taux_abandon, weights=g.w), include_groups=False)
         .rename("taux_abandon").reset_index())
    h["periode"] = h.annee.map(M.annee_label)
    t1 = M.annee_label(infos["annee_prevue"])
    prev = regions[regions.region_new.isin(noms)][["region_new", "prevision", "prevision_bas80",
                                                   "prevision_haut80"]].assign(periode=t1)
    ordre = [M.annee_label(a) for a in sorted(h.annee.unique())] + [t1]
    x = alt.X("periode:N", sort=ordre, title=None, axis=alt.Axis(labelAngle=0))
    couleur = alt.Color("region_new:N", title=None, legend=alt.Legend(orient="bottom"))
    ligne = alt.Chart(h).mark_line(point=True, strokeWidth=2).encode(
        x=x, y=alt.Y("taux_abandon:Q", title="Taux d'abandon (%)", scale=alt.Scale(zero=True)), color=couleur,
        tooltip=[alt.Tooltip("region_new", title="Région"), alt.Tooltip("periode", title="Année"),
                 alt.Tooltip("taux_abandon", title="Abandon (%)", format=".1f")])
    barre = alt.Chart(prev).mark_rule(strokeWidth=4, opacity=0.35).encode(
        x=x, y="prevision_bas80:Q", y2="prevision_haut80:Q", color=couleur)
    point = alt.Chart(prev).mark_point(shape="diamond", size=170, filled=True).encode(
        x=x, y="prevision:Q", color=couleur,
        tooltip=[alt.Tooltip("region_new", title="Région"), alt.Tooltip("prevision", title="Abandon prévu (%)", format=".1f")])
    st.altair_chart((barre + ligne + point).properties(height=360), width="stretch")
    st.caption("Moyenne régionale pondérée par les effectifs. Le losange est la prévision de l'année suivante ; "
               "le trait vertical clair est la fourchette à 80 %.")


def fiche_province(x, infos):
    p = code_priorite(x.priorite)
    t, t1 = infos["annee_donnees"], infos["annee_prevue"]
    lignes = [
        (f"Indice de risque {M.annee_label(t)}", f"{x.IRD:.0f} / 100 (rang {x.rang_IRD} sur 47)"),
        (f"Abandon {M.annee_label(t)}", f"{x.taux_abandon:.1f} %"),
        (f"Abandon prévu {M.annee_label(t1)}", f"{x.prevision:.1f} %"),
        ("Fourchette probable", f"{x.prevision_bas80:.1f} à {x.prevision_haut80:.1f} %"),
        ("Alerte (abandon ≥ 15 %)", "oui" if x.signalee_alerte else "non"),
        ("Élèves dans le primaire", nombre(x.effectif_propre)),
        (f"Élèves susceptibles d'abandonner {M.annee_label(t1)}", nombre(x.eleves_decrocheurs_prevus)),
    ]
    corps = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in lignes)
    note = ""
    if x.scindee:
        note = (f'<p style="font-size:0.82rem;color:#555;margin:10px 0 0 0">Province créée à partir de '
                f'{x.province_old}. Ses effectifs lui sont propres ; ses taux sont, pour l\'instant, ceux de '
                f'{x.province_old}, faute de statistiques publiées par commune.</p>')
    st.markdown(f'<div class="fiche"><h3>{x.province_new}</h3><span style="color:#666">{x.region_new}</span> '
                f'&nbsp; <span class="pastille" style="background:{COULEURS_PRIORITE[p]};'
                f'color:{"#fff" if p == "P1" else "#222"}">{NOMS_PRIORITE[p]}</span>'
                f'<table>{corps}</table>{note}</div>', unsafe_allow_html=True)


def graphique_evolution(infos, resultat, codes):
    """Abandon observé année par année, puis prévision de l'année suivante avec sa fourchette."""
    h = infos["historique"][infos["historique"].pcode_prov_new.isin(codes)].merge(
        resultat[["pcode_prov_new", "province_new"]], on="pcode_prov_new")
    h = h.assign(periode=h.annee.map(M.annee_label))
    t1 = M.annee_label(infos["annee_prevue"])
    prev = resultat[resultat.pcode_prov_new.isin(codes)][["province_new", "prevision", "prevision_bas80",
                                                          "prevision_haut80"]].assign(periode=t1)
    ordre = [M.annee_label(a) for a in sorted(h.annee.unique())] + [t1]
    x = alt.X("periode:N", sort=ordre, title=None, axis=alt.Axis(labelAngle=0))
    couleur = alt.Color("province_new:N", title=None, legend=alt.Legend(orient="bottom"))
    ligne = alt.Chart(h).mark_line(point=True, strokeWidth=2).encode(
        x=x, y=alt.Y("taux_abandon:Q", title="Taux d'abandon (%)", scale=alt.Scale(zero=True)), color=couleur,
        tooltip=[alt.Tooltip("province_new", title="Province"), alt.Tooltip("periode", title="Année"),
                 alt.Tooltip("taux_abandon", title="Abandon (%)", format=".1f")])
    barre = alt.Chart(prev).mark_rule(strokeWidth=4, opacity=0.35).encode(
        x=x, y="prevision_bas80:Q", y2="prevision_haut80:Q", color=couleur)
    point = alt.Chart(prev).mark_point(shape="diamond", size=170, filled=True).encode(
        x=x, y="prevision:Q", color=couleur,
        tooltip=[alt.Tooltip("province_new", title="Province"), alt.Tooltip("periode", title="Année prévue"),
                 alt.Tooltip("prevision", title="Abandon prévu (%)", format=".1f"),
                 alt.Tooltip("prevision_bas80", title="Bas (%)", format=".1f"),
                 alt.Tooltip("prevision_haut80", title="Haut (%)", format=".1f")])
    st.altair_chart((barre + ligne + point).properties(height=360), width="stretch")
    st.caption("Le losange est la prévision de l'année suivante ; le trait vertical clair est la fourchette dans "
               "laquelle l'abandon a 8 chances sur 10 de se situer.")


def tableau_dynamique(resultat, infos, visibles_df):
    t1 = M.annee_label(infos["annee_prevue"])
    colonnes = ["rang_IRD", "province_new", "region_new", "priorite", "IRD", "taux_abandon", "prevision",
                "prevision_bas80", "prevision_haut80", "proba_alerte", "eleves_decrocheurs_prevus"]
    tab = visibles_df[colonnes].copy()
    tab["priorite"] = tab.priorite.map(lambda s: NOMS_PRIORITE[code_priorite(s)])
    tab["proba_alerte"] = 100 * tab.proba_alerte
    noms = {"rang_IRD": "Rang", "province_new": "Province", "region_new": "Région", "priorite": "Priorité",
            "IRD": "Indice de risque", "taux_abandon": "Abandon actuel (%)",
            "prevision": f"Abandon prévu {t1} (%)", "prevision_bas80": "Fourchette basse (%)",
            "prevision_haut80": "Fourchette haute (%)", "proba_alerte": "Risque d'alerte",
            "eleves_decrocheurs_prevus": f"Élèves susceptibles d'abandonner {t1}"}
    cfg = {noms[c]: st.column_config.NumberColumn(format="%.1f")
           for c in ["IRD", "taux_abandon", "prevision", "prevision_bas80", "prevision_haut80"]}
    cfg[noms["proba_alerte"]] = st.column_config.ProgressColumn(format="%.0f %%", min_value=0, max_value=100)
    cfg[noms["eleves_decrocheurs_prevus"]] = st.column_config.NumberColumn(format="%d")
    st.dataframe(tab.rename(columns=noms), hide_index=True, width="stretch", height=430, column_config=cfg)


def rendu_dynamique(resultat, infos, cle):
    """Page unique : niveau (provinces ou regions), filtres, chiffres cles, carte, fiche, classement, evolution."""
    t, t1 = infos["annee_donnees"], infos["annee_prevue"]
    regions_df = agreger_regions(resultat)

    niveau = st.radio("Niveau d'affichage", ["Provinces", "Régions"], horizontal=True, key=f"niv_{cle}",
                      help="Les régions (17) regroupent les provinces (47) : valeurs moyennes pondérées par les effectifs.")
    par_region = niveau == "Régions"
    f1, f2, f3 = st.columns([2, 2, 3])
    regions = sorted(resultat.region_new.unique())
    choix_regions = f1.multiselect("Régions", regions, placeholder="Toutes les régions", key=f"reg_{cle}")
    choix_prio = f2.multiselect("Niveaux de priorité" + (" (régionale)" if par_region else ""),
                                [NOMS_PRIORITE[p] for p in NOMS_PRIORITE], placeholder="Tous les niveaux",
                                key=f"prio_{cle}")
    mode = f3.radio("Colorer la carte selon", ["Priorité", f"Abandon prévu {M.annee_label(t1)}",
                                               f"Indice de risque {M.annee_label(t)}"],
                    horizontal=True, key=f"mode_{cle}")
    inv = {v: k for k, v in NOMS_PRIORITE.items()}

    masque = pd.Series(True, index=resultat.index)
    if choix_regions:
        masque &= resultat.region_new.isin(choix_regions)
    if choix_prio:
        if par_region:
            ok = set(regions_df[regions_df.priorite.isin([inv[c] for c in choix_prio])].region_new)
            masque &= resultat.region_new.isin(ok)
        else:
            masque &= resultat.priorite.map(code_priorite).isin([inv[c] for c in choix_prio])
    vis = resultat[masque]
    if vis.empty:
        st.warning("Aucune province ne correspond à ces filtres.")
        return
    regions_vis = regions_df[regions_df.region_new.isin(set(vis.region_new))]

    # chiffres cles : calcules sur la selection
    n = vis.priorite.map(code_priorite).value_counts()
    taux_moyen = np.average(vis.prevision, weights=vis.effectif_propre.clip(lower=1))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Provinces en priorité 1", int(n.get("P1", 0)), help="Intervention immédiate recommandée.")
    k2.metric(f"Abandon moyen prévu {M.annee_label(t1)}", f"{taux_moyen:.1f} %",
              help="Moyenne de la sélection, pondérée par le nombre d'élèves.")
    k3.metric("Élèves susceptibles d'abandonner", nombre(vis.eleves_decrocheurs_prevus.sum()),
              help=f"Estimation pour l'année {M.annee_label(t1)}, dans la sélection.")
    k4.metric("Provinces en alerte", f"{int(vis.signalee_alerte.sum())} sur {len(vis)}",
              help="Provinces où l'abandon risque de dépasser 15 %.")

    gauche, droite = st.columns([6, 3], gap="large")
    with droite:
        if par_region:
            options = ["Aucune (voir le classement)"] + sorted(regions_vis.region_new)
            choix = st.selectbox("Voir le détail d'une région", options, key=f"regsel_{cle}")
            if choix == options[0]:
                st.markdown("**Les régions les plus exposées**")
                top = regions_vis.head(10)[["region_new", "priorite", "IRD", "prevision"]].copy()
                top["priorite"] = top.priorite.map(NOMS_PRIORITE)
                st.dataframe(top.rename(columns={"region_new": "Région", "priorite": "Priorité", "IRD": "Indice",
                                                 "prevision": "Abandon prévu (%)"}), hide_index=True, width="stretch",
                             column_config={"Indice": st.column_config.NumberColumn(format="%.0f"),
                                            "Abandon prévu (%)": st.column_config.NumberColumn(format="%.1f")})
                st.caption("Survolez la carte pour lire les chiffres d'une région, ou choisissez-la ci-dessus.")
                choisie = None
            else:
                fiche_region(regions_vis[regions_vis.region_new == choix].iloc[0], resultat, infos)
                choisie = choix
        else:
            options = ["Aucune (voir le classement)"] + sorted(vis.province_new)
            province = st.selectbox("Voir le détail d'une province", options, key=f"prov_{cle}")
            if province == options[0]:
                st.markdown("**Les 10 provinces les plus exposées**")
                top = vis.head(10)[["province_new", "priorite", "IRD", "prevision"]].copy()
                top["priorite"] = top.priorite.map(lambda s: NOMS_PRIORITE[code_priorite(s)])
                st.dataframe(top.rename(columns={"province_new": "Province", "priorite": "Priorité",
                                                 "IRD": "Indice", "prevision": "Abandon prévu (%)"}),
                             hide_index=True, width="stretch",
                             column_config={"Indice": st.column_config.NumberColumn(format="%.0f"),
                                            "Abandon prévu (%)": st.column_config.NumberColumn(format="%.1f")})
                st.caption("Survolez la carte pour lire les chiffres d'une province, ou choisissez-la ci-dessus.")
                choisie = None
            else:
                fiche_province(vis[vis.province_new == province].iloc[0], infos)
                choisie = vis[vis.province_new == province].pcode_prov_new.iloc[0]
    with gauche:
        afficher_html(carte_svg(resultat, mode, set(vis.pcode_prov_new), choisie, niveau, regions_df), 760)

    onglets = st.tabs([f"Classement des {'régions' if par_region else 'provinces'}", "Évolution de l'abandon",
                       "Élèves par région"])
    with onglets[0]:
        if par_region:
            tab = regions_vis[["rang_IRD", "region_new", "priorite", "IRD", "taux_abandon", "prevision",
                               "provinces", "P1", "P2", "P3", "eleves_decrocheurs_prevus"]].copy()
            tab["priorite"] = tab.priorite.map(NOMS_PRIORITE)
            noms_c = {"rang_IRD": "Rang", "region_new": "Région", "priorite": "Priorité", "IRD": "Indice de risque",
                      "taux_abandon": "Abandon actuel (%)", "prevision": f"Abandon prévu {M.annee_label(t1)} (%)",
                      "provinces": "Provinces", "P1": "P1", "P2": "P2", "P3": "P3",
                      "eleves_decrocheurs_prevus": f"Élèves susceptibles d'abandonner {M.annee_label(t1)}"}
            cfg = {noms_c[c]: st.column_config.NumberColumn(format="%.1f") for c in ("IRD", "taux_abandon", "prevision")}
            cfg[noms_c["eleves_decrocheurs_prevus"]] = st.column_config.NumberColumn(format="%d")
            st.dataframe(tab.rename(columns=noms_c), hide_index=True, width="stretch", column_config=cfg)
            st.caption("Moyennes régionales pondérées par les effectifs. La priorité régionale applique les seuils "
                       "d'indice (70, 55, 40) à l'indice moyen de la région.")
            st.download_button("Télécharger le tableau (Excel)", vers_excel(regions_df), key=f"dlr_{cle}",
                               file_name=f"regions_{M.annee_label(t1)}.xlsx")
        else:
            tableau_dynamique(resultat, infos, vis)
            st.download_button("Télécharger le tableau (Excel)", vers_excel(resultat), key=f"dl_{cle}",
                               file_name=f"prevision_{M.annee_label(t1)}.xlsx")
    with onglets[1]:
        if par_region:
            defaut = [choisie] if choisie else list(regions_vis.head(3).region_new)
            sel = st.multiselect("Régions à comparer", list(regions_vis.region_new), default=defaut,
                                 max_selections=8, key=f"evor_{cle}_{choisie}")
            if sel:
                evolution_regions(infos, regions_df, resultat, sel)
            else:
                st.info("Choisissez au moins une région.")
        else:
            defaut = [choisie] if choisie else list(vis.head(3).pcode_prov_new)
            noms = dict(zip(vis.pcode_prov_new, vis.province_new))
            sel = st.multiselect("Provinces à comparer", list(noms), default=defaut, format_func=noms.get,
                                 max_selections=8, key=f"evo_{cle}_{choisie}")
            if sel:
                graphique_evolution(infos, resultat, sel)
            else:
                st.info("Choisissez au moins une province.")
    with onglets[2]:
        reg = regions_vis[["region_new", "eleves_decrocheurs_prevus", "provinces"]].rename(
            columns={"eleves_decrocheurs_prevus": "eleves"}).sort_values("eleves", ascending=False)
        graphe = alt.Chart(reg).mark_bar(color=ROUGE).encode(
            y=alt.Y("region_new:N", sort="-x", title=None),
            x=alt.X("eleves:Q", title=f"Élèves susceptibles d'abandonner en {M.annee_label(t1)}"),
            tooltip=[alt.Tooltip("region_new", title="Région"), alt.Tooltip("provinces", title="Provinces"),
                     alt.Tooltip("eleves", title="Élèves", format=",.0f")])
        st.altair_chart(graphe.properties(height=max(220, 26 * len(reg))), width="stretch")

    nouv = vis[vis.province_new.isin(NOUVELLES)]
    if len(nouv):
        with st.expander("Les quatre nouvelles provinces : Djelgodji, Karo-Peli, Dyamongou, Gobnangou"):
            st.markdown("Ces provinces ont leurs propres effectifs, donc leurs propres volumes d'élèves. Leurs taux "
                        "sont pour l'instant ceux de la province d'origine (Soum, Tapoa), les statistiques par commune "
                        "n'étant pas encore publiées. Dès que l'administrateur charge de nouvelles données, leurs "
                        "chiffres propres s'affichent ici.")
            st.dataframe(nouv[["province_new", "province_old", "effectif_propre", "taux_abandon", "prevision",
                               "eleves_decrocheurs_prevus"]].rename(columns={
                                   "province_new": "Province", "province_old": "Province d'origine",
                                   "effectif_propre": "Élèves", "taux_abandon": "Abandon actuel (%)",
                                   "prevision": "Abandon prévu (%)",
                                   "eleves_decrocheurs_prevus": "Élèves susceptibles d'abandonner"}),
                         hide_index=True, width="stretch",
                         column_config={"Abandon actuel (%)": st.column_config.NumberColumn(format="%.1f"),
                                        "Abandon prévu (%)": st.column_config.NumberColumn(format="%.1f"),
                                        "Élèves": st.column_config.NumberColumn(format="%d"),
                                        "Élèves susceptibles d'abandonner": st.column_config.NumberColumn(format="%d")})


def page_tableau_de_bord():
    panel, eff47, propres = donnees_publiees()
    resultat, infos = calculer(panel, eff47, propres)
    t, t1 = infos["annee_donnees"], infos["annee_prevue"]
    st.title("Décrochage scolaire au primaire")
    st.markdown(f"**Burkina Faso · 47 provinces** — situation {M.annee_label(t)} et prévision "
                f"{M.annee_label(t1)}. Filtrez par région ou par niveau de priorité : les chiffres, la carte et les "
                "graphiques suivent.")
    rendu_dynamique(resultat, infos, "public")
    st.caption("Sources : DGESS / MENAPLN, INSD, CONASUR. Une prévision est une estimation : la fourchette indique "
               "la marge d'incertitude.")


# =============================================================================
# Administration (protegee)
# =============================================================================
def bilan_prevision_precedente(panel_avant, eff_avant, propres_avant, lignes):
    """Compare la prevision qui avait ete faite pour l'annee chargee aux chiffres reels saisis."""
    if panel_avant.annee.max() != lignes.annee.iloc[0] - 1:
        return
    prevu, _ = calculer(panel_avant, eff_avant, propres_avant)
    # une ligne par ancienne province : les taux observes ne sont publies qu'a ce niveau
    prevu = prevu.sort_values("poids", ascending=False).drop_duplicates("pcode_prov_old")
    m = prevu[["pcode_prov_old", "province_old", "prevision", "prevision_bas80", "prevision_haut80"]].merge(
        lignes[["pcode_prov_old", "taux_abandon"]], on="pcode_prov_old")
    ecart = (m.prevision - m.taux_abandon).abs()
    dedans = ((m.taux_abandon >= m.prevision_bas80) & (m.taux_abandon <= m.prevision_haut80)).mean()
    with st.expander(f"Bilan : la prévision faite pour {M.annee_label(int(lignes.annee.iloc[0]))} face aux chiffres "
                     "saisis"):
        a, b, c = st.columns(3)
        a.metric("Erreur moyenne", f"{ecart.mean():.1f} points")
        b.metric("Corrélation de rang", f"{spearmanr(m.prevision, m.taux_abandon).correlation:.2f}")
        c.metric("Dans la fourchette", f"{100 * dedans:.0f} %")
        st.dataframe(m.assign(ecart=m.taux_abandon - m.prevision).sort_values("ecart", key=abs, ascending=False)
                     .rename(columns={"province_old": "Province", "prevision": "Prévu", "taux_abandon": "Observé",
                                      "ecart": "Écart", "prevision_bas80": "Bas", "prevision_haut80": "Haut"})
                     .drop(columns="pcode_prov_old"), hide_index=True, width="stretch")


def connexion_admin():
    """Vrai si l'administrateur est connecté ; sinon affiche le formulaire de connexion."""
    if st.session_state.get("admin_ok"):
        return True
    attendu = mot_de_passe_admin()
    if attendu is None:
        st.info("L'espace administrateur n'est pas activé : aucun mot de passe n'est configuré sur le serveur "
                "(voir DEPLOIEMENT.md).")
        return False
    with st.form("connexion_admin"):
        saisi = st.text_input("Mot de passe administrateur", type="password")
        envoye = st.form_submit_button("Se connecter")
    if envoye:
        if hmac.compare_digest(saisi.encode(), str(attendu).encode()):
            st.session_state["admin_ok"] = True
            st.rerun()
        st.error("Mot de passe incorrect.")
    return False


def admin_ajouter_annee():
    panel, eff47, propres = donnees_publiees()
    suivante = int(panel.annee.max()) + 1
    st.markdown(f"Dernière année en ligne : **{M.annee_label(suivante - 1)}**. Année à ajouter : "
                f"**{M.annee_label(suivante)}**. La plateforme réajuste alors tous les modèles sur l'ensemble des années "
                f"et recalcule la prévision {M.annee_label(suivante + 1)} pour les 47 provinces.")

    st.subheader("1. Télécharger le modèle Excel")
    st.markdown(f"""
Le classeur est pré-rempli avec {M.annee_label(suivante - 1)} : remplacez les valeurs par celles de la nouvelle année.
- Feuille **saisie** : **une ligne par province du découpage en vigueur (47)**, 12 chiffres chacune, y compris
  Djelgodji, Karo-Peli, Dyamongou et Gobnangou, avec leurs chiffres propres dès qu'ils sont publiés. Si les deux
  provinces d'une même origine ont exactement les mêmes taux, la plateforme leur applique ceux de la province d'origine.
- Feuille **notice** : la description de chaque colonne.
""")
    st.download_button(f"Télécharger le modèle {M.annee_label(suivante)}",
                       M.creer_modele_excel(panel, eff47, suivante, propres), file_name=f"saisie_{M.annee_label(suivante)}.xlsx")

    st.subheader("2. Charger le fichier rempli")
    fichier = st.file_uploader("Classeur Excel (.xlsx)", type=["xlsx"])
    if fichier is None:
        return
    saisie47, erreurs, avertissements = M.lire_saisie(fichier, panel, eff47, propres)
    if erreurs:
        st.error(f"Le fichier contient {len(erreurs)} erreur(s) ; rien n'a été calculé.")
        for e in erreurs[:50]:
            st.markdown(f"- {e}")
        return
    for a in avertissements:
        st.warning(a)
    annee = int(saisie47.annee.iloc[0])
    lignes, lignes47, nouveaux_propres = M.deriver_annee(saisie47, panel, eff47)
    st.success(f"Fichier valide : 47 provinces, année {M.annee_label(annee)}."
               + (f" {len(nouveaux_propres)} province(s) issues de scissions ont des taux propres."
                  if len(nouveaux_propres) else " Les provinces issues de scissions gardent les taux de leur province d'origine."))

    st.subheader(f"3. Aperçu de la prévision {M.annee_label(annee + 1)}")
    st.caption("Cet aperçu n'est visible que de vous tant que vous n'avez pas publié.")
    nouveau, nouveau47 = M.ajouter_annee(panel, lignes), M.ajouter_annee(eff47, lignes47)
    nouv_propres = pd.concat([propres[propres.annee.astype(int) < annee], nouveaux_propres], ignore_index=True)
    resultat, infos = calculer(nouveau, nouveau47, nouv_propres)
    bilan_prevision_precedente(panel[panel.annee < annee], eff47[eff47.annee < annee],
                               propres[propres.annee.astype(int) < annee], lignes)
    rendu_dynamique(resultat, infos, "apercu")

    st.subheader("4. Publier pour tous les visiteurs")
    if st.button(f"Publier {M.annee_label(annee)} et la prévision {M.annee_label(annee + 1)}", type="primary"):
        nouvelles = saisie47.astype({"annee": int})
        if PUBLIEES.exists():
            deja = pd.read_csv(PUBLIEES, dtype={"pcode_prov_new": str})
            nouvelles = pd.concat([deja[deja.annee < annee], nouvelles], ignore_index=True)
        nouvelles.to_csv(PUBLIEES, index=False, encoding="utf-8")
        st.success(f"{M.annee_label(annee)} publiée : le tableau de bord affiche désormais la prévision "
                   f"{M.annee_label(annee + 1)}.")
        st.caption("Pour rendre cette année permanente après un redémarrage du serveur, déposez le fichier de "
                   "l'onglet « Années publiées » dans le dossier `donnees/` du dépôt GitHub.")


def admin_annees_publiees():
    if not PUBLIEES.exists():
        st.info("Aucune année n'a été ajoutée : la plateforme utilise les données officielles "
                f"{M.annee_label(int(charger_base()[0].annee.min()))} à {M.annee_label(int(charger_base()[0].annee.max()))}.")
        return
    ajout = pd.read_csv(PUBLIEES, dtype={"pcode_prov_new": str})
    st.markdown("Années ajoutées : **" + ", ".join(M.annee_label(int(a)) for a in sorted(ajout.annee.unique())) + "**")
    st.markdown("Pour rendre ces années permanentes, déposez le fichier suivant dans le dossier `donnees/` du dépôt GitHub :")
    st.download_button("Télécharger annees_publiees_47.csv", PUBLIEES.read_bytes(), file_name="annees_publiees_47.csv")
    st.divider()
    if st.button("Retirer les années ajoutées (revenir aux données officielles)"):
        PUBLIEES.unlink(missing_ok=True)
        st.success("Années retirées.")
        st.rerun()


def page_administration():
    st.title("Espace administrateur")
    if not connexion_admin():
        return
    colonne, _ = st.columns([1, 5])
    if colonne.button("Se déconnecter"):
        st.session_state["admin_ok"] = False
        st.rerun()
    onglets = st.tabs(["Ajouter une année", "Années publiées"])
    with onglets[0]:
        admin_ajouter_annee()
    with onglets[1]:
        admin_annees_publiees()


# =============================================================================
pages = [st.Page(page_tableau_de_bord, title="Tableau de bord", icon=":material/dashboard:", default=True,
                 url_path="tableau-de-bord"),
         st.Page(page_administration, title="Administration", icon=":material/lock:", url_path="administration")]
st.navigation(pages, position="top").run()
