# logic.py
"""
Logica decisionale del motore MeteoBot.
Implementa:
  - Score convettivo multi-parametro (con amplificazione orografica Spezzino)
  - Classificazione modalità temporale (WMO + SPC taxonomy)
  - Hazard mapping completo (grandine, trombe, downburst, alluvioni rapide, ecc.)
  - Sistema allerte ARPAL Liguria: Verde / Gialla / Arancione / Rossa
  - Analisi fenomeni specifici del Levante Ligure (brezza, ciclogenesi Ligure,
    Medicane, neve in quota, nebbia marina, Libeccio/Scirocco intensi)

Soglie calibrate su:
  - ARPAL Liguria – Valori soglia per avviso meteorologico (2020)
  - WMO Guide to Severe Weather Warnings (2018)
  - SPC Supercell/Tornado Composite parameters
"""

from typing import Dict, List, Tuple, Optional
from config import THRESHOLDS, ALERT_LEVELS, ALERT_EMOJI, thresholds

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Score convettivo multi-parametro
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def convective_score(params: Dict[str, float]) -> int:
    """
    Score multi-parametro convettivo (0–12+).
    Combina CAPE (SB/MU/ML), shear, SRH, PWAT, CIN, TT, K-Index,
    EHI, SCP, lapse rates e fattori orografici Spezzino.
    Maggiore punteggio = maggiore rischio convettivo.
    """
    score = 0

    # \u2014 CAPE \u2013 usa il massimo tra SB, MU, ML
    cape_sb = params.get("SBCAPE", params.get("CAPE", 0))
    cape_mu = params.get("MUCAPE", cape_sb)
    cape_ml = params.get("MLCAPE", cape_sb)
    cape = max(cape_sb, cape_mu, cape_ml)

    if cape >= thresholds.SBCAPE_EXTREME:
        score += 4
    elif cape >= thresholds.SBCAPE_STRONG:
        score += 3
    elif cape >= thresholds.SBCAPE_MODERATE:
        score += 2
    elif cape >= thresholds.SBCAPE_WEAK:
        score += 1

    # \u2014 Shear 0-6 km
    shear = params.get("shear_0_6", 0)
    if shear >= thresholds.SHEAR_06_EXTREME:
        score += 3
    elif shear >= thresholds.SHEAR_06_SUPERCELL:
        score += 2
    elif shear >= thresholds.SHEAR_06_ORGANIZED:
        score += 1

    # \u2014 SRH 0-3 km (più significativo del 0-1 per il sistema Liguria)
    srh = max(
        params.get("srh_0_3", 0),
        params.get("srh_0_1", 0) * 1.5,  # normalizza al 0-3
    )
    if srh >= thresholds.SRH_03_HIGH:
        score += 2
    elif srh >= thresholds.SRH_03_MODERATE:
        score += 1

    # \u2014 PWAT
    pwat = params.get("PWAT", 0)
    if pwat >= thresholds.PWAT_EXTREME:
        score += 2
    elif pwat >= thresholds.PWAT_HUMID:
        score += 1

    # \u2014 CIN (riduce lo score)
    cin = abs(params.get("CIN", params.get("SBCIN", 0)))
    if cin >= abs(thresholds.CIN_STRONG):
        score -= 2
    elif cin >= abs(thresholds.CIN_MODERATE):
        score -= 1

    # \u2014 Totals-Totals
    tt = params.get("TT", None)
    if tt is not None:
        if tt >= thresholds.TT_EXTREME:
            score += 2
        elif tt >= thresholds.TT_STRONG:
            score += 1

    # \u2014 K-Index
    ki = params.get("KI", None)
    if ki is not None:
        if ki >= thresholds.KI_EXTREME:
            score += 1
        elif ki >= thresholds.KI_STRONG:
            score += 1

    # \u2014 EHI (se disponibile)
    ehi = params.get("EHI", None)
    if ehi is not None:
        if ehi >= thresholds.EHI_EXTREME:
            score += 2
        elif ehi >= thresholds.EHI_HIGH:
            score += 1

    # \u2014 SCP (Supercell Composite)
    scp = params.get("SCP", None)
    if scp is not None and scp >= thresholds.SCP_HIGH:
        score += 2
    elif scp is not None and scp >= thresholds.SCP_MODERATE:
        score += 1

    # \u2014 Lapse rate 0-3 km > 8 K/km = molto instabile
    lr = params.get("lr_0_3km", None)
    if lr is not None and lr >= 8.0:
        score += 1

    # \u2014 Amplificazione orografica Appennino Ligure
    oro = params.get("orographic_factor", 0.0)
    if oro >= 0.7:
        score += 2
    elif oro >= 0.4:
        score += 1

    # \u2014 Convergenza brezza marina (rischio innesco pomeridiano)
    sea_conv = params.get("sea_breeze_convergence", 0.0)
    if sea_conv >= 0.6:
        score += 1

    return max(score, 0)


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Classificazione modalità convettiva
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def classify_storm_mode(params: Dict[str, float]) -> str:
    """
    Classifica la modalità convettiva attesa in base a CAPE, shear, SRH, SCP, STP.
    """
    cape   = max(params.get("SBCAPE", params.get("CAPE", 0)),
                 params.get("MUCAPE", 0))
    shear  = params.get("shear_0_6", 0)
    srh    = params.get("srh_0_3", params.get("srh_0_1", 0))
    scp    = params.get("SCP",  0) or 0
    stp    = params.get("STP",  0) or 0
    pwat   = params.get("PWAT", 0) or 0
    oro    = params.get("orographic_factor", 0.0) or 0.0

    if cape < thresholds.SBCAPE_WEAK:
        if pwat >= thresholds.PWAT_HUMID:
            return "precipitazioni stratiforme con debole convezione embedded"
        return "attività convettiva assente o molto debole"

    if stp >= thresholds.STP_VIOLENT:
        return "supercella intensa con rischio tornado significativo"
    if scp >= thresholds.SCP_HIGH and srh >= thresholds.SRH_03_HIGH:
        return "supercelle probabili – ambiente fortemente rotante"
    if scp >= thresholds.SCP_MODERATE:
        return "supercella isolata possibile"
    if shear >= thresholds.SHEAR_06_SUPERCELL and srh >= thresholds.SRH_03_MODERATE:
        return "multicelle organizzate con possibile supercella"
    if shear >= thresholds.SHEAR_06_ORGANIZED:
        if oro >= 0.5:
            return "multicelle organizzate con forte forzante orografico (Appennino Ligure)"
        return "multicelle organizzate – cluster temporalesco (MCS probabile)"
    if oro >= 0.5:
        return "temporali orografici su Appennino Ligure – rischio accumuli rapidi"
    if cape >= thresholds.SBCAPE_STRONG:
        return "temporali isolati forti – celle singole dominanti"
    return "temporali sparsi di calore – bassa organizzazione"


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Hazard mapping completo
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def severe_hazards(params: Dict[str, float]) -> List[str]:
    """
    Determina tutti i fenomeni severi possibili in base alle combinazioni
    di parametri. Lista ordinata per pericolosità decrescente.
    """
    hazards: List[str] = []

    cape   = max(params.get("SBCAPE", params.get("CAPE", 0)),
                 params.get("MUCAPE", 0))
    shear  = params.get("shear_0_6", 0)
    shear1 = params.get("shear_0_1", 0)
    srh1   = params.get("srh_0_1", 0)
    srh3   = params.get("srh_0_3", 0)
    pwat   = params.get("PWAT", 0)
    li     = params.get("LI", 0) or 0
    cin    = params.get("CIN", params.get("SBCIN", 0)) or 0
    precip = params.get("precip_rate_mm_h", 0)
    wind   = params.get("wind_gust_kmh", 0)
    stp    = params.get("STP",  0) or 0
    scp    = params.get("SCP",  0) or 0
    ehi    = params.get("EHI",  0) or 0
    oro    = params.get("orographic_factor", 0.0) or 0.0
    lr03   = params.get("lr_0_3km", 0) or 0
    p_sfc  = params.get("pressure_hpa", 1013)
    temp   = params.get("temp_c", None)

    # \u2500\u2500 Fenomeni ad alto impatto \u2500\u2500

    # Tornado / trombe d'aria
    if stp >= thresholds.STP_VIOLENT:
        hazards.append("RISCHIO TORNADO SIGNIFICATIVO – condizioni supercellulari intense")
    elif stp >= thresholds.STP_HIGH:
        hazards.append("trombe d'aria probabili – STP elevato")
    elif (srh1 >= thresholds.SRH_01_HIGH
          and shear1 >= thresholds.SHEAR_01_TORNADO
          and cape >= thresholds.SBCAPE_MODERATE):
        hazards.append("trombe d'aria possibili (SRH-01 e shear basso strato critici)")

    # Grandine di grandi dimensioni (WMO: >2 cm)
    if cape >= 2500 and shear >= thresholds.SHEAR_06_SUPERCELL and lr03 >= 8.0:
        hazards.append("grandine di grandi dimensioni (>2 cm) – alta probabilità")
    elif cape >= 1500 and shear >= thresholds.SHEAR_06_ORGANIZED:
        hazards.append("grandine di dimensioni significative (1–2 cm)")

    # Raffiche severe e downburst
    if shear >= thresholds.SHEAR_06_SUPERCELL and cape >= thresholds.SBCAPE_MODERATE:
        hazards.append("raffiche severe (>90 km/h) e possibili microburst/downburst")
    elif wind >= thresholds.ARPAL_WIND_ARANCIONE or shear >= thresholds.SHEAR_06_ORGANIZED:
        hazards.append("raffiche di vento intense – possibili downburst")

    # Allagamenti rapidi / flash flood (rischio tipico del Levante Ligure)
    if pwat >= thresholds.PWAT_HUMID and precip >= THRESHOLDS["PRECIP_INTENSE_MM_H"]:
        if oro >= 0.5:
            hazards.append("RISCHIO ALLAGAMENTI RAPIDI ELEVATO – forzante orografico + PWAT critico")
        else:
            hazards.append("rischio allagamenti rapidi e colate detritiche")
    elif pwat >= thresholds.PWAT_NORMAL and precip >= thresholds.ARPAL_RAIN_1H_ARANCIONE:
        hazards.append("piogge intense con rischio di allagamenti localizzati")

    # Piogge persistenti su suolo saturo (tipico autunno spezzino)
    rain_24 = params.get("rain_24h_mm", 0)
    if rain_24 >= thresholds.ARPAL_RAIN_24H_ARANCIONE:
        hazards.append("accumuli di pioggia critici nelle 24h – suolo saturo, rischio idrogeologico")

    # Attività elettrica intensa
    if cape >= thresholds.SBCAPE_MODERATE and pwat >= thresholds.PWAT_NORMAL:
        hazards.append("elevata attività elettrica (fulmini intensi e frequenti)")

    # Neve a quote basse (inverno / primavera)
    snow_level = params.get("snow_level_m", 2000)
    if snow_level is not None and snow_level <= thresholds.SNOW_LEVEL_COASTAL_M:
        if temp is not None and temp <= 2:
            hazards.append("neve a quote collinari / costiere possibile")

    # Nebbia marina / bassa visibilità
    rh = params.get("humidity_pct", 0)
    spread = params.get("temp_dewpoint_spread", 10)
    if rh >= thresholds.HUMIDITY_FOG and spread <= thresholds.TEMP_DEWPOINT_SPREAD_FOG:
        hazards.append("rischio nebbia densa – visibilità <200 m")

    # Mareggiata (Golfo della Spezia)
    wave_h = params.get("wave_height_m", 0)
    if wave_h >= thresholds.WAVE_HEIGHT_ROSSO:
        hazards.append("MAREGGIATA INTENSA – onde >4 m, rischio allagamento zone costiere")
    elif wave_h >= thresholds.WAVE_HEIGHT_ARANCIONE:
        hazards.append("mareggiata significativa – onde >2.5 m")
    elif wave_h >= thresholds.WAVE_HEIGHT_GIALLO:
        hazards.append("mare agitato – onde >1.5 m")

    # Ciclogenesi Ligure / Medicane
    if p_sfc is not None and p_sfc <= thresholds.MEDICANE_PRESSURE:
        hazards.append("CICLONE SUBTROPICALE (MEDICANE) – condizioni estreme")
    elif p_sfc is not None and p_sfc <= thresholds.CYCLOGENESIS_LIGURE:
        hazards.append("ciclogenesi sul Golfo Ligure – venti e precipitazioni in forte aumento")

    # Libeccio/Scirocco forte (vento canalizzato in Valle del Magra)
    if wind >= thresholds.ARPAL_WIND_ROSSO:
        hazards.append("vento tempestoso (>90 km/h) – rischio danni strutturali")
    elif wind >= thresholds.ARPAL_WIND_ARANCIONE:
        hazards.append("vento forte (>60 km/h) – possibili danni a vegetazione e strutture")

    # Calore estremo
    heat_idx = params.get("heat_index", None)
    if heat_idx is not None and heat_idx >= thresholds.HEAT_INDEX_EXTREME:
        hazards.append("emergenza calore – stress termico estremo")
    elif heat_idx is not None and heat_idx >= thresholds.HEAT_INDEX_DANGER:
        hazards.append("caldo pericoloso – rischio colpo di calore")

    return hazards


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Sistema allerte ARPAL (Verde / Gialla / Arancione / Rossa)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def arpal_alert_rain(
    rain_1h: float = 0,
    rain_3h: float = 0,
    rain_6h: float = 0,
    rain_12h: float = 0,
    rain_24h: float = 0,
) -> str:
    """Livello allerta ARPAL per precipitazioni (Zona A/B Levante Ligure)."""
    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_ROSSO
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_ROSSO
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_ROSSO
     or rain_12h >= thresholds.ARPAL_RAIN_12H_ROSSO
     or rain_24h >= thresholds.ARPAL_RAIN_24H_ROSSO):
        return "rossa"
    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_ARANCIONE
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_ARANCIONE
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_ARANCIONE
     or rain_12h >= thresholds.ARPAL_RAIN_12H_ARANCIONE
     or rain_24h >= thresholds.ARPAL_RAIN_24H_ARANCIONE):
        return "arancione"
    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_GIALLO
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_GIALLO
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_GIALLO
     or rain_12h >= thresholds.ARPAL_RAIN_12H_GIALLO
     or rain_24h >= thresholds.ARPAL_RAIN_24H_GIALLO):
        return "gialla"
    return "verde"


