#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEMS Analyser — Application Streamlit
Conforme ISO 19867-1 · Classement ISO/IWA-11

Refonte UI (2026-10-17) : navigation en 6 étapes par série de tests.
Aucune des fonctions de calculs.py / interpretation.py / import_csv.py
n'est modifiée — seule l'orchestration de l'interface change.
"""

import datetime, io, os, tempfile
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from import_csv import lire_csv
from calculs import (analyser, COMBUSTIBLES, PCI_DEFAUT, FRAC_C_DEFAUT,
                     FUELS_AVEC_RESIDU_CHARBONNEUX, HHV_CHARBON,
                     appliquer_calibration, calculer_taux_emission)
from visualisation import graphique_comparaison_calibration, tableau_calibration_df
from interpretation import (analyser_phase, generer_texte, generer_recommandations,
                             TIER_COUL, TIER_BG, TIER_LABEL,
                             SEUILS_CO_G_MJD)
import rapport_pdf
import report_counter

import ui
import auth

st.set_page_config(
    page_title='LEMS Analyser',
    page_icon='assets/logo-cerer.png',
    layout='wide',
    initial_sidebar_state='expanded',
)
ui.inject_style()
auth.require_login()
ui.render_header()

CSV_TEST = os.path.join(os.path.dirname(__file__), 'csv', '01-12-2022-Sakkanal-T11.csv')

PHASES_LABELS = {'HP': 'Haute Puissance', 'MP': 'Moyenne Puissance', 'BP': 'Basse Puissance'}
PHASE_COLORS  = {
    'HP': dict(fill='rgba(29,78,137,0.12)',  border='#1D4E89', pos='top left'),
    'MP': dict(fill='rgba(208,138,46,0.12)', border='#D08A2E', pos='top right'),
    'BP': dict(fill='rgba(94,156,152,0.14)', border='#5E9C98', pos='bottom right'),
}

TEST_DEFAULTS = {
    'HP': dict(mb=1.820, mc=0.062, np=4, me=2.5, td=22.0, tf=95.0, hmc=12.0),
    'MP': dict(mb=0.900, mc=0.030, np=4, me=2.5, td=22.0, tf=95.0, hmc=12.0),
    'BP': dict(mb=0.400, mc=0.010, np=4, me=2.5, td=22.0, tf=95.0, hmc=12.0),
}

# ─────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────
if 'etape' not in st.session_state:
    st.session_state.etape = 1
if 'serie' not in st.session_state:
    st.session_state.serie = {}
if 'test_n' not in st.session_state:
    st.session_state.test_n = 1
if 'resultats' not in st.session_state:
    st.session_state.resultats = {}
if 'tests_accumules' not in st.session_state:
    st.session_state.tests_accumules = []

# ─────────────────────────────────────────────────────────────────────
# Helpers génériques (logique inchangée depuis la version précédente)
# ─────────────────────────────────────────────────────────────────────

def lire_upload(fichier):
    contenu = fichier.read().decode('utf-8', errors='replace')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False,
                                     encoding='utf-8', errors='replace') as tmp:
        tmp.write(contenu)
        chemin = tmp.name
    try:
        return lire_csv(chemin)
    finally:
        os.unlink(chemin)


def estimer_fond(df_full):
    n = len(df_full)
    i_bg0 = max(0, n // 20)
    i_bg1 = min(n, n // 7)
    i_zero = min(20, n)
    bg_pm   = round(float(df_full['PM'].iloc[i_bg0:i_bg1].mean()), 1)  if i_bg1 > i_bg0 else 0.0
    bg_co   = round(float(df_full['CO'].iloc[i_bg0:i_bg1].mean()), 1)  if i_bg1 > i_bg0 else 0.0
    bg_co2  = round(float(df_full['CO2'].iloc[i_bg0:i_bg1].mean()), 1) if i_bg1 > i_bg0 else 615.0
    bg_flow = round(float(df_full['Flow'].iloc[:i_zero].mean()), 0)     if i_zero > 0    else 9900.0
    return bg_pm, bg_co, bg_co2, bg_flow


def _reset_test_data():
    """Remet à zéro CSV, intervalles, pesées, températures, résultats — garde la série."""
    for k in ('current_csv', 'current_csv_name'):
        st.session_state.pop(k, None)
    for p in ('HP', 'MP', 'BP'):
        st.session_state.pop(f'intervalle_{p}', None)
        for kk in (f'mb_{p}', f'mc_{p}', f'cp_{p}', f'me_{p}', f'td_{p}', f'tf_{p}',
                   f'fa_{p}', f'fp_{p}', f'deb_{p}', f'fin_{p}'):
            st.session_state.pop(kk, None)
    for kk in ('horloge_debut_hp', 'horloge_fin_hp', 'horloge_fin_mp', 'horloge_fin_bp'):
        st.session_state.pop(kk, None)
    st.session_state.resultats = {}


def render_sidebar_donnees_communes():
    with st.sidebar:
        s = st.session_state.serie
        st.header('Série en cours')
        st.caption(f"{s.get('foyer', '')} · {s.get('protocole', '')}")
        st.markdown(f"**Test {st.session_state.get('test_n', 1)} sur {s.get('nb_tests', 1)}**")

        with st.expander('Données communes', expanded=False):
            liste_comb = list(COMBUSTIBLES.keys())
            idx = liste_comb.index(s.get('type_combustible', liste_comb[0])) \
                if s.get('type_combustible') in liste_comb else 0
            s['type_combustible'] = st.selectbox('Type de combustible', liste_comb,
                                                   index=idx, key='sb_tc')
            pci_defaut, _ = COMBUSTIBLES.get(s['type_combustible'], (PCI_DEFAUT, FRAC_C_DEFAUT))
            with st.expander('PCI personnalisé (optionnel)'):
                st.caption(f'Valeur par défaut pour « {s["type_combustible"]} » : '
                           f'{pci_defaut:.0f} kJ/kg (PCI net). Renseignez ci-dessous le PCI net '
                           f'mesuré pour ce combustible précis si vous le connaissez — sinon '
                           f'laissez à 0 pour utiliser la valeur par défaut.')
                pci_saisi = st.number_input('PCI net mesuré (kJ/kg)', min_value=0.0,
                                             value=float(s.get('pci_custom_kJ_kg') or 0.0),
                                             step=10.0, format='%.0f', key='sb_pci_custom')
                s['pci_custom_kJ_kg'] = pci_saisi if pci_saisi > 0 else None
            if s['type_combustible'] in FUELS_AVEC_RESIDU_CHARBONNEUX:
                with st.expander('PCI du charbon produit (optionnel)'):
                    st.caption(f'Valeur par défaut : {HHV_CHARBON:.0f} kJ/kg (PCI net du charbon '
                               f'résiduel). Ce PCI varie selon le combustible d\'origine — '
                               f'renseignez la valeur mesurée pour ce test si vous la connaissez, '
                               f'sinon laissez à 0.')
                    pci_char_saisi = st.number_input('PCI net du charbon (kJ/kg)', min_value=0.0,
                                                      value=float(s.get('pci_char_custom_kJ_kg') or 0.0),
                                                      step=10.0, format='%.0f', key='sb_pci_char_custom')
                    s['pci_char_custom_kJ_kg'] = pci_char_saisi if pci_char_saisi > 0 else None
            s['humidite_pct'] = st.number_input('Humidité combustible (%)', min_value=0.0,
                                                  max_value=100.0, value=float(s.get('humidite_pct', 12.0)),
                                                  step=0.5, format='%.1f', key='sb_hc')
            s['T_atm'] = st.number_input('Température ambiante (°C)', value=float(s.get('T_atm', 29.0)),
                                          step=0.5, format='%.1f', key='sb_ta')
            s['pression'] = st.number_input('Pression atmosphérique (hPa)', value=float(s.get('pression', 1012.0)),
                                             step=1.0, format='%.0f', key='sb_pr')
            s['nombre_pots'] = st.number_input('Nombre de pots', min_value=1, max_value=6,
                                                value=int(s.get('nombre_pots', 4)), step=1, key='sb_npots')
            s['eau_par_pot_kg'] = st.number_input('Eau par pot (kg)', value=float(s.get('eau_par_pot_kg', 2.5)),
                                                   step=0.1, format='%.1f', key='sb_eau')

        st.divider()
        st.caption('Statut des phases du test en cours')
        for p in ('HP', 'MP', 'BP'):
            res_p = st.session_state.resultats.get(p)
            if res_p is not None:
                badge = f'<span class="lems-badge-ok">Analysée · Tier {res_p["tier"]}</span>'
            else:
                badge = '<span class="lems-badge-todo">À faire</span>'
            st.markdown(f'<div style="margin-bottom:6px;"><strong>{p}</strong> {badge}</div>',
                        unsafe_allow_html=True)

        st.divider()
        if st.button('Nouvelle série', use_container_width=True, key='btn_nouvelle_serie'):
            st.session_state['_confirmer_nouvelle_serie'] = True
        if st.session_state.get('_confirmer_nouvelle_serie'):
            st.warning('Cela effacera la série en cours, y compris les tests déjà enregistrés.')
            c1, c2 = st.columns(2)
            if c1.button('Confirmer', key='btn_confirme_nouvelle_serie', use_container_width=True):
                for k in list(st.session_state.keys()):
                    if k not in ('auth_ok', 'auth_user', 'auth_name', 'auth_role'):
                        del st.session_state[k]
                st.session_state.etape = 1
                st.rerun()
            if c2.button('Annuler', key='btn_annule_nouvelle_serie', use_container_width=True):
                st.session_state['_confirmer_nouvelle_serie'] = False
                st.rerun()


def _calculer_df_taux(res_csv, s, bg_pm_raw, bg_co_raw, bg_co2_ppm, baseline_flow):
    df0 = res_csv['donnees']
    calibr0 = res_csv['calibration']
    pm_cal0 = calibr0[2] if len(calibr0) > 2 and calibr0[2] != 0 else 0.77
    co_cal0 = calibr0[0] if len(calibr0) > 0 and calibr0[0] != 0 else 0.03863
    df_cal0 = appliquer_calibration(df0, calibr0)
    df_taux0 = calculer_taux_emission(
        df_cal0, baseline_flow, s.get('T_atm', 29.0),
        bg_pm_ug=bg_pm_raw * pm_cal0,
        bg_co_ppm=bg_co_raw * co_cal0,
        bg_co2_ppm=bg_co2_ppm,
        p_Pa=s.get('pression', 1012.0) * 100.0,
    )
    return df0, df_cal0, df_taux0, calibr0


def _lancer_analyse(phase, res_csv, nom_fichier, type_comb, hum_comb, T_atm, pression,
                     baseline_flow, bg_pm_raw, bg_co_raw, bg_co2_ppm):
    pots = [{
        'masse_eau': st.session_state[f'me_{phase}'],
        'T_debut'  : st.session_state[f'td_{phase}'],
        'T_fin'    : st.session_state[f'tf_{phase}'],
    }]
    donnees_ext = {
        'type_combustible': type_comb,
        'masse_bois_kg'   : st.session_state[f'mb_{phase}'],
        'masse_charbon_kg': st.session_state[f'mc_{phase}'],
        'masse_charbon_produit_kg': st.session_state.get(f'cp_{phase}', 0.0) or 0.0,
        'pci_custom_kJ_kg': st.session_state.serie.get('pci_custom_kJ_kg'),
        'pci_char_custom_kJ_kg': st.session_state.serie.get('pci_char_custom_kJ_kg'),
        'humidite_pct'    : hum_comb,
        'pots'            : pots,
        'T_atm'           : T_atm,
        'p_Pa'            : pression * 100.0,
        'baseline_flow'   : baseline_flow,
        'bg_pm_raw'       : bg_pm_raw,
        'bg_co_raw'       : bg_co_raw,
        'bg_co2_ppm'      : bg_co2_ppm,
        'filtre_avant_mg' : st.session_state.get(f'fa_{phase}', 0.0),
        'filtre_apres_mg' : st.session_state.get(f'fp_{phase}', 0.0),
    }
    iv = st.session_state.get(f'intervalle_{phase}')
    if iv:
        donnees_ext['t_debut_s'] = iv[0] * 60.0
        donnees_ext['t_fin_s']   = iv[1] * 60.0
    with st.spinner(f'Calculs {phase}...'):
        result = analyser(res_csv, donnees_ext)
    result['_fichier'] = nom_fichier
    fa = st.session_state.get(f'fa_{phase}', 0.0)
    fp = st.session_state.get(f'fp_{phase}', 0.0)
    result['_pm_gravi_mg'] = round(fp - fa, 3) if fp > fa > 0 else None
    st.session_state.resultats[phase] = result


def _enregistrer_test_courant(tier_global, analyses, resultats):
    entree = {
        'fichier': st.session_state.get('current_csv_name', ''),
        'tier'   : tier_global,
        'phases' : {c: {
            'eff'          : a['eff'],
            'eff_sc'       : a['eff_sc'],
            'co_g_min'     : a['co_g_min'],
            'pm_mg_min'    : a['pm_mg_min'],
            'co_mjd'       : a['co_mjd'],
            'pm_mjd'       : a['pm_mjd'],
            'mce'          : a['mce'],
            'puissance_cuisson_W': resultats[c]['thermique']['puissance_cuis_kW'] * 1000
                                    if c in resultats else None,
            'taux_combustion_g_min': resultats[c]['thermique']['taux_combustion_g_min']
                                      if c in resultats else None,
        } for c, a in analyses.items()},
    }
    st.session_state.tests_accumules.append(entree)


def _get_id(cle, defaut=''):
    return st.session_state.get(f'id_{cle}', defaut)


def _construire_contexte_rapport():
    """Assemble le contexte passé à rapport_pdf.generer_rapport_test / _serie :
    champs saisis par l'utilisateur (étape 1 'Identification de l'essai' + champs
    optionnels de l'étape 5) et champs automatiques (n° de rapport, date/heure de
    génération, version de l'application, utilisateur connecté, métadonnées CSV)."""
    res_csv = st.session_state.get('current_csv')
    df0 = res_csv['donnees'] if res_csv else None
    n_mesures = None
    freq_hz = None
    duree_totale_min = None
    if df0 is not None and len(df0) > 1:
        duree_s_tot = float(df0['seconds'].max() - df0['seconds'].min())
        n_mesures = len(df0)
        duree_totale_min = duree_s_tot / 60.0
        intervalle_s = duree_s_tot / (n_mesures - 1)
        freq_hz = round(1.0 / intervalle_s, 1) if intervalle_s > 0 else None

    s = st.session_state.serie
    cle_meta = f'rapport_meta_test_{st.session_state.test_n}'
    if cle_meta not in st.session_state:
        st.session_state[cle_meta] = {
            'numero'   : report_counter.numero_rapport_suivant(),
            'genere_le': datetime.datetime.now(),
        }
    meta = st.session_state[cle_meta]

    return {
        'numero_rapport': meta['numero'],
        'date_emission' : meta['genere_le'].date(),
        'genere_le'     : meta['genere_le'],
        'auth_name'     : st.session_state.get('auth_name', ''),

        'demandeur_raison_sociale'  : _get_id('demandeur_raison_sociale'),
        'demandeur_adresse'         : _get_id('demandeur_adresse'),
        'demandeur_contact_nom'     : _get_id('demandeur_contact_nom'),
        'demandeur_contact_fonction': _get_id('demandeur_contact_fonction'),
        'demandeur_contact_tel'     : _get_id('demandeur_contact_tel'),
        'demandeur_contact_courriel': _get_id('demandeur_contact_courriel'),
        'demandeur_reference'       : _get_id('demandeur_reference'),

        'foyer_nom'           : s.get('foyer', ''),
        'foyer_fabricant'     : _get_id('foyer_fabricant'),
        'foyer_modele'        : _get_id('foyer_modele'),
        'foyer_numero_serie'  : _get_id('foyer_numero_serie'),
        'foyer_type'          : _get_id('foyer_type'),
        'foyer_date_reception': _get_id('foyer_date_reception'),

        'type_combustible': s.get('type_combustible', ''),
        'humidite_pct'    : s.get('humidite_pct'),
        'nombre_pots'     : s.get('nombre_pots'),
        'eau_par_pot_kg'  : s.get('eau_par_pot_kg'),

        'date_essai_iso'    : res_csv['date'] if res_csv else None,
        'heure_debut_hms'   : res_csv['heure'] if res_csv else None,
        'duree_totale_min'  : duree_totale_min,
        'n_mesures'         : n_mesures,
        'freq_hz'           : freq_hz,

        'lieu_essai'             : st.session_state.get('lieu_test', ''),
        'T_atm'                  : s.get('T_atm'),
        'pression'               : s.get('pression'),
        'humidite_relative_pct'  : st.session_state.get('id_humidite_relative_pct'),

        'operateur_nom'         : _get_id('operateur_nom'),
        'operateur_fonction'    : _get_id('operateur_fonction'),
        'verificateur_nom'      : _get_id('verificateur_nom'),
        'verificateur_fonction' : _get_id('verificateur_fonction'),
        'approbateur_nom'       : _get_id('approbateur_nom'),
        'approbateur_fonction'  : _get_id('approbateur_fonction'),

        'equipement_numero_serie': _get_id('equipement_numero_serie'),
        'derniere_calibration'   : _get_id('derniere_calibration'),

        'nom_fichier': st.session_state.get('current_csv_name', ''),
        'test_n'     : st.session_state.test_n,
        'nb_tests'   : s.get('nb_tests', 1),

        'observations_operateur': st.session_state.get('observations_operateur', ''),
    }


