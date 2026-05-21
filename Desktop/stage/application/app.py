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

CSV_TEST       = os.path.join(os.path.dirname(__file__), 'csv', '01-12-2022-Sakkanal-T11.csv')
DOSSIER_DEFAUT = r'C:\Emissions-Output'

PHASES_LABELS = {'HP': 'Haute Puissance', 'MP': 'Moyenne Puissance', 'BP': 'Basse Puissance'}
PHASE_COLORS  = {
    'HP': dict(fill='rgba(33,150,243,0.13)',  border='#1565C0', pos='top left'),
    'MP': dict(fill='rgba(255,152,0,0.13)',   border='#E65100', pos='top right'),
    'BP': dict(fill='rgba(76,175,80,0.13)',   border='#2E7D32', pos='bottom right'),
}

TEST_DEFAULTS = {
    'HP': dict(mb=1.820, mc=0.062, np=4, me=2.5, td=22.0, tf=95.0, hmc=12.0),
    'MP': dict(mb=0.900, mc=0.030, np=4, me=2.5, td=22.0, tf=95.0, hmc=12.0),
    'BP': dict(mb=0.400, mc=0.010, np=4, me=2.5, td=22.0, tf=95.0, hmc=12.0),
}

# ─────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────
if 'resultats' not in st.session_state:
    st.session_state.resultats = {}
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
# Barre latérale — données communes + CSV
# ─────────────────────────────────────────────────────────────────────

with st.sidebar:
    mode_test = st.toggle('🧪 Mode test (Sakkanal-T11, 01-12-2022)', value=False)

    if mode_test != st.session_state.prev_mode_test:
        st.session_state.prev_mode_test = mode_test
        for k in ['tc', 'hc', 'ta', 'pr']:
            if k in st.session_state:
                del st.session_state[k]
        for p in ['HP', 'MP', 'BP']:
            for k in [f'mb_{p}', f'mc_{p}', f'me_{p}', f'td_{p}', f'tf_{p}']:
                if k in st.session_state:
                    del st.session_state[k]
        st.rerun()

    st.divider()

    # ── Source CSV ────────────────────────────────────────────────────
    st.header('📂 Fichier CSV')

    _CSV  = 'current_csv'
    _NAME = 'current_csv_name'

    if mode_test:
        if _CSV not in st.session_state:
            try:
                st.session_state[_CSV]  = lire_csv(CSV_TEST)
                st.session_state[_NAME] = '01-12-2022-Sakkanal-T11.csv'
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

    st.divider()

    # ── Données communes (saisies une seule fois) ─────────────────────
    st.header('📋 Données communes')
    st.caption('Ces paramètres s\'appliquent aux trois phases.')

    td0 = TEST_DEFAULTS['HP']
    liste_comb = list(COMBUSTIBLES.keys())
    type_comb = st.selectbox('Type de combustible', liste_comb, index=0, key='tc')
    hum_comb  = st.number_input('Humidité combustible (%)', min_value=0.0, max_value=100.0,
                                 value=td0['hmc'] if mode_test else 6.0,
                                 step=0.5, format='%.1f', key='hc')
    T_atm    = st.number_input('Température ambiante (°C)', value=29.0,
                                step=0.5, format='%.1f', key='ta')
    pression = st.number_input('Pression atmosphérique (hPa)', value=1012.0,
                                step=1.0, format='%.1f', key='pr')


    # ── Paramètres avancés (zérotage capteurs) ────────────────────────
    if res_csv is not None:
        bg_pm_a, bg_co_a, bg_co2_a, bg_fl_a = estimer_fond(res_csv['donnees'])
        with st.expander('⚙️ Paramètres avancés (zérotage capteurs)'):
            st.caption('Estimés automatiquement depuis le début du CSV. Modifiables si nécessaire.')
            bg_pm_raw     = st.number_input('PM ambiant (logunits)',  value=bg_pm_a,  step=0.1, format='%.1f', key='bpm')
            bg_co_raw     = st.number_input('CO ambiant (logunits)',  value=bg_co_a,  step=0.1, format='%.1f', key='bco')
            bg_co2_ppm    = st.number_input('CO₂ ambiant (ppm)',      value=bg_co2_a, step=1.0, format='%.1f', key='bco2')
            baseline_flow = st.number_input('Débit ventilateur arrêté (logunits)',
                                             value=bg_fl_a, step=10.0, format='%.0f', key='bfl')
    else:
        bg_pm_raw, bg_co_raw, bg_co2_ppm, baseline_flow = 0.0, 0.0, 615.0, 9900.0

    st.divider()

    # ── Statut des phases + reset ─────────────────────────────────────
    st.caption('Statut des phases')
    cols_stat = st.columns(3)
    for i, p in enumerate(['HP', 'MP', 'BP']):
        if p in st.session_state.resultats:
            cols_stat[i].success(f'✓ {p}')
        else:
            cols_stat[i].warning(f'· {p}')

    if st.session_state.resultats:
        if st.button('🗑️  Réinitialiser les résultats', use_container_width=True):
            st.session_state.resultats = {}
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Zone principale — Graphe CSV
# ─────────────────────────────────────────────────────────────────────