def arpal_alert_wind(wind_kmh: float, coastal: bool = True) -> str:
    """Livello allerta ARPAL per vento."""
    lim_r = thresholds.ARPAL_WIND_COAST_ROSSO    if coastal else thresholds.ARPAL_WIND_INLAND_ROSSO
    lim_a = thresholds.ARPAL_WIND_COAST_ARANCIONE if coastal else thresholds.ARPAL_WIND_INLAND_ARANCIONE
    lim_g = thresholds.ARPAL_WIND_COAST_GIALLO    if coastal else thresholds.ARPAL_WIND_INLAND_GIALLO
    if wind_kmh >= lim_r:
        return "rossa"
    if wind_kmh >= lim_a:
        return "arancione"
    if wind_kmh >= lim_g:
        return "gialla"
    return "verde"


def arpal_alert_temperature(temp_c: float) -> str:
    """Livello allerta ARPAL per caldo / freddo."""
    if temp_c >= thresholds.ARPAL_HEAT_ROSSO or temp_c <= thresholds.ARPAL_FROST_ROSSO:
        return "rossa"
    if temp_c >= thresholds.ARPAL_HEAT_ARANCIONE or temp_c <= thresholds.ARPAL_FROST_ARANCIONE:
        return "arancione"
    if temp_c >= thresholds.ARPAL_HEAT_GIALLO or temp_c <= thresholds.ARPAL_FROST_GIALLO:
        return "gialla"
    return "verde"


