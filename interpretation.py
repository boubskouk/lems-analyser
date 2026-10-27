#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module d'interprétation professionnelle des résultats LEMS.
Références : ISO 19867-1 · IWA-11 · Tableau calcul puissance Bois 5 Tests.xlsx
"""

import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
# Seuils IWA-11 (taux d'émission instantanés)
# ─────────────────────────────────────────────────────────────────────────────
SEUILS_CO_G_MIN  = {4: 0.50,  3: 2.00,  2: 4.00,  1: 8.00}
SEUILS_PM_MG_MIN = {4: 0.50,  3: 2.50,  2: 5.00,  1: 10.00}

# Seuils ISO 19867-1 normalisés par énergie utile (g/MJd et mg/MJd)
# Source : T1.xlsx feuille ISO + documentation Aprovecho
SEUILS_CO_G_MJD  = {5: 3.0,   4: 4.4,   3: 7.2,   2: 11.5,  1: 18.3}
SEUILS_PM_MG_MJD = {5: 5.0,   4: 62.0,  3: 218.0, 2: 481.0, 1: 1030.0}

# Seuils efficacité thermique avec charbon (ISO 19867-1)
SEUILS_EFF_PCT   = {5: 50.0,  4: 40.0,  3: 30.0,  2: 20.0,  1: 10.0}

# Valeurs de référence empiriques (Tableau calcul puissance Bois 5 Tests.xlsx)
REF_5TESTS = {
    'HP': {'eff_avec_char': 48.18, 'eff_sd': 3.36, 'pm_utile': 743.5,  'co_utile': 2.66},
    'MP': {'eff_avec_char': 46.26, 'eff_sd': 1.43, 'pm_utile': 990.1,  'co_utile': 2.82},
    'BP': {'eff_avec_char': 42.22, 'eff_sd': 6.55, 'pm_utile': 782.2,  'co_utile': 3.00},
}

# ─────────────────────────────────────────────────────────────────────────────
# Palettes
# ─────────────────────────────────────────────────────────────────────────────
TIER_COUL  = {5: '#1B5E20', 4: '#2E7D32', 3: '#558B2F', 2: '#E65100', 1: '#BF360C', 0: '#B71C1C'}
TIER_BG    = {5: '#E8F5E9', 4: '#E8F5E9', 3: '#F1F8E9', 2: '#FFF3E0', 1: '#FBE9E7', 0: '#FFEBEE'}
TIER_LABEL = {5: 'Excellent+', 4: 'Excellent', 3: 'Bon', 2: 'Intermédiaire', 1: 'Basique', 0: 'Hors normes'}
TIER_EMOJI = {5: '🟢', 4: '🟢', 3: '🟡', 2: '🟠', 1: '🔴', 0: '⛔'}
PHASE_NOM  = {'HP': 'Haute Puissance', 'MP': 'Moyenne Puissance', 'BP': 'Basse Puissance'}

MCE_SEUILS = [
    (99.5, 'Combustion quasi-complète — très faible CO résiduel'),
    (98.0, 'Très bonne combustion — CO maîtrisé'),
    (95.0, 'Bonne combustion'),
    (90.0, 'Combustion incomplète — CO significatif'),
    (0,    'Combustion très incomplète'),
]

# ─────────────────────────────────────────────────────────────────────────────
# Fonctions de classement
# ─────────────────────────────────────────────────────────────────────────────

def _tier_inferieur(val, seuils):
    """Retourne le Tier maximum dont le seuil est respecté (ordre décroissant).

    Robustesse (2026-10-18) : None/NaN -> 0 (voir _avertissement_valeur()
    pour le message à afficher). Ces deux cas sont traités AVANT tout
    max(val, 0.0), car max(nan, 0.0) renvoie nan en Python (pas 0.0) — le
    clamp seul ne neutraliserait pas un NaN. Valeur négative classée comme 0
    (résultat numérique inchangé, une valeur négative étant déjà sous tout
    seuil positif)."""
    if val is None:
        return 0
    if val != val:  # NaN : seule valeur flottante telle que val != val
        return 0
    val = max(val, 0.0)
    for t in sorted(seuils.keys(), reverse=True):
        if val < seuils[t]:
            return t
    return 0


def _avertissement_valeur(nom, val):
    """Message d'avertissement si val est invalide ou négative, sinon None.
    Purement informatif : ne change jamais le Tier renvoyé par
    _tier_inferieur()."""
    if val is None:
        return (f"Tier non calculable (valeur de {nom} manquante) — Tier "
                f"affiché (0) à titre indicatif, à ne pas interpréter "
                f"comme un résultat réel.")
    if val != val:  # NaN
        return (f"Tier non calculable (valeur de {nom} invalide : NaN) — "
                f"Tier affiché (0) à titre indicatif, à ne pas interpréter "
                f"comme un résultat réel.")
    if val < 0:
        return ("Valeur négative après soustraction du bruit de fond — "
                "Tier à confirmer.")
    return None

def _tier_eff(eff_pct):
    for t in sorted(SEUILS_EFF_PCT.keys(), reverse=True):
        if eff_pct >= SEUILS_EFF_PCT[t]:
            return t
    return 0

def _mce_label(mce):
    for seuil, label in MCE_SEUILS:
        if mce >= seuil:
            return label
    return MCE_SEUILS[-1][1]


# ─────────────────────────────────────────────────────────────────────────────
# Analyse complète d'une phase
# ─────────────────────────────────────────────────────────────────────────────

def analyser_phase(code, r):
    """Retourne un dict d'analyse détaillée pour une phase."""
    co_g_min  = r['stats']['CO_taux_moy_mg_min'] / 1000.0
    pm_mg_min = r['stats']['PM_taux_moy_mg_min']
    eff       = r['thermique']['efficacite_avec_char_pct']
    eff_sc    = r['thermique']['efficacite_sans_char_pct']
    a_residu  = r['thermique'].get('a_residu_charbonneux', True)
    mce       = r['stats']['MCE_pct']
    co_mjd    = r['normalises'].get('CO_par_utile_g_MJ', 0.0)
    pm_mjd    = r['normalises'].get('PM_par_utile_mg_MJ', 0.0)

    t_co_rate = _tier_inferieur(co_g_min,  SEUILS_CO_G_MIN)
    t_pm_rate = _tier_inferieur(pm_mg_min, SEUILS_PM_MG_MIN)
    t_co_mjd  = _tier_inferieur(co_mjd,    SEUILS_CO_G_MJD)
    t_pm_mjd  = _tier_inferieur(pm_mjd,    SEUILS_PM_MG_MJD)
    t_eff     = _tier_eff(eff)
    avertissement_tier = (_avertissement_valeur('CO', co_mjd)
                           or _avertissement_valeur('PM2,5', pm_mjd))
    # Tier global = seuils officiels ISO 19867-1 Tableau 1 (g/MJd, mg/MJd), confirmés
    # le 2026-10-16 contre le texte de la norme (photo). Les seuils g/min
    # (SEUILS_CO_G_MIN / SEUILS_PM_MG_MIN) restent affichés en info secondaire
    # mais ne pilotent plus le Tier global, leur origine n'ayant jamais été confirmée.
    t_iwa11   = min(t_co_mjd, t_pm_mjd)

    # Facteur limitant (ce qui plafonne le Tier IWA-11), sur la base des seuils officiels
    if t_co_mjd <= t_pm_mjd:
        seuil_next = SEUILS_CO_G_MJD.get(t_co_mjd + 1, None)
        seuil_ref  = SEUILS_CO_G_MJD.get(t_co_mjd, SEUILS_CO_G_MJD[1])
        if seuil_next:
            limitant = (f'CO — {co_mjd:.2f} g/MJd '
                        f'(seuil Tier {t_co_mjd+1} : {seuil_next} g/MJd, '
                        f'ecart : +{co_mjd - seuil_ref:.2f})')
        else:
            limitant = f'CO — {co_mjd:.2f} g/MJd (depasse Tier 1)'
    else:
        seuil_next = SEUILS_PM_MG_MJD.get(t_pm_mjd + 1, None)
        seuil_ref  = SEUILS_PM_MG_MJD.get(t_pm_mjd, SEUILS_PM_MG_MJD[1])
        if seuil_next:
            limitant = (f'PM2.5 — {pm_mjd:.1f} mg/MJd '
                        f'(seuil Tier {t_pm_mjd+1} : {seuil_next} mg/MJd, '
                        f'ecart : +{pm_mjd - seuil_ref:.1f})')
        else:
            limitant = f'PM2.5 — {pm_mjd:.1f} mg/MJd (depasse Tier 1)'

    # Comparaison aux 5 tests de référence
    ref = REF_5TESTS.get(code, {})
    vs_ref_eff = eff - ref.get('eff_avec_char', eff)

    return {
        'code': code, 'label': PHASE_NOM.get(code, code),
        'co_g_min': co_g_min, 't_co_rate': t_co_rate,
        'pm_mg_min': pm_mg_min, 't_pm_rate': t_pm_rate,
        'co_mjd': co_mjd, 't_co_mjd': t_co_mjd,
        'pm_mjd': pm_mjd, 't_pm_mjd': t_pm_mjd,
        'eff': eff, 'eff_sc': eff_sc, 't_eff': t_eff, 'a_residu_charbonneux': a_residu,
        'mce': mce, 'mce_label': _mce_label(mce),
        't_iwa11': t_iwa11, 'limitant': limitant,
        'avertissement_tier': avertissement_tier,
        'vs_ref_eff': vs_ref_eff,
        'ref': ref,
        'duree_min': r['duree_min'],
        'co_total_g': r['totaux']['CO_total_g'],
        'pm_total_mg': r['totaux']['PM_total_mg'],
        'puissance_cuis_W': r['thermique']['puissance_cuis_kW'] * 1000,
        'taux_comb': r['thermique']['taux_combustion_g_min'],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Graphique 1 — Jauges d'émissions CO + PM par phase
# ─────────────────────────────────────────────────────────────────────────────

def graphique_jauges_emissions(analyses):
    phases = list(analyses.values())
    n = len(phases)
    if n == 0:
        return go.Figure()

    co_max = 10.0
    pm_max = 12.0

    fig = make_subplots(
        rows=2, cols=n,
        specs=[[{'type': 'domain'}] * n] * 2,
        subplot_titles=(
            [f"CO (g/min)  ·  {a['label']}" for a in phases] +
            [f"PM₂.₅ (mg/min)  ·  {a['label']}" for a in phases]
        ),
        vertical_spacing=0.22,
        horizontal_spacing=0.06,
    )

    # Zones plus contrastées : vert foncé → vert clair → jaune → orange → rouge
    def _steps_co():
        return [
            dict(range=[0,                      SEUILS_CO_G_MIN[4]], color='#81C784'),
            dict(range=[SEUILS_CO_G_MIN[4],     SEUILS_CO_G_MIN[3]], color='#C5E1A5'),
            dict(range=[SEUILS_CO_G_MIN[3],     SEUILS_CO_G_MIN[2]], color='#FFF176'),
            dict(range=[SEUILS_CO_G_MIN[2],     SEUILS_CO_G_MIN[1]], color='#FFB74D'),
            dict(range=[SEUILS_CO_G_MIN[1],     co_max],             color='#E57373'),
        ]

    def _steps_pm():
        return [
            dict(range=[0,                       SEUILS_PM_MG_MIN[4]], color='#81C784'),
            dict(range=[SEUILS_PM_MG_MIN[4],     SEUILS_PM_MG_MIN[3]], color='#C5E1A5'),
            dict(range=[SEUILS_PM_MG_MIN[3],     SEUILS_PM_MG_MIN[2]], color='#FFF176'),
            dict(range=[SEUILS_PM_MG_MIN[2],     SEUILS_PM_MG_MIN[1]], color='#FFB74D'),
            dict(range=[SEUILS_PM_MG_MIN[1],     pm_max],              color='#E57373'),
        ]

    def _prox(val, tier, seuils, unit):
        """Texte indiquant la distance au seuil du Tier suivant."""
        if tier < 4:
            seuil_next = seuils[tier + 1]
            ecart = val - seuil_next
            if ecart > 0:
                return f"→ Réduire de {ecart:.3f} {unit} pour Tier {tier + 1} (seuil : {seuil_next} {unit})"
            return f"✓ En dessous du seuil Tier {tier + 1} ({seuil_next} {unit})"
        return "✓ Tier 4 atteint — performances excellentes"

    for i, a in enumerate(phases):
        col = i + 1
        t_co = a['t_co_rate']
        t_pm = a['t_pm_rate']
        c_co = TIER_COUL.get(t_co, '#888')
        c_pm = TIER_COUL.get(t_pm, '#888')

        prox_co = _prox(a['co_g_min'],  t_co, SEUILS_CO_G_MIN,  'g/min')
        prox_pm = _prox(a['pm_mg_min'], t_pm, SEUILS_PM_MG_MIN, 'mg/min')

        # ── Jauge CO ──────────────────────────────────────────────────
        fig.add_trace(go.Indicator(
            mode='gauge+number',
            value=a['co_g_min'],
            number=dict(
                suffix=' g/min',
                font=dict(size=19, color=c_co),
                valueformat='.4f',
            ),
            title=dict(
                text=(
                    f"<b><span style='color:{c_co};font-size:15px'>"
                    f"Tier {t_co} — {TIER_LABEL[t_co]}</span></b>"
                    f"<br><span style='font-size:10px;color:#555'>{prox_co}</span>"
                ),
                font=dict(size=13),
            ),
            gauge=dict(
                axis=dict(
                    range=[0, co_max],
                    tickfont=dict(size=9),
                    tickvals=[0, SEUILS_CO_G_MIN[4], SEUILS_CO_G_MIN[3],
                               SEUILS_CO_G_MIN[2], SEUILS_CO_G_MIN[1], co_max],
                    ticktext=['0', 'T4\n0.5', 'T3\n2.0', 'T2\n4.0', 'T1\n8.0', '10'],
                ),
                bar=dict(color=c_co, thickness=0.35),
                bgcolor='white',
                borderwidth=1,
                bordercolor='#E0E0E0',
                steps=_steps_co(),
                threshold=dict(
                    line=dict(color='#212121', width=4),
                    thickness=0.85,
                    value=a['co_g_min'],
                ),
            ),
        ), row=1, col=col)

        # ── Jauge PM₂.₅ ───────────────────────────────────────────────
        fig.add_trace(go.Indicator(
            mode='gauge+number',
            value=a['pm_mg_min'],
            number=dict(
                suffix=' mg/min',
                font=dict(size=19, color=c_pm),
                valueformat='.4f',
            ),
            title=dict(
                text=(
                    f"<b><span style='color:{c_pm};font-size:15px'>"
                    f"Tier {t_pm} — {TIER_LABEL[t_pm]}</span></b>"
                    f"<br><span style='font-size:10px;color:#555'>{prox_pm}</span>"
                ),
                font=dict(size=13),
            ),
            gauge=dict(
                axis=dict(
                    range=[0, pm_max],
                    tickfont=dict(size=9),
                    tickvals=[0, SEUILS_PM_MG_MIN[4], SEUILS_PM_MG_MIN[3],
                               SEUILS_PM_MG_MIN[2], SEUILS_PM_MG_MIN[1], pm_max],
                    ticktext=['0', 'T4\n0.5', 'T3\n2.5', 'T2\n5.0', 'T1\n10', '12'],
                ),
                bar=dict(color=c_pm, thickness=0.35),
                bgcolor='white',
                borderwidth=1,
                bordercolor='#E0E0E0',
                steps=_steps_pm(),
                threshold=dict(
                    line=dict(color='#212121', width=4),
                    thickness=0.85,
                    value=a['pm_mg_min'],
                ),
            ),
        ), row=2, col=col)

    fig.update_layout(
        height=640,
        paper_bgcolor='white',
        font=dict(family='Arial', size=12),
        margin=dict(l=20, r=20, t=70, b=20),
    )
    fig.update_annotations(font=dict(size=13, color='#212121'))
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Graphique 2 — Radar de performance (5 critères normalisés)
# ─────────────────────────────────────────────────────────────────────────────

def graphique_radar(analyses):
    categories = [
        'Efficacité\nthermique',
        'Qualité\ncombustion (MCE)',
        'Émissions CO\n(IWA-11)',
        'Émissions PM₂.₅\n(IWA-11)',
        'CO normalisé\n(g/MJd)',
    ]
    colors = {'HP': '#1565C0', 'MP': '#E65100', 'BP': '#2E7D32'}
    fig = go.Figure()

    for a in analyses.values():
        # Scores normalisés 0→100 (100 = meilleur)
        eff_s  = min(100, a['eff'] / SEUILS_EFF_PCT[5] * 100)
        mce_s  = min(100, max(0, (a['mce'] - 88) / (99.5 - 88) * 100))
        co_s   = max(0, 100 - a['co_g_min'] / SEUILS_CO_G_MIN[1] * 100)
        pm_s   = max(0, 100 - a['pm_mg_min'] / SEUILS_PM_MG_MIN[1] * 100)
        co_n_s = max(0, 100 - a['co_mjd'] / SEUILS_CO_G_MJD[1] * 100)

        vals = [eff_s, mce_s, co_s, pm_s, co_n_s]
        vals.append(vals[0])
        cats = categories + [categories[0]]

        c = colors.get(a['code'], '#888')
        # Convert hex to rgba for fillcolor (Plotly doesn't support 8-char hex)
        r_hex = int(c[1:3], 16)
        g_hex = int(c[3:5], 16)
        b_hex = int(c[5:7], 16)
        fill_rgba = f'rgba({r_hex},{g_hex},{b_hex},0.18)'
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=cats,
            fill='toself', name=f"{a['code']} ({a['label']})",
            fillcolor=fill_rgba,
            line=dict(color=c, width=2.5),
            hovertemplate='%{theta} : %{r:.0f}/100<extra>' + a['code'] + '</extra>',
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100],
                            tickvals=[25, 50, 75, 100],
                            tickfont=dict(size=10), gridcolor='#E0E0E0'),
            angularaxis=dict(tickfont=dict(size=12), linecolor='#BDBDBD'),
            bgcolor='white',
        ),
        showlegend=True,
        legend=dict(orientation='h', y=-0.15, x=0.5, xanchor='center', font=dict(size=12)),
        height=380,
        paper_bgcolor='white',
        font=dict(family='Arial'),
        margin=dict(l=50, r=50, t=20, b=70),
        title=dict(text='Score normalisé (100 = meilleur)', font=dict(size=12), x=0.5),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Graphique 3 — Barres comparatives efficacité vs référence
