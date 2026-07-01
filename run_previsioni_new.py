#!/usr/bin/env python3
"""
run_previsioni_new.py – Previsioni AI 3 giorni con motore MeteoBot.

Struttura per ogni giorno:
  ── INTESTAZIONE  (data, livello di attenzione, modello)
  ◆ ANALISI SEMPLICE  (script – testo dinamico con molte varianti)
  ◆ ANALISI TECNICA   (script – dati avanzati + narrativa Gemini)

Modelli: AROME (day 0-1) + ICON-EU (tutti e 3 i giorni, sempre).
"""

import sys
import time
import datetime
import requests
from zoneinfo import ZoneInfo

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    GEMINI_API_KEY,
    LATITUDE, LONGITUDE, TIMEZONE,
)
from io_ingest import (
    fetch_forecast_3days,
    build_day_obs,
    build_day_hourly_list,
)
from engine import run_pipeline, export_json
from logic import maltempo_score, livello_attenzione
from templates import (
    render_analisi_semplice,
    render_section2_detailed,
    build_gemini_prompt_tecnico,
)

TZ_ROME       = ZoneInfo(TIMEZONE)
LOCATION_NAME = "La Spezia"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

GEMINI_MODELS = [
    ("gemini-2.5-flash",   "Gemini 2.5 Flash"),
    ("gemini-2.0-flash",   "Gemini 2.0 Flash"),
    ("gemini-1.5-flash",   "Gemini 1.5 Flash"),
]

GIORNI_IT = ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"]
MESI_IT   = ["gennaio","febbraio","marzo","aprile","maggio","giugno",
             "luglio","agosto","settembre","ottobre","novembre","dicembre"]

def _format_date(d: datetime.date) -> str:
    return f"{GIORNI_IT[d.weekday()]} {d.day} {MESI_IT[d.month-1]} {d.year}"


