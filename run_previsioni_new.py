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
    fetch_uwyo_sounding,
    compute_model_spread,
    fetch_temperature_history,
    extract_day_hourly,
)
from engine import run_pipeline, export_json
from logic import maltempo_score, livello_attenzione, flash_flood_guidance, heatwave_analysis, instability_evolution, format_evolution_text
from templates import (
    render_analisi_semplice,
    render_section2_detailed,
    build_gemini_prompt_tecnico,
)

TZ_ROME       = ZoneInfo(TIMEZONE)
LOCATION_NAME = "La Spezia"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

GEMINI_MODELS = [
    ("gemini-3.1-flash-lite",   "Gemini 3.1 Flash Lite"),
    ("gemini-3.5-flash",   "Gemini 3.5 Flash"),
    ("gemini-3-flash-preview",   "Gemini 3 Flash Preview"),
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
    """
    Chiama Gemini con retry su 3 modelli.
    MAX_TOKENS → restituisce il testo parziale (non lo scarta).
    Logga il motivo preciso di ogni fallimento.
    """
    # Sanity: se il prompt è enorme, tronca la tabella oraria per non superare i limiti
    MAX_PROMPT_CHARS = 25_000
    if len(prompt) > MAX_PROMPT_CHARS:
        # Trova e tronca il blocco TABELLA ORARIA (la parte più lunga)
        tag = "\nTABELLA ORARIA COMPLETA"
        tag_end = "\nREGOLA CRITICA:"
        idx_start = prompt.find(tag)
        idx_end   = prompt.find(tag_end)
        if 0 < idx_start < idx_end:
            table_block = prompt[idx_start:idx_end]
            lines = table_block.splitlines()
            # Mantieni intestazione + ogni 3 ore
            keep = [lines[0], lines[1]] if len(lines) > 2 else lines
            keep += [l for i, l in enumerate(lines[2:]) if i % 3 == 0]
            prompt = prompt[:idx_start] + "\n".join(keep) + prompt[idx_end:]
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n[prompt troncato per lunghezza]"
        print(f"    [Gemini] Prompt ridotto a {len(prompt)} chars")

    payload = {
        "system_instruction": {"parts": [{"text": (
            "Sei un meteorologo esperto del Levante Ligure e della città di La Spezia. "
            "Rispondi SOLO con testo piano, senza Markdown, senza asterischi. "
            "Segui rigorosamente le istruzioni del prompt."
        )}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 180,
            "topP": 0.85,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in ["HARM_CATEGORY_HARASSMENT","HARM_CATEGORY_HATE_SPEECH",
                      "HARM_CATEGORY_SEXUALLY_EXPLICIT","HARM_CATEGORY_DANGEROUS_CONTENT"]
        ],
    }
    last_error = "nessun tentativo completato"
    for model_id, model_label in GEMINI_MODELS:
        url = f"{GEMINI_API_BASE}/models/{model_id}:generateContent?key={api_key}"
        print(f"    [Gemini] Provo {model_label} ({model_id})...")
        for attempt in range(1, 5):
            try:
                resp = requests.post(url, json=payload, timeout=180)

                if resp.status_code == 404:
                    last_error = f"{model_label}: modello non trovato (404)"
                    print(f"    [Gemini] {last_error}")
                    break
                if resp.status_code == 400:
                    try:
                        msg = resp.json().get("error", {}).get("message", resp.text[:200])
                    except Exception:
                        msg = resp.text[:200]
                    last_error = f"{model_label}: richiesta non valida (400) – {msg}"
                    print(f"    [Gemini] {last_error}")
                    break
                if resp.status_code == 429:
                    if attempt < 4:
                        wait = 30 * (2 ** (attempt - 1))
                        print(f"    [Gemini] Rate limit, attendo {wait}s ({attempt}/3)...")
                        time.sleep(wait)
                        continue
                    last_error = f"{model_label}: rate limit persistente"
                    break
                if resp.status_code >= 500:
                    last_error = f"{model_label}: errore server ({resp.status_code})"
                    print(f"    [Gemini] {last_error}")
                    if attempt < 4:
                        time.sleep(10); continue
                    break

                resp.raise_for_status()
                data  = resp.json()
                cands = data.get("candidates", [])

                if not cands:
                    reason = data.get("promptFeedback", {}).get("blockReason", "sconosciuto")
                    last_error = f"{model_label}: risposta bloccata ({reason})"
                    print(f"    [Gemini] {last_error}")
                    break

                fin  = cands[0].get("finishReason", "")
                text = (cands[0].get("content",{}).get("parts",[{}])[0].get("text","") or "").strip()

                if fin == "SAFETY":
                    last_error = f"{model_label}: bloccato da filtri sicurezza"
                    print(f"    [Gemini] {last_error}")
                    break
                if fin == "MAX_TOKENS":
                    # Testo troncato ma utilizzabile – non scartarlo
                    if text:
                        print(f"    [Gemini] OK {model_label} ({len(text)} chars, MAX_TOKENS – testo parziale)")
                        return text + "\n[risposta troncata per lunghezza]", model_label
                    last_error = f"{model_label}: MAX_TOKENS senza testo"
                    break
                if text:
                    print(f"    [Gemini] OK {model_label} ({len(text)} chars)")
                    return text, model_label

                last_error = f"{model_label}: risposta vuota (finishReason={fin})"
                print(f"    [Gemini] {last_error}")
                break

            except requests.exceptions.Timeout:
                last_error = f"{model_label}: timeout (tentativo {attempt}/4)"
                print(f"    [Gemini] {last_error}")
                if attempt < 4:
                    time.sleep(5); continue
                break
            except Exception as e:
                last_error = f"{model_label}: eccezione {type(e).__name__}: {e}"
                print(f"    [Gemini] {last_error}")
                if attempt < 4:
                    time.sleep(3); continue
                break

    print(f"    [Gemini] Tutti i modelli falliti. Ultimo errore: {last_error}")
    return f"(narrativa AI non disponibile – {last_error})", "nessun_modello"


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
    day_date:         datetime.date,
    day_hourly:       dict,
    day_label:        str,
    model_label:      str,
    is_tendency:      bool = False,
    api_key:          str  = "",
    day_hourly_icon:  dict = None,   # dati ICON-EU raw per spread
    day_offset:       int  = 0,
    temp_history:     list = None,   # storia T per heatwave
    uwyo_sounding:    dict = None,   # sounding UWYO se disponibile
) -> str:
    """
    Costruisce il testo completo per un giorno:
    intestazione + ANALISI SEMPLICE + ANALISI TECNICA (dati + Gemini).
    """
    if not day_hourly:
        return f"\n{'─'*50}\n{day_label.upper()}\n(dati non disponibili per questo giorno)\n"

    # Hourly list con confronto modello secondario
    obs    = build_day_obs(day_hourly, model_label)
    hourly = build_day_hourly_list(
        day_hourly,
        day_hourly_secondary=day_hourly_icon,
        primary_label="arome",
        secondary_label="icon",
    )

    if not obs:
        return f"\n{'─'*50}\n{day_label.upper()}\n(dati insufficienti)\n"

    # Se c'è un sounding UWYO valido, sostituisce il sounding da modello
    if uwyo_sounding and len(uwyo_sounding.get("pressure_pa", [])) >= 6:
        obs["sounding"] = {
            "pressure_pa":   uwyo_sounding["pressure_pa"],
            "temperature_k": uwyo_sounding["temperature_k"],
            "dewpoint_k":    uwyo_sounding["dewpoint_k"],
            "height_m":      uwyo_sounding["height_m"],
            "u_ms":          uwyo_sounding.get("u_ms", []),
            "v_ms":          uwyo_sounding.get("v_ms", []),
        }
        obs["sounding_source"] = uwyo_sounding.get("source", "UWYO")

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
    print(f"  [DEBUG {day_label}] cape={params.get('SBCAPE')} shear={params.get('shear_0_6')} "
          f"cin={params.get('CIN')} lcl={params.get('LCL')} rh={params.get('humidity_pct')} "
          f"wind={params.get('wind_gust_kmh')} temp={params.get('temp_c')} score={m_score}")
    livello, emoji_liv = livello_attenzione(m_score)

    # Flash Flood Guidance
    ffg_score, ffg_desc = flash_flood_guidance(params, rain_obs,
        soil_moisture=obs.get("soil_moisture"))
    ffg_result = {"score": ffg_score, "desc": ffg_desc} if ffg_score >= 0.20 else None

    # Ondata di calore
    hw_result = heatwave_analysis(
        temp_history   = temp_history or [],
        temp_max_today = obs.get("temp_max_c"),
        temp_min_today = obs.get("temp_min_c"),
        heat_index_today = obs.get("heat_index"),
    ) if temp_history else None

    # Spread modelli (AROME vs ICON-EU)
    # Spread modelli (AROME vs ICON-EU) — solo come indicatore di incertezza,
    # MAI come dato alternativo da mostrare al posto di AROME.
    # AROME resta sempre il valore "ufficiale" del bollettino (richiesta:
    # priorità al modello più affidabile nelle prime 48h).
    spread = {}
    if day_hourly_icon:
        try:
            cape_arome = max((h.get("CAPE") or 0 for h in hourly), default=0)
            cape_icon  = max((h.get("CAPE_icon") or 0 for h in hourly), default=None)
            gust_arome = max((h.get("wind_gust") or 0 for h in hourly), default=0)
            gust_icon  = max((h.get("gust_icon") or 0 for h in hourly), default=None)
            prec_arome = sum((h.get("precip") or 0 for h in hourly))
            prec_icon  = sum((h.get("precip_icon") or 0 for h in hourly
                              if h.get("precip_icon") is not None))

            checks = [
                ("CAPE_peak",  cape_arome, cape_icon,  500.0, "J/kg"),
                ("precip_sum", prec_arome, prec_icon,  5.0,   "mm"),
                ("gust_max",   gust_arome, gust_icon,  15.0,  "km/h"),
            ]
            for lbl, va, vi, thr_v, unit in checks:
                if va is not None and vi is not None:
                    diff = abs(va - vi)
                    if diff >= thr_v:
                        spread[lbl] = {
                            "AROME": round(va, 1), "ICON": round(vi, 1),
                            "diff": round(diff, 1), "unit": unit,
                            # "high" ora indica solo se l'incertezza è forte,
                            # non cambia mai quale valore viene usato nel bollettino
                            "high": diff >= thr_v * 2,
                        }
        except Exception as e:
            print(f"  [spread] Calcolo spread fallito: {e}")

    # Estratto sounding UWYO per Gemini (solo indici derivati, non il profilo raw)
    uwyo_summary = None
    if uwyo_sounding and obs.get("sounding_source", "").startswith("UWYO"):
        age = uwyo_sounding.get("age_hours", "?")
        src = uwyo_sounding.get("source", "UWYO")
        shear06 = params.get("shear_0_6")
        srh03   = params.get("srh_0_3")
        sbcape  = params.get("SBCAPE", 0)
        uwyo_summary = (
            f"Fonte: {src} (età {age}h) | "
            f"SBCAPE={sbcape:.0f} J/kg | "
            f"Shear 0-6km={shear06:.1f} kt | SRH 0-3km={srh03:.1f} m²/s²"
            if shear06 is not None and srh03 is not None
            else f"Fonte: {src} (età {age}h) – indici calcolati dal sounding osservato"
        )

    # ── Intestazione ──────────────────────────────────────────────────────
    sounding_tag = f" · {obs.get('sounding_source','')}" if obs.get("sounding_source") else ""

    icona_giorno = "☀️" if livello == "BASSO" else ("⛈️" if livello in ("ALTO", "MOLTO ALTO") else "🌤️")

    lines = [
        "",
        f"{icona_giorno} LA SPEZIA — {day_label.upper()}",
        f"{_format_date(day_date)}",
        "",
        f"{emoji_liv} {livello} · Score {m_score:.1f}/5",
        f"📡 Modello: {model_label}{sounding_tag}",
        "",
    ]

    # ── SINTESI (analisi semplice) ──────────────────────────────────────
    lines.append("📋 SINTESI")
    semplice = render_analisi_semplice(obs, params, hourly, giorno_label=day_label)
    lines.append(semplice)

    evo = instability_evolution(hourly)
    from logic import multi_param_evolution
    multi_evo = multi_param_evolution(hourly)

    if ffg_result and ffg_score >= 0.45:
        lines.append(f"⚠️ {ffg_desc}")
    if hw_result and hw_result.get("is_heatwave"):
        lines.append(f"🌡️ {hw_result.get('desc', '')}")
    lines.append("")

    # ── DATI TECNICI (in colonna, blocco monospazio) ──────────────────────
    sbcape  = float(params.get("SBCAPE", params.get("CAPE", 0)) or 0)
    mucape  = float(params.get("MUCAPE", sbcape) or sbcape)
    pwat    = params.get("PWAT")
    shear06 = params.get("shear_0_6")
    srh03   = params.get("srh_0_3")
    scp     = params.get("SCP")
    stp     = params.get("STP")
    li_v    = params.get("LI")
    cin_v   = params.get("CIN") or params.get("SBCIN")
    dcape_v = params.get("DCAPE", 0) or 0

    def fv(v, fmt=".1f", u=""):
        return f"{v:{fmt}}{u}" if v is not None else "n.d."

    def fv(v, fmt=".1f", u=""):
        return f"{v:{fmt}}{u}" if v is not None else "n.d."

    # Coppie (etichetta sinistra, valore sinistra, etichetta destra, valore destra)
    def fv(v, fmt=".1f", u=""):
        return f"{v:{fmt}}{u}" if v is not None else "n.d."

    dati_tabella = [
        ("SBCAPE",  fv(sbcape, '.0f', ' J/kg')),
        ("MUCAPE",  fv(mucape, '.0f', ' J/kg')),
        ("CIN",     fv(cin_v, '.0f', ' J/kg')),
        ("LI",      fv(li_v, '.1f')),
        ("Shear06", fv(shear06, '.1f', ' kt')),
        ("SRH03",   fv(srh03, '.0f', ' m²/s²')),
        ("PWAT",    fv(pwat, '.1f', ' mm')),
        ("SCP",     fv(scp, '.2f')),
    ]

    etichetta_width = max(len(lbl) for lbl, _ in dati_tabella) + 1
    tabella = [f"{lbl.ljust(etichetta_width)}{val}" for lbl, val in dati_tabella]

    if dcape_v > 50:
        try:
            from thermo import dcape_gust_kmh as _dg
            v_est = _dg(dcape_v)
            tabella.append(f"DCAPE{'':<{etichetta_width-5}}{dcape_v:.0f} J/kg (raffica stim. {v_est:.0f} km/h)")
        except Exception:
            tabella.append(f"DCAPE{'':<{etichetta_width-5}}{dcape_v:.0f} J/kg")

    lines.append("📊 DATI TECNICI")
    lines.append("\n".join(tabella))

    # ── Note extra sotto la tabella (solo se rilevanti) ────────────────────
    cape_hrs    = [(h.get("time", ""), float(h.get("CAPE") or 0)) for h in hourly]
    cape_active = [(t, c) for t, c in cape_hrs if c >= 200]
    if cape_active:
        cpeak = max(cape_active, key=lambda x: x[1])
        lines.append(f"🔺 CAPE>200 per {len(cape_active)}h (picco {cpeak[1]:.0f} J/kg alle {cpeak[0]})")

    rain_hrs = [(h.get("time", ""), float(h.get("precip") or 0))
                for h in hourly if (h.get("precip") or 0) > 0.1]
    if rain_hrs:
        rpeak = max(rain_hrs, key=lambda x: x[1])
        rtot  = sum(r[1] for r in rain_hrs)
        lines.append(
            f"🌧️ Pioggia {rain_hrs[0][0]}–{rain_hrs[-1][0]}: "
            f"{rtot:.1f} mm tot, picco {rpeak[1]:.1f} mm/h alle {rpeak[0]}"
        )

    if evo.get("windows"):
        lines.append("📈 " + format_evolution_text(evo))
    if multi_evo.get("cape"):
        lines.append("📈 " + multi_evo["cape"])
    if multi_evo.get("shear"):
        lines.append("📈 " + multi_evo["shear"])

    if ffg_result:
        lines.append(f"🌊 FFG {ffg_score:.2f}/1.0 – {ffg_desc}")

    if hw_result and hw_result.get("severity") not in ("nessuna", None, ""):
        lines.append(f"🌡️ Calore: {hw_result.get('desc', '')}")

    if spread:
        note_incertezza = []
        for lbl, info in spread.items():
            etichetta = {
                "CAPE_peak": "energia convettiva (CAPE)",
                "precip_sum": "cumulata di pioggia",
                "gust_max": "raffiche di vento",
            }.get(lbl, lbl)
            if info.get("high"):
                note_incertezza.append(f"{etichetta} (forte incertezza)")
            else:
                note_incertezza.append(etichetta)
        lines.append("⚠️ Incertezza modelli: " + ", ".join(note_incertezza) + " — bollettino su AROME")

    lines.append(f"🌪️ Modalità: {mode}")
    if hazards:
        lines.append("⚠️ Fenomeni: " + " | ".join(hazards[:5]))
    lines.append("")

    # ── Narrativa Gemini ────────────────────────────────────────────────
    tech_lines_for_prompt = tabella  # riusato solo per il prompt AI, non stampato di nuovo
    if api_key and GEMINI_API_KEY:
        analisi_tecnica_str = "\n".join(tech_lines_for_prompt)
        hourly_table = result.get("section3", "")
        wind_dir_val = obs.get("wind_dir_deg")
        wind_gust_val = obs.get("wind_gust_kmh")
        wind_speed_val = obs.get("wind_speed_kmh")
        directions = ["Nord", "Nord-Est", "Est", "Sud-Est", "Sud", "Sud-Ovest", "Ovest", "Nord-Ovest"]
        wind_dir_name = directions[int(((wind_dir_val or 0) + 22.5) % 360 / 45)]
        wind_summary_str = (
            f"direzione {wind_dir_name}, velocità media {wind_speed_val or 0:.0f} km/h, "
            f"raffiche fino a {wind_gust_val or 0:.0f} km/h"
        )
        prompt_gemini = build_gemini_prompt_tecnico(
            analisi_tecnica    = analisi_tecnica_str,
            params             = params,
            maltempo_score_val = m_score,
            giorno_label       = f"{day_label} {_format_date(day_date)}",
            is_tendency        = is_tendency,
            hourly_table       = hourly_table,
            spread_data        = spread if spread else None,
            ffg_result         = ffg_result,
            heatwave_result    = hw_result,
            uwyo_summary       = uwyo_summary,
            evolution_result   = evo,
            multi_evolution    = multi_evo,
            wind_summary       = wind_summary_str,
        )
      
      gemini_params = {}
    for k, v in params.items():
        if v is None:
            continue
        try:
            if isinstance(v, float) and (v != v):  # NaN check
                continue
        except (TypeError, ValueError):
            pass
        gemini_params[k] = v
    
    # Se shear è None, non inviarlo a Gemini (evita che inventi valori di vento)
    # I dati tecnici vengono passati tramite build_gemini_prompt_tecnico
      
        narrativa, gem_model = call_gemini(prompt_gemini, api_key)
        lines.append("🤖 ANALISI AI")
        lines.append(narrativa)
        lines.append("")
        lines.append(f"[{gem_model}]")
    else:
        lines.append("(analisi AI non disponibile)")

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

    # ── 2. Radiosondaggio UWYO (solo per oggi/domani, stazione Milano Linate) ─
    print("\n🌡 Tentativo fetch sounding UWYO (Milano Linate 16080)...")
    uwyo_sounding = None
    try:
        uwyo_sounding = fetch_uwyo_sounding(station_id="16080")
        if uwyo_sounding is None:
            print("  [UWYO] Non disponibile, uso profilo da modello")
        else:
            print(f"  [UWYO] OK – {uwyo_sounding['age_hours']:.1f}h fa")
    except Exception as e:
        print(f"  [UWYO] Errore: {e}")

    # ── 3. Storico temperature (per analisi ondata di calore) ──────────────
    print("\n🌡 Fetch storico temperature (7 giorni)...")
    try:
        temp_history = fetch_temperature_history(past_days=7)
        print(f"  ✓ {len(temp_history)} giorni di storico")
    except Exception as e:
        print(f"  ✗ Errore storico: {e}")
        temp_history = []

    # ── 4. Header messaggio ───────────────────────────────────────────────
    header = (
        f"Previsioni Meteo La Spezia\n"
        f"Emissione: {now.strftime('%d/%m/%Y %H:%M')}\n"
        f"Modelli: {model_primary}\n"
        f"{'=' * 50}\n"
    )

    # ── 5. Costruisci messaggi per i 3 giorni ─────────────────────────────
    day_configs = [
        (today,                        "OGGI",     forecast["day0"], forecast.get("day0_icon"), model_primary, False, 0),
        (today + datetime.timedelta(1),"DOMANI",   forecast["day1"], forecast.get("day1_icon"), model_primary, False, 1),
        (today + datetime.timedelta(2),"TENDENZA", forecast["day2"], None,                      forecast["model_fallback"], True, 2),
    ]

    messages = []
    for day_date, label, day_hourly, icon_raw, mdl, is_tend, day_off in day_configs:
        print(f"\n⚙️  Elaborazione {label} ({_format_date(day_date)})...")
        # Il sounding UWYO è usato solo per oggi/domani (se fresco)
        uwyo_for_day = uwyo_sounding if (not is_tend and uwyo_sounding) else None
        msg = build_day_message(
            day_date        = day_date,
            day_hourly      = day_hourly,
            day_label       = label,
            model_label     = mdl,
            is_tendency     = is_tend,
            api_key         = GEMINI_API_KEY,
            day_hourly_icon = icon_raw,
            day_offset      = day_off,
            temp_history    = temp_history,
            uwyo_sounding   = uwyo_for_day,
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