# ─────────────────────────────────────────────────────────────────────
# Étape 1 — Nouvelle série d'essais
# ─────────────────────────────────────────────────────────────────────

def _appliquer_demo_serie1():
    if st.session_state.get('f1_demo'):
        st.session_state['f1_foyer'] = 'Sakkanal-T11'
        st.session_state['f1_tc'] = 'Bois dur moyen'
        st.session_state['f1_hc'] = 12.0
        st.session_state['f1_npots'] = 4
        st.session_state['f1_eau'] = 2.5
        st.session_state['f1_ta'] = 29.0
        st.session_state['f1_pr'] = 1012.0
        st.session_state['id_foyer_type'] = 'Foyer à bois'


def etape_1_serie():
    st.subheader("Nouvelle série d'essais")
    ui.render_todo_box(
        "Renseignez le foyer testé et les données communes à tous les tests de la série, "
        "puis cliquez sur « Démarrer la série »."
    )

    with st.container(border=True):
        foyer = st.text_input('Foyer testé', value=st.session_state.serie.get('foyer', ''),
                               placeholder='ex. Sakkanal-T11', key='f1_foyer')
        if not foyer.strip():
            st.markdown(
                '<p style="color:#9B2C1C;font-size:0.85rem;margin:-10px 0 6px 0;">'
                'Indiquez le foyer testé pour démarrer la série.</p>',
                unsafe_allow_html=True,
            )
        st.selectbox('Protocole', ['WBT ISO 19867-1'], index=0, key='f1_protocole', disabled=True)

        st.markdown('**Nombre de tests**')
        nb_choisi = st.session_state.get('_nb_tests_choice', 3)
        cols_n = st.columns(3)
        for i, n in enumerate((3, 4, 5)):
            if cols_n[i].button(str(n), key=f'nb_tests_{n}',
                                 type='primary' if nb_choisi == n else 'secondary',
                                 use_container_width=True):
                st.session_state['_nb_tests_choice'] = n
                st.rerun()
        st.caption('La norme ISO 19867 demande au moins 3 répétitions.')

        st.markdown('')
        demo = st.checkbox('Utiliser le jeu de démonstration (Sakkanal-T11)',
                            value=st.session_state.serie.get('demo', False),
                            key='f1_demo', on_change=_appliquer_demo_serie1)

        msg_avertissement_f1 = '<p style="color:#7A5A12;font-size:0.82rem;margin:4px 0 0 0;">⚠ {}</p>'

        def _avertir_hors_plage_f1(valeur, lo, hi, libelle):
            if valeur is not None and not (lo <= valeur <= hi):
                st.markdown(msg_avertissement_f1.format(
                    f'Valeur inhabituelle pour « {libelle} » (plage attendue {lo}–{hi}). '
                    f'Vérifiez la saisie — ce n\'est pas bloquant.'),
                    unsafe_allow_html=True)

        st.markdown('**Données communes**')
        c1, c2, c3 = st.columns(3)
        with c1:
            liste_comb = list(COMBUSTIBLES.keys())
            type_comb = st.selectbox('Type de combustible', liste_comb, index=0, key='f1_tc')
            hum_comb = st.number_input('Humidité combustible (%)', min_value=0.0, max_value=100.0,
                                        value=(12.0 if demo else None), step=0.5, format='%.1f', key='f1_hc')
            if not demo:
                st.caption("Mesurée en laboratoire ; laissez vide si inconnue.")
            _avertir_hors_plage_f1(hum_comb, 3.0, 30.0, 'humidité combustible (%)')
        with c2:
            T_atm = st.number_input('Température ambiante (°C)',
                                     value=(29.0 if demo else None), step=0.5,
                                     format='%.1f', key='f1_ta')
            if not demo:
                st.caption("Relevée sur le site du test.")
            _avertir_hors_plage_f1(T_atm, 10.0, 45.0, 'température ambiante (°C)')
            pression = st.number_input('Pression atmosphérique (hPa)',
                                        value=(1012.0 if demo else None), step=1.0,
                                        format='%.0f', key='f1_pr')
            if not demo:
                st.caption("Pression atmosphérique locale au moment du test.")
            _avertir_hors_plage_f1(pression, 900.0, 1050.0, 'pression atmosphérique (hPa)')
        with c3:
            nombre_pots = st.number_input('Nombre de pots', min_value=1, max_value=6, value=4,
                                           step=1, format='%d', key='f1_npots')
            eau_par_pot = st.number_input('Eau par pot (kg)', value=2.5, step=0.1, format='%.1f',
                                           key='f1_eau')

        with st.expander('Informations complémentaires (optionnel)'):
            ci1, ci2 = st.columns(2)
            nom_testeur = ci1.text_input('Nom du testeur(s)', value=st.session_state.get('nom_testeur', ''),
                                          placeholder='ex. A. Fall, M. Diallo', key='f1_testeur')
            lieu_test = ci2.text_input('Lieu du test', value=st.session_state.get('lieu_test', ''),
                                        placeholder='ex. CERER, Dakar', key='f1_lieu')

        with st.expander("Identification de l'essai (optionnel, pour l'en-tête du rapport PDF)"):
            st.caption("Ces informations sont conservées pour toute la série et reprises sur "
                       "chaque page de couverture du rapport PDF.")
            st.markdown('**Demandeur**')
            d1, d2 = st.columns(2)
            d1.text_input('Raison sociale', key='id_demandeur_raison_sociale')
            d2.text_input('Référence de la demande', key='id_demandeur_reference')
            d1.text_input('Adresse', key='id_demandeur_adresse')
            d2.text_input('Contact (nom)', key='id_demandeur_contact_nom')
            d1.text_input('Contact (fonction)', key='id_demandeur_contact_fonction')
            d2.text_input('Contact (téléphone)', key='id_demandeur_contact_tel')
            d1.text_input('Contact (courriel)', key='id_demandeur_contact_courriel')

            st.markdown('**Foyer**')
            f1c, f2c = st.columns(2)
            f1c.text_input('Fabricant', key='id_foyer_fabricant')
            f2c.text_input('Modèle', key='id_foyer_modele')
            f1c.text_input('N° de série du foyer', key='id_foyer_numero_serie')
            f2c.text_input('Type de foyer', value=st.session_state.get('id_foyer_type', ''),
                            placeholder='ex. Foyer à bois', key='id_foyer_type')
            f1c.text_input('Date de réception (JJ/MM/AAAA)', key='id_foyer_date_reception')

            st.markdown('**Personnel**')
            p1, p2 = st.columns(2)
            p1.text_input("Opérateur de l'essai (nom)", key='id_operateur_nom')
            p2.text_input("Opérateur (fonction)", key='id_operateur_fonction')
            p1.text_input('Vérificateur (nom)', key='id_verificateur_nom')
            p2.text_input('Vérificateur (fonction)', key='id_verificateur_fonction')
            p1.text_input('Approbateur (nom)', key='id_approbateur_nom')
            p2.text_input('Approbateur (fonction)', key='id_approbateur_fonction')

            st.markdown('**Équipement et conditions ambiantes**')
            e1, e2 = st.columns(2)
            e1.text_input('N° de série du LEMS', key='id_equipement_numero_serie')
            e2.text_input('Dernière calibration (JJ/MM/AAAA)', key='id_derniere_calibration')
            e1.number_input('Humidité relative ambiante (%)', min_value=0.0, max_value=100.0,
                             value=None, step=1.0, format='%.0f', key='id_humidite_relative_pct')

        st.markdown('')
        nb_tests = st.session_state.get('_nb_tests_choice', 3)
        valeurs_manquantes = hum_comb is None or T_atm is None or pression is None
        disabled = not foyer.strip() or valeurs_manquantes
        if valeurs_manquantes and foyer.strip():
            st.caption("Renseignez l'humidité, la température ambiante et la pression pour continuer.")
        if st.button(f'Démarrer la série de {nb_tests} tests', type='primary',
                     use_container_width=True, disabled=disabled, key='f1_demarrer'):
            st.session_state.serie = {
                'foyer': foyer.strip(), 'protocole': 'WBT ISO 19867-1', 'nb_tests': nb_tests,
                'type_combustible': type_comb, 'humidite_pct': hum_comb,
                'T_atm': T_atm, 'pression': pression,
                'nombre_pots': nombre_pots, 'eau_par_pot_kg': eau_par_pot,
                'demo': demo,
            }
            st.session_state.nom_testeur = nom_testeur
            st.session_state.lieu_test = lieu_test
            st.session_state.test_n = 1
            st.session_state.etape = 2
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Étape 2 — Fichier CSV
# ─────────────────────────────────────────────────────────────────────

