# Plateforme de prévision — mise en ligne et utilisation

> Version illustrée et détaillée, pour la mise en ligne et pour les administrateurs :
> `GUIDE_DEPLOIEMENT_ET_ADMINISTRATION.pdf`. Pour modifier la plateforme :
> `GUIDE_DEVELOPPEMENT_PLATEFORME.pdf`.

La plateforme est une application Python (Streamlit) hébergée gratuitement sur **Streamlit Community Cloud**.
Les visiteurs n'installent rien : ils ouvrent un lien dans leur navigateur.

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `app.py` | l'application (5 pages : Prévision, Mettre à jour une année, Méthode et sources, Tableau de bord, Administration) |
| `moteur.py` | les calculs : variables, passage aux 47 provinces, indice, modèles (noyau L11), contrôle du fichier Excel |
| `donnees/panel_base.csv` | historique officiel des 45 anciennes provinces × 2017-18 à 2024-25 (12 chiffres bruts par ligne) |
| `donnees/effectifs_47.csv` | effectifs des 47 provinces en vigueur et méthode de chaque chiffre |
| `donnees/carte_47.json` | contours simplifiés des 47 provinces (COD-AB) |
| `donnees/tableau_de_bord.html` | le tableau de bord de l'analyse, affiché tel quel |
| `requirements.txt` | bibliothèques installées par le serveur |
| `.streamlit/config.toml` | réglages d'affichage |
| `preparer_donnees.py` | régénère `donnees/` à partir du projet (à relancer si l'analyse change) |
| `verifier_moteur.py` | vérifie que la plateforme redonne exactement les résultats du carnet |

## Mise en ligne (environ 15 minutes, sans rien installer)

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
4. Ouvrez le lien : la page « Prévision » doit afficher la prévision **2025-26**.

Sans le secret `MOT_DE_PASSE_ADMIN`, tout fonctionne sauf la publication : chacun peut charger un fichier et voir
la prévision dans sa propre session.

## Utilisation : ajouter une nouvelle année

1. Page **Mettre à jour une année** → *Télécharger le modèle* : un classeur pré-rempli avec les chiffres de la
   dernière année connue.
2. Feuille **saisie** (45 lignes, les provinces de l'ancien découpage, celui des annuaires DGESS) : remplacer les
   12 colonnes par les chiffres de la nouvelle année, réels ou estimés :
   - annuaire statistique DGESS : effectif total, effectif du CM2, nouveaux inscrits au CP1, taux d'abandon,
     taux de redoublement, taux d'achèvement (total, garçons, filles), taux brut de scolarisation,
     nombre d'écoles publiques ;
   - CONASUR : personnes déplacées internes ; projections INSD : population des 6-11 ans.
3. Feuille **provinces_scindees** (facultative) : l'effectif propre de Djelgodji, Karo-Peli, Dyamongou et
   Gobnangou (somme de leurs communes, annuaires régionaux INSD). Les deux moitiés doivent retomber sur l'effectif
   de l'ancienne province à 1 % près. Laissées vides, la plateforme reprend les parts de l'année précédente et
   l'indique (« estimation : parts … appliquées »).
4. Charger le fichier. La plateforme contrôle chaque valeur (provinces manquantes, valeurs hors bornes, cases vides,
   CM2 ou nouveaux inscrits supérieurs à l'effectif, somme des moitiés) et refuse le fichier en cas d'erreur, en
   indiquant laquelle.
5. La prévision de l'année suivante s'affiche aussitôt pour les 47 provinces : les modèles sont **réentraînés**
   avec la nouvelle année.
   Si l'année chargée suit directement la dernière connue, un bilan compare aussi la prévision qui avait été faite
   pour elle aux chiffres saisis.
6. **Publier** (mot de passe administrateur) : la page « Prévision » affiche alors la nouvelle année pour tous.

## Limite à connaître : conserver une publication

Streamlit Community Cloud efface les fichiers écrits par l'application quand elle redémarre (mise à jour du dépôt,
ou mise en veille après plusieurs jours sans visite). Pour rendre une année publiée **permanente** :
page **Administration** → téléchargez `annees_publiees.csv` **et** `effectifs_47_publies.csv`, puis déposez les
deux fichiers tels quels dans le dossier `donnees/` du dépôt GitHub.

## Vérifier les calculs (en local, avec Python)

La méthode est celle de l'analyse publiée (`src/step04_analyse_v2.py`) : 47 provinces, provinces scindées
pondérées par leur part d'effectif, noyau L11. Si l'analyse change, relancer les deux scripts ci-dessous :
le second compare la plateforme aux sorties déposées dans `depots/04_analyse/`.

```
python preparer_donnees.py      # régénère donnees/ (lit aussi les contours COD-AB du Data Pack)
python verifier_moteur.py       # doit finir par « TOUT EST CONFORME »
streamlit run app.py            # ouvre la plateforme sur http://localhost:8501
```
