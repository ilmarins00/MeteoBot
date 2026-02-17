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
    
    # Rainfall thresholds (mm/h)
    RAIN_SIGNIFICANT = 1.0
    RAIN_INTENSE = 10.0
    RAIN_EXTREME = 50.0
    
    # Wind thresholds (km/h)
    WIND_STRONG = 30.0
    WIND_VERY_STRONG = 50.0
    WIND_STORM = 60.0
    
    # Temperature thresholds (°C)
    TEMP_FREEZING = 0.0
    TEMP_HOT = 35.0
    TEMP_VERY_HOT = 40.0
    
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

# Create singleton instance
thresholds = Thresholds()