# ─────────────────────────────────────────────────────────────────────────────

def graphique_efficacite(analyses):
    codes  = list(analyses.keys())
    eff_ac = [analyses[c]['eff']    for c in codes]
    eff_sc = [analyses[c]['eff_sc'] for c in codes]
    ref_ac = [REF_5TESTS.get(c, {}).get('eff_avec_char', None) for c in codes]
    ref_sd = [REF_5TESTS.get(c, {}).get('eff_sd', 0) for c in codes]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name='Efficacité avec charbon (%)',
        x=codes, y=eff_ac,
        marker_color=['#1565C0', '#E65100', '#2E7D32'][:len(codes)],
        text=[f'{v:.1f}%' for v in eff_ac],
        textposition='outside', textfont=dict(size=13),
    ))
    fig.add_trace(go.Bar(
        name='Efficacité sans charbon (%)',
        x=codes, y=eff_sc,
        marker_color=['#90CAF9', '#FFCC80', '#A5D6A7'][:len(codes)],
        text=[f'{v:.1f}%' for v in eff_sc],
        textposition='outside', textfont=dict(size=13),
    ))

    # Ligne de référence (5 tests CERER)
    for i, (c, r, sd) in enumerate(zip(codes, ref_ac, ref_sd)):
        if r is not None:
            fig.add_trace(go.Scatter(
                x=[c], y=[r],
                mode='markers', name=f'Réf. 5 tests {c}',
                marker=dict(symbol='diamond', size=12, color='#F44336',
                            line=dict(width=2, color='#B71C1C')),
                error_y=dict(type='data', array=[sd], visible=True,
                             color='#F44336', thickness=2),
                showlegend=(i == 0),
            ))

    # Lignes des seuils Tier
    seuils_eff_label = [(SEUILS_EFF_PCT[4], 'Tier 4 (40%)', '#2E7D32'),
                        (SEUILS_EFF_PCT[3], 'Tier 3 (30%)', '#558B2F'),
                        (SEUILS_EFF_PCT[2], 'Tier 2 (20%)', '#E65100')]
    for seuil, label, color in seuils_eff_label:
        fig.add_hline(y=seuil, line=dict(color=color, width=1.5, dash='dash'),
                      annotation_text=label,
                      annotation_font=dict(size=10, color=color),
                      annotation_position='right')

    fig.update_layout(
        barmode='group',
        yaxis=dict(title='Efficacité thermique (%)', range=[0, 75],
                   title_font=dict(size=13), tickfont=dict(size=12)),
        xaxis=dict(title='Phase', title_font=dict(size=13), tickfont=dict(size=13)),
        height=380,
        plot_bgcolor='white', paper_bgcolor='white',
        legend=dict(orientation='h', y=-0.20, x=0.5, xanchor='center', font=dict(size=11)),
        margin=dict(l=60, r=80, t=30, b=80),
        font=dict(family='Arial'),
    )
    fig.update_yaxes(showgrid=True, gridcolor='#EEEEEE')
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Texte d'interprétation automatique (Markdown)
# ─────────────────────────────────────────────────────────────────────────────

