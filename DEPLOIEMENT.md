# Plateforme de prévision — mise en ligne et utilisation

La plateforme est une application Python (Streamlit) hébergée gratuitement sur **Streamlit Community Cloud**.
Les visiteurs n'installent rien : ils ouvrent un lien dans leur navigateur.

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `app.py` | l'application : 2 pages, **Tableau de bord** (publique, une seule page dynamique) et **Administration** (mot de passe) |
| `carte.py` | la carte SVG : place les noms des 47 provinces sans chevauchement |
| `moteur.py` | les calculs : variables, passage aux 47 provinces, indice, modèles (noyau L11), contrôle du fichier Excel |
| `donnees/panel_base.csv` | historique officiel des 45 anciennes provinces × 2017-18 à 2024-25 (12 chiffres bruts par ligne) |
| `donnees/effectifs_47.csv` | effectifs des 47 provinces en vigueur et méthode de chaque chiffre |
| `donnees/carte_47.json` | contours simplifiés des 47 provinces (COD-AB) |
| `donnees/reference/` | sorties des carnets 01-02, pour vérifier le moteur |
| `requirements.txt` | bibliothèques installées par le serveur |
| `.streamlit/config.toml` | réglages d'affichage |
| `preparer_donnees.py` | régénère `donnees/` à partir du projet (à relancer si l'analyse change) |
| `verifier_moteur.py` | vérifie que la plateforme redonne les résultats des carnets Jupyter |

## Mettre à jour une application déjà en ligne (version 4, nouveaux poids)

Si l'application existe déjà, inutile d'en créer une autre :
1. Sur GitHub, ouvrir le dépôt de l'application → *Add file* → *Upload files*.
2. Glisser **le contenu** de `plateforme_pour_deploiement/` : `app.py`, `moteur.py`, `carte.py`, `requirements.txt`, `preparer_donnees.py`, `verifier_moteur.py`, ainsi que les dossiers `donnees/` et `.streamlit/`. Les fichiers de même nom sont remplacés.
3. Ne pas toucher aux éventuels `annees_publiees.csv` et `effectifs_47_publies.csv` déjà présents dans `donnees/`.
4. *Commit changes*. Streamlit redémarre seul en une à deux minutes ; le secret `MOT_DE_PASSE_ADMIN` est conservé.
5. Contrôle : l'indice de Komandjari doit valoir 91 (rang 3), Djelgodji et Karo-Peli 92 (rang 1), et Gourma doit être en P2.

## Première mise en ligne (environ 15 minutes, sans rien installer)

> **Évaluation à l'aveugle.** Le nom du compte GitHub, le nom du dépôt et l'adresse de l'application ne doivent
> contenir **aucun nom d'équipe ni de membre**. Utilisez un compte GitHub neutre.

1. **GitHub** — sur <https://github.com>, connectez-vous (compte neutre), puis *New repository* :
   nom neutre (par exemple `prevision-decrochage-primaire`), visibilité **Public**, *Create repository*.
2. Dans le dépôt vide : *uploading an existing file*, puis glissez **le contenu** du dossier `plateforme/`
   (les fichiers et les dossiers `donnees/` et `.streamlit/`, pas le dossier `plateforme` lui-même).
   *Commit changes*. Vérifiez que `app.py` est bien à la racine du dépôt.
3. **Streamlit** — sur <https://share.streamlit.io>, *Continue with GitHub*, puis *Create app* →
   *Deploy a public app from GitHub* :
   - Repository : le dépôt créé · Branch : `main` · Main file path : `app.py`
   - App URL : choisissez une adresse neutre (par exemple `prevision-decrochage-bf`)
   - *Advanced settings* : Python **3.12** ; dans *Secrets*, collez :
     ```
     MOT_DE_PASSE_ADMIN = "choisissez-un-mot-de-passe"
     ```
   - *Deploy*. Le premier démarrage prend quelques minutes (installation des bibliothèques).
4. Ouvrez le lien : la page « Tableau de bord » doit afficher la prévision **2025-26**, avec la carte aux 47 noms.

Sans le secret `MOT_DE_PASSE_ADMIN`, l'espace administrateur reste fermé : le tableau de bord public fonctionne
normalement, mais personne ne peut ajouter ni publier une année.

## Espace administrateur : ajouter une nouvelle année

Le tableau de bord est public. L'espace **Administration** (deuxième onglet de la barre du haut) n'est accessible
qu'avec le mot de passe `MOT_DE_PASSE_ADMIN` ; le bouton *Se déconnecter* ferme la session.

1. Onglet **Ajouter une année** → *Télécharger le modèle* : un classeur pré-rempli avec les chiffres de la
   dernière année connue.
2. Feuille **saisie** (45 lignes, les provinces de l'ancien découpage, celui des annuaires DGESS) : remplacer les
   12 colonnes par les chiffres de la nouvelle année, réels ou estimés :
   - annuaire statistique DGESS : effectif total, effectif du CM2, nouveaux inscrits au CP1, taux d'abandon,
     taux de redoublement, taux d'achèvement (total, garçons, filles), taux brut de scolarisation,
     nombre d'écoles publiques ;
   - CONASUR : personnes déplacées internes ; projections INSD : population des 6-11 ans.
3. Feuille **provinces_scindees** (facultative) : l'effectif propre de Djelgodji, Karo-Peli, Dyamongou et
   Gobnangou (somme de leurs communes, annuaires régionaux INSD). C'est elle qui donne à ces quatre provinces leurs
   **volumes propres** (élèves, élèves susceptibles d'abandonner). Les deux moitiés doivent retomber sur l'effectif
   de l'ancienne province à 1 % près. Laissées vides, la plateforme reprend les parts de l'année précédente.
   Leurs taux restent ceux de la province d'origine tant que les statistiques par commune ne sont pas publiées.
4. Charger le fichier. La plateforme contrôle chaque valeur (provinces manquantes, valeurs hors bornes, cases vides,
   CM2 ou nouveaux inscrits supérieurs à l'effectif, somme des moitiés) et refuse le fichier en cas d'erreur, en
   indiquant laquelle.
5. Un **aperçu** de la prévision de l'année suivante s'affiche aussitôt (visible de vous seul), avec la même page
   dynamique que le public : les modèles sont réentraînés avec la nouvelle année. Un bilan compare la prévision qui
   avait été faite pour l'année chargée aux chiffres saisis.
6. **Publier** : le tableau de bord public affiche alors la nouvelle année.
7. Onglet **Années publiées** : liste des années ajoutées, téléchargement des deux fichiers à conserver, retour aux
   données officielles.

## Limite à connaître : conserver une publication

Streamlit Community Cloud efface les fichiers écrits par l'application quand elle redémarre (mise à jour du dépôt,
ou mise en veille après plusieurs jours sans visite). Pour rendre une année publiée **permanente** :
onglet **Années publiées** de l'espace administrateur → téléchargez `annees_publiees.csv` **et** `effectifs_47_publies.csv`, puis déposez les
deux fichiers tels quels dans le dossier `donnees/` du dépôt GitHub.

## Vérifier les calculs (en local, avec Python)

La méthode est celle des carnets Jupyter (`carnets/02_indice_prevision_alerte.ipynb`) : 47 provinces, provinces scindées
pondérées par leur part d'effectif, noyau L11. Si l'analyse change, relancer les deux scripts ci-dessous :
le second compare la plateforme aux sorties des carnets (copiées dans `donnees/reference/`).

```
python preparer_donnees.py      # régénère donnees/ (lit aussi les contours COD-AB du Data Pack)
python verifier_moteur.py       # doit finir par « TOUT EST CONFORME »
streamlit run app.py            # ouvre la plateforme sur http://localhost:8501
```

## Poids de l'indice de risque

Les poids de l'indice (37,5 % abandon, 35 % exclusion et non-achèvement, 27,5 % choc sécuritaire) sont fixés dans
`moteur.py`. Ils proviennent de l'estimation du carnet 02 (moindres carrés contraints sur l'abandon de l'année
suivante, arrondis au quart de point). Pour les ré-estimer après plusieurs années ajoutées, relancer ce carnet,
reporter les nouveaux poids dans `moteur.py`, puis remplacer les fichiers de `donnees/reference/` et lancer
`python verifier_moteur.py`.
