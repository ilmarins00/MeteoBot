#!/usr/bin/env python3
import json
import sys
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    LATITUDE, LONGITUDE,
)

TZ_ROME = ZoneInfo("Europe/Rome")
LOCATION_NAME = "La Spezia"

# ----------------------------
# MODELLI
# ----------------------------

MODELS = [
    ("meteofrance_arome_france_hd", "AROME HD", 3),
    ("meteofrance_arome_france", "AROME", 3),
    ("icon_eu", "ICON-EU", 1),
]

FALLBACK_MODEL = "icon_eu"

DAILY_VARS = [
    "weather_code", "temperature_2m_max", "temperature_2m_min",
    "precipitation_sum", "wind_speed_10m_max", "wind_gusts_10m_max",
]

HOURLY_VARS = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_gusts_10m",
    "precipitation",
    "cloud_cover",
    "relative_humidity_2m",
    "pressure_msl",
]

# ----------------------------
# FETCH OPENMETEO
# ----------------------------

def fetch_openmeteo(start, end, model):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(HOURLY_VARS),
        "daily": ",".join(DAILY_VARS),
        "models": model,
        "start_date": start,
        "end_date": end,
        "timezone": "Europe/Rome",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def get_data():
    today = datetime.now(TZ_ROME).date()
    start = today.strftime("%Y-%m-%d")
    end = (today + timedelta(days=3)).strftime("%Y-%m-%d")

    for model, name, retries in MODELS:
        for _ in range(retries):
            try:
                data = fetch_openmeteo(start, end, model)
                return data, name
            except Exception:
                time.sleep(2)

    raise RuntimeError("No weather data")

# ----------------------------
# WEATHER BRIEF
# ----------------------------

def safe(arr, fn):
    vals = [v for v in arr if v is not None]
    return fn(vals) if vals else None

def build_brief(hourly):
    return {
        "tmin": safe(hourly["temperature_2m"], min),
        "tmax": safe(hourly["temperature_2m"], max),
        "wind": safe(hourly["wind_speed_10m"], max),
        "gusts": safe(hourly["wind_gusts_10m"], max),
        "rain": safe(hourly["precipitation"], max),
        "cloud": safe(hourly["cloud_cover"], max),
    }

# ----------------------------
# SEZIONE 1 - SEMPLICE
# ----------------------------

def simple_forecast(brief):
    text = (
        f"Previsioni per {LOCATION_NAME}. "
        f"Temperature tra {brief['tmin']:.1f} e {brief['tmax']:.1f} gradi. "
        f"Vento fino a {brief['wind']:.0f} km/h con raffiche fino a {brief['gusts']:.0f} km/h. "
    )

    if brief["rain"] and brief["rain"] > 0.1:
        text += f"Precipitazioni fino a {brief['rain']:.1f} mm orari. "

    text += "Evoluzione variabile nel corso della giornata con alternanza di nubi e schiarite."
    return text

# ----------------------------
# TECNICA (MINIMA MA COERENTE)
# ----------------------------

def technical(hourly):
    return (
        f"Pressione media attorno a {safe(hourly['pressure_msl'], lambda x: sum(x)/len(x)):.0f} hPa. "
        f"Vento massimo nei bassi strati fino a {safe(hourly['wind_speed_10m'], max):.0f} km/h. "
        f"Umidità su valori medi intorno al {safe(hourly['relative_humidity_2m'], lambda x: sum(x)/len(x)):.0f}%."
    )

# ----------------------------
# LRO (placeholder coerente col tuo sistema)
# ----------------------------

def lro_block():
    return (
        "[30/06/2026]\n"
        "❗️PUNTEGGIO: 1/5\n\n"
        "🌧Pioggia: 0/1.5\n"
        "🌩Temporali: 0/1.5\n"
        "🍃Vento: 0/1.5\n"
        "🔥Caldo: 0/1.5\n"
        "🥵Afa: 0/1.5\n\n\n\n\n"
    )

# ----------------------------
# RISCHI (SEMPLIFICATO)
# ----------------------------

def risk_section(brief):
    if brief["wind"] and brief["wind"] > 70:
        return "ARANCIONE\nVento intenso con possibili criticità locali."
    if brief["rain"] and brief["rain"] > 10:
        return "GIALLO\nPiogge localmente intense."
    return "VERDE\nNessun rischio significativo previsto."

# ----------------------------
# REPORT FINALE
# ----------------------------

def render(data):
    hourly = data["hourly"]
    brief = build_brief(hourly)

    simple = simple_forecast(brief)
    tech = technical(hourly)
    lro = lro_block()
    risk = risk_section(brief)

    return (
        simple +
        "\n\n---SEZIONE TECNICA---\n" + tech +
        "\n\n---SEZIONE INDICE---\n" + lro +
        "\n\n---SEZIONE RISCHI---\n" + risk
    )

# ----------------------------
# TELEGRAM
# ----------------------------

def send(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat in LISTA_CHAT:
        requests.post(url, data={"chat_id": chat, "text": text})

# ----------------------------
# MAIN
# ----------------------------

def main():
    print("PREVISIONI METEO – SYSTEM")

    data, model = get_data()

    print(f"Modello: {model}")

    report = render(data)

    print(report)

    send(report)

if __name__ == "__main__":
    main()