#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEMS Analyser — Application Streamlit
Conforme ISO 19867-1 · Classement ISO/IWA-11
"""

import io, os, tempfile, datetime
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from import_csv import lire_csv
from calculs import (analyser, COMBUSTIBLES, LABEL_TIER,
                     appliquer_calibration, calculer_taux_emission)
from visualisation import graphique_comparaison_calibration, tableau_calibration_df
from interpretation import (analyser_phase, graphique_jauges_emissions,
                             generer_texte, generer_recommandations, generer_pdf,
                             TIER_COUL, TIER_BG, TIER_LABEL, TIER_EMOJI)

# ─────────────────────────────────────────────────────────────────────
APP_CSS = """
<style>
:root {
  --lems-primary: #3D5A80;
  --lems-primary-dark: #293F5C;
  --lems-bg-soft: #F4F6F8;
  --lems-border: #E2E8F0;
}

.lems-header {
  display: flex;
  align-items: center;
  gap: 18px;
  background: linear-gradient(135deg, var(--lems-primary) 0%, var(--lems-primary-dark) 100%);
  color: #fff;
  padding: 20px 28px;
  border-radius: 12px;
  margin-bottom: 6px;
}
.lems-header__icon { font-size: 2.3rem; line-height: 1; }
.lems-header__title { font-size: 1.55rem; font-weight: 700; letter-spacing: -0.01em; }
.lems-header__subtitle { font-size: 1.0rem; opacity: 0.92; margin-top: 2px; }
.lems-header__meta { font-size: 0.8rem; opacity: 0.78; margin-top: 6px; }
.lems-header__badge {
  margin-left: auto;
  background: rgba(255,255,255,0.18);
  border: 1px solid rgba(255,255,255,0.35);
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
}

