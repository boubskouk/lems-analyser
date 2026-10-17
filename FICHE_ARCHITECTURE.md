# Fiche technique — LEMS Analyser
*Document d'analyse pour la rédaction du chapitre « Architecture modulaire » du mémoire. Généré par analyse du code source réel (`app.py`, `calculs.py`, `interpretation.py`, `import_csv.py`, `visualisation.py`, `requirements.txt`), aucun fichier du projet n'a été modifié pour produire cette fiche.*

---

## 1. Présentation

**Nom de l'outil** : LEMS Analyser

**Objectif** : automatiser le traitement et l'interprétation des données d'émissions produites par le dispositif LEMS (Laboratory Emissions Monitoring System, Aprovecho Research Center) lors des essais de foyers de cuisson à biomasse, conformément à la norme ISO 19867-1 (Water Boiling Test) et au système de classement par Tiers IWA-11.

**Problème résolu** : avant l'outil, le traitement des données collectées par le LEMS se faisait manuellement sous Excel via le fichier de référence du fabricant (« Sensor Box Processing ISO LEMS.xls » / T1.xlsx) — un processus fastidieux, peu reproductible et propice aux erreurs de saisie ou de copie de formules. LEMS Analyser automatise l'ensemble de la chaîne : import du CSV brut, calibration des capteurs, calcul des métriques de performance, classement Tier, génération d'un rapport de synthèse.

