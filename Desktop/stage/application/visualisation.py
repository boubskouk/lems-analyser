#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module 3 : Visualisation interactive des données LEMS avec Plotly.

Fonctions exposées :
    graphique_concentrations(df_cal)                          → fig Plotly (CO, PM, CO₂, TC)
    graphique_taux_emission(df_taux)                          → fig Plotly (taux CO et PM)
    graphique_temperature(df_cal)                             → fig Plotly (GasTemp, FlueTemp, TC)
    graphique_debit(df_cal)                                   → fig Plotly (Flow)
    tableau_resume(stats, totaux, therm)                      → fig Plotly (tableau récap)
    graphique_tier(tier, stats)                               → fig Plotly (jauge Tier)
    tableau_calibration_df(df_brut, df_cal, cal)              → DataFrame (8 capteurs + descriptions)
    graphique_comparaison_calibration(df_brut, df_cal, cal)   → fig Plotly (grille 2×4, un panneau par capteur)
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd


# ─────────────────────────────────────────────────────────────────────
# Palette de couleurs LEMS
# ─────────────────────────────────────────────────────────────────────

COULEURS = {
    'CO'       : '#2196F3',   # bleu
    'PM'       : '#F44336',   # rouge
    'CO2'      : '#4CAF50',   # vert
    'TC'       : '#FF9800',   # orange
    'GasTemp'  : '#9C27B0',   # violet
    'FlueTemp' : '#00BCD4',   # cyan
    'Flow'     : '#607D8B',   # gris-bleu
}

TIER_COULEURS = {4: '#4CAF50', 3: '#8BC34A', 2: '#FFC107', 1: '#FF9800', 0: '#F44336'}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _axe_temps(df: pd.DataFrame) -> pd.Series:
    """Retourne l'axe temps en minutes à partir de la colonne 'seconds'."""
    return df['seconds'] / 60.0


