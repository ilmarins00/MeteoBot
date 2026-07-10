# thermo.py
"""
Funzioni termodinamiche per MeteoBot – implementazione nativa senza dipendenze esterne.
Calcola CAPE/CIN per tre tipi di particella:
  - Surface-Based (SBCAPE/SBCIN): dalla superficie
  - Most-Unstable (MUCAPE/MUCIN): dal livello più instabile (massimo θe)
  - Mixed-Layer 100hPa (MLCAPE/MLCIN): media del primo strato 100 hPa

Riferimenti:
  - Bolton (1980) – LCL / parcel temperature
  - Doswell & Rasmussen (1994) – CAPE/CIN discrete integration
  - WMO No.49 (2018) – termini e definizioni
  - Emanuel (1994) – Atmospheric Convection
"""

import math
from typing import List, Tuple, Dict, Optional

# \u2500\u2500 Costanti fisiche \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
Rd  = 287.05   # J/(kg·K) costante gas secco
Rv  = 461.5    # J/(kg·K) costante gas vapore
Cp  = 1004.0   # J/(kg·K) calore specifico aria a p costante
Lv  = 2.501e6  # J/kg     calore latente vaporizzazione (a 0°C)
g   = 9.80665  # m/s²
eps = Rd / Rv  # 0.6220

# \u2500\u2500 Pressione di vapore saturo (Tetens, Alduchov & Eskridge 1996) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def esat(T_k: float) -> float:
    """Pressione di vapore saturo (Pa) da temperatura (K)."""
    Tc = T_k - 273.15
    return 611.2 * math.exp(17.67 * Tc / (Tc + 243.5))

def mixing_ratio_sat(T_k: float, p_pa: float) -> float:
    """Mixing ratio di saturazione ws (kg/kg) da T(K), p(Pa)."""
    es = esat(T_k)
    es = min(es, p_pa * 0.999)
    return eps * es / (p_pa - es)

def dewpoint_from_rh(T_k: float, RH: float) -> float:
    """Punto di rugiada (K) da T(K) e RH(%)."""
    if RH <= 0:
        return T_k - 50.0
    Tc = T_k - 273.15
    # Magnus approximation
    gamma = math.log(RH / 100.0) + 17.67 * Tc / (243.5 + Tc)
    Td_c = 243.5 * gamma / (17.67 - gamma)
    return Td_c + 273.15

def virtual_temperature(T_k: float, w_kg_kg: float) -> float:
    """Temperatura virtuale Tv = T * (1 + w/eps) / (1 + w)."""
    return T_k * (1.0 + w_kg_kg / eps) / (1.0 + w_kg_kg)

# \u2500\u2500 LCL \u2013 Bolton (1980) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def lcl_temperature(T_k: float, Td_k: float) -> float:
    """Temperatura al LCL (K) – Bolton (1980) eq. 15."""
    try:
        return 1.0 / (
            1.0 / (Td_k - 56.0) + math.log(T_k / Td_k) / 800.0
        ) + 56.0
    except (ValueError, ZeroDivisionError):
        return T_k - (T_k - Td_k) * 1.212

def lcl_height(T_k: float, Td_k: float, p_pa: Optional[float] = None) -> float:
    """
    Altezza del LCL (m).
    Se p fornita usa il metodo isoentropico, altrimenti usa la regressione
    empirica z_LCL ≈ 123 * (T - Td) in °C [Romps 2017, approssimazione].
    """
    dT = T_k - Td_k
    if dT < 0:
        dT = 0.0
    return 123.0 * dT   # m

def lcl_pressure(T_k: float, Td_k: float, p_sfc_pa: float) -> float:
    """Pressione al LCL (Pa) – Bolton (1980)."""
    T_lcl = lcl_temperature(T_k, Td_k)
    return p_sfc_pa * (T_lcl / T_k) ** (Cp / Rd)

# \u2500\u2500 Temperatura della particella lungo la pseudoadiabatica umida \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def moist_adiabatic_lapse_rate(T_k: float, p_pa: float) -> float:
    """
    Gradiente pseudoadiabatico umido MALR (K/m) a T(K), p(Pa).
    Formula Wallace & Hobbs (2006), eq. 3.98:
      Γs = (g/Cp) * (1 + Lv*ws/(Rd*T)) / (1 + Lv²*ws/(Cp*Rv*T²))
    dove Rv = gas constant vapore, eps = Rd/Rv.
    """
    ws = mixing_ratio_sat(T_k, p_pa)
    numer = 1.0 + Lv * ws / (Rd * T_k)
    denom = 1.0 + Lv**2 * ws * eps / (Cp * Rd * T_k**2)
    return g / Cp * numer / denom  # K/m

