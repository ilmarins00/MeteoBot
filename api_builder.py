# api_builder.py
"""
Costruisce output JSON strutturati per il frontend del sito, a partire
dagli oggetti già prodotti dal motore MeteoBot (engine.run_pipeline,
logic.assess_phenomena_risks). Non fa NESSUN nuovo calcolo meteorologico:
riorganizza dati già esistenti in una forma consumabile da un frontend.
"""

import json
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional


# Sottoinsieme di params mostrato nella sezione "tecnica" del sito.
_TECHNICAL_FIELDS = [
    "SBCAPE", "MUCAPE", "CIN", "LI", "shear_0_6", "srh_0_3",
    "PWAT", "SCP", "STP", "KI", "TT", "DCAPE",
]
_ROME = ZoneInfo("Europe/Rome")


def _build_day_highlights(hourly: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Timeline sintetica dei momenti più significativi della giornata, calcolata
    deterministicamente dai dati orari già disponibili (nessuna chiamata AI):
    è sempre disponibile anche quando l'analisi AI non è stata generata.
    """
    if not hourly:
        return []
    events = []
    peak_cape = max(hourly, key=lambda h: float(h.get("CAPE") or 0), default=None)
    if peak_cape and float(peak_cape.get("CAPE") or 0) >= 500:
        events.append({"time": peak_cape.get("time"), "label": f"Picco di energia convettiva (CAPE {peak_cape['CAPE']:.0f} J/kg)"})
    peak_rain = max(hourly, key=lambda h: float(h.get("precip") or 0), default=None)
    if peak_rain and float(peak_rain.get("precip") or 0) >= 1:
        events.append({"time": peak_rain.get("time"), "label": f"Massimo delle precipitazioni ({peak_rain['precip']:.1f} mm/h)"})
    peak_gust = max(hourly, key=lambda h: float(h.get("wind_gust") or 0), default=None)
    if peak_gust and float(peak_gust.get("wind_gust") or 0) >= 40:
        events.append({"time": peak_gust.get("time"), "label": f"Raffica massima prevista ({peak_gust['wind_gust']:.0f} km/h)"})
    storm_hours = [h for h in hourly if int(h.get("wmo_code") or 0) in (95, 96, 99)]
    if storm_hours:
        events.append({"time": storm_hours[0].get("time"), "label": "Inizio della finestra con rischio temporali"})
    events.sort(key=lambda e: e.get("time") or "")
    return events


def _build_insights(
    storm_mode: Optional[str],
    ffg_result: Optional[Dict[str, Any]],
    heatwave_result: Optional[Dict[str, Any]],
    model_spread: Optional[Dict[str, Any]],
    uwyo_summary: Optional[str],
    rain_evolution_text: Optional[str],
    wind_evolution_text: Optional[str],
    temp_anomaly: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """
    Raccoglie le analisi che nel vecchio bollettino Telegram/HTML erano solo
    testo (flash flood, ondata di calore, spread AROME/ICON, radiosondaggio,
    evoluzione pioggia/vento, anomalia termica in quota) e che il sito non
    mostrava ancora. Ogni voce è opzionale: appare solo se rilevante per la
    giornata.
    """
    insights: List[Dict[str, str]] = []
    if storm_mode and storm_mode not in ("n.d.", ""):
        from logic import is_intense_storm_mode
        if is_intense_storm_mode(storm_mode):
            insights.append({"label": "Modalità temporalesca", "text": storm_mode})
    if ffg_result and ffg_result.get("desc"):
        insights.append({"label": "Rischio flash flood", "text": ffg_result["desc"]})
    if heatwave_result and heatwave_result.get("severity") not in ("nessuna", None, "") and heatwave_result.get("desc"):
        insights.append({"label": "Ondata di calore", "text": heatwave_result["desc"]})
    if model_spread:
        for label, v in model_spread.items():
            nomi = {"CAPE_peak": "Energia convettiva (CAPE)", "precip_sum": "Pioggia totale", "gust_max": "Raffica massima"}
            forte = " — incertezza forte" if v.get("high") else ""
            insights.append({
                "label": f"Confronto modelli: {nomi.get(label, label)}",
                "text": f"AROME {v['AROME']}{v['unit']} vs ICON-EU {v['ICON']}{v['unit']} (differenza {v['diff']}{v['unit']}{forte})",
            })
    if uwyo_summary:
        insights.append({"label": "Radiosondaggio osservato", "text": uwyo_summary})
    if rain_evolution_text:
        insights.append({"label": "Evoluzione pioggia", "text": rain_evolution_text})
    if wind_evolution_text:
        insights.append({"label": "Evoluzione vento", "text": wind_evolution_text})
    if temp_anomaly and temp_anomaly.get("desc"):
        insights.append({"label": "Anomalia termica in quota", "text": temp_anomaly["desc"]})
    return insights


def build_bulletin_json(
    result: Dict[str, Any],
    obs: Dict[str, Any],
    hourly: List[Dict[str, Any]],
    risks: Dict[str, str],
    m_score: float,
    livello: str,
    emoji_liv: str,
    prob_pct: int,
    hazards_reali: List[str],
    hazards_potenziali: List[str],
    narrativa: Optional[str],
    day_label: str,
    date_str: str,
    model_label: str,
    arpal_alert: Optional[Dict[str, Any]] = None,
    ffg_result: Optional[Dict[str, Any]] = None,
    heatwave_result: Optional[Dict[str, Any]] = None,
    model_spread: Optional[Dict[str, Any]] = None,
    uwyo_summary: Optional[str] = None,
    rain_evolution_text: Optional[str] = None,
    wind_evolution_text: Optional[str] = None,
    temp_anomaly: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Riconfeziona l'output di run_pipeline() + dati collaterali già calcolati
    in build_day_message() in un JSON pensato per un frontend web.
    """
    params = result.get("params", {})
    meta = result.get("meta", {})

    technical = {
        k: params.get(k) for k in _TECHNICAL_FIELDS if params.get(k) is not None
    }

    # Serie oraria ridotta ai campi utili al frontend (niente dati tecnici
    # duplicati qui, quelli stanno in "technical" e nella sezione tecnica
    # espandibile del sito se vorrai estenderla in futuro)
    hourly_light = [
        {
            "time": h.get("time"),
            "T": h.get("T"),
            "RH": h.get("RH"),
            "wind": h.get("wind"),
            "wind_dir": h.get("wind_dir"),
            "wind_gust": h.get("wind_gust"),
            "precip": h.get("precip"),
            "cloud": h.get("cloud"),
            "cloud_low": h.get("cloud_low"),
            "cloud_mid": h.get("cloud_mid"),
            "cloud_high": h.get("cloud_high"),
            "CAPE": h.get("CAPE"),
            "CIN": h.get("CIN"),
            "shear": h.get("shear"),
            "SRH": h.get("SRH"),
            "PWAT": h.get("PWAT"),
            "DCAPE": h.get("DCAPE"),
            "SCP": h.get("SCP"),
            "wmo_code": h.get("wmo_code"),
        }
        for h in (hourly or [])[:24]
    ]

    first_hour = next((h for h in hourly_light if h.get("T") is not None), {})
    current_temp = first_hour.get("T", obs.get("temp_c"))
    current_wind = first_hour.get("wind", obs.get("wind_speed_kmh"))
    current_gust = first_hour.get("wind_gust", obs.get("wind_gust_kmh"))
    current_precip = first_hour.get("precip", obs.get("precip_rate_mm_h", 0))

    snapshot = {
        "score": m_score,
        "wind_gust_kmh": float(obs.get("wind_gust_kmh", 0) or 0),
        "rain_peak": max((h.get("precip") or 0) for h in (hourly or [])) if hourly else 0.0,
    }

    if arpal_alert and arpal_alert.get("ok"):
        official_alert = {
            "status": arpal_alert.get("title") or "Nessuna Allerta",
            "level": arpal_alert.get("level"),
            "risk_types": arpal_alert.get("risk_types"),
            "message_datetime": arpal_alert.get("message_datetime"),
            "source": "AllertaLiguria / ARPAL",
            "url": arpal_alert.get("source_url") or "https://allertaliguria.regione.liguria.it/allerta_protezione_civile.php",
            "note": "Rilevato automaticamente dal portale ufficiale ARPAL.",
        }
    else:
        official_alert = {
            "status": "da verificare sul portale ufficiale",
            "level": None,
            "source": "AllertaLiguria / ARPAL",
            "url": "https://allertaliguria.regione.liguria.it/allerta_protezione_civile.php",
            "note": "Lettura automatica non disponibile in questo momento.",
        }

    return {
        "official_alert": official_alert,
        "meta": {
                "location": "La Spezia",
                "area_label": "Quadro generale della città",
                "reference_point": obs.get("location", "La Spezia"),
            "day_label": day_label,
            "date": date_str,
            "model": model_label,
            "generated_at": datetime.now(_ROME).isoformat(),
            "timezone": "Europe/Rome",
            "source": obs.get("source", model_label),
        },
        "current": {
            "temp_c": current_temp,
            "temp_max_c": obs.get("temp_max_c"),
            "temp_min_c": obs.get("temp_min_c"),
            "apparent_temperature": obs.get("apparent_temperature", obs.get("heat_index")),
            "wind_kmh": current_wind,
            "wind_gust_kmh": current_gust,
            "precip_rate_mm_h": current_precip,
            "cloud_pct": first_hour.get("cloud"),
            "cloud_low_pct": first_hour.get("cloud_low"),
            "cloud_mid_pct": first_hour.get("cloud_mid"),
            "cloud_high_pct": first_hour.get("cloud_high"),
            "wmo_code": first_hour.get("wmo_code", obs.get("wmo_code", 0)),
            # Condizione più severa prevista nelle prossime ore, per distinguere
            # "adesso" da "punta attesa" e non dare l'impressione di un errore
            # quando ora è sereno ma nel pomeriggio è previsto un temporale.
            "wmo_peak_code": max((h.get("wmo_code") or 0 for h in hourly_light), default=0),
            "alert_level": official_alert.get("level"),
            "alert_source": "ARPAL" if official_alert.get("level") else None,
            "model_alert_level": meta.get("alert_level", "verde"),
            "model_alert_emoji": meta.get("alert_emoji", "🟢"),
            "livello_attenzione": livello,
            "livello_emoji": emoji_liv,
            "score": m_score,
            "score_scale": 5,
        },
        "risk_panel": risks,
        "hourly": hourly_light,
        "technical": technical,
        "hazards": {
            "reali": hazards_reali,
            "potenziali": hazards_potenziali,
        },
        "summary": result.get("section1", ""),
        "highlights": _build_day_highlights(hourly_light),
        "insights": _build_insights(
            meta.get("mode"), ffg_result, heatwave_result, model_spread,
            uwyo_summary, rain_evolution_text, wind_evolution_text, temp_anomaly,
        ),
        "technical_analysis": None,
        "hazard_probability_pct": prob_pct,
        "ai_analysis": narrativa,
        "model_comparison": None,  # riempito da run_previsioni_new.py con multi_model.fetch_and_compare()
        "_snapshot": snapshot,  # uso interno per il confronto storico, il frontend lo ignora
    }


def build_full_site_json(
    forecast: Dict[str, Any],
    zone_results: Optional[Dict[str, Any]],
    diff_precedente: Optional[List[str]],
    path: str = "docs/site_data.json",
) -> Dict[str, Any]:
    """
    Assembla il JSON finale che il sito consuma via fetch().
    Rimuove la chiave interna "_snapshot" prima di scrivere su disco.
    """
    forecast_clean = {k: v for k, v in forecast.items() if k != "_snapshot"}

    payload = {
        "city": "La Spezia",
        "generated_at": datetime.now(_ROME).isoformat(),
        "timezone": "Europe/Rome",
        "forecast": forecast_clean,
        "areas": zone_results or {},
        "changes_since_last": diff_precedente,
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    directory = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".site_data_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception:
        os.unlink(temp_path)
        raise

    return payload