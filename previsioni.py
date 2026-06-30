#!/usr/bin/env python3
"""
Previsioni Meteo La Spezia – Generazione automatica con AI e Motore LRO (Soglie ARPAL)
"""
import json
import sys
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ==============================================================================
# CONFIGURAZIONE INIZIALE
# ==============================================================================

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS, GEMINI_API_KEY, LATITUDE, LONGITUDE

# Alternative coordinates (currently using config.py values)
# LATITUDE = 44.1025  # La Spezia
# LONGITUDE = 9.8241  # La Spezia

TZ_ROME = ZoneInfo("Europe/Rome")
LOCATION_NAME = "La Spezia"

GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]

# ==============================================================================
# VARIABILI METEOROLOGICHE (SUPERFICIE E QUOTA)
# ==============================================================================

HOURLY_VARS = [
    # --- Superficie, Termodinamica e Strato Limite ---
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "wet_bulb_temperature_2m",
    "precipitation", "rain", "showers", "snowfall", "snow_depth", 
    "weather_code", "pressure_msl", "surface_pressure", 
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", 
    "visibility",
    
    # --- Vento al suolo ---
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    
    # --- Indici Convettivi e Radiazione ---
    "uv_index", "cape", "lifted_index", "convective_inhibition",
    "sunshine_duration", "shortwave_radiation", "direct_radiation", 
    "diffuse_radiation", "direct_normal_irradiance",
    "freezing_level_height", "vapour_pressure_deficit", "is_day",
    "et0_fao_evapotranspiration",
    
    # --- Livelli soprasuolo (Boundary Layer) ---
    "temperature_20m", "temperature_50m", "temperature_100m",
    "temperature_150m", "temperature_200m",
    "wind_speed_20m", "wind_speed_50m", "wind_speed_100m",
    "wind_speed_150m", "wind_speed_200m",
    "wind_direction_20m", "wind_direction_50m", "wind_direction_100m",
    "wind_direction_150m", "wind_direction_200m",
    
    # --- Livelli di pressione principali (inclusi nel fetch primario) ---
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
    # Temperatura a tutti i livelli significativi
    "temperature_1000hPa", "temperature_950hPa", "temperature_925hPa",
    "temperature_900hPa", "temperature_850hPa", "temperature_800hPa",
    "temperature_750hPa", "temperature_700hPa", "temperature_650hPa",
    "temperature_600hPa", "temperature_550hPa", "temperature_500hPa",
    "temperature_450hPa", "temperature_400hPa", "temperature_350hPa",
    "temperature_300hPa", "temperature_250hPa",
    # Dewpoint ai livelli chiave
    "dew_point_1000hPa", "dew_point_925hPa", "dew_point_850hPa",
    "dew_point_700hPa", "dew_point_500hPa", "dew_point_300hPa",
    # Velocità vento
    "wind_speed_1000hPa", "wind_speed_950hPa", "wind_speed_925hPa",
    "wind_speed_900hPa", "wind_speed_850hPa", "wind_speed_800hPa",
    "wind_speed_750hPa", "wind_speed_700hPa", "wind_speed_650hPa",
    "wind_speed_600hPa", "wind_speed_500hPa", "wind_speed_400hPa",
    "wind_speed_300hPa", "wind_speed_250hPa",
    # Direzione vento
    "wind_direction_1000hPa", "wind_direction_925hPa",
    "wind_direction_850hPa", "wind_direction_700hPa",
    "wind_direction_500hPa", "wind_direction_300hPa",
    "wind_direction_250hPa",
    # Altezza geopotenziale
    "geopotential_height_1000hPa", "geopotential_height_950hPa",
    "geopotential_height_925hPa", "geopotential_height_850hPa",
    "geopotential_height_700hPa", "geopotential_height_500hPa",
    "geopotential_height_400hPa", "geopotential_height_300hPa",
    "geopotential_height_250hPa",
    # Umidità relativa
    "relative_humidity_1000hPa", "relative_humidity_925hPa",
    "relative_humidity_850hPa", "relative_humidity_700hPa",
    "relative_humidity_600hPa", "relative_humidity_500hPa",
    "relative_humidity_400hPa", "relative_humidity_300hPa",
    # Copertura nuvolosa ai livelli
    "cloud_cover_1000hPa", "cloud_cover_925hPa", "cloud_cover_850hPa",
    "cloud_cover_700hPa", "cloud_cover_500hPa", "cloud_cover_300hPa",
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

FALLBACK_MODEL = "icon_eu"
FALLBACK_MODEL_DISPLAY = "ICON-EU"

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

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL_PRIMARY = "gemini-3.5-flash" # Aggiornato ai modelli correnti consigliati
GEMINI_MODEL_FALLBACK = "gemini-3.1-flash-lite"


# ==============================================================================
# FUNZIONI DI UTILITA' E FETCHING
# ==============================================================================

def format_date_it(dt):
    return f"{GIORNI_IT[dt.weekday()]} {dt.day} {MESI_IT[dt.month - 1]} {dt.year}"

def load_ground_conditions(hourly, timestamp_str):
    """Estrae le condizioni attuali (ora 0) direttamente dai dati orari del modello"""
    ground = {}
    
    def val(key):
        v = hourly.get(key)
        return v[0] if v and len(v) > 0 else None

    ground["suolo"] = {
        "pressione_msl": val("pressure_msl"),
        "data_aggiornamento": timestamp_str,
    }

    ground["termodinamica_attuale"] = {
        "sbcape_jkg": val("cape"),
        "cin_jkg": val("convective_inhibition"),
        "lifted_index": val("lifted_index"),
        "timestamp": timestamp_str,
    }

    ground["osservazioni_recenti"] = {
        "temp": val("temperature_2m"),
        "umidita": val("relative_humidity_2m"),
        "pressione": val("pressure_msl"),
        "pioggia_1h": val("precipitation"),
        "vento_kmh": val("wind_speed_10m"),
        "raffica_kmh": val("wind_gusts_10m"),
        "dew_point": val("dew_point_2m"),
        "timestamp": timestamp_str,
    }

    return ground if ground else None

def _fetch_openmeteo(start_date_str, end_date_str, model_name, hourly_vars):
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(hourly_vars),
        "daily": ",".join(DAILY_VARS),
        "models": model_name,
        "start_date": start_date_str,
        "end_date": end_date_str,
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

def _strip_null_vars(data):
    hourly = data.get("hourly", {})
    keys_to_remove = []
    for key, vals in hourly.items():
        if key == "time":
            continue
        if isinstance(vals, list) and all(v is None for v in vals):
            keys_to_remove.append(key)
    for key in keys_to_remove:
        del hourly[key]
    if keys_to_remove:
        print(f"  ⚠ Rimosse {len(keys_to_remove)} variabili senza dati")
    return data

def _fetch_pressure_levels(start_date_str, end_date_str, model_name=None):
    try:
        params = {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(PRESSURE_LEVEL_VARS),
            "start_date": start_date_str,
            "end_date": end_date_str,
            "timezone": "Europe/Rome",
        }
        if model_name:
            params["models"] = model_name
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast", params=params, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            print(f"  ⚠ Errore livelli pressione supplementari: {data.get('reason')}")
            return {}
        hourly = data.get("hourly", {})
        result = {}
        for key, vals in hourly.items():
            if key == "time":
                continue
            if isinstance(vals, list) and any(v is not None for v in vals):
                result[key] = vals
        if result:
            print(f"  ✓ Livelli pressione supplementari: {len(result)} variabili ottenute")
        return result
    except Exception as e:
        print(f"  ⚠ Errore fetch supplementare: {e}")
        return {}

def _fetch_fallback_vars(start_date_str, end_date_str, missing_vars):
    if not missing_vars:
        return {}, []
    try:
        params = {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(missing_vars),
            "models": FALLBACK_MODEL,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "timezone": "Europe/Rome",
        }
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast", params=params, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            print(f"  ⚠ Errore fallback {FALLBACK_MODEL_DISPLAY}: {data.get('reason')}")
            return {}, []
        hourly = data.get("hourly", {})
        fb_times = hourly.get("time", [])
        result = {
            k: v for k, v in hourly.items()
            if k != "time" and isinstance(v, list) and any(x is not None for x in v)
        }
        return result, fb_times
    except Exception as e:
        print(f"  ⚠ Errore fetch fallback {FALLBACK_MODEL_DISPLAY}: {e}")
        return {}, []

def check_data_freshness(data, model_api_name, model_display, now):
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return False, "Nessun dato orario disponibile"

    temps = hourly.get("temperature_2m", [])
    if not temps:
        return False, "temperature_2m non disponibile, impossibile verificare freshness"

    last_valid_idx = None
    for i in range(len(temps) - 1, -1, -1):
        if temps[i] is not None:
            last_valid_idx = i
            break

    if last_valid_idx is None:
        return False, "Tutti i valori di temperature_2m sono null"

    try:
        last_valid_dt = datetime.fromisoformat(times[last_valid_idx]).replace(tzinfo=TZ_ROME)
    except ValueError:
        return False, f"Formato timestamp non riconosciuto: {times[last_valid_idx]}"

    hours_ahead = (last_valid_dt - now).total_seconds() / 3600

    if hours_ahead < MIN_FUTURE_HOURS:
        return False, (
            f"Copertura insufficiente [{model_display}]: "
            f"solo {hours_ahead:.0f}h future (ultimo dato valido: {times[last_valid_idx]})"
        )

    horizon_h = MODEL_HORIZONS_HOURS.get(model_api_name)
    if horizon_h is None:
        return True, (
            f"Copertura futura {hours_ahead:.0f}h [{model_display}] "
            f"(orizzonte nominale non noto, età run non verificabile)"
        )

    run_dt = last_valid_dt - timedelta(hours=horizon_h)
    age_h = (now - run_dt).total_seconds() / 3600

    if age_h > MAX_RUN_AGE_H:
        return False, (
            f"Run obsoleta [{model_display}]: "
            f"inizializzata ~{run_dt.strftime('%d/%m %H:%M')} ({age_h:.0f}h fa), "
            f"attesa run più recente (orizzonte {horizon_h}h, "
            f"ultimo dato valido: {times[last_valid_idx]})"
        )

    return True, (
        f"Run aggiornata [{model_display}]: "
        f"inizializzata ~{run_dt.strftime('%d/%m %H:%M')} ({age_h:.1f}h fa), "
        f"copertura futura {hours_ahead:.0f}h (fino a {times[last_valid_idx]})"
    )

def fetch_forecast_data(start_date):
    start_str = start_date.strftime("%Y-%m-%d")

    for model_name, display, max_retries in MODELS:
        horizon_days = MODEL_HORIZONS.get(model_name, 2)
        end_str = (start_date + timedelta(days=horizon_days)).strftime("%Y-%m-%d")
        print(f"  [{display}] Orizzonte richiesto: {horizon_days} giorni → {end_str}")

        for attempt in range(1, max_retries + 1):
            print(f"  [{display}] Tentativo {attempt}/{max_retries}...")
            try:
                try:
                    data = _fetch_openmeteo(start_str, end_str, model_name, HOURLY_VARS)
                except Exception:
                    data = _fetch_openmeteo(start_str, end_str, model_name, HOURLY_VARS_CORE)

                hours = data.get("hourly", {}).get("time", [])
                if len(hours) < 24:
                    print(f"  ⚠ Solo {len(hours)}/24 ore disponibili")
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    break

                data = _strip_null_vars(data)

                print("  📊 Richiesta livelli di pressione supplementari...")
                extra = _fetch_pressure_levels(start_str, end_str, model_name=model_name)
                if extra:
                    hourly = data.get("hourly", {})
                    for key, vals in extra.items():
                        if key not in hourly:
                            hourly[key] = vals

                hourly = data.get("hourly", {})
                if model_name != FALLBACK_MODEL:
                    all_expected_vars = set(HOURLY_VARS) | set(PRESSURE_LEVEL_VARS)
                    missing_vars = sorted(v for v in all_expected_vars if v not in hourly)
                    if missing_vars:
                        print(f"  ⚠ {len(missing_vars)} variabili non disponibili su {display}, "
                              f"integrazione da {FALLBACK_MODEL_DISPLAY}...")
                        fb_vars, fb_times = _fetch_fallback_vars(start_str, end_str, missing_vars)
                        if fb_vars and fb_times:
                            arome_times = hourly.get("time", [])
                            time_index = {t: i for i, t in enumerate(fb_times)}
                            added = []
                            for key, vals in fb_vars.items():
                                aligned = []
                                for t in arome_times:
                                    if t in time_index:
                                        idx_fb = time_index[t]
                                        # Verifica rigida dell'indice per evitare IndexError
                                        if idx_fb < len(vals):
                                            aligned.append(vals[idx_fb])
                                        else:
                                            aligned.append(None)
                                    else:
                                        aligned.append(None)
                                
                                if any(v is not None for v in aligned):
                                    hourly[key] = aligned
                                    added.append(key)
                            if added:
                                print(f"  ✓ Variabili integrate da {FALLBACK_MODEL_DISPLAY}: {', '.join(added)}")

                print(f"  ✓ {display}: {len(hours)} ore, "
                      f"{len([k for k in data.get('hourly', {}) if k != 'time'])} variabili totali")
                return data, model_name, display

            except Exception as e:
                print(f"  ✗ Errore: {e}")
                if attempt < max_retries:
                    time.sleep(2)

        print(f"  ✗ Falliti tutti i tentativi con {display}")

    raise RuntimeError("Impossibile ottenere dati meteo da nessun modello Open-Meteo")

# --- FINE PRIMA PARTE ---

# ==============================================================================
# MOTORE MATEMATICO - CALCOLO INDICE RISCHIO OGGETTIVO (LRO) E SOGLIE ARPAL
# ==============================================================================

def _calcola_lro_pioggia(precipitazioni_orarie):
    """
    Calcola il contributo pioggia (max 1.5).
    Sotto i 6 mm/h senza persistenza: 0.
    Eccezione persistenza (stratiforme): 5 mm/h ma prolungata -> 0.5 - 1.
    Intensità >= 6 mm/h: da 0.5 a 1.5.
    """
    if not precipitazioni_orarie or all(p is None for p in precipitazioni_orarie):
        return 0.0

    p_valide = [p for p in precipitazioni_orarie if p is not None]
    max_oraria = max(p_valide) if p_valide else 0
    cumulata_tot = sum(p_valide)
    
    # Calcolo persistenza: ore consecutive con pioggia > 2 mm/h
    ore_consecutive = 0
    max_consecutive = 0
    for p in p_valide:
        if p >= 2.0:
            ore_consecutive += 1
            if ore_consecutive > max_consecutive:
                max_consecutive = ore_consecutive
        else:
            ore_consecutive = 0

    punteggio = 0.0

    # Valutazione intensità di picco
    if max_oraria >= 30.0:
        punteggio = max(punteggio, 1.5)
    elif max_oraria >= 20.0:
        punteggio = max(punteggio, 1.0)
    elif max_oraria >= 6.0:
        punteggio = max(punteggio, 0.5)

    # Valutazione persistenza stratiforme (tipica ligure/scirocco)
    if max_consecutive >= 6 and cumulata_tot >= 40.0:
        punteggio = max(punteggio, 1.0)
    elif max_consecutive >= 3 and cumulata_tot >= 15.0:
        punteggio = max(punteggio, 0.5)

    return min(punteggio, 1.5)

def _calcola_lro_temporali(cape_orario, rh_orario, vento_dir_orario, pioggia_oraria):
    """
    Calcola contributo temporali convettivi (max 1.5).
    Considera le specificità liguri (ARPAL): CAPE 300-800 J/kg è sufficiente 
    se combinato con elevata umidità e convergenze/pioggia.
    """
    if not cape_orario or all(c is None for c in cape_orario):
        return 0.0

    punteggio = 0.0
    
    for i in range(len(cape_orario)):
        cape = cape_orario[i] or 0
        rh = rh_orario[i] or 0
        pioggia = pioggia_oraria[i] or 0
        
        # Verifica forzanti (umidità alta e precipitazione in atto)
        forzante_attiva = (rh >= 80 and pioggia >= 2.0)
        
        if forzante_attiva:
            if cape >= 1500:
                punteggio = max(punteggio, 1.5)
            elif cape >= 800:
                punteggio = max(punteggio, 1.0)
            elif cape >= 300: # Soglia ligure abbassata
                punteggio = max(punteggio, 0.5)
        else:
            # Se il CAPE è alto ma isolato, senza forzanti dinamiche/umidità
            if cape >= 2000:
                punteggio = max(punteggio, 0.5) # Rischio potenziale ma inespresso
                
    return min(punteggio, 1.5)

def _calcola_lro_vento(raffiche_orarie):
    """
    Calcola contributo vento (max 1.5).
    Sotto 60: 0 | 60-70: 0.5 | 70-80: 1.0 | >80: 1.5
    """
    if not raffiche_orarie or all(r is None for r in raffiche_orarie):
        return 0.0

    max_gust = max(r for r in raffiche_orarie if r is not None)
    
    if max_gust >= 80: return 1.5
    if max_gust >= 70: return 1.0
    if max_gust >= 60: return 0.5
    return 0.0

def _calcola_lro_caldo(t_max_giornaliera):
    """
    Calcola contributo caldo (max 1.5).
    <34: 0 | >=34: 0.5 | >=36: 1.0 | >=38: 1.5
    """
    if t_max_giornaliera is None:
        return 0.0
        
    if t_max_giornaliera >= 38: return 1.5
    if t_max_giornaliera >= 36: return 1.0
    if t_max_giornaliera >= 34: return 0.5
    return 0.0

def _calcola_lro_afa(temp_orarie, rh_orarie, vpd_orarie):
    """
    Calcola contributo afa (max 1.5).
    Condizione base: T >= 27 E RH > 70%.
    Valutazione tramite combinazione con VPD (Vapour Pressure Deficit).
    """
    if not temp_orarie or all(t is None for t in temp_orarie):
        return 0.0

    punteggio = 0.0
    
    for i in range(len(temp_orarie)):
        t = temp_orarie[i] or 0
        rh = rh_orarie[i] or 0
        vpd = vpd_orarie[i] if (vpd_orarie and i < len(vpd_orarie) and vpd_orarie[i] is not None) else 1.0
        
        if t >= 27.0 and rh > 70.0:
            # Afa presente, calcoliamo la gravità
            if rh >= 85.0 or vpd <= 0.5:
                punteggio = max(punteggio, 1.5) # Molto marcato (saturazione vicina)
            elif rh >= 75.0 or vpd <= 0.8:
                punteggio = max(punteggio, 1.0) # Marcato
            else:
                punteggio = max(punteggio, 0.5) # Moderato
                
    return min(punteggio, 1.5)

def calcola_lro_giornaliero(dati_orari, dati_giornalieri, data_target_str):
    """
    Raccoglie i dati orari di un singolo giorno e calcola l'indice LRO completo.
    Versione ultra-protetta contro disallineamenti di liste e IndexError.
    """
    times = dati_orari.get("time", [])
    
    # Trova gli indici delle ore che appartengono alla giornata target
    indici_giorno = [i for i, t in enumerate(times) if t.startswith(data_target_str)]
    
    if not indici_giorno:
        return None
        
    # Funzione interna ultra-sicura: estrae ESATTAMENTE i 24 valori (o meno) di quel giorno
    def estrai_sicuro(chiave):
        arr = dati_orari.get(chiave, [])
        risultato = []
        for i in indici_giorno:
            if i < len(arr) and arr[i] is not None:
                risultato.append(arr[i])
            else:
                risultato.append(0.0) # Valore neutro di fallback se manca il dato orario
        return risultato

    pioggia = estrai_sicuro("precipitation")
    cape = estrai_sicuro("cape")
    rh = estrai_sicuro("relative_humidity_2m")
    vento_dir = estrai_sicuro("wind_direction_10m")
    raffiche = estrai_sicuro("wind_gusts_10m")
    temp = estrai_sicuro("temperature_2m")
    vpd = estrai_sicuro("vapour_pressure_deficit")
    
    # Calcolo della temperatura massima del giorno in modo sicuro
    t_max = max(temp) if temp else 0.0

    # Calcolo dei punteggi parziali passandogli le liste pulite e della stessa identica lunghezza
    score_pioggia = _calcola_lro_pioggia(pioggia)
    score_temporali = _calcola_lro_temporali(cape, rh, vento_dir, pioggia)
    score_vento = _calcola_lro_vento(raffiche)
    score_caldo = _calcola_lro_caldo(t_max)
    score_afa = _calcola_lro_afa(temp, rh, vpd)
    
    totale_grezzo = score_pioggia + score_temporali + score_vento + score_caldo + score_afa
    lro_totale = min(totale_grezzo, 5.0)

    # Formattazione stringa per il bollettino
    try:
        dt_obj = datetime.strptime(data_target_str, "%Y-%m-%d")
        data_formattata = dt_obj.strftime("%d/%m/%Y")
    except Exception:
        data_formattata = data_target_str
    
    blocco_testo = (
        f"[📅{data_formattata}]\n"
        f"❗️PUNTEGGIO: {lro_totale:.1f}/5\n\n"
        f"🌧Pioggia: {score_pioggia:.1f}/1.5\n"
        f"🌩Temporali: {score_temporali:.1f}/1.5\n"
        f"🍃Vento: {score_vento:.1f}/1.5\n"
        f"🔥Caldo: {score_caldo:.1f}/1.5\n"
        f"🥵Afa: {score_afa:.1f}/1.5\n"
    )

    return {
        "totale": lro_totale,
        "testo_formattato": blocco_testo
    }

# --- FINE SECONDA PARTE ---

# ==============================================================================
# SERIALIZZAZIONE DATI E CHIAMATA API GEMINI
# ==============================================================================

def prepara_compendio_orario(dati_orari, giorni_validi):
    """
    Raccoglie e compatta i dati orari significativi per i giorni analizzati.
    Questo evita di inviare dump json grezzi giganteschi a Gemini, prevenendo i 502/429.
    """
    compendio = []
    times = dati_orari.get("time", [])
    
    # Funzione interna protetta contro IndexError e chiavi mancanti
    def get_val(chiave, index):
        arr = dati_orari.get(chiave)
        if arr and isinstance(arr, list) and index < len(arr):
            return arr[index]
        return None

    for g_str in giorni_validi:
        indici = [i for i, t in enumerate(times) if t.startswith(g_str)]
        if not indici:
            continue
            
        g_data = {"data": g_str, "ore": []}
        
        for idx in indici:
            ora_completa = times[idx]
            ora_h = ora_completa.split("T")[1][:5] if "T" in ora_completa else ora_completa
            
            # Estrazione parametri principali e di quota sicura
            orario_info = {
                "ora": ora_h,
                "t2m": get_val("temperature_2m", idx),
                "rh2m": get_val("relative_humidity_2m", idx),
                "prec": get_val("precipitation", idx),
                "w_code": get_val("weather_code", idx),
                "gust": get_val("wind_gusts_10m", idx),
                "wind_spd": get_val("wind_speed_10m", idx),
                "wind_dir": get_val("wind_direction_10m", idx),
                "cape": get_val("cape", idx),
                "cin": get_val("convective_inhibition", idx),
                "li": get_val("lifted_index", idx),
                # Dati verticali termodinamici
                "t850": get_val("temperature_850hPa", idx),
                "t500": get_val("temperature_500hPa", idx),
                "gh500": get_val("geopotential_height_500hPa", idx),
                "rh700": get_val("relative_humidity_700hPa", idx),
            }
            g_data["ore"].append(orario_info)
            
        compendio.append(g_data)
        
    return compendio

def interroga_gemini(modello_display, compendio_dati, lro_testo_collettivo, ground_info):
    """
    Costruisce l'architettura del super-prompt e interroga l'API di Gemini.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "LA_TUA_GEMINI_API_KEY":
        print("  ⚠ API Key di Gemini non configurata. Salto la generazione del testo.")
        return None

    # Strutturazione del prompt con le 4 macro-aree richieste
    prompt = f"""
Sei un meteorologo professionista esperto del territorio della Liguria e in particolare della provincia di La Spezia (caratterizzata da microclimi complessi, interazioni sciroccali, convergenze nel Golfo e sollevamento orografico appenninico).

Analizza i seguenti dati tecnici strutturati e genera un bollettino previsionale rigoroso ed esaustivo, seguendo tassativamente la scaletta indicata sotto.

DATI TECNICI DI COMPENDIO (ORARI E QUOTA):
{json.dumps(compendio_dati, indent=2)}

INFORMAZIONI INIZIALI AL SUOLO (ORA 0):
{json.dumps(ground_info, indent=2)}

INDICI DI RISCHIO OGGETTIVO (LRO) CALCOLATI MATEMATICAMENTE:
{lro_testo_collettivo}

Modello meteorologico di riferimento utilizzato per il fetching: {modello_display}

---

REGOLE DI COMPILAZIONE DEL BOLLETTINO:
Genera l'output strutturato esattamente nei seguenti 4 macro-blocchi. Non inventare i dati, attieniti ai valori fisici forniti e applica la modellistica concettuale ARPAL (es. l'interazione tra tramontana scura e scirocco, gradienti termici verticali pesanti con aria fredda a 500hPa in estate, o tetti termo-igrometrici estivi).
ASSOLUTAMENTE NESSUNA FORMATTAZIONE MARKDOWN (NO ASTERISCHI, HASHTAG, GRASSETTO, ITALICO, CODICE, LINK, IMMAGINI). Tutto il testo deve essere in chiaro e leggibile.

