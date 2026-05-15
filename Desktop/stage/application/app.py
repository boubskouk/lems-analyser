#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEMS Analyser — Application Streamlit
Conforme ISO 19867-1 · Classement ISO/IWA-11
"""

import io, os, tempfile
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from import_csv import lire_csv
from calculs import (analyser, COMBUSTIBLES, LABEL_TIER,
                     appliquer_calibration, calculer_taux_emission)

# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title='LEMS Analyser',
    page_icon='🔥',
    layout='wide',
    initial_sidebar_state='expanded',
)
st.title('🔥 LEMS Analyser — Analyse des émissions de foyers biomasse')
st.caption('Conforme ISO 19867-1 · Classement ISO/IWA-11 · CERER / ESP-UCAD')
st.warning('⚠️ Version bêta — résultats en cours de validation. Ne pas utiliser pour des rapports officiels.')

CSV_TEST       = os.path.join(os.path.dirname(__file__), 'csv', 'T1_foyer_kevin.csv')
DOSSIER_DEFAUT = r'C:\Emissions-Output'

PHASES_LABELS = {'HP': 'Haute Puissance', 'MP': 'Moyenne Puissance', 'BP': 'Basse Puissance'}

TEST_DEFAULTS = {
    'HP': dict(mb=1.820, mc=0.062, np=4, me=2.5, td=21.0, tf=91.5, hmc=4.41),
    'MP': dict(mb=0.900, mc=0.030, np=4, me=2.5, td=21.0, tf=91.5, hmc=4.41),
    'BP': dict(mb=0.400, mc=0.010, np=4, me=2.5, td=21.0, tf=91.5, hmc=4.41),
}

# ─────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────
if 'resultats' not in st.session_state:
    st.session_state.resultats = {}   # {'HP': result, 'MP': result, 'BP': result}
if 'prev_mode_test' not in st.session_state:
    st.session_state.prev_mode_test = False

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _adj(key, delta, min_val=None):
    val = round(st.session_state[key] + delta, 1)
    if min_val is not None:
        val = max(min_val, val)
    st.session_state[key] = val


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


def lister_csv(dossier):
    try:
        fichiers = [f for f in os.listdir(dossier) if f.lower().endswith('.csv')]
        fichiers.sort(key=lambda f: os.path.getmtime(os.path.join(dossier, f)), reverse=True)
        return fichiers
    except Exception:
        return []


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


# ─────────────────────────────────────────────────────────────────────
# Barre latérale
# ─────────────────────────────────────────────────────────────────────

with st.sidebar:
    mode_test = st.toggle('🧪 Mode test (T1 — Foyer Kevin)', value=False)

    # Quand le mode test change, on réinitialise les champs terrain
    if mode_test != st.session_state.prev_mode_test:
        st.session_state.prev_mode_test = mode_test
        for p in ['HP', 'MP', 'BP']:
            td = TEST_DEFAULTS[p]
            for k in [f'mb_{p}', f'mc_{p}', f'hc_{p}', f'np_{p}']:
                if k in st.session_state:
                    del st.session_state[k]
            for j in range(4):
                for k in [f'ni_me_{p}_{j}', f'ni_td_{p}_{j}', f'ni_tf_{p}_{j}']:
                    if k in st.session_state:
                        del st.session_state[k]
        st.rerun()

    st.divider()

    # ── Sélecteur de phase ────────────────────────────────────────────
    st.header('📊 Phase à analyser')
    phase = st.radio('Phase', ['HP', 'MP', 'BP'], horizontal=True,
                     label_visibility='collapsed')

    # Statut des phases
    cols_stat = st.columns(3)
    for i, p in enumerate(['HP', 'MP', 'BP']):
        if p in st.session_state.resultats:
            cols_stat[i].success(f'✓ {p}')
        else:
            cols_stat[i].warning(f'· {p}')

    st.divider()

    # ── Source CSV ────────────────────────────────────────────────────
    st.header('📂 Fichier CSV')

    _CSV  = 'current_csv'
    _NAME = 'current_csv_name'

    if mode_test:
        if _CSV not in st.session_state:
            try:
                st.session_state[_CSV]  = lire_csv(CSV_TEST)
                st.session_state[_NAME] = 'T1_foyer_kevin.csv'
            except Exception as e:
                st.error(f'Fichier test introuvable : {e}')
        st.info(f'Fichier chargé : {st.session_state.get(_NAME, "")}')
    else:
        dossier  = st.text_input('Dossier des CSV', value=DOSSIER_DEFAUT, key='dossier_csv')
        csv_list = lister_csv(dossier)

        if csv_list:
            prev        = st.session_state.get(_NAME, '')
            default_idx = csv_list.index(prev) if prev in csv_list else 0
            choix       = st.selectbox('Choisir un fichier', csv_list,
                                        index=default_idx, key='sel_csv')
            if choix != st.session_state.get(_NAME) or _CSV not in st.session_state:
                try:
                    st.session_state[_CSV]  = lire_csv(os.path.join(dossier, choix))
                    st.session_state[_NAME] = choix
                except Exception as e:
                    st.error(f'Erreur lecture : {e}')
        else:
            if os.path.isdir(dossier):
                st.warning('Aucun fichier CSV dans ce dossier.')
            else:
                st.warning('Dossier introuvable.')
            uploaded = st.file_uploader('Charger un CSV manuellement', type=['csv'],
                                         key='upload_csv')
            if uploaded and uploaded.name != st.session_state.get(_NAME):
                try:
                    st.session_state[_CSV]  = lire_upload(uploaded)
                    st.session_state[_NAME] = uploaded.name
                except Exception as e:
                    st.error(f'Erreur : {e}')

        if _NAME in st.session_state:
            st.caption(f'Chargé : {st.session_state[_NAME]}')

    res_csv     = st.session_state.get(_CSV)
    nom_fichier = st.session_state.get(_NAME, '')

    # ── Mesures de fond ───────────────────────────────────────────────
    st.divider()
    st.header('📡 Mesures de fond')

    if res_csv is not None:
        bg_pm_a, bg_co_a, bg_co2_a, bg_fl_a = estimer_fond(res_csv['donnees'])
    else:
        bg_pm_a, bg_co_a, bg_co2_a, bg_fl_a = 0.0, 0.0, 615.0, 9900.0

    bg_pm_raw  = st.number_input('PM fond (logunits)',  value=bg_pm_a,  step=0.1, format='%.1f', key=f'bpm_{phase}')
    bg_co_raw  = st.number_input('CO fond (logunits)',  value=bg_co_a,  step=0.1, format='%.1f', key=f'bco_{phase}')
    bg_co2_ppm = st.number_input('CO2 fond (ppm)',      value=bg_co2_a, step=1.0, format='%.1f', key=f'bco2_{phase}')
    baseline_flow = st.number_input('Zero-flux Flow',   value=bg_fl_a,  step=10.0, format='%.0f', key=f'bfl_{phase}')

    # ── Conditions ────────────────────────────────────────────────────
    st.divider()
    st.header('🌡️ Conditions')
    T_atm    = st.number_input('T ambiante (°C)',    value=29.0,   step=0.5, format='%.1f', key=f'ta_{phase}')
    pression = st.number_input('Pression (hPa)',     value=1012.0, step=1.0, format='%.1f', key=f'pr_{phase}')

    # ── Données terrain ───────────────────────────────────────────────
    st.divider()
    st.header('🔥 Données terrain')

    td = TEST_DEFAULTS[phase]
    liste_comb = list(COMBUSTIBLES.keys())
    type_comb  = st.selectbox('Type de combustible', liste_comb, index=0, key=f'tc_{phase}')
    hum_comb   = st.number_input('Humidité combustible (%)', min_value=0.0, max_value=100.0,
                                  value=td['hmc'] if mode_test else 6.0,
                                  step=0.5, format='%.1f', key=f'hc_{phase}')
    c1, c2 = st.columns(2)
    mb = c1.number_input('Combustible (kg)', min_value=0.0,
                          value=td['mb'] if mode_test else 1.0,
                          step=0.01, format='%.3f', key=f'mb_{phase}')
    mc = c2.number_input('Charbon (kg)', min_value=0.0,
                          value=td['mc'] if mode_test else 0.0,
                          step=0.001, format='%.3f', key=f'mc_{phase}')

    nb_pots = st.selectbox('Nombre de pots', [1, 2, 3, 4],
                            index=td['np'] - 1 if mode_test else 0,
                            key=f'np_{phase}')
    pots = []
    for j in range(nb_pots):
        k_me = f'ni_me_{phase}_{j}'
        k_t0 = f'ni_td_{phase}_{j}'
        k_tf = f'ni_tf_{phase}_{j}'
        if k_me not in st.session_state: st.session_state[k_me] = float(td['me'] if mode_test else 2.0)
        if k_t0 not in st.session_state: st.session_state[k_t0] = float(td['td'] if mode_test else 20.0)
        if k_tf not in st.session_state: st.session_state[k_tf] = float(td['tf'] if mode_test else 90.0)

        st.caption(f'Pot {j + 1}')
        ca, cb, cc = st.columns([1, 4, 1])
        ca.button('−', key=f'me_m_{phase}_{j}', use_container_width=True,
                  on_click=_adj, args=(k_me, -0.1), kwargs={'min_val': 0.1})
        cb.number_input('Eau (kg)', step=0.1, format='%.1f', min_value=0.1, key=k_me)
        cc.button('+', key=f'me_p_{phase}_{j}', use_container_width=True,
                  on_click=_adj, args=(k_me, 0.1))

        ca, cb, cc = st.columns([1, 4, 1])
        ca.button('−', key=f'td_m_{phase}_{j}', use_container_width=True,
                  on_click=_adj, args=(k_t0, -1.0))
        cb.number_input('T début (°C)', step=1.0, format='%.1f', key=k_t0)
        cc.button('+', key=f'td_p_{phase}_{j}', use_container_width=True,
                  on_click=_adj, args=(k_t0, 1.0))

        ca, cb, cc = st.columns([1, 4, 1])
        ca.button('−', key=f'tf_m_{phase}_{j}', use_container_width=True,
                  on_click=_adj, args=(k_tf, -1.0))
        cb.number_input('T fin (°C)', step=1.0, format='%.1f', key=k_tf)
        cc.button('+', key=f'tf_p_{phase}_{j}', use_container_width=True,
                  on_click=_adj, args=(k_tf, 1.0))

        pots.append({
            'masse_eau': st.session_state[k_me],
            'T_debut'  : st.session_state[k_t0],
            'T_fin'    : st.session_state[k_tf],
        })

    # ── Pesée gravimétrique du filtre PM ─────────────────────────────
    st.divider()
    st.header('⚖️ Filtre PM2.5 (optionnel)')
    st.caption('Laisser à 0 si pas de pesée de filtre.')
    f1, f2 = st.columns(2)
    filtre_avant = f1.number_input('Filtre avant (mg)', min_value=0.0,
                                    value=0.0, step=0.001, format='%.3f',
                                    key=f'fa_{phase}')
    filtre_apres = f2.number_input('Filtre après (mg)', min_value=0.0,
                                    value=0.0, step=0.001, format='%.3f',
                                    key=f'fp_{phase}')
    if filtre_apres > filtre_avant > 0:
        pm_gravi = round(filtre_apres - filtre_avant, 3)
        st.success(f'PM gravimétrique : **{pm_gravi} mg**')
    elif filtre_apres > 0 and filtre_apres <= filtre_avant:
        st.warning('Filtre après doit être > filtre avant.')

    # ── Bouton analyser ───────────────────────────────────────────────
    st.divider()
    if st.button(f'▶  Analyser la phase {phase}', type='primary',
                 use_container_width=True, disabled=(res_csv is None)):
        donnees_ext = {
            'type_combustible': type_comb,
            'masse_bois_kg'   : mb,
            'masse_charbon_kg': mc,
            'humidite_pct'    : hum_comb,
            'pots'            : pots,
            'T_atm'           : T_atm,
            'p_Pa'            : pression * 100.0,
            'baseline_flow'   : baseline_flow,
            'bg_pm_raw'       : bg_pm_raw,
            'bg_co_raw'       : bg_co_raw,
            'bg_co2_ppm'      : bg_co2_ppm,
            'filtre_avant_mg' : filtre_avant,
            'filtre_apres_mg' : filtre_apres,
        }
        _iv = st.session_state.get(f'intervalle_{phase}')
        if _iv:
            donnees_ext['t_debut_s'] = _iv[0] * 60.0
            donnees_ext['t_fin_s']   = _iv[1] * 60.0
        with st.spinner(f'Calculs phase {phase}...'):
            result = analyser(res_csv, donnees_ext)
        result['_fichier'] = nom_fichier
        # PM gravimétrique
        if filtre_apres > filtre_avant > 0:
            result['_pm_gravi_mg'] = round(filtre_apres - filtre_avant, 3)
        else:
            result['_pm_gravi_mg'] = None
        st.session_state.resultats[phase] = result
        st.success(f'Phase {phase} analysée — {result["duree_min"]:.1f} min')
        st.rerun()

    if res_csv is None:
        st.info('Chargez un CSV pour analyser.')

    if st.session_state.resultats:
        st.divider()
        if st.button('🗑️  Réinitialiser', use_container_width=True):
            st.session_state.resultats = {}
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Zone principale
# ─────────────────────────────────────────────────────────────────────

# ── Aperçu CSV ────────────────────────────────────────────────────────
if res_csv is not None:
    df0       = res_csv['donnees']
    duree_tot = (df0['seconds'].max() - df0['seconds'].min()) / 60.0

    st.subheader(f'📄 {nom_fichier} — Phase {phase} ({PHASES_LABELS[phase]})')
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Date',          res_csv['date'])
    m2.metric('Heure début',   res_csv['heure'])
    m3.metric('Durée totale',  f'{duree_tot:.1f} min')
    m4.metric('Nb mesures',    f'{len(df0)}')

    calibr0  = res_csv['calibration']
    pm_cal0  = calibr0[2] if len(calibr0) > 2 and calibr0[2] != 0 else 0.77
    co_cal0  = calibr0[0] if len(calibr0) > 0 and calibr0[0] != 0 else 0.03863
    df_cal0  = appliquer_calibration(df0, calibr0)
    df_taux0 = calculer_taux_emission(
        df_cal0, baseline_flow, T_atm,
        bg_pm_ug=bg_pm_raw * pm_cal0,
        bg_co_ppm=bg_co_raw * co_cal0,
        bg_co2_ppm=bg_co2_ppm,
        p_Pa=pression * 100.0,
    )
    t_min     = df0['seconds'] / 60.0
    t_min_val = float(t_min.min())
    t_max_val = float(t_min.max())

    # ── Slider de sélection de l'intervalle ──────────────────────────
    k_slider = f'intervalle_{phase}'
    if k_slider not in st.session_state:
        st.session_state[k_slider] = (t_min_val, t_max_val)

    st.markdown('**⏱️ Sélectionner l\'intervalle de la phase (minutes)**')
    intervalle = st.slider(
        'Intervalle',
        min_value=round(t_min_val, 1),
        max_value=round(t_max_val, 1),
        value=st.session_state[k_slider],
        step=0.5,
        label_visibility='collapsed',
        key=k_slider,
    )
    t_debut_min, t_fin_min = intervalle
    st.caption(f'Début : **{t_debut_min:.1f} min**  |  Fin : **{t_fin_min:.1f} min**  |  Durée sélectionnée : **{t_fin_min - t_debut_min:.1f} min**')

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t_min, y=df_taux0['CO_ppm_zeroed'],
                             name='CO (ppm)', line=dict(color='#2196F3', width=1)))
    fig.add_trace(go.Scatter(x=t_min, y=df_taux0['PM_ug_zeroed'],
                             name='PM (ug/m3)', line=dict(color='#F44336', width=1),
                             yaxis='y2'))
    # Zone sélectionnée en vert transparent
    fig.add_vrect(
        x0=t_debut_min, x1=t_fin_min,
        fillcolor='rgba(0,200,0,0.12)',
        line=dict(color='green', width=2, dash='dash'),
        annotation_text=f'Phase sélectionnée ({t_fin_min - t_debut_min:.1f} min)',
        annotation_position='top left',
        annotation_font=dict(size=13, color='green'),
    )
    # Ligne de début (verte)
    fig.add_vline(x=t_debut_min, line_color='green',  line_width=3,
                  annotation_text=f'Début {t_debut_min:.1f} min',
                  annotation_position='bottom left',
                  annotation_font=dict(size=12, color='green'))
    # Ligne de fin (rouge foncé)
    fig.add_vline(x=t_fin_min,   line_color='darkred', line_width=3,
                  annotation_text=f'Fin {t_fin_min:.1f} min',
                  annotation_position='bottom right',
                  annotation_font=dict(size=12, color='darkred'))
    fig.update_layout(
        xaxis=dict(
            title='Temps (min)',
            title_font=dict(size=16, color='black'),
            tickfont=dict(size=15, color='black'),
            showgrid=True,
            gridcolor='#e0e0e0',
        ),
        yaxis=dict(
            title='CO (ppm)',
            title_font=dict(size=14, color='#2196F3'),
            tickfont=dict(size=13, color='#2196F3'),
        ),
        yaxis2=dict(
            title='PM (µg/m³)',
            title_font=dict(size=14, color='#F44336'),
            tickfont=dict(size=13, color='#F44336'),
            overlaying='y', side='right',
        ),
        legend=dict(orientation='h', y=1.08, font=dict(size=13)),
        hovermode='x unified', plot_bgcolor='white', paper_bgcolor='white',
        margin=dict(l=70, r=70, t=40, b=50), height=320,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    t_debut_min, t_fin_min = None, None
    st.info('👈 Chargez un fichier CSV dans la barre latérale pour commencer.')

st.divider()

# ─────────────────────────────────────────────────────────────────────
# Tableau de résultats
# ─────────────────────────────────────────────────────────────────────

LIGNES_DEF = [
    ('Durée',                            'min',    lambda r: r['duree_min']),
    ('Combustible sec brûlé',            'g',      lambda r: r['thermique']['bois_brule_sec_kg'] * 1000),
    ('Humidité combustible',             '%',      lambda r: r['thermique'].get('humidite_pct', None)),
    ('Efficacité thermique (s/charbon)', '%',      lambda r: r['thermique']['efficacite_sans_char_pct']),
    ('Efficacité thermique (a/charbon)', '%',      lambda r: r['thermique']['efficacite_avec_char_pct']),
    ('Taux de combustion (sec)',         'g/min',  lambda r: r['thermique']['taux_combustion_g_min']),
    ('Puissance feu',                    'W',      lambda r: r['thermique']['puissance_feu_kW'] * 1000),
    ('Puissance cuisson',                'W',      lambda r: r['thermique']['puissance_cuis_kW'] * 1000),
    ('MCE',                              '%',      lambda r: r['stats']['MCE_pct']),
    ('CO moyen',                         'ppm',    lambda r: r['stats']['CO_moy_ppm']),
    ('CO total',                         'g',      lambda r: r['totaux']['CO_total_g']),
    ('CO / masse combustible',           'g/kg',   lambda r: r['normalises']['CO_par_masse_g_kg']),
    ('CO / énergie combustible',         'g/MJ',   lambda r: r['normalises']['CO_par_energie_g_MJ']),
    ('CO / énergie utile',               'g/MJ',   lambda r: r['normalises']['CO_par_utile_g_MJ']),
    ('CO / temps',                       'g/min',  lambda r: r['normalises']['CO_par_temps_g_min']),
    ('PM2.5 moyen',                      'ug/m3',  lambda r: r['stats']['PM_moy_ug_m3']),
    ('PM2.5 total',                      'mg',     lambda r: r['totaux']['PM_total_mg']),
    ('PM2.5 / masse combustible',        'mg/kg',  lambda r: r['normalises']['PM_par_masse_mg_kg']),
    ('PM2.5 / énergie combustible',      'mg/MJ',  lambda r: r['normalises']['PM_par_energie_mg_MJ']),
    ('PM2.5 / énergie utile',            'mg/MJ',  lambda r: r['normalises']['PM_par_utile_mg_MJ']),
    ('PM2.5 / temps',                    'mg/min', lambda r: r['normalises']['PM_par_temps_mg_min']),
    ('CO2 moyen (excès)',                'ppm',    lambda r: r['stats']['CO2_moy_ppm']),
    ('CO2 total',                        'g',      lambda r: r['totaux']['CO2_total_g']),
    ('CO2 / temps',                      'g/min',  lambda r: r['normalises']['CO2_par_temps_g_min']),
    ('Débit tunnel moyen',               'm3/min', lambda r: r['stats']['debit_moy_m3_min']),
    ('PM2.5 gravimétrique',              'mg',     lambda r: r.get('_pm_gravi_mg')),
    ('PM2.5 gravi / masse comb.',        'mg/kg',  lambda r: (
        r['_pm_gravi_mg'] / (r['thermique']['bois_brule_sec_kg'] * 1000) * 1000
        if r.get('_pm_gravi_mg') and r['thermique']['bois_brule_sec_kg'] > 0 else None)),
    ('PM2.5 gravi / énergie utile',      'mg/MJ',  lambda r: (
        r['_pm_gravi_mg'] / (r['thermique']['Q_utile_kJ'] / 1000.0)
        if r.get('_pm_gravi_mg') and r['thermique'].get('Q_utile_kJ', 0) > 0 else None)),
    ('Tier IWA-11',                      '',       lambda r: r['tier']),
]


def tableau_phase(code):
    r = st.session_state.resultats.get(code)
    if r is None:
        st.info(f'Phase {code} non analysée. '
                f'Sélectionnez "{code}" → chargez le CSV → cliquez "Analyser la phase {code}".')
        return
    fichier = r.get('_fichier', '')
    if fichier:
        st.caption(f'Fichier : {fichier}')
    rows = []
    for label, unite, fn in LIGNES_DEF:
        try:
            val = fn(r)
        except Exception:
            val = None
        if isinstance(val, float):
            val_str = f'{val:.4g}'
        elif val is None:
            val_str = ''
        else:
            val_str = str(val)
        rows.append({'Métrique': label, 'Unité': unite, 'Valeur': val_str})
    df_tab = pd.DataFrame(rows).set_index('Métrique')
    st.dataframe(df_tab, use_container_width=True)
    tier = r['tier']
    st.info(f'**Tier phase {code} : Tier {tier} — {LABEL_TIER[tier]}**')


st.subheader('📋 Résultats par phase')
tab_hp, tab_mp, tab_bp, tab_global = st.tabs([
    '🔴 Haute Puissance (HP)',
    '🟡 Moyenne Puissance (MP)',
    '🔵 Basse Puissance (BP)',
    '📊 Rapport global',
])

with tab_hp:
    tableau_phase('HP')

with tab_mp:
    tableau_phase('MP')

with tab_bp:
    tableau_phase('BP')

# ─────────────────────────────────────────────────────────────────────
# Rapport global
# ─────────────────────────────────────────────────────────────────────

with tab_global:
    phases_ok = {c: r for c, r in st.session_state.resultats.items() if r is not None}

    if not phases_ok:
        st.info('Analysez au moins une phase pour voir le rapport global.')
    else:
        st.caption(f'{len(phases_ok)}/3 phases analysées')

        metriques_recap = [
            ('Eff. therm. sans charbon (%)', lambda r: r['thermique']['efficacite_sans_char_pct']),
            ('Eff. therm. avec charbon (%)', lambda r: r['thermique']['efficacite_avec_char_pct']),
            ('Puissance cuisson (W)',         lambda r: r['thermique']['puissance_cuis_kW'] * 1000),
            ('Taux de combustion (g/min)',    lambda r: r['thermique']['taux_combustion_g_min']),
            ('PM2.5 / énergie utile (mg/MJ)',lambda r: r['normalises']['PM_par_utile_mg_MJ']),
            ('CO / énergie utile (g/MJ)',     lambda r: r['normalises']['CO_par_utile_g_MJ']),
            ('CO total (g)',                  lambda r: r['totaux']['CO_total_g']),
            ('CO2 total (g)',                 lambda r: r['totaux']['CO2_total_g']),
            ('MCE (%)',                        lambda r: r['stats']['MCE_pct']),
            ('Tier IWA-11',                   lambda r: r['tier']),
        ]

        recap_rows = []
        for label, fn in metriques_recap:
            row = {'Métrique': label}
            for code in ['HP', 'MP', 'BP']:
                r = phases_ok.get(code)
                if r:
                    try:
                        v = fn(r)
                        row[code] = f'{v:.4g}' if isinstance(v, float) else str(v)
                    except Exception:
                        row[code] = ''
                else:
                    row[code] = '—'
            recap_rows.append(row)

        df_recap = pd.DataFrame(recap_rows).set_index('Métrique')
        st.dataframe(df_recap, use_container_width=True)

        tier_global = min(r['tier'] for r in phases_ok.values())
        st.success(f'**Tier global du foyer : Tier {tier_global} — {LABEL_TIER[tier_global]}**')

        # ── Export Excel ──────────────────────────────────────────────
        st.divider()
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            for code in ['HP', 'MP', 'BP']:
                r = phases_ok.get(code)
                if not r:
                    continue
                ligne = {
                    'Fichier CSV'             : r.get('_fichier', ''),
                    'Durée (min)'             : r['duree_min'],
                    'Masse comb. sec (g)'     : r['thermique']['bois_brule_sec_kg'] * 1000,
                    'Eff. sans charbon (%)'   : r['thermique']['efficacite_sans_char_pct'],
                    'Eff. avec charbon (%)'   : r['thermique']['efficacite_avec_char_pct'],
                    'Taux combustion (g/min)' : r['thermique']['taux_combustion_g_min'],
                    'Puissance feu (W)'       : r['thermique']['puissance_feu_kW'] * 1000,
                    'Puissance cuisson (W)'   : r['thermique']['puissance_cuis_kW'] * 1000,
                    'MCE (%)'                 : r['stats']['MCE_pct'],
                    'CO total (g)'            : r['totaux']['CO_total_g'],
                    'CO / masse (g/kg)'       : r['normalises']['CO_par_masse_g_kg'],
                    'CO / énergie (g/MJ)'     : r['normalises']['CO_par_energie_g_MJ'],
                    'CO / utile (g/MJ)'       : r['normalises']['CO_par_utile_g_MJ'],
                    'CO / temps (g/min)'      : r['normalises']['CO_par_temps_g_min'],
                    'PM2.5 total (mg)'        : r['totaux']['PM_total_mg'],
                    'PM2.5 / masse (mg/kg)'   : r['normalises']['PM_par_masse_mg_kg'],
                    'PM2.5 / énergie (mg/MJ)' : r['normalises']['PM_par_energie_mg_MJ'],
                    'PM2.5 / utile (mg/MJ)'   : r['normalises']['PM_par_utile_mg_MJ'],
                    'PM2.5 / temps (mg/min)'  : r['normalises']['PM_par_temps_mg_min'],
                    'CO2 total (g)'           : r['totaux']['CO2_total_g'],
                    'Débit tunnel (m3/min)'   : r['stats']['debit_moy_m3_min'],
                    'Tier IWA-11'             : r['tier'],
                }
                pd.DataFrame([ligne]).to_excel(writer, sheet_name=code, index=False)

        st.download_button(
            label='📥 Télécharger rapport Excel',
            data=buffer.getvalue(),
            file_name='rapport_LEMS_WBT.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
