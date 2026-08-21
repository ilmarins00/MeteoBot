# indices.py
"""
Calcolo indici convettivi, sinottici e orografici per il motore MeteoBot.
Territorio di riferimento: La Spezia e Levante Ligure (Appennino Ligure Orientale).

Indici implementati:
  - Bulk shear 0-1, 0-3, 0-6 km (kt)
  - SRH 0-1 km, 0-3 km (m²/s²) – metodo integrale discreto Bunkers-Weisman
  - Lapse rates strato per strato
  - K-Index, Totals-Totals, SWEAT
  - EHI (Energy-Helicity Index)
  - SCP (Supercell Composite Parameter)
  - STP (Significant Tornado Parameter)
  - PWAT – integrazione discreta nativa (no MetPy)
  - Orographic enhancement per Appennino Ligure
  - Indice brezza marina / convergenza costiera
"""

import math
from typing import Dict, List, Tuple, Optional, Any

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Utility
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def vector_magnitude(u: float, v: float) -> float:
    return math.hypot(u, v)

def interpolate_wind(
    u_profile: List[float],
    v_profile: List[float],
    heights: List[float],
    target_z: float,
) -> Tuple[float, float]:
    """Interpolazione lineare vento a quota target_z (m)."""
    if not heights or not u_profile or not v_profile:
        return 0.0, 0.0
    if len(u_profile) != len(heights) or len(v_profile) != len(heights):
        return 0.0, 0.0
    if target_z <= heights[0]:
        return u_profile[0], v_profile[0]
    if target_z >= heights[-1]:
        return u_profile[-1], v_profile[-1]
    for i in range(1, len(heights)):
        if heights[i] >= target_z:
            dz = heights[i] - heights[i-1]
            if dz == 0:
                return u_profile[i], v_profile[i]
            frac = (target_z - heights[i-1]) / dz
            return (
                u_profile[i-1] + frac * (u_profile[i] - u_profile[i-1]),
                v_profile[i-1] + frac * (v_profile[i] - v_profile[i-1]),
            )
    return u_profile[-1], v_profile[-1]

def near_surface_wind(
    u_profile: List[float],
    v_profile: List[float],
    heights: List[float],
) -> Tuple[float, float]:
    """Media vento strato 0-500 m (rappresentativo superficiale)."""
    pts_u, pts_v = [], []
    for u, v, z in zip(u_profile, v_profile, heights):
        if z <= 500:
            pts_u.append(u)
            pts_v.append(v)
    if not pts_u:
        return u_profile[0], v_profile[0]
    return sum(pts_u) / len(pts_u), sum(pts_v) / len(pts_v)

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Shear
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def bulk_shear_ms(
    u_sfc: float, v_sfc: float, u_top: float, v_top: float
) -> float:
    """Bulk shear in m/s."""
    return math.hypot(u_top - u_sfc, v_top - v_sfc)

def bulk_shear_kt(
    u_sfc: float, v_sfc: float, u_top: float, v_top: float
) -> float:
    """Bulk shear in kt (1 m/s = 1.94384 kt)."""
    return bulk_shear_ms(u_sfc, v_sfc, u_top, v_top) * 1.94384

def compute_shear_profile(
    u_profile: List[float],
    v_profile: List[float],
    heights: List[float],
) -> Dict[str, float]:
    """
    Calcola bulk shear 0-1km, 0-3km, 0-6km e 0-500m.
    heights in m, u/v in m/s. Output in kt.
    Usa interpolazione lineare per le quote non presenti nel profilo.
    """
    u0, v0 = near_surface_wind(u_profile, v_profile, heights)
    u1, v1 = interpolate_wind(u_profile, v_profile, heights, 1000)
    u3, v3 = interpolate_wind(u_profile, v_profile, heights, 3000)
    u6, v6 = interpolate_wind(u_profile, v_profile, heights, 6000)
    u05, v05 = interpolate_wind(u_profile, v_profile, heights, 500)
    return {
        "shear_0_05": bulk_shear_kt(u0, v0, u05, v05),
        "shear_0_1":  bulk_shear_kt(u0, v0, u1,  v1),
        "shear_0_3":  bulk_shear_kt(u0, v0, u3,  v3),
        "shear_0_6":  bulk_shear_kt(u0, v0, u6,  v6),
        # Vento medio strato 0-6 km in m/s (per SCP)
        "mean_wind_0_6_ms": math.hypot(
            (u0 + u6) / 2, (v0 + v6) / 2
        ),
    }

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Bunkers storm motion (Rif: Bunkers et al. 2000)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