# ─────────────────────────────────────────────────────────────────────────────
# Gemini
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini(prompt: str, api_key: str) -> tuple[str, str]:
    payload = {
        "system_instruction": {"parts": [{"text": (
            "Sei un meteorologo esperto del Levante Ligure e della città di La Spezia. "
            "Rispondi SOLO con testo piano, senza Markdown, senza asterischi. "
            "Segui rigorosamente le istruzioni del prompt."
        )}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 4096,
            "topP": 0.85,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in ["HARM_CATEGORY_HARASSMENT","HARM_CATEGORY_HATE_SPEECH",
                      "HARM_CATEGORY_SEXUALLY_EXPLICIT","HARM_CATEGORY_DANGEROUS_CONTENT"]
        ],
    }
    for model_id, model_label in GEMINI_MODELS:
        url = f"{GEMINI_API_BASE}/models/{model_id}:generateContent?key={api_key}"
        print(f"    [Gemini] Provo {model_label}...")
        for attempt in range(1, 5):
            try:
                resp = requests.post(url, json=payload, timeout=180)
                if resp.status_code == 404:
                    break
                if resp.status_code == 429:
                    if attempt < 4:
                        wait = 30 * (2 ** (attempt - 1))
                        print(f"    [Gemini] Rate limit, attendo {wait}s...")
                        time.sleep(wait)
                        continue
                    break
                resp.raise_for_status()
                cands = resp.json().get("candidates", [])
                if not cands:
                    break
                fin = cands[0].get("finishReason", "")
                if fin in ("SAFETY", "MAX_TOKENS"):
                    break
                text = (cands[0].get("content",{}).get("parts",[{}])[0].get("text","") or "").strip()
                if text:
                    print(f"    [Gemini] OK {model_label} ({len(text)} chars)")
                    return text, model_label
            except requests.exceptions.Timeout:
                if attempt < 4:
                    time.sleep(5); continue
                break
            except Exception as e:
                print(f"    [Gemini] errore: {e}")
                if attempt < 4:
                    time.sleep(3); continue
                break

    return "(narrativa AI non disponibile al momento)", "nessun_modello"


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

def send_telegram(text: str, max_len: int = 4000):
    """Invia a tutti i chat_id, spezzando se >max_len chars."""
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("  [TG] Telegram non configurato, skip")
        return
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > max_len:
            if cur:
                chunks.append(cur.rstrip())
            cur = line
        else:
            cur += line
    if cur.strip():
        chunks.append(cur.rstrip())

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in LISTA_CHAT:
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = f"(segue {i+1}/{len(chunks)})\n" + chunk
            try:
                r = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=15)
                r.raise_for_status()
                ok = r.json().get("ok", False)
                print(f"  [TG] {'✓' if ok else '✗'} chat {chat_id} chunk {i+1}/{len(chunks)}")
            except Exception as e:
                print(f"  [TG] Errore {chat_id}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Build del messaggio per un singolo giorno
# ─────────────────────────────────────────────────────────────────────────────

def build_day_message(
    day_date:    datetime.date,
    day_hourly:  dict,
    day_label:   str,
    model_label: str,
    is_tendency: bool = False,
    api_key:     str  = "",
) -> str:
    """
    Costruisce il testo completo per un giorno:
    intestazione + ANALISI SEMPLICE + ANALISI TECNICA (dati + Gemini).
    """
    if not day_hourly:
        return f"\n{'─'*50}\n{day_label.upper()}\n(dati non disponibili per questo giorno)\n"

    obs     = build_day_obs(day_hourly, model_label)
    hourly  = build_day_hourly_list(day_hourly)

    if not obs:
        return f"\n{'─'*50}\n{day_label.upper()}\n(dati insufficienti)\n"

    # Pipeline motore
    try:
        result  = run_pipeline(obs, hourly)
        params  = result["params"]
        hazards = result["hazards"]
        mode    = result["meta"]["mode"]
    except Exception as e:
        print(f"  [pipeline] Errore giorno {day_label}: {e}")
        params  = {}
        hazards = []
        mode    = "n.d."
        result  = {"meta": {"score": 0}, "params": {}, "hazards": []}

    # Score maltempo
    rain_obs = {
        "1h":  float(obs.get("precip_rate_mm_h", 0) or 0),
        "24h": float(obs.get("rain_24h_mm", 0) or 0),
    }
    m_score  = maltempo_score(params, rain_obs)
    livello, emoji_liv = livello_attenzione(m_score)

    # ── Intestazione ──────────────────────────────────────────────────────
    sep = "═" * 50
    lines = [
        "",
        sep,
        f"  {day_label.upper()}",
        f"  {_format_date(day_date)}",
        sep,
        f"Livello di ATTENZIONE: {emoji_liv} {livello}  (score {m_score:.1f}/5)",
        f"Modello: {model_label}",
        "",
    ]

    # ── ANALISI SEMPLICE ──────────────────────────────────────────────────
    lines.append("◆ ANALISI SEMPLICE")
    lines.append("─" * 40)
    semplice = render_analisi_semplice(obs, params, hourly, giorno_label=day_label)
    lines.append(semplice)
    lines.append("")

    # ── ANALISI TECNICA ──────────────────────────────────────────────────
    lines.append("◆ ANALISI TECNICA")
    lines.append("─" * 40)

    # Dati avanzati (testo script)
    sbcape  = float(params.get("SBCAPE", params.get("CAPE", 0)) or 0)
    mucape  = float(params.get("MUCAPE", sbcape) or sbcape)
    pwat    = params.get("PWAT")
    shear06 = params.get("shear_0_6")
    srh03   = params.get("srh_0_3")
    scp     = params.get("SCP")
    stp     = params.get("STP")
    li_v    = params.get("LI")
    cin_v   = params.get("CIN") or params.get("SBCIN")

    def fv(v, fmt=".1f", u=""):
        return f"{v:{fmt}}{u}" if v is not None else "n.d."

    tech_lines = [
        f"SBCAPE: {fv(sbcape,'.0f',' J/kg')}  |  MUCAPE: {fv(mucape,'.0f',' J/kg')}",
        f"CIN:    {fv(cin_v, '.0f',' J/kg')}  |  LI:     {fv(li_v,'.1f')}",
        f"Shear 0-6 km: {fv(shear06,'.1f',' kt')}  |  SRH 0-3 km: {fv(srh03,'.0f',' m²/s²')}",
        f"PWAT: {fv(pwat,'.1f',' mm')}  |  SCP: {fv(scp,'.2f')}  |  STP: {fv(stp,'.2f')}",
    ]

    # Evoluzione CAPE (ore con convezione attiva)
    cape_hrs = [(h.get("time", ""), float(h.get("CAPE") or 0)) for h in hourly]
    cape_active = [(t, c) for t, c in cape_hrs if c >= 200]
    if cape_active:
        cpeak = max(cape_active, key=lambda x: x[1])
        tech_lines.append(
            f"CAPE>200: {len(cape_active)}h (picco {cpeak[1]:.0f} J/kg alle {cpeak[0]})"
        )

    # Range orario precipitazioni
    rain_hrs = [(h.get("time", ""), float(h.get("precip") or 0))
                for h in hourly if (h.get("precip") or 0) > 0.1]
    if rain_hrs:
        rpeak = max(rain_hrs, key=lambda x: x[1])
        rtot  = sum(r[1] for r in rain_hrs)
        tech_lines.append(
            f"Pioggia: {rain_hrs[0][0]}–{rain_hrs[-1][0]}, "
            f"{rtot:.1f} mm tot, picco {rpeak[1]:.1f} mm/h alle {rpeak[0]}"
        )

    tech_lines.append(f"Modalità: {mode}")
    if hazards:
        tech_lines.append("Fenomeni: " + " | ".join(hazards[:5]))
    lines.extend(tech_lines)
    lines.append("")

    # Narrativa Gemini
    if api_key and GEMINI_API_KEY:
        analisi_tecnica_str = "\n".join(tech_lines)
        hourly_table = result.get("section3", "")
        prompt_gemini = build_gemini_prompt_tecnico(
            analisi_tecnica    = analisi_tecnica_str,
            params             = params,
            maltempo_score_val = m_score,
            giorno_label       = f"{day_label} {_format_date(day_date)}",
            is_tendency        = is_tendency,
            hourly_table       = hourly_table,
        )
        narrativa, gem_model = call_gemini(prompt_gemini, api_key)
        lines.append(narrativa)
        lines.append(f"\n[AI: {gem_model}]")
    else:
        lines.append("(analisi AI non disponibile – GEMINI_API_KEY mancante)")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  METEOBOT – PREVISIONI 3 GIORNI (nuovo motore)")
    print("=" * 60)

    if not GEMINI_API_KEY:
        print("ATTENZIONE: GEMINI_API_KEY non configurata – invio senza AI")

    now   = datetime.datetime.now(TZ_ROME)
    today = now.date()
    print(f"\nOra: {now.strftime('%d/%m/%Y %H:%M')} – {LOCATION_NAME}")

    # ── 1. Fetch dati 3 giorni ────────────────────────────────────────────
    print("\n📡 Scaricamento dati Open-Meteo (AROME + ICON-EU)...")
    try:
        forecast = fetch_forecast_3days()
        model_primary = forecast["model_primary"]
        print(f"  ✓ Dati scaricati – modello primario: {model_primary}")
    except Exception as e:
        print(f"  ✗ Errore fetch: {e}")
        sys.exit(1)

    # ── 2. Header messaggio ───────────────────────────────────────────────
    header = (
        f"Previsioni Meteo La Spezia\n"
        f"Emissione: {now.strftime('%d/%m/%Y %H:%M')}\n"
        f"Modelli: {model_primary}\n"
        f"{'=' * 50}\n"
    )

    # ── 3. Costruisci messaggi per i 3 giorni ─────────────────────────────
    day_configs = [
        (today,                     "OGGI",     forecast["day0"], model_primary, False),
        (today + datetime.timedelta(1), "DOMANI", forecast["day1"], model_primary, False),
        (today + datetime.timedelta(2), "TENDENZA", forecast["day2"], forecast["model_fallback"], True),
    ]

    messages = []
    for day_date, label, day_hourly, mdl, is_tend in day_configs:
        print(f"\n⚙️  Elaborazione {label} ({_format_date(day_date)})...")
        msg = build_day_message(
            day_date   = day_date,
            day_hourly = day_hourly,
            day_label  = label,
            model_label = mdl,
            is_tendency = is_tend,
            api_key    = GEMINI_API_KEY,
        )
        messages.append(msg)
        print(f"  ✓ {label}: {len(msg)} chars")

    # ── 4. Invia su Telegram ──────────────────────────────────────────────
    print("\n📤 Invio via Telegram...")
    # Prima: header + giorno 0 nello stesso messaggio
    send_telegram(header + messages[0])
    # Poi: giorni 1 e 2 separati
    for msg in messages[1:]:
        send_telegram(msg)

    # ── 5. Salva JSON ──────────────────────────────────────────────────────
    export_json({"messages": messages, "generated": now.isoformat()}, "previsioni_output.json")
    print(f"\n✅ Completato. Output in previsioni_output.json")


if __name__ == "__main__":
    main()


import json
import sys
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    GEMINI_API_KEY,
    LATITUDE, LONGITUDE, TIMEZONE,
)
from io_ingest import (
    fetch_openmeteo_current,
    build_obs_from_openmeteo,
    build_hourly_forecast_from_openmeteo,
)
from engine import run_pipeline, export_json

