#!/usr/bin/env python3
"""
Previsioni Meteo – Generazione automatica con AI

Scarica dati meteo orari da Open-Meteo per il giorno successivo
(modello AROME, fallback ICON-EU) e li invia a Google Gemini
per generare previsioni in linguaggio naturale.

Uso:
    python previsioni.py          # Esecuzione standard (workflow manuale)
"""
import json
import sys
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    GEMINI_API_KEY,
    LATITUDE, LONGITUDE,
)

TZ_ROME = ZoneInfo("Europe/Rome")
LOCATION_NAME = "La Spezia"

GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


# ── Open-Meteo: variabili richieste ─────────────────────────────────────

HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "precipitation", "rain", "showers",
    "snowfall", "snow_depth", "weather_code", "pressure_msl",
    "surface_pressure", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "visibility",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "uv_index", "cape", "sunshine_duration",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "freezing_level_height", "vapour_pressure_deficit", "is_day",
]

HOURLY_VARS_CORE = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "precipitation", "rain", "snowfall",
    "weather_code", "pressure_msl", "cloud_cover",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "is_day",
]

DAILY_VARS = [
    "weather_code", "temperature_2m_max", "temperature_2m_min",
    "apparent_temperature_max", "apparent_temperature_min",
    "sunrise", "sunset", "daylight_duration", "sunshine_duration",
    "uv_index_max", "precipitation_sum", "rain_sum", "showers_sum",
    "snowfall_sum", "precipitation_hours",
    "wind_speed_10m_max", "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
]

# Modelli in ordine di preferenza: (nome API, nome display, tentativi max)
MODELS = [
    ("meteofrance_arome_france_hd", "AROME HD", 3),
    ("meteofrance_arome_france", "AROME", 3),
    # MOLOCH non è disponibile su Open-Meteo
    ("icon_eu", "ICON-EU", 1),
]


# ── Utilità ──────────────────────────────────────────────────────────────

def format_date_it(dt):
    """Formatta una data in italiano (es. 'mercoledì 12 marzo 2025')."""
    return f"{GIORNI_IT[dt.weekday()]} {dt.day} {MESI_IT[dt.month - 1]} {dt.year}"


# ── Open-Meteo ───────────────────────────────────────────────────────────

def _fetch_openmeteo(date_str, model_name, hourly_vars):
    """Singola richiesta a Open-Meteo. Solleva eccezione in caso di errore."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(hourly_vars),
        "daily": ",".join(DAILY_VARS),
        "models": model_name,
        "start_date": date_str,
        "end_date": date_str,
        "timezone": "Europe/Rome",
    }
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast", params=params, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise ValueError(data.get("reason", "Errore sconosciuto Open-Meteo"))
    return data


def fetch_forecast_data(target_date):
    """Scarica dati orari da Open-Meteo provando i modelli in ordine di preferenza."""
    date_str = target_date.strftime("%Y-%m-%d")

    for model_name, display, max_retries in MODELS:
        for attempt in range(1, max_retries + 1):
            print(f"  [{display}] Tentativo {attempt}/{max_retries}...")
            try:
                try:
                    data = _fetch_openmeteo(date_str, model_name, HOURLY_VARS)
                except Exception:
                    # Se il set completo fallisce, riprova con variabili essenziali
                    data = _fetch_openmeteo(date_str, model_name, HOURLY_VARS_CORE)

                hours = data.get("hourly", {}).get("time", [])
                if len(hours) < 24:
                    print(f"  ⚠ Solo {len(hours)}/24 ore disponibili")
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    break  # Dati incompleti, prova modello successivo

                print(f"  ✓ {display}: {len(hours)} ore ottenute")
                return data, display
            except Exception as e:
                print(f"  ✗ Errore: {e}")
                if attempt < max_retries:
                    time.sleep(2)

        print(f"  ✗ Falliti tutti i tentativi con {display}")

    raise RuntimeError("Impossibile ottenere dati meteo da nessun modello Open-Meteo")


# ── Google Gemini ────────────────────────────────────────────────────────

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = f"""Sei un meteorologo professionista italiano. Ricevi dati meteo orari e giornalieri per {LOCATION_NAME} e devi scrivere le previsioni per la giornata indicata.

FORMATO OBBLIGATORIO — segui SEMPRE queste regole senza eccezioni:

Il testo deve essere un UNICO BLOCCO CONTINUO, senza andare a capo, senza elenchi puntati, senza trattini, senza numerazioni, senza sezioni separate. Un paragrafo unico e fluido dall'inizio alla fine.

Struttura del testo:
- Inizia con "Previsioni per {LOCATION_NAME}, [giorno della settimana] [giorno] [mese] [anno]."
- Prosegui descrivendo in sequenza: la notte (00-06), la mattina (06-12), il pomeriggio (12-18), la sera (18-24).
- Per ogni fascia indica: condizioni del cielo, temperatura, vento (velocità e direzione), umidità relativa, e precipitazioni se presenti.
- Indica alba e tramonto con gli orari esatti dai dati.
- Concludi con una frase riepilogativa sulla giornata.

