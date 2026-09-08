#!/usr/bin/env python3
"""
run_previsioni_new.py – Genera i dati meteo per il sito con il motore MeteoBot.

Struttura per ogni giorno:
  ── INTESTAZIONE  (data, livello di attenzione, modello)
  ◆ ANALISI SEMPLICE  (script – testo dinamico con molte varianti)
  ◆ ANALISI TECNICA   (script – dati avanzati)

Modelli: AROME (day 0-1) + ICON-EU (tutti i giorni, sempre). Niente Gemini/Telegram/UWYO:
il risultato è solo il JSON per docs/site_data.json.
"""

import sys
import json
import datetime
from zoneinfo import ZoneInfo

from config import (
    LATITUDE, LONGITUDE, TIMEZONE,
    load_state_section, save_state_section,
)
from io_ingest import (
    fetch_forecast_3days,
    build_day_obs,
    build_day_hourly_list,
    build_nowcast_quarter_hourly,
    compute_model_spread,
    fetch_temperature_history,
    extract_day_hourly,
    fetch_arpal_alert,
)
from engine import run_pipeline, export_json
from logic import (
    maltempo_score, livello_attenzione, flash_flood_guidance, heatwave_analysis,
    instability_evolution, format_evolution_text,
    rain_evolution, wind_evolution, format_rain_evolution, format_wind_evolution,
    upper_level_temperature_anomaly, is_intense_storm_mode, hazard_probability, assess_phenomena_risks
)
from templates import (
    render_analisi_semplice,
    render_section2_detailed,
    render_phenomena_risks
)

TZ_ROME       = ZoneInfo(TIMEZONE)
LOCATION_NAME = "La Spezia"

GIORNI_IT = ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"]
MESI_IT   = ["gennaio","febbraio","marzo","aprile","maggio","giugno",
             "luglio","agosto","settembre","ottobre","novembre","dicembre"]

def _format_date(d: datetime.date) -> str:
    return f"{GIORNI_IT[d.weekday()]} {d.day} {MESI_IT[d.month-1]} {d.year}"

# ─────────────────────────────────────────────────────────────────────────────
# Confronto con l'emissione precedente (Fase 2 — "cosa è cambiato")
# ─────────────────────────────────────────────────────────────────────────────

def confronta_con_precedente(day_key: str, current_snapshot: dict) -> list | None:
    """
    Confronta lo snapshot di oggi con quello salvato dall'esecuzione precedente
    (in state.json, sezione 'storico_previsioni'). Aggiorna sempre lo stato
    con lo snapshot corrente, indipendentemente dall'esito del confronto.

    Ritorna una lista di frasi descrittive, o None se non ci sono variazioni
    significative (o se non esiste ancora uno storico da confrontare).
    """
    sezione = load_state_section("storico_previsioni")
    prev = sezione.get(day_key)

    sezione[day_key] = current_snapshot
    save_state_section("storico_previsioni", sezione)

    if not prev:
        return None

    diffs = []

    d_score = current_snapshot.get("score", 0) - prev.get("score", 0)
    if abs(d_score) >= 0.5:
        verso = "aumentato" if d_score > 0 else "diminuito"
        diffs.append(
            f"Il livello di rischio è {verso} rispetto alla precedente elaborazione "
            f"({prev.get('score', 0):.1f} → {current_snapshot.get('score', 0):.1f})"
        )

    d_wind = current_snapshot.get("wind_gust_kmh", 0) - prev.get("wind_gust_kmh", 0)
    if abs(d_wind) >= 15:
        diffs.append(
            f"Raffiche massime previste passate da {prev.get('wind_gust_kmh', 0):.0f} "
            f"a {current_snapshot.get('wind_gust_kmh', 0):.0f} km/h"
        )

    d_rain = current_snapshot.get("rain_peak", 0) - prev.get("rain_peak", 0)
    if abs(d_rain) >= 10:
        verso = "aumentato" if d_rain > 0 else "diminuito"
        diffs.append(
            f"Il picco di pioggia oraria è {verso} rispetto alla precedente elaborazione "
            f"({prev.get('rain_peak', 0):.0f} → {current_snapshot.get('rain_peak', 0):.0f} mm/h)"
        )

    return diffs if diffs else None