def _mise_en_forme(fig: go.Figure, titre: str) -> go.Figure:
    """Applique une mise en forme commune à tous les graphiques."""
    fig.update_layout(
        title=dict(text=titre, font=dict(size=16)),
        plot_bgcolor='white',
        paper_bgcolor='white',
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=60, r=20, t=70, b=50),
        font=dict(family='Arial', size=12),
    )
    fig.update_xaxes(
        title_text='Temps (min)',
        showgrid=True, gridcolor='#EEEEEE',
        zeroline=False,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor='#EEEEEE',
        zeroline=False,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────
# 1. Concentrations des polluants
# ─────────────────────────────────────────────────────────────────────

def graphique_concentrations(df_cal: pd.DataFrame) -> go.Figure:
    """
    Graphique des concentrations calibrées de CO, PM et CO₂ en fonction du temps.
    CO et CO₂ en ppm (axe gauche), PM en mg/m³ (axe droit).
    """
    t = _axe_temps(df_cal)

    fig = make_subplots(specs=[[{'secondary_y': True}]])

    fig.add_trace(go.Scatter(
        x=t, y=df_cal['CO'],
        name='CO (ppm)', line=dict(color=COULEURS['CO'], width=1.5),
        hovertemplate='%{y:.1f} ppm',
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=t, y=df_cal['CO2'],
        name='CO₂ (ppm)', line=dict(color=COULEURS['CO2'], width=1.5),
        hovertemplate='%{y:.0f} ppm',
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=t, y=df_cal['PM'],
        name='PM₂.₅ (mg/m³)', line=dict(color=COULEURS['PM'], width=1.5),
        hovertemplate='%{y:.2f} mg/m³',
    ), secondary_y=True)

    fig.update_yaxes(title_text='CO / CO₂ (ppm)', secondary_y=False)
    fig.update_yaxes(title_text='PM₂.₅ (mg/m³)', secondary_y=True)

    _mise_en_forme(fig, 'Concentrations des polluants (après calibration)')
    return fig


# ─────────────────────────────────────────────────────────────────────
# 2. Taux d'émission
# ─────────────────────────────────────────────────────────────────────

def graphique_taux_emission(df_taux: pd.DataFrame) -> go.Figure:
    """
    Graphique des taux d'émission instantanés de CO et PM en mg/min.
    """
    t = _axe_temps(df_taux)

    fig = make_subplots(specs=[[{'secondary_y': True}]])

    fig.add_trace(go.Scatter(
        x=t, y=df_taux['CO_taux_mg_min'],
        name='Taux CO (mg/min)', line=dict(color=COULEURS['CO'], width=1.5),
        hovertemplate='%{y:.4f} mg/min',
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=t, y=df_taux['PM_taux_mg_min'],
        name='Taux PM (mg/min)', line=dict(color=COULEURS['PM'], width=1.5),
        hovertemplate='%{y:.4f} mg/min',
    ), secondary_y=True)

    fig.update_yaxes(title_text='Taux CO (mg/min)', secondary_y=False)
    fig.update_yaxes(title_text='Taux PM (mg/min)', secondary_y=True)

    _mise_en_forme(fig, "Taux d'émission instantanés CO et PM₂.₅")
    return fig


# ─────────────────────────────────────────────────────────────────────
# 3. Températures
# ─────────────────────────────────────────────────────────────────────

def graphique_temperature(df_cal: pd.DataFrame) -> go.Figure:
    """
    Graphique des températures : GasTemp, FlueTemp et TC en fonction du temps.
    """
    t = _axe_temps(df_cal)

    fig = go.Figure()

    for col, label, unite in [
        ('GasTemp',  'Température gaz (GasTemp)',    '°C'),
        ('FlueTemp', 'Température fumée (FlueTemp)',  '°C'),
        ('TC',       'Thermocouple (TC)',              '°C'),
    ]:
        fig.add_trace(go.Scatter(
            x=t, y=df_cal[col],
            name=label,
            line=dict(color=COULEURS[col], width=1.5),
            hovertemplate=f'%{{y:.2f}} {unite}',
        ))

    fig.update_yaxes(title_text='Température (°C)')
    _mise_en_forme(fig, 'Températures mesurées')
    return fig


# ─────────────────────────────────────────────────────────────────────
# 4. Débit volumique
# ─────────────────────────────────────────────────────────────────────

def graphique_debit(df_cal: pd.DataFrame) -> go.Figure:
    """
    Graphique du débit volumique (Flow) en mL/min en fonction du temps.
    """
    t = _axe_temps(df_cal)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t, y=df_cal['Flow'],
        name='Débit (mL/min)',
        line=dict(color=COULEURS['Flow'], width=1.5),
        fill='tozeroy',
        fillcolor='rgba(96,125,139,0.1)',
        hovertemplate='%{y:.0f} mL/min',
    ))

    fig.update_yaxes(title_text='Débit (mL/min)')
    _mise_en_forme(fig, 'Débit volumique (Flow)')
    return fig


# ─────────────────────────────────────────────────────────────────────
# 5. Tableau récapitulatif
# ─────────────────────────────────────────────────────────────────────

