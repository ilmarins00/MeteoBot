#!/usr/bin/env python3
"""
Previsioni Meteo – Generazione automatica con AI
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

HOURLY_VARS = [
    # Superficie e strato limite
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "wet_bulb_temperature_2m",
    "precipitation", "rain", "showers",
    "snowfall", "snow_depth", "weather_code", "pressure_msl",
    "surface_pressure", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "visibility",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "uv_index", "cape", "lifted_index", "convective_inhibition",
    "sunshine_duration",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance",
    "freezing_level_height", "vapour_pressure_deficit", "is_day",
    "et0_fao_evapotranspiration",
    # Livelli soprasuolo (disponibili in AROME; AROME HD non supporta >100 m)
    "temperature_20m", "temperature_50m", "temperature_100m",
    "temperature_150m", "temperature_200m",
    "wind_speed_20m", "wind_speed_50m", "wind_speed_100m",
    "wind_speed_150m", "wind_speed_200m",
    "wind_direction_20m", "wind_direction_50m", "wind_direction_100m",
    "wind_direction_150m", "wind_direction_200m",
    # Livelli di pressione principali (inclusi nel fetch primario)
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

# Variabili ai livelli di pressione – fetch supplementare completo per AROME
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

# Finestra di richiesta in giorni. Deve superare l'orizzonte nominale
# del modello per permettere l'inferenza dell'orario di run tramite i null di coda.
MODEL_HORIZONS = {
    "meteofrance_arome_france_hd": 3,   # 72h richiesti > 51h nominali
    "meteofrance_arome_france":     3,   # 72h richiesti > 48h nominali
    "icon_eu":                      5,   # 120h richiesti = orizzonte nominale
}

# Orizzonti nominali in ore. Usati per inferire run_init:
#   run_init ≈ last_valid_timestamp − horizon_hours
MODEL_HORIZONS_HOURS = {
    "meteofrance_arome_france_hd": 51,
    "meteofrance_arome_france":    48,
    "icon_eu":                     120,
}

# Soglia di obsolescenza. AROME gira ogni 6h con ~3-4h di latenza → 12h margine ok.
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
    """Scarica variabili ai livelli di pressione dal modello indicato.
    Se model_name è None, usa il best-match di Open-Meteo."""
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


def check_data_freshness(data, model_api_name, model_display, now):
    """
    Inferisce l'orario di inizializzazione della run NWP dall'ultimo timestamp
    non-null di temperature_2m, poi verifica che la run non sia obsoleta.

    Principio: la finestra richiesta (MODEL_HORIZONS in giorni) è volutamente
    più larga dell'orizzonte nominale del modello (MODEL_HORIZONS_HOURS).
    Le ore oltre il cutoff reale della run tornano come None in temperature_2m.
    L'ultimo indice non-null è la fine effettiva della previsione; da lì:

        run_init ≈ last_valid_timestamp − orizzonte_nominale_ore

    Se (now − run_init) > MAX_RUN_AGE_H la run è considerata obsoleta.

    Restituisce (ok: bool, messaggio: str).
    """
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return False, "Nessun dato orario disponibile"

    temps = hourly.get("temperature_2m", [])
    if not temps:
        return False, "temperature_2m non disponibile, impossibile verificare freshness"

    # Trova l'ultimo indice con valore non-null
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
    """Scarica dati da Open-Meteo usando l'orizzonte massimo per ogni modello.
    Restituisce (data, model_api_name, model_display_name)."""
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

                print(f"  ✓ {display}: {len(hours)} ore, "
                      f"{len([k for k in data.get('hourly', {}) if k != 'time'])} variabili totali")
                return data, model_name, display

            except Exception as e:
                print(f"  ✗ Errore: {e}")
                if attempt < max_retries:
                    time.sleep(2)

        print(f"  ✗ Falliti tutti i tentativi con {display}")

    raise RuntimeError("Impossibile ottenere dati meteo da nessun modello Open-Meteo")


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = f"""Sei un meteorologo professionista italiano. Ricevi dati meteo orari e giornalieri per {LOCATION_NAME} e devi scrivere le previsioni per il periodo indicato.
I dati coprono le ore rimanenti della giornata corrente e i giorni successivi fino all'orizzonte del modello (tipicamente 2-3 giorni).