1. PREVISIONI SEMPLICI
Fornisci per ogni giorno un riassunto chiaro e accessibile sull'evoluzione dello stato del cielo, dei venti e delle temperature (es. quando e quanto si annuvola, tempistiche precise delle piogge).

2. ANALISI TECNICA
Questa sezione deve essere estremamente approfondita, adatta a un appassionato di meteorologia. Analizza:
- La termodinamica della colonna d'aria (CAPE, CIN, Lifted Index correlati con la presenza o assenza di forzanti dinamiche al suolo o in quota).
- Il gradiente termico verticale (es. differenza T2m - T500hPa) e il geopotenziale a 500hPa per stimare la reattività dell'atmosfera.
- I flussi portanti nei bassi strati (850hPa) e al suolo per rilevare eventuali profili di wind shear o convergenze locali nello spezzino.

3. PUNTEGGIO OGGETTIVO
Riporta fedelmente, blocco per blocco e senza alcuna modifica, il testo dei punteggi LRO calcolati matematicamente che ti ho fornito sopra sotto la voce "INDICI DI RISCHIO OGGETTIVO (LRO)". Non ricalcolarli, usa quelli.

4. DESCRIZIONE GIORNALIERA E RISCHI
Delinea per ciascuna giornata un quadro dettagliato dei rischi specifici per il territorio spezzino (es. rischio idrogeologico per piogge persistenti stratiformi, colpi di vento/downburst in caso di fulminazioni associate a lapse rate elevati, ondate di calore o disagio bioclimatico da afa intensa in base alle soglie di umidità).
"""

    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL_PRIMARY}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
    }
    headers = {"Content-Type": "application/json"}

    for modello_chiamata in [GEMINI_MODEL_PRIMARY, GEMINI_MODEL_FALLBACK]:
        try:
            if modello_chiamata == GEMINI_MODEL_FALLBACK:
                url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL_FALLBACK}:generateContent?key={GEMINI_API_KEY}"
                print(f"  🔄 Tentativo di fallback con il modello {GEMINI_MODEL_FALLBACK}...")
            
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            
            if response.status_code == 429:
                print("  ⚠ Errore 429 (Quota Exceeded). Attesa di 10 secondi prima del retry...")
                time.sleep(10)
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                
            response.raise_for_status()
            res_json = response.json()
            
            testo_generato = res_json['candidates'][0]['content']['parts'][0]['text']
            return testo_generato
            
        except Exception as e:
            print(f"  ✗ Errore durante la chiamata a {modello_chiamata}: {e}")
            if modello_chiamata == GEMINI_MODEL_PRIMARY:
                continue
                
    return "Impossibile generare l'analisi dettagliata tramite le API di Gemini a causa di errori persistenti."

# --- FINE TERZA PARTE ---

# ==============================================================================
# INVIO TELEGRAM E FUNZIONE PRINCIPALE (ORCHESTRAZIONE)
# ==============================================================================

def invia_messaggio_telegram(testo):
    """
    Invia il bollettino generato alle chat Telegram impostate.
    Gestisce in automatico il limite dei 4096 caratteri di Telegram, 
    spezzando il testo in modo intelligente sui cambi riga.
    """
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "IL_TUO_TELEGRAM_TOKEN":
        print("\n  ⚠ Telegram non configurato. Stampo il bollettino finale a schermo:\n")
        print(testo)
        return

    # Margine di sicurezza sotto i 4096 caratteri nominali
    max_length = 4000
    parti = []

    # Algoritmo di partizionamento stringa sui newline
    while len(testo) > max_length:
        split_idx = testo.rfind("\n", 0, max_length)
        if split_idx == -1:
            split_idx = max_length
        parti.append(testo[:split_idx])
        testo = testo[split_idx:]
    parti.append(testo)

    # Ciclo di invio per ogni chat ID registrata
    for chat_id in TELEGRAM_CHAT_IDS:
        if chat_id == "LA_TUA_CHAT_ID":
            continue
            
        for idx, parte in enumerate(parti):
            print(f"  📤 Invio blocco {idx + 1}/{len(parti)} alla chat Telegram {chat_id}...")
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": parte
            }
            try:
                resp = requests.post(url, json=payload, timeout=25)
                resp.raise_for_status()
            except Exception as e:
                print(f"  ✗ Errore durante l'invio della parte {idx + 1}: {e}")
            
            # Pausa tecnica anti-flooding tra i blocchi di messaggio
            time.sleep(1.5)


def main():
    """
    Funzione di orchestrazione principale dell'intero script previsionale.
    """
    print("====================================================================")
    print("🚀 AVVIO SISTEMA METEOROLOGICO DI ANALISI AVANZATA - LA SPEZIA")
    print("====================================================================")
    
    now = datetime.now(TZ_ROME)
    print(f"⏰ Orario locale di esecuzione: {now.strftime('%d/%m/%Y %H:%M:%S')}")

    try:
        # 1. Fetching dinamico dei dati meteo dai modelli (AROME HD / AROME / ICON-EU)
        data, model_api_name, display_name = fetch_forecast_data(now)
        
        # 2. Verifica rigidità temporale e freschezza della run estratta
        is_fresh, msg_freshness = check_data_freshness(data, model_api_name, display_name, now)
        print(f"🔍 Controllo Freshness: {msg_freshness}")
        if not is_fresh:
            print("  ⚠ Nota: Lo script procede ugualmente, ma la run potrebbe non essere l'ultima disponibile.")

        hourly_data = data.get("hourly", {})
        daily_data = data.get("daily", {})
        times = hourly_data.get("time", [])

        if not times:
            raise ValueError("Dati temporali orari totalmente assenti nel feed Open-Meteo.")

        # 3. Estrazione dei giorni reali coperti dal feed, partendo dalla giornata odierna
        giorni_disponibili = sorted(list(set(t.split("T")[0] for t in times)))
        oggi_str = now.strftime("%Y-%m-%d")
        giorni_da_elaborare = [g for g in giorni_disponibili if g >= oggi_str]

        print(f"📅 Giorni totali validi identificati per l'analisi: {', '.join(giorni_da_elaborare)}")

        # 4. Calcolo dell'Indice di Rischio Oggettivo (LRO) sul motore matematico locale
        print("📊 Calcolo matematico degli indici LRO basato sulle soglie fisiche...")
        lro_collettivo_testo = ""
        for g_str in giorni_da_elaborare:
            risultato_giornaliero = calcola_lro_giornaliero(hourly_data, daily_data, g_str)
            if risultato_giornaliero:
                lro_collettivo_testo += risultato_giornaliero["testo_formattato"] + "\n"
                lro_collettivo_testo += "---------------------------------------\n"

        # 5. Estrazione delle condizioni meteo al suolo iniziali (Ora 0)
        timestamp_iniziale = times[0]
        ground_info = load_ground_conditions(hourly_data, timestamp_iniziale)

        # 6. Generazione del compendio compatto orario e di quota per ottimizzare i token
        compendio_compresso = prepara_compendio_orario(hourly_data, giorni_da_elaborare)

        # 7. Interrogazione dell'API di Gemini con inserimento delle 4 macro-aree richieste
        print("🧠 Interrogazione del modello AI Gemini per l'analisi fisica e strutturata...")
        bollettino_finale = interroga_gemini(display_name, compendio_compresso, lro_collettivo_testo, ground_info)

        # Meccanismo di Fallback protettivo se Gemini dovesse fallire completamente (errori 502/429 non gestiti)
        if not bollettino_finale or "Impossibile generare" in bollettino_finale:
            print("  ✗ Generazione AI fallita. Costruzione automatica del bollettino di emergenza...")
            bollettino_finale = (
                f"⚠️ BOLLETTINO DI EMERGENZA (SOLO DATI MATEMATICI LOCALI)\n"
                f"Modello meteorologico base: {display_name}\n\n"
                f"I sistemi di intelligenza artificiale hanno restituito un errore di comunicazione. "
                f"Vengono comunque trasmessi gli indici di rischio calcolati matematicamente dallo script:\n\n"
                f"{lro_collettivo_testo}"
            )

        # 8. Smistamento del testo finale alle API di Telegram
        invia_messaggio_telegram(bollettino_finale)
        print("\n🏁 [FINE SCRIPT] Procedura completata con successo in tutte le sue componenti.")

    except Exception as e:
        print(f"\n❌ ERRORE CRITICO NON GESTITO: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

# --- FINE QUARTA PARTE - FILE COMPLETO ---