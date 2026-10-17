#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composants d'interface partagés pour LEMS Analyser (refonte UI, 2026-10-17).

Ce module ne touche à aucune logique de calcul : il ne fait qu'assembler
du HTML/CSS autour des résultats produits par calculs.py / interpretation.py.
"""

import base64
import os

import streamlit as st

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')

ETAPES_LABELS = [
    'Série',
    'Fichier CSV',
    'Phases',
    'Pesées et analyse',
    'Rapport',
    'Enregistrement',
]


@st.cache_data(show_spinner=False)
def _lire_fichier_binaire(chemin):
    with open(chemin, 'rb') as f:
        return f.read()


def logo_data_uri():
    """Retourne le logo CERER encodé en data URI, ou None s'il est absent/illisible."""
    chemin = os.path.join(_ASSETS_DIR, 'logo-cerer.png')
    try:
        data = _lire_fichier_binaire(chemin)
    except OSError:
        return None
    return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')


@st.cache_data(show_spinner=False)
def _lire_css():
    chemin = os.path.join(_ASSETS_DIR, 'style.css')
    with open(chemin, encoding='utf-8') as f:
        return f.read()


def inject_style():
    st.markdown(f'<style>{_lire_css()}</style>', unsafe_allow_html=True)


def render_header():
    """En-tête applicative affichée sur tous les écrans après connexion."""
    logo = logo_data_uri()
    badge_html = (
        f'<img src="{logo}" alt="CERER">' if logo
        else '<span style="font-weight:700;color:#1F5C45;font-size:0.75rem;">CERER</span>'
    )
    nom = st.session_state.get('auth_name', '')
    role = st.session_state.get('auth_role', '')
    st.markdown(
        '<div class="lems-header">'
        f'<div class="lems-header__badge">{badge_html}</div>'
        '<div>'
        '<div class="lems-header__title">LEMS Analyser</div>'
        '<div class="lems-header__meta">ISO 19867-1 · ISO/IWA-11 · CERER</div>'
        '</div>'
        f'<div class="lems-header__user"><div class="name">{nom}</div>'
        f'<div class="role">{role}</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    _, col_btn = st.columns([6, 1])
    with col_btn:
        if st.button('Se déconnecter', key='btn_deconnexion', use_container_width=True):
            if _test_non_enregistre():
                st.session_state['_confirmer_deconnexion'] = True
            else:
                _effacer_session_auth()
                st.rerun()
    if st.session_state.get('_confirmer_deconnexion'):
        with st.container(border=True):
            st.warning('Le test en cours n\'est pas enregistré. Se déconnecter maintenant '
                       'fera perdre les données saisies pour ce test.')
            c1, c2 = st.columns(2)
            if c1.button('Se déconnecter quand même', key='btn_deco_confirme'):
                _effacer_session_auth()
                st.rerun()
            if c2.button('Annuler', key='btn_deco_annule'):
                st.session_state['_confirmer_deconnexion'] = False
                st.rerun()


def _test_non_enregistre():
    return bool(st.session_state.get('resultats')) and st.session_state.get('etape', 1) not in (1,)


def _effacer_session_auth():
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def render_stepper(etape_actuelle, n_phases_ok=0):
    """Barre des 6 étapes + libellé 'Série <foyer> · Test N sur nb_tests'."""
    serie = st.session_state.get('serie', {})
    foyer = serie.get('foyer', '')
    nb_tests = serie.get('nb_tests', 1)
    test_n = st.session_state.get('test_n', 1)

    col_g, col_d = st.columns([2, 3])
    with col_g:
        if foyer:
            st.markdown(
                f'<div class="lems-series-label">Série {foyer} · Test {test_n} sur {nb_tests}</div>',
                unsafe_allow_html=True,
            )
    with col_d:
        chips = []
        for i, label in enumerate(ETAPES_LABELS, start=1):
            texte = label
            if i == 4 and etape_actuelle >= 4:
                texte = f'{label} · {n_phases_ok} sur 3'
            if i < etape_actuelle:
                chips.append(f'<span class="lems-step lems-step--done">✓ {texte}</span>')
            elif i == etape_actuelle:
                chips.append(f'<span class="lems-step lems-step--current">{i}. {texte}</span>')
            else:
                chips.append(f'<span class="lems-step lems-step--todo">{texte}</span>')
        st.markdown(f'<div class="lems-stepper">{"".join(chips)}</div>', unsafe_allow_html=True)
    st.markdown('')


def render_todo_box(texte_html):
    """Encadré 'À faire maintenant' sous le titre de l'étape."""
    st.markdown(
        f'<div class="lems-todo-box"><strong>À faire maintenant</strong><br>{texte_html}</div>',
        unsafe_allow_html=True,
    )


def phase_label_html(phase, texte):
    return f'<span class="lems-phase-label--{phase}">{texte}</span>'
