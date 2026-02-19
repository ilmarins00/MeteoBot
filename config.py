"""
Centralized configuration for Weather Station project.
All environment variables and constants in one place.
"""

import os
from typing import List
from dataclasses import dataclass

def get_env_required(key: str) -> str:
    """Get required environment variable or raise informative error."""
    value = os.environ.get(key)
    if not value:
        raise ValueError(
            f"Missing required environment variable: {key}\n"
            f"Please set it in your GitHub repository secrets."
        )
    return value


def get_env_optional(key: str, default: str = "") -> str:
    """Get optional environment variable, return default if not set."""
    return os.environ.get(key, default)

def get_chat_ids() -> List[str]:
    """Parse comma-separated Telegram chat IDs from environment."""
    raw = os.environ.get("TELEGRAM_CHAT_IDS", "")
    return [chat_id.strip() for chat_id in raw.split(",") if chat_id.strip()]

# Tuya API Configuration
TUYA_ACCESS_ID = get_env_optional("TUYA_ACCESS_ID")
TUYA_ACCESS_SECRET = get_env_optional("TUYA_ACCESS_SECRET")
TUYA_DEVICE_ID = get_env_optional("TUYA_DEVICE_ID")
TUYA_ENDPOINT = get_env_optional("TUYA_ENDPOINT", "https://openapi.tuyaeu.com")

# Telegram Configuration
TELEGRAM_TOKEN = get_env_optional("TELEGRAM_TOKEN")
TELEGRAM_CHAT_IDS = get_chat_ids()

# Location Configuration
LATITUDE = 44.124444
LONGITUDE = 9.798167
ELEVATION = 100  # meters above sea level
TIMEZONE = "Europe/Rome"

# File Paths
FILE_STORICO = "storico_24h.json"
FILE_MEMORIA = "meteo_memoria.json"
FILE_SBCAPE = "sbcape.json"
FILE_RAFFICA = "raffica.json"