_BUNKERS_D = 7.5   # m/s – deviazione laterale
_BUNKERS_H = 6000  # m

def bunkers_storm_motion(
    u_profile: List[float],
    v_profile: List[float],
    heights: List[float],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Restituisce (moto cella destrorsa, moto cella sinistrorsa) in m/s.
    Usa il metodo Bunkers 2000 (Internal Dynamics).
    """
    # Vento medio 0-6 km
    u0, v0 = near_surface_wind(u_profile, v_profile, heights)
    u6, v6 = interpolate_wind(u_profile, v_profile, heights, _BUNKERS_H)
    um = (u0 + u6) / 2
    vm = (v0 + v6) / 2
    # Shear vettore 0-6 km
    du = u6 - u0
    dv = v6 - v0
    mag = math.hypot(du, dv)
    if mag < 1e-6:
        return (um, vm), (um, vm)
    # Vettore perpendicolare (rotazione 90°)
    px = -dv / mag * _BUNKERS_D
    py =  du / mag * _BUNKERS_D
    rm = (um + px, vm + py)   # destrorsa
    lm = (um - px, vm - py)   # sinistrorsa
    return rm, lm

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# SRH – Storm Relative Helicity (integrale discreto)
# Rif: Davies-Jones 1984; Markowski & Richardson (2010)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _srh_layer(
    u_profile: List[float],
    v_profile: List[float],
    heights: List[float],
    z_top: float,
    storm_u: float,
    storm_v: float,
) -> float:
    """
    SRH integrale da quota 0 a z_top m.
    Formula: SRH = -∑ (u_sr[i+1]+u_sr[i])*(v_sr[i+1]-v_sr[i])
                      - (v_sr[i+1]+v_sr[i])*(u_sr[i+1]-u_sr[i])
    dove u_sr = u - storm_u (vento storm-relativo).
    """
    # Costruisci livelli fino a z_top interpolando
    zs, us, vs = [], [], []
    for u, v, z in zip(u_profile, v_profile, heights):
        if z <= z_top:
            zs.append(z)
            us.append(u)
            vs.append(v)
    # Aggiungi punto interpolato a z_top se necessario
    if not zs or zs[-1] < z_top:
        u_top, v_top = interpolate_wind(u_profile, v_profile, heights, z_top)
        zs.append(z_top)
        us.append(u_top)
        vs.append(v_top)

    if len(zs) < 2:
        return 0.0

    srh = 0.0
    for i in range(len(zs) - 1):
        u1_sr = us[i]   - storm_u
        v1_sr = vs[i]   - storm_v
        u2_sr = us[i+1] - storm_u
        v2_sr = vs[i+1] - storm_v
        # Contributo prodotto vettoriale componente verticale
        srh += (u2_sr - u1_sr) * (v2_sr + v1_sr) - (v2_sr - v1_sr) * (u2_sr + u1_sr)
    return -srh / 2.0

def compute_srh(
    u_profile: List[float],
    v_profile: List[float],
    heights: List[float],
) -> Dict[str, float]:
    """
    Calcola SRH 0-1km e 0-3km con moto temporale Bunkers destrorso.
    Output in m²/s².
    """
    if len(u_profile) < 2 or len(heights) < 2:
        return {"srh_0_1": 0.0, "srh_0_3": 0.0}
    rm, _ = bunkers_storm_motion(u_profile, v_profile, heights)
    srh_01 = _srh_layer(u_profile, v_profile, heights, 1000, rm[0], rm[1])
    srh_03 = _srh_layer(u_profile, v_profile, heights, 3000, rm[0], rm[1])
    return {
        "srh_0_1": round(srh_01, 1),
        "srh_0_3": round(srh_03, 1),
    }

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Lapse rates
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def lapse_rate(
    T_top: float, T_bottom: float, z_top: float, z_bottom: float
) -> float:
    """Gradiente termico verticale K/km (positivo = instabile)."""
    dz_km = (z_top - z_bottom) / 1000.0
    if abs(dz_km) < 1e-6:
        return 0.0
    return (T_bottom - T_top) / dz_km

def compute_lapse_rates(
    temperature: List[float],
    heights: List[float],
) -> Dict[str, float]:
    """
    Calcola lapse rates per strati significativi (K/km).
    temperature in K o °C (units non cambiano la differenza).
    """
    def lr(z_bot, z_top):
        tb = _interp_temp(temperature, heights, z_bot)
        tt = _interp_temp(temperature, heights, z_top)
        if tb is None or tt is None:
            return None
        dz = (z_top - z_bot) / 1000.0
        return (tb - tt) / dz if dz > 0 else None

    return {
        "lr_0_3km":   lr(0,    3000),
        "lr_700_500": lr(3000, 5500),   # approssimazione 700-500 hPa
        "lr_850_500": lr(1500, 5500),   # approssimazione 850-500 hPa
    }

def _interp_temp(
    temperature: List[float],
    heights: List[float],
    target_z: float,
) -> Optional[float]:
    if not heights:
        return None
    if target_z <= heights[0]:
        return temperature[0]
    if target_z >= heights[-1]:
        return temperature[-1]
    for i in range(1, len(heights)):
        if heights[i] >= target_z:
            dz = heights[i] - heights[i-1]
            frac = (target_z - heights[i-1]) / dz if dz > 0 else 0
            return temperature[i-1] + frac * (temperature[i] - temperature[i-1])
    return None

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Indici termodinamici classici
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def k_index(
    T850: float, Td850: float, T700: float, Td700: float, T500: float
) -> float:
    """
    K-Index (George 1960). Input in °C.
    K = (T850 - T500) + Td850 - (T700 - Td700)
    Valori >25: temporali possibili; >35: probabili; >40: certi.
    """
    return (T850 - T500) + Td850 - (T700 - Td700)

def totals_totals(
    T850: float, Td850: float, T500: float
) -> float:
    """
    Totals-Totals Index. Input in °C.
    TT = VT + CT = (T850 - T500) + (Td850 - T500)
    Soglie: >44 temporali, >50 severi, >55 tornado.
    """
    return (T850 - T500) + (Td850 - T500)

def sweat_index(
    Td850: float, tt: float, wind_850_kt: float,
    wind_500_kt: float, dir_850: float, dir_500: float
) -> float:
    """
    SWEAT Index (Miller 1972). Input: Td850 in °C, TT da totals_totals,
    venti in kt, direzioni in gradi.
    Soglie: >150 temporali; >300 severi.
    """
    term1 = 12 * max(Td850, 0)
    term2 = 20 * max(tt - 49, 0)
    term3 = 2 * wind_850_kt
    term4 = wind_500_kt
    # Termine shear direzionale (solo se direzioni valide)
    term5 = 0.0
    if 130 <= dir_850 <= 250 and 210 <= dir_500 <= 310:
        dd = dir_500 - dir_850
        if dd > 0:
            term5 = 125 * (math.sin(math.radians(dd)) + 0.2)
    return term1 + term2 + term3 + term4 + term5

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Indici compositi: EHI, SCP, STP
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def ehi(cape: float, srh: float) -> float:
    """
    Energy-Helicity Index (Hart & Korotky 1991).
    EHI = (CAPE * SRH) / 160000
    EHI>1: significativo; >2.5: elevato; >5: estremo.
    """
    return (cape * srh) / 160000.0

def supercell_composite(
    mucape: float, srh_03: float, shear_0_6_kt: float,
) -> float:
    """
    Supercell Composite Parameter (Thompson et al. 2004).
    SCP = (MUCAPE/1000) * (SRH_03/50) * (Shear_06/40)
    SCP>1: ambiente favorevole supercelle; >4: altamente favorevole.
    """
    shear_ms = shear_0_6_kt / 1.94384
    return (mucape / 1000.0) * (srh_03 / 50.0) * (shear_ms / 20.0)

def significant_tornado_parameter(
    sbcape: float, srh_01: float, shear_0_6_kt: float,
    lcl_m: float, cin: float,
) -> float:
    """
    Significant Tornado Parameter (Thompson et al. 2012, aggiornato).
    STP = f(SBCAPE, LCL, SRH_01, shear_06, CIN)
    STP>1: ambiente tornadogenico significativo.
    """
    if sbcape <= 0:
        return 0.0
    shear_ms = shear_0_6_kt / 1.94384
    cape_term  = sbcape / 1500.0
    srh_term   = max(srh_01, 0) / 150.0
    shear_term = min(shear_ms / 12.0, 1.5)
    # Fattore LCL (penalizza LCL alti)
    lcl_term = max((2000.0 - lcl_m) / 1000.0, 0.0)
    lcl_term = min(lcl_term, 1.0)
    # Fattore CIN (cin è negativo)
    cin_abs = abs(min(cin, 0))
    cin_term = max((200.0 - cin_abs) / 150.0, 0.0)
    cin_term = min(cin_term, 1.0)
    return cape_term * srh_term * shear_term * lcl_term * cin_term

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# PWAT \u2013 Precipitable Water (integrazione discreta nativa, nessuna dipendenza esterna)
# Rif: Wallace & Hobbs (2006), formula integrale colonna d'acqua
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

_g   = 9.80665   # m/s²
_Rv  = 461.5     # J/(kg·K) costante gas vapore
_eps = 0.622     # Rd/Rv

def _esat_pa(T_k: float) -> float:
    """Pressione di vapore saturo (Pa) – formula di Tetens (Alduchov & Eskridge 1996)."""
    Tc = T_k - 273.15
    return 611.2 * math.exp(17.67 * Tc / (Tc + 243.5))

def _mixing_ratio(T_k: float, Td_k: float, p_pa: float) -> float:
    """Mixing ratio g/kg dato T, Td (K) e pressione (Pa)."""
    e = _esat_pa(Td_k)
    e = min(e, p_pa * 0.999)
    return _eps * e / (p_pa - e) * 1000.0  # g/kg

def pwat_from_profile(
    pressure: List[float],
    temperature: List[float],
    dewpoint: List[float],
) -> float:
    """
    PWAT (mm) tramite integrazione discreta – nessuna dipendenza da MetPy.
    pressure in Pa (decrescente con quota), temperature/dewpoint in K.
    PWAT = (1/g) * ∫ w dp  dove w è il mixing ratio (kg/kg).
    """
    if len(pressure) < 2:
        return 0.0
    # Ordina per pressione decrescente (dal basso)
    layers = sorted(
        zip(pressure, temperature, dewpoint),
        key=lambda x: -x[0]
    )
    pwat_mm = 0.0
    for i in range(1, len(layers)):
        p1, T1, Td1 = layers[i-1]
        p2, T2, Td2 = layers[i]
        dp = abs(p1 - p2)
        w1 = _mixing_ratio(T1, Td1, p1) / 1000.0  # kg/kg
        w2 = _mixing_ratio(T2, Td2, p2) / 1000.0
        w_avg = (w1 + w2) / 2.0
        pwat_mm += w_avg * dp / _g  # kg/m² = mm di acqua precipitabile
    return round(max(pwat_mm, 0.0), 1)

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Indici orografici \u2013 specifici Liguria / Spezzino
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

# Direzioni di flusso che massimizzano il sollevamento orografico
# sull'Appennino Ligure orientale (valore ottimale ~200-220°, ovvero scirocco/libeccio)
_OROGRAPHIC_OPTIMAL_DIR = 210.0
_OROGRAPHIC_HALF_WIDTH  = 60.0   # semi-larghezza della campana (gradi)

def orographic_enhancement(
    wind_dir_deg: float,
    wind_speed_ms: float,
    instability_factor: float = 1.0,
    elevation_m: float = 95.0,
) -> float:
    """
    Fattore di amplificazione orografica delle precipitazioni per il
    Levante Ligure (0.0 = nessuna amplificazione; 1.0 = massima).

    Massima amplificazione con flusso da S-SSO (200-220°) e venti forti.
    Modulato da fattore instabilità (es. CAPE normalizzato).

    elevation_m: quota del punto di osservazione (m s.l.m.). Zone più elevate
    e più interne sono più esposte al sollevamento orografico del flusso
    umido rispetto a zone costiere basse. Il coefficiente sotto è una stima
    EMPIRICA (non calibrata su osservazioni reali): se in futuro hai dati
    storici delle diverse zone, ricalibralo confrontando accumuli osservati.
    Default 95.0 m = quota storica della stazione di riferimento (Foce),
    così il comportamento resta identico a prima per chi non passa il parametro.
    """
    angle_diff = abs(wind_dir_deg - _OROGRAPHIC_OPTIMAL_DIR) % 360
    if angle_diff > 180:
        angle_diff = 360 - angle_diff
    # Campana gaussiana centrata sul flusso ottimale
    gauss = math.exp(-0.5 * (angle_diff / _OROGRAPHIC_HALF_WIDTH) ** 2)
    speed_factor = min(wind_speed_ms / 15.0, 1.0)  # satura a 15 m/s
    # Fattore quota: +1 punto ogni 500m sopra i 95m di riferimento, cap 1.3/0.85
    elevation_factor = min(1.0 + (elevation_m - 95.0) / 500.0, 1.3)
    elevation_factor = max(elevation_factor, 0.85)
    return gauss * speed_factor * instability_factor * elevation_factor

def sea_breeze_convergence_score(
    surface_wind_dir: float,
    surface_wind_speed_ms: float,
    synoptic_wind_dir: float,
    hour_utc: int,
) -> float:
    """
    Stima il rischio di convergenza brezza marina / flusso sinottico
    nel Golfo della Spezia (convezione pomeridiana innescata dalla convergenza).
    Restituisce 0.0 (nessun rischio) – 1.0 (massimo rischio).
    """
    # Brezza marina tipicamente da S-SO pomeridiana (12-18 UTC in estate)
    peak_hour = 14  # UTC (16 ora locale estiva)
    time_factor = max(0.0, 1.0 - abs(hour_utc - peak_hour) / 6.0)
    # Brezza opposta al flusso sinottico massimizza convergenza
    dir_diff = abs(surface_wind_dir - synoptic_wind_dir) % 360
    if dir_diff > 180:
        dir_diff = 360 - dir_diff
    convergence_factor = max(0.0, (dir_diff - 90.0) / 90.0) if dir_diff > 90 else 0.0
    speed_factor = min(surface_wind_speed_ms / 10.0, 1.0)
    return min(time_factor * convergence_factor * speed_factor * 1.5, 1.0)

# ─────────────────────────────────────────────────────────────────────────────
# Evoluzione oraria multi-parametro (per bollettino e prompt Gemini)
# ─────────────────────────────────────────────────────────────────────────────

def hourly_trend_series(
    hourly: List[Dict[str, Any]],
    field: str,
    sample_hours: Optional[List[int]] = None,
) -> List[Tuple[str, float]]:
    """
    Estrae una serie oraria campionata di un campo (es. 'CAPE', 'shear', 'SRH', 'PWAT')
    dalla lista hourly_forecast. Se sample_hours è None, campiona ogni 3 ore.

    Ritorna lista di (time_str, valore), solo per le ore effettivamente presenti.
    Serve a evitare che un singolo "picco" isolato (es. CAPE alle 15:00) venga
    mostrato senza il contesto della curva completa, che può indurre in errore
    quando confrontato con un valore di sintesi (es. SBCAPE massimo giornaliero)
    calcolato con un metodo diverso.
    """
    if not hourly:
        return []

    result = []
    for i, h in enumerate(hourly):
        t = h.get("time", "")
        try:
            hour_num = int(t.split(":")[0])
        except (ValueError, IndexError):
            continue
        if sample_hours is not None and hour_num not in sample_hours:
            continue
        if sample_hours is None and hour_num % 3 != 0:
            continue
        v = h.get(field)
        if v is not None:
            result.append((t, float(v)))
    return result


def describe_trend_series(
    series: List[Tuple[str, float]],
    unit: str = "",
    label: str = "",
) -> str:
    """
    Converte una serie (time, valore) in una frase descrittiva del trend,
    es. 'CAPE: 09:00=200, 12:00=1800, 15:00=4100 J/kg (in forte aumento)'.
    """
    if not series:
        return f"{label}: dati non disponibili" if label else "dati non disponibili"

    vals = [v for _, v in series]
    delta = vals[-1] - vals[0]
    if len(vals) >= 2:
        rel = abs(delta) / max(abs(vals[0]), 1.0)
        if rel < 0.15:
            trend_txt = "stazionario"
        elif delta > 0:
            trend_txt = "in forte aumento" if rel > 0.6 else "in aumento"
        else:
            trend_txt = "in forte calo" if rel > 0.6 else "in calo"
    else:
        trend_txt = "punto singolo"

    punti = ", ".join(f"{t}={v:.0f}" for t, v in series)
    prefix = f"{label}: " if label else ""
    return f"{prefix}{punti} {unit} ({trend_txt})"