def arpal_alert_snow(snow_cm: float) -> str:
    """Livello allerta ARPAL per neve (quota 0-200 m)."""
    if snow_cm >= thresholds.ARPAL_SNOW_ROSSO:     return "rossa"
    if snow_cm >= thresholds.ARPAL_SNOW_ARANCIONE: return "arancione"
    if snow_cm >= thresholds.ARPAL_SNOW_GIALLO:    return "gialla"
    return "verde"


def composite_arpal_alert(
    rain_1h: float = 0,
    rain_3h: float = 0,
    rain_6h: float = 0,
    rain_12h: float = 0,
    rain_24h: float = 0,
    wind_kmh: float = 0,
    temp_c: Optional[float] = None,
    snow_cm: float = 0,
    wave_height_m: float = 0,
    coastal: bool = True,
) -> Tuple[str, Dict[str, str]]:
    """
    Calcola il livello allerta composito (il massimo tra tutti i rischi)
    e ritorna (livello_max, dict con dettaglio per rischio).
    """
    detail: Dict[str, str] = {
        "pioggia": arpal_alert_rain(rain_1h, rain_3h, rain_6h, rain_12h, rain_24h),
        "vento":   arpal_alert_wind(wind_kmh, coastal),
    }
    if temp_c is not None:
        detail["temperatura"] = arpal_alert_temperature(temp_c)
    if snow_cm > 0:
        detail["neve"] = arpal_alert_snow(snow_cm)
    if wave_height_m >= thresholds.WAVE_HEIGHT_GIALLO:
        if wave_height_m >= thresholds.WAVE_HEIGHT_ROSSO:
            detail["mare"] = "rossa"
        elif wave_height_m >= thresholds.WAVE_HEIGHT_ARANCIONE:
            detail["mare"] = "arancione"
        else:
            detail["mare"] = "gialla"

    order = ["rossa", "arancione", "gialla", "verde"]
    for lvl in order:
        if any(v == lvl for v in detail.values()):
            return lvl, detail
    return "verde", detail


