#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compteur de numéros de rapport LEMS-AAAA-NNNN.

Le compteur est stocké dans un fichier JSON HORS du dépôt git (par défaut un
dossier frère de ce dépôt), pour qu'un redéploiement à partir de `git clone`
ne réinitialise jamais la numérotation. Chemin personnalisable via les
variables d'environnement :
    LEMS_COUNTER_FILE : chemin complet du fichier JSON (prioritaire)
    LEMS_COUNTER_DIR  : dossier dans lequel créer report_counter.json
                        (par défaut : un dossier 'lems_data' au même niveau
                        que ce dépôt — donc hors du dépôt git)

Sur le VPS, monter LEMS_COUNTER_DIR sur un volume Docker persistant pour que
la numérotation survive aux reconstructions de l'image.
"""

import datetime
import json
import os

_DEFAUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lems_data')


def _chemin_compteur() -> str:
    chemin_env = os.environ.get('LEMS_COUNTER_FILE')
    if chemin_env:
        os.makedirs(os.path.dirname(chemin_env) or '.', exist_ok=True)
        return chemin_env
    repertoire = os.environ.get('LEMS_COUNTER_DIR', _DEFAUT_DIR)
    os.makedirs(repertoire, exist_ok=True)
    return os.path.join(repertoire, 'report_counter.json')


def _lire(chemin: str) -> dict:
    if not os.path.exists(chemin):
        return {}
    try:
        with open(chemin, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _ecrire(chemin: str, donnees: dict):
    tmp = chemin + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(donnees, f, indent=2, ensure_ascii=False)
    os.replace(tmp, chemin)


def numero_rapport_suivant(annee: int = None) -> str:
    """Retourne le prochain numéro de rapport 'LEMS-AAAA-NNNN' pour l'année
    donnée (année en cours par défaut) et incrémente le compteur persisté."""
    annee = annee or datetime.date.today().year
    chemin = _chemin_compteur()
    donnees = _lire(chemin)
    cle = str(annee)
    suivant = donnees.get(cle, 0) + 1
    donnees[cle] = suivant
    _ecrire(chemin, donnees)
    return f'LEMS-{annee}-{suivant:04d}'
