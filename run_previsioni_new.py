#!/usr/bin/env python3
"""
run_previsioni_new.py – Previsioni AI con il nuovo motore MeteoBot.

Pipeline:
  1. Scarica dati da Open-Meteo (io_ingest)
  2. Calcola tutti gli indici con il nuovo motore (engine.py)
  3. Invia gemini_prompt al modello Gemini (con retry/fallback)
  4. Invia bollettino AI + analisi tecnica su Telegram
"""

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