def tableau_resume(stats: dict, totaux: dict, thermique: dict,
                   tier: int, label_tier: str, duree_min: float) -> go.Figure:
    """
    Tableau Plotly affichant les principaux résultats de l'analyse.
    """
    lignes = [
        ['Durée du test',             f"{duree_min:.1f} min"],
        ['Classement Tier IWA-11',    f"Tier {tier} — {label_tier}"],
        ['CO moyen',                  f"{stats['CO_moy_ppm']:.2f} ppm"],
        ['CO maximum',                f"{stats['CO_max_ppm']:.2f} ppm"],
        ['PM₂.₅ moyen',              f"{stats['PM_moy_mg_m3']:.2f} mg/m³"],
        ['PM₂.₅ maximum',            f"{stats['PM_max_mg_m3']:.3f} mg/m³"],
        ['CO₂ moyen',                 f"{stats['CO2_moy_ppm']:.1f} ppm"],
        ['Taux émission CO moyen',    f"{stats['CO_taux_moy_mg_min']:.4f} mg/min"],
        ['Taux émission PM moyen',    f"{stats['PM_taux_moy_mg_min']:.4f} mg/min"],
        ['CO total émis',             f"{totaux['CO_total_g']:.4f} g"],
        ['PM total émis',             f"{totaux['PM_total_g']:.6f} g"],
        ['CO₂ total émis',            f"{totaux['CO2_total_g']:.2f} g"],
        ['Efficacité thermique',      f"{thermique['efficacite_pct']:.1f} %"],
        ['Puissance feu',             f"{thermique['puissance_feu_kW']:.3f} kW"],
        ['Puissance de cuisson',      f"{thermique['puissance_cuis_kW']:.3f} kW"],
        ['Taux de combustion',        f"{thermique['taux_combustion_g_min']:.2f} g/min"],
    ]

    parametres = [l[0] for l in lignes]
    valeurs    = [l[1] for l in lignes]

    # Couleur alternée des lignes
    couleurs_lignes = ['#F5F5F5' if i % 2 == 0 else 'white' for i in range(len(lignes))]

    fig = go.Figure(data=[go.Table(
        columnwidth=[250, 200],
        header=dict(
            values=['<b>Paramètre</b>', '<b>Valeur</b>'],
            fill_color='#1565C0',
            font=dict(color='white', size=13),
            align='left',
            height=35,
        ),
        cells=dict(
            values=[parametres, valeurs],
            fill_color=[couleurs_lignes, couleurs_lignes],
            align=['left', 'right'],
            font=dict(size=12),
            height=28,
        ),
    )])

    fig.update_layout(
        title=dict(text='Résultats complets de l\'analyse LEMS', font=dict(size=16)),
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor='white',
    )
    return fig


# ─────────────────────────────────────────────────────────────────────
# 6. Jauge Tier IWA-11
# ─────────────────────────────────────────────────────────────────────

def graphique_tier(tier: int, stats: dict) -> go.Figure:
    """
    Jauge indiquant le Tier ISO/IWA-11 obtenu (0 à 4).
    """
    couleur = TIER_COULEURS.get(tier, '#F44336')

    fig = go.Figure(go.Indicator(
        mode='gauge+number+delta',
        value=tier,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': 'Tier ISO/IWA-11', 'font': {'size': 18}},
        delta={'reference': 3, 'increasing': {'color': '#4CAF50'}},
        gauge={
            'axis': {'range': [0, 4], 'tickvals': [0, 1, 2, 3, 4],
                     'ticktext': ['0', '1', '2', '3', '4']},
            'bar': {'color': couleur},
            'steps': [
                {'range': [0, 1], 'color': '#FFEBEE'},
                {'range': [1, 2], 'color': '#FFF3E0'},
                {'range': [2, 3], 'color': '#FFFDE7'},
                {'range': [3, 4], 'color': '#E8F5E9'},
            ],
            'threshold': {
                'line': {'color': '#212121', 'width': 3},
                'thickness': 0.75,
                'value': tier,
            },
        },
        number={'font': {'size': 48, 'color': couleur}},
    ))

    co_g_min  = stats['CO_taux_moy_mg_min'] / 1000
    pm_mg_min = stats['PM_taux_moy_mg_min']
    annotation = (
        f"CO moy : {co_g_min:.5f} g/min<br>"
        f"PM moy : {pm_mg_min:.4f} mg/min"
    )

    fig.update_layout(
        paper_bgcolor='white',
        margin=dict(l=30, r=30, t=80, b=30),
        annotations=[dict(
            text=annotation,
            x=0.5, y=0.15,
            showarrow=False,
            font=dict(size=13),
            align='center',
        )],
    )
    return fig


# ─────────────────────────────────────────────────────────────────────
# 7. Comparaison données brutes / calibrées
# ─────────────────────────────────────────────────────────────────────