def etape_2_fichier():
    st.subheader('Fichier CSV')
    render_sidebar_donnees_communes()

    s = st.session_state.serie
    demo = s.get('demo', False)
    _CSV, _NAME = 'current_csv', 'current_csv_name'

    if demo and _CSV not in st.session_state:
        try:
            st.session_state[_CSV]  = lire_csv(CSV_TEST)
            st.session_state[_NAME] = '01-12-2022-Sakkanal-T11.csv'
        except Exception as e:
            st.error(f'Fichier de démonstration introuvable : {e}')

    res_csv = st.session_state.get(_CSV)
    if res_csv is None:
        texte_todo = ("Importez le fichier CSV du LEMS pour le test "
                       f"{st.session_state.get('test_n', 1)}, puis cliquez sur « Suivant ». "
                       "Ensuite : délimiter les phases HP, MP et BP.")
    elif demo:
        texte_todo = ("Le fichier de démonstration Sakkanal-T11 est chargé. "
                       "Vérifiez la fiche du fichier puis cliquez sur « Suivant ».")
    else:
        texte_todo = "Fichier chargé. Vérifiez la date et la durée, puis cliquez sur « Suivant »."
    ui.render_todo_box(texte_todo)

    with st.container(border=True):
        if not demo:
            uploaded = st.file_uploader('Importer le fichier CSV du test', type=['csv'], key='upload_csv')
            if uploaded is not None and uploaded.name != st.session_state.get(_NAME):
                try:
                    st.session_state[_CSV]  = lire_upload(uploaded)
                    st.session_state[_NAME] = uploaded.name
                    st.session_state.resultats = {}
                except Exception as e:
                    st.error(f'Erreur de lecture du fichier : {e}')

        res_csv     = st.session_state.get(_CSV)
        nom_fichier = st.session_state.get(_NAME, '')

        if res_csv is not None:
            df0 = res_csv['donnees']
            duree_tot = (df0['seconds'].max() - df0['seconds'].min()) / 60.0
            st.success(f'✓ Fichier chargé — **{nom_fichier}**')
            m1, m2, m3, m4 = st.columns(4)
            m1.metric('Date', res_csv['date'])
            m2.metric('Heure début', res_csv['heure'])
            m3.metric('Durée totale', f'{duree_tot:.1f} min')
            m4.metric('Nb mesures', f'{len(df0)}')

    res_csv = st.session_state.get(_CSV)
    col_retour, _, col_suivant = st.columns([1, 3, 1])
    with col_retour:
        if st.button('Retour', use_container_width=True, key='btn_retour_2'):
            st.session_state.etape = 1
            st.rerun()
    with col_suivant:
        disabled = res_csv is None
        if st.button('Suivant', type='primary', use_container_width=True,
                     disabled=disabled, key='btn_suivant_2'):
            st.session_state.etape = 3
            st.rerun()
        if disabled:
            st.caption('Importez un fichier CSV pour continuer.')


