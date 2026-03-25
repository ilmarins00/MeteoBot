#!/usr/bin/env python3
"""
Previsioni Meteo – Generazione automatica con AI (Versione Corretta Model Names)
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

STATE_FILE = "state.json"
STORICO_FILE = "storico_24h.json"

# Inclusione completa di tutte le variabili orarie disponibili per AROME/Open-Meteo
HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "precipitation", "rain", "showers",
    "snowfall", "snow_depth", "weather_code", "pressure_msl",
    "surface_pressure", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "visibility",
    "evapotranspiration", "et0_fao_evapotranspiration", 
    "vapour_pressure_deficit", "wind_speed_10m", "wind_direction_10m", 
    "wind_gusts_10m", "wind_speed_100m", "wind_direction_100m", 
    "soil_temperature_0_to_7cm", "soil_temperature_7_to_28cm", 
    "soil_moisture_0_to_7cm", "soil_moisture_7_to_28cm",
    "uv_index", "is_day", "sunshine_duration", 
    "shortwave_radiation", "direct_radiation", "diffuse_radiation", 
    "direct_normal_irradiance", "terrestrial_radiation",
    "cape", "freezing_level_height", "boundary_layer_height", 
    "convective_inhibition", "lifted_index", "lightning_potential",
    "temperature_850hPa", "temperature_500hPa",
    "wind_speed_850hPa", "wind_speed_500hPa",
    "wind_direction_850hPa", "wind_direction_500hPa",
    "geopotential_height_850hPa", "geopotential_height_500hPa",
]

HOURLY_VARS_CORE = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "precipitation", "rain", "snowfall",
    "weather_code", "pressure_msl", "cloud_cover",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "is_day",
]

PRESSURE_LEVEL_VARS = [
    "temperature_925hPa", "temperature_700hPa", "temperature_300hPa",
    "wind_speed_925hPa", "wind_speed_700hPa", "wind_speed_300hPa",
    "wind_direction_925hPa", "wind_direction_700hPa", "wind_direction_300hPa",
    "geopotential_height_1000hPa", "geopotential_height_700hPa",
    "geopotential_height_300hPa",
    "relative_humidity_850hPa", "relative_humidity_700hPa",
    "relative_humidity_500hPa",
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

MODELS = [
    ("meteofrance_arome_france_hd", "AROME HD", 3),
    ("meteofrance_arome_france", "AROME", 3),
    ("icon_eu", "ICON-EU", 1),
]

MODEL_HORIZONS = {
    "meteofrance_arome_france_hd": 3,
    "meteofrance_arome_france":     3,
    "icon_eu":                      5,
}

MODEL_HORIZONS_HOURS = {
    "meteofrance_arome_france_hd": 51,
    "meteofrance_arome_france":    48,
    "icon_eu":                     120,
}

MAX_RUN_AGE_H = 12
MIN_FUTURE_HOURS = 24


def format_date_it(dt):
    return f"{GIORNI_IT[dt.weekday()]} {dt.day} {MESI_IT[dt.month - 1]} {dt.year}"


def load_ground_conditions():
    ground = {}
    import os
    base = os.path.dirname(os.path.abspath(__file__))

    state_path = os.path.join(base, STATE_FILE)
    try:
        with open(state_path) as f:
            state = json.load(f)

        meteo = state.get("meteo", {})
        if meteo:
            ground["suolo"] = {
                "api_mm": meteo.get("api_ultimo_valore"),
                "saturazione_perc": meteo.get("ultima_saturazione_perc"),
                "capacita_campo_mm": 200,
                "pioggia_24h_stazione": None,
                "t_min_oggi": meteo.get("t_min_oggi"),
                "t_max_oggi": meteo.get("t_max_oggi"),
                "pressione_msl": meteo.get("ultima_pressione"),
                "etp_giornaliera": meteo.get("ultimo_etp_giornaliera"),
                "etr_giornaliera": meteo.get("ultimo_etr_giornaliera"),
                "stress_idrico_ks": meteo.get("ultimo_ks"),
                "data_aggiornamento": meteo.get("ultimo_update_ora"),
            }

        sbcape = state.get("sbcape", {})
        if sbcape:
            ground["termodinamica_attuale"] = {
                "sbcape_jkg": sbcape.get("sbcape"),
                "mucape_jkg": sbcape.get("mucape"),
                "cin_jkg": sbcape.get("cin"),
                "lifted_index": sbcape.get("lifted_index"),
                "bulk_shear_ms": sbcape.get("bulk_shear"),
                "lcl_hpa": sbcape.get("lcl_pressure"),
                "lfc_hpa": sbcape.get("lfc_pressure"),
                "el_hpa": sbcape.get("el_pressure"),
                "severe_score": sbcape.get("severe_score"),
                "timestamp": sbcape.get("timestamp"),
            }

        arpal = state.get("arpal", {})
        if arpal:
            ground["allerta_arpal_attuale"] = {
                "max_livello": arpal.get("max_livello"),
                "dettaglio": arpal.get("dettaglio"),
                "vigilanza": arpal.get("vigilanza"),
            }
    except Exception as e:
        print(f"  ⚠ Impossibile caricare state.json: {e}")

    storico_path = os.path.join(base, STORICO_FILE)
    try:
        with open(storico_path) as f:
            storico = json.load(f)
        if storico:
            ultimo = storico[-1]
            ground.setdefault("suolo", {})["pioggia_24h_stazione"] = ultimo.get("pioggia_24h")
            ground["osservazioni_recenti"] = {
                "temp": ultimo.get("temp"),
                "umidita": ultimo.get("umidita"),
                "pressione": ultimo.get("pressione"),
                "pioggia_1h": ultimo.get("pioggia_1h"),
                "pioggia_24h": ultimo.get("pioggia_24h"),
                "vento_kmh": ultimo.get("vento"),
                "raffica_kmh": ultimo.get("raffica"),
                "dew_point": ultimo.get("dew_point"),
                "api": ultimo.get("api"),
                "timestamp": ultimo.get("ts"),
            }
    except Exception as e:
        print(f"  ⚠ Impossibile caricare storico_24h.json: {e}")

    return ground if ground else None


def _fetch_openmeteo(start_date_str, end_date_str, model_name, hourly_vars):
    params = {
        "latitude": LATITUDE, "longitude": LONGITUDE,
        "hourly": ",".join(hourly_vars), "daily": ",".join(DAILY_VARS),
        "models": model_name, "start_date": start_date_str,
        "end_date": end_date_str, "timezone": "Europe/Rome",
    }
    resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise ValueError(data.get("reason", "Errore sconosciuto Open-Meteo"))
    return data


def _strip_null_vars(data):
    hourly = data.get("hourly", {})
    keys_to_remove = [k for k, v in hourly.items() if k != "time" and isinstance(v, list) and all(x is None for x in v)]
    for key in keys_to_remove: del hourly[key]
    if keys_to_remove: print(f"  ⚠ Rimosse {len(keys_to_remove)} variabili senza dati")
    return data


def _fetch_pressure_levels(start_date_str, end_date_str):
    try:
        params = {
            "latitude": LATITUDE, "longitude": LONGITUDE,
            "hourly": ",".join(PRESSURE_LEVEL_VARS), "start_date": start_date_str,
            "end_date": end_date_str, "timezone": "Europe/Rome",
        }
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        result = {k: v for k, v in hourly.items() if k != "time" and isinstance(v, list) and any(x is not None for x in v)}
        return result
    except Exception as e:
        print(f"  ⚠ Errore fetch supplementare: {e}")
        return {}


def check_data_freshness(data, model_api_name, model_display, now):
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    if not times or not temps: return False, "Dati non disponibili"

    last_valid_idx = next((i for i in range(len(temps)-1, -1, -1) if temps[i] is not None), None)
    if last_valid_idx is None: return False, "Tutti i valori null"

    last_valid_dt = datetime.fromisoformat(times[last_valid_idx]).replace(tzinfo=TZ_ROME)
    hours_ahead = (last_valid_dt - now).total_seconds() / 3600
    if hours_ahead < MIN_FUTURE_HOURS: return False, f"Copertura insufficiente ({hours_ahead:.0f}h)"

    horizon_h = MODEL_HORIZONS_HOURS.get(model_api_name)
    if horizon_h:
        run_dt = last_valid_dt - timedelta(hours=horizon_h)
        age_h = (now - run_dt).total_seconds() / 3600
        if age_h > MAX_RUN_AGE_H: return False, f"Run obsoleta ({age_h:.0f}h fa)"
        return True, f"Run aggiornata (~{age_h:.1f}h fa), copertura +{hours_ahead:.0f}h"
    return True, f"Copertura futura {hours_ahead:.0f}h"


def fetch_forecast_data(start_date):
    start_str = start_date.strftime("%Y-%m-%d")
    for model_name, display, max_retries in MODELS:
        horizon_days = MODEL_HORIZONS.get(model_name, 2)
        end_str = (start_date + timedelta(days=horizon_days)).strftime("%Y-%m-%d")
        for attempt in range(1, max_retries + 1):
            try:
                try: data = _fetch_openmeteo(start_str, end_str, model_name, HOURLY_VARS)
                except: data = _fetch_openmeteo(start_str, end_str, model_name, HOURLY_VARS_CORE)
                
                if len(data.get("hourly", {}).get("time", [])) < 24: continue
                data = _strip_null_vars(data)
                extra = _fetch_pressure_levels(start_str, end_str)
                if extra: data.setdefault("hourly", {}).update(extra)
                return data, model_name, display
            except Exception as e:
                print(f"  ✗ Errore {display}: {e}")
                time.sleep(2)
    raise RuntimeError("Nessun dato ottenuto")


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = f"""Sei un meteorologo professionista italiano. Ricevi dati meteo per {LOCATION_NAME}.
Il tuo output DEVE contenere TRE sezioni separate dai marcatori "---SEZIONE TECNICA---" e "---SEZIONE RISCHI---".

