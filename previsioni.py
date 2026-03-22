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

STATE_FILE = "state.json"
STORICO_FILE = "storico_24h.json"

HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "precipitation", "rain", "showers",
    "snowfall", "snow_depth", "weather_code", "pressure_msl",
    "surface_pressure", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "visibility",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "uv_index", "cape", "lifted_index", "convective_inhibition",
    "sunshine_duration",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "freezing_level_height", "vapour_pressure_deficit", "is_day",
    # Livelli di pressione supportati da AROME HD
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

# Variabili aggiuntive a livelli di pressione (richieste con modello GFS)
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

# Modelli in ordine di preferenza: (nome API, nome display, tentativi max)
MODELS = [
    ("meteofrance_arome_france_hd", "AROME HD", 3),
    ("meteofrance_arome_france", "AROME", 3),
    ("icon_eu", "ICON-EU", 1),
]

MODEL_HORIZONS = {
    "meteofrance_arome_france_hd": 3,   # ~51h → richiedi 3 gg, restituisce ciò che ha
    "meteofrance_arome_france":     3,   # ~48h
    "icon_eu":                      5,   # ~120h
}

MIN_FUTURE_HOURS = 24   # soglia minima di copertura futura considerata "fresca"
MAX_START_LAG_H  = 6    # ore massime di ritardo sull'inizio dei dati

# ── Utilità ──────────────────────────────────────────────────────────────

def format_date_it(dt):
    """Formatta una data in italiano (es. 'mercoledì 12 marzo 2025')."""
    return f"{GIORNI_IT[dt.weekday()]} {dt.day} {MESI_IT[dt.month - 1]} {dt.year}"


# ── Open-Meteo ───────────────────────────────────────────────────────────

def load_ground_conditions():
    """Carica condizioni del terreno e dati termodinamici attuali da state.json e storico_24h."""
    ground = {}
    import os
    base = os.path.dirname(os.path.abspath(__file__))

    # state.json
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

    # storico_24h.json — ultimo record
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
    """Singola richiesta a Open-Meteo. Solleva eccezione in caso di errore."""
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
    """Rimuove dalle hourly le variabili che hanno tutti valori None (non supportate)."""
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


