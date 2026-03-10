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
TUYA_ACCESS_ID = get_env_optional("TUYA_ACCESS_ID")
TUYA_ACCESS_SECRET = get_env_optional("TUYA_ACCESS_SECRET")
TUYA_DEVICE_ID = get_env_optional("TUYA_DEVICE_ID")
TUYA_ENDPOINT = get_env_optional("TUYA_ENDPOINT", "https://openapi.tuyaeu.com")
ECOWITT_APPLICATION_KEY = get_env_optional("ECOWITT_APPLICATION_KEY")
ECOWITT_API_KEY = get_env_optional("ECOWITT_API_KEY")
ECOWITT_MAC = get_env_optional("ECOWITT_MAC")
TELEGRAM_TOKEN = get_env_optional("TELEGRAM_TOKEN")
TELEGRAM_CHAT_IDS = get_chat_ids()
LATITUDE = 44.124444
LONGITUDE = 9.798167
ELEVATION = 100  
TIMEZONE = "Europe/Rome"
TUYA_RAIN_CALIBRATION = 1.0      
TUYA_RAIN_RATE_CALIBRATION = 1.0 
ECOWITT_RAIN_CALIBRATION = 1.0      
ECOWITT_RAIN_RATE_CALIBRATION = 1.0 
METEO_SCRIPT = "meteo"
FILE_STATE = "state.json"       
FILE_STORICO = "storico_24h.json"  
def load_state_section(section: str) -> dict:
    """Legge una sezione dal file di stato unificato state.json.
    Sezioni: 'meteo', 'sbcape', 'arpal', 'omirl', 'fulmini'.
    Restituisce un dict vuoto se la sezione non esiste.
    """
    import json as _json
    if not os.path.exists(FILE_STATE):
        return {}
    try:
        with open(FILE_STATE, "r") as f:
            data = _json.load(f)
        return data.get(section, {})
    except Exception:
        return {}
def save_state_section(section: str, value: dict):
    """Scrive una sezione nel file di stato unificato state.json.
    Le altre sezioni rimangono invariate.
    """
    import json as _json
    data = {}
    if os.path.exists(FILE_STATE):
        try:
            with open(FILE_STATE, "r") as f:
                data = _json.load(f)
        except Exception:
            data = {}
    data[section] = value
    with open(FILE_STATE, "w") as f:
        _json.dump(data, f, indent=4, ensure_ascii=False)
@dataclass
class Thresholds:
    """Weather thresholds for alerts and notifications."""
    RAIN_SIGNIFICANT = 1.0
    RAIN_INTENSE = 15.0     
    RAIN_EXTREME = 50.0     
    WIND_STRONG = 50.0      
    WIND_VERY_STRONG = 80.0 
    WIND_STORM = 100.0      
    TEMP_FREEZING = 0.0     
    TEMP_HOT = 35.0         
    TEMP_VERY_HOT = 40.0    
    PRESSURE_FALLING = -1.0
    PRESSURE_RISING = 1.0
    PRESSURE_STRONG_CHANGE = 3.0
    HUMIDITY_FOG = 99
    TEMP_DEWPOINT_SPREAD_FOG = 0.5
    SBCAPE_WEAK = 300.0
    SBCAPE_MODERATE = 800.0
    SBCAPE_STRONG = 1500.0
    SBCAPE_EXTREME = 2500.0
    MUCAPE_MODERATE = 500.0
    CIN_WEAK = -50.0  
    LIFTED_INDEX_UNSTABLE = -3.0
    LIFTED_INDEX_VERY_UNSTABLE = -6.0
    SEVERE_SCORE_WARNING = 3
    SEVERE_SCORE_ALERT = 5
    SEVERE_SCORE_EMERGENCY = 7
    SOIL_VERY_SATURATED = 185.0
    ARPAL_RAIN_1H_GIALLO = 15.0      
    ARPAL_RAIN_1H_ARANCIONE = 30.0   
    ARPAL_RAIN_1H_ROSSO = 50.0       
    ARPAL_RAIN_24H_GIALLO = 80.0
    ARPAL_RAIN_24H_ARANCIONE = 150.0
    ARPAL_RAIN_24H_ROSSO = 250.0
    ARPAL_WIND_GIALLO = 50.0
    ARPAL_WIND_ARANCIONE = 80.0
    ARPAL_WIND_ROSSO = 100.0
    ARPAL_HEAT_GIALLO = 35.0
    ARPAL_HEAT_ARANCIONE = 38.0
    ARPAL_HEAT_ROSSO = 40.0
    ARPAL_FROST_GIALLO = 0.0
    ARPAL_FROST_ARANCIONE = -5.0
    ARPAL_FROST_ROSSO = -10.0
    ARPAL_STORM_SURGE_GIALLO = 998.0
    ARPAL_STORM_SURGE_ARANCIONE = 995.0
    ARPAL_STORM_SURGE_ROSSO = 990.0
    ARPAL_SNOW_GIALLO = 5.0
    ARPAL_SNOW_ARANCIONE = 15.0
    ARPAL_SNOW_ROSSO = 30.0
    LIGHTNING_RADIUS_KM = 30.0       
    LIGHTNING_STRIKE_THRESHOLD = 1   
    LIGHTNING_WINDOW_MINUTES = 30    
thresholds = Thresholds()
RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"
RAINVIEWER_TILE_URL = "https://tilecache.rainviewer.com/v2/radar/{ts}/512/{z}/{x}/{y}/2/1_1.png"
BLITZORTUNG_WS_URLS = [
    "wss://ws1.blitzortung.org/",
    "wss://ws7.blitzortung.org/",
    "wss://ws8.blitzortung.org/",
]
BLITZORTUNG_REGION = 1   
LIGHTNINGMAPS_URL = (
    "https://www.lightningmaps.org/"
    "?lang=it#m=oss;t=3;s=0;o=0;b=;ts=0;z=9;"
    f"y={LATITUDE};x={LONGITUDE};d=2;dl=2;dc=0;"
)