def generer_texte(analyses, nom_fichier='', nom_testeur='', nom_fourneau='',
                  date_test='', lieu_test='', n_replique=None, remarques=''):
    tier_global = min(a['t_iwa11'] for a in analyses.values())
    n = len(analyses)
    phases_str = ' / '.join(f"**{c}**" for c in analyses)

    # ── Bloc identification ───────────────────────────────────────────────────
    id_lignes = []
    if nom_fourneau:
        id_lignes.append(f"**Fourneau / poêle :** {nom_fourneau}")
    if n_replique:
        id_lignes.append(f"**N° de réplique :** {n_replique}")
    if nom_testeur:
        id_lignes.append(f"**Testeur(s) :** {nom_testeur}")
    if date_test:
        id_lignes.append(f"**Date du test :** {date_test}")
    if lieu_test:
        id_lignes.append(f"**Lieu :** {lieu_test}")
    if remarques:
        id_lignes.append(f"**Remarques :** {remarques}")

    bloc_id = ''
    if id_lignes:
        bloc_id = (
            "---\n"
            + "  \n".join(id_lignes)
            + "\n\n---\n\n"
        )

    intro = (
        bloc_id +
        f"L'analyse LEMS du fichier **{nom_fichier}** porte sur {n} phase(s) "
        f"({phases_str}). "
        f"Le foyer est classé **{TIER_EMOJI[tier_global]} Tier {tier_global} — "
        f"{TIER_LABEL[tier_global]}** selon la norme ISO/IWA-11, "
        f"ce classement étant déterminé par la phase la plus défavorable."
    )

    lignes_phases = []
    for a in analyses.values():
        ref = a['ref']
        vs_eff = a['vs_ref_eff']
        signe  = '+' if vs_eff >= 0 else ''
        ref_txt = (f" (réf. 5 tests CERER : {ref.get('eff_avec_char', '—'):.1f}% "
                   f"± {ref.get('eff_sd', 0):.1f}%, écart actuel : {signe}{vs_eff:.1f}%)")

        eff_lbl = 'avec résidu charbonneux' if a['a_residu_charbonneux'] else 'résidu non applicable à ce combustible'
        txt = (
            f"**Phase {a['code']} — {a['label']} :**  \n"
            f"- Durée : {a['duree_min']:.1f} min  \n"
            f"- Efficacité thermique ({eff_lbl}) : **{a['eff']:.1f}%** "
            f"→ Tier {a['t_eff']} ({TIER_LABEL[a['t_eff']]}){ref_txt}  \n"
            f"- CO : **{a['co_mjd']:.2f} g/MJd** → Tier {a['t_co_mjd']} (ISO) "
            f"| taux instantané : {a['co_g_min']:.4f} g/min  \n"
            f"- PM₂.₅ : **{a['pm_mjd']:.1f} mg/MJd** → Tier {a['t_pm_mjd']} (ISO) "
            f"| taux instantané : {a['pm_mg_min']:.4f} mg/min  \n"
            f"- MCE : **{a['mce']:.2f}%** — {a['mce_label']}  \n"
            f"- ⚠️ Facteur limitant : {a['limitant']}"
        )
        if a.get('avertissement_tier'):
            txt += f"  \n- ⚠️ **{a['avertissement_tier']}**"
        lignes_phases.append(txt)

    if tier_global >= 4:
        verdict = (
            "✅ **Verdict global — Performances excellentes (Tier 4)**  \n"
            "Le foyer répond aux exigences des foyers améliorés de haute performance. "
            "Les émissions de CO et PM₂.₅ sont maîtrisées sur toutes les phases. "
            "Pour confirmer ces résultats, il est recommandé de réaliser un minimum "
            "de 5 tests WBT complets conformément à l'ISO 19867-1."
        )
    elif tier_global == 3:
        verdict = (
            "🟡 **Verdict global — Bonnes performances (Tier 3)**  \n"
            "Le foyer présente de bonnes performances mais n'atteint pas encore "
            "l'excellence (Tier 4). Des améliorations ciblées sur le facteur limitant "
            "identifié permettraient d'atteindre le palier supérieur."
        )
    elif tier_global == 2:
        verdict = (
            "🟠 **Verdict global — Performances intermédiaires (Tier 2)**  \n"
            "Le foyer nécessite des améliorations significatives pour répondre aux "
            "standards des foyers améliorés. Les émissions dépassent les seuils Tier 3 "
            "sur au moins une phase."
        )
    else:
        verdict = (
            f"🔴 **Verdict global — Performances insuffisantes (Tier {tier_global})**  \n"
            "Des interventions techniques importantes sont nécessaires pour améliorer "
            "les émissions et/ou l'efficacité du foyer."
        )

    return intro + '\n\n' + '\n\n'.join(lignes_phases) + '\n\n' + verdict


