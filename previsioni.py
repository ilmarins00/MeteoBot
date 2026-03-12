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


def _fetch_pressure_levels(date_str):
    """Chiamata supplementare senza modello specifico (best_match/GFS) per dati
    a livelli di pressione aggiuntivi (925, 700, 300 hPa, umidità in quota)."""
    try:
        params = {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(PRESSURE_LEVEL_VARS),
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


def fetch_forecast_data(target_date):
    """Scarica dati orari da Open-Meteo provando i modelli in ordine di preferenza.
    Integra automaticamente dati a livelli di pressione supplementari da GFS."""
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

                # Rimuovi variabili senza dati
                data = _strip_null_vars(data)

                # Integra livelli di pressione supplementari (GFS/best_match)
                print("  📊 Richiesta livelli di pressione supplementari...")
                extra = _fetch_pressure_levels(date_str)
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

SYSTEM_PROMPT = f"""Sei un meteorologo professionista italiano. Ricevi dati meteo orari e giornalieri per {LOCATION_NAME} e devi scrivere le previsioni per la giornata indicata.

Il tuo output DEVE contenere TRE sezioni separate dai marcatori "---SEZIONE TECNICA---" e "---SEZIONE RISCHI---" (esattamente così, ciascuno su una riga a sé).

═══ PRIMA SEZIONE: PREVISIONI SEMPLICI ═══

Scrivi un testo BREVE e CONCISO (massimo 600-800 caratteri), in un UNICO BLOCCO CONTINUO senza andare a capo, comprensibile da chiunque.

Struttura:
- Inizia con "Previsioni per {LOCATION_NAME}, [giorno della settimana] [giorno] [mese] [anno]."
- Descrivi in sequenza le 4 fasce orarie (notte, mattina, pomeriggio, sera) in modo sintetico: cielo, temperature min/max, vento e precipitazioni solo se presenti.
- Indica alba e tramonto.
- Concludi con una frase riepilogativa.

Regole:
- Temperature arrotondate a un decimale. Precipitazioni in mm. Vento in km/h con direzione cardinale.
- Nuvolosità a parole: sereno, poco nuvoloso, parzialmente nuvoloso, nuvoloso, molto nuvoloso, coperto.
- NON usare emoji. NON usare formattazione Markdown. Sii sintetico ma completo.

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

Dopo il marcatore "---SEZIONE RISCHI---", scrivi una valutazione dei possibili rischi meteorologici per la giornata.

DEVI iniziare la sezione con ESATTAMENTE una di queste quattro righe (senza virgolette), a seconda del livello di rischio che emerge dai dati:
- VERDE se non ci sono rischi significativi o il rischio è molto basso/trascurabile
- GIALLO se c'è un possibile rischio locale o moderato
- ARANCIONE se c'è un rischio probabile
- ROSSO se il rischio è molto probabile o severo

Dopo la riga del colore, descrivi i rischi in modo REALISTICO basandoti esclusivamente sui dati numerici. Non esagerare, non minimizzare. Sii oggettivo.

Rischi da valutare (SOLO se supportati dai dati):
- Precipitazioni intense (accumuli > 20 mm in poche ore)
- Temporali (CAPE elevato, Lifted Index negativo)
- Vento forte (raffiche > 50 km/h)
- Neve a bassa quota (zero termico basso + precipitazioni)
- Gelate (temperature minime sotto 0°C)
- Nebbia (umidità alta + vento debole + inversione termica)
- Ondate di calore (temperature molto sopra media + UHI)
- Visibilità ridotta
- Rischio idrogeologico (precipitazioni prolungate su terreno saturo)

Se NON ci sono rischi significativi (giornata tranquilla, senza fenomeni rilevanti), scrivi "VERDE" come colore e poi "Nessun rischio previsto." come descrizione.

IMPORTANTE: sii REALISTICO. Un po' di pioggia non è un rischio. Vento a 20 km/h non è un rischio. Valuta con equilibrio professionale.

═══ REGOLE GENERALI ═══

- Basati SOLO sui dati numerici forniti, non inventare nulla.
- Se un dato di quota non è disponibile (null/None), non menzionarlo.
- Scrivi testi completi, non troncare mai a metà frase.
- NON usare emoji in nessuna delle tre sezioni.
- NON usare formattazione Markdown (no asterischi, no underscore, no backtick)."""


def get_latest_gemini_model(api_key):
    """Interroga l'API Gemini per trovare il modello flash più recente."""
    url = f"{GEMINI_API_BASE}/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except Exception as e:
        print(f"  ⚠ Impossibile listare modelli Gemini ({e}), uso default")
        return "gemini-2.5-pro-preview-05-06"

    # Filtra modelli pro che supportano generateContent
    # Escludi vecchi gemini-pro 1.0 e varianti specializzate (tts, embedding, etc.)
    EXCLUDE = {"tts", "embedding", "image", "vision", "tuning"}
    pro = []
    for m in models:
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        if ("generateContent" in methods
                and "pro" in name
                and "gemini-2" in name
                and not any(x in name for x in EXCLUDE)):
            pro.append(name)

    if not pro:
        return "gemini-2.5-pro-preview-05-06"

    # Preferisci modelli senza suffissi sperimentali, poi i più recenti
    def sort_key(name):
        # Nomi "puliti" (senza preview) prima, poi per nome decrescente
        is_stable = "preview" not in name
        return (is_stable, name)
    pro.sort(key=sort_key, reverse=True)
    return pro[0]


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

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingBudget": 2048},
        },
    }

    # Prova Pro (3 tentativi, 60s tra uno e l'altro → ~3 min max)
    # Se Pro è rate-limited, usa Flash (stesso thinking)
    models_to_try = [gemini_model, "gemini-2.5-flash"]
    for model in models_to_try:
        url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={api_key}"
        max_retries = 3 if model == gemini_model else 2
        success = False
        for attempt in range(1, max_retries + 1):
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 429 and attempt < max_retries:
                wait = 60
                print(f"  ⚠ Rate limit (429) su {model}, attendo {wait}s ({attempt}/{max_retries})...")
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                print(f"  ✗ {model} rate-limited, provo modello successivo...")
                break
            resp.raise_for_status()
            success = True
            gemini_model = model
            break
        if success:
            break
    else:
        raise RuntimeError("Tutti i modelli Gemini sono rate-limited, riprova più tardi")

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
        date_line = f"📅 {target_dt.strftime('%d/%m/%Y')} ({GIORNI_IT[target_dt.weekday()]})"

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