def _fetch_pressure_levels(start_date_str, end_date_str):
    """Chiamata supplementare senza modello specifico (best_match/GFS) per dati
    a livelli di pressione aggiuntivi (925, 700, 300 hPa, umidità in quota)."""
    try:
        params = {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(PRESSURE_LEVEL_VARS),
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
            print(f"  ⚠ Errore livelli pressione supplementari: {data.get('reason')}")
            return {}
        hourly = data.get("hourly", {})
        # Restituisci solo le variabili con dati validi
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

def check_data_freshness(data, model_used, now):
    """
    Controlla che i dati non siano obsoleti.
    Restituisce (ok: bool, messaggio: str).
    """
    times = data.get("hourly", {}).get("time", [])
    if not times:
        return False, "Nessun dato orario disponibile"

    # Parsing primo e ultimo timestamp
    fmt = "%Y-%m-%dT%H:%M"
    try:
        first_dt = datetime.strptime(times[0],  fmt).replace(tzinfo=TZ_ROME)
        last_dt  = datetime.strptime(times[-1], fmt).replace(tzinfo=TZ_ROME)
    except ValueError:
        # Prova senza minuti (formato "2025-03-22T06:00")
        fmt = "%Y-%m-%dT%H:%M"
        first_dt = datetime.fromisoformat(times[0]).replace(tzinfo=TZ_ROME)
        last_dt  = datetime.fromisoformat(times[-1]).replace(tzinfo=TZ_ROME)

    hours_ahead  = (last_dt  - now).total_seconds() / 3600
    hours_behind = (now - first_dt).total_seconds() / 3600

    if hours_behind > MAX_START_LAG_H:
        return False, (
            f"Dati potenzialmente obsoleti [{model_used}]: "
            f"primo dato {hours_behind:.0f}h fa ({times[0]})"
        )
    if hours_ahead < MIN_FUTURE_HOURS:
        return False, (
            f"Copertura insufficiente [{model_used}]: "
            f"solo {hours_ahead:.0f}h di previsione futura (min. {MIN_FUTURE_HOURS}h)"
        )

    return True, (
        f"Run aggiornata: {len(times)} ore totali, "
        f"copertura futura {hours_ahead:.0f}h (fino a {times[-1]})"
    )

def fetch_forecast_data(start_date):
    """Scarica dati da Open-Meteo usando l'orizzonte massimo per ogni modello."""
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
                extra = _fetch_pressure_levels(start_str, end_str)
                if extra:
                    hourly = data.get("hourly", {})
                    for key, vals in extra.items():
                        if key not in hourly:
                            hourly[key] = vals

                print(f"  ✓ {display}: {len(hours)} ore, "
                      f"{len([k for k in data.get('hourly', {}) if k != 'time'])} variabili totali")
                return data, display

            except Exception as e:
                print(f"  ✗ Errore: {e}")
                if attempt < max_retries:
                    time.sleep(2)

        print(f"  ✗ Falliti tutti i tentativi con {display}")

    raise RuntimeError("Impossibile ottenere dati meteo da nessun modello Open-Meteo")


# ── Google Gemini ────────────────────────────────────────────────────────

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = f"""Sei un meteorologo professionista italiano. Ricevi dati meteo orari e giornalieri per {LOCATION_NAME} e devi scrivere le previsioni per il periodo indicato.
I dati possono coprire le ore rimanenti della giornata corrente e l'intera giornata successiva.

Il tuo output DEVE contenere TRE sezioni separate dai marcatori "---SEZIONE TECNICA---" e "---SEZIONE RISCHI---" (esattamente così, ciascuno su una riga a sé).

═══ PRIMA SEZIONE: PREVISIONI SEMPLICI ═══

Scrivi un testo BREVE e CONCISO (massimo 600-800 caratteri), in un UNICO BLOCCO CONTINUO senza andare a capo, comprensibile da chiunque.

Struttura:
- Inizia con "Previsioni per {LOCATION_NAME}, [periodo coperto dai dati]."
- Per le ore rimanenti di oggi: descrivi brevemente cosa aspettarsi.
- Per domani: descrivi in sequenza le 4 fasce orarie (notte, mattina, pomeriggio, sera) in modo sintetico: cielo, temperature min/max, vento e precipitazioni solo se presenti.
- Indica alba e tramonto di domani.
- Concludi con una frase riepilogativa.

Regole:
- Temperature arrotondate a un decimale. Precipitazioni in mm. Vento in km/h con direzione cardinale.
- Nuvolosità a parole: sereno, poco nuvoloso, parzialmente nuvoloso, nuvoloso, molto nuvoloso, coperto.
- NON usare emoji. NON usare formattazione Markdown. Sii sintetico ma completo.
- Se nel testo citi avvisi o segnalazioni, indica SOLO il tipo di fenomeno SENZA valori numerici tra parentesi (es. scrivi "pioggia forte" e NON "pioggia forte (14 mm/h)").

═══ SECONDA SEZIONE: ANALISI TECNICA ═══

Dopo il marcatore "---SEZIONE TECNICA---", scrivi un'analisi meteorologica tecnica dettagliata, anche questa in formato testo continuo (un unico blocco senza andare a capo). Questa sezione è rivolta a un appassionato di meteorologia e deve includere:

- Temperature ai diversi livelli di pressione disponibili (925, 850, 700, 500, 300 hPa) con le relative variazioni nel corso della giornata.
- Venti in quota (850, 500, 300 hPa): velocità, direzione e eventuali variazioni significative che indicano avvezione calda/fredda o rotazione.
- Altezze geopotenziali (1000, 850, 700, 500, 300 hPa) e spessori derivati (es. 500-1000 hPa) con implicazioni per la massa d'aria.
- Analisi termodinamica: CAPE (J/kg), Lifted Index, CIN (Convective Inhibition). Se CAPE > 0 commenta il potenziale convettivo; se Lifted Index < 0 il grado di instabilità.
- Livello dello zero termico (freezing level height) e implicazioni per neve/pioggia.
- Umidità relativa ai vari livelli e implicazioni per la formazione di nubi a diverse quote.
- Gradiente termico verticale (differenza temperatura tra livelli) per valutare stabilità/instabilità.
- Deficit di pressione di vapore (VPD) e implicazioni per evapotraspirazione.
- Se ci sono dati di radiazione: analisi radiativa breve.

Usa terminologia tecnica appropriata (avvezione, gradiente adiabatico, baroclinia, etc.) ma rimani comprensibile per un appassionato.

═══ TERZA SEZIONE: VALUTAZIONE RISCHI ═══

Dopo il marcatore "---SEZIONE RISCHI---", scrivi una valutazione dei possibili rischi meteorologici.

DEVI iniziare la sezione con ESATTAMENTE una di queste quattro righe (senza virgolette), a seconda del livello di rischio che emerge dai dati:
- VERDE se non ci sono rischi significativi
- GIALLO se c'è un possibile rischio locale o moderato
- ARANCIONE se c'è un rischio probabile
- ROSSO se il rischio è molto probabile o severo

SOGLIE DI RIFERIMENTO ARPAL (Agenzia Regionale Protezione Ambiente Liguria):
- Pioggia oraria: Giallo >= 15 mm/h, Arancione >= 30 mm/h, Rosso >= 50 mm/h
- Pioggia cumulata 24h: Giallo >= 80 mm, Arancione >= 150 mm, Rosso >= 250 mm
- Vento/raffiche: Giallo >= 50 km/h, Arancione >= 80 km/h, Rosso >= 100 km/h
- Caldo: Giallo >= 35°C, Arancione >= 38°C, Rosso >= 40°C
- Gelo: Giallo <= 0°C, Arancione <= -5°C, Rosso <= -10°C
- Neve: Giallo >= 5 cm, Arancione >= 15 cm, Rosso >= 30 cm
- Mareggiata (pressione): Giallo <= 998 hPa, Arancione <= 995 hPa, Rosso <= 990 hPa
- Suolo molto saturo (API): >= 185 mm → rischio idrogeologico elevato

DATI INTEGRATIVI disponibili nel prompt:
- Se presenti i dati del terreno: usa la saturazione del suolo (%) e l'API (mm) per valutare il rischio idrogeologico. Un terreno saturo (>85%) amplifica enormemente il rischio di allagamenti e frane anche con piogge moderate.
- Se presenti i dati termodinamici della stazione (SBCAPE, MUCAPE, bulk_shear, lifted_index): usali per valutare il rischio convettivo. Confrontali con i valori previsti dal modello.
- Se presente l'allerta ARPAL attuale: menzionala come contesto.

REGOLA FONDAMENTALE SULLA BREVITÀ:
- Se NON ci sono rischi significativi, scrivi SOLO:
  VERDE
  Nessun rischio significativo previsto.
  E BASTA. Non aggiungere NIENTE altro. NIENTE. Solo quelle due righe.

- Se CI SONO rischi significativi, menziona ESCLUSIVAMENTE i fenomeni rilevanti. NON parlare dei parametri nella norma. Scrivi in modo DISCORSIVO, spiegando il perché del rischio e indicando probabilità approssimative. NON elencare dati grezzi, NON citare valori numerici tra parentesi negli avvisi.

═══ REGOLE GENERALI ═══

- Basati SOLO sui dati numerici forniti, non inventare nulla.
- Se un dato di quota non è disponibile (null/None), non menzionarlo.
- Scrivi testi completi, non troncare mai a metà frase.
- NON usare emoji in nessuna delle tre sezioni.
- NON usare formattazione Markdown (no asterischi, no underscore, no backtick).
- Negli avvisi o segnalazioni: indica SOLO il tipo di fenomeno, MAI i valori numerici tra parentesi."""


GEMINI_MODEL = "gemini-2.5-flash"


def generate_forecast(weather_data, model_used, date_range_info, api_key, ground_data=None):
    """Invia i dati meteo a Gemini e ottiene le previsioni in linguaggio naturale."""
    print(f"  Modello Gemini: {GEMINI_MODEL}")

    hourly = weather_data.get("hourly", {})
    daily = weather_data.get("daily", {})

    user_prompt = (
        f"Dati meteo per {LOCATION_NAME}. {date_range_info}. "
        f"Modello meteorologico utilizzato: {model_used}.\n\n"
        f"DATI ORARI:\n"
        f"{json.dumps(hourly, indent=2, ensure_ascii=False)}\n\n"
        f"DATI GIORNALIERI AGGREGATI:\n"
        f"{json.dumps(daily, indent=2, ensure_ascii=False)}\n\n"
    )

    if ground_data:
        user_prompt += (
            f"CONDIZIONI ATTUALI DEL TERRENO E TERMODINAMICA (dati della stazione locale):\n"
            f"{json.dumps(ground_data, indent=2, ensure_ascii=False)}\n\n"
        )

    user_prompt += "Scrivi le previsioni seguendo rigorosamente le istruzioni fornite."

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingBudget": 2048},
        },
    }

    # Usa Gemini Flash con retry
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code == 429 and attempt < max_retries:
            wait = 60
            print(f"  ⚠ Rate limit (429), attendo {wait}s ({attempt}/{max_retries})...")
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            raise RuntimeError("Gemini Flash rate-limited dopo tutti i tentativi")
        resp.raise_for_status()
        break

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

    return text.strip(), GEMINI_MODEL