Il tuo output DEVE contenere TRE sezioni separate dai marcatori "---SEZIONE TECNICA---" e "---SEZIONE RISCHI---" (esattamente così, ciascuno su una riga a sé).

═══ PRIMA SEZIONE: PREVISIONI SEMPLICI ═══

Scrivi un testo CONCISO in un UNICO BLOCCO CONTINUO senza andare a capo, comprensibile da chiunque. La lunghezza deve essere proporzionale al numero di giorni coperti: circa 600-800 caratteri per un giorno, fino a 1500 caratteri per tre giorni.

Struttura:
- Inizia con "Previsioni per {LOCATION_NAME}, [periodo coperto dai dati]."
- Per le ore rimanenti di oggi: descrivi brevemente cosa aspettarsi.
- Per ciascun giorno successivo presente nei dati: descrivi in sequenza le 4 fasce orarie (notte, mattina, pomeriggio, sera) in modo sintetico: cielo, temperature min/max, vento e precipitazioni solo se presenti. Indica alba e tramonto. Se i dati coprono solo una parte della giornata, descrivi solo le ore disponibili.
- Concludi con una frase riepilogativa sull'intero periodo.

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

Usa terminologia tecnica appropriata (avvezione, gradiente adiabatico, baroclinia, etc.) ma rimani comprensibile per un appassionato. Cita TUTTI i dati.

═══ TERZA SEZIONE: VALUTAZIONE RISCHI ═══

Dopo il marcatore "---SEZIONE RISCHI---", scrivi una valutazione dei possibili rischi meteorologici.

DEVI iniziare la sezione con ESATTAMENTE una di queste quattro righe (senza virgolette), a seconda del livello di rischio che emerge dai dati:
- VERDE se non ci sono rischi significativi
- GIALLO se c'è un possibile rischio locale o moderato
- ARANCIONE se c'è un rischio probabile
- ROSSO se il rischio è molto probabile o severo

═══ SOGLIE ARPAL – APPLICAZIONE OBBLIGATORIA E NON NEGOZIABILE ═══

PRIMA DI SCRIVERE QUALSIASI COSA nella sezione rischi, devi svolgere mentalmente questa procedura di controllo sistematico, parametro per parametro. Il livello finale è il MASSIMO tra tutti i parametri esaminati. Non è mai consentito abbassare il livello rispetto a quello imposto dalle soglie numeriche.

SOGLIE DI RIFERIMENTO ARPAL (Agenzia Regionale Protezione Ambiente Liguria):
- Pioggia oraria: VERDE < 15 mm/h | GIALLO >= 15 mm/h | ARANCIONE >= 30 mm/h | ROSSO >= 50 mm/h
- Pioggia cumulata 24h: VERDE < 80 mm | GIALLO >= 80 mm | ARANCIONE >= 150 mm | ROSSO >= 250 mm
- Vento/raffiche: VERDE < 50 km/h | GIALLO >= 50 km/h | ARANCIONE >= 80 km/h | ROSSO >= 100 km/h
- Caldo: VERDE < 35°C | GIALLO >= 35°C | ARANCIONE >= 38°C | ROSSO >= 40°C
- Gelo: VERDE > 0°C | GIALLO <= 0°C | ARANCIONE <= -5°C | ROSSO <= -10°C
- Neve: VERDE < 5 cm | GIALLO >= 5 cm | ARANCIONE >= 15 cm | ROSSO >= 30 cm
- Mareggiata (pressione): VERDE > 998 hPa | GIALLO <= 998 hPa | ARANCIONE <= 995 hPa | ROSSO <= 990 hPa
- Suolo saturo (API): >= 185 mm → rischio idrogeologico elevato (amplifica il livello di rischio pioggia di un grado)