# ─────────────────────────────────────────────────────────────────────────────
# Recommandations automatiques
# ─────────────────────────────────────────────────────────────────────────────

def generer_recommandations(analyses):
    recs = []
    co_tiers  = [a['t_co_rate']  for a in analyses.values()]
    pm_tiers  = [a['t_pm_rate']  for a in analyses.values()]
    eff_vals  = [a['eff']        for a in analyses.values()]
    mce_vals  = [a['mce']        for a in analyses.values()]
    tier_glob = min(a['t_iwa11'] for a in analyses.values())

    if min(co_tiers) < 3:
        recs.append(('🔵 Émissions CO', (
            'Améliorer l\'alimentation en air primaire pour réduire le CO. '
            'Vérifier le tirage de la cheminée et assurer un allumage par le haut (TLUD). '
            'Utiliser du bois sec (humidité < 20 %) pour favoriser une combustion complète.'
        )))
    if min(pm_tiers) < 3:
        recs.append(('🔴 Émissions PM₂.₅', (
            'Réduire les particules fines en optimisant la taille des bûches '
            '(≤ 5 cm de diamètre) et en évitant le bois vert ou pourri. '
            'Améliorer le confinement de la chambre de combustion pour augmenter '
            'la température et favoriser l\'oxydation des particules.'
        )))
    if min(eff_vals) < 35:
        recs.append(('⚡ Efficacité thermique', (
            'Améliorer le transfert thermique vers le pot : réduire l\'espace '
            'entre le pot et la flamme (jupe), isoler la chambre de combustion '
            'et utiliser un couvercle de pot pour réduire les pertes par évaporation.'
        )))
    if min(mce_vals) < 95:
        recs.append(('🔥 Qualité de combustion (MCE)', (
            'La combustion est incomplète (MCE < 95 %). '
            'Augmenter l\'apport en air secondaire et maintenir une température '
            'de chambre > 600 °C. Éviter de surcharger le foyer en combustible.'
        )))
    if tier_glob >= 3:
        recs.append(('📋 Validation statistique', (
            'Les performances sont satisfaisantes. Pour homologuer ce foyer, '
            'réaliser 5 tests WBT complets (ISO 19867-1) avec calcul de la moyenne '
            'et de l\'intervalle de confiance à 90 % (IC90%). '
            'Documenter les conditions atmosphériques (T°, humidité, pression).'
        )))

    return recs