# ── Telegram ─────────────────────────────────────────────────────────────

def send_telegram(text, target_chat_id=None):
    """Invia le previsioni ai chat Telegram configurati (o a uno specifico).
    Restituisce True se l'invio è riuscito per almeno un chat."""
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
            if resp.status_code == 400:
                print(f"  ⚠ Messaggio troppo lungo per {chat_id} ({len(text)} char)")
                return False
            resp.raise_for_status()
            if resp.json().get("ok"):
                print(f"✓ Inviato a {chat_id}")
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
    today = now.date()
    tomorrow = today + timedelta(days=1)
    today_dt = datetime.combine(today, datetime.min.time()).replace(tzinfo=TZ_ROME)
    tomorrow_dt = datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=TZ_ROME)

    print(f"\nPeriodo: dalle {now.strftime('%H:%M')} di {format_date_it(today_dt)} a fine {format_date_it(tomorrow_dt)}")
    print(f"Località: {LOCATION_NAME} ({LATITUDE}°N, {LONGITUDE}°E)")

    # 1. Scarica dati meteo (oggi + domani)
    print("\n📡 Scaricamento dati Open-Meteo...")
    weather_data, model_used = fetch_forecast_data(today_dt)

    print("\n🔍 Verifica aggiornamento dati...")