def map_score_to_alert(score: int) -> str:
    """
    Mappa score convettivo → livello allerta ARPAL.
    Calibrato su Liguria / Levante.
    """
    mapping = THRESHOLDS["SCORE_TO_ALERT"]
    keys = sorted(mapping.keys())
    selected = "verde"
    for k in keys:
        if score >= k:
            selected = mapping[k]
    return selected


def full_alert(
    params: Dict[str, float],
    score: int,
    rain_obs: Optional[Dict[str, float]] = None,
) -> Tuple[str, str]:
    """
    Allerta finale integrando score convettivo + allerte ARPAL per pioggia/vento.
    Ritorna (livello_stringa, emoji).
    """
    convective_level = map_score_to_alert(score)
    rain = rain_obs or {}
    arpal_level, _ = composite_arpal_alert(
        rain_1h=rain.get("1h", 0),
        rain_3h=rain.get("3h", 0),
        rain_6h=rain.get("6h", 0),
        rain_12h=rain.get("12h", 0),
        rain_24h=rain.get("24h", 0),
        wind_kmh=params.get("wind_gust_kmh", 0),
        temp_c=params.get("temp_c"),
        wave_height_m=params.get("wave_height_m", 0),
    )
    order = {"verde": 0, "gialla": 1, "arancione": 2, "rossa": 3}
    final = max(convective_level, arpal_level, key=lambda x: order.get(x, 0))
    return final, ALERT_EMOJI.get(final, "⚪")