Regole sul contenuto:
- Temperature arrotondate a un decimale (esempio: 14.2°C).
- Precipitazioni in millimetri.
- Vento in km/h con direzione cardinale (N, NE, E, SE, S, SW, W, NW).
- Umidità relativa in percentuale.
- Nuvolosità descritta a parole: sereno (0-10%), poco nuvoloso (10-30%), parzialmente nuvoloso (30-60%), nuvoloso (60-80%), molto nuvoloso (80-95%), coperto (95-100%).
- NON usare emoji.
- NON usare formattazione Markdown (no asterischi, no underscore, no backtick).
- Massimo 1500 caratteri.
- Basati SOLO sui dati numerici forniti, non inventare nulla.
- Tono professionale ma accessibile a tutti."""


def get_latest_gemini_model(api_key):
    """Interroga l'API Gemini per trovare il modello flash più recente."""
    url = f"{GEMINI_API_BASE}/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except Exception as e:
        print(f"  ⚠ Impossibile listare modelli Gemini ({e}), uso default")
        return "gemini-2.0-flash"

    # Filtra modelli che supportano generateContent
    flash = []
    for m in models:
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods and "flash" in name and "gemini" in name:
            flash.append(name)

    if not flash:
        return "gemini-2.0-flash"

    # Ordina in modo decrescente: versioni più recenti prima
    flash.sort(reverse=True)
    return flash[0]


def generate_forecast(weather_data, model_used, target_date, api_key):
    """Invia i dati meteo a Gemini e ottiene le previsioni in linguaggio naturale."""
    gemini_model = get_latest_gemini_model(api_key)
    print(f"  Modello Gemini selezionato: {gemini_model}")

    date_it = format_date_it(target_date)
    hourly = weather_data.get("hourly", {})
    daily = weather_data.get("daily", {})

    user_prompt = (
        f"Dati meteo per {LOCATION_NAME}, {date_it}. "
        f"Modello meteorologico utilizzato: {model_used}.\n\n"
        f"DATI ORARI (dalle 00:00 alle 23:00):\n"
        f"{json.dumps(hourly, indent=2, ensure_ascii=False)}\n\n"
        f"DATI GIORNALIERI AGGREGATI:\n"
        f"{json.dumps(daily, indent=2, ensure_ascii=False)}\n\n"
        f"Scrivi le previsioni seguendo rigorosamente le istruzioni fornite."
    )

    url = f"{GEMINI_API_BASE}/models/{gemini_model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
        },
    }

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()

    candidates = result.get("candidates", [])
    if not candidates:
        block_reason = result.get("promptFeedback", {}).get("blockReason", "sconosciuto")
        raise ValueError(f"Risposta bloccata da Gemini (motivo: {block_reason})")

    finish_reason = candidates[0].get("finishReason", "")
    if finish_reason == "SAFETY":
        raise ValueError("Risposta bloccata per motivi di sicurezza")

    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    if not text:
        raise ValueError(f"Risposta Gemini vuota (finishReason: {finish_reason})")

    return text.strip(), gemini_model


# ── Telegram ─────────────────────────────────────────────────────────────

def send_telegram(text, target_chat_id=None):
    """Invia le previsioni ai chat Telegram configurati (o a uno specifico)."""
    if not TELEGRAM_TOKEN:
        print("Telegram non configurato")
        return False

    chat_ids = [target_chat_id] if target_chat_id else LISTA_CHAT
    if not chat_ids:
        print("Nessun chat_id configurato")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    any_ok = False

    for chat_id in chat_ids:
        try:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": text},
                timeout=15,
            )
            resp.raise_for_status()
            if resp.json().get("ok"):
                print(f"✓ Previsioni inviate a {chat_id}")
                any_ok = True
            else:
                print(f"✗ Errore per {chat_id}: {resp.json()}")
        except Exception as e:
            print(f"✗ Errore invio a {chat_id}: {e}")

    return any_ok


# ── Main ─────────────────────────────────────────────────────────────────

def main(target_chat_id=None):
    print("=" * 50)
    print("  PREVISIONI METEO – GENERAZIONE AI")
    print("=" * 50)

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY non configurata")
        sys.exit(1)

    now = datetime.now(TZ_ROME)
    target = (now + timedelta(days=1)).date()
    target_dt = datetime.combine(target, datetime.min.time()).replace(tzinfo=TZ_ROME)

    print(f"\nData target: {format_date_it(target_dt)}")
    print(f"Località: {LOCATION_NAME} ({LATITUDE}°N, {LONGITUDE}°E)")

    # 1. Scarica dati meteo
    print("\n📡 Scaricamento dati Open-Meteo...")
    weather_data, model_used = fetch_forecast_data(target_dt)

    # 2. Genera previsioni con AI
    print("\n🤖 Generazione previsioni con AI...")
    forecast_text, gemini_model = generate_forecast(
        weather_data, model_used, target_dt, GEMINI_API_KEY
    )

    print(f"\n--- Previsioni ({len(forecast_text)} caratteri) ---")
    print(forecast_text)
    print("---")

    # 3. Componi e invia messaggio Telegram
    print("\n📤 Invio via Telegram...")
    header = (
        f"🌤 Previsioni Meteo\n"
        f"📍 {LOCATION_NAME}\n"
        f"📅 {target_dt.strftime('%d/%m/%Y')} ({GIORNI_IT[target_dt.weekday()]})\n"
        f"🔬 Modello: {model_used} | AI: {gemini_model}\n\n"
    )
    full_msg = header + forecast_text

    if send_telegram(full_msg, target_chat_id=target_chat_id):
        print("\n✅ Previsioni inviate con successo")
    else:
        print("\n⚠️ Invio fallito")
        sys.exit(1)


if __name__ == "__main__":
    main()