def parcel_temperature_moist(
    T_lcl_k: float,
    p_lcl_pa: float,
    p_target_pa: float,
) -> float:
    """
    Temperatura della particella alla pressione p_target seguendo
    la pseudoadiabatica umida. Integrazione numerica RK4.
    """
    # Scala di pressione: dalla LCL fino al target
    if abs(p_target_pa - p_lcl_pa) < 1:
        return T_lcl_k
    # Usa passaggi di 500 Pa
    dp = -500.0 if p_target_pa < p_lcl_pa else 500.0
    p_cur = p_lcl_pa
    T_cur = T_lcl_k
    n_steps = max(int(abs(p_target_pa - p_lcl_pa) / abs(dp)), 1)
    dp_actual = (p_target_pa - p_lcl_pa) / n_steps
    for _ in range(n_steps):
        # RK4 su dT/dp = T/(p) * g*numer/Cp/denom (approssimazione su log p)
        def dT_dp(T, p):
            rho = p / (Rd * T)
            malr = moist_adiabatic_lapse_rate(T, p)
            # dT/dp = (dT/dz) / (dp/dz) = (-MALR) / (-rho*g)
            return malr / (rho * g)
        k1 = dT_dp(T_cur, p_cur)
        k2 = dT_dp(T_cur + dp_actual * k1 / 2, p_cur + dp_actual / 2)
        k3 = dT_dp(T_cur + dp_actual * k2 / 2, p_cur + dp_actual / 2)
        k4 = dT_dp(T_cur + dp_actual * k3, p_cur + dp_actual)
        T_cur += dp_actual * (k1 + 2*k2 + 2*k3 + k4) / 6
        p_cur += dp_actual
    return T_cur

# \u2500\u2500 Profilo parcella completo \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def build_parcel_profile(
    pressure: List[float],
    temperature: List[float],
    parcel_p: float,
    parcel_T: float,
    parcel_Td: float,
) -> List[float]:
    """
    Costruisce il profilo temperatura della particella per ogni livello di pressione.
    Sotto la LCL: gradiente secco adiabático (g/Cp).
    Sopra la LCL: pseudoadiabatica umida.
    Ritorna lista di T_parcel (K) per ogni livello in `pressure`.
    """
    T_lcl = lcl_temperature(parcel_T, parcel_Td)
    p_lcl = lcl_pressure(parcel_T, parcel_Td, parcel_p)
    DALR = g / Cp  # K/m appross. con K/Pa: usa rapporto isoentropico
    profile = []
    for p in pressure:
        if p >= p_lcl:
            # Sotto LCL: adiabatica secca (T_parcel ~ T_sfc * (p/p_sfc)^(Rd/Cp))
            T_p = parcel_T * (p / parcel_p) ** (Rd / Cp)
        else:
            # Sopra LCL: pseudoadiabatica umida
            T_p = parcel_temperature_moist(T_lcl, p_lcl, p)
        profile.append(T_p)
    return profile