═══ PRIMA SEZIONE: PREVISIONI SEMPLICI ═══
Testo CONCISO in un UNICO BLOCCO CONTINUO. Descrivi oggi (ore restanti) e giorni successivi (notte, mattina, pomeriggio, sera). No emoji, no markdown.

═══ SECONDA SEZIONE: ANALISI TECNICA ═══
Analisi per esperti in UNICO BLOCCO CONTINUO. Includi: temperature ai livelli (925, 850, 700, 500, 300 hPa), venti in quota, geopotenziali, CAPE, LI, CIN, zero termico, umidità e VPD.

═══ TERZA SEZIONE: VALUTAZIONE RISCHI ═══
Inizia con ESATTAMENTE una riga: VERDE, GIALLO, ARANCIONE o ROSSO.
SOGLIE ARPAL DA RISPETTARE MATEMATICAMENTE:
- Pioggia oraria: Giallo >= 15, Arancione >= 30, Rosso >= 50 mm/h
- Pioggia 24h: Giallo >= 80, Arancione >= 150, Rosso >= 250 mm
- Vento/Raffiche: Giallo >= 50, Arancione >= 80, Rosso >= 100 km/h
- Caldo/Gelo: Giallo >=35/<=0, Arancione >=38/<=-5, Rosso >=40/<=-10 °C
- Neve: Giallo >= 5, Arancione >= 15, Rosso >= 30 cm
- API Suolo: >= 185 mm -> rischio idrogeologico elevato.
Sia SEVERO: se i dati sono sotto soglia, il livello è VERDE.
Se VERDE, scrivi solo:
VERDE
Nessun rischio significativo previsto.
Altrimenti spiega i motivi del rischio senza citare valori numerici tra parentesi."""


def generate_forecast(weather_data, model_used, date_range_info, api_key, ground_data=None):
    user_prompt = (
        f"Dati meteo per {LOCATION_NAME}. {date_range_info}. Modello: {model_used}.\n"
        f"ORARI: {json.dumps(weather_data.get('hourly', {}), ensure_ascii=False)}\n"
        f"GIORNALIERI: {json.dumps(weather_data.get('daily', {}), ensure_ascii=False)}\n"
    )
    if ground_data: user_prompt += f"STAZIONE: {json.dumps(ground_data, ensure_ascii=False)}\n"
    user_prompt += "Segui rigorosamente le istruzioni."

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192}
    }

    # Nomi modelli CORRETTI per evitare 404
    models_to_try = [("gemini-1.5-pro", 1), ("gemini-1.5-flash", 3)]

    for model_name, max_retries in models_to_try:
        print(f"  Tentativo con: {model_name}")
        url = f"{GEMINI_API_BASE}/models/{model_name}:generateContent?key={api_key}"
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=120)
                if resp.status_code == 429:
                    time.sleep(60); continue
                resp.raise_for_status()
                text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                return text.strip(), model_name
            except Exception as e:
                print(f"  ⚠ {model_name} fallito: {e}")
    raise RuntimeError("Tutti i modelli Gemini hanno fallito.")


def send_telegram(text, target_chat_id=None):
    if not TELEGRAM_TOKEN: return False
    chat_ids = [target_chat_id] if target_chat_id else LISTA_CHAT
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    ok = False
    for cid in chat_ids:
        try:
            r = requests.post(url, data={"chat_id": cid, "text": text}, timeout=15)
            if r.status_code == 200: ok = True
        except: pass
    return ok


def main(target_chat_id=None):
    now = datetime.now(TZ_ROME)
    today_dt = datetime.combine(now.date(), datetime.min.time()).replace(tzinfo=TZ_ROME)
    
    print(f"--- Avvio Previsioni: {now.strftime('%H:%M')} ---")
    weather_data, model_api, model_display = fetch_forecast_data(today_dt)
    
    fresh_ok, fresh_msg = check_data_freshness(weather_data, model_api, model_display, now)
    
    # Filtro orario
    hourly = weather_data.get("hourly", {})
    start_idx = next((i for i, t in enumerate(hourly.get("time", [])) if t >= now.strftime("%Y-%m-%dT%H:00")), 0)
    for k in hourly: 
        if isinstance(hourly[k], list): hourly[k] = hourly[k][start_idx:]
    
    last_t = hourly.get("time", [])[-1]
    actual_end = datetime.fromisoformat(last_t).replace(tzinfo=TZ_ROME)
    
    ground = load_ground_conditions()
    range_info = f"Dal {now.strftime('%H:00 %d/%m')} al {actual_end.strftime('%H:00 %d/%m')}"
    
    forecast_text, gemini_model = generate_forecast(weather_data, model_display, range_info, GEMINI_API_KEY, ground)

    # Parsing e Invio
    header = f"🌤 Previsioni {LOCATION_NAME}\n📅 {range_info}\n🔬 {model_display} | AI: {gemini_model}\n"
    if not fresh_ok: header += f"⚠️ {fresh_msg}\n"

    parts = forecast_text.split("---SEZIONE TECNICA---")
    simple = parts[0].strip()
    tech_risk = parts[1].split("---SEZIONE RISCHI---")
    tech = tech_risk[0].strip()
    risk_raw = tech_risk[1].strip()

    colors = {"VERDE": "🟢", "GIALLO": "🟡", "ARANCIONE": "🟠", "ROSSO": "🔴"}
    r_lines = risk_raw.split("\n", 1)
    c_word = r_lines[0].strip().upper()
    risk_msg = f"{colors.get(c_word, '🟢')} RISCHI: {r_lines[1] if len(r_lines)>1 else 'Nessuno'}"

    full_msg = f"{header}\n{simple}\n\n📊 ANALISI TECNICA\n{tech}\n\n{risk_msg}"
    
    if not send_telegram(full_msg, target_chat_id):
        # Fallback split
        send_telegram(header + simple, target_chat_id)
        send_telegram("📊 TECNICA\n" + tech, target_chat_id)
        send_telegram(risk_msg, target_chat_id)
    print("✅ Completato.")

if __name__ == "__main__":
    main()