**Public cible** : ingénieurs-chercheurs et techniciens de laboratoire de la Division Bioénergie et Environnement du CERER (Centre d'Études et de Recherches sur les Énergies Renouvelables), ainsi que toute équipe utilisant un dispositif LEMS pour l'évaluation de foyers de cuisson selon ISO 19867.

---

## 2. Utilisateurs et rôles

**Non applicable.** L'application ne comporte aucun système d'authentification ni de gestion de rôles. Elle est accessible librement à toute personne disposant du lien (Streamlit Cloud ou VPS), sans distinction de profil ni de droits dans le code. Il n'existe qu'un seul mode d'usage : la saisie et l'analyse d'un test par un opérateur unique à la fois, session par session (`st.session_state` de Streamlit, propre à chaque navigateur/onglet ouvert).

---

## 3. Fonctionnalités

### Implémentées
- **Import de CSV LEMS** : lecture du fichier brut produit par le boîtier capteur (en-tête date/heure/calibration + flux de mesures à 0,5 Hz), extraction automatique des 8 facteurs de calibration.
- **Mode test intégré** : jeu de données préchargé (test réel Sakkanal-T11, 01-12-2022) pour démonstration/formation sans dépendre d'un fichier externe.
- **Découpage en 3 phases** : sélection interactive des intervalles Haute Puissance (HP) / Moyenne Puissance (MP) / Basse Puissance (BP) sur un graphe temporel.
- **Saisie des données externes** : combustible (type, humidité), pesées et températures de l'eau par pot, résidu de combustible, filtre gravimétrique PM2.5 (optionnel), conditions ambiantes (température, pression, humidité du laboratoire).
- **Calibration des capteurs** : application des facteurs lus dans l'en-tête du CSV à chaque canal (CO, PM, débit, températures, CO₂).
- **Calcul du débit du tunnel de dilution** (formule Pitot/Bernoulli).
- **Calcul des taux d'émission instantanés** (CO, PM2.5, CO₂) et intégration temporelle (émissions totales par méthode des trapèzes).
- **Calcul des métriques thermiques ISO 19867** : efficacité (avec/sans résidu charbonneux selon le combustible), puissance de cuisson, taux de combustion, MCE (Modified Combustion Efficiency).
- **Classement Tier ISO 19867-1 / IWA-11** : seuils officiels normalisés par énergie utile délivrée (g/MJd, mg/MJd), par phase et globalement (minimum des 3 phases).
- **Visualisations interactives** (Plotly) : concentrations, taux d'émission, températures, débit, jauge Tier, comparaison avant/après calibration.
- **Génération d'un rapport de synthèse textuel** interprété (recommandations incluses) et export PDF/Excel des résultats.
- **Accumulation de tests** (jusqu'à 5 répétitions, conformément à la recommandation ISO 19867) avec statistiques agrégées (moyenne, écart-type).
- **Comparaison aux valeurs de référence** d'un jeu de 5 tests biomasse (`Tableau calcul puissance Bois 5 Tests.xlsx`).

### Prévues mais non terminées / limitations connues
- **Calibration MSE (Mass Scattering Efficiency) par test** : l'application utilise une valeur fixe (3,0 m²/g) pour convertir le signal optique de diffusion en masse de PM2.5, au lieu de la dériver à chaque test à partir du filtre gravimétrique pesé (méthode prescrite par le manuel du fabricant). La valeur réelle peut varier de 0,01 à 8 m²/g selon le combustible — un écart significatif reste donc possible sur les résultats PM2.5 tant que cette calibration par test n'est pas implémentée.
- **Export PDF partiellement fonctionnel en production** : `generer_pdf()` dépend de la librairie `fpdf`, absente de `requirements.txt` (le code intercepte l'`ImportError` et désactive silencieusement le bouton d'export si elle n'est pas installée). De plus, la fonction référence des polices Windows en chemin absolu (`C:\Windows\Fonts\arial.ttf`), inexistantes sur les environnements Linux de déploiement (Streamlit Cloud, VPS Docker) — l'export bascule alors sur un rendu ASCII dégradé (accents remplacés).
- **Aucune persistance entre sessions** : tous les résultats (y compris les tests accumulés) sont perdus à la fermeture ou au rechargement de la page.
- **Table des matières / listes du rapport de stage** : sans lien avec le code de l'app — mentionné ici pour mémoire si le chapitre couvre aussi la documentation produite.

---

## 4. Stack technique

**Frontend** : [Streamlit](https://streamlit.io) ≥ 1.35 — framework Python qui génère à la fois l'interface web et exécute la logique serveur dans un seul processus (pas de séparation frontend/backend classique). Visualisations via **Plotly** ≥ 5.18 (graphiques interactifs intégrés).

**Backend** : Python 3.12. Logique métier organisée en modules séparés appelés directement par `app.py` (pas d'API REST interne, tout est en appels de fonctions Python dans le même processus) :
- `calculs.py` — cœur de calcul scientifique
- `interpretation.py` — interprétation ISO et génération de rapports
- `import_csv.py` — lecture des fichiers CSV
- `visualisation.py` — graphiques Plotly

**Base de données** : aucune. L'application est entièrement *stateless* du point de vue persistant : les données transitent en mémoire via `st.session_state` (propre à chaque session utilisateur) et des `pandas.DataFrame`, sans aucune écriture en base ni fichier persistant côté serveur.

**Authentification** : aucune.

**Hébergement / déploiement** : deux déploiements actifs, tous deux construits depuis le même dépôt GitHub (`github.com/boubskouk/lems-analyser`, branche `main`) :
- **Streamlit Community Cloud** (hébergement géré, redéploiement automatique sur chaque push).
- **VPS Hostinger** (conteneur Docker autonome, build via `Dockerfile` présent à la racine du dépôt, `requirements.txt` + `pip install`, lancement `streamlit run app.py --server.port=8501 --server.address=0.0.0.0`, redéploiement via `git pull` + rebuild manuel ou script `redeploy.sh`).

**Services externes et API tierces** : aucun. Dépendances purement locales : `pandas`, `numpy`, `streamlit`, `plotly`, `openpyxl` (lecture Excel pour les données de référence). Pas d'email, SMS, paiement, service IA ou autre API tierce appelée par l'application.

---

## 5. Arborescence

```
application/
├── app.py                 # Point d'entrée Streamlit : orchestration de l'UI,
│                           #   formulaires de saisie, état de session, assemblage
│                           #   des résultats et des exports
├── calculs.py              # Cœur de calcul : calibration capteurs, débit tunnel,
│                           #   taux d'émission, intégration temporelle, métriques
│                           #   thermiques ISO 19867, classement Tier
├── interpretation.py       # Seuils ISO/IWA-11, génération du texte d'analyse
│                           #   interprété, génération PDF, recommandations
├── import_csv.py           # Lecture et parsing des fichiers CSV bruts du LEMS
├── visualisation.py        # Graphiques interactifs Plotly (concentrations, taux
│                           #   d'émission, températures, débit, jauge Tier)
├── requirements.txt        # Dépendances Python
├── Dockerfile               # Image de déploiement (VPS)
├── .dockerignore
├── redeploy.sh              # Script de redéploiement VPS (git pull + rebuild Docker)
├── .streamlit/
│   └── config.toml          # Thème visuel de l'interface
└── csv/                     # Fichiers CSV de test (fixtures du « Mode test »)
```

Aucun sous-dossier supplémentaire : l'application est volontairement plate, sans couche `models/`, `views/`, `controllers/` ou `api/` distincte — cohérent avec une app Streamlit mono-fichier-d'entrée de taille modeste (~2 500 lignes au total).

---

## 6. Découpage en modules fonctionnels

| Module | Rôle | Fichier(s) | Données manipulées | Communique avec |
|---|---|---|---|---|
| **Import** | Lit le CSV brut du LEMS, extrait date/heure/calibration, construit le DataFrame de mesures brutes | `import_csv.py` | Fichier CSV → `dict` (métadonnées + `DataFrame`) | → Module Calcul |
| **Calcul** | Calibre les capteurs, calcule le débit tunnel, les concentrations et taux d'émission, intègre dans le temps, calcule l'efficacité thermique ISO 19867 et le Tier | `calculs.py` | `DataFrame` brut + paramètres externes saisis → `dict` de résultats (stats, totaux, métriques normalisées, tier) | ← Module Import · → Modules Interprétation et Visualisation |
| **Interprétation** | Applique les seuils ISO/IWA-11 officiels, génère le texte d'analyse par phase et global, les recommandations, le PDF de synthèse | `interpretation.py` | `dict` de résultats (sortie du module Calcul) → texte structuré / fichier PDF | ← Module Calcul · → Module UI |
| **Visualisation** | Construit les graphiques interactifs (courbes, jauges, tableaux) à partir des `DataFrame` calculés | `visualisation.py` | `DataFrame` calibré/taux → figures Plotly | ← Module Calcul · → Module UI |
| **UI / Orchestration** | Gère les formulaires de saisie, l'état de session (phases, tests accumulés), assemble et affiche les résultats, déclenche les exports | `app.py` | `st.session_state` (phases en cours, tests accumulés) | ← tous les modules ci-dessus |

Les modules communiquent exclusivement par **appels de fonctions directs et structures Python en mémoire** (`dict`, `DataFrame`) — il n'existe ni file de messages, ni base partagée, ni API interne entre eux ; `app.py` joue le rôle de chef d'orchestre appelant chaque module dans l'ordre Import → Calcul → Interprétation/Visualisation.

---

## 7. Flux principaux

**a) Analyse d'une phase de test (flux central)**
1. L'utilisateur importe un CSV (upload manuel, dossier local, ou « Mode test ») → module **Import**.
2. Il ajuste les intervalles temporels des 3 phases (HP/MP/BP) sur le graphe interactif → module **Visualisation**.
3. Il saisit les données externes de la phase (combustible, eau, pots, filtre PM2.5) dans le formulaire → `app.py`.
4. Au clic sur « Analyser », `app.py` appelle le module **Calcul** (calibration → débit → émissions → thermique → Tier).
5. Le résultat est transmis au module **Interprétation** (texte, Tier commenté) et au module **Visualisation** (graphiques de résultats), puis affiché par `app.py`.

**b) Rapport global ISO 19867 (bout en bout)**
1. Les 3 phases sont analysées individuellement (flux a, répété 3 fois) et stockées dans `st.session_state.resultats`.
2. Une fois les 3 phases complètes, l'utilisateur accède à l'onglet « Rapport global » : `app.py` agrège les résultats via le module **Interprétation** (Tier global = minimum des 3 phases, texte de synthèse, recommandations).
3. Le test complet peut être ajouté à `st.session_state.tests_accumules` (jusqu'à 5, pour les statistiques ISO 19867) et exporté en PDF/Excel.

**c) Mode test (démonstration)**
1. L'utilisateur active le bouton « Mode test » dans la barre latérale.
2. `app.py` recharge automatiquement un CSV fixture (`csv/01-12-2022-Sakkanal-T11.csv`) et pré-remplit tous les champs du formulaire avec des valeurs par défaut (`TEST_DEFAULTS`), permettant de parcourir instantanément le flux (a) sans données réelles — utile pour la formation ou la démonstration du guidage pas à pas de l'outil.

---

## 8. Sécurité

**Non applicable au sens classique** (pas d'authentification, pas de base de données, aucune donnée personnelle stockée côté serveur). Les seules mesures présentes relèvent de la validation d'entrée côté interface :
- Bornage des champs numériques (`min_value`/`max_value`) dans les formulaires Streamlit (ex. humidité 0-100 %, nombre de pots 1-6).
- Gestion des erreurs de lecture CSV (`on_bad_lines='skip'`, conversion numérique tolérante avec `errors='coerce'`).

Aucun chiffrement, gestion de rôles, Row Level Security ou protection CSRF/XSS spécifique n'est implémenté — l'exposition de l'application se limite à un outil de calcul sans donnée sensible ni compte utilisateur.