# ─────────────────────────────────────────────────────────────────────────────
# Build del messaggio per un singolo giorno
# ─────────────────────────────────────────────────────────────────────────────

def build_day_message(
    day_date:         datetime.date,
    day_hourly:       dict,
    day_label:        str,
    model_label:      str,
    is_tendency:      bool = False,
    day_hourly_icon:  dict = None,   # dati ICON-EU raw per spread
    day_offset:       int = 0,
    temp_history:     list = None,   # storia T per heatwave
    site_data:        dict = None,   # se fornito (solo per OGGI), accumula qui il JSON per il sito
    arome_pi_data:    dict = None,   # nowcast AROME-PI, solo per OGGI
    arpal_alert:      dict = None,   # stato allerta ufficiale letto automaticamente da ARPAL
    next_day_hourly_list: list = None,  # tabella oraria di DOMANI (già costruita),
                                         # serve solo a OGGI per completare i quarti dopo mezzanotte
    injected_quarters: list = None,     # quarti d'ora oltre mezzanotte calcolati da OGGI,
                                         # da inserire qui se questa chiamata è per DOMANI
) -> tuple:
    """
    Ritorna (testo_messaggio, quarti_per_domani).
    quarti_per_domani è None per tutti i giorni tranne OGGI: contiene le
    righe da 15 minuti che cadono dopo la mezzanotte, da passare alla
    chiamata di build_day_message per DOMANI.
    """
    tomorrow_quarters = None
    """
    Costruisce il testo completo per un giorno:
    intestazione + ANALISI SEMPLICE + ANALISI TECNICA (dati + Gemini).
    """
    if not day_hourly:
        return f"\n{'─'*50}\n{day_label.upper()}\n(dati non disponibili per questo giorno)\n", None

    obs    = build_day_obs(day_hourly, model_label)
    hourly = build_day_hourly_list(
        day_hourly,
        day_hourly_secondary=day_hourly_icon,
        primary_label="arome",
        secondary_label="icon",
    )
    if day_offset == 1 and injected_quarters:
        ore_coperte = {r["time"][:2] + ":00" for r in injected_quarters}
        hourly = [h for h in hourly if h.get("time", "")[:2] + ":00" not in ore_coperte]
        hourly = injected_quarters + hourly

    if day_offset == 0:
        now_local = datetime.datetime.now(TZ_ROME)
        current_hour_str = f"{now_local.hour:02d}:00"
        hourly = [h for h in hourly if h.get("time", "00:00") >= current_hour_str]
        if arome_pi_data:
            hourly, tomorrow_quarters = build_nowcast_quarter_hourly(
                arome_pi_data, hourly, day_date,
                next_day_hourly_list=next_day_hourly_list,
            )

    if not obs:
        return f"\n{'─'*50}\n{day_label.upper()}\n(dati insufficienti)\n", None

    # Pipeline motore
    try:
        result       = run_pipeline(obs, hourly)
        params       = result["params"]
        hazards      = result["hazards"]
        hazards_dict = result.get("hazards_dict", {"reali": [], "potenziali": []})
        mode         = result["meta"]["mode"]
    except Exception as e:
        print(f"  [pipeline] Errore giorno {day_label}: {e}")
        params       = {}
        hazards      = []
        hazards_dict = {"reali": [], "potenziali": []}
        mode         = "n.d."
        result       = {"meta": {"score": 0}, "params": {}, "hazards": []}

    # Score maltempo
    rain_obs = {
        "1h":  float(obs.get("precip_rate_mm_h", 0) or 0),
        "24h": float(obs.get("rain_24h_mm", 0) or 0),
    }
    temp_anomaly = upper_level_temperature_anomaly(params, day_date.month)
    m_score  = maltempo_score(params, rain_obs, temp_anomaly=temp_anomaly)
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

    # ── Intestazione ──────────────────────────────────────────────────────
    ha_rischio_reale = bool(hazards_dict.get("reali"))
    if ha_rischio_reale:
        icona_giorno = "⛈️"
    elif livello == "BASSO":
        icona_giorno = "☀️"
    elif hw_result and hw_result.get("is_heatwave"):
        icona_giorno = "🌡️"
    else:
        icona_giorno = "🌤️"

    prob = hazard_probability(params)
    risks = assess_phenomena_risks(params, obs, hourly, hazard_prob_pct=prob)
    lines = [
        "",
        f"{icona_giorno} LA SPEZIA — {day_label.upper()}",
        f"{_format_date(day_date)}",
        "",
        render_phenomena_risks(risks),
        "",
        f"📡 Modello: {model_label}",
        "",
    ]

    # ── SINTESI (analisi semplice) ──────────────────────────────────────
    lines.append("📋 SINTESI")
    semplice = render_analisi_semplice(obs, params, hourly, giorno_label=day_label)
    lines.append(semplice)

    evo = instability_evolution(hourly)

    if ffg_result and ffg_score >= 0.45:
        lines.append(f"⚠️ {ffg_desc}")
    if hw_result and hw_result.get("is_heatwave"):
        lines.append(f"🌡️ {hw_result.get('desc', '')}")
    if temp_anomaly:
        lines.append(f"🧊 {temp_anomaly['desc']}")
    lines.append("")

    # ── DATI TECNICI (in colonna, blocco monospazio) ──────────────────────
    dcape_v = params.get("DCAPE", 0) or 0

    def fv(v, fmt=".1f", u=""):
        return f"{v:{fmt}}{u}" if v is not None else "n.d."

    dati_tabella = [
        ("SBCAPE",  fv(params.get("SBCAPE", params.get("CAPE")), ".0f", " J/kg")),
        ("MUCAPE",  fv(params.get("MUCAPE"), ".0f", " J/kg")),
        ("CIN",     fv(params.get("CIN"), ".0f", " J/kg")),
        ("LI",      fv(params.get("LI"), ".1f")),
        ("Shear06", fv(params.get("shear_0_6"), ".1f", " kt")),
        ("SRH03",   fv(params.get("srh_0_3"), ".0f", " m²/s²")),
        ("PWAT",    fv(params.get("PWAT"), ".1f", " mm")),
        ("SCP",     fv(params.get("SCP"), ".2f")),
        ("Vento",   fv(obs.get("wind_speed_kmh"), ".0f", " km/h")),
        ("Raffica", fv(obs.get("wind_gust_kmh"), ".0f", " km/h")),
        ("K-Index", fv(params.get("KI"), ".0f")),
        ("Totals-Totals", fv(params.get("TT"), ".0f")),
    ]

    etichetta_width = max(len(lbl) for lbl, _ in dati_tabella) + 1
    tabella = [f"{lbl.ljust(etichetta_width)}{val}" for lbl, val in dati_tabella]

    ha_innesco_oggi = float(obs.get("precip_rate_mm_h", 0) or 0) > 1.0 or int(obs.get("wmo_code", 0) or 0) in (80, 81, 82, 95, 96, 99)
    if dcape_v > 50:
        try:
            from thermo import dcape_gust_kmh as _dg
            v_est = _dg(dcape_v)
            if ha_innesco_oggi:
                tabella.append(f"DCAPE{'':<{etichetta_width-5}}{dcape_v:.0f} J/kg (raffica stim. {v_est:.0f} km/h)")
            else:
                tabella.append(f"DCAPE{'':<{etichetta_width-5}}{dcape_v:.0f} J/kg (teorico, nessun innesco previsto)")
        except Exception:
            tabella.append(f"DCAPE{'':<{etichetta_width-5}}{dcape_v:.0f} J/kg")

    lines.append(f"📊 DATI TECNICI — modello {model_label}")
    lines.append("\n".join(tabella))
   
    # ── Note extra sotto la tabella (solo se rilevanti) ────────────────────
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

    rain_evo     = rain_evolution(hourly)
    wind_evo     = wind_evolution(hourly)
    rain_evo_txt = format_rain_evolution(rain_evo)
    wind_evo_txt = format_wind_evolution(wind_evo)
    if rain_evo_txt:
        lines.append("🌧️ " + rain_evo_txt)
    if wind_evo_txt:
        lines.append("💨 " + wind_evo_txt)

    if ffg_result:
        lines.append(f"🌊 FFG {ffg_score:.2f}/1.0 – {ffg_desc}")

    if hw_result and hw_result.get("severity") not in ("nessuna", None, ""):
        lines.append(f"🌡️ Calore: {hw_result.get('desc', '')}")

    is_intense = is_intense_storm_mode(mode)
    if is_intense:
        lines.append(f"🌪️ Modalità: {mode}")

    # Evita di ripetere un concetto già espresso in "Modalità": se un hazard
    # condivide troppe parole chiave con la modalità, è quasi certamente
    # la stessa informazione ridetta con altre parole — la scartiamo.
    def _troppo_simile(hazard_txt: str, mode_txt: str) -> bool:
        stop = {"e", "di", "la", "il", "in", "a", "con", "non", "un", "una",
                "che", "per", "resta", "pur", "assenza", "presente"}
        parole_mode = {w.lower().strip(",.():") for w in mode_txt.split() if w.lower() not in stop and len(w) > 3}
        parole_haz  = {w.lower().strip(",.():") for w in hazard_txt.split() if w.lower() not in stop and len(w) > 3}
        if not parole_mode or not parole_haz:
            return False
        comuni = parole_mode & parole_haz
        return len(comuni) / len(parole_haz) >= 0.5

    reali_filtrati       = [h for h in hazards_dict.get("reali", [])       if not _troppo_simile(h, mode)]
    potenziali_filtrati  = [h for h in hazards_dict.get("potenziali", [])  if not _troppo_simile(h, mode)]

    if reali_filtrati:
        lines.append("⚠️ Fenomeni in atto/certi: " + " | ".join(reali_filtrati[:5]))

    if is_intense or potenziali_filtrati:
        lines.append(f"🎲 Probabilità fenomeni convettivi intensi: {prob}%")

    if not reali_filtrati and not is_intense and not potenziali_filtrati:
        lines.append("🟢 Nessun fenomeno severo rilevato")
    lines.append("")

    if site_data is not None:
        from api_builder import build_bulletin_json
        bulletin = build_bulletin_json(
            result=result,
            obs=obs,
            hourly=hourly,
            risks=risks,
            m_score=m_score,
            livello=livello,
            emoji_liv=emoji_liv,
            prob_pct=prob,
            hazards_reali=reali_filtrati,
            hazards_potenziali=potenziali_filtrati,
            narrativa=None,
            day_label=day_label,
            date_str=_format_date(day_date),
            model_label=model_label,
            arpal_alert=arpal_alert,
            ffg_result=ffg_result,
            heatwave_result=hw_result,
            model_spread=spread,
            rain_evolution_text=rain_evo_txt,
            wind_evolution_text=wind_evo_txt,
            temp_anomaly=temp_anomaly,
        )
        site_data.setdefault("days", {})[day_label.lower()] = bulletin
        if day_label == "OGGI":
            site_data.update(bulletin)

    return "\n".join(lines), tomorrow_quarters

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