# ─────────────────────────────────────────────────────────────────────
# Étape 3 — Phases
# ─────────────────────────────────────────────────────────────────────

def etape_3_phases():
    st.subheader('Découpage des phases')
    render_sidebar_donnees_communes()
    with st.sidebar:
        with st.expander('Comment repérer les phases'):
            st.markdown(
                '- **HP** : démarrage jusqu\'à l\'ébullition\n'
                '- **MP** : reprise après rechargement jusqu\'à la nouvelle ébullition\n'
                '- **BP** : mijotage sous l\'ébullition'
            )

    res_csv = st.session_state.get('current_csv')
    if res_csv is None:
        st.warning('Aucun fichier CSV chargé. Revenez à l\'étape précédente.')
        if st.button('Retour', key='btn_retour_3_vide'):
            st.session_state.etape = 2
            st.rerun()
        return

    ui.render_todo_box(
        "Ajustez les bornes Début / Fin de chaque phase (HP, MP, BP) à l'aide du graphique, "
        "puis cliquez sur « Valider les intervalles »."
    )

    s = st.session_state.serie
    bg_pm_a, bg_co_a, bg_co2_a, bg_fl_a = estimer_fond(res_csv['donnees'])
    with st.expander('Paramètres avancés (zérotage capteurs)'):
        st.caption('Estimés automatiquement depuis le début du CSV. Modifiables si nécessaire.')
        bg_pm_raw     = st.number_input('PM ambiant (logunits)', value=bg_pm_a, step=0.1, format='%.1f', key='bpm')
        bg_co_raw     = st.number_input('CO ambiant (logunits)', value=bg_co_a, step=0.1, format='%.1f', key='bco')
        bg_co2_ppm    = st.number_input('CO₂ ambiant (ppm)', value=bg_co2_a, step=1.0, format='%.1f', key='bco2')
        baseline_flow = st.number_input('Débit ventilateur arrêté (logunits)', value=bg_fl_a,
                                         step=10.0, format='%.0f', key='bfl')
    st.session_state['zero_bg_pm_raw']     = bg_pm_raw
    st.session_state['zero_bg_co_raw']     = bg_co_raw
    st.session_state['zero_bg_co2_ppm']    = bg_co2_ppm
    st.session_state['zero_baseline_flow'] = baseline_flow

    st.info(f"⏱ Heure de démarrage de l'enregistrement LEMS : **{res_csv.get('date', '—')} à "
            f"{res_csv.get('heure', '—')}**")

    df0, df_cal0, df_taux0, _ = _calculer_df_taux(res_csv, s, bg_pm_raw, bg_co_raw, bg_co2_ppm, baseline_flow)
    t_min = df0['seconds'] / 60.0
    t_min_val, t_max_val = float(t_min.min()), float(t_min.max())
    # Bornes arrondies à 1 décimale une seule fois ici, puis réutilisées partout
    # (min_value/max_value des number_input ET valeurs par défaut) : un mélange de
    # valeurs brutes et arrondies provoquait un crash StreamlitValueAboveMaxError
    # quand l'arrondi flottant de t_max_val ne tombait pas du même côté.
    t_min_r, t_max_r = round(t_min_val, 1), round(t_max_val, 1)
    duree_tot_min = t_max_r - t_min_r

    with st.expander("Saisir les heures de phase à l'horloge (optionnel, plus fiable qu'un "
                      "calcul manuel de minutes écoulées)"):
        st.caption(
            "Indiquez l'heure d'horloge à laquelle chaque phase a réellement commencé "
            "(ex. heure d'allumage pour HP, heure de rechargement pour MP, etc.). L'app "
            "calcule elle-même le nombre de minutes écoulées depuis le début de "
            "l'enregistrement — vous n'avez rien à soustraire à la main."
        )
        heure_ref = None
        try:
            heure_ref = datetime.datetime.strptime(res_csv.get('heure', ''), '%H:%M:%S').time()
        except ValueError:
            st.warning("Heure de démarrage du fichier illisible — saisie à l'horloge indisponible "
                       "pour ce fichier, utilisez les champs en minutes ci-dessous.")

        if heure_ref is not None:
            col_h1, col_h2, col_h3, col_h4 = st.columns(4)
            t_debut_hp = col_h1.time_input('Début HP (allumage)', value=None, step=60, key='horloge_debut_hp')
            t_fin_hp   = col_h2.time_input('Fin HP = début MP', value=None, step=60, key='horloge_fin_hp')
            t_fin_mp   = col_h3.time_input('Fin MP = début BP', value=None, step=60, key='horloge_fin_mp')
            t_fin_bp   = col_h4.time_input('Fin BP', value=None, step=60, key='horloge_fin_bp')

            def _ecart_min(t_cible):
                if t_cible is None:
                    return None
                ref_s = heure_ref.hour * 3600 + heure_ref.minute * 60 + heure_ref.second
                cible_s = t_cible.hour * 3600 + t_cible.minute * 60 + t_cible.second
                ecart_s = cible_s - ref_s
                if ecart_s < 0:
                    ecart_s += 24 * 3600  # passage de minuit
                return ecart_s / 60.0

            points = [_ecart_min(t_debut_hp), _ecart_min(t_fin_hp),
                      _ecart_min(t_fin_mp), _ecart_min(t_fin_bp)]

            if st.button('Appliquer ces heures aux 3 phases', key='btn_appliquer_horloge',
                         disabled=any(p is None for p in points)):
                croissant = all(points[i] < points[i + 1] for i in range(3))
                dans_bornes = all(t_min_r - 1e-6 <= p <= t_max_r + 1e-6 for p in points)
                if not croissant:
                    st.error("Les heures doivent être dans l'ordre chronologique "
                             "(Début HP < Fin HP < Fin MP < Fin BP).")
                elif not dans_bornes:
                    st.error(f"Ces heures tombent en dehors de la durée du fichier "
                             f"({t_min_r:.1f} à {t_max_r:.1f} min après le démarrage de "
                             f"l'enregistrement). Vérifiez l'heure saisie.")
                else:
                    p0, p1, p2, p3 = (round(p, 1) for p in points)
                    st.session_state['deb_HP'] = p0
                    st.session_state['fin_HP'] = p1
                    st.session_state['deb_MP'] = p1
                    st.session_state['fin_MP'] = p2
                    st.session_state['deb_BP'] = p2
                    st.session_state['fin_BP'] = p3
                    st.session_state['intervalle_HP'] = (p0, p1)
                    st.session_state['intervalle_MP'] = (p1, p2)
                    st.session_state['intervalle_BP'] = (p2, p3)
                    st.success('Intervalles mis à jour à partir des heures saisies.')
                    st.rerun()

    tiers = [
        (t_min_r, round(t_min_r + duree_tot_min * 0.37, 1)),
        (round(t_min_r + duree_tot_min * 0.37, 1), round(t_min_r + duree_tot_min * 0.69, 1)),
        (round(t_min_r + duree_tot_min * 0.69, 1), t_max_r),
    ]
    for idx_p, p in enumerate(('HP', 'MP', 'BP')):
        if f'intervalle_{p}' not in st.session_state:
            st.session_state[f'intervalle_{p}'] = tiers[idx_p]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t_min, y=df_taux0['CO_ppm_zeroed'], name='CO (ppm)',
                              line=dict(color='#2196F3', width=1.2)))
    fig.add_trace(go.Scatter(x=t_min, y=df_taux0['PM_ug_zeroed'], name='PM2.5 (µg/m3)',
                              line=dict(color='#F44336', width=1.2), yaxis='y2'))
    fig.add_trace(go.Scatter(x=t_min, y=df_cal0['GasTemp'], name='Température gaz (°C)',
                              line=dict(color='#FF9800', width=1.5, dash='dot'), yaxis='y3'))

    for p, sstyle in PHASE_COLORS.items():
        iv = st.session_state.get(f'intervalle_{p}')
        if iv:
            x0, x1 = iv
            fig.add_vrect(x0=x0, x1=x1, fillcolor=sstyle['fill'],
                          line=dict(color=sstyle['border'], width=2, dash='dash'),
                          annotation_text=f'{p} ({x1 - x0:.1f} min)',
                          annotation_position=sstyle['pos'],
                          annotation_font=dict(size=12, color=sstyle['border']))

    fig.update_layout(
        xaxis=dict(domain=[0.08, 0.88], title='Temps (min)', title_font=dict(size=14),
                   tickfont=dict(size=12), showgrid=True, gridcolor='#e0e0e0'),
        yaxis=dict(title='CO (ppm)', title_font=dict(size=13, color='#2196F3'),
                   tickfont=dict(size=12, color='#2196F3')),
        yaxis3=dict(title='T gaz (°C)', title_font=dict(size=13, color='#FF9800'),
                    tickfont=dict(size=12, color='#FF9800'), overlaying='y', side='left',
                    anchor='free', position=0.0, showgrid=False),
        yaxis2=dict(title='PM2.5 (µg/m3)', title_font=dict(size=13, color='#F44336'),
                    tickfont=dict(size=12, color='#F44336'), overlaying='y', side='right'),
        legend=dict(orientation='h', y=1.10, font=dict(size=12)),
        hovermode='x unified', plot_bgcolor='white', paper_bgcolor='white',
        margin=dict(l=100, r=90, t=50, b=50), height=370,
    )
    st.plotly_chart(fig, use_container_width=True)

    for p in ('HP', 'MP', 'BP'):
        iv = st.session_state[f'intervalle_{p}']
        if f'deb_{p}' not in st.session_state:
            st.session_state[f'deb_{p}'] = round(float(iv[0]), 1)
        if f'fin_{p}' not in st.session_state:
            st.session_state[f'fin_{p}'] = round(float(iv[1]), 1)
        # Recadre toute valeur restée en session depuis un CSV précédent (durée
        # différente) pour qu'elle reste dans les bornes du fichier actuel.
        st.session_state[f'deb_{p}'] = min(max(st.session_state[f'deb_{p}'], t_min_r), t_max_r)
        st.session_state[f'fin_{p}'] = min(max(st.session_state[f'fin_{p}'], t_min_r), t_max_r)

    deb_vals = {p: st.session_state[f'deb_{p}'] for p in ('HP', 'MP', 'BP')}
    fin_vals = {p: st.session_state[f'fin_{p}'] for p in ('HP', 'MP', 'BP')}

    erreurs = {'HP': [], 'MP': [], 'BP': []}
    for p in ('HP', 'MP', 'BP'):
        if deb_vals[p] >= fin_vals[p]:
            erreurs[p].append('Le début doit être inférieur à la fin.')
    if abs(fin_vals['HP'] - deb_vals['MP']) > 1e-6:
        erreurs['MP'].append('Le début de MP doit correspondre à la fin de HP.')
    if abs(fin_vals['MP'] - deb_vals['BP']) > 1e-6:
        erreurs['BP'].append('Le début de BP doit correspondre à la fin de MP.')
    if fin_vals['BP'] > t_max_r + 1e-6:
        erreurs['BP'].append('La fin de BP ne peut pas dépasser la durée totale du fichier.')

    st.markdown('**Intervalles des phases (minutes)**')
    cols = st.columns(3)
    for col, p in zip(cols, ('HP', 'MP', 'BP')):
        with col, st.container(border=True):
            st.markdown(ui.phase_label_html(p, f'{p} — {PHASES_LABELS[p]}'), unsafe_allow_html=True)
            deb = st.number_input('Début (min)', min_value=t_min_r, max_value=t_max_r,
                                   step=0.5, format='%.1f', key=f'deb_{p}')
            fin = st.number_input('Fin (min)', min_value=t_min_r, max_value=t_max_r,
                                   step=0.5, format='%.1f', key=f'fin_{p}')
            st.session_state[f'intervalle_{p}'] = (deb, fin)
            st.caption(f'{max(0.0, fin - deb):.1f} min')
            for msg in erreurs[p]:
                st.markdown(f'<p style="color:#9B2C1C;font-size:0.82rem;margin:4px 0 0 0;">{msg}</p>',
                            unsafe_allow_html=True)

    with st.expander('Calibration — données brutes vs calibrées', expanded=False):
        st.caption('Valeurs lues depuis la ligne #0 du CSV · valeur calibrée = valeur brute × facteur')
        st.dataframe(tableau_calibration_df(df0, df_cal0, res_csv['calibration']), use_container_width=True)
        st.plotly_chart(graphique_comparaison_calibration(df0, df_cal0, res_csv['calibration']),
                        use_container_width=True)

    col_retour, col_suivant = st.columns([1, 3])
    with col_retour:
        if st.button('Retour', use_container_width=True, key='btn_retour_3'):
            st.session_state.etape = 2
            st.rerun()
    with col_suivant:
        intervalles_invalides = any(erreurs[p] for p in erreurs)
        if st.button('Valider les intervalles', type='primary', use_container_width=True,
                     disabled=intervalles_invalides, key='btn_suivant_3'):
            st.session_state.etape = 4
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Étape 4 — Pesées et analyse
# ─────────────────────────────────────────────────────────────────────

