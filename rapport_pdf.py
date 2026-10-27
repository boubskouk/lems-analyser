#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génération du rapport d'essai LEMS (PDF) — fpdf2 + police DejaVu Sans
embarquée (assets/fonts/), conforme au gabarit docs/modele_rapport_essai_LEMS.pdf.

Deux rapports :
    generer_rapport_test(...)  — rapport d'un test individuel (3 pages)
    generer_rapport_serie(...) — rapport de fin de série (mêmes sections +
                                  tableau multi-tests avec moyennes/écarts-types)

Classement Tier : uniquement les seuils ISO 19867-1 en g/MJd (CO) et mg/MJd
(PM2,5) — voir interpretation.SEUILS_CO_G_MJD / SEUILS_PM_MG_MJD. Aucune
colonne ni tableau de seuils en g/min n'est produit ici.
"""

import datetime
import os
import re

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from calculs import MSE_PM
from interpretation import (TIER_COUL, TIER_LABEL, SEUILS_CO_G_MJD,
                             SEUILS_PM_MG_MJD, SEUILS_EFF_PCT,
                             _tier_inferieur, _tier_eff, generer_recommandations)

APP_VERSION = '1.0'

_DIR = os.path.dirname(os.path.abspath(__file__))
_FONTS_DIR = os.path.join(_DIR, 'assets', 'fonts')
_LOGO_PATH = os.path.join(_DIR, 'assets', 'logo-cerer.png')
_LOGO_UCAD_PATH = os.path.join(_DIR, 'assets', 'logo-ucad-circle.png')

# ─────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────
VERT_FONCE   = '#163F31'
VERT         = '#1F5C45'
GRIS_TEXTE   = '#262626'
GRIS_MOYEN   = '#595959'
GRIS_CLAIR   = '#8A8A8A'
GRIS_FOND    = '#F2F4F3'
GRIS_BORD    = '#D9DEDC'
AMBRE_FOND   = '#FFF3CD'
BLANC        = '#FFFFFF'

COUL_PHASE = {'HP': '#1D4E89', 'MP': '#D08A2E', 'BP': '#5E9C98'}
PHASE_NOM  = {'HP': 'Haute Puissance', 'MP': 'Moyenne Puissance', 'BP': 'Basse Puissance'}

SEUILS_NIVEAU = {5: 'Le plus performant', 4: 'Très bon', 3: 'Bon',
                  2: 'Intermédiaire', 1: 'Basique', 0: 'Hors seuils'}

# ─────────────────────────────────────────────────────────────────────────
# Statistiques de série — Moyenne / Écart-type / IC 90%
# ─────────────────────────────────────────────────────────────────────────
# Valeur t de Student (bilatéral, 90%, ddof=N-1) pour petits échantillons
# (N=3 à 5 typique ISO 19867-1). Méthode statistique STANDARD — aucune
# formule n'est documentée dans les fichiers du projet/labo pour ce calcul
# (vérifié le 2026-10-27 : manuel ISO LEMS + questionnaires du labo ne
# contiennent que la mention "IC 90%" sans formule). À confirmer avec le
# labo si une méthode différente est utilisée.
_T_CRIT_90 = {2: 6.314, 3: 2.920, 4: 2.353, 5: 2.132, 6: 2.015,
              7: 1.943, 8: 1.895, 9: 1.860, 10: 1.833}


def _mean_sd_ci90(vals):
    """Retourne (moyenne, écart-type ddof=1, borne_basse_IC90, borne_haute_IC90).
    N=1 : écart-type et IC = la valeur elle-même (pas de dispersion calculable).
    N>10 : t fixé à la valeur N=10 (conservateur, approche la loi normale)."""
    import numpy as np
    n = len(vals)
    if n == 0:
        return None
    moyenne = float(np.mean(vals))
    if n == 1:
        return moyenne, 0.0, moyenne, moyenne
    sd = float(np.std(vals, ddof=1))
    t_crit = _T_CRIT_90.get(n, _T_CRIT_90[10])
    marge = t_crit * sd / (n ** 0.5)
    return moyenne, sd, moyenne - marge, moyenne + marge


def _combine_egal(valeurs_par_phase):
    """Moyenne simple (pondération égale 1/1/1, conforme aux poids par défaut
    des classeurs labo officiels, feuille ISO 'Weighting for voluntary
    performance Tiers') des 3 phases HP/MP/BP d'UN test. None si une phase
    manque pour ce test."""
    vals = [valeurs_par_phase.get(c) for c in ('HP', 'MP', 'BP')]
    if any(v is None for v in vals):
        return None
    return sum(vals) / len(vals)

PAGE_W = 210.0
MARGE  = 15.0
LARGEUR_UTILE = PAGE_W - 2 * MARGE


# ─────────────────────────────────────────────────────────────────────────
# Formatage français
# ─────────────────────────────────────────────────────────────────────────

def fr(valeur, decimales=1):
    """Formate un nombre en notation française (virgule, espace des milliers)."""
    if valeur is None:
        return '—'
    try:
        s = f'{float(valeur):,.{decimales}f}'
    except (TypeError, ValueError):
        return str(valeur)
    if '.' in s:
        entier, frac = s.split('.')
    else:
        entier, frac = s, ''
    entier = entier.replace(',', ' ')
    return f'{entier},{frac}' if decimales > 0 else entier


def fr_date(iso_ou_texte):
    """Convertit une date ISO 'AAAA-MM-JJ' en 'JJ/MM/AAAA' ; sinon renvoie tel quel."""
    if not iso_ou_texte:
        return '—'
    try:
        d = datetime.date.fromisoformat(str(iso_ou_texte).strip())
        return d.strftime('%d/%m/%Y')
    except ValueError:
        return str(iso_ou_texte)


def fr_heure(hms):
    """Convertit 'HH:MM:SS' en 'H h MM min SS s'."""
    if not hms:
        return '—'
    try:
        h, m, s = str(hms).strip().split(':')
        return f'{int(h)} h {int(m):02d} min {int(s):02d} s'
    except (ValueError, AttributeError):
        return str(hms)


def _v(ctx, cle, defaut='—'):
    val = ctx.get(cle)
    if val is None or (isinstance(val, str) and not val.strip()):
        return defaut
    return val


def _rejoindre(parts, sep=' · ', defaut='—'):
    parts = [str(p).strip() for p in parts if p is not None and str(p).strip()]
    return sep.join(parts) if parts else defaut


def _strip_emoji(texte):
    return re.sub(r'[^\x00-\x7FÀ-ſ₀-₉]+', '', texte).strip()


# ─────────────────────────────────────────────────────────────────────────
# Texte d'interprétation (factuel, sans formulation alarmiste)
# ─────────────────────────────────────────────────────────────────────────

def _limite_par(a):
    if a['t_co_mjd'] == a['t_pm_mjd']:
        return 'limité par CO et PM2,5'
    if a['t_co_mjd'] < a['t_pm_mjd']:
        return 'limité par le CO'
    return 'limité par les PM2,5'


def _phrase_resultat_principal(analyses, tier_global):
    limitantes = [a for a in analyses.values() if a['t_iwa11'] == tier_global]
    noms = ' et '.join(f"{a['label']} ({a['code']})" for a in limitantes)
    verbe = 'limite' if len(limitantes) == 1 else 'limitent'
    a0 = limitantes[0]
    if a0['t_co_mjd'] <= a0['t_pm_mjd']:
        valeur_txt = f"ses émissions de monoxyde de carbone : {fr(a0['co_mjd'], 2)} g/MJd"
        seuil_n = SEUILS_CO_G_MJD.get(a0['t_co_mjd'] + 1)
        seuil_txt = (f", au-dessus du seuil du Tier {a0['t_co_mjd'] + 1} "
                     f"({fr(seuil_n, 1)} g/MJd).") if seuil_n else '.'
    else:
        valeur_txt = f"ses émissions de particules fines (PM2,5) : {fr(a0['pm_mjd'], 1)} mg/MJd"
        seuil_n = SEUILS_PM_MG_MJD.get(a0['t_pm_mjd'] + 1)
        seuil_txt = (f", au-dessus du seuil du Tier {a0['t_pm_mjd'] + 1} "
                     f"({fr(seuil_n, 0)} mg/MJd).") if seuil_n else '.'
    return (f"Le Tier global est le plus faible des {len(analyses)} phases. "
            f"La phase {noms} {verbe} le classement par {valeur_txt}{seuil_txt}")


def _phrase_interpretation_phase(a):
    t_co, t_pm = a['t_co_mjd'], a['t_pm_mjd']
    co_val, pm_val = a['co_mjd'], a['pm_mjd']
    if t_co == t_pm:
        seuil_co_n = SEUILS_CO_G_MJD.get(t_co + 1)
        seuil_pm_n = SEUILS_PM_MG_MJD.get(t_pm + 1)
        if seuil_co_n is not None and seuil_pm_n is not None:
            return (f"Le CO ({fr(co_val, 2)} g/MJd) et les PM2,5 ({fr(pm_val, 1)} mg/MJd) "
                    f"dépassent les seuils du Tier {t_co + 1} "
                    f"({fr(seuil_co_n, 1)} g/MJd et {fr(seuil_pm_n, 0)} mg/MJd).")
        return (f"Le CO ({fr(co_val, 2)} g/MJd) et les PM2,5 ({fr(pm_val, 1)} mg/MJd) "
                f"sont tous deux classés Tier {t_co}.")
    if t_co < t_pm:
        seuil_co_n = SEUILS_CO_G_MJD.get(t_co + 1)
        if seuil_co_n is not None:
            return (f"Le CO atteint {fr(co_val, 2)} g/MJd, au-dessus du seuil du Tier "
                    f"{t_co + 1} ({fr(seuil_co_n, 1)} g/MJd). "
                    f"Les PM2,5 ({fr(pm_val, 1)} mg/MJd) restent en Tier {t_pm}.")
        return (f"Le CO ({fr(co_val, 2)} g/MJd) limite la phase au Tier {t_co}. "
                f"Les PM2,5 ({fr(pm_val, 1)} mg/MJd) restent en Tier {t_pm}.")
    seuil_pm_n = SEUILS_PM_MG_MJD.get(t_pm + 1)
    if seuil_pm_n is not None:
        return (f"Les PM2,5 atteignent {fr(pm_val, 1)} mg/MJd, au-dessus du seuil du Tier "
                f"{t_pm + 1} ({fr(seuil_pm_n, 0)} mg/MJd). "
                f"Le CO ({fr(co_val, 2)} g/MJd) reste en Tier {t_co}.")
    return (f"Les PM2,5 ({fr(pm_val, 1)} mg/MJd) limitent la phase au Tier {t_pm}. "
            f"Le CO ({fr(co_val, 2)} g/MJd) reste en Tier {t_co}.")


def _phrase_performance_phase(a, analyses):
    effs = [v['eff_sc'] for v in analyses.values()]
    mces = [v['mce'] for v in analyses.values()]
    suffixe_eff = ''
    if len(effs) > 1:
        if a['eff_sc'] == max(effs):
            suffixe_eff = ' — la plus élevée des trois phases'
        elif a['eff_sc'] == min(effs):
            suffixe_eff = ' — la plus faible des trois phases'
    suffixe_mce = ''
    if len(mces) > 1:
        if a['mce'] == min(mces):
            suffixe_mce = ' — la plus basse des trois phases'
        elif a['mce'] == max(mces):
            suffixe_mce = ' — la plus élevée des trois phases'
    return (f"Efficacité thermique : {fr(a['eff_sc'], 1)} % sans charbon "
            f"({fr(a['eff'], 1)} % avec charbon){suffixe_eff}. "
            f"MCE : {fr(a['mce'], 1)} %{suffixe_mce}.")


def _texte_remarques(ctx, resultats, est_serie):
    remarques = []
    if est_serie:
        n = ctx.get('nb_tests_enregistres', ctx.get('nb_tests', 1))
        remarques.append(
            f"Résultats de {n} test(s) de la série. La norme ISO 19867-1 prévoit au moins "
            f"3 répétitions ; le classement ci-dessus repose sur la moyenne de la série."
        )
    else:
        remarques.append(
            "Résultats d'un seul test. La norme ISO 19867-1 prévoit au moins 3 répétitions ; "
            "le classement définitif repose sur la moyenne de la série."
        )

    gravi = [c for c, r in (resultats or {}).items() if r.get('_pm_gravi_mg')]
    if gravi:
        remarques.append(
            f"Conversion optique des PM2,5 calibrée par la pesée du filtre gravimétrique pour "
            f"la/les phase(s) {', '.join(gravi)} : efficacité de diffusion massique (MSE) "
            f"dérivée spécifiquement pour cette/ces phase(s) — valeur généralement très "
            f"différente de la constante par défaut ({fr(MSE_PM, 1)} m²/g), voir § 3."
        )
    else:
        remarques.append(
            f"Conversion optique des PM2,5 avec une efficacité de diffusion massique fixe de "
            f"{fr(MSE_PM, 1)} m²/g (hypothèse de départ du labo, jamais validée indépendamment) "
            f"— aucun filtre gravimétrique n'a été pesé pour calibrer cette valeur. Les PM2,5 "
            f"de ce rapport doivent être pris avec prudence."
        )
    remarques.append(
        "Calculs vérifiés par comparaison avec le fichier de traitement de référence du "
        "fabricant (écart inférieur à 1 %)."
    )
    obs = ctx.get('observations_operateur', '')
    if obs and obs.strip():
        remarques.append(obs.strip())
    return remarques


# ─────────────────────────────────────────────────────────────────────────
# Construction du PDF — classe de base (polices, en-tête, pied de page)
# ─────────────────────────────────────────────────────────────────────────

class _RapportPDF(FPDF):
    def __init__(self):
        super().__init__(format='A4', unit='mm')
        self.set_margins(MARGE, 14, MARGE)
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()
        self._police_unicode = False
        self._charger_polices()

    def _charger_polices(self):
        regulier = os.path.join(_FONTS_DIR, 'DejaVuSans.ttf')
        gras     = os.path.join(_FONTS_DIR, 'DejaVuSans-Bold.ttf')
        italique = os.path.join(_FONTS_DIR, 'DejaVuSans-Italic.ttf')
        if os.path.exists(regulier) and os.path.exists(gras):
            self.add_font('DejaVu', '', regulier)
            self.add_font('DejaVu', 'B', gras)
            if os.path.exists(italique):
                self.add_font('DejaVu', 'I', italique)
            self.FONT = 'DejaVu'
            self._police_unicode = True
        else:
            self.FONT = 'Helvetica'
        self.set_font(self.FONT, '', 10)

    # ── petits utilitaires de mise en page ─────────────────────────────

    def section_title(self, numero, titre):
        self.ln(2)
        self.set_font(self.FONT, 'B', 11.5)
        self.set_text_color(22, 63, 49)
        self.cell(0, 7, f'{numero}. {titre}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(31, 92, 69)
        self.set_line_width(0.5)
        y = self.get_y() + 0.5
        self.line(MARGE, y, PAGE_W - MARGE, y)
        self.set_text_color(38, 38, 38)
        self.ln(3)

    def kv_table(self, lignes):
        """lignes : liste de (label_g, val_g, label_d, val_d) — 4 colonnes."""
        col = [30, 60, 30, 60]
        label_style = FontFace(family=self.FONT, emphasis='B', size_pt=8.3,
                                color='#1F5C45', fill_color='#F2F4F3')
        value_style = FontFace(family=self.FONT, size_pt=8.8, color='#262626',
                                fill_color='#FFFFFF')
        with self.table(col_widths=col, borders_layout='ALL', line_height=4.6,
                         text_align='LEFT', first_row_as_headings=False,
                         padding=(1.3, 1.6)) as table:
            for lg, vg, ld, vd in lignes:
                row = table.row()
                row.cell(lg, style=label_style)
                row.cell(str(vg), style=value_style)
                row.cell(ld, style=label_style)
                row.cell(str(vd), style=value_style)

    def footer(self):
        self.set_y(-18)
        self.set_draw_color(*self._hex_rgb(GRIS_BORD))
        self.set_line_width(0.2)
        self.line(MARGE, self.get_y(), PAGE_W - MARGE, self.get_y())
        self.ln(1.5)
        self.set_font(self.FONT, '', 7)
        self.set_text_color(130, 130, 130)
        numero = getattr(self, 'numero_rapport_footer', '—')
        foyer  = getattr(self, 'foyer_footer', '—')
        genere = getattr(self, 'genere_footer', '')
        ligne1 = (f"Rapport d'essai n° {numero} · {foyer} · CERER, laboratoire de "
                  f"biomasse-énergie. Les résultats ne concernent que le foyer testé ; "
                  f"reproduction partielle interdite sans accord écrit du CERER.")
        self.set_x(MARGE)
        self.multi_cell(LARGEUR_UTILE - 28, 3.2, ligne1, align='L',
                         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if genere:
            self.set_x(MARGE)
            self.set_font(self.FONT, '', 6.5)
            self.cell(LARGEUR_UTILE - 28, 3.2, genere, align='L')
        self.set_xy(PAGE_W - MARGE - 26, -13)
        self.set_font(self.FONT, '', 7)
        self.cell(26, 4, f'Page {self.page_no()} / {{nb}}', align='R')

    @staticmethod
    def _hex_rgb(hexcode):
        hexcode = hexcode.lstrip('#')
        return tuple(int(hexcode[i:i + 2], 16) for i in (0, 2, 4))


# ─────────────────────────────────────────────────────────────────────────
# Page 1 — Identification + Résultat principal
# ─────────────────────────────────────────────────────────────────────────

def _page_identification_et_resultat(pdf, ctx, analyses, tier_global, test_label,
                                      inclure_resultat_principal=True):
    pdf.add_page()
    pdf.numero_rapport_footer = ctx.get('numero_rapport', '—')
    pdf.foyer_footer = _v(ctx, 'foyer_nom')
    genere_le = ctx.get('genere_le')
    if genere_le:
        pdf.genere_footer = (f"Généré le {genere_le.strftime('%d/%m/%Y à %H:%M')} · "
                              f"LEMS Analyser v{APP_VERSION}")

    # ── Entête : logo CERER (gauche) + texte CERER (centré) + logo UCAD (droite) ──
    y0 = pdf.get_y()
    LARG_LOGO_CERER = 29.0
    LARG_LOGO_UCAD = 21.0
    if os.path.exists(_LOGO_PATH):
        try:
            pdf.image(_LOGO_PATH, x=MARGE, y=y0, w=LARG_LOGO_CERER)
        except Exception:
            pass
    x_ucad = PAGE_W - MARGE - LARG_LOGO_UCAD
    if os.path.exists(_LOGO_UCAD_PATH):
        try:
            pdf.image(_LOGO_UCAD_PATH, x=x_ucad, y=y0, w=LARG_LOGO_UCAD)
        except Exception:
            pass
    x_centre = MARGE + LARG_LOGO_CERER
    larg_centre = x_ucad - x_centre
    pdf.set_xy(x_centre, y0 + 2)
    pdf.set_font(pdf.FONT, 'B', 14)
    pdf.set_text_color(22, 63, 49)
    pdf.multi_cell(larg_centre, 5.3,
                    "Centre d'Études et de Recherches sur les Énergies Renouvelables (CERER)",
                    align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(x_centre, pdf.get_y() + 1)
    pdf.set_font(pdf.FONT, '', 9)
    pdf.set_text_color(89, 89, 89)
    pdf.multi_cell(larg_centre, 4.3,
                    "Laboratoire de biomasse-énergie · Division Bioénergie et Environnement\n"
                    "Université Cheikh Anta Diop de Dakar · Dakar, Sénégal",
                    align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    y_centre_fin = pdf.get_y()

    date_emission = ctx.get('date_emission')
    date_emission_s = date_emission.strftime('%d/%m/%Y') if date_emission else '—'

    pdf.set_y(max(y_centre_fin, y0 + LARG_LOGO_CERER / 1.388, y0 + LARG_LOGO_UCAD) + 2)
    pdf.set_draw_color(31, 92, 69)
    pdf.set_line_width(0.6)
    pdf.line(MARGE, pdf.get_y(), PAGE_W - MARGE, pdf.get_y())
    pdf.ln(3)

    pdf.set_font(pdf.FONT, 'B', 14)
    pdf.set_text_color(22, 63, 49)
    pdf.cell(0, 7.5, "Rapport d'essai de performance d'un foyer de cuisson à biomasse",
              new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(pdf.FONT, '', 9)
    pdf.set_text_color(89, 89, 89)
    pdf.cell(0, 5, 'Protocole Water Boiling Test (WBT) · Norme ISO 19867-1:2018 · '
                    'Classement par Tiers (cibles volontaires, 0 à 5)',
              new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(MARGE)
    pdf.set_font(pdf.FONT, '', 9)
    pdf.set_text_color(38, 38, 38)
    pdf.write(5, "Rapport d'essai n° ")
    pdf.set_font(pdf.FONT, 'B', 9)
    pdf.write(5, ctx.get('numero_rapport', '—'))
    pdf.set_font(pdf.FONT, '', 9)
    pdf.write(5, f"  ·  Date d'émission : {date_emission_s}  ·  Version : 1")
    pdf.ln(6)

    # ── 1. Identification ───────────────────────────────────────────
    pdf.section_title('1', 'IDENTIFICATION')

    nomfn_demandeur = _rejoindre([ctx.get('demandeur_contact_nom'),
                                    ctx.get('demandeur_contact_fonction')], sep=', ', defaut='')
    contact_demandeur = _rejoindre([nomfn_demandeur, ctx.get('demandeur_contact_tel'),
                                      ctx.get('demandeur_contact_courriel')])
    fabricant_modele = _rejoindre([
        ctx.get('foyer_fabricant'),
        _rejoindre([ctx.get('foyer_modele'),
                    f"n° {ctx.get('foyer_numero_serie')}" if ctx.get('foyer_numero_serie') else None],
                   sep=', ', defaut=''),
    ])
    operateur = _rejoindre([ctx.get('operateur_nom'), ctx.get('operateur_fonction')], sep=', ')
    conditions_amb = _rejoindre([
        f"{fr(ctx.get('T_atm'), 1)} °C" if ctx.get('T_atm') is not None else None,
        f"{fr(ctx.get('pression'), 0)} hPa" if ctx.get('pression') is not None else None,
        f"{fr(ctx.get('humidite_relative_pct'), 0)} % HR" if ctx.get('humidite_relative_pct') is not None else None,
    ])
    n_mesures = ctx.get('n_mesures')
    freq_hz = ctx.get('freq_hz')
    fichier_txt = _rejoindre([
        ctx.get('nom_fichier'),
        f"{fr(n_mesures, 0)} mesures" if n_mesures else None,
        f"({fr(freq_hz, 1)} Hz)" if freq_hz else None,
    ])

    lignes = [
        ('Demandeur (entreprise)', _v(ctx, 'demandeur_raison_sociale'),
         'Contact du demandeur', contact_demandeur),
        ('Adresse du demandeur', _v(ctx, 'demandeur_adresse'),
         'Référence de la demande', _v(ctx, 'demandeur_reference')),
        ('Foyer testé', _v(ctx, 'foyer_nom'),
         'Fabricant / modèle', fabricant_modele),
        ('Type de foyer', _v(ctx, 'foyer_type'),
         'Date de réception du foyer', _v(ctx, 'foyer_date_reception')),
        ('Combustible',
         _rejoindre([ctx.get('type_combustible'),
                     f"humidité {fr(ctx.get('humidite_pct'), 1)} %" if ctx.get('humidite_pct') is not None else None]),
         'Pots',
         _rejoindre([f"{int(ctx['nombre_pots'])} pots" if ctx.get('nombre_pots') else None,
                     f"{fr(ctx.get('eau_par_pot_kg'), 1)} kg d'eau par pot" if ctx.get('eau_par_pot_kg') is not None else None])),
        ('Date de l\'essai', fr_date(ctx.get('date_essai_iso')),
         'Heure de début · durée',
         _rejoindre([fr_heure(ctx.get('heure_debut_hms')),
                     f"{fr(ctx.get('duree_totale_min'), 1)} min" if ctx.get('duree_totale_min') is not None else None])),
        ('Lieu de l\'essai', _v(ctx, 'lieu_essai'),
         'Conditions ambiantes', conditions_amb),
        ('Opérateur de l\'essai', operateur if operateur != '—' else _v(ctx, 'operateur_nom'),
         'Traitement des données',
         f"LEMS Analyser v{APP_VERSION} · par {_v(ctx, 'auth_name')}"),
        ('Équipement de mesure',
         _rejoindre(['LEMS (Aprovecho Research Center)',
                     f"n° {ctx.get('equipement_numero_serie')}" if ctx.get('equipement_numero_serie') else None]),
         'Dernière calibration', _v(ctx, 'derniere_calibration')),
        ('Fichier de données', fichier_txt,
         'Répétition', f"Test {ctx.get('test_n', '?')} sur {ctx.get('nb_tests', '?')} de la série"),
    ]
    pdf.kv_table(lignes)
    pdf.ln(3)

    if not inclure_resultat_principal:
        return

    # ── 2. Résultat principal ───────────────────────────────────────
    pdf.section_title('2', 'RÉSULTAT PRINCIPAL')

    y_badge = pdf.get_y()
    cx, cy, d = MARGE + 13, y_badge + 13, 24
    coul = TIER_COUL.get(tier_global, '#555555')
    pdf.set_draw_color(*pdf._hex_rgb(coul))
    pdf.set_fill_color(*pdf._hex_rgb('#FFFFFF'))
    pdf.set_line_width(1.1)
    pdf.ellipse(cx - d / 2, cy - d / 2, d, d, style='D')
    pdf.set_xy(cx - d / 2, cy - d / 2 - 6)
    pdf.set_font(pdf.FONT, '', 7.2)
    pdf.set_text_color(89, 89, 89)
    pdf.cell(d, 4, 'Tier global', align='C')
    pdf.set_xy(cx - d / 2, cy - 6)
    pdf.set_font(pdf.FONT, 'B', 18)
    pdf.set_text_color(*pdf._hex_rgb(coul))
    pdf.cell(d, 12, str(tier_global), align='C')

    x_txt = MARGE + 30
    pdf.set_xy(x_txt, y_badge + 2)
    pdf.set_font(pdf.FONT, 'B', 12.5)
    pdf.set_text_color(*pdf._hex_rgb(coul))
    pdf.cell(LARGEUR_UTILE - 30, 6.5, f'Tier {tier_global} — {TIER_LABEL.get(tier_global, "")}',
              new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(x_txt)
    pdf.set_font(pdf.FONT, '', 9)
    pdf.set_text_color(38, 38, 38)
    pdf.multi_cell(LARGEUR_UTILE - 30, 4.3, _phrase_resultat_principal(analyses, tier_global),
                    new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(max(pdf.get_y(), y_badge + d + 4) + 4)

    phases_ordre = [c for c in ('HP', 'MP', 'BP') if c in analyses]
    n = len(phases_ordre)
    marge_boite = 4
    largeur_boite = (LARGEUR_UTILE - marge_boite * (n - 1)) / n if n else LARGEUR_UTILE
    y_box = pdf.get_y()
    h_box = 20
    for i, code in enumerate(phases_ordre):
        a = analyses[code]
        x = MARGE + i * (largeur_boite + marge_boite)
        coul_p = COUL_PHASE.get(code, '#555555')
        pdf.set_fill_color(*pdf._hex_rgb(coul_p))
        pdf.rect(x, y_box, largeur_boite, 1.1, style='F')
        pdf.set_draw_color(*pdf._hex_rgb(GRIS_BORD))
        pdf.set_line_width(0.3)
        pdf.rect(x, y_box + 1.1, largeur_boite, h_box - 1.1, style='D')
        pdf.set_xy(x + 2, y_box + 3)
        pdf.set_font(pdf.FONT, 'B', 9)
        pdf.set_text_color(*pdf._hex_rgb(coul_p))
        pdf.cell(largeur_boite - 4, 4.5, f"{code} · {a['label']}")
        pdf.set_xy(x + 2, y_box + 9.5)
        pdf.set_font(pdf.FONT, '', 8.3)
        pdf.set_text_color(38, 38, 38)
        pdf.multi_cell(largeur_boite - 4, 3.9, f"Tier {a['t_iwa11']} · {_limite_par(a)}")
    pdf.set_y(y_box + h_box)


# ─────────────────────────────────────────────────────────────────────────
# Page 2 — Résultats par phase + Seuils + Interprétation
# ─────────────────────────────────────────────────────────────────────────

def _page_resultats_phases(pdf, ctx, analyses, resultats, tier_global):
    pdf.add_page()

    pdf.section_title('3', 'RÉSULTATS PAR PHASE')
    phases_ordre = [c for c in ('HP', 'MP', 'BP') if c in analyses]
    larg_metrique, larg_unite = 75, 19
    reste = LARGEUR_UTILE - larg_metrique - larg_unite
    col_w = [larg_metrique, larg_unite] + [reste / len(phases_ordre)] * len(phases_ordre)

    entete_style = FontFace(family=pdf.FONT, emphasis='B', size_pt=8,
                             color='#FFFFFF', fill_color='#163F31')
    normal_style = FontFace(family=pdf.FONT, size_pt=7.8, color='#262626')
    gras_style   = FontFace(family=pdf.FONT, emphasis='B', size_pt=7.8,
                             color='#262626', fill_color='#F2F4F3')

    def _ligne(table, metrique, unite, valeurs, style=normal_style):
        row = table.row()
        row.cell(metrique, style=style)
        row.cell(unite, style=style)
        for v in valeurs:
            row.cell(v, style=style)

    with pdf.table(col_widths=col_w, borders_layout='ALL', line_height=4.2,
                    text_align='LEFT', first_row_as_headings=True,
                    headings_style=entete_style, padding=(1.0, 1.4)) as table:
        row = table.row()
        row.cell('Métrique', style=entete_style)
        row.cell('Unité', style=entete_style)
        for code in phases_ordre:
            row.cell(code, style=entete_style)

        _ligne(table, 'Durée de la phase', 'min',
               [fr(resultats[c]['duree_min'], 1) for c in phases_ordre])
        _ligne(table, 'Combustible sec brûlé', 'g',
               [fr(resultats[c]['thermique']['bois_brule_sec_kg'] * 1000, 0) for c in phases_ordre])
        _ligne(table, 'Efficacité thermique, sans charbon résiduel', '%',
               [fr(analyses[c]['eff_sc'], 1) for c in phases_ordre])
        _ligne(table, 'Efficacité thermique, avec charbon résiduel', '%',
               [fr(analyses[c]['eff'], 1) for c in phases_ordre])
        _ligne(table, 'Tier Efficacité thermique', '0 à 5',
               [str(analyses[c]['t_eff']) for c in phases_ordre])
        _ligne(table, 'Puissance de cuisson', 'W',
               [fr(analyses[c]['puissance_cuis_W'], 0) for c in phases_ordre])
        _ligne(table, 'Taux de combustion', 'g/min',
               [fr(analyses[c]['taux_comb'], 2) for c in phases_ordre])
        _ligne(table, 'Efficacité de combustion modifiée (MCE)', '%',
               [fr(analyses[c]['mce'], 1) for c in phases_ordre])
        _ligne(table, 'CO émis (total)', 'g',
               [fr(analyses[c]['co_total_g'], 3) for c in phases_ordre])
        _ligne(table, 'CO par énergie utile délivrée', 'g/MJd',
               [fr(analyses[c]['co_mjd'], 2) for c in phases_ordre])
        pm_nul = any(round(analyses[c]['pm_mjd'], 1) == 0.0 for c in phases_ordre)
        _ligne(table, 'PM2,5 par énergie utile délivrée' + (' *' if pm_nul else ''), 'mg/MJd',
               [fr(analyses[c]['pm_mjd'], 1) for c in phases_ordre])
        _ligne(table, 'Tier CO · Tier PM2,5', '0 à 5',
               [f"{analyses[c]['t_co_mjd']} · {analyses[c]['t_pm_mjd']}" for c in phases_ordre])
        _ligne(table, 'Tier de la phase (le plus faible des deux)', '0 à 5',
               [str(analyses[c]['t_iwa11']) for c in phases_ordre], style=gras_style)

    if any(round(analyses[c]['pm_mjd'], 1) == 0.0 for c in phases_ordre):
        pdf.set_font(pdf.FONT, '', 7.3)
        pdf.set_text_color(89, 89, 89)
        pdf.multi_cell(LARGEUR_UTILE, 3.3,
                        '* Valeur nulle après soustraction du bruit de fond : à confirmer par '
                        'la pesée du filtre gravimétrique (voir § 7).',
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # ── 4. Seuils de classement utilisés ────────────────────────────
    pdf.section_title('4', 'SEUILS DE CLASSEMENT UTILISÉS')
    col2 = [16, 60, 52, 52]
    entete2 = FontFace(family=pdf.FONT, emphasis='B', size_pt=8.2, color='#FFFFFF', fill_color='#163F31')
    normal2 = FontFace(family=pdf.FONT, size_pt=8.2, color='#262626')
    surlign = FontFace(family=pdf.FONT, emphasis='B', size_pt=8.2, color='#262626', fill_color=AMBRE_FOND)
    with pdf.table(col_widths=col2, borders_layout='ALL', line_height=4.4,
                    text_align='CENTER', first_row_as_headings=True,
                    headings_style=entete2, padding=(0.9, 1.4)) as table:
        row = table.row()
        row.cell('Tier', style=entete2)
        row.cell('Niveau', style=entete2, align='LEFT')
        row.cell('CO (g/MJd)', style=entete2)
        row.cell('PM2,5 (mg/MJd)', style=entete2)
        for t in (5, 4, 3, 2, 1, 0):
            niveau = SEUILS_NIVEAU[t]
            est_global = (t == tier_global)
            if est_global:
                niveau += ' (résultat global)'
            style = surlign if est_global else normal2
            if t == 0:
                co_txt = f"≥ {fr(SEUILS_CO_G_MJD[1], 1)}"
                pm_txt = f"≥ {fr(SEUILS_PM_MG_MJD[1], 0)}"
            else:
                co_txt = f"< {fr(SEUILS_CO_G_MJD[t], 1)}"
                pm_txt = f"< {fr(SEUILS_PM_MG_MJD[t], 0)}"
            row = table.row()
            row.cell(str(t), style=style)
            row.cell(niveau, style=style, align='LEFT')
            row.cell(co_txt, style=style)
            row.cell(pm_txt, style=style)
    pdf.set_font(pdf.FONT, '', 7.3)
    pdf.set_text_color(89, 89, 89)
    pdf.multi_cell(LARGEUR_UTILE, 3.3,
                    "Émissions normalisées par l'énergie utile délivrée au pot (MJd), selon les "
                    "cibles volontaires de performance de la série ISO 19867. Un foyer atteint un "
                    "Tier si le CO ET les PM2,5 sont sous les deux seuils.",
                    new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # ── 5. Interprétation ───────────────────────────────────────────
    pdf.section_title('5', 'INTERPRÉTATION')
    for code in phases_ordre:
        a = analyses[code]
        limitante = a['t_iwa11'] == tier_global and len(phases_ordre) > 1
        pdf.set_font(pdf.FONT, 'B', 8.6)
        pdf.set_text_color(38, 38, 38)
        entete_phrase = (f"{PHASE_NOM.get(code, code)} ({code}). Tier {a['t_iwa11']}"
                          f"{', phase limitante.' if limitante else '.'} ")
        pdf.write(4.1, entete_phrase)
        pdf.set_font(pdf.FONT, '', 8.6)
        pdf.write(4.1, _phrase_interpretation_phase(a))
        pdf.ln(4.1)
        pdf.set_x(MARGE)
        pdf.set_font(pdf.FONT, '', 8.6)
        pdf.multi_cell(LARGEUR_UTILE, 4.0, _phrase_performance_phase(a, analyses),
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)


# ─────────────────────────────────────────────────────────────────────────
# Page 3 — Recommandations, Remarques, Validation
# ─────────────────────────────────────────────────────────────────────────

_CATEGORIES_RENOMMEES = {
    'Émissions CO': 'Monoxyde de carbone',
    'Émissions PM₂.₅': 'Particules fines',
    'Efficacité thermique': 'Efficacité thermique',
    'Qualité de combustion (MCE)': 'Qualité de combustion',
    'Validation statistique': 'Validation statistique',
}


def _page_recommandations(pdf, ctx, analyses, resultats, est_serie,
                           inclure_recommandations=True, num_remarques='7', num_validation='8'):
    pdf.add_page()

    if inclure_recommandations:
        pdf.section_title('6', 'RECOMMANDATIONS')
        pdf.set_font(pdf.FONT, '', 9)
        for cat, texte in generer_recommandations(analyses):
            cat_propre = _strip_emoji(cat)
            cat_propre = _CATEGORIES_RENOMMEES.get(cat_propre, cat_propre)
            pdf.set_x(MARGE)
            pdf.set_font(pdf.FONT, 'B', 9)
            pdf.write(4.6, f'{cat_propre}. ')
            pdf.set_font(pdf.FONT, '', 9)
            pdf.write(4.6, texte)
            pdf.ln(5.8)
        pdf.ln(2)

    pdf.section_title(num_remarques, 'REMARQUES ET LIMITES')
    pdf.set_font(pdf.FONT, '', 9)
    for remarque in _texte_remarques(ctx, resultats, est_serie):
        pdf.set_x(MARGE)
        pdf.cell(4, 4.4, '•')
        pdf.multi_cell(LARGEUR_UTILE - 4, 4.4, remarque, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)
    pdf.ln(2)

    pdf.section_title(num_validation, 'VALIDATION')
    cases = [
        ("Opérateur de l'essai", _rejoindre([ctx.get('operateur_nom'), ctx.get('operateur_fonction')], sep=', ')),
        ('Vérifié par', _rejoindre([ctx.get('verificateur_nom'), ctx.get('verificateur_fonction')], sep=', ')),
        ('Approuvé par', _rejoindre([ctx.get('approbateur_nom'), ctx.get('approbateur_fonction')], sep=', ')),
    ]
    marge_boite = 4
    largeur_boite = (LARGEUR_UTILE - marge_boite * 2) / 3
    y0 = pdf.get_y()
    h = 28
    for i, (titre, nom) in enumerate(cases):
        x = MARGE + i * (largeur_boite + marge_boite)
        pdf.set_draw_color(*pdf._hex_rgb(GRIS_BORD))
        pdf.set_line_width(0.3)
        pdf.rect(x, y0, largeur_boite, h, style='D')
        pdf.set_xy(x + 2, y0 + 2)
        pdf.set_font(pdf.FONT, 'B', 8.7)
        pdf.set_text_color(38, 38, 38)
        pdf.cell(largeur_boite - 4, 4, titre)
        pdf.set_fill_color(*pdf._hex_rgb(AMBRE_FOND))
        pdf.set_xy(x + 2, y0 + 8)
        pdf.set_font(pdf.FONT, '', 8.5)
        pdf.cell(largeur_boite - 4, 5, nom if nom != '—' else '', fill=True)
        pdf.set_draw_color(*pdf._hex_rgb('#999999'))
        pdf.line(x + 2, y0 + h - 7, x + largeur_boite - 2, y0 + h - 7)
        pdf.set_xy(x + 2, y0 + h - 6)
        pdf.set_font(pdf.FONT, '', 7.2)
        pdf.set_text_color(130, 130, 130)
        sous_titre = 'Date, signature et cachet' if i == 2 else 'Date et signature'
        pdf.cell(largeur_boite - 4, 3.6, sous_titre)
    pdf.set_y(y0 + h)


# ─────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────

def generer_rapport_test(analyses, resultats, ctx):
    """Rapport d'un test individuel (3 pages). `ctx` : voir app.py (fonction
    _construire_contexte_rapport) pour la liste complète des champs."""
    tier_global = min(a['t_iwa11'] for a in analyses.values())
    pdf = _RapportPDF()
    _page_identification_et_resultat(pdf, ctx, analyses, tier_global, None)
    _page_resultats_phases(pdf, ctx, analyses, resultats, tier_global)
    _page_recommandations(pdf, ctx, analyses, resultats, est_serie=False)
    return bytes(pdf.output())


def generer_rapport_serie(ctx, tests_accumules, dernier_analyses, dernier_resultats):
    """Rapport de fin de série : identification du foyer + UNIQUEMENT le
    tableau récapitulatif de tous les tests de la série (Moyenne/ET/IC90%
    par phase et combiné, format ISO 19867-1) — pas le détail d'un test
    individuel pris isolément (chaque test a déjà son propre rapport
    téléchargeable séparément ; répéter son détail ici n'apportait rien
    et entretenait la confusion entre "ce test" et "la série")."""
    tier_global = min(a['t_iwa11'] for a in dernier_analyses.values())
    ctx = dict(ctx)
    ctx['nb_tests_enregistres'] = len(tests_accumules)
    pdf = _RapportPDF()
    _page_identification_et_resultat(pdf, ctx, dernier_analyses, tier_global, None,
                                      inclure_resultat_principal=False)

    # ── 2. Statistiques de série (format ISO 19867-1) ───────────────
    pdf.add_page()
    pdf.section_title('2', 'STATISTIQUES DE LA SÉRIE')
    pdf.set_font(pdf.FONT, '', 9)
    n_tests = len(tests_accumules)
    pdf.multi_cell(LARGEUR_UTILE, 4.4,
                    f"{n_tests} test(s) enregistré(s) pour le foyer {_v(ctx, 'foyer_nom')}. "
                    f"Moyenne, écart-type et intervalle de confiance à 90% (loi de Student, "
                    f"méthode statistique standard — aucune formule officielle du labo "
                    f"n'est documentée pour ce calcul, à confirmer si besoin) par phase et "
                    f"combiné (pondération égale HP/MP/BP). Performance/Tier calculé sur la "
                    f"borne défavorable de l'IC 90% (borne basse pour l'efficacité, borne "
                    f"haute pour CO/PM2,5) plutôt que sur la moyenne — approche conservatrice.",
                    new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    def _valeurs(champ):
        """Pour un champ donné, retourne ({'HP':[...],'MP':[...],'BP':[...],'Combine':[...]})."""
        out = {'HP': [], 'MP': [], 'BP': [], 'Combine': []}
        for t in tests_accumules:
            phases = t.get('phases', {})
            par_phase = {}
            for c in ('HP', 'MP', 'BP'):
                v = phases.get(c, {}).get(champ)
                if v is not None:
                    out[c].append(v)
                    par_phase[c] = v
            comb = _combine_egal(par_phase)
            if comb is not None:
                out['Combine'].append(comb)
        return out

    def _fmt_cell(vals, decimales):
        if not vals:
            return ('—', '—', '—')
        moyenne, sd, lo, hi = _mean_sd_ci90(vals)
        ci_txt = fr(lo, decimales) + '-' + fr(hi, decimales) if len(vals) > 1 else '—'
        return (fr(moyenne, decimales), fr(sd, decimales), ci_txt)

    def _tier_eff_consv(vals):
        if not vals:
            return None
        _, _, lo, _ = _mean_sd_ci90(vals)
        return _tier_eff(lo)

    def _tier_mjd_consv(vals, seuils):
        if not vals:
            return None
        _, _, _, hi = _mean_sd_ci90(vals)
        return _tier_inferieur(hi, seuils)

    # (libellé, champ, décimales, calc_tier, affiche_IC90%)
    # Structure calquée exactement sur le tableau-type du labo (Capt.PNG) :
    # seules Efficacité (x2)/PM2,5/CO ont une ligne IC 90% — Productivité du
    # charbon, Puissance de cuisson et Taux de combustion n'ont que Moy./ET.
    lignes = [
        ('Efficacité thermique sans charbon résiduel (%)', 'eff_sc', 1,
         lambda v: _tier_eff_consv(v['Combine']), True),
        ('Efficacité thermique avec charbon résiduel (%)', 'eff', 1,
         lambda v: _tier_eff_consv(v['Combine']), True),
        ('Productivité énergétique du charbon (%)', None, 1, lambda v: None, False),
        ('Productivité massique du charbon (%)', None, 1, lambda v: None, False),
        ('Puissance de cuisson (kW)', 'puissance_cuisson_W_kw', 2, lambda v: None, False),
        ('Taux de combustion (g/min)', 'taux_combustion_g_min', 1, lambda v: None, False),
        ('PM2,5 par énergie utile (mg/MJd)', 'pm_mjd', 1,
         lambda v: _tier_mjd_consv(v['Combine'], SEUILS_PM_MG_MJD), True),
        ('CO par énergie utile (g/MJd)', 'co_mjd', 2,
         lambda v: _tier_mjd_consv(v['Combine'], SEUILS_CO_G_MJD), True),
    ]

    col_w = [32, 14, 26, 26, 26, 28, 28]
    entete = FontFace(family=pdf.FONT, emphasis='B', size_pt=7.5, color='#FFFFFF', fill_color='#163F31')
    normal = FontFace(family=pdf.FONT, size_pt=7.5, color='#262626')
    gras   = FontFace(family=pdf.FONT, emphasis='B', size_pt=7.5, color='#262626')
    with pdf.table(col_widths=col_w, borders_layout='ALL', line_height=4.6,
                    text_align='CENTER', first_row_as_headings=True,
                    headings_style=entete, padding=(1.0, 1.2)) as table:
        row = table.row()
        for h in ('Métrique', '', 'Haute', 'Moyenne', 'Basse', 'Combiné', 'Performance (Tier)'):
            row.cell(h, style=entete)

        for libelle, champ, dec, calc_tier, avec_ci in lignes:
            if champ is None:
                # Métrique non calculée par l'app (productivité charbon) :
                # affichée "n.d." plutôt qu'une valeur inventée. 2 lignes
                # (Moy./ET) seulement, comme dans le tableau-type du labo.
                # "Métrique" et "Performance" fusionnées verticalement
                # (rowspan=2) sur les 2 lignes, comme dans Capt.PNG — pas
                # des cellules vides répétées.
                row = table.row()
                row.cell(libelle, style=gras, rowspan=2)
                row.cell('Moy.', style=normal)
                for _ in range(4):
                    row.cell('n.d.', style=normal)
                row.cell('n.d.', style=normal, rowspan=2)
                row = table.row()
                row.cell('ET', style=normal)
                for _ in range(4):
                    row.cell('n.d.', style=normal)
                continue

            if champ == 'puissance_cuisson_W_kw':
                donnees = _valeurs('puissance_cuisson_W')
                for k in donnees:
                    donnees[k] = [v / 1000.0 for v in donnees[k]]
            else:
                donnees = _valeurs(champ)

            tier = calc_tier(donnees)
            perf_txt = str(tier) if tier is not None else 'n.d.'

            moy = {c: _fmt_cell(donnees[c], dec) for c in ('HP', 'MP', 'BP', 'Combine')}
            n_eff = len(donnees['Combine'])
            n_lignes = 3 if (avec_ci and n_eff > 1) else 2

            # "Métrique" et "Performance" fusionnées verticalement (rowspan)
            # sur les n_lignes (2 ou 3) de ce bloc, comme dans Capt.PNG.
            row = table.row()
            row.cell(libelle, style=gras, rowspan=n_lignes)
            row.cell('Moy.', style=normal)
            for c in ('HP', 'MP', 'BP', 'Combine'):
                row.cell(moy[c][0], style=(gras if c == 'Combine' else normal))
            row.cell(perf_txt, style=gras, rowspan=n_lignes)

            row = table.row()
            row.cell('ET', style=normal)
            for c in ('HP', 'MP', 'BP', 'Combine'):
                row.cell(moy[c][1], style=normal)

            if n_lignes == 3:
                row = table.row()
                row.cell('IC 90%', style=normal)
                for c in ('HP', 'MP', 'BP', 'Combine'):
                    row.cell(moy[c][2], style=normal)

        # Sécurité : une seule ligne "Score", valeur unique (pas de ventilation
        # par phase), exactement comme dans le tableau-type du labo.
        row = table.row()
        row.cell('Sécurité', style=gras)
        row.cell('Score', style=normal)
        row.cell('n.d.', style=normal, colspan=4)
        row.cell('n.d.', style=normal)

    pdf.ln(2)
    pdf.set_font(pdf.FONT, 'I', 7.5)
    pdf.set_text_color(*pdf._hex_rgb(GRIS_CLAIR))
    pdf.multi_cell(LARGEUR_UTILE, 3.6,
                    "Productivité du charbon et score de Sécurité : non calculés par "
                    "l'application (méthode non implémentée) — « n.d. » plutôt qu'une "
                    "valeur approximative.",
                    new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*pdf._hex_rgb(GRIS_TEXTE))

    # ── 3. Remarques et limites · 4. Validation ──────────────────────
    # Pas de § 6 Recommandations ici : ces recommandations sont dérivées
    # de l'analyse d'UN test précis (le dernier) et n'ont pas leur place
    # dans un rapport qui résume la série entière — chaque test a déjà
    # ses propres recommandations dans son rapport individuel.
    _page_recommandations(pdf, ctx, dernier_analyses, dernier_resultats, est_serie=True,
                           inclure_recommandations=False, num_remarques='3', num_validation='4')

    pdf.numero_rapport_footer = ctx.get('numero_rapport', '—')
    pdf.foyer_footer = _v(ctx, 'foyer_nom')
    return bytes(pdf.output())
