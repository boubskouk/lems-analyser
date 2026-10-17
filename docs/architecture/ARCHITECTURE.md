# Architecture modulaire de LEMS Analyser

## 1. Introduction

Une architecture modulaire répartit un logiciel en unités indépendantes, chacune responsable d'une seule famille de traitements, communiquant par des interfaces simples. Elle facilite la maintenance, les tests et l'évolution isolée de chaque partie.

Ce choix convient à LEMS Analyser : le traitement d'un essai LEMS suit une chaîne linéaire et bien délimitée — lecture des données, calcul scientifique, interprétation normative, visualisation. Séparer ces quatre responsabilités en modules distincts évite qu'une modification du calcul n'affecte l'affichage, et inversement.

## 2. Vue d'ensemble des modules

L'application s'organise autour d'un module d'orchestration (`app.py`) qui pilote quatre modules spécialisés. Le module Calcul en constitue le cœur scientifique : les trois autres en dépendent directement ou indirectement.

**Figure 1 : Architecture modulaire de LEMS Analyser**
![Figure 1](images/01_architecture_modulaire.png)

## 3. Description des modules

| Module | Rôle | Entrées | Sorties |
|---|---|---|---|
| Import (`import_csv.py`) | Lit le CSV brut du LEMS et en extrait les métadonnées | Fichier CSV | Métadonnées + `DataFrame` brut |
| Calcul (`calculs.py`) | Calibre les capteurs, calcule débit, émissions, efficacité thermique et Tier | `DataFrame` brut, paramètres de test | Métriques, émissions, Tier |
| Interprétation (`interpretation.py`) | Applique les seuils ISO/IWA-11, génère le texte d'analyse et le PDF | Résultats du module Calcul | Texte interprété, PDF |
| Visualisation (`visualisation.py`) | Construit les graphiques de calibration | `DataFrame` calibré | Figures Plotly |

Chaque module expose un petit nombre de fonctions publiques et ne modifie aucune donnée en dehors de ce qu'il retourne.

## 4. Organisation en couches

L'application se lit aussi en trois couches : présentation, métier, données. Chaque couche n'appelle que celle du dessous, ce qui limite les dépendances croisées.

**Figure 2 : Architecture en couches**
![Figure 2](images/02_architecture_en_couches.png)

## 5. Diagramme de composants

Le diagramme suivant détaille les fonctions publiques réellement appelées par `app.py`, ainsi que les bibliothèques externes dont dépend chaque module.

**Figure 3 : Diagramme de composants**
![Figure 3](images/03_diagramme_composants.png)

## 6. Communication entre modules et flux de traitement

Les modules communiquent uniquement par appels de fonctions et structures Python en mémoire (`dict`, `DataFrame`) : aucune base partagée, aucune file de messages. `app.py` orchestre l'ensemble dans l'ordre Import → Calcul → Interprétation / Visualisation.

La Figure 4 détaille ce flux pour l'analyse d'une phase. La Figure 5 situe cette analyse dans le déroulement complet d'un essai (trois phases, rapport global, accumulation, export).

**Figure 4 : Séquence d'analyse d'une phase**
![Figure 4](images/04_sequence_analyse_phase.png)

**Figure 5 : Activité d'un essai complet**
![Figure 5](images/05_activite_essai_complet.png)

## 7. Cas d'utilisation

L'application ne connaît qu'un seul acteur, l'opérateur de laboratoire, qui dispose de neuf actions principales.

**Figure 6 : Cas d'utilisation**
![Figure 6](images/06_cas_utilisation.png)

## 8. Choix technologiques

| Besoin | Technologie | Justification |
|---|---|---|
| Interface et exécution serveur | Streamlit | Un seul langage (Python) pour l'interface et le calcul, déploiement simple |
| Calcul scientifique | pandas, NumPy | Manipulation efficace de séries temporelles à 0,5 Hz |
| Visualisation | Plotly | Graphiques interactifs intégrés à Streamlit |
| Lecture de données de référence | openpyxl | Lecture de fichiers Excel (comparaison à 5 tests de référence) |
| Export de rapport | fpdf | Génération de PDF (fonctionnement limité en production, voir §10) |

Aucune base de données ni service externe n'est utilisé : l'application reste volontairement simple au regard de son usage, limité à un essai à la fois.

## 9. Architecture de déploiement

Un seul dépôt GitHub sert de source à deux déploiements indépendants, tous deux mis à jour automatiquement ou semi-automatiquement depuis la branche `main`.

**Figure 7 : Architecture de déploiement**
![Figure 7](images/07_deploiement.png)

## 10. Limites actuelles et perspectives d'évolution

| Limite | Module concerné | Évolution possible |
|---|---|---|
| MSE (Mass Scattering Efficiency) fixée à 3,0 m²/g pour tout calcul PM2.5, au lieu d'une calibration par test à partir du filtre gravimétrique | `calculs.py` | Ajouter la saisie des pesées de filtre et dériver la MSE réelle par test |
| Export PDF dépendant de `fpdf`, absent de `requirements.txt`, et de polices Windows absentes des serveurs Linux de déploiement | `interpretation.py` | Ajouter `fpdf2` à `requirements.txt` et utiliser des polices embarquées multiplateformes |
| Aucune persistance : résultats perdus à la fermeture de la session | `app.py` | Ajouter un export/import de session, ou une base légère (SQLite) |
| Aucune authentification ni gestion de droits | `app.py` | Non prioritaire vu l'usage actuel à un seul opérateur ; à revoir si l'outil est partagé entre plusieurs équipes |