@dataclass
class Thresholds:
    """Weather thresholds for alerts and notifications."""
    
    # Rainfall thresholds (mm/h) — trigger invio smart
    RAIN_SIGNIFICANT = 1.0
    RAIN_INTENSE = 15.0     # = soglia ARPAL Gialla 1h
    RAIN_EXTREME = 50.0     # = soglia ARPAL Rossa 1h
    
    # Wind thresholds (km/h) — trigger invio smart
    WIND_STRONG = 50.0      # = soglia ARPAL Gialla
    WIND_VERY_STRONG = 80.0 # = soglia ARPAL Arancione
    WIND_STORM = 100.0      # = soglia ARPAL Rossa
    
    # Temperature thresholds (°C) — trigger invio smart
    TEMP_FREEZING = 0.0     # = soglia ARPAL Gialla gelo
    TEMP_HOT = 35.0         # = soglia ARPAL Gialla calore
    TEMP_VERY_HOT = 40.0    # = soglia ARPAL Rossa calore
    
    # Pressure change thresholds (hPa/3h)
    PRESSURE_FALLING = -1.0
    PRESSURE_RISING = 1.0
    PRESSURE_STRONG_CHANGE = 3.0
    
    # Humidity thresholds (%)
    HUMIDITY_FOG = 99
    
    # Temperature-dewpoint spread for fog (°C)
    TEMP_DEWPOINT_SPREAD_FOG = 0.5
    
    # Convective indices thresholds
    SBCAPE_WEAK = 300.0
    SBCAPE_MODERATE = 800.0
    SBCAPE_STRONG = 1500.0
    SBCAPE_EXTREME = 2500.0
    
    MUCAPE_MODERATE = 500.0
    
    CIN_WEAK = -50.0  # Weak cap, easy triggering
    
    LIFTED_INDEX_UNSTABLE = -3.0
    LIFTED_INDEX_VERY_UNSTABLE = -6.0
    
    SEVERE_SCORE_WARNING = 3
    SEVERE_SCORE_ALERT = 5
    SEVERE_SCORE_EMERGENCY = 7
    
    # Soil saturation thresholds (mm)
    SOIL_VERY_SATURATED = 185.0

    # ── SOGLIE ARPAL Protezione Civile Liguria (Zona C – La Spezia) ──
    # Pioggia oraria (mm/h)  — riferimento: Bacini Piccoli
    ARPAL_RAIN_1H_GIALLO = 15.0      # Allerta Gialla
    ARPAL_RAIN_1H_ARANCIONE = 30.0   # Allerta Arancione
    ARPAL_RAIN_1H_ROSSO = 50.0       # Allerta Rossa

    # Pioggia cumulata 24h (mm) — riferimento: Bacini Grandi
    ARPAL_RAIN_24H_GIALLO = 80.0
    ARPAL_RAIN_24H_ARANCIONE = 150.0
    ARPAL_RAIN_24H_ROSSO = 250.0

    # Raffiche di vento (km/h)
    ARPAL_WIND_GIALLO = 50.0
    ARPAL_WIND_ARANCIONE = 80.0
    ARPAL_WIND_ROSSO = 100.0

    # Temperatura – ondata di calore (°C)
    ARPAL_HEAT_GIALLO = 35.0
    ARPAL_HEAT_ARANCIONE = 38.0
    ARPAL_HEAT_ROSSO = 40.0

    # Temperatura – gelo (°C)
    ARPAL_FROST_GIALLO = 0.0
    ARPAL_FROST_ARANCIONE = -5.0
    ARPAL_FROST_ROSSO = -10.0

    # Mareggiate – pressione indicativa MSL (hPa)
    ARPAL_STORM_SURGE_GIALLO = 998.0
    ARPAL_STORM_SURGE_ARANCIONE = 995.0
    ARPAL_STORM_SURGE_ROSSO = 990.0

    # Neve cumulata 24h (cm) — pianura costiera
    ARPAL_SNOW_GIALLO = 5.0
    ARPAL_SNOW_ARANCIONE = 15.0
    ARPAL_SNOW_ROSSO = 30.0

    # ── OMIRL – Soglia radar precipitazione (mm/h) ──
    OMIRL_RAIN_TRIGGER = 6.0   # Invia radar quando pioggia ≥ 6 mm/h in zona SP

    # ── Fulmini – Raggio e soglie ──
    LIGHTNING_RADIUS_KM = 20.0       # Cerchio di monitoraggio (km)
    LIGHTNING_STRIKE_THRESHOLD = 5   # Numero fulmini in 30 min per trigger
    LIGHTNING_WINDOW_MINUTES = 30    # Finestra temporale raccolta scariche

# Create singleton instance
thresholds = Thresholds()

# ── OMIRL API ──
OMIRL_API_BASE = "https://omirl.regione.liguria.it/Omirl/rest"
OMIRL_RAIN_ENDPOINT = f"{OMIRL_API_BASE}/stations/sensorvalues/Pluvio"
OMIRL_DISTRICT_FILTER = "SP"   # Distretto La Spezia

# ── RainViewer (radar composito) ──
RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"
RAINVIEWER_TILE_URL = "https://tilecache.rainviewer.com/v2/radar/{ts}/512/{z}/{x}/{y}/2/1_1.png"

# ── Blitzortung (fulmini via WebSocket) ──
BLITZORTUNG_WS_URLS = [
    "wss://ws1.blitzortung.org/",
    "wss://ws7.blitzortung.org/",
    "wss://ws8.blitzortung.org/",
]
BLITZORTUNG_REGION = 1   # Europa

# ── LightningMaps snapshot URL ──
LIGHTNINGMAPS_URL = (
    "https://www.lightningmaps.org/"
    "?lang=it#m=oss;t=3;s=0;o=0;b=;ts=0;z=9;"
    f"y={LATITUDE};x={LONGITUDE};d=2;dl=2;dc=0;"
)

# ── File di stato per i nuovi monitor ──
FILE_OMIRL_STATE = "omirl_state.json"
FILE_FULMINI_STATE = "fulmini_state.json"
