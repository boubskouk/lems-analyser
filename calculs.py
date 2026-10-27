#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module 2 : Calculs ISO 19867 — LEMS Analyser
Sources des constantes : T1.xlsx (Aprovecho PEMS) + ISO 19867-1
"""

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# Constantes physiques (chimie fondamentale / NIST)
# ─────────────────────────────────────────────────────────────────────
MW_CO        = 28.01    # g/mol
MW_CO2       = 44.01    # g/mol
Vm_STP       = 22.4     # L/mol  (0 °C, 1 atm)
K_CO         = MW_CO  / Vm_STP   # ≈ 1.2504 mg·m⁻³/ppm
K_CO2        = MW_CO2 / Vm_STP   # ≈ 1.9647 mg·m⁻³/ppm
CP_EAU       = 4.186    # kJ/(kg·°C)
R_AIR        = 287.05   # J/(kg·K)  constante gaz air sec (non utilisé dans formule T1.xlsx)

# ─────────────────────────────────────────────────────────────────────
# Constantes tunnel LEMS — source : T1.xlsx, feuilles "Assumptions and QC"
#                                     et "Emissions Import" (flowslope / intercept)
# ─────────────────────────────────────────────────────────────────────
# Conversion logunits Flow → ΔP (inH₂O) :
#   ΔP = (Flow_logunits − zéro_flux) × K_FLOW_INH2O
# Zéro flux ≈ 9 900 logunits (fan éteint, début du CSV)
# 13 594 logunits → 0,40 inH₂O ⇒ K = 0,40/(13594−9900) = 1,083e-4
K_FLOW_INH2O  = 1.083e-4   # inH₂O/logunit (T1.xlsx flowslope ≈ 1,100e-4)

# Constante débit massique (T1.xlsx formule Logger Data col I) :
#   ṁ (g/s) = PITOT_MASS × sqrt(ΔP_inH₂O × p_Pa / T_tube_K)
# Dérivée de : PITOT_CAL×VEL_FACTOR×STACK_AREA×√(2×249.089×8.314/29) × 1000
# T1.xlsx utilise 15.3 ; notre dérivation donne ≈15.7 (même ordre)
PITOT_MASS    = 15.3        # constante empirique T1.xlsx

# ─────────────────────────────────────────────────────────────────────
# Combustibles — source : T1.xlsx, feuille "Calorific Values"
# Format : (PCI kJ/kg,  fraction carbone)
# ─────────────────────────────────────────────────────────────────────
COMBUSTIBLES = {
    'Bois dur moyen'      : (17829.0, 0.50),  # ISO standard (source: T1.xlsx Results row 74)
    'Bois tendre moyen'   : (20817.0, 0.50),
    'Charbon de bois'     : (28200.0, 0.78),  # PCI NET (Net CV) — pas le PCI brut (Gross CV=29400)
    'LPG'                 : (48000.0, 0.82),
    'Kérosène'            : (43300.0, 0.86),
    'Charbon minéral'     : (24700.0, 0.75),
    'Résidus agricoles'   : (14700.0, 0.45),
    'Bouse de vache (sec)': (13600.0, 0.38),
    'Éthanol'             : (26800.0, 0.52),
}

PCI_DEFAUT       = 17829.0
FRAC_C_DEFAUT    = 0.50
HHV_CHARBON      = 29490.0   # kJ/kg  PCI charbon résiduel (T1.xlsx)

# Combustibles pour lesquels le résidu en fin de phase est du CHARBON produit par
# combustion incomplète du combustible initial (donc une 2e forme d'efficacité,
# "avec résidu charbonneux", a un sens physique : on crédite l'énergie du charbon
# non brûlé). Pour les autres combustibles (charbon de bois lui-même, GPL, kérosène,
# charbon minéral, éthanol...), le résidu pesé est juste du combustible non brûlé de
# même nature que celui chargé — il n'y a qu'une seule efficacité pertinente.
# Remarque labo CERER (15/10/2026) : limiter aux deux bois.
FUELS_AVEC_RESIDU_CHARBONNEUX = {'Bois dur moyen', 'Bois tendre moyen'}

# Conversion PM scattering → concentration massique :
# cal_pm (ligne #0 CSV) est un facteur scattering [1/Mm / logunit].
# PM_ug/m³ = PM_scat_zeroed (1/Mm) / (MSE × 1e-3)
# MSE = 3 m²/g  ← T1.xlsx Assumptions L6 ; donne facteur 0.003
# ATTENTION (2026-10-16) : T1.xlsx ne se contente PAS de ce facteur fixe pour son
# résultat final — il dérive une MSE propre à chaque phase à partir du filtre
# gravimétrique pesé (ISO!M39 net filter mass / débit supposé 17,397 LPM, comparé au
# coefficient de diffusion moyen de la phase), puis l'applique à la trace optique
# seconde par seconde (Logger Data col R). Cette MSE dérivée varie de 0,0026 à 0,033
# m²/g sur un seul test (foyer Kevin) — un facteur fixe unique ne peut PAS reproduire
# T1.xlsx sans données de filtre gravimétrique propres à chaque test. Voir le point 5
# de LEMS-Analyser-Questions-maitre-de-stage.docx.
MSE_PM            = 3.0        # Mass Scattering Efficiency (m²/g) — T1.xlsx Assumptions L6
_MSE_FACTOR       = MSE_PM * 1e-3  # facteur effectif pour 1/Mm → ug/m³

# ─────────────────────────────────────────────────────────────────────
# Tier ISO 19867-1:2018 Tableau 1 (Objectifs de performances volontaires)
# →  (CO_max g/MJd, PM_max mg/MJd) — confirmé le 2026-10-16 contre le texte
# officiel de la norme (photo fournie par l'utilisateur). Remplace les anciens
# seuils en g/min dont l'origine n'était pas confirmée.
# ─────────────────────────────────────────────────────────────────────
SEUILS_TIER = {
    5: (3.0,   5.0),
    4: (4.4,   62.0),
    3: (7.2,   218.0),
    2: (11.5,  481.0),
    1: (18.3, 1030.0),
}
LABEL_TIER = {
    5: 'Excellent+ (Tier 5)',
    4: 'Excellent (Tier 4)',
    3: 'Bon (Tier 3)',
    2: 'Intermédiaire (Tier 2)',
    1: 'Basique (Tier 1)',
    0: 'Hors normes (Tier 0)',
}

COLONNES_CAPTEURS = ['CO', 'GasTemp', 'PM', 'Flow', 'FlueTemp', 'TC', 'CO2', 'PM_RH']


# ═════════════════════════════════════════════════════════════════════
# 1. Calibration
# ═════════════════════════════════════════════════════════════════════

def appliquer_calibration(df_brut: pd.DataFrame, calibration: list) -> pd.DataFrame:
    df = df_brut.copy()
    for i, col in enumerate(COLONNES_CAPTEURS):
        if i < len(calibration) and calibration[i] != 0.0:
            df[col] = df_brut[col] * calibration[i]
    return df


# ═════════════════════════════════════════════════════════════════════
# 2. Débit tunnel (Bernoulli + corrections Pitot)
# ═════════════════════════════════════════════════════════════════════

def calculer_debit_tunnel(flow_series: pd.Series,
                          flue_temp_series: pd.Series,
                          baseline_flow: float,
                          p_Pa: float = 101325.0) -> pd.Series:
    """
    Débit volumique tunnel (m³/min) selon la formule T1.xlsx Logger Data col J.

    Formule (T1.xlsx, feuille Logger Data) :
        ΔP (inH₂O) = max(0, (logunits − zéro_flux) × K_FLOW_INH2O)
        ṁ (g/s)    = PITOT_MASS × √(ΔP × p_Pa / T_K)
        ρ (g/m³)   = 29 × p_Pa / (8,314 × T_K)
        Q (m³/hr)  = ṁ × 3600 / ρ
        Q (m³/min) = Q / 60

    baseline_flow : logunits Flow quand le ventilateur est éteint (≈ 9 900)
    flue_temp_series : température du tunnel (°C) — colonne FlueTemp calibrée
    """
    delta_P = ((flow_series - baseline_flow) * K_FLOW_INH2O).clip(lower=0)
    T_K     = flue_temp_series + 273.15
    mask    = delta_P > 0

    mass_g_s  = pd.Series(0.0, index=flow_series.index)
    rho_g_m3  = 29.0 * p_Pa / (8.314 * T_K)
    mass_g_s[mask] = PITOT_MASS * np.sqrt(delta_P[mask] * p_Pa / T_K[mask])

    vol_m3_hr = pd.Series(0.0, index=flow_series.index)
    vol_m3_hr[mask] = mass_g_s[mask] * 3600.0 / rho_g_m3[mask]

    return vol_m3_hr / 60.0   # m³/min


# ═════════════════════════════════════════════════════════════════════
# 3. Taux d'émission instantanés
# ═════════════════════════════════════════════════════════════════════

def calculer_taux_emission(df_cal: pd.DataFrame,
                           baseline_flow: float = None,
                           T_atm: float = 25.0,
                           bg_pm_ug: float = 0.0,
                           bg_co_ppm: float = 0.0,
                           bg_co2_ppm: float = 0.0,
                           p_Pa: float = 101325.0) -> pd.DataFrame:
    """
    Calcule les taux d'émission instantanés de CO, PM et CO₂.

    baseline_flow : logunits Flow quand le ventilateur est éteint (≈ 9 900).
                    ≠ flow moyen pendant la période de fond (≈ 13 600).
    bg_pm_ug   : PM de fond calibré (μg/m³) — soustrait.
    bg_co_ppm  : CO de fond calibré (ppm) — soustrait.
    bg_co2_ppm : CO₂ de fond (ppm) — soustrait. T1.xlsx col 40 "Zeroed CO2".
                 Valeur typique ≈ 615 ppm (ambiante avant allumage).
    p_Pa       : pression atmosphérique (Pa).
    """
    df = df_cal.copy()

    if baseline_flow is None:
        baseline_flow = df['Flow'].iloc[:20].mean()

    # FlueTemp (calibré) est la température du tunnel, utilisée dans la formule de débit
    flue_temp_C = df['FlueTemp'].copy()
    flue_temp_C = flue_temp_C.where(flue_temp_C > 0, T_atm)   # fallback si FlueTemp invalide

    debit_m3_min = calculer_debit_tunnel(df['Flow'], flue_temp_C, baseline_flow, p_Pa)
    df['debit_m3_min'] = debit_m3_min

    # PM pipeline 2 étapes (T1.xlsx Assumptions L6) :
    #   df['PM'] est en 1/Mm après appliquer_calibration (cal_pm = facteur scattering).
    #   bg_pm_ug est aussi en 1/Mm (bg_PM_log × cal_pm dans app.py).
    #   Étape 2 : PM_scat_zeroed (1/Mm) → PM_ug/m³ via MSE = 3 m²/g
    df['PM_ug_zeroed'] = (df['PM'] - bg_pm_ug).clip(lower=0) / _MSE_FACTOR
    df['PM_mg_m3']     = df['PM_ug_zeroed'] / 1000.0

    # Correction température : T1.xlsx utilise le débit molaire à la température réelle
    # du tunnel (FlueTemp), non le volume molaire STP (22,4 L à 0°C).
    T_tube_K = flue_temp_C + 273.15

    # CO : soustraction du fond ; valeurs négatives non écrêtées ici (réduisent le total)
    df['CO_ppm_zeroed'] = df['CO'] - bg_co_ppm
    df['CO_mg_m3']      = df['CO_ppm_zeroed'] * K_CO * (273.15 / T_tube_K)

    # CO₂ : soustraction du fond ambiant (T1.xlsx "Zeroed CO2"), borné à 0
    # T1.xlsx col 40 = CO2 - background_CO2 (≈615 ppm).  Intégration sur excès uniquement.
    df['CO2_ppm_zeroed'] = (df['CO2'] - bg_co2_ppm).clip(lower=0)
    df['CO2_mg_m3']      = df['CO2_ppm_zeroed'] * K_CO2 * (273.15 / T_tube_K)

    # Taux (mg/min) = concentration × débit
    df['CO_taux_mg_min']  = df['CO_mg_m3']  * debit_m3_min
    df['PM_taux_mg_min']  = df['PM_mg_m3']  * debit_m3_min
    df['CO2_taux_mg_min'] = df['CO2_mg_m3'] * debit_m3_min

    return df


# ═════════════════════════════════════════════════════════════════════
# 4. Intégration temporelle → émissions totales
# ═════════════════════════════════════════════════════════════════════

def integrer_emissions(df: pd.DataFrame) -> dict:
    dt_s   = df['seconds'].diff().fillna(2.0)
    dt_min = dt_s / 60.0

    co_mg  = (df['CO_taux_mg_min']  * dt_min).sum()
    pm_mg  = (df['PM_taux_mg_min']  * dt_min).sum()
    co2_mg = (df['CO2_taux_mg_min'] * dt_min).sum()

    return {
        'CO_total_mg'  : co_mg,
        'CO_total_g'   : co_mg  / 1000,
        'PM_total_mg'  : pm_mg,
        'PM_total_g'   : pm_mg  / 1000,
        'CO2_total_mg' : co2_mg,
        'CO2_total_g'  : co2_mg / 1000,
    }


# ═════════════════════════════════════════════════════════════════════
# 5. Métriques thermiques et normalisées ISO 19867-1
# ═════════════════════════════════════════════════════════════════════

def calculer_metriques_thermiques(df_cal: pd.DataFrame, ext: dict) -> dict:
    """
    Paramètres ext :
        type_combustible       : clé du dict COMBUSTIBLES
        masse_bois_kg          : masse combustible initial (kg, humide)
        masse_charbon_kg       : masse résidu combustible en fin de phase (kg, humide) —
                                  bois non brûlé + charbon mélangés, sert uniquement au
                                  bilan massique (combustible brûlé = chargé − résidu).
        masse_charbon_produit_kg : masse de CHARBON SEUL produit par la combustion (kg,
                                  humide), pesée séparément (conteneur+charbon avant/après,
                                  comme le fait le classeur labo officiel). Optionnel — sans
                                  cette valeur, aucun crédit d'énergie charbon n'est appliqué
                                  (eff_avec_char == eff_sans_char), plutôt que de supposer à
                                  tort que tout le résidu pesé est du charbon pur.
        pci_custom_kJ_kg        : PCI net (kJ/kg) mesuré pour ce combustible précis, prioritaire
                                  sur la valeur par défaut du type de combustible sélectionné.
        pci_char_custom_kJ_kg   : PCI net (kJ/kg) du charbon produit, spécifique à ce test,
                                  prioritaire sur la constante HHV_CHARBON par défaut.
        humidite_pct        : teneur en humidité base humide (%)
        pots                : liste de dicts {masse_eau, T_debut, T_fin}
        T_atm               : température ambiante (°C)
        duree_min           : durée de la phase (min)
    """
    masse_bois    = ext.get('masse_bois_kg', 0.0)
    masse_charbon = ext.get('masse_charbon_kg', 0.0)
    masse_charbon_produit = ext.get('masse_charbon_produit_kg', 0.0) or 0.0
    humidite_pct  = ext.get('humidite_pct', 0.0)
    T_atm         = ext.get('T_atm', 25.0)
    duree_min     = ext.get('duree_min', 1.0)

    type_comb = ext.get('type_combustible', 'Bois dur moyen')
    pci, frac_c = COMBUSTIBLES.get(type_comb, (PCI_DEFAUT, FRAC_C_DEFAUT))
    pci_custom = ext.get('pci_custom_kJ_kg')
    if pci_custom:
        pci = pci_custom

    # Masse sèche (base humide → sèche)
    masse_bois_sec    = masse_bois    * (1.0 - humidite_pct / 100.0)
    masse_charbon_sec = masse_charbon * (1.0 - humidite_pct / 100.0)
    bois_brule_sec    = max(masse_bois_sec - masse_charbon_sec, 0.0)

    # Énergie combustible brûlé
    Q_combustible = bois_brule_sec * pci             # kJ

    # Énergie résiduelle dans le charbon RÉELLEMENT produit (pesée séparée).
    # ATTENTION : ne PAS utiliser masse_charbon_sec (résidu total = bois non brûlé +
    # charbon mélangés) ici — ce serait supposer à tort que 100% du résidu est du
    # charbon pur, ce qui surestime massivement Q_char (bug corrigé le 2026-10-27,
    # confirmé par comparaison avec 5 foyers bois × 5 tests : écarts +194% à +3255%
    # sur "Eff. avec charbon" avant correction).
    # Pas de correction d'humidité ici : masse_charbon_produit_kg est la masse de
    # charbon (déjà essentiellement sec/carbonisé) telle que pesée séparément — le taux
    # d'humidité du combustible d'origine ne s'applique pas à son propre résidu
    # carbonisé. Confirmé par comparaison avec le classeur officiel (foyers "Noflaye
    # Jeeg" A et C, 2026-10-27) : appliquer la correction d'humidité ici introduit un
    # écart résiduel de -0,18% à -1,15% ; sans elle, écart exactement 0,000%.
    masse_charbon_produit_sec = masse_charbon_produit
    pci_char = ext.get('pci_char_custom_kJ_kg') or HHV_CHARBON
    Q_char = masse_charbon_produit_sec * pci_char  # kJ

    # Chaleur utile (somme des pots)
    pots = ext.get('pots', None)
    if pots:
        Q_utile = sum(
            p.get('masse_eau', 0) * CP_EAU * (p.get('T_fin', 0) - p.get('T_debut', 0))
            for p in pots
        )
    else:
        masse_eau = ext.get('masse_eau_kg', 1.0)
        Q_utile   = masse_eau * CP_EAU * (ext.get('T_eau_fin', 90) - ext.get('T_eau_debut', 20))

    # Efficacité thermique ISO 19867 : dénominateur = combustible BRÛLÉ sec × PCI (pas le chargé initial)
    a_residu_charbonneux = type_comb in FUELS_AVEC_RESIDU_CHARBONNEUX
    eff_sans_char = (Q_utile / Q_combustible * 100.0) if Q_combustible > 0 else 0.0
    if a_residu_charbonneux and Q_char > 0:
        # Formule officielle Aprovecho (confirmée exacte à 0,000% d'écart sur 15 couples
        # test×phase, foyer "Noflaye Jeeg", 2026-10-27) : le charbon produit réduit
        # l'énergie combustible effectivement DÉPENSÉE (dénominateur), il n'est PAS un
        # crédit ajouté à l'énergie utile (numérateur) — contrairement à la première
        # version de ce correctif (eff = (Q_utile+Q_char)/Q_combustible), qui restait
        # fausse de +7% à +47% même une fois la masse de charbon correctement saisie.
        denom = Q_combustible - Q_char
        eff_avec_char = (Q_utile / denom * 100.0) if denom > 0 else eff_sans_char
    else:
        # Pas de notion de "résidu charbonneux" distincte pour ce combustible, ou pas de
        # charbon produit renseigné (le résidu pesé est du combustible non brûlé, pas un
        # sous-produit à créditer).
        eff_avec_char = eff_sans_char

    # Puissances (kW)
    duree_s = duree_min * 60.0
    puissance_feu  = Q_combustible / duree_s if duree_s > 0 else 0.0
    puissance_cuis = Q_utile       / duree_s if duree_s > 0 else 0.0

    # Taux de combustion base sèche (g/min)
    taux_combustion = (bois_brule_sec * 1000) / duree_min if duree_min > 0 else 0.0

    # CO₂ théorique
    co2_theorique_g = frac_c * bois_brule_sec * 1000 * (MW_CO2 / 12.0)

    return {
        'masse_bois_sec_kg'       : round(masse_bois_sec, 4),
        'masse_charbon_sec_kg'    : round(masse_charbon_sec, 4),
        'masse_charbon_produit_sec_kg': round(masse_charbon_produit_sec, 4),
        'bois_brule_sec_kg'       : round(bois_brule_sec, 4),
        'humidite_pct'            : round(humidite_pct, 2),
        'Q_utile_kJ'              : round(Q_utile, 2),
        'Q_combustible_kJ'        : round(Q_combustible, 2),
        'Q_char_kJ'               : round(Q_char, 2),
        'efficacite_sans_char_pct': round(eff_sans_char, 2),
        'efficacite_avec_char_pct': round(eff_avec_char, 2),
        'a_residu_charbonneux'    : a_residu_charbonneux,
        'puissance_feu_kW'        : round(puissance_feu, 4),
        'puissance_cuis_kW'       : round(puissance_cuis, 4),
        'taux_combustion_g_min'   : round(taux_combustion, 4),
        'CO2_theorique_g'         : round(co2_theorique_g, 2),
    }


def calculer_metriques_normalisees(totaux: dict, thermique: dict, duree_min: float) -> dict:
    """
    Métriques normalisées par masse combustible, par énergie et par temps.
    Reproduit exactement les colonnes du Tableau calcul puissance Bois 5 Tests.xlsx.
    """
    fuel_dry_g  = thermique['bois_brule_sec_kg'] * 1000
    fuel_dry_kg = thermique['bois_brule_sec_kg']
    Q_comb_MJ   = thermique['Q_combustible_kJ'] / 1000.0
    Q_utile_MJ  = thermique['Q_utile_kJ']       / 1000.0

    def safe_div(a, b):
        return round(a / b, 6) if b > 0 else 0.0

    pm_mg  = totaux['PM_total_mg']
    co_g   = totaux['CO_total_g']
    co2_g  = totaux['CO2_total_g']

    return {
        # PM2.5
        'PM_par_masse_mg_kg'    : safe_div(pm_mg,       fuel_dry_kg),
        'PM_par_energie_mg_MJ'  : safe_div(pm_mg / 1000, Q_comb_MJ) * 1000,
        'PM_par_utile_mg_MJ'    : safe_div(pm_mg / 1000, Q_utile_MJ) * 1000,
        'PM_par_temps_mg_min'   : safe_div(pm_mg,        duree_min),
        # CO
        'CO_par_masse_g_kg'     : safe_div(co_g,         fuel_dry_kg),
        'CO_par_energie_g_MJ'   : safe_div(co_g,         Q_comb_MJ),
        'CO_par_utile_g_MJ'     : safe_div(co_g,         Q_utile_MJ),
        'CO_par_temps_g_min'    : safe_div(co_g,         duree_min),
        # CO2
        'CO2_par_masse_g_kg'    : safe_div(co2_g,        fuel_dry_kg),
        'CO2_par_energie_g_MJ'  : safe_div(co2_g,        Q_comb_MJ),
        'CO2_par_utile_g_MJ'    : safe_div(co2_g,        Q_utile_MJ),
        'CO2_par_temps_g_min'   : safe_div(co2_g,        duree_min),
    }


# ═════════════════════════════════════════════════════════════════════
# 6. Efficacité de combustion modifiée (MCE)
# ═════════════════════════════════════════════════════════════════════

def calculer_mce(df_taux: pd.DataFrame) -> float:
    """MCE = ΔCO₂/(ΔCO₂+ΔCO) avec CO₂ et CO zéro-ajustés (T1.xlsx Logger Data col 40+35)."""
    co2_moy = df_taux['CO2_ppm_zeroed'].mean()
    co_moy  = df_taux['CO_ppm_zeroed'].clip(lower=0).mean()
    denom   = co2_moy + co_moy
    return round(co2_moy / denom * 100.0, 4) if denom > 0 else 0.0


# ═════════════════════════════════════════════════════════════════════
# 7. Classement Tier ISO/IWA-11
# ═════════════════════════════════════════════════════════════════════

def calculer_tier(co_g_mjd: float, pm_mg_mjd: float) -> int:
    """Tier ISO 19867-1 à partir des émissions normalisées par énergie utile
    (g/MJd, mg/MJd) — voir SEUILS_TIER.

    Robustesse (2026-10-18) : ne lève jamais d'exception.
    - None ou NaN (CO et/ou PM) : renvoie 0 par défaut. Ce 0 est un Tier
      "non calculable", pas un vrai résultat — voir detecter_anomalie_tier()
      pour le message à afficher à l'utilisateur. Ces deux cas sont traités
      AVANT tout clampage, car max(nan, 0.0) renvoie nan en Python (pas 0.0)
      — on ne peut donc pas compter sur le clamp pour neutraliser un NaN.
    - Valeur négative (CO et/ou PM, ex. après soustraction imparfaite du
      bruit de fond) : classée comme si elle était 0. Cela NE CHANGE PAS le
      chiffre retourné par rapport à avant (une valeur négative était déjà
      sous tout seuil positif) — voir detecter_anomalie_tier() pour
      l'avertissement, désormais disponible séparément.
    """
    if co_g_mjd is None or pm_mg_mjd is None:
        return 0
    if np.isnan(co_g_mjd) or np.isnan(pm_mg_mjd):
        return 0
    co_clamp = max(co_g_mjd, 0.0)
    pm_clamp = max(pm_mg_mjd, 0.0)
    for tier in [5, 4, 3, 2, 1]:
        co_max, pm_max = SEUILS_TIER[tier]
        if co_clamp < co_max and pm_clamp < pm_max:
            return tier
    return 0


def detecter_anomalie_tier(co_g_mjd, pm_mg_mjd):
    """Décrit en texte une valeur CO/PM anormale avant classement Tier.
    Purement informatif : ne change jamais le chiffre renvoyé par
    calculer_tier(). Retourne None si rien à signaler.
    """
    for nom, val in (('CO', co_g_mjd), ('PM2,5', pm_mg_mjd)):
        if val is None:
            return (f"Tier non calculable (valeur de {nom} manquante) — "
                    f"Tier affiché (0) à titre indicatif, à ne pas "
                    f"interpréter comme un résultat réel.")
        if np.isnan(val):
            return (f"Tier non calculable (valeur de {nom} invalide : NaN) — "
                    f"Tier affiché (0) à titre indicatif, à ne pas "
                    f"interpréter comme un résultat réel.")
    if co_g_mjd < 0 or pm_mg_mjd < 0:
        return ("Valeur négative après soustraction du bruit de fond — "
                "Tier à confirmer.")
    return None


# ═════════════════════════════════════════════════════════════════════
# 8. Analyse complète d'une phase
# ═════════════════════════════════════════════════════════════════════

def analyser(resultat_csv: dict, donnees_ext: dict = None) -> dict:
    donnees_ext   = donnees_ext or {}
    df_brut_full  = resultat_csv['donnees']
    calibr        = resultat_csv['calibration']
    T_atm         = donnees_ext.get('T_atm', 25.0)
    baseline_flow = donnees_ext.get('baseline_flow', None)

    # Filtrage temporel — si l'utilisateur a sélectionné un intervalle
    t_debut_s = donnees_ext.get('t_debut_s', None)
    t_fin_s   = donnees_ext.get('t_fin_s', None)
    if t_debut_s is not None and t_fin_s is not None:
        df_brut = df_brut_full[
            (df_brut_full['seconds'] >= t_debut_s) &
            (df_brut_full['seconds'] <= t_fin_s)
        ].copy()
    else:
        df_brut = df_brut_full

    # Valeurs de fond (logunits bruts du CSV)
    # Converties en unités calibrées : bg_pm_ug = bg_pm_raw × cal_PM (0.77)
    #                                  bg_co_ppm = bg_co_raw × cal_CO (0.03863)
    pm_cal = calibr[2] if len(calibr) > 2 and calibr[2] != 0 else 0.77
    co_cal = calibr[0] if len(calibr) > 0 and calibr[0] != 0 else 0.03863
    bg_pm_raw  = donnees_ext.get('bg_pm_raw', None)
    bg_co_raw  = donnees_ext.get('bg_co_raw', None)
    bg_pm_ug   = (bg_pm_raw * pm_cal) if bg_pm_raw is not None else 0.0
    bg_co_ppm  = (bg_co_raw * co_cal) if bg_co_raw is not None else 0.0
    bg_co2_ppm = donnees_ext.get('bg_co2_ppm', 0.0)  # CO₂ de fond en ppm (déjà calibré)

    p_Pa = donnees_ext.get('p_Pa', 101325.0)

    df_cal  = appliquer_calibration(df_brut, calibr)
    df_taux = calculer_taux_emission(df_cal, baseline_flow, T_atm,
                                     bg_pm_ug, bg_co_ppm, bg_co2_ppm, p_Pa)
    totaux  = integrer_emissions(df_taux)

    duree_s   = float(df_brut['seconds'].max() - df_brut['seconds'].min())
    duree_min = duree_s / 60.0
    if 'duree_min' not in donnees_ext:
        donnees_ext['duree_min'] = duree_min

    thermique  = calculer_metriques_thermiques(df_cal, donnees_ext)
    normalises = calculer_metriques_normalisees(totaux, thermique, duree_min)
    mce        = calculer_mce(df_taux)

    stats = {
        'CO_moy_ppm'         : round(df_taux['CO_ppm_zeroed'].mean(), 2),
        'CO_max_ppm'         : round(df_taux['CO_ppm_zeroed'].max(), 2),
        'PM_moy_ug_m3'       : round(df_taux['PM_ug_zeroed'].mean(), 2),
        'PM_max_ug_m3'       : round(df_taux['PM_ug_zeroed'].max(), 2),
        'CO2_moy_ppm'        : round(df_taux['CO2_ppm_zeroed'].mean(), 2),
        'TC_moy_C'           : round(df_cal['TC'].mean(), 2),
        'debit_moy_m3_min'   : round(df_taux['debit_m3_min'].mean(), 4),
        'CO_taux_moy_mg_min' : round(df_taux['CO_taux_mg_min'].mean(), 4),
        'PM_taux_moy_mg_min' : round(df_taux['PM_taux_mg_min'].mean(), 4),
        'MCE_pct'            : mce,
    }

    co_g_mjd  = normalises.get('CO_par_utile_g_MJ', 0.0)
    pm_mg_mjd = normalises.get('PM_par_utile_mg_MJ', 0.0)
    tier      = calculer_tier(co_g_mjd, pm_mg_mjd)
    avertissement_tier = detecter_anomalie_tier(co_g_mjd, pm_mg_mjd)

    return {
        'df_brut'    : df_brut,
        'df_cal'     : df_cal,
        'df_taux'    : df_taux,
        'totaux'     : totaux,
        'stats'      : stats,
        'thermique'  : thermique,
        'normalises' : normalises,
        'tier'       : tier,
        'label_tier' : LABEL_TIER[tier],
        'avertissement_tier': avertissement_tier,
        'duree_s'    : round(duree_s, 1),
        'duree_min'  : round(duree_min, 2),
    }