def tableau_calibration_df(
    df_brut: pd.DataFrame,
    df_cal: pd.DataFrame,
    calibration: list,
) -> pd.DataFrame:
    """
    Retourne un DataFrame pédagogique expliquant les facteurs de calibration.
    Colonnes : Capteur | Description | Valeur brute moy. | × Facteur | = Valeur calibrée.
    """
    NOMS  = ['CO', 'GasTemp', 'PM', 'Flow', 'FlueTemp', 'TC', 'CO2', 'PM_RH']
    UNITS = ['ppm', '°C', 'µg/m³', 'log-units', '°C', '°C', 'ppm', 'µg/m³']
    DESCS = [
        'Monoxyde de carbone (polluant principal)',
        'Température des gaz dans le tunnel de dilution',
        'Particules fines PM₂.₅',
        'Débit volumique — convertir log-units → ΔP via formule Pitot',
        'Température de la cheminée (FlueTemp)',
        'Thermocouple de référence',
        'Dioxyde de carbone',
        'PM₂.₅ avec correction humidité relative',
    ]
    cal_pad = (list(calibration) + [1.0] * 8)[:8]
    rows = []
    for i, (nom, unite, desc) in enumerate(zip(NOMS, UNITS, DESCS)):
        brut = df_brut[nom].mean() if nom in df_brut.columns else None
        cal  = df_cal[nom].mean()  if nom in df_cal.columns  else None
        rows.append({
            'Capteur'              : nom,
            'Description'          : desc,
            'Valeur brute moy.'    : f'{brut:.0f} log-units' if brut is not None else 'N/A',
            '× Facteur'            : f'{cal_pad[i]:.5g}',
            '= Valeur calibrée'    : f'{cal:.2f} {unite}'    if cal  is not None else 'N/A',
        })
    return pd.DataFrame(rows).set_index('Capteur')