.phase-chip {
  padding: 8px 14px;
  border-radius: 8px;
  border-left: 4px solid var(--chip-border, #999);
  background: var(--chip-fill, #f5f5f5);
  font-weight: 700;
  font-size: 1.05rem;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.tier-banner {
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

div[data-testid="stButton"] button {
  border-radius: 8px;
  font-weight: 600;
  transition: box-shadow 0.15s ease;
}
div[data-testid="stButton"] button:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 12px !important;
}

section[data-testid="stSidebar"] h2 {
  font-size: 1.0rem;
  border-bottom: 1px solid var(--lems-border);
  padding-bottom: 6px;
}

div[data-testid="stMetric"] {
  background: var(--lems-bg-soft);
  border-radius: 8px;
  padding: 8px 10px;
}

div[data-testid="stDataFrame"] {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--lems-border);
}
</style>
"""

st.set_page_config(
    page_title='LEMS Analyser',
    page_icon='🔥',
    layout='wide',
    initial_sidebar_state='expanded',
)
st.markdown(APP_CSS, unsafe_allow_html=True)
st.markdown(
    '<div class="lems-header">'
    '<div class="lems-header__icon">🔥</div>'
    '<div>'
    '<div class="lems-header__title">LEMS Analyser</div>'
    '<div class="lems-header__subtitle">Analyse des émissions de foyers biomasse</div>'
    '<div class="lems-header__meta">Conforme ISO 19867-1 · Classement ISO/IWA-11 · CERER / ESP-UCAD</div>'
    '</div>'
    '<div class="lems-header__badge">⚠️ Version bêta</div>'
    '</div>',
    unsafe_allow_html=True,
)
st.caption('Résultats en cours de validation — ne pas utiliser pour des rapports officiels.')

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
if 'tests_accumules' not in st.session_state:
    st.session_state.tests_accumules = []  # liste de tests complets (HP+MP+BP) pour stats ISO

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

    # ── Avancement tests ISO 19867 ────────────────────────────────────
    _n_acc_sb = len(st.session_state.tests_accumules)
    if _n_acc_sb < 5:
        _test_sb = _n_acc_sb + 1
        st.info(f'**Test {_test_sb} / 5**  \nISO 19867 — 5 répétitions recommandées')
    else:
        st.success(f'**{_n_acc_sb} tests enregistrés ✅**  \nMinimum ISO atteint')

    # ── Source CSV ────────────────────────────────────────────────────
    st.header('📂 Étape 1 — Fichier CSV')

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
    st.header('📋 Étape 2 — Données communes')
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
    hum_labo = st.number_input('Humidité du laboratoire (%)', min_value=0.0, max_value=100.0,
                                value=50.0, step=1.0, format='%.1f', key='hum_labo')
    nom_testeur = st.text_input('Nom du testeur(s)', value='', key='nom_testeur',
                                 placeholder='ex. A. Fall, M. Diallo')


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
# Guidage utilisateur — Bastien & Scapin : Guidage / Incitation / Feedback
# ─────────────────────────────────────────────────────────────────────
_n_acc = len(st.session_state.tests_accumules)
_n_res = len([r for r in st.session_state.resultats.values() if r])

_ETAPES_LBL = [
    '📂 1. Charger CSV',
    '⏱️ 2. Intervalles',
    '📝 3. Saisir données',
    '▶ 4. Analyser',
    '💾 5. Enregistrer',
]

if _n_acc >= 5:
    _col_done1, _col_done2 = st.columns([3, 1])
    with _col_done1:
        st.success(
            f'🎉 **{_n_acc} tests enregistrés** — minimum ISO 19867 atteint !  \n'
            f'Vous pouvez enregistrer des tests supplémentaires ou générer le rapport final.'
        )
    with _col_done2:
        if st.button('📊 Rapport final', type='primary', use_container_width=True,
                     key='btn_rapport_final_top',
                     help='Aller directement aux statistiques ISO 19867 et aux exports.'):
            st.session_state['goto_rapport'] = True
            st.rerun()
else:
    _test_n = _n_acc + 1
    if not res_csv:
        _ei  = 0
        _msg = (f'👈 **Test {_test_n}/5 — Étape 1 :** Chargez le fichier CSV du test '
                f'dans la **barre latérale à gauche**.')
        _msg_type = 'warning'
    elif _n_res == 0:
        _ei  = 1
        _msg = (f'⬇️ **Test {_test_n}/5 — Étape 2 :** CSV chargé ✅  '
                f'Ajustez les **intervalles HP / MP / BP** sur le graphe avec les sliders, '
                f'puis descendez pour saisir les données de pesée.')
        _msg_type = 'info'
    elif 0 < _n_res < 3:
        _ei  = 3
        _msg = (f'⬇️ **Test {_test_n}/5 — Étape 3 :** {_n_res}/3 phases analysées.  '
                f'Analysez les phases restantes ou cliquez **"▶▶ Analyser les 3 phases"**.')
        _msg_type = 'info'
    else:
        _ei  = 4
        _msg = (f'➡️ **Test {_test_n}/5 — Étape 4 :** ✅ 3 phases analysées !  '
                f'Descendez jusqu\'à l\'onglet **📊 Rapport global** et cliquez '
                f'**"➕ Enregistrer ce test"** pour valider ce test.')
        _msg_type = 'success'

    # Stepper natif : étiquettes avec préfixe visuel selon l'état
    _step_cols = st.columns(5)
    for _si, (_sc, _slbl) in enumerate(zip(_step_cols, _ETAPES_LBL)):
        if _si < _ei:
            _sc.success(f'~~{_slbl}~~')
        elif _si == _ei:
            _sc.info(f'**{_slbl}**')
        else:
            _sc.caption(_slbl)

    if _msg_type == 'warning':
        st.warning(_msg)
    elif _msg_type == 'success':
        st.success(_msg)
    else:
        st.info(_msg)

st.markdown('')

# ─────────────────────────────────────────────────────────────────────
# Identification du test
# ─────────────────────────────────────────────────────────────────────
with st.expander('🏷️ Identification du test', expanded=False):
    col_id1, col_id2, col_id3 = st.columns(3)
    with col_id1:
        st.text_input('Nom du fourneau / poêle', value='', key='nom_fourneau',
                       placeholder='ex. Sakkanal-T11')
        st.number_input('N° de réplique', min_value=1, max_value=20, value=1, step=1, key='n_replique')
    with col_id2:
        st.text_input('Lieu du test', value='', key='lieu_test',
                       placeholder='ex. CERER, Dakar')
        st.text_input('Date du test (JJ/MM/AAAA)', value='', key='date_test',
                       placeholder='ex. 01/12/2022')
    with col_id3:
        st.text_area('Remarques / observations', value='', key='remarques', height=105,
                      placeholder='ex. Vent modéré, allumage au papier, foyer propre...')

# ─────────────────────────────────────────────────────────────────────
# Zone principale — Graphe CSV
# ─────────────────────────────────────────────────────────────────────

if res_csv is not None:
    df0       = res_csv['donnees']
    duree_tot = (df0['seconds'].max() - df0['seconds'].min()) / 60.0

    st.subheader(f'📄 {nom_fichier}')
    with st.container(border=True):
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

    # ── Comparaison brutes / calibrées ────────────────────────────
    with st.expander('🔬 Calibration — données brutes vs calibrées', expanded=False):

        st.markdown('### Pourquoi calibrer ?')
        st.markdown(
            'Les capteurs du LEMS ne mesurent pas directement des ppm ou des µg/m³. '
            'Ils produisent un **signal électrique brut** converti en **log-units** — '
            'un nombre interne sans signification physique (ex : 8 500).  \n\n'
            'La calibration convertit ce nombre en **unité réelle** grâce à un facteur '
            'propre à chaque capteur :  \n\n'
            '> **Signal brut (log-units) × facteur = Valeur physique (ppm, µg/m³, °C…)**  \n\n'
            'Exemple : `8 500 × 0.00148 = 12.6 ppm de CO`  \n\n'
            'Ces facteurs sont stockés dans la **ligne `#0` du fichier CSV** '
            '(première ligne, 8 valeurs correspondant aux 8 capteurs).  \n\n'
            '⚠️ **Sans calibration valide, tous les calculs d\'émissions (CO, PM₂.₅) '
            'et le classement Tier IWA-11 sont incorrects.**'
        )

        st.markdown('### Facteurs de calibration appliqués')
        st.caption('Valeurs lues depuis la ligne #0 du CSV · valeur calibrée = valeur brute × facteur')
        st.dataframe(
            tableau_calibration_df(df0, df_cal0, calibr0),
            use_container_width=True,
        )

        st.markdown('### Vérification graphique')
        st.info(
            '**Comment lire :** chaque ligne = un capteur. '
            '**Colonne gauche** = signal brut (log-units, gris). '
            '**Colonne droite** = valeur calibrée (ppm / µg/m³ / °C, colorée).  \n\n'
            '**Règle :** les deux courbes doivent avoir **la même forme** '
            '(mêmes pics et creux au même moment) — la calibration ne fait que changer '
            'l\'échelle, pas la forme.  \n'
            'Si c\'est le cas → ✅ calibration fiable.  \n'
            'Si les formes divergent → ⚠️ le facteur de ce capteur est à vérifier.  \n'
            'Le verdict ✅ / ⚠️ est calculé automatiquement et affiché dans chaque titre.'
        )
        st.plotly_chart(
            graphique_comparaison_calibration(df0, df_cal0, calibr0),
            use_container_width=True,
        )

    # ── Contrôles de Fuite & Étalonnage ──────────────────────────────
    with st.expander('🔧 Contrôles de Fuite & Étalonnage', expanded=False):
        st.caption(
            'Remplir **avant** de démarrer le test. '
            'Valeurs de référence typiques : gravimétrique −14 in Hg, capteur gaz −64 in H₂O, Δt = 1/1 min.'
        )

        col_fuite1, col_fuite2 = st.columns(2)

        with col_fuite1:
            st.markdown('**Gravimétrique (in Hg)**')
            c_g1, c_g2 = st.columns(2)
            c_g1.number_input('Pi (in Hg)', value=-14.0, step=0.5, format='%.1f', key='gravi_pi')
            c_g2.number_input('Pf (in Hg)', value=-14.0, step=0.5, format='%.1f', key='gravi_pf')

            st.markdown('**Capteur de gaz (in H₂O)**')
            c_gz1, c_gz2 = st.columns(2)
            c_gz1.number_input('Pi (in H₂O)', value=-64.0, step=0.5, format='%.1f', key='gaz_pi')
            c_gz2.number_input('Pf (in H₂O)', value=-64.0, step=0.5, format='%.1f', key='gaz_pf')

            st.markdown('**Δt (min)**')
            c_dt1, c_dt2 = st.columns(2)
            c_dt1.number_input('Δt début', value=1.0, step=0.5, format='%.1f', key='dt_debut')
            c_dt2.number_input('Δt fin',   value=1.0, step=0.5, format='%.1f', key='dt_fin')

            st.markdown('**LRS (kg)**')
            c_lrs1, c_lrs2 = st.columns(2)
            c_lrs1.number_input('LRS début (kg)', value=0.0, step=0.001, format='%.3f', key='lrs_debut')
            c_lrs2.number_input('LRS fin (kg)',   value=0.0, step=0.001, format='%.3f', key='lrs_fin')

        with col_fuite2:
            st.markdown('**Étalonnage CO₂**')
            c_e1, c_e2, c_e3 = st.columns(3)
            c_e1.number_input('Zéro CO₂',         value=0.0,   step=0.01, format='%.2f', key='etal_co2_zero')
            c_e2.number_input('Pente CO₂ (%)',     value=100.0, step=0.1,  format='%.1f', key='etal_co2_pente')
            c_e3.number_input('Dérive CO₂',        value=0.0,   step=0.01, format='%.2f', key='etal_co2_derive')

            st.markdown('**Étalonnage CO**')
            c_f1, c_f2, c_f3 = st.columns(3)
            c_f1.number_input('Zéro CO',           value=0.0,   step=0.01, format='%.2f', key='etal_co_zero')
            c_f2.number_input('Pente CO (%)',       value=100.0, step=0.1,  format='%.1f', key='etal_co_pente')
            c_f3.number_input('Dérive CO',          value=0.0,   step=0.01, format='%.2f', key='etal_co_derive')

            st.markdown('**Étalonnage PM₂.₅**')
            c_pm1, c_pm2, c_pm3 = st.columns(3)
            c_pm1.number_input('Zéro PM',          value=0.0,   step=0.01, format='%.2f', key='etal_pm_zero')
            c_pm2.number_input('Pente PM (%)',      value=100.0, step=0.1,  format='%.1f', key='etal_pm_pente')
            c_pm3.number_input('Dérive PM',         value=0.0,   step=0.01, format='%.2f', key='etal_pm_derive')

else:
    baseline_flow = 9900.0
    bg_pm_raw, bg_co_raw, bg_co2_ppm = 0.0, 0.0, 615.0
    st.info('👈 Chargez un fichier CSV dans la barre latérale pour commencer.')

st.divider()

# ─────────────────────────────────────────────────────────────────────
# Saisie des données de test — 3 phases en parallèle
# ─────────────────────────────────────────────────────────────────────

st.subheader('📝 Données du test par phase')
st.caption('Un onglet par phase — remplissez puis analysez. '
           'Le bouton "Analyser les 3 phases" en bas lance les trois à la fois une fois tout rempli.')

tab_hp_in, tab_mp_in, tab_bp_in = st.tabs([
    f'🔴 HP — {PHASES_LABELS["HP"]}',
    f'🟡 MP — {PHASES_LABELS["MP"]}',
    f'🔵 BP — {PHASES_LABELS["BP"]}',
])

for tab, phase in zip([tab_hp_in, tab_mp_in, tab_bp_in], ['HP', 'MP', 'BP']):
    td = TEST_DEFAULTS[phase]
    s  = PHASE_COLORS[phase]

    with tab:
        # ── Horodatage terrain ─────────────────────────────────────
        st.markdown('**Horodatage terrain**')
        h_col1, h_col2 = st.columns(2)
        h_col1.time_input('Heure début', value=datetime.time(8, 0),  key=f'h_debut_{phase}')
        h_col2.time_input('Heure fin',   value=datetime.time(9, 0),  key=f'h_fin_{phase}')

        st.markdown('')
        col_init, col_final = st.columns(2)

        with col_init:
            # ── Données initiales ──────────────────────────────────────
            st.markdown('**Pesées et températures initiales**')
            mb = st.number_input(
                'Combustible chargé en début de phase (kg)',
                help='Masse de combustible pesée AVANT la phase et mise dans le foyer '
                     '(bois, charbon de bois, etc. selon le combustible choisi ci-dessus).',
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

        with col_final:
            # ── Données finales ──────────────────────────────────────
            st.markdown('**Pesées et températures finales**')
            mc = st.number_input(
                'Résidu combustible en fin de phase (kg)',
                help='Masse de combustible non brûlé restant dans le foyer à la FIN de la phase '
                     '(charbon de bois résiduel pour un test au bois, combustible non consommé sinon). '
                     'Le combustible brûlé = chargé en début − résidu en fin (calculé automatiquement).',
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
        st.caption(f'→ Combustible brûlé estimé : **{brule:.3f} kg** (chargé en début − résidu en fin)')

        col_pot, col_filtre = st.columns(2)
        with col_pot:
            # ── Données par pot (optionnel) ────────────────────────────
            with st.expander('🪣 Données par pot (optionnel)'):
                n_pots_val = st.number_input(
                    'Nombre de pots', min_value=1, max_value=6,
                    value=4, step=1, key=f'npots_{phase}',
                )
                n_pots_int = int(n_pots_val)
                for _ip in range(1, n_pots_int + 1):
                    st.caption(f'Pot {_ip}')
                    _pa, _pb = st.columns(2)
                    _pa.number_input(f'Poids vide P{_ip} (kg)',    min_value=0.0, value=1.0,  step=0.001, format='%.3f', key=f'pot_{phase}_{_ip}_vide')
                    _pb.number_input(f'P{_ip}+eau début (kg)',     min_value=0.0, value=3.5,  step=0.001, format='%.3f', key=f'pot_{phase}_{_ip}_eau_debut')
                    _pc, _pd = st.columns(2)
                    _pc.number_input(f'T° eau début P{_ip} (°C)', value=20.0, step=0.5, format='%.1f', key=f'pot_{phase}_{_ip}_td')
                    _pd.number_input(f'P{_ip}+eau fin (kg)',       min_value=0.0, value=3.2,  step=0.001, format='%.3f', key=f'pot_{phase}_{_ip}_eau_fin')
                    st.number_input(f'T° eau fin P{_ip} (°C)',    value=95.0, step=0.5, format='%.1f', key=f'pot_{phase}_{_ip}_tf')

        with col_filtre:
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

# ── Bouton global : analyser les 3 phases d'un coup ──────────────────
st.markdown('')
phases_saisies = all(
    f'mb_{p}' in st.session_state and f'mc_{p}' in st.session_state
    and f'me_{p}' in st.session_state and f'td_{p}' in st.session_state
    and f'tf_{p}' in st.session_state
    for p in ['HP', 'MP', 'BP']
)
col_g1, col_g2, col_g3 = st.columns([1, 2, 1])
with col_g2:
    analyser_tout = st.button(
        '▶▶  Analyser les 3 phases en une fois (HP + MP + BP)',
        key='btn_analyser_tout',
        type='primary',
        use_container_width=True,
        disabled=(res_csv is None or not phases_saisies),
        help='Lance l\'analyse des 3 phases simultanément sans passer par les boutons individuels.',
    )

if analyser_tout and res_csv is not None:
    with st.spinner('Calculs HP + MP + BP en cours…'):
        for _p in ['HP', 'MP', 'BP']:
            _pots = [{
                'masse_eau': st.session_state[f'me_{_p}'],
                'T_debut'  : st.session_state[f'td_{_p}'],
                'T_fin'    : st.session_state[f'tf_{_p}'],
            }]
            _fa = st.session_state.get(f'fa_{_p}', 0.0)
            _fp = st.session_state.get(f'fp_{_p}', 0.0)
            _donnees = {
                'type_combustible': type_comb,
                'masse_bois_kg'   : st.session_state[f'mb_{_p}'],
                'masse_charbon_kg': st.session_state[f'mc_{_p}'],
                'humidite_pct'    : hum_comb,
                'pots'            : _pots,
                'T_atm'           : T_atm,
                'p_Pa'            : pression * 100.0,
                'baseline_flow'   : baseline_flow,
                'bg_pm_raw'       : bg_pm_raw,
                'bg_co_raw'       : bg_co_raw,
                'bg_co2_ppm'      : bg_co2_ppm,
                'filtre_avant_mg' : _fa,
                'filtre_apres_mg' : _fp,
            }
            _iv = st.session_state.get(f'intervalle_{_p}')
            if _iv:
                _donnees['t_debut_s'] = _iv[0] * 60.0
                _donnees['t_fin_s']   = _iv[1] * 60.0
            _res = analyser(res_csv, _donnees)
            _res['_fichier'] = nom_fichier
            _res['_pm_gravi_mg'] = (
                round(_fp - _fa, 3) if _fp > _fa > 0 else None
            )
            st.session_state.resultats[_p] = _res
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
    ('Efficacité thermique (a/charbon)', '%',      lambda r: (
        r['thermique']['efficacite_avec_char_pct']
        if r['thermique'].get('a_residu_charbonneux') else None)),
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


# ── Bannière CTA : guider vers "Rapport global" quand les 3 phases sont prêtes ──
if len(st.session_state.resultats) == 3 and len(st.session_state.tests_accumules) < 5:
    st.success(
        '**Les 3 phases sont analysees !**  \n'
        'Cliquez sur l\'onglet **Rapport global** ci-dessous, '
        'puis sur **"Enregistrer ce test"** pour valider.'
    )

st.subheader('📋 Résultats par phase')
_n_acc_tabs = len(st.session_state.tests_accumules)
_global_label = (
    '📊 Rapport global ✅' if len(st.session_state.resultats) == 3
    else '📊 Rapport global'
)
tab_hp, tab_mp, tab_bp, tab_global = st.tabs([
    '🔴 Haute Puissance (HP)',
    '🟡 Moyenne Puissance (MP)',
    '🔵 Basse Puissance (BP)',
    _global_label,
])

with tab_hp:
    tableau_phase('HP')

with tab_mp:
    tableau_phase('MP')

with tab_bp:
    tableau_phase('BP')

# ─────────────────────────────────────────────────────────────────────
# Rapport global — Interprétation professionnelle ISO 19867-1 / IWA-11
# ─────────────────────────────────────────────────────────────────────

with tab_global:
    phases_ok = {c: r for c, r in st.session_state.resultats.items() if r is not None}

    if not phases_ok:
        st.info('Analysez au moins une phase (HP, MP ou BP) pour générer le rapport.')
    else:
        # ── Analyse détaillée de chaque phase ────────────────────────
        analyses = {code: analyser_phase(code, r) for code, r in phases_ok.items()}
        tier_global = min(a['t_iwa11'] for a in analyses.values())
        bg  = TIER_BG.get(tier_global, '#F5F5F5')
        col = TIER_COUL.get(tier_global, '#555')

        # ── Bandeau Tier global ───────────────────────────────────────
        st.markdown(
            f'<div class="tier-banner" style="background:{bg};border-left:6px solid {col};'
            f'padding:14px 20px;margin-bottom:12px;">'
            f'<span style="font-size:1.5em;font-weight:700;color:{col};">'
            f'{TIER_EMOJI[tier_global]} Tier {tier_global} — {TIER_LABEL[tier_global]}</span><br>'
            f'<span style="color:#555;font-size:0.95em;">'
            f'{len(analyses)}/3 phases analysées · Classement IWA-11 = phase la plus défavorable'
            f'</span></div>',
            unsafe_allow_html=True,
        )

        # ── Compteur multi-tests ISO 19867 ───────────────────────────
        n_tests = len(st.session_state.tests_accumules)
        if len(phases_ok) == 3:
            col_cpt, col_btn = st.columns([3, 1])
            with col_cpt:
                if n_tests == 0:
                    st.warning(
                        f'🧪 **0 test enregistré** — '
                        f'il en faut **5 minimum** pour les statistiques ISO 19867 '
                        f'(moyenne, écart-type, IC 90%).'
                    )
                elif n_tests < 5:
                    st.warning(
                        f'🧪 **{n_tests} / 5 test(s) enregistré(s)** — '
                        f'continuez jusqu\'à 5 pour satisfaire ISO 19867.'
                    )
                else:
                    st.success(
                        f'✅ **{n_tests} tests enregistrés** — '
                        f'statistiques ISO 19867 disponibles ci-dessous.  \n'
                        f'Vous pouvez en ajouter d\'autres ou générer le rapport final.'
                    )
            with col_btn:
                if st.button('➕ Enregistrer ce test', use_container_width=True,
                             help='Ajoute les résultats actuels (HP+MP+BP) à l\'historique '
                                  'pour le calcul des statistiques ISO 19867.'):
                    entree = {
                        'fichier'  : nom_fichier,
                        'tier'     : tier_global,
                        'phases'   : {c: {
                            'eff'       : a['eff'],
                            'co_g_min'  : a['co_g_min'],
                            'pm_mg_min' : a['pm_mg_min'],
                            'co_mjd'    : a['co_mjd'],
                            'pm_mjd'    : a['pm_mjd'],
                            'mce'       : a['mce'],
                        } for c, a in analyses.items()},
                    }
                    st.session_state.tests_accumules.append(entree)
                    st.rerun()

            # ── Guidage post-enregistrement ───────────────────────────
            if 0 < n_tests < 5:
                st.info(
                    f'**Test {n_tests}/5 enregistré — Que faire maintenant ?**  \n'
                    f'**1.** Remontez en haut de la page  \n'
                    f'**2.** Dans la **barre latérale**, sélectionnez le CSV du **test {n_tests + 1}**  \n'
                    f'**3.** Cliquez **Réinitialiser les résultats** (bouton 🗑️ dans la barre latérale)  \n'
                    f'**4.** Répétez : ajuster intervalles → saisir données → analyser → enregistrer'
                )

            # ── Bouton "Terminer" visible dès 5 tests ─────────────────
            if n_tests >= 5:
                st.divider()
                _col_t1, _col_t2, _col_t3 = st.columns([1, 2, 1])
                with _col_t2:
                    st.success(
                        f'**Vous avez {n_tests} tests enregistrés.**  \n'
                        f'Vous pouvez en ajouter d\'autres (pour plus de robustesse)  \n'
                        f'ou **terminer et télécharger votre rapport final** ci-dessous.'
                    )
                    st.button(
                        '📥 Terminer — Télécharger le rapport final',
                        key='btn_terminer',
                        type='primary',
                        use_container_width=True,
                        help='Les exports PDF et Excel sont disponibles dans la section "Exports" ci-dessous.',
                    )
                    st.caption('↓ Section "Exports" juste en-dessous')
        else:
            st.info(
                f'ℹ️ {len(phases_ok)}/3 phases analysées. '
                f'Analysez les 3 phases (HP+MP+BP) pour enregistrer un test complet '
                f'et alimenter les statistiques ISO 19867.'
            )

        # ── Statistiques multi-tests (si ≥ 5 tests) ──────────────────
        if n_tests >= 5:
            st.subheader('📈 Statistiques ISO 19867-1 — Résultats agrégés')
            st.caption(f'{n_tests} tests enregistrés · Moyenne ± Écart-type (ddof=1)')
            stats_rows = []
            for code in ['HP', 'MP', 'BP']:
                vals_eff = [t['phases'][code]['eff']       for t in st.session_state.tests_accumules if code in t['phases']]
                vals_co  = [t['phases'][code]['co_g_min']  for t in st.session_state.tests_accumules if code in t['phases']]
                vals_pm  = [t['phases'][code]['pm_mg_min'] for t in st.session_state.tests_accumules if code in t['phases']]
                if vals_eff:
                    stats_rows.append({
                        'Phase'              : code,
                        'Eff. moy. (%)'      : f'{np.mean(vals_eff):.1f} ± {np.std(vals_eff, ddof=1):.1f}',
                        'CO moy. (g/min)'    : f'{np.mean(vals_co):.4f} ± {np.std(vals_co, ddof=1):.4f}',
                        'PM₂.₅ moy. (mg/min)': f'{np.mean(vals_pm):.4f} ± {np.std(vals_pm, ddof=1):.4f}',
                        'N tests'            : len(vals_eff),
                    })
            if stats_rows:
                st.dataframe(pd.DataFrame(stats_rows).set_index('Phase'),
                             use_container_width=True)
            if st.button('🗑️ Effacer l\'historique des tests', use_container_width=False):
                st.session_state.tests_accumules = []
                st.rerun()
            st.divider()

        # ── Tableau de synthèse IWA-11 ────────────────────────────────
        st.subheader('📊 Synthèse IWA-11 par phase')
        synth_rows = []
        for a in analyses.values():
            synth_rows.append({
                'Phase'              : f"{a['code']} — {a['label']}",
                'CO (g/min)'         : f"{a['co_g_min']:.4f}",
                'Tier CO'            : f"Tier {a['t_co_rate']}",
                'PM₂.₅ (mg/min)'    : f"{a['pm_mg_min']:.4f}",
                'Tier PM'            : f"Tier {a['t_pm_rate']}",
                'Eff. % (av. char.)' : f"{a['eff']:.1f}",
                'Tier Eff.'          : f"Tier {a['t_eff']}",
                'MCE (%)'            : f"{a['mce']:.2f}",
                'Tier IWA-11'        : f"Tier {a['t_iwa11']}",
                'Facteur limitant'   : a['limitant'],
            })
        st.dataframe(pd.DataFrame(synth_rows).set_index('Phase'),
                     use_container_width=True)

        st.divider()

        # ── Jauges d'émissions CO + PM ────────────────────────────────
        st.subheader('🎯 Jauges d\'émissions CO et PM₂.₅ vs seuils IWA-11')
        st.caption(
            '**Lecture des jauges :** la valeur mesurée est affichée en grand avec le Tier obtenu. '
            'Les zones colorées sur l\'arc indiquent les Tiers IWA-11 : '
            '🟢 vert foncé = Tier 4 (Excellent) · vert clair = Tier 3 (Bon) · '
            '🟡 jaune = Tier 2 (Intermédiaire) · 🟠 orange = Tier 1 (Basique) · 🔴 rouge = Tier 0 (Hors normes). '
            'Les marqueurs T4/T3/T2/T1 sur l\'axe indiquent les seuils de chaque Tier. '
            'La ligne sous le Tier indique combien il faut réduire pour atteindre le Tier supérieur.'
        )
        st.plotly_chart(graphique_jauges_emissions(analyses),
                        use_container_width=True)

        st.divider()

        # ── Interprétation narrative ──────────────────────────────────
        st.subheader('📝 Interprétation des résultats')
        st.markdown(generer_texte(
            analyses, nom_fichier,
            nom_testeur  = st.session_state.get('nom_testeur', ''),
            nom_fourneau = st.session_state.get('nom_fourneau', ''),
            date_test    = st.session_state.get('date_test', ''),
            lieu_test    = st.session_state.get('lieu_test', ''),
            n_replique   = st.session_state.get('n_replique', None),
            remarques    = st.session_state.get('remarques', ''),
        ))

        st.divider()

        # ── Recommandations ───────────────────────────────────────────
        st.subheader('💡 Recommandations')
        for cat, rec in generer_recommandations(analyses):
            st.markdown(f'**{cat}**')
            st.markdown(f'> {rec}')

        st.divider()

        # ── Exports ───────────────────────────────────────────────────
        st.subheader('📥 Exports')
        col_pdf, col_xls = st.columns(2)

        with col_pdf:
            pdf_bytes = generer_pdf(
                analyses, nom_fichier,
                nom_testeur  = st.session_state.get('nom_testeur', ''),
                nom_fourneau = st.session_state.get('nom_fourneau', ''),
                date_test    = st.session_state.get('date_test', ''),
                lieu_test    = st.session_state.get('lieu_test', ''),
                n_replique   = st.session_state.get('n_replique', None),
                remarques    = st.session_state.get('remarques', ''),
            )
            if pdf_bytes:
                st.download_button(
                    label='📄 Télécharger rapport PDF',
                    data=pdf_bytes,
                    file_name=f'rapport_LEMS_{nom_fichier.replace(".csv","")}.pdf',
                    mime='application/pdf',
                    use_container_width=True,
                )
            else:
                st.warning('fpdf2 non disponible — installez-le avec `pip install fpdf2`.')

        with col_xls:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                # Feuille identification
                id_data = {
                    'Champ': [
                        'Fourneau / poêle', 'N° de réplique', 'Testeur(s)',
                        'Date du test', 'Lieu', 'Remarques',
                        'Fichier CSV',
                    ],
                    'Valeur': [
                        st.session_state.get('nom_fourneau', ''),
                        str(st.session_state.get('n_replique', '')),
                        st.session_state.get('nom_testeur', ''),
                        st.session_state.get('date_test', ''),
                        st.session_state.get('lieu_test', ''),
                        st.session_state.get('remarques', ''),
                        nom_fichier,
                    ],
                }
                pd.DataFrame(id_data).to_excel(writer, sheet_name='Identification', index=False)

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
                        'CO / énergie utile (g/MJ)': r['normalises']['CO_par_utile_g_MJ'],
                        'PM2.5 total (mg)'        : r['totaux']['PM_total_mg'],
                        'PM2.5 / énergie utile (mg/MJ)': r['normalises']['PM_par_utile_mg_MJ'],
                        'CO2 total (g)'           : r['totaux']['CO2_total_g'],
                        'Tier IWA-11'             : r['tier'],
                    }
                    pd.DataFrame([ligne]).to_excel(writer, sheet_name=code, index=False)
            st.download_button(
                label='📊 Télécharger rapport Excel',
                data=buffer.getvalue(),
                file_name=f'rapport_LEMS_{nom_fichier.replace(".csv","")}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                use_container_width=True,
            )