def _texte_aide_etape4(nb_phases_ok, resultats):
    ordre = ['HP', 'MP', 'BP']
    if nb_phases_ok == 0:
        return "Remplissez les pesées de la phase HP puis cliquez sur « Analyser HP »."
    if nb_phases_ok == 3:
        return "Les 3 phases sont analysées. Cliquez sur « Suivant » pour accéder au rapport."
    fait = [p for p in ordre if p in resultats]
    restant = [p for p in ordre if p not in resultats]
    derniere = fait[-1]
    r = resultats[derniere]
    suivante = restant[0]
    return (f"La phase {derniere} est analysée (Tier {r['tier']}). Passez à la phase {suivante} : "
            f"saisissez ses pesées puis cliquez sur « Analyser {suivante} ». "
            f"Il reste {len(restant)} phase(s) avant le rapport.")


def _rendre_onglet_phase(phase, res_csv, nom_fichier, type_comb, hum_comb, T_atm, pression,
                          baseline_flow, bg_pm_raw, bg_co_raw, bg_co2_ppm, demo, t_min, df_taux0):
    td = TEST_DEFAULTS[phase]

    deja = st.session_state.resultats.get(phase)
    if deja:
        st.markdown(f'<span class="lems-badge-ok">Analysée · Tier {deja["tier"]}</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="lems-badge-todo">À faire</span>', unsafe_allow_html=True)
    st.markdown('')
    msg_incoherence = '<p style="color:#9B2C1C;font-size:0.82rem;margin:4px 0 0 0;">{}</p>'
    msg_avertissement = '<p style="color:#7A5A12;font-size:0.82rem;margin:4px 0 0 0;">⚠ {}</p>'

    def _avertir_hors_plage(valeur, lo, hi, libelle):
        if valeur is not None and not (lo <= valeur <= hi):
            st.markdown(msg_avertissement.format(
                f'Valeur inhabituelle pour « {libelle} » (plage attendue {lo}–{hi}). '
                f'Vérifiez la saisie — ce n\'est pas bloquant.'),
                unsafe_allow_html=True)

    col_init, col_final = st.columns(2)
    with col_init:
        st.markdown('**Pesées et températures initiales**')
        mb = st.number_input('Combustible chargé en début de phase (kg)', min_value=0.0,
                              value=(float(td['mb']) if demo else None), step=0.01, format='%.3f', key=f'mb_{phase}')
        if mb is None:
            st.caption('Obligatoire : pesée du combustible chargé.')
        else:
            _avertir_hors_plage(mb, 0.05, 10.0, 'combustible chargé (kg)')
        me = st.number_input('Eau totale dans les pots (kg)', min_value=0.1,
                              value=(float(td['me'] * td['np']) if demo else None),
                              step=0.1, format='%.1f', key=f'me_{phase}')
        if me is None:
            st.caption("Obligatoire : masse totale d'eau dans les pots.")
        else:
            _avertir_hors_plage(me, 0.5, 15.0, 'eau totale (kg)')
        t0 = st.number_input("T° eau initiale (°C)", value=(float(td['td']) if demo else None),
                              step=0.5, format='%.1f', key=f'td_{phase}')
        if t0 is None:
            st.caption("Obligatoire : température initiale de l'eau.")
        else:
            _avertir_hors_plage(t0, 10.0, 45.0, "température initiale de l'eau (°C)")
    with col_final:
        st.markdown('**Pesées et températures finales**')
        mc = st.number_input('Résidu combustible en fin de phase (kg)', min_value=0.0,
                              value=(float(td['mc']) if demo else None), step=0.001, format='%.3f', key=f'mc_{phase}')
        if mc is None:
            st.caption('Obligatoire : pesée du résidu combustible.')
        elif mb is not None and mc >= mb:
            st.markdown(msg_incoherence.format(
                'Le résidu combustible doit être inférieur au combustible chargé.'),
                unsafe_allow_html=True)
        else:
            _avertir_hors_plage(mc, 0.0, 5.0, 'résidu combustible (kg)')
        if type_comb in FUELS_AVEC_RESIDU_CHARBONNEUX:
            cp = st.number_input('Dont charbon produit, pesée séparée (kg, optionnel)',
                                  min_value=0.0, value=0.0, step=0.001, format='%.3f', key=f'cp_{phase}')
            st.caption('Masse de CHARBON SEUL (conteneur + charbon pesé avant/après), pas le '
                       'résidu total ci-dessus. Sans cette valeur, « Efficacité avec charbon » '
                       'est identique à « Efficacité sans charbon » (aucun crédit énergétique '
                       'n\'est supposé sans pesée réelle du charbon produit).')
            if mc is not None and cp is not None and cp > mc:
                st.markdown(msg_incoherence.format(
                    'Le charbon produit ne peut pas dépasser le résidu combustible total.'),
                    unsafe_allow_html=True)
        tf = st.number_input("T° eau finale (°C)", value=(float(td['tf']) if demo else None),
                              step=0.5, format='%.1f', key=f'tf_{phase}')
        if tf is None:
            st.caption("Obligatoire : température finale de l'eau.")
        elif t0 is not None and tf <= t0:
            st.markdown(msg_incoherence.format(
                'La température finale doit être supérieure à la température initiale.'),
                unsafe_allow_html=True)
        elif tf > 100.0:
            st.markdown(msg_avertissement.format(
                "L'eau bout à 100 °C au niveau de la mer : une température finale "
                "supérieure est très inhabituelle. Vérifiez la saisie — ce n'est pas bloquant."),
                unsafe_allow_html=True)
        else:
            _avertir_hors_plage(tf, 50.0, 100.0, "température finale de l'eau (°C)")

    mb_val = mb if mb is not None else 0.0
    mc_val = mc if mc is not None else 0.0
    st.caption(f'Combustible brûlé estimé : {max(0.0, mb_val - mc_val):.3f} kg '
               f'(chargé en début − résidu en fin)')

    with st.expander('Filtre PM2.5 (optionnel)'):
        f1, f2 = st.columns(2)
        f1.number_input('Avant (mg)', min_value=0.0, value=0.0, step=0.001, format='%.3f', key=f'fa_{phase}')
        f2.number_input('Après (mg)', min_value=0.0, value=0.0, step=0.001, format='%.3f', key=f'fp_{phase}')

    champs_manquants = any(v is None for v in (mb, me, t0, mc, tf))
    incoherent = (mc is not None and mb is not None and mc >= mb) or \
                 (tf is not None and t0 is not None and tf <= t0)
    bloque = champs_manquants or incoherent or res_csv is None

    st.markdown('')
    if st.button(f'Analyser {phase}', key=f'btn_analyser_{phase}', type='primary',
                 use_container_width=True, disabled=bloque):
        _lancer_analyse(phase, res_csv, nom_fichier, type_comb, hum_comb, T_atm, pression,
                         baseline_flow, bg_pm_raw, bg_co_raw, bg_co2_ppm)
        st.rerun()
    if res_csv is not None:
        if champs_manquants:
            st.caption('Renseignez toutes les pesées et températures obligatoires pour analyser cette phase.')
        elif incoherent:
            st.caption("Corrigez les valeurs incohérentes signalées ci-dessus avant d'analyser cette phase.")

    r = st.session_state.resultats.get(phase)
    if r:
        a = analyser_phase(phase, r)
        bg, col = TIER_BG.get(a['t_iwa11'], '#F5F5F5'), TIER_COUL.get(a['t_iwa11'], '#555')
        st.markdown(
            f'<div class="tier-banner" style="background:{bg};border-left:6px solid {col};'
            f'padding:12px 18px;margin:8px 0;">'
            f'<span style="font-size:1.3em;font-weight:700;color:{col};">'
            f'Tier {a["t_iwa11"]} — {TIER_LABEL[a["t_iwa11"]]}</span></div>',
            unsafe_allow_html=True,
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric('CO', f'{a["co_mjd"]:.2f} g/MJd')
        m2.metric('PM2.5', f'{a["pm_mjd"]:.1f} mg/MJd')
        m3.metric('Efficacité thermique', f'{a["eff"]:.1f} %')
        m4.metric('MCE', f'{a["mce"]:.1f} %')
        st.caption(f'Puissance de cuisson : {r["thermique"]["puissance_cuis_kW"] * 1000:.0f} W · '
                   f'Taux de combustion : {r["thermique"]["taux_combustion_g_min"]:.2f} g/min · '
                   f'Facteur limitant : {a["limitant"]}')

        iv = st.session_state.get(f'intervalle_{phase}')
        if iv:
            x0, x1 = iv
            masque = (t_min >= x0) & (t_min <= x1)
            fig_taux = go.Figure()
            fig_taux.add_trace(go.Scatter(x=t_min[masque], y=df_taux0['CO_ppm_zeroed'][masque],
                                           name='CO (ppm)', line=dict(color='#2196F3', width=1.3)))
            fig_taux.add_trace(go.Scatter(x=t_min[masque], y=df_taux0['PM_ug_zeroed'][masque],
                                           name='PM2.5 (µg/m3)', line=dict(color='#F44336', width=1.3),
                                           yaxis='y2'))
            fig_taux.update_layout(
                title=f"Taux d'émission — phase {phase}",
                xaxis=dict(title='Temps (min)'),
                yaxis=dict(title='CO (ppm)', title_font=dict(color='#2196F3')),
                yaxis2=dict(title='PM2.5 (µg/m3)', overlaying='y', side='right',
                            title_font=dict(color='#F44336')),
                height=260, margin=dict(l=60, r=60, t=40, b=40), legend=dict(orientation='h', y=1.18),
                plot_bgcolor='white', paper_bgcolor='white',
            )
            st.plotly_chart(fig_taux, use_container_width=True)


def etape_4_pesees():
    st.subheader('Pesées et analyse')
    render_sidebar_donnees_communes()

    res_csv = st.session_state.get('current_csv')
    nom_fichier = st.session_state.get('current_csv_name', '')
    if res_csv is None:
        st.warning('Aucun fichier CSV chargé. Revenez à l\'étape précédente.')
        if st.button('Retour', key='btn_retour_4_vide'):
            st.session_state.etape = 2
            st.rerun()
        return

    s = st.session_state.serie
    type_comb = s.get('type_combustible', list(COMBUSTIBLES.keys())[0])
    hum_comb  = s.get('humidite_pct', 12.0)
    T_atm     = s.get('T_atm', 29.0)
    pression  = s.get('pression', 1012.0)
    baseline_flow = st.session_state.get('zero_baseline_flow', 9900.0)
    bg_pm_raw     = st.session_state.get('zero_bg_pm_raw', 0.0)
    bg_co_raw     = st.session_state.get('zero_bg_co_raw', 0.0)
    bg_co2_ppm    = st.session_state.get('zero_bg_co2_ppm', 615.0)
    demo = s.get('demo', False)

    _, _, df_taux0, _ = _calculer_df_taux(res_csv, s, bg_pm_raw, bg_co_raw, bg_co2_ppm, baseline_flow)
    t_min = res_csv['donnees']['seconds'] / 60.0

    ui.render_todo_box(_texte_aide_etape4(len(st.session_state.resultats), st.session_state.resultats))

    tabs = st.tabs([f'{p} — {PHASES_LABELS[p]}' for p in ('HP', 'MP', 'BP')])
    for tab, phase in zip(tabs, ('HP', 'MP', 'BP')):
        with tab:
            _rendre_onglet_phase(phase, res_csv, nom_fichier, type_comb, hum_comb, T_atm, pression,
                                  baseline_flow, bg_pm_raw, bg_co_raw, bg_co2_ppm, demo, t_min, df_taux0)

    def _phase_prete(p):
        vals = (st.session_state.get(f'mb_{p}'), st.session_state.get(f'me_{p}'),
                st.session_state.get(f'td_{p}'), st.session_state.get(f'mc_{p}'),
                st.session_state.get(f'tf_{p}'))
        if any(v is None for v in vals):
            return False
        mb, me, t0, mc, tf = vals
        return mc < mb and tf > t0

    st.markdown('')
    phases_saisies = all(_phase_prete(p) for p in ('HP', 'MP', 'BP'))
    if st.button('Analyser les 3 phases d\'un coup', type='primary', use_container_width=True,
                 disabled=not phases_saisies, key='btn_analyser_3'):
        with st.spinner('Calculs HP + MP + BP en cours...'):
            for p in ('HP', 'MP', 'BP'):
                _lancer_analyse(p, res_csv, nom_fichier, type_comb, hum_comb, T_atm, pression,
                                 baseline_flow, bg_pm_raw, bg_co_raw, bg_co2_ppm)
        st.rerun()
    if not phases_saisies:
        st.caption('Remplissez des pesées cohérentes pour les 3 phases pour utiliser ce bouton.')

    col_retour, _, col_suivant = st.columns([1, 3, 1])
    with col_retour:
        if st.button('Retour', use_container_width=True, key='btn_retour_4'):
            st.session_state.etape = 3
            st.rerun()
    with col_suivant:
        disabled = len(st.session_state.resultats) < 3
        if st.button('Suivant', type='primary', use_container_width=True,
                     disabled=disabled, key='btn_suivant_4'):
            st.session_state.etape = 5
            st.rerun()
        if disabled:
            st.caption('Analysez les 3 phases (HP, MP, BP) pour accéder au rapport.')


# ─────────────────────────────────────────────────────────────────────
# Étape 5 — Rapport
# ─────────────────────────────────────────────────────────────────────

def etape_5_rapport():
    st.subheader('Rapport')
    resultats = st.session_state.resultats
    if len(resultats) < 3:
        st.warning('Les 3 phases ne sont pas toutes analysées.')
        if st.button('Retour', key='btn_retour_5_vide'):
            st.session_state.etape = 4
            st.rerun()
        return

    nom_fichier = st.session_state.get('current_csv_name', '')
    analyses = {code: analyser_phase(code, r) for code, r in resultats.items()}
    tier_global = min(a['t_iwa11'] for a in analyses.values())
    bg, col = TIER_BG.get(tier_global, '#F5F5F5'), TIER_COUL.get(tier_global, '#555')

    serie_terminee = st.session_state.get('serie_terminee', False)
    if not serie_terminee:
        ui.render_todo_box('Vérifiez le Tier global et le tableau ci-dessous, puis exportez ou '
                           'enregistrez ce test avant de passer au suivant.')

    st.markdown(
        f'<div class="tier-banner" style="background:{bg};border-left:8px solid {col};'
        f'padding:22px 28px;margin-bottom:16px;">'
        f'<span style="font-size:2.1em;font-weight:700;color:{col};">'
        f'Tier {tier_global} — {TIER_LABEL[tier_global]}</span><br>'
        f'<span style="color:#555;font-size:0.95em;">'
        f'Classement IWA-11 = phase la plus défavorable sur les 3</span></div>',
        unsafe_allow_html=True,
    )

    phases_ordre = [c for c in ('HP', 'MP', 'BP') if c in analyses]
    couleurs = {'HP': '#1D4E89', 'MP': '#D08A2E', 'BP': '#5E9C98'}
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(x=phases_ordre, y=[analyses[c]['co_mjd'] for c in phases_ordre],
                              marker_color=[couleurs[c] for c in phases_ordre], name='CO (g/MJd)'))
    for tier_n, seuil in SEUILS_CO_G_MJD.items():
        fig_bar.add_hline(y=seuil, line_dash='dot', line_color='#999',
                           annotation_text=f'Tier {tier_n}', annotation_position='right',
                           annotation_font=dict(size=10, color='#777'))
    fig_bar.update_layout(title='CO par phase vs seuils IWA-11', yaxis_title='CO (g/MJd)',
                           height=340, margin=dict(l=50, r=90, t=50, b=40),
                           plot_bgcolor='white', paper_bgcolor='white')
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown('**Tableau complet des 3 phases**')
    synth_rows = [{
        'Phase': f"{a['code']} — {a['label']}",
        'CO (g/MJd)': f"{a['co_mjd']:.2f}",
        'PM2.5 (mg/MJd)': f"{a['pm_mjd']:.1f}",
        'Efficacité (%)': f"{a['eff']:.1f}",
        'MCE (%)': f"{a['mce']:.2f}",
        'Tier': f"Tier {a['t_iwa11']}",
        'Facteur limitant': a['limitant'],
    } for a in analyses.values()]
    st.dataframe(pd.DataFrame(synth_rows).set_index('Phase'), use_container_width=True)

    with st.expander("Informations complémentaires de ce test (optionnel)"):
        ci1, ci2 = st.columns(2)
        st.session_state['date_test'] = ci1.text_input('Date du test (JJ/MM/AAAA)',
            value=st.session_state.get('date_test', ''), placeholder='ex. 01/12/2022', key='r5_date')
        st.session_state['observations_operateur'] = ci2.text_area(
            "Observations de l'opérateur",
            value=st.session_state.get('observations_operateur', ''), height=80,
            placeholder='Incidents, rechargements, conditions particulières…', key='r5_observations')

    st.markdown(generer_texte(
        analyses, nom_fichier,
        nom_testeur  = st.session_state.get('nom_testeur', ''),
        nom_fourneau = st.session_state.serie.get('foyer', ''),
        date_test    = st.session_state.get('date_test', ''),
        lieu_test    = st.session_state.get('lieu_test', ''),
        n_replique   = st.session_state.test_n,
        remarques    = st.session_state.get('observations_operateur', ''),
    ))

    with st.expander('Recommandations'):
        for cat, rec in generer_recommandations(analyses):
            st.markdown(f'**{cat}**')
            st.markdown(f'> {rec}')

    nb_tests = st.session_state.serie.get('nb_tests', 3)
    st.markdown('**Tests de la série**')
    cols_tests = st.columns(nb_tests)
    n_enreg = len(st.session_state.tests_accumules)
    for i in range(nb_tests):
        n = i + 1
        with cols_tests[i]:
            if n <= n_enreg:
                st.markdown(f'<div class="lems-badge-ok" style="display:block;text-align:center;">'
                            f'Test {n}</div>', unsafe_allow_html=True)
            elif n == st.session_state.test_n:
                st.markdown(f'<div class="lems-badge-todo" style="display:block;text-align:center;">'
                            f'Test {n} (en cours)</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="lems-badge-todo" style="display:block;text-align:center;'
                            f'opacity:0.5;">Test {n}</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown('**Exports**')
    ctx_rapport = _construire_contexte_rapport()
    col_pdf, col_xls = st.columns(2)
    with col_pdf:
        pdf_bytes = rapport_pdf.generer_rapport_test(analyses, resultats, ctx_rapport)
        st.download_button('Exporter en PDF', data=pdf_bytes,
            file_name=f"{ctx_rapport['numero_rapport']}.pdf",
            mime='application/pdf', use_container_width=True)
        st.caption(f"Rapport n° {ctx_rapport['numero_rapport']}")
    with col_xls:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            id_data = {
                'Champ': ['Fourneau / foyer', 'N° de réplique (test)', 'Testeur(s)', 'Date du test',
                          'Lieu', "Observations de l'opérateur", 'Fichier CSV'],
                'Valeur': [
                    st.session_state.serie.get('foyer', ''), str(st.session_state.test_n),
                    st.session_state.get('nom_testeur', ''), st.session_state.get('date_test', ''),
                    st.session_state.get('lieu_test', ''),
                    st.session_state.get('observations_operateur', ''),
                    nom_fichier,
                ],
            }
            pd.DataFrame(id_data).to_excel(writer, sheet_name='Identification', index=False)
            for code in ('HP', 'MP', 'BP'):
                r = resultats.get(code)
                if not r:
                    continue
                ligne = {
                    'Fichier CSV': r.get('_fichier', ''),
                    'Durée (min)': r['duree_min'],
                    'Masse comb. sec (g)': r['thermique']['bois_brule_sec_kg'] * 1000,
                    'Eff. sans charbon (%)': r['thermique']['efficacite_sans_char_pct'],
                    'Eff. avec charbon (%)': r['thermique']['efficacite_avec_char_pct'],
                    'Taux combustion (g/min)': r['thermique']['taux_combustion_g_min'],
                    'Puissance feu (W)': r['thermique']['puissance_feu_kW'] * 1000,
                    'Puissance cuisson (W)': r['thermique']['puissance_cuis_kW'] * 1000,
                    'MCE (%)': r['stats']['MCE_pct'],
                    'CO total (g)': r['totaux']['CO_total_g'],
                    'CO / énergie utile (g/MJ)': r['normalises']['CO_par_utile_g_MJ'],
                    'PM2.5 total (mg)': r['totaux']['PM_total_mg'],
                    'PM2.5 / énergie utile (mg/MJ)': r['normalises']['PM_par_utile_mg_MJ'],
                    'CO2 total (g)': r['totaux']['CO2_total_g'],
                    'Tier IWA-11': r['tier'],
                }
                pd.DataFrame([ligne]).to_excel(writer, sheet_name=code, index=False)
        st.download_button('Exporter en Excel', data=buffer.getvalue(),
            file_name=f'rapport_LEMS_{nom_fichier.replace(".csv", "")}.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True)

    st.divider()

    if serie_terminee:
        st.subheader('Rapport de série — Statistiques ISO 19867-1')
        st.caption(f"{len(st.session_state.tests_accumules)} tests enregistrés · "
                   f"Moyenne ± écart-type (ddof=1)")
        stats_rows = []
        for code in ('HP', 'MP', 'BP'):
            vals_eff = [t['phases'][code]['eff'] for t in st.session_state.tests_accumules if code in t['phases']]
            vals_co  = [t['phases'][code]['co_g_min'] for t in st.session_state.tests_accumules if code in t['phases']]
            vals_pm  = [t['phases'][code]['pm_mg_min'] for t in st.session_state.tests_accumules if code in t['phases']]
            if not vals_eff:
                continue
            if len(vals_eff) > 1:
                eff_str = f'{np.mean(vals_eff):.1f} +/- {np.std(vals_eff, ddof=1):.1f}'
                co_str  = f'{np.mean(vals_co):.4f} +/- {np.std(vals_co, ddof=1):.4f}'
                pm_str  = f'{np.mean(vals_pm):.4f} +/- {np.std(vals_pm, ddof=1):.4f}'
            else:
                eff_str, co_str, pm_str = f'{vals_eff[0]:.1f}', f'{vals_co[0]:.4f}', f'{vals_pm[0]:.4f}'
            stats_rows.append({'Phase': code, 'Eff. moy. (%)': eff_str, 'CO moy. (g/min)': co_str,
                               'PM2.5 moy. (mg/min)': pm_str, 'N tests': len(vals_eff)})
        if stats_rows:
            st.dataframe(pd.DataFrame(stats_rows).set_index('Phase'), use_container_width=True)
        st.caption("Les boutons « Exporter » ci-dessus produisent le rapport du dernier test effectué.")

        if 'rapport_meta_serie' not in st.session_state:
            st.session_state['rapport_meta_serie'] = {
                'numero'   : report_counter.numero_rapport_suivant(),
                'genere_le': datetime.datetime.now(),
            }
        meta_serie = st.session_state['rapport_meta_serie']
        ctx_serie = dict(_construire_contexte_rapport())
        ctx_serie['numero_rapport'] = meta_serie['numero']
        ctx_serie['date_emission'] = meta_serie['genere_le'].date()
        ctx_serie['genere_le'] = meta_serie['genere_le']
        pdf_serie = rapport_pdf.generer_rapport_serie(
            ctx_serie, st.session_state.tests_accumules, analyses, resultats)
        st.download_button('Exporter le rapport de série (PDF)', data=pdf_serie,
            file_name=f"{meta_serie['numero']}_serie.pdf",
            mime='application/pdf', use_container_width=True)
        st.caption(f"Rapport de série n° {meta_serie['numero']}")

        if st.button('Retour', use_container_width=True, key='btn_retour_5_fin'):
            st.session_state.etape = 4
            st.rerun()
    else:
        dernier = st.session_state.test_n >= nb_tests
        col_retour, _, col_action = st.columns([1, 2, 1.6])
        with col_retour:
            if st.button('Retour', use_container_width=True, key='btn_retour_5'):
                st.session_state.etape = 4
                st.rerun()
        with col_action:
            if dernier:
                if st.button('Terminer la série', type='primary', use_container_width=True,
                             key='btn_terminer_serie'):
                    _enregistrer_test_courant(tier_global, analyses, resultats)
                    st.session_state['serie_terminee'] = True
                    st.rerun()
            else:
                if st.button('Enregistrer et passer au test suivant', type='primary',
                             use_container_width=True, key='btn_suivant_test'):
                    _enregistrer_test_courant(tier_global, analyses, resultats)
                    st.session_state.etape = 6
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Étape 6 — Enregistrement
# ─────────────────────────────────────────────────────────────────────

def etape_6_enregistrement():
    nb_tests = st.session_state.serie.get('nb_tests', 3)
    n = st.session_state.test_n
    dernier_test = st.session_state.tests_accumules[-1] if st.session_state.tests_accumules else {}
    tier = dernier_test.get('tier', '?')

    with st.container(border=True):
        st.markdown(f'### Test {n} enregistré · Tier global {tier}')
        st.progress(min(1.0, n / nb_tests), text=f'{n} sur {nb_tests} tests de la série')

        col_garde, col_refaire = st.columns(2)
        with col_garde:
            st.markdown('**Conservé pour le test suivant**')
            st.caption('Foyer, protocole, type de combustible, humidité, température ambiante, '
                       'pression, nombre de pots, eau par pot.')
        with col_refaire:
            st.markdown('**À refaire**')
            st.caption('Fichier CSV, intervalles de phase, pesées, températures de l\'eau.')

        st.markdown('')
        if st.button(f'Commencer le test {n + 1} sur {nb_tests}', type='primary',
                     use_container_width=True, key='btn_test_suivant'):
            _reset_test_data()
            st.session_state.test_n += 1
            st.session_state.etape = 2
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────

etape = st.session_state.etape
n_phases_ok = len(st.session_state.resultats)
if etape >= 1 and st.session_state.serie:
    ui.render_stepper(min(etape, 6), n_phases_ok)
elif etape == 1:
    ui.render_stepper(1, 0)

{
    1: etape_1_serie,
    2: etape_2_fichier,
    3: etape_3_phases,
    4: etape_4_pesees,
    5: etape_5_rapport,
    6: etape_6_enregistrement,
}.get(etape, etape_1_serie)()