def graphique_comparaison_calibration(
    df_brut: pd.DataFrame,
    df_cal: pd.DataFrame,
    calibration: list,
) -> go.Figure:
    """
    Grille 4 lignes × 2 colonnes : un capteur par ligne.
    Colonne gauche = signal BRUT (log-units, gris).
    Colonne droite = signal CALIBRÉ (unité physique, couleur).
    Les formes doivent être identiques → calibration fiable.
    """
    SELECTION = [
        ('CO',      'ppm',    '#2196F3', 'CO',      'Monoxyde de carbone'),
        ('PM',      'µg/m³',  '#F44336', 'PM₂.₅',  'Particules fines'),
        ('GasTemp', '°C',     '#9C27B0', 'GasTemp', 'Température des gaz'),
        ('CO2',     'ppm',    '#4CAF50', 'CO₂',     'Dioxyde de carbone'),
    ]
    t = df_brut['seconds'] / 60.0

    def _correlation(a: pd.Series, b: pd.Series) -> float:
        try:
            r = float(a.fillna(0).corr(b.fillna(0)))
            return 0.0 if (r != r) else r  # NaN → 0.0
        except Exception:
            return 0.0  # 1.0 était un bug : exception = ✅ faux

    def _verdict(r: float) -> str:
        if r > 0.90:
            return '✅ Formes identiques'
        if r < -0.90:
            return f'🔄 Signal inversé (r={r:.2f}) — facteur négatif ?'
        return f'⚠️ Vérifier (r={r:.2f})'

    # Titres : colonne gauche = brut, colonne droite = calibré avec verdict
    panel_titles = []
    verdicts = []
    for nom, unite, color, court, long_label in SELECTION:
        y_b = df_brut[nom] if nom in df_brut.columns else pd.Series(dtype=float)
        y_c = df_cal[nom]  if nom in df_cal.columns  else pd.Series(dtype=float)
        r   = _correlation(y_b, y_c)
        verdicts.append(r)
        panel_titles.append(f'{court} — brut (log-units)')
        panel_titles.append(f'{court} — calibré ({unite})  {_verdict(r)}')

    fig = make_subplots(
        rows=4, cols=2,
        subplot_titles=panel_titles,
        shared_xaxes=True,
        vertical_spacing=0.07,
        horizontal_spacing=0.12,
    )

    for i, (nom, unite, color, court, long_label) in enumerate(SELECTION):
        row = i + 1
        y_b = df_brut[nom] if nom in df_brut.columns else pd.Series(dtype=float)
        y_c = df_cal[nom]  if nom in df_cal.columns  else pd.Series(dtype=float)

        # ── Colonne gauche : signal brut ──────────────────────────────
        fig.add_trace(go.Scatter(
            x=t, y=y_b,
            name=f'{court} brut',
            showlegend=False,
            line=dict(color='#757575', width=1.5),
            fill='tozeroy',
            fillcolor='rgba(117,117,117,0.08)',
            hovertemplate=f'<b>{court} brut</b> : %{{y:.0f}} log-units<extra></extra>',
        ), row=row, col=1)

        # ── Colonne droite : signal calibré ───────────────────────────
        fig.add_trace(go.Scatter(
            x=t, y=y_c,
            name=f'{court} calibré',
            showlegend=False,
            line=dict(color=color, width=1.8),
            fill='tozeroy',
            fillcolor=f'rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.10)',
            hovertemplate=f'<b>{court} calibré</b> : %{{y:.2f}} {unite}<extra></extra>',
        ), row=row, col=2)

        # Axes brut (gris)
        fig.update_yaxes(
            title_text='log-units',
            title_font=dict(color='#757575', size=10),
            tickfont=dict(color='#757575', size=9),
            showgrid=True, gridcolor='#F5F5F5', zeroline=False,
            row=row, col=1,
        )
        # Axes calibré (couleur)
        fig.update_yaxes(
            title_text=unite,
            title_font=dict(color=color, size=10),
            tickfont=dict(color=color, size=9),
            showgrid=True, gridcolor='#F5F5F5', zeroline=False,
            row=row, col=2,
        )

    # Axe X uniquement sur la dernière ligne
    for col in [1, 2]:
        fig.update_xaxes(
            title_text='Temps (min)',
            title_font=dict(size=11),
            tickfont=dict(size=10),
            showgrid=True, gridcolor='#EEEEEE',
            zeroline=False, row=4, col=col,
        )

    fig.update_layout(
        height=820,
        title=dict(
            text='Calibration — BRUT (gauche) vs CALIBRÉ (droite) · Formes identiques = calibration fiable',
            font=dict(size=13, color='#333'),
            x=0.5, xanchor='center',
        ),
        plot_bgcolor='white', paper_bgcolor='white',
        hovermode='x unified',
        font=dict(family='Arial', size=11),
        margin=dict(l=70, r=70, t=80, b=50),
        showlegend=False,
    )
    fig.update_annotations(font=dict(size=11, color='#333'))
    return fig


# ─────────────────────────────────────────────────────────────────────
# Test rapide si on lance ce fichier directement
# ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')
    from import_csv import lire_csv
    from calculs import analyser

    fichier = sys.argv[1] if len(sys.argv) > 1 else 'csv/01-12-2022-Sakkanal-T11.csv'

    res_csv = lire_csv(fichier)
    res     = analyser(res_csv)

    # Génération de tous les graphiques et sauvegarde HTML
    figs = {
        'concentrations'          : graphique_concentrations(res['df_cal']),
        'taux_emission'           : graphique_taux_emission(res['df_taux']),
        'temperatures'            : graphique_temperature(res['df_cal']),
        'debit'                   : graphique_debit(res['df_cal']),
        'tableau'                 : tableau_resume(
                                        res['stats'], res['totaux'], res['thermique'],
                                        res['tier'], res['label_tier'], res['duree_min']),
        'tier'                    : graphique_tier(res['tier'], res['stats']),
        'comparaison_calibration' : graphique_comparaison_calibration(
                                        res['df_brut'], res['df_cal'], res_csv['calibration']),
    }

    for nom, fig in figs.items():
        chemin = f'csv/{nom}.html'
        fig.write_html(chemin)
        print(f'Graphique sauvegardé : {chemin}')

    print(f"\nTier obtenu : {res['tier']} — {res['label_tier']}")
