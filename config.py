"""
Centralized configuration for MeteoBot – Stazione Meteorologica La Spezia.
Soglie basate su:
  – ARPAL Liguria (Direttiva Allertamento 2020, Zone A/B/C/D/E)
  – WMO Guide to Meteorological Instruments and Methods of Observation (2021)
  – DPC (Dipartimento Protezione Civile) – Indicatori e soglie allerta
Tutte le variabili d'ambiente sono centralizzate qui.
"""
import os
import json as _json
from typing import List, Dict
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
# Helpers environment
# ─────────────────────────────────────────────────────────────────────────────

def get_env_required(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise ValueError(
            f"Missing required environment variable: {key}\n"
            f"Please set it in your GitHub repository secrets."
        )
    return value

def get_env_optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def get_chat_ids() -> List[str]:
    raw = os.environ.get("TELEGRAM_CHAT_IDS", "")
    return [c.strip() for c in raw.split(",") if c.strip()]

# ─────────────────────────────────────────────────────────────────────────────
# Credenziali (da GitHub Secrets / env vars)
# ─────────────────────────────────────────────────────────────────────────────

TUYA_ACCESS_ID     = get_env_optional("TUYA_ACCESS_ID")
TUYA_ACCESS_SECRET = get_env_optional("TUYA_ACCESS_SECRET")
TUYA_DEVICE_ID     = get_env_optional("TUYA_DEVICE_ID")
TUYA_ENDPOINT      = get_env_optional("TUYA_ENDPOINT", "https://openapi.tuyaeu.com")

ECOWITT_APPLICATION_KEY = get_env_optional("ECOWITT_APPLICATION_KEY")
ECOWITT_API_KEY         = get_env_optional("ECOWITT_API_KEY")
ECOWITT_MAC             = get_env_optional("ECOWITT_MAC")

TELEGRAM_TOKEN    = get_env_optional("TELEGRAM_TOKEN")
TELEGRAM_CHAT_IDS = get_chat_ids()
GEMINI_API_KEY    = get_env_optional("GEMINI_API_KEY")

# ─────────────────────────────────────────────────────────────────────────────
# Posizione – Stazione La Spezia / Foce (WGS84) gg
# ─────────────────────────────────────────────────────────────────────────────

LATITUDE  = 44.12514
LONGITUDE = 9.79706
ELEVATION = 95        # m s.l.m. – zona costiera Foce
TIMEZONE  = "Europe/Rome"

# Parametri orografici specifici per il territorio spezzino
# (Appennino Ligure, golfo del Tigullio, Valle del Magra, Riviera di Levante)
ORO_ENHANCEMENT_FACTOR = 1.40
AROME_PI_FORECAST_QUARTERS = 24
COASTAL_SEA_BREEZE_SPEED = 15.0 # km/h – brezza tipica pomeridiana
COASTAL_CONVERGENCE_ZONE = True # zona di convergenza brezza/flusso sinottico
VALLE_MAGRA_FUNNELING  = 1.25   # amplificazione vento in valle per canalizzazione
SEA_SST_SUMMER_AVG     = 23.0   # °C – temperatura media superficiale mare estate
SEA_SST_AUTUMN_AVG     = 19.0   # °C – estate di S. Martino, instabilità mar-tirrenica

# ─────────────────────────────────────────────────────────────────────────────
# Calibrazioni pioggia
# ─────────────────────────────────────────────────────────────────────────────

TUYA_RAIN_CALIBRATION        = 1.0
TUYA_RAIN_RATE_CALIBRATION   = 1.0
ECOWITT_RAIN_CALIBRATION     = 1.0
ECOWITT_RAIN_RATE_CALIBRATION = 1.0

# ─────────────────────────────────────────────────────────────────────────────
# File di stato
# ─────────────────────────────────────────────────────────────────────────────

METEO_SCRIPT = "meteo"
FILE_STATE   = "state.json"
FILE_STORICO = "storico_24h.json"

# ─────────────────────────────────────────────────────────────────────────────
# Stato persistente (state.json unificato)
# ─────────────────────────────────────────────────────────────────────────────

def load_state_section(section: str) -> dict:
    if not os.path.exists(FILE_STATE):
        return {}
    try:
        with open(FILE_STATE, "r") as f:
            data = _json.load(f)
        return data.get(section, {})
    except Exception:
        return {}

def save_state_section(section: str, value: dict):
    data: dict = {}
    if os.path.exists(FILE_STATE):
        try:
            with open(FILE_STATE, "r") as f:
                data = _json.load(f)
        except Exception:
            data = {}
    data[section] = value
    with open(FILE_STATE, "w") as f:
        _json.dump(data, f, indent=4, ensure_ascii=False)

# ─────────────────────────────────────────────────────────────────────────────
# Soglie ARPAL + WMO – Classe Thresholds (dataclass)
# Riferimenti:
#   ARPAL Liguria – Valori soglia per l'emissione dell'avviso meteorologico
#   WMO No.49 – Technical Regulations, Vol. II (Meteorological Service for
#               International Air Navigation), 2018 update
#   DPC Allegato A – Indicatori e soglie allerta meteo-idrogeologica
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Thresholds:
    # ── Precipitazione oraria [mm/h] – ARPAL Zone A/B (Levante Ligure) ──────
    ARPAL_RAIN_1H_GIALLO:    float = 10.0   # WMO: heavy rain onset
    ARPAL_RAIN_1H_ARANCIONE: float = 30.0
    ARPAL_RAIN_1H_ROSSO:     float = 50.0   # WMO: extreme precipitation

    # ── Precipitazione 3h [mm] ───────────────────────────────────────────────
    ARPAL_RAIN_3H_GIALLO:    float = 30.0
    ARPAL_RAIN_3H_ARANCIONE: float = 60.0
    ARPAL_RAIN_3H_ROSSO:     float = 100.0

    # ── Precipitazione 6h [mm] ───────────────────────────────────────────────
    ARPAL_RAIN_6H_GIALLO:    float = 60.0
    ARPAL_RAIN_6H_ARANCIONE: float = 100.0
    ARPAL_RAIN_6H_ROSSO:     float = 150.0

    # ── Precipitazione 12h [mm] ──────────────────────────────────────────────
    ARPAL_RAIN_12H_GIALLO:    float = 80.0
    ARPAL_RAIN_12H_ARANCIONE: float = 150.0
    ARPAL_RAIN_12H_ROSSO:     float = 220.0

    # ── Precipitazione 24h [mm] ──────────────────────────────────────────────
    ARPAL_RAIN_24H_GIALLO:    float = 100.0
    ARPAL_RAIN_24H_ARANCIONE: float = 200.0
    ARPAL_RAIN_24H_ROSSO:     float = 300.0

    # ── Vento (km/h) – costa e entroterra ────────────────────────────────────
    ARPAL_WIND_COAST_GIALLO:    float = 40.0  # Beaufort 6
    ARPAL_WIND_COAST_ARANCIONE: float = 60.0  # Beaufort 7-8
    ARPAL_WIND_COAST_ROSSO:     float = 80.0  # Beaufort 9+
    ARPAL_WIND_INLAND_GIALLO:    float = 50.0
    ARPAL_WIND_INLAND_ARANCIONE: float = 70.0
    ARPAL_WIND_INLAND_ROSSO:     float = 90.0
    # Legacy (compatibilità)
    ARPAL_WIND_GIALLO:    float = 50.0
    ARPAL_WIND_ARANCIONE: float = 80.0
    ARPAL_WIND_ROSSO:     float = 100.0

    # ── Neve (cm) – quota 0-200 m ─────────────────────────────────────────────
    ARPAL_SNOW_GIALLO:    float = 5.0
    ARPAL_SNOW_ARANCIONE: float = 15.0
    ARPAL_SNOW_ROSSO:     float = 30.0
    SNOW_LEVEL_COASTAL_M: float = 400.0  # quota neve critica per zona costiera

    # ── Calore e siccità [°C] – WMO ──────────────────────────────────────────
    ARPAL_HEAT_GIALLO:    float = 35.0
    ARPAL_HEAT_ARANCIONE: float = 38.0
    ARPAL_HEAT_ROSSO:     float = 40.0
    HEAT_INDEX_WARNING:   float = 32.0   # WMO: significativo disagio
    HEAT_INDEX_DANGER:    float = 39.0   # WMO: pericoloso
    HEAT_INDEX_EXTREME:   float = 46.0   # WMO: emergenza calore

    # ── Freddo e ghiaccio ─────────────────────────────────────────────────────
    ARPAL_FROST_GIALLO:    float =  0.0
    ARPAL_FROST_ARANCIONE: float = -5.0
    ARPAL_FROST_ROSSO:     float = -10.0
    BLACK_ICE_TEMP:        float =  2.0  # rischio ghiaccio su strada

    # ── Pressione al suolo (hPa) – Medicane / Ciclogenesi Ligure ─────────────
    ARPAL_STORM_SURGE_GIALLO:    float = 998.0
    ARPAL_STORM_SURGE_ARANCIONE: float = 993.0
    ARPAL_STORM_SURGE_ROSSO:     float = 988.0
    CYCLOGENESIS_LIGURE:         float = 1005.0  # soglia ciclogenesi sul Golfo
    MEDICANE_PRESSURE:           float = 985.0

    # ── Mare e Costa (altezza onde significativa – m) ─────────────────────────
    WAVE_HEIGHT_GIALLO:    float = 1.5
    WAVE_HEIGHT_ARANCIONE: float = 2.5
    WAVE_HEIGHT_ROSSO:     float = 4.0
    STORM_SURGE_CM:        float = 50.0  # surge sopra media astronomica

    # ── Nebbia ────────────────────────────────────────────────────────────────
    HUMIDITY_FOG:            float = 98.0
    TEMP_DEWPOINT_SPREAD_FOG: float = 1.5   # T-Td ≤ 1.5°C → rischio nebbia
    VIS_FOG_M:               float = 200.0  # visibilità nebbia densa
    VIS_MIST_M:              float = 1000.0 # foschia

    # ── Indici convettivi – WMO / SPC ─────────────────────────────────────────
    # CAPE (J/kg)
    SBCAPE_WEAK:     float = 300.0
    SBCAPE_MODERATE: float = 800.0    # WMO: temporal organizzato possibile
    SBCAPE_STRONG:   float = 1500.0   # WMO: temporal severo
    SBCAPE_EXTREME:  float = 2500.0   # WMO: tornado/supercella
    MUCAPE_MODERATE: float = 500.0
    MUCAPE_STRONG:   float = 1500.0
    MLCAPE_MODERATE: float = 600.0

    # ── Lapse rate 0-3 km (K/km) – instabilità bassi strati ───────────────
    LAPSE_03_UNSTABLE:      float = 7.0
    LAPSE_03_VERY_UNSTABLE: float = 8.0
    LAPSE_03_EXTREME:       float = 9.0

    # ── Lapse rate 700-500 hPa (K/km) – instabilità media quota ────────────
    LAPSE_75_UNSTABLE:      float = 6.0
    LAPSE_75_VERY_UNSTABLE: float = 7.0

    # CIN (J/kg – valori negativi)
    CIN_WEAK:     float = -50.0    # leggera inibizione
    CIN_MODERATE: float = -100.0   # inibizione moderata
    CIN_STRONG:   float = -200.0   # forte inibizione (blocca convezione)

    # Shear bulk 0-6 km (kt)
    SHEAR_06_WEAK:      float = 15.0
    SHEAR_06_ORGANIZED: float = 20.0
    SHEAR_06_SUPERCELL: float = 35.0  # SPC: soglia supercella
    SHEAR_06_EXTREME:   float = 50.0

    # Shear bulk 0-1 km (kt) – basso strato per trombe
    SHEAR_01_MODERATE: float = 15.0
    SHEAR_01_TORNADO:  float = 25.0

    # SRH 0-3 km (m²/s²)
    SRH_03_LOW:      float = 150.0
    SRH_03_MODERATE: float = 300.0
    SRH_03_HIGH:     float = 500.0   # WMO: alto rischio rotazione

    # SRH 0-1 km (m²/s²) – effective layer
    SRH_01_CONCERN: float = 100.0
    SRH_01_HIGH:    float = 200.0

    # Lifted Index
    LI_UNSTABLE:      float = -3.0
    LI_VERY_UNSTABLE: float = -6.0
    LI_EXTREME:       float = -9.0

    # PWAT (mm)
    PWAT_DRY:     float = 15.0
    PWAT_NORMAL:  float = 25.0
    PWAT_HUMID:   float = 35.0   # Alta umidità atmosferica totale
    PWAT_EXTREME: float = 50.0   # Livello tropicale

    # LCL (m)
    LCL_LOW:      float = 500.0
    LCL_MODERATE: float = 1500.0
    LCL_HIGH:     float = 3000.0

    # Totals-Totals Index
    TT_MODERATE: float = 44.0
    TT_STRONG:   float = 50.0
    TT_EXTREME:  float = 55.0

    # K-Index
    KI_MODERATE: float = 25.0
    KI_STRONG:   float = 35.0
    KI_EXTREME:  float = 40.0

    # SWEAT Index
    SWEAT_MODERATE: float = 150.0
    SWEAT_STRONG:   float = 300.0

    # EHI (Energy-Helicity Index)
    EHI_MODERATE: float = 1.0
    EHI_HIGH:     float = 2.5
    EHI_EXTREME:  float = 5.0

    # Supercell Composite Parameter (SCP)
    SCP_MODERATE: float = 1.0
    SCP_HIGH:     float = 4.0

    # Significant Tornado Parameter (STP)
    STP_MODERATE: float = 0.5
    STP_HIGH:     float = 1.0
    STP_VIOLENT:  float = 3.0

    # ── Livelli di score convettivo ───────────────────────────────────────────
    SEVERE_SCORE_WARNING:   int = 3
    SEVERE_SCORE_ALERT:     int = 5
    SEVERE_SCORE_EMERGENCY: int = 8

    # ── Fulmini ───────────────────────────────────────────────────────────────
    LIGHTNING_RADIUS_KM:       float = 30.0
    LIGHTNING_STRIKE_THRESHOLD: int   = 1
    LIGHTNING_WINDOW_MINUTES:   int   = 30

    # ── Precipitazione rate significativa (compatibilità) ─────────────────────
    RAIN_SIGNIFICANT: float = 1.0
    RAIN_INTENSE:     float = 15.0
    RAIN_EXTREME:     float = 50.0

    # ── Vento generico (compatibilità) ────────────────────────────────────────
    WIND_STRONG:      float = 50.0
    WIND_VERY_STRONG: float = 80.0
    WIND_STORM:       float = 100.0

    # ── Temperatura ───────────────────────────────────────────────────────────
    TEMP_FREEZING:       float = 0.0
    TEMP_HOT:            float = 35.0
    TEMP_VERY_HOT:       float = 40.0

    # ── Pressione tendenza ────────────────────────────────────────────────────
    PRESSURE_FALLING:       float = -1.0
    PRESSURE_RISING:        float =  1.0
    PRESSURE_STRONG_CHANGE: float =  3.0

    # ── Suolo saturo ──────────────────────────────────────────────────────────
    SOIL_VERY_SATURATED: float = 185.0

    # ── DCAPE – energia disponibile per downburst (J/kg) ─────────────────────
    # V_max = √(2·DCAPE): 100→45km/h, 500→114km/h, 1000→161km/h
    DCAPE_LOW:      float = 100.0    # basso rischio raffiche discendenti
    DCAPE_MODERATE: float = 500.0    # raffiche fino a ~115 km/h
    DCAPE_HIGH:     float = 1000.0   # raffiche severe >140 km/h

    # ── Flash Flood Guidance (FFG) – WMO + ARPAL Levante Ligure ─────────────
    # Soil moisture: m³/m³ (Open-Meteo ERA5-Land 0-10cm)
    SOIL_MOISTURE_FIELD_CAP: float = 0.30   # capacità di campo tipica Liguria
    SOIL_MOISTURE_SATURATION: float = 0.42  # saturazione
    # Precipitazione totale 48h precedenti che precondiciona il suolo
    PRECIP_48H_PRESAT:  float = 60.0    # mm → suolo parzialmente saturo
    PRECIP_48H_SAT:     float = 120.0   # mm → suolo saturo
    # FFG rate critico (ARPAL Zone A/B): pioggia che scatena allagamento
    FFG_RATE_MODERATE:  float = 20.0    # mm/h su suolo saturo = alluvione lampo
    FFG_RATE_HIGH:      float = 35.0    # mm/h critico anche su suolo asciutto

    # ── Ondata di calore – WMO / ARPAL Liguria ───────────────────────────────
    # WMO: ondata di calore = ≥3 giorni consecutivi con Tmax ≥ percentile 90°
    # ARPAL Liguria: Tmax ≥ 35°C (costa), Tmin ≥ 25°C (notti tropicali)
    HEATWAVE_TMAX:         float = 35.0   # °C – soglia giornaliera Tmax
    HEATWAVE_TMIN:         float = 25.0   # °C – notte tropicale
    HEATWAVE_DAYS_MIN:     int   = 3      # giorni consecutivi minimi
    HEATWAVE_EHF_MODERATE: float = 1.0    # Excess Heat Factor moderato
    HEATWAVE_EHF_HIGH:     float = 3.0    # EHF alto (emergenza)

    # ── UWYO sounding (radiosondaggio) ────────────────────────────────────────
    UWYO_STATION_PRIMARY:   str = "16080"   # Milano Linate (WMO 16080)
    UWYO_STATION_SECONDARY: str = "16090"   # Cuneo/Levaldigi (WMO 16090)
    UWYO_MAX_AGE_HOURS:     int = 13        # radiosondaggio valido per max 13h

thresholds = Thresholds()

# ─────────────────────────────────────────────────────────────────────────────
# API esterne
# ─────────────────────────────────────────────────────────────────────────────

RAINVIEWER_API      = "https://api.rainviewer.com/public/weather-maps.json"
RAINVIEWER_TILE_URL = "https://tilecache.rainviewer.com/v2/radar/{ts}/512/{z}/{x}/{y}/2/1_1.png"

BLITZORTUNG_WS_URLS = [
    "wss://ws1.blitzortung.org/",
    "wss://ws7.blitzortung.org/",
    "wss://ws8.blitzortung.org/",
    "wss://ws2.blitzortung.org/",
]
BLITZORTUNG_REGION = 1   # Europa

LIGHTNINGMAPS_URL = (
    f"https://www.lightningmaps.org/"
    f"?lang=it#m=oss;t=3;s=0;o=0;b=;ts=0;z=10;"
    f"y={LATITUDE};x={LONGITUDE};d=2;dl=2;dc=0;"
)

# Open-Meteo (API libera, no chiave)
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HISTORICAL = "https://archive-api.open-meteo.com/v1/archive"

# ─────────────────────────────────────────────────────────────────────────────
# Orizzonti nominali dei modelli NWP (ore) — servono per capire quanto è
# "vecchia" la run scaricata (vedi io_ingest.check_model_freshness)
# ─────────────────────────────────────────────────────────────────────────────
MODEL_HORIZONS_HOURS: Dict[str, int] = {
    "meteofrance_arome_france_hd": 51,
    "meteofrance_arome_france":    48,
    "icon_eu":                     120,
}
MAX_RUN_AGE_H: int = 12   # oltre questa età (ore) la run è considerata obsoleta

# ─────────────────────────────────────────────────────────────────────────────
# Livelli allerta (per logic.py e templates.py)
# ─────────────────────────────────────────────────────────────────────────────

ALERT_LEVELS: Dict[str, int] = {
    "verde":    0,
    "gialla":   1,
    "arancione": 2,
    "rossa":    3,
}

ALERT_EMOJI: Dict[str, str] = {
    "verde":    "🟢",
    "gialla":   "🟡",
    "arancione": "🟠",
    "rossa":    "🔴",
}

# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLDS dict – compatibilità con engine.py / logic.py
# Basato su WMO Guide to Severe Weather Warnings (2018) + ARPAL Liguria
# ─────────────────────────────────────────────────────────────────────────────

THRESHOLDS: Dict = {
    # CAPE (J/kg) – WMO
    "CAPE": {
        "weak":     200,
        "marginal": 800,
        "moderate": 1500,
        "strong":   2500,
        "extreme":  3500,
    },
    # Bulk shear 0-6 km (kt) – SPC
    "SHEAR_0_6": {
        "weak":       10,
        "organized":  20,
        "supercell":  35,
        "extreme":    50,
    },
    # Bulk shear 0-1 km (kt)
    "SHEAR_0_1": {
        "moderate": 15,
        "tornado":  25,
    },
    # SRH 0-3 km (m²/s²) – WMO
    "SRH_0_3": {
        "low":      150,
        "moderate": 300,
        "high":     500,
    },
    # SRH 0-1 km (m²/s²)
    "SRH_0_1": {
        "low":     50,
        "concern": 100,
        "high":    200,
    },
    # PWAT (mm)
    "PWAT": {
        "dry":     15,
        "normal":  25,
        "humid":   35,
        "extreme": 50,
    },
    # Precipitazione intensa (mm/h) – ARPAL Zona A/B
    "PRECIP_INTENSE_MM_H": 30,
    # CIN (J/kg, valore assoluto)
    "CIN_STRONG": 200,
    # LCL (m)
    "LCL": {
        "low":      500,
        "moderate": 1500,
        "high":     3000,
    },
    # Totals-Totals
    "TT": {
        "moderate": 44,
        "strong":   50,
        "extreme":  55,
    },
    # K-Index
    "KI": {
        "moderate": 25,
        "strong":   35,
    },
    # Score → livello allerta (ARPAL-calibrated)
    "SCORE_TO_ALERT": {
        0: "verde",
        2: "gialla",
        4: "arancione",
        7: "rossa",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Climatologia INDICATIVA mensile T a 500 hPa e 850 hPa — Nord Italia / Mar Ligure
#
# ATTENZIONE: questi valori sono una stima approssimativa di riferimento (ordine
# di grandezza tipico per l'area, non un dataset ufficiale con verifica statistica
# fatta qui). NON hanno lo stesso status "certificato" delle soglie ARPAL/SPC usate
# altrove in questo file. Se hai accesso a una climatologia reale (es. serie storica
# radiosondaggi Milano Linate/LIML, o un archivio ERA5 interrogabile), sostituisci
# questi numeri con la media (e magari deviazione standard) calcolata sul periodo
# di riferimento che preferisci: la funzione che li usa (logic.py,
# upper_level_temperature_anomaly) non richiede altre modifiche.
# ─────────────────────────────────────────────────────────────────────────────

T500_CLIMATOLOGY_C: Dict[int, float] = {
    1: -21.0, 2: -20.0, 3: -18.0, 4: -14.5, 5: -10.5, 6: -7.5,
    7: -6.0,  8: -6.5,  9: -9.5,  10: -13.5, 11: -17.5, 12: -20.0,
}

T850_CLIMATOLOGY_C: Dict[int, float] = {
    1: 2.0,  2: 3.0,  3: 6.0,  4: 9.5,  5: 14.0, 6: 18.0,
    7: 20.5, 8: 20.5, 9: 17.0, 10: 12.5, 11: 7.0, 12: 3.0,
}

# Soglie di anomalia = scarto assoluto dalla climatologia del mese (°C).
# Seguono la prassi diagnostica comune in meteorologia sinottica per
# identificare avvezioni degne di nota rispetto alla norma stagionale;
# non sono una soglia WMO specifica per questo uso puntuale.
TEMP_ALOFT_ANOMALY_NOTABLE:     float = 6.0
TEMP_ALOFT_ANOMALY_SIGNIFICANT: float = 10.0
TEMP_ALOFT_ANOMALY_EXCEPTIONAL: float = 14.0