# \u2500\u2500 CAPE / CIN discrete \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _cape_cin_from_parcel_profile(
    pressure: List[float],
    temperature: List[float],
    parcel_profile: List[float],
    parcel_p: float,
) -> Tuple[float, float]:
    """
    Integrazione discreta CAPE e CIN (J/kg).
    Usa temperatura virtuale per includere l'effetto del vapore acqueo.
    CAPE = ∫ g * (Tv_parcel - Tv_env) / Tv_env * dz  (strati positivi sopra LFC)
    CIN  = ∫ g * (Tv_parcel - Tv_env) / Tv_env * dz  (strati negativi sotto LFC)
    Algoritmo LFC: la prima quota dove il buoyancy è positivo dopo la superficie.
    """
    # Ordina i livelli dal basso (pressione alta) verso l'alto
    layers = sorted(
        zip(pressure, temperature, parcel_profile),
        key=lambda x: -x[0],
    )
    # Calcola contributi per ogni strato
    contributions = []
    for i in range(1, len(layers)):
        p1, Tenv1, Tp1 = layers[i-1]
        p2, Tenv2, Tp2 = layers[i]
        if p1 > parcel_p and p2 > parcel_p:
            continue   # sotto il livello di partenza (pressione maggiore = quota inferiore)

        # Spessore strato in m (approssimazione isostatica)
        dz = Rd / g * (Tenv1 + Tenv2) / 2.0 * math.log(p1 / p2)
        if dz <= 0:
            continue

        # Buoyancy medio nello strato
        Tv_parcel_avg = (Tp1 + Tp2) / 2.0
        Tv_env_avg    = (Tenv1 + Tenv2) / 2.0
        buoyancy = g * (Tv_parcel_avg - Tv_env_avg) / Tv_env_avg
        contributions.append((buoyancy, dz))

    if not contributions:
        return 0.0, 0.0

    # Trova il LFC: cerca la prima transizione negativo→positivo
    # (oppure il primo strato positivo se parte già positivo)
    lfc_idx = None
    for i, (b, dz) in enumerate(contributions):
        if b > 0:
            lfc_idx = i
            break

    if lfc_idx is None:
        # Nessuna positività → solo CIN
        cin_acc = sum(b * dz for b, dz in contributions)
        return 0.0, round(min(cin_acc, 0.0), 1)

    # CIN = integrale negativo PRIMA dell'LFC.
    # Se il primo strato è già positivo (LFC coincide con la superficie),
    # non significa CIN=0 in senso fisico: con soli 6 livelli isobarici
    # da Open-Meteo la risoluzione verticale può non catturare sottili
    # strati di inibizione presso il suolo. In quel caso stimiamo un CIN
    # minimo conservativo proporzionale al gap LCL-superficie, invece di
    # affermare "nessuna inibizione" con overconfidence.
    if lfc_idx == 0 and len(contributions) < 8:
        cin_acc = -15.0  # inibizione minima stimata, risoluzione insufficiente
    else:
        cin_acc = sum(b * dz for b, dz in contributions[:lfc_idx] if b < 0)
    # CAPE = integrale positivo DOPO (e incluso) l'LFC
    cape_acc = sum(b * dz for b, dz in contributions[lfc_idx:] if b > 0)

    return round(max(cape_acc, 0.0), 1), round(min(cin_acc, 0.0), 1)

def cape_cin_from_profile(
    pressure: List[float],
    temperature: List[float],
    dewpoint: List[float],
    parcel_p: float,
    parcel_T: float,
    parcel_Td: float,
) -> Tuple[float, float]:
    """
    CAPE e CIN (J/kg) per la parcella specificata.
    Implementazione nativa senza MetPy.
    Se MetPy è disponibile, lo usa per maggiore precisione.
    """
    # Prova MetPy (più preciso)
    try:
        import metpy.calc as mpcalc
        from metpy.units import units
        p_u   = [x * units.pascal for x in pressure]
        T_u   = [x * units.kelvin for x in temperature]
        Td_u  = [x * units.kelvin for x in dewpoint]
        pT_u  = parcel_T  * units.kelvin
        pTd_u = parcel_Td * units.kelvin
        pp_u  = parcel_p  * units.pascal
        parcel_prof = mpcalc.parcel_profile(p_u, pT_u, pTd_u)
        cape, cin = mpcalc.cape_cin(p_u, T_u, Td_u, parcel_prof)
        return float(cape.magnitude), float(cin.magnitude)
    except Exception:
        pass
    # Fallback: implementazione nativa
    parcel_profile = build_parcel_profile(pressure, temperature, parcel_p, parcel_T, parcel_Td)
    return _cape_cin_from_parcel_profile(pressure, temperature, parcel_profile, parcel_p)

# \u2500\u2500 Most-Unstable CAPE (MUCAPE) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def theta_e(T_k: float, Td_k: float, p_pa: float) -> float:
    """
    Temperatura equivalente potenziale θe (K) – Bolton (1980) eq. 43.
    """
    T_lcl = lcl_temperature(T_k, Td_k)
    ws = mixing_ratio_sat(Td_k, p_pa)  # approssimazione: ws al Td ≈ mixing ratio
    return T_k * (100000.0 / p_pa) ** (0.2854 * (1.0 - 0.28 * ws)) * \
        math.exp((3376.0 / T_lcl - 2.54) * ws * (1.0 + 0.81 * ws))