REGOLE FERREE:
1. Controlla il valore MASSIMO di ogni parametro rilevante nell'intero periodo previsto.
2. Se anche UN SOLO valore supera una soglia, il livello NON PUÒ essere inferiore a quello corrispondente. Nessuna eccezione.
3. Se il suolo è saturo (API >= 185 mm o saturazione >= 85%) E sono previste precipitazioni, il livello di rischio pioggia DEVE essere elevato di un grado (VERDE→GIALLO, GIALLO→ARANCIONE, ARANCIONE→ROSSO).
4. In caso di dubbio tra due livelli, scegli sempre il più alto.
5. Non attribuire MAI un livello inferiore motivandolo con "probabilità bassa" o "fenomeni passeggeri": le soglie sono oggettive e si applicano ai valori previsti, non alla loro probabilità soggettiva.
6. VERDE è consentito SOLO se TUTTI i parametri restano sotto le rispettive soglie GIALLO.

DATI INTEGRATIVI disponibili nel prompt:
- Se presenti i dati del terreno: usa la saturazione del suolo (%) e l'API (mm) per valutare il rischio idrogeologico. Un terreno saturo amplifica enormemente il rischio di allagamenti e frane.
- Se presenti i dati termodinamici della stazione (SBCAPE, MUCAPE, bulk_shear, lifted_index): usali per valutare il rischio convettivo. Confrontali con i valori previsti dal modello.
- Se presente l'allerta ARPAL attuale: menzionala come contesto.

REGOLA FONDAMENTALE SULLA BREVITÀ:
- Se NON ci sono rischi significativi (tutti i parametri sotto soglia GIALLO), scrivi SOLO:
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


GEMINI_MODEL_PRIMARY = "gemini-3.1-pro-preview"
GEMINI_MODEL_FALLBACK = "gemini-3-flash-preview"


def generate_forecast(weather_data, model_used, date_range_info, api_key, ground_data=None):
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

    # Prova prima con Gemini 3.1 Pro Preview, poi fallback su 3 Flash Preview
    models_to_try = [
        (GEMINI_MODEL_PRIMARY, "3.1 Pro Preview"),
        (GEMINI_MODEL_FALLBACK, "3 Flash Preview (fallback)"),
    ]

    for gemini_model, gemini_label in models_to_try:
        print(f"  Modello Gemini: {gemini_label} ({gemini_model})")

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingLevel": "medium"},
            },
        }

        url = f"{GEMINI_API_BASE}/models/{gemini_model}:generateContent?key={api_key}"
        max_retries = 3
        success = False
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=180)

                # 404 = modello non disponibile → prova il fallback
                if resp.status_code == 404:
                    print(f"  ⚠ Modello {gemini_model} non disponibile (404), "
                          f"provo il fallback...")
                    last_error = f"404 per {gemini_model}"
                    break  # esci dal loop dei retry, passa al modello successivo

                # 429 = rate limit → attendi e riprova sullo stesso modello
                if resp.status_code == 429 and attempt < max_retries:
                    wait = 60
                    print(f"  ⚠ Rate limit (429), attendo {wait}s "
                          f"({attempt}/{max_retries})...")
                    time.sleep(wait)
                    continue

                if resp.status_code == 429:
                    last_error = f"Rate limit persistente su {gemini_model}"
                    break  # prova il fallback

                resp.raise_for_status()
                success = True
                break

            except requests.exceptions.Timeout:
                print(f"  ⚠ Timeout ({attempt}/{max_retries})...")
                if attempt < max_retries:
                    time.sleep(5)
                    continue
                last_error = f"Timeout su {gemini_model}"
                break

            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                break

        if not success:
            print(f"  ✗ {last_error}")
            continue  # prova il modello successivo

        result = resp.json()

        candidates = result.get("candidates", [])
        if not candidates:
            block_reason = result.get("promptFeedback", {}).get("blockReason", "sconosciuto")
            print(f"  ✗ Risposta bloccata da Gemini ({block_reason}), provo fallback...")
            continue

        finish_reason = candidates[0].get("finishReason", "")
        if finish_reason == "SAFETY":
            print(f"  ✗ Risposta bloccata per sicurezza, provo fallback...")
            continue

        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not text:
            print(f"  ✗ Risposta vuota (finishReason: {finish_reason}), provo fallback...")
            continue

        print(f"  ✓ Risposta ottenuta da {gemini_label}")
        return text.strip(), gemini_model

    raise RuntimeError(
        "Impossibile ottenere una risposta da nessun modello Gemini "
        f"({GEMINI_MODEL_PRIMARY} e {GEMINI_MODEL_FALLBACK})"
    )


