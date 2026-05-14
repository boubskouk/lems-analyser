#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module 1 : Lecture des fichiers CSV produits par le LEMS.

Structure du fichier CSV :
    Ligne 1 : date          ex: #,2022-12-01
    Ligne 2 : heure         ex: #,13:07:04
    Ligne 3 : séparateur    ex: ##,##
    Ligne 4 : calibration   ex: #0,.03863,0.00384,0.77,1,.00399,.1034,1,1
    Ligne 5 : en-têtes      ex: seconds,CO,GasTemp,PM,Flow,FlueTemp,TC,CO2,PM_RH
    Ligne 6+ : données mesurées (une ligne toutes les 2 secondes)
"""

import pandas as pd


# Noms des colonnes dans l'ordre du fichier CSV
COLONNES = ['seconds', 'CO', 'GasTemp', 'PM', 'Flow', 'FlueTemp', 'TC', 'CO2', 'PM_RH']

# Noms des colonnes qui ont un facteur de calibration (toutes sauf 'seconds')
COLONNES_CALIBRATION = ['CO', 'GasTemp', 'PM', 'Flow', 'FlueTemp', 'TC', 'CO2', 'PM_RH']


def lire_csv(chemin_fichier: str) -> dict:
    """
    Lit un fichier CSV du LEMS et retourne ses données structurées.

    Paramètre :
        chemin_fichier : chemin vers le fichier CSV (ex: 'csv/test.csv')

    Retourne un dictionnaire avec :
        - 'date'         : date du test (texte)
        - 'heure'        : heure de début du test (texte)
        - 'calibration'  : liste des 8 facteurs de calibration
        - 'donnees'      : DataFrame pandas avec toutes les mesures brutes
        - 'chemin'       : chemin du fichier (pour l'affichage)
    """

    # ── Lecture des 4 premières lignes (métadonnées) ──────────────────
    with open(chemin_fichier, 'r', encoding='utf-8', errors='replace') as f:
        lignes = f.readlines()

    # Ligne 1 : date  →  "#,2022-12-01"  →  on prend ce qui est après la virgule
    date = lignes[0].strip().replace('#,', '').strip()

    # Ligne 2 : heure  →  "#,13:07:04"  →  idem
    heure = lignes[1].strip().replace('#,', '').strip()

    # Ligne 4 : facteurs de calibration  →  "#0,.03863,0.00384,0.77,..."
    # On supprime le préfixe "#0," puis on sépare par les virgules
    ligne_cal = lignes[3].strip().replace('#0,', '')
    valeurs_cal = ligne_cal.split(',')

    # On convertit chaque valeur en nombre décimal
    calibration = []
    for valeur in valeurs_cal:
        valeur = valeur.strip()
        if valeur != '':
            calibration.append(float(valeur))

    # Si on n'a pas les 8 facteurs, on met 1.0 par défaut (pas de modification)
    while len(calibration) < 8:
        calibration.append(1.0)

    # ── Lecture des données mesurées ──────────────────────────────────
    # skiprows=5 : on saute les 4 lignes de métadonnées + la ligne d'en-têtes
    donnees = pd.read_csv(
        chemin_fichier,
        skiprows=5,
        names=COLONNES,
        on_bad_lines='skip'
    )
    for col in COLONNES:
        donnees[col] = pd.to_numeric(donnees[col], errors='coerce')

    # Supprimer les lignes sans valeur de temps
    donnees = donnees.dropna(subset=['seconds'])
    donnees = donnees.reset_index(drop=True)

    return {
        'chemin'     : chemin_fichier,
        'date'       : date,
        'heure'      : heure,
        'calibration': calibration,
        'donnees'    : donnees,
    }


def afficher_resume(resultat: dict):
    """
    Affiche un résumé lisible du fichier chargé.
    Utile pour vérifier que la lecture s'est bien passée.
    """
    print("=" * 50)
    print(f"  Fichier    : {resultat['chemin']}")
    print(f"  Date       : {resultat['date']}")
    print(f"  Heure      : {resultat['heure']}")
    print(f"  Calibration: {resultat['calibration']}")
    print(f"  Mesures    : {len(resultat['donnees'])} lignes")
    print(f"  Durée      : {resultat['donnees']['seconds'].max():.0f} secondes")
    print("=" * 50)
    print(resultat['donnees'].head())   # affiche les 5 premières lignes


# ── Test rapide si on lance ce fichier directement ────────────────────
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        fichier = sys.argv[1]
    else:
        fichier = '../csv/01-12-2022-Sakkanal-T11.csv'

    resultat = lire_csv(fichier)
    afficher_resume(resultat)