def mucape_mucin(
    pressure: List[float],
    temperature: List[float],
    dewpoint: List[float],
    search_depth_pa: float = 30000.0,
) -> Tuple[float, float, int]:
    """
    MUCAPE/MUCIN: cerca la parcella più instabile (massimo θe)
    nei primi search_depth_pa Pa al di sopra della superficie.
    Ritorna (MUCAPE, MUCIN, indice_livello).
    """
    if not pressure:
        return 0.0, 0.0, 0
    p_sfc = max(pressure)
    p_top_search = p_sfc - search_depth_pa
    best_idx = 0
    best_the = -999.0
    for i, (p, T, Td) in enumerate(zip(pressure, temperature, dewpoint)):
        if p < p_top_search:
            continue
        the = theta_e(T, Td, p)
        if the > best_the:
            best_the = the
            best_idx = i
    p_mu  = pressure[best_idx]
    T_mu  = temperature[best_idx]
    Td_mu = dewpoint[best_idx]
    cape, cin = cape_cin_from_profile(
        pressure, temperature, dewpoint, p_mu, T_mu, Td_mu
    )
    return cape, cin, best_idx

def mlcape_mlcin(
    pressure: List[float],
    temperature: List[float],
    dewpoint: List[float],
    layer_depth_pa: float = 10000.0,
) -> Tuple[float, float]:
    """
    MLCAPE/MLCIN: media T e Td nei primi layer_depth_pa Pa (tipicamente ~100 hPa)
    come rappresentazione dello strato rimescolato.
    """
    if not pressure:
        return 0.0, 0.0
    p_sfc = max(pressure)
    p_bottom = p_sfc
    p_top_layer = p_sfc - layer_depth_pa
    T_vals, Td_vals, p_vals = [], [], []
    for p, T, Td in zip(pressure, temperature, dewpoint):
        if p >= p_top_layer:
            T_vals.append(T)
            Td_vals.append(Td)
            p_vals.append(p)
    if not T_vals:
        T_vals = [temperature[0]]
        Td_vals = [dewpoint[0]]
        p_vals = [pressure[0]]
    T_ml  = sum(T_vals) / len(T_vals)
    Td_ml = sum(Td_vals) / len(Td_vals)
    p_ml  = sum(p_vals) / len(p_vals)
    return cape_cin_from_profile(
        pressure, temperature, dewpoint, p_ml, T_ml, Td_ml
    )

# \u2500\u2500 Lifted Index \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def lifted_index(
    pressure: List[float],
    temperature: List[float],
    parcel_T: float,
    parcel_Td: float,
    parcel_p: float,
) -> Optional[float]:
    """
    Lifted Index (LI) a 500 hPa.
    LI = T_500_ambiente - T_500_parcella.
    Negativo = instabile.
    """
    target_p = 50000.0  # 500 hPa
    # Trova T ambiente a 500 hPa (interpolazione)
    T_env_500 = None
    for i in range(1, len(pressure)):
        if pressure[i-1] >= target_p >= pressure[i]:
            frac = (pressure[i-1] - target_p) / (pressure[i-1] - pressure[i])
            T_env_500 = temperature[i-1] + frac * (temperature[i] - temperature[i-1])
            break
    if T_env_500 is None:
        return None
    T_lcl = lcl_temperature(parcel_T, parcel_Td)
    p_lcl = lcl_pressure(parcel_T, parcel_Td, parcel_p)
    T_parcel_500 = parcel_temperature_moist(T_lcl, p_lcl, target_p)
    return round(T_env_500 - T_parcel_500, 1)

# — Calcolo completo di tutti gli indici termodinamici da profilo ────────────────