fresh_ok, fresh_msg = check_data_freshness(weather_data, model_used, now)
if fresh_ok:
    print(f"  ✓ {fresh_msg}")
else:
    print(f"  ⚠ ATTENZIONE: {fresh_msg}")

    # 1a. Filtra dati orari: dalle ore correnti in poi
    hourly = weather_data.get("hourly", {})
    times = hourly.get("time", [])
    current_hour_str = now.strftime("%Y-%m-%dT%H:00")
    start_idx = 0
    for i, t in enumerate(times):
        if t >= current_hour_str:
            start_idx = i
            break
    if start_idx > 0:
        for key in hourly:
            if isinstance(hourly[key], list):
                hourly[key] = hourly[key][start_idx:]
        print(f"  ✓ Dati filtrati: da {times[start_idx] if start_idx < len(times) else '?'} ({len(hourly.get('time', []))} ore)")

    # 1b. Carica condizioni terreno e termodinamica attuale
    print("\n🌱 Caricamento condizioni terreno...")
    ground_data = load_ground_conditions()
    if ground_data:
        sat = ground_data.get("suolo", {}).get("saturazione_perc")
        api_val = ground_data.get("suolo", {}).get("api_mm")
        print(f"  ✓ Saturazione: {sat}% | API: {api_val} mm")
    else:
        print("  ⚠ Dati terreno non disponibili")

    # 2. Genera previsioni con AI
    print("\n🤖 Generazione previsioni con AI...")
    date_range_info = (
        f"Periodo: dalle ore {now.strftime('%H:00')} di {format_date_it(today_dt)} "
        f"fino alle 23:00 di {format_date_it(tomorrow_dt)}"
    )
    forecast_text, gemini_model = generate_forecast(
        weather_data, model_used, date_range_info, GEMINI_API_KEY, ground_data
    )

    print(f"\n--- Previsioni ({len(forecast_text)} caratteri) ---")
    print(forecast_text)
    print("---")

    # 3. Componi e invia messaggio Telegram
    print("\n📤 Invio via Telegram...")
    header = (
        f"🌤 Previsioni Meteo\n"
        f"📍 {LOCATION_NAME}\n"
        f"📅 {today_dt.strftime('%d/%m/%Y')} – {tomorrow_dt.strftime('%d/%m/%Y')}\n"
        f"🔬 Modello: {model_used} | AI: {gemini_model}\n\n"
    )

    # Componi messaggio unico: semplice + tecnica + rischi
    SEP_TECH = "---SEZIONE TECNICA---"
    SEP_RISK = "---SEZIONE RISCHI---"

    remaining = forecast_text
    # Estrai sezione semplice
    if SEP_TECH in remaining:
        simple_part, remaining = remaining.split(SEP_TECH, 1)
    else:
        simple_part, remaining = remaining, ""

    # Estrai sezione tecnica e rischi
    if SEP_RISK in remaining:
        tech_part, risk_part = remaining.split(SEP_RISK, 1)
    else:
        tech_part, risk_part = remaining, ""

    simple_part = simple_part.strip()
    tech_part = tech_part.strip()
    risk_part = risk_part.strip()

    # Componi la sezione rischi
    RISK_COLORS = {
        "VERDE": "🟢", "GIALLO": "🟡",
        "ARANCIONE": "🟠", "ROSSO": "🔴",
    }
    if risk_part:
        lines = risk_part.split("\n", 1)
        color_word = lines[0].strip().upper()
        emoji = RISK_COLORS.get(color_word, "🟢")
        risk_desc = lines[1].strip() if len(lines) > 1 else "Nessun rischio previsto."
        risk_block = f"{emoji} RISCHI POSSIBILI\n\n{risk_desc}"
    else:
        risk_block = "🟢 RISCHI POSSIBILI\n\nNessun rischio previsto."

    # Prova prima messaggio unico
    body = simple_part
    if tech_part:
        body += "\n\n📊 Analisi Tecnica\n\n" + tech_part
    body += "\n\n" + risk_block
    full_msg = header + body

    if send_telegram(full_msg, target_chat_id=target_chat_id):
        print("\n✅ Previsioni inviate con successo (messaggio unico)")
    else:
        # Messaggio troppo lungo → dividi in 3 messaggi logici
        print("  ⚠ Messaggio unico troppo lungo, invio in 3 parti...")
        date_line = f"📅 {today_dt.strftime('%d/%m/%Y')} – {tomorrow_dt.strftime('%d/%m/%Y')}"

        msg1 = header + simple_part
        msg2 = f"📊 Analisi Tecnica\n📍 {LOCATION_NAME} · {date_line}\n\n{tech_part}" if tech_part else None
        msg3 = f"{risk_block}"

        ok = send_telegram(msg1, target_chat_id=target_chat_id)
        if msg2:
            ok = send_telegram(msg2, target_chat_id=target_chat_id) and ok
        ok = send_telegram(msg3, target_chat_id=target_chat_id) and ok

        if ok:
            print("\n✅ Previsioni inviate con successo (3 messaggi)")
        else:
            print("\n⚠️ Invio fallito")
            sys.exit(1)


if __name__ == "__main__":
    main()