# ─────────────────────────────────────────────────────────────────────────────
# Score maltempo e Livello di Attenzione
# Riferimenti: ARPAL Liguria, WMO Severe Weather Guidance
# ─────────────────────────────────────────────────────────────────────────────

def maltempo_score(
    params: Dict[str, float],
    rain_obs: Optional[Dict[str, float]] = None,
) -> float:
    """
    Score maltempo multi-categoria (0–5), cap a 5.

    Cinque categorie, ognuna contribuisce max 1.5:
      Pioggia/alluvioni | Temporali/convezione | Vento | Caldo | Afa
    Scala di ogni categoria:
      0.5 = media probabilità di impatto (attenzione)
      1.0 = alta probabilità con possibili danni a persone o strutture
      1.5 = probabilità molto alta con danni probabili a strutture o persone
    """
    rain = rain_obs or {}
    score = 0.0

    # ── 1. Pioggia / Alluvioni (ARPAL Zona A/B – Levante Ligure) ─────────
    rain_1h  = max(float(rain.get("1h",  0) or 0),
                   float(params.get("precip_rate_mm_h", 0) or 0))
    rain_3h  = float(rain.get("3h",  0) or 0)
    rain_6h  = float(rain.get("6h",  0) or 0)
    rain_24h = float(rain.get("24h", params.get("rain_24h_mm", 0)) or 0)

    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_ROSSO
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_ROSSO
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_ROSSO
     or rain_24h >= thresholds.ARPAL_RAIN_24H_ROSSO):
        score += 1.5
    elif (rain_1h  >= thresholds.ARPAL_RAIN_1H_ARANCIONE
       or rain_3h  >= thresholds.ARPAL_RAIN_3H_ARANCIONE
       or rain_6h  >= thresholds.ARPAL_RAIN_6H_ARANCIONE
       or rain_24h >= thresholds.ARPAL_RAIN_24H_ARANCIONE):
        score += 1.0
    elif (rain_1h  >= thresholds.ARPAL_RAIN_1H_GIALLO
       or rain_3h  >= thresholds.ARPAL_RAIN_3H_GIALLO
       or rain_6h  >= thresholds.ARPAL_RAIN_6H_GIALLO
       or rain_24h >= thresholds.ARPAL_RAIN_24H_GIALLO):
        score += 0.5

    # ── 2. Temporali / Convezione ─────────────────────────────────────────
    cape = max(
        float(params.get("SBCAPE", params.get("CAPE", 0)) or 0),
        float(params.get("MUCAPE", 0) or 0),
    )
    wmo = int(params.get("wmo_code", 0) or 0)
    scp = float(params.get("SCP", 0) or 0)
    li  = params.get("LI")
    li_f = float(li) if li is not None else 0.0

    if cape >= thresholds.SBCAPE_EXTREME or scp >= thresholds.SCP_HIGH or wmo == 99:
        score += 1.5
    elif (cape >= thresholds.SBCAPE_STRONG or scp >= thresholds.SCP_MODERATE
          or wmo in (95, 96) or li_f <= thresholds.LI_VERY_UNSTABLE):
        score += 1.0
    elif (cape >= thresholds.SBCAPE_MODERATE or wmo in (80, 81, 82, 91, 92)
          or li_f <= thresholds.LI_UNSTABLE):
        score += 0.5

    # ── 3. Vento (costa spezzina) ─────────────────────────────────────────
    wind = float(params.get("wind_gust_kmh", 0) or 0)

    if wind >= thresholds.ARPAL_WIND_COAST_ROSSO:
        score += 1.5
    elif wind >= thresholds.ARPAL_WIND_COAST_ARANCIONE:
        score += 1.0
    elif wind >= thresholds.ARPAL_WIND_COAST_GIALLO:
        score += 0.5

    # ── 4. Caldo estremo ──────────────────────────────────────────────────
    temp = params.get("temp_c")
    temp_f = float(temp) if temp is not None else None

    if temp_f is not None:
        if temp_f >= thresholds.ARPAL_HEAT_ROSSO:
            score += 1.5
        elif temp_f >= thresholds.ARPAL_HEAT_ARANCIONE:
            score += 1.0
        elif temp_f >= thresholds.ARPAL_HEAT_GIALLO:
            score += 0.5

    # ── 5. Afa (disagio termico da caldo + umidità) ────────────────────────
    app_temp = params.get("heat_index") or params.get("apparent_temperature")
    if app_temp is not None:
        app_f = float(app_temp)
        t_base = temp_f if temp_f is not None else 0.0
        # Disagio aggiuntivo oltre alla temperatura reale
        disagio = app_f - t_base
        if app_f >= thresholds.HEAT_INDEX_EXTREME or disagio >= 6:
            score += 1.5
        elif app_f >= thresholds.HEAT_INDEX_DANGER or disagio >= 4:
            score += 1.0
        elif app_f >= thresholds.HEAT_INDEX_WARNING or disagio >= 2:
            score += 0.5

    return round(min(score, 5.0), 1)


def livello_attenzione(score: float) -> Tuple[str, str]:
    """
    Converte lo score maltempo (0–5+) in livello di attenzione.
    BASSO <1 | MODERATO 1–2.5 | ALTO 2.5–4 | MOLTO ALTO 4–5 | NON CLASSIFICABILE >5
    Ritorna (etichetta, emoji).
    """
    if score > 5.0:
        return "NON CLASSIFICABILE", "⛔"
    if score >= 4.0:
        return "MOLTO ALTO", "🔴"
    if score > 2.5:
        return "ALTO", "🟠"
    if score >= 1.0:
        return "MODERATO", "🟡"
    return "BASSO", "🟢"