import os
import atexit

LOCK_FILE = "/tmp/meteobot.lock"

def main():
    from datetime import timedelta
    if os.path.exists(LOCK_FILE):
        print("⚠️ Un'altra esecuzione è già in corso, esco per evitare doppioni.")
        return
    open(LOCK_FILE, "w").close()
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.remove(LOCK_FILE))

    print("=" * 60)
    now   = datetime.datetime.now(TZ_ROME)
    today = now.date()
    print(f"\nOra: {now.strftime('%d/%m/%Y %H:%M')} – {LOCATION_NAME}")

    print("\n🚨 Verifico lo stato di allerta ufficiale ARPAL...")
    arpal_alert = fetch_arpal_alert()
    if arpal_alert.get("ok"):
        print(f"  ✓ Livello: {arpal_alert['level']} — {arpal_alert.get('title')}")
    else:
        print(f"  ⚠ Non disponibile: {arpal_alert.get('error')}")
        # Rete instabile/pagina irraggiungibile per questo solo ciclo: riusa
        # l'ultima lettura ARPAL reale pubblicata invece di mostrare "da
        # verificare" quando in realtà un'allerta era stata rilevata poco fa.
        try:
            with open("docs/site_data.json", encoding="utf-8") as f:
                prev_alert = json.load(f).get("forecast", {}).get("official_alert", {})
            if prev_alert.get("level") and "automaticamente" in (prev_alert.get("note") or ""):
                arpal_alert = {
                    "ok": True,
                    "level": prev_alert["level"],
                    "title": prev_alert.get("status"),
                    "risk_types": prev_alert.get("risk_types"),
                    "message_datetime": prev_alert.get("message_datetime"),
                    "source_url": prev_alert.get("url"),
                    "stale": True,
                }
                print(f"  ↺ Riuso ultima lettura ARPAL nota: {arpal_alert['level']}")
        except Exception:
            pass

    # ── 1. Fetch dati 3 giorni ────────────────────────────────────────────
    print("\n📡 Scaricamento dati Open-Meteo (AROME + ICON-EU)...")
    try:
        forecast = fetch_forecast_3days()
        model_primary = forecast["model_primary"]
        print(f"  ✓ Dati scaricati – modello primario: {model_primary}")
    except Exception as e:
        print(f"  ✗ Errore fetch: {e}")
        sys.exit(1)

  # ── Verifica freschezza dei dati NWP appena scaricati ─────────────────
    freshness = forecast.get("freshness", {})
    freshness_warnings = [info["msg"] for info in freshness.values() if not info.get("ok", True)]
    if freshness_warnings:
        print("\n⚠️  ATTENZIONE FRESCHEZZA DATI:")
        for w in freshness_warnings:
            print(f"  - {w}")
    else:
        print("\n✓ Run NWP aggiornate.")

    # ── 2. Storico temperature (per analisi ondata di calore) ──────────────
    print("\n🌡 Fetch storico temperature (7 giorni)...")
    try:
        temp_history = fetch_temperature_history(past_days=7)
        print(f"  ✓ {len(temp_history)} giorni di storico")
    except Exception as e:
        print(f"  ✗ Errore storico: {e}")
        temp_history = []

    # ── 3. Costruisci messaggi per i giorni ────────────────────────────────
    messages = []

    day1_hourly_preview = build_day_hourly_list(
        forecast["day1"],
        day_hourly_secondary=forecast.get("day1_icon"),
        primary_label="arome",
        secondary_label="icon",
    ) if forecast.get("day1") else []

    print(f"\n⚙️  Elaborazione OGGI ({_format_date(today)})...")
    site_data: dict = {}
    msg0, quarti_per_domani = build_day_message(
        day_date        = today,
        day_hourly      = forecast["day0"],
        day_label       = "OGGI",
        model_label     = model_primary,
        is_tendency     = False,
        day_hourly_icon = forecast.get("day0_icon"),
        day_offset      = 0,
        temp_history    = temp_history,
        site_data       = site_data,
        arome_pi_data   = forecast.get("arome_pi"),
        next_day_hourly_list = day1_hourly_preview,
        arpal_alert     = arpal_alert,
    )
    messages.append(msg0)
    print(f"  ✓ OGGI: {len(msg0)} chars")

    print(f"\n⚙️  Elaborazione DOMANI ({_format_date(today + timedelta(1))})...")
    msg1, _ = build_day_message(
        day_date        = today + timedelta(1),
        day_hourly      = forecast["day1"],
        day_label       = "DOMANI",
        model_label     = model_primary,
        is_tendency     = False,
        day_hourly_icon = forecast.get("day1_icon"),
        day_offset      = 1,
        temp_history    = temp_history,
        site_data       = site_data,
        arome_pi_data   = None,
        injected_quarters = quarti_per_domani,
        arpal_alert     = arpal_alert,
    )
    messages.append(msg1)
    print(f"  ✓ DOMANI: {len(msg1)} chars")

    print(f"\n⚙️  Elaborazione DOPODOMANI ({_format_date(today + timedelta(2))})...")
    msg2, _ = build_day_message(
        day_date        = today + timedelta(2),
        day_hourly      = forecast["day2"],
        day_label       = "DOPODOMANI",
        model_label     = model_primary,
        is_tendency     = False,
        day_hourly_icon = None,
        day_offset      = 2,
        temp_history    = temp_history,
        site_data       = site_data,
        arome_pi_data   = None,
        arpal_alert     = arpal_alert,
    )
    messages.append(msg2)
    print(f"  ✓ DOPODOMANI: {len(msg2)} chars")

    # ── Giorno 4 e 5: solo tendenza per il sito (niente Telegram/Gemini,
    # per non moltiplicare i costi AI su un orizzonte già poco affidabile) ──
    from api_builder import build_bulletin_json

    def _format_date_short(d):
        return f"{d.day} {MESI_IT[d.month - 1].capitalize()}"

    for day_key, day_offset, label in (("day3", 3, "GIORNO 4"), ("day4", 4, "GIORNO 5")):
        print(f"\n⚙️  Elaborazione {label} (tendenza, {_format_date(today + timedelta(day_offset))})...")
        try:
            day_data = forecast.get(day_key)
            day_obs = build_day_obs(day_data, model_primary)
            day_hourly = build_day_hourly_list(day_data, day_hourly_secondary=None, primary_label="arome", secondary_label="icon")
            day_result = run_pipeline(day_obs, day_hourly)
            day_rain = {"1h": float(day_obs.get("precip_rate_mm_h", 0) or 0), "24h": float(day_obs.get("rain_24h_mm", 0) or 0)}
            day_score = maltempo_score(day_result["params"], day_rain)
            day_level, day_emoji = livello_attenzione(day_score)
            day_prob = hazard_probability(day_result["params"])
            day_risks = assess_phenomena_risks(day_result["params"], day_obs, day_hourly, hazard_prob_pct=day_prob)
            day_hazards = day_result.get("hazards_dict", {"reali": [], "potenziali": []})
            bulletin = build_bulletin_json(
                result=day_result, obs=day_obs, hourly=day_hourly, risks=day_risks,
                m_score=day_score, livello=day_level, emoji_liv=day_emoji, prob_pct=day_prob,
                hazards_reali=day_hazards.get("reali", []), hazards_potenziali=day_hazards.get("potenziali", []),
                narrativa=None, day_label=label, date_str=_format_date_short(today + timedelta(day_offset)),
                model_label=model_primary, arpal_alert=arpal_alert,
            )
            site_data.setdefault("days", {})[label.lower().replace(" ", "")] = bulletin
            print(f"  ✓ {label} elaborato")
        except Exception as e:
            print(f"  ✗ Errore {label}: {e}")

    # ── Costruzione JSON per il sito web ───────────────────────────────────
    print("\n🌐 Costruzione dati per il sito web...")
    try:
        from api_builder import build_full_site_json

        zone_results = None
        try:
            from run_zone_forecast import build_all_zones_today
            zone_results = build_all_zones_today(arpal_alert=arpal_alert)
        except Exception as e:
            print(f"  ⚠ Zone non disponibili: {e}")

        try:
            from multi_model import fetch_and_compare
            print("  [multi_model] Confronto tra modelli disponibili...")
            site_data["model_comparison"] = fetch_and_compare()
        except Exception as e:
            print(f"  ⚠ Confronto multi-modello non disponibile: {e}")
            site_data["model_comparison"] = None

        snapshot = site_data.get("_snapshot", {})
        diff_precedente = confronta_con_precedente("oggi", snapshot)

        build_full_site_json(
            forecast=site_data,
            zone_results=zone_results,
            diff_precedente=diff_precedente,
            path="docs/site_data.json",
        )
        print("  ✓ docs/site_data.json generato")
    except Exception as e:
        print(f"  ✗ Errore generazione sito: {e}")

    # ── Salva JSON ──────────────────────────────────────────────────────
    export_json({"messages": messages, "generated": now.isoformat()}, "previsioni_output.json")
    print(f"\n✅ Completato. Output in previsioni_output.json")

if __name__ == "__main__":
    main()