if res_csv is not None:
    df0       = res_csv['donnees']
    duree_tot = (df0['seconds'].max() - df0['seconds'].min()) / 60.0

    st.subheader(f'📄 {nom_fichier}')
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Date',         res_csv['date'])
    m2.metric('Heure début',  res_csv['heure'])
    m3.metric('Durée totale', f'{duree_tot:.1f} min')
    m4.metric('Nb mesures',   f'{len(df0)}')

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

    # Initialiser les intervalles des 3 phases (découpage par tiers)
    duree_tot_min = t_max_val - t_min_val
    tiers = [
        (t_min_val,
         round(t_min_val + duree_tot_min * 0.37, 1)),
        (round(t_min_val + duree_tot_min * 0.37, 1),
         round(t_min_val + duree_tot_min * 0.69, 1)),
        (round(t_min_val + duree_tot_min * 0.69, 1),
         t_max_val),
    ]
    for idx_p, p in enumerate(['HP', 'MP', 'BP']):
        if f'intervalle_{p}' not in st.session_state:
            st.session_state[f'intervalle_{p}'] = tiers[idx_p]

    # ── Figure combinée : CO + PM + Température ──────────────────────
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t_min, y=df_taux0['CO_ppm_zeroed'],
        name='CO (ppm)', line=dict(color='#2196F3', width=1.2),
    ))
    fig.add_trace(go.Scatter(
        x=t_min, y=df_taux0['PM_ug_zeroed'],
        name='PM₂.₅ (µg/m³)', line=dict(color='#F44336', width=1.2),
        yaxis='y2',
    ))
    fig.add_trace(go.Scatter(
        x=t_min, y=df_cal0['GasTemp'],
        name='Température gaz (°C)', line=dict(color='#FF9800', width=1.5, dash='dot'),
        yaxis='y3',
    ))

    for p, s in PHASE_COLORS.items():
        iv = st.session_state.get(f'intervalle_{p}')
        if iv:
            x0, x1 = iv
            fig.add_vrect(
                x0=x0, x1=x1,
                fillcolor=s['fill'],
                line=dict(color=s['border'], width=2, dash='dash'),
                annotation_text=f'{p} ({x1 - x0:.1f} min)',
                annotation_position=s['pos'],
                annotation_font=dict(size=12, color=s['border']),
            )

    fig.update_layout(
        # Zone de tracé réduite des deux côtés pour laisser de la place aux axes
        xaxis=dict(
            domain=[0.08, 0.88],
            title='Temps (min)', title_font=dict(size=14),
            tickfont=dict(size=12), showgrid=True, gridcolor='#e0e0e0',
        ),
        # Axe gauche : CO (bleu)
        yaxis=dict(
            title='CO (ppm)',
            title_font=dict(size=13, color='#2196F3'),
            tickfont=dict(size=12, color='#2196F3'),
        ),
        # Axe gauche secondaire : Température (orange) — décalé à l'extérieur
        yaxis3=dict(
            title='T gaz (°C)',
            title_font=dict(size=13, color='#FF9800'),
            tickfont=dict(size=12, color='#FF9800'),
            overlaying='y', side='left',
            anchor='free', position=0.0,
            showgrid=False,
        ),
        # Axe droit : PM₂.₅ (rouge) — seul sur la droite, bien lisible
        yaxis2=dict(
            title='PM₂.₅ (µg/m³)',
            title_font=dict(size=13, color='#F44336'),
            tickfont=dict(size=12, color='#F44336'),
            overlaying='y', side='right',
        ),
        legend=dict(orientation='h', y=1.10, font=dict(size=12)),
        hovermode='x unified', plot_bgcolor='white', paper_bgcolor='white',
        margin=dict(l=100, r=90, t=50, b=50), height=370,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Sliders d'intervalle pour les 3 phases ────────────────────────
    st.markdown('**⏱️ Définir les intervalles de chaque phase (minutes)**')
    sl_hp, sl_mp, sl_bp = st.columns(3)
    for col, p, color in zip([sl_hp, sl_mp, sl_bp],
                              ['HP', 'MP', 'BP'],
                              ['#1565C0', '#E65100', '#2E7D32']):
        with col:
            st.markdown(f'<span style="color:{color};font-weight:600">{p} — {PHASES_LABELS[p]}</span>',
                        unsafe_allow_html=True)
            iv = st.slider(
                f'Intervalle {p}',
                min_value=round(t_min_val, 1),
                max_value=round(t_max_val, 1),
                value=st.session_state[f'intervalle_{p}'],
                step=0.5,
                label_visibility='collapsed',
                key=f'intervalle_{p}',
            )
            x0, x1 = iv
            st.caption(f'{x0:.1f} → {x1:.1f} min  ({x1 - x0:.1f} min)')

else:
    baseline_flow = 9900.0
    bg_pm_raw, bg_co_raw, bg_co2_ppm = 0.0, 0.0, 615.0
    st.info('👈 Chargez un fichier CSV dans la barre latérale pour commencer.')

st.divider()

# ─────────────────────────────────────────────────────────────────────
# Saisie des données de test — 3 phases en parallèle
# ─────────────────────────────────────────────────────────────────────

st.subheader('📝 Données du test par phase')
st.caption('Saisissez les données des trois phases simultanément, puis analysez.')

col_hp, col_mp, col_bp = st.columns(3)

for col, phase in zip([col_hp, col_mp, col_bp], ['HP', 'MP', 'BP']):
    td = TEST_DEFAULTS[phase]
    s  = PHASE_COLORS[phase]

    with col:
        st.markdown(
            f'<div style="background:{s["fill"]};border-left:4px solid {s["border"]};'
            f'padding:6px 10px;border-radius:4px;font-weight:700;font-size:1.05em;">'
            f'{phase} — {PHASES_LABELS[phase]}</div>',
            unsafe_allow_html=True,
        )
        st.markdown('')

        # ── Données initiales ──────────────────────────────────────
        st.markdown('**Pesées et températures initiales**')
        mb = st.number_input(
            'Bois chargé dans le foyer (kg)',
            help='Masse de bois pesée AVANT la phase et mise dans le foyer.',
            min_value=0.0,
            value=float(td['mb'] if mode_test else 1.0),
            step=0.01, format='%.3f',
            key=f'mb_{phase}',
        )
        k_me = f'me_{phase}'
        if k_me not in st.session_state:
            st.session_state[k_me] = float(td['me'] * td['np'] if mode_test else 2.0)
        st.number_input(
            'Eau totale dans les pots (kg)',
            help='Masse totale d\'eau mise dans tous les pots au début de la phase.',
            min_value=0.1, step=0.1, format='%.1f',
            key=k_me,
        )
        k_t0 = f'td_{phase}'
        if k_t0 not in st.session_state:
            st.session_state[k_t0] = float(td['td'] if mode_test else 20.0)
        st.number_input(
            'T° eau initiale (°C)',
            help='Température de l\'eau mesurée au DÉBUT de la phase.',
            step=0.5, format='%.1f',
            key=k_t0,
        )

        st.markdown('**Pesées et températures finales**')
        mc = st.number_input(
            'Charbon résiduel dans le foyer (kg)',
            help='Masse de charbon restant dans le foyer à la FIN de la phase. '
                 'Le combustible brûlé = bois chargé − charbon résiduel (calculé automatiquement).',
            min_value=0.0,
            value=float(td['mc'] if mode_test else 0.0),
            step=0.001, format='%.3f',
            key=f'mc_{phase}',
        )
        k_tf = f'tf_{phase}'
        if k_tf not in st.session_state:
            st.session_state[k_tf] = float(td['tf'] if mode_test else 90.0)
        st.number_input(
            'T° eau finale (°C)',
            help='Température de l\'eau mesurée à la FIN de la phase.',
            step=0.5, format='%.1f',
            key=k_tf,
        )

        # Afficher le combustible brûlé calculé
        mb_val = st.session_state.get(f'mb_{phase}', 0.0)
        mc_val = st.session_state.get(f'mc_{phase}', 0.0)
        brule  = max(0.0, mb_val - mc_val)
        st.caption(f'→ Combustible brûlé estimé : **{brule:.3f} kg** (bois chargé − charbon résiduel)')

        # ── Filtre PM optionnel ────────────────────────────────────
        with st.expander('⚖️ Filtre PM2.5 (optionnel)'):
            f1, f2 = st.columns(2)
            filtre_avant = f1.number_input('Avant (mg)', min_value=0.0,
                                            value=0.0, step=0.001, format='%.3f',
                                            key=f'fa_{phase}')
            filtre_apres = f2.number_input('Après (mg)', min_value=0.0,
                                            value=0.0, step=0.001, format='%.3f',
                                            key=f'fp_{phase}')

        st.markdown('')

        # ── Bouton analyser ────────────────────────────────────────
        analyser_btn = st.button(
            f'▶  Analyser {phase}',
            key=f'btn_analyser_{phase}',
            type='primary',
            use_container_width=True,
            disabled=(res_csv is None),
        )

        if phase in st.session_state.resultats:
            r_done = st.session_state.resultats[phase]
            st.success(f'✓ Analysée — {r_done["duree_min"]:.1f} min  |  Tier {r_done["tier"]}')

        if analyser_btn and res_csv is not None:
            pots = [{
                'masse_eau': st.session_state[f'me_{phase}'],
                'T_debut'  : st.session_state[f'td_{phase}'],
                'T_fin'    : st.session_state[f'tf_{phase}'],
            }]
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
            with st.spinner(f'Calculs {phase}...'):
                result = analyser(res_csv, donnees_ext)
            result['_fichier'] = nom_fichier
            result['_pm_gravi_mg'] = (
                round(filtre_apres - filtre_avant, 3)
                if filtre_apres > filtre_avant > 0 else None
            )
            st.session_state.resultats[phase] = result
            st.rerun()

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
        st.info(f'Phase {code} non encore analysée. '
                f'Remplissez les données ci-dessus et cliquez "Analyser {code}".')
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
            ('PM2.5 / énergie utile (mg/MJ)', lambda r: r['normalises']['PM_par_utile_mg_MJ']),
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