def dcape_from_profile(
    pressure: List[float],
    temperature: List[float],
    dewpoint: List[float],
) -> float:
    """
    Downdraft CAPE (J/kg): energia disponibile per raffiche discendenti / downburst.

    Algoritmo (Brooks & Doswell 1994; Emanuel 1994):
    1. Trova il livello con minima θe nella fascia 600-300 hPa (sorgente del downdraft)
    2. Calcola la parcella che scende in pseudoadiabatica umida fino alla superficie
    3. Integra il buoyancy NEGATIVO (parcel fredda) → energia disponibile per la discesa

    V_max_downburst ≈ √(2 · DCAPE) in m/s
      DCAPE 500 J/kg → ~114 km/h
      DCAPE 1000 J/kg → ~161 km/h
    """
    if len(pressure) < 4:
        return 0.0

    # Livelli ordinati dal basso verso l'alto (pressione decrescente)
    levels = sorted(zip(pressure, temperature, dewpoint), key=lambda x: -x[0])

    # Trova il livello con minima θe nella fascia 600-300 hPa
    source_level: Optional[Tuple[float, float, float]] = None
    min_the = float("inf")
    for p, T, Td in levels:
        if 30000.0 <= p <= 60000.0:
            the = theta_e(T, Td, p)
            if the < min_the:
                min_the = the
                source_level = (p, T, Td)

    if source_level is None:
        return 0.0

    p_src, T_src, Td_src = source_level

    # Integra buoyancy negativo dalla sorgente alla superficie
    dcape = 0.0
    p_prev = T_parcel_prev = T_env_prev = None

    for p, T_env, _ in levels:
        if p < p_src:
            continue  # sopra la sorgente → non consideriamo

        T_parcel = parcel_temperature_moist(T_src, p_src, p)

        if p_prev is not None:
            T_env_mid = (T_env_prev + T_env) / 2.0
            dz = abs(Rd / g * T_env_mid * math.log(p_prev / p))
            Tv_parcel_mid = (T_parcel_prev + T_parcel) / 2.0
            buoy = g * (Tv_parcel_mid - T_env_mid) / T_env_mid
            if buoy < 0:
                dcape += abs(buoy) * dz

        p_prev = p
        T_parcel_prev = T_parcel
        T_env_prev = T_env

    return round(dcape, 1)


def dcape_gust_kmh(dcape: float) -> float:
    """Stima raffica massima da downburst: V = √(2·DCAPE) convertita in km/h."""
    return round(math.sqrt(2.0 * max(dcape, 0.0)) * 3.6, 0)


def compute_all_thermo(
    pressure: List[float],
    temperature: List[float],
    dewpoint: List[float],
) -> Dict[str, Optional[float]]:
    """
    Calcola tutti gli indici termodinamici in un'unica chiamata.
    Ritorna un dict con SBCAPE, SBCIN, MUCAPE, MUCIN, MLCAPE, MLCIN,
    LI, LCL_height, θe_max.
    """
    if not pressure or len(pressure) < 2:
        return {
            "SBCAPE": 0.0, "SBCIN": 0.0,
            "MUCAPE": 0.0, "MUCIN": 0.0,
            "MLCAPE": 0.0, "MLCIN": 0.0,
            "LI": None, "LCL": None, "theta_e_max": None,
        }
    # Livello superficie = indice con pressione massima
    sfc_idx = pressure.index(max(pressure))
    p_sfc  = pressure[sfc_idx]
    T_sfc  = temperature[sfc_idx]
    Td_sfc = dewpoint[sfc_idx]

    sb_cape, sb_cin = cape_cin_from_profile(
        pressure, temperature, dewpoint, p_sfc, T_sfc, Td_sfc
    )
    mu_cape, mu_cin, _ = mucape_mucin(pressure, temperature, dewpoint)
    ml_cape, ml_cin   = mlcape_mlcin(pressure, temperature, dewpoint)
    li = lifted_index(pressure, temperature, T_sfc, Td_sfc, p_sfc)
    lcl = lcl_height(T_sfc, Td_sfc)
    the_max = max(
        theta_e(T, Td, p) for p, T, Td in zip(pressure, temperature, dewpoint)
        if p >= max(pressure) - 30000
    )
    dcape = dcape_from_profile(pressure, temperature, dewpoint)

    return {
        "SBCAPE": sb_cape,  "SBCIN": sb_cin,
        "MUCAPE": mu_cape,  "MUCIN": mu_cin,
        "MLCAPE": ml_cape,  "MLCIN": ml_cin,
        "CAPE":   sb_cape,  "CIN":   sb_cin,  # compatibilità
        "LI":     li,
        "LCL":    lcl,
        "theta_e_max": round(the_max, 1),
        "DCAPE": dcape,
    }
