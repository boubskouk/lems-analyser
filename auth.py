#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentification par mot de passe (PBKDF2-SHA256) pour LEMS Analyser.

hash_password() / verify_password() : logique inchangée (identique à la version
en production sur le VPS depuis le 17/10/2026). Seul l'écran de connexion
(require_login) a été redessiné lors de la refonte UI.
"""

import hashlib
import hmac
import os
import time

import streamlit as st

import ui

_ALGO = 'pbkdf2_sha256'
_ITERATIONS = 260_000

_MAX_ECHECS = 5
_BLOCAGE_S = 60


def hash_password(password: str, salt: bytes = None) -> str:
    """Retourne une empreinte au format 'pbkdf2_sha256$iterations$sel$hash' (hex)."""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, _ITERATIONS)
    return f'{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}'


def verify_password(password: str, stored_hash: str) -> bool:
    """Compare un mot de passe en clair à une empreinte stockée (comparaison à temps constant)."""
    try:
        algo, iterations, salt_hex, hash_hex = stored_hash.split('$')
        if algo != _ALGO:
            return False
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, int(iterations))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ─────────────────────────────────────────────────────────────────────
# Écran de connexion (affichage uniquement — la logique ci-dessus est
# inchangée)
# ─────────────────────────────────────────────────────────────────────

def _blocage_restant():
    until = st.session_state.get('auth_bloque_jusqu', 0.0)
    reste = until - time.time()
    return max(0.0, reste)


def require_login():
    """Affiche l'écran de connexion tant que l'utilisateur n'est pas authentifié.
    Bloque l'exécution du reste de l'application (st.stop()) si non connecté.
    """
    if st.session_state.get('auth_ok'):
        return

    with st.container(key='lems_login_row'):
        col_gauche, col_droite = st.columns([1.15, 1], gap='large')

        with col_gauche:
            badge_html = ui.logo_img_tag(56, css_class='lems-login-logo')
            st.markdown(
                '<div class="lems-login-brand">'
                f'  <div class="lems-login-badge">{badge_html}</div>'
                '  <div class="lems-login-title">LEMS Analyser</div>'
                '  <div class="lems-login-subtitle">Laboratoire biomasse-énergie · CERER · UCAD</div>'
                '  <p class="lems-login-desc">'
                '    Outil informatique d\'automatisation du traitement et de la visualisation '
                '    des données d\'émissions issues du dispositif LEMS (Laboratory Emissions '
                '    Monitoring System) du laboratoire de biomasse-énergie du CERER'
                '  </p>'
                '  <p class="lems-login-norme">'
                '    Conforme à la norme ISO 19867-1 : calibration des capteurs, métriques '
                '    thermiques, émissions de CO et de PM2,5, classement Tier ISO/IWA-11.'
                '  </p>'
                '</div>',
                unsafe_allow_html=True,
            )

        with col_droite:
            with st.container(border=True):
                st.markdown('#### Connexion')
                st.caption('Accès réservé aux équipes du laboratoire.')

                reste = _blocage_restant()
                if reste > 0:
                    st.error(f"Accès bloqué après {_MAX_ECHECS} échecs. "
                             f"Réessayez dans {int(reste) + 1} seconde(s).")
                else:
                    with st.form('login_form'):
                        identifiant = st.text_input('Identifiant', key='login_identifiant').strip().lower()
                        mot_de_passe = st.text_input('Mot de passe', type='password', key='login_mdp')
                        submitted = st.form_submit_button('Se connecter', type='primary',
                                                           use_container_width=True)

                    if submitted:
                        users = st.secrets.get('users', {})
                        user = users.get(identifiant)
                        if user is not None and verify_password(mot_de_passe, user.get('password_hash', '')):
                            st.session_state.auth_ok = True
                            st.session_state.auth_user = identifiant
                            st.session_state.auth_name = user.get('name', identifiant)
                            st.session_state.auth_role = user.get('role', 'utilisateur')
                            st.session_state.pop('auth_echecs', None)
                            st.session_state.pop('auth_bloque_jusqu', None)
                            st.rerun()
                        else:
                            echecs = st.session_state.get('auth_echecs', 0) + 1
                            st.session_state.auth_echecs = echecs
                            if echecs >= _MAX_ECHECS:
                                st.session_state.auth_bloque_jusqu = time.time() + _BLOCAGE_S
                                st.error(f"Accès bloqué après {_MAX_ECHECS} échecs. "
                                         f"Réessayez dans {_BLOCAGE_S} seconde(s).")
                            else:
                                st.error('Identifiant ou mot de passe incorrect.')

                st.caption(f"Après {_MAX_ECHECS} échecs, l'accès est bloqué {_BLOCAGE_S} secondes.")

    st.stop()