TZ_ROME = ZoneInfo(TIMEZONE)
LOCATION_NAME = "La Spezia"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Modelli Gemini – stesso ordine di precedenza di previsioni.py
GEMINI_MODELS = [
    ("gemini-3.5-flash",          "Gemini 3.5 Flash"),
    ("gemini-3-flash-preview",          "Gemini 2.0 Flash"),
    ("gemini-1.5-flash",          "Gemini 1.5 Flash"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Gemini call (con retry e fallback modello)
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini(prompt: str, api_key: str) -> tuple[str, str]:
    """
    Chiama Gemini con il prompt fornito.
    Ritorna (testo_risposta, nome_modello_usato).
    """
    payload = {
        "system_instruction": {
            "parts": [{"text": (
                "Sei un meteorologo professionista italiano esperto del territorio ligure. "
                "Ricevi l'analisi tecnica completa del motore meteorologico MeteoBot "
                "per La Spezia e il Levante Ligure. "
                "Devi scrivere un bollettino meteorologico completo e professionale. "
                "NON usare formattazione Markdown (no asterischi, no underscore). "
                "Scrivi in italiano, tono professionale ma comprensibile. "
                "Segui ESATTAMENTE le istruzioni contenute nel prompt fornito."
            )}]
        },
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8192,
            "topP": 0.8,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in [
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            ]
        ],
    }

    for model_id, model_label in GEMINI_MODELS:
        url = f"{GEMINI_API_BASE}/models/{model_id}:generateContent?key={api_key}"
        print(f"  Provo {model_label}...")
        max_retries = 4

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=180)

                if resp.status_code == 404:
                    print(f"  ⚠ {model_label} non disponibile (404), passo al successivo")
                    break

                if resp.status_code == 429:
                    if attempt < max_retries:
                        wait = 30 * (2 ** (attempt - 1))
                        print(f"  ⚠ Rate limit, attendo {wait}s ({attempt}/{max_retries})...")
                        time.sleep(wait)
                        continue
                    print(f"  ✗ Rate limit persistente su {model_label}")
                    break

                resp.raise_for_status()

                result = resp.json()
                candidates = result.get("candidates", [])
                if not candidates:
                    reason = result.get("promptFeedback", {}).get("blockReason", "sconosciuto")
                    print(f"  ✗ Risposta bloccata ({reason}), passo al successivo")
                    break

                finish = candidates[0].get("finishReason", "")
                if finish in ("SAFETY", "MAX_TOKENS"):
                    print(f"  ✗ finishReason={finish}, passo al successivo")
                    break

                text = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if not text.strip():
                    print(f"  ✗ Risposta vuota, passo al successivo")
                    break

                print(f"  ✓ Risposta ottenuta da {model_label} ({len(text)} chars)")
                return text.strip(), model_label

            except requests.exceptions.Timeout:
                print(f"  ⚠ Timeout ({attempt}/{max_retries})...")
                if attempt < max_retries:
                    time.sleep(5)
                    continue
                break
            except requests.exceptions.RequestException as e:
                print(f"  ✗ Errore rete: {e}")
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                break

    return (
        "Le previsioni automatiche non sono disponibili al momento "
        "(Gemini non raggiungibile o rate limit esaurito).",
        "nessun_modello",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

def _send_telegram_message(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": ""},
            timeout=15,
        )
        resp.raise_for_status()
        if resp.json().get("ok"):
            print(f"  ✓ Inviato a {chat_id}")
            return True
        print(f"  ✗ Errore Telegram per {chat_id}: {resp.json()}")
        return False
    except Exception as e:
        print(f"  ✗ Eccezione invio {chat_id}: {e}")
        return False


def send_telegram(text: str, max_len: int = 4096):
    """Invia il testo a tutti i chat_id; spezza se >4096 caratteri."""
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato, skip")
        return
    # Spezza in chunk di max_len preservando le righe
    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > max_len:
            if current:
                chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.rstrip())

    for chat_id in LISTA_CHAT:
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = f"(continua {i+1}/{len(chunks)})\n" + chunk
            _send_telegram_message(chat_id, chunk)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  METEOBOT – PREVISIONI AI (nuovo motore)")
    print("=" * 60)

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY non configurata")
        sys.exit(1)

    now = datetime.now(TZ_ROME)
    print(f"\nOra: {now.strftime('%d/%m/%Y %H:%M')} – {LOCATION_NAME}")
    print(f"Posizione: {LATITUDE}°N, {LONGITUDE}°E")

    # ── 1. Dati Open-Meteo ──────────────────────────────────────────────────
    print("\n📡 Scaricamento dati Open-Meteo...")
    try:
        raw_data = fetch_openmeteo_current()
        obs = build_obs_from_openmeteo(raw_data)
        hourly = build_hourly_forecast_from_openmeteo(raw_data, n_hours=48)
        n_hours = len(hourly)
        print(f"  ✓ {n_hours} ore di previsione scaricate")
    except Exception as e:
        print(f"  ✗ Errore Open-Meteo: {e}")
        sys.exit(1)

    # ── 2. Pipeline motore meteorologico ────────────────────────────────────
    print("\n⚙️  Calcolo indici con motore MeteoBot...")
    try:
        result = run_pipeline(obs, hourly)
        meta = result["meta"]
        print(f"  ✓ Pipeline completata")
        print(f"     Allerta : {meta.get('alert_emoji','⚪')} {meta['alert_level'].upper()}")
        print(f"     Score   : {meta['score']}/12")
        print(f"     Modo    : {meta['mode']}")
        print(f"     SCP     : {result['params'].get('SCP', 0):.2f}")
        print(f"     STP     : {result['params'].get('STP', 0):.2f}")
        print(f"     SBCAPE  : {result['params'].get('SBCAPE', result['params'].get('CAPE', 0)):.0f} J/kg")
        export_json(result, "previsioni_output.json")
    except Exception as e:
        print(f"  ✗ Errore pipeline: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # ── 3. Chiama Gemini con il prompt del motore ────────────────────────────
    print("\n🤖 Generazione bollettino AI con Gemini...")
    gemini_prompt = result["gemini_prompt"]
    ai_text, gemini_model = call_gemini(gemini_prompt, GEMINI_API_KEY)

    # ── 4. Componi messaggio Telegram ────────────────────────────────────────
    print("\n📤 Invio via Telegram...")

    emoji_allerta = meta.get("alert_emoji", "⚪")
    livello = meta["alert_level"].upper()

    header = (
        f"Previsioni Meteo - {LOCATION_NAME}\n"
        f"Data: {now.strftime('%d/%m/%Y %H:%M')}\n"
        f"Allerta ARPAL: {emoji_allerta} {livello}\n"
        f"Score convettivo: {meta['score']}/12\n"
        f"AI: {gemini_model}\n"
        f"{'─' * 40}\n\n"
    )

    # Analisi tecnica sintetica (solo valori chiave per non appesantire)
    p = result["params"]
    sbcape = p.get("SBCAPE", p.get("CAPE", 0)) or 0
    shear  = p.get("shear_0_6", 0) or 0
    srh    = p.get("srh_0_3", p.get("srh_0_1", 0)) or 0
    pwat   = p.get("PWAT", 0) or 0
    scp    = p.get("SCP", 0) or 0
    stp    = p.get("STP", 0) or 0

    tech_summary = (
        f"[ANALISI TECNICA]\n"
        f"SBCAPE: {sbcape:.0f} J/kg | PWAT: {pwat:.1f} mm\n"
        f"Shear 0-6: {shear:.1f} kt | SRH 0-3: {srh:.0f} m2/s2\n"
        f"SCP: {scp:.2f} | STP: {stp:.2f}\n"
        f"Modo: {meta['mode']}\n"
    )
    if result.get("hazards"):
        tech_summary += "Fenomeni: " + "; ".join(result["hazards"][:4]) + "\n"

    tech_summary += f"{'─' * 40}\n\n"

    full_message = header + tech_summary + ai_text

    send_telegram(full_message)

    print(f"\n✅ Completato. Messaggio: {len(full_message)} caratteri")


if __name__ == "__main__":
    main()