def send_telegram(text, target_chat_id=None):
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

    print(f"\nOra: {now.strftime('%H:%M')} di {format_date_it(today_dt)}")
    print(f"Località: {LOCATION_NAME} ({LATITUDE}°N, {LONGITUDE}°E)")

    # 1. Scarica dati meteo
    print("\n📡 Scaricamento dati Open-Meteo...")
    weather_data, model_api_name, model_used = fetch_forecast_data(today_dt)

    # 1a. Verifica aggiornamento run NWP e ricava fine effettiva copertura
    #     (prima del filtro sull'ora corrente, così temperature_2m è ancora
    #     integro con i null di coda oltre l'orizzonte del modello)
    print("\n🔍 Verifica aggiornamento run NWP...")
    fresh_ok, fresh_msg = check_data_freshness(weather_data, model_api_name, model_used, now)
    if fresh_ok:
        print(f"  ✓ {fresh_msg}")
    else:
        print(f"  ⚠ ATTENZIONE: {fresh_msg}")

    # Ricava la fine effettiva della copertura dall'ultimo valore non-null
    # di temperature_2m — questo è il vero orizzonte della run scaricata
    _temps_raw = weather_data.get("hourly", {}).get("temperature_2m", [])
    _times_raw = weather_data.get("hourly", {}).get("time", [])
    actual_end_dt = tomorrow_dt  # fallback conservativo
    for _i in range(len(_temps_raw) - 1, -1, -1):
        if _temps_raw[_i] is not None and _i < len(_times_raw):
            try:
                actual_end_dt = datetime.fromisoformat(_times_raw[_i]).replace(tzinfo=TZ_ROME)
            except ValueError:
                pass
            break
    print(f"  ✓ Fine effettiva copertura: {actual_end_dt.strftime('%d/%m %H:%M')} "
          f"({(actual_end_dt - now).total_seconds() / 3600:.0f}h da ora)")

    # 1b. Filtra dati orari: dalle ore correnti in poi
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

    # 1c. Carica condizioni terreno e termodinamica attuale
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
        f"fino alle {actual_end_dt.strftime('%H:00')} di {format_date_it(actual_end_dt)}"
    )
    forecast_text, gemini_model = generate_forecast(
        weather_data, model_used, date_range_info, GEMINI_API_KEY, ground_data
    )

    print(f"\n--- Previsioni ({len(forecast_text)} caratteri) ---")
    print(forecast_text)
    print("---")

    # 3. Componi e invia messaggio Telegram
    print("\n📤 Invio via Telegram...")
    freshness_warning = "" if fresh_ok else f"⚠️ {fresh_msg}\n"
    header = (
        f"🌤 Previsioni Meteo\n"
        f"📍 {LOCATION_NAME}\n"
        f"📅 {today_dt.strftime('%d/%m/%Y')} – {actual_end_dt.strftime('%d/%m/%Y')}\n"
        f"🔬 Modello: {model_used} | AI: {gemini_model}\n"
        f"{freshness_warning}\n"
    )

    SEP_TECH = "---SEZIONE TECNICA---"
    SEP_RISK = "---SEZIONE RISCHI---"

    remaining = forecast_text
    if SEP_TECH in remaining:
        simple_part, remaining = remaining.split(SEP_TECH, 1)
    else:
        simple_part, remaining = remaining, ""

    if SEP_RISK in remaining:
        tech_part, risk_part = remaining.split(SEP_RISK, 1)
    else:
        tech_part, risk_part = remaining, ""

    simple_part = simple_part.strip()
    tech_part = tech_part.strip()
    risk_part = risk_part.strip()

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

    body = simple_part
    if tech_part:
        body += "\n\n📊 Analisi Tecnica\n\n" + tech_part
    body += "\n\n" + risk_block
    full_msg = header + body

    if send_telegram(full_msg, target_chat_id=target_chat_id):
        print("\n✅ Previsioni inviate con successo (messaggio unico)")
    else:
        print("  ⚠ Messaggio unico troppo lungo, invio in 3 parti...")
        date_line = f"📅 {today_dt.strftime('%d/%m/%Y')} – {actual_end_dt.strftime('%d/%m/%Y')}"

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