# run_zone_forecast.py
"""
Calcola la previsione COMPLETA (non solo score) per le 4 zone interne di
La Spezia. Ogni zona interroga Open-Meteo su coordinate proprie e applica
il fattore orografico basato sulla propria elevazione.

Uso standalone (nessuna chiave richiesta, serve solo la rete verso
Open-Meteo, già nell'allowlist del progetto):
    python run_zone_forecast.py
"""

import datetime
from typing import Dict, Any
from zoneinfo import ZoneInfo

from config import CITY_ZONES, ZONE_DIFFERENCE_SIGNIFICANT_THRESHOLD
from io_ingest import fetch_forecast_3days, build_day_obs, build_day_hourly_list
from engine import run_pipeline
from logic import maltempo_score, livello_attenzione, hazard_probability, assess_phenomena_risks
from api_builder import build_bulletin_json

_TZ_ROME = ZoneInfo("Europe/Rome")
_GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
            "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_DAY_OFFSETS = {"OGGI": 0, "DOMANI": 1, "DOPODOMANI": 2, "GIORNO 4": 3, "GIORNO 5": 4}


def _format_date_it(d: datetime.date) -> str:
    return f"{_GIORNI_IT[d.weekday()]} {d.day} {_MESI_IT[d.month - 1]} {d.year}"


# Formato breve "[numero] [mese]" (es. "12 Settembre"), usato per le schede
# giorno 4/5 che sono solo una tendenza (nessun nome tipo "oggi"/"domani").
def _format_date_short_it(d: datetime.date) -> str:
    return f"{d.day} {_MESI_IT[d.month - 1].capitalize()}"


def build_zone_result(zona_id: str, zona: Dict[str, Any], arpal_alert: Dict[str, Any] = None) -> Dict[str, Any]:
    """Calcola la pipeline completa per UNA zona e restituisce un bollettino
    con la STESSA struttura di quello generale (hourly, hazards, risk_panel),
    non solo un numero di score — altrimenti selezionare una zona nel sito
    non mostra quasi nulla di diverso dal quadro cittadino."""
    region = zona.get("region", "liguria")
    forecast = fetch_forecast_3days(lat=zona["lat"], lon=zona["lon"])
    day0 = forecast["day0"]

    obs = build_day_obs(day0, forecast["model_primary"])
    if not obs:
        return {
            "label": zona["label"], "alert_level": "n.d.", "alert_emoji": "⚪",
            "score": 0, "note_locale": zona["note"],
            "error": "dati insufficienti per questa zona",
        }

    obs["elevation_m"] = zona["elevation_m"]
    obs["hour_utc"] = obs.get("hour_utc", 14)

    hourly = build_day_hourly_list(
        day0, day_hourly_secondary=forecast.get("day0_icon"),
        primary_label="arome", secondary_label="icon",
    )

    result = run_pipeline(obs, hourly)
    rain_obs = {
        "1h": float(obs.get("precip_rate_mm_h", 0) or 0),
        "24h": float(obs.get("rain_24h_mm", 0) or 0),
    }
    m_score = maltempo_score(result["params"], rain_obs)
    livello, emoji_liv = livello_attenzione(m_score)
    prob = hazard_probability(result["params"])
    risks = assess_phenomena_risks(result["params"], obs, hourly, hazard_prob_pct=prob)
    hazards_dict = result.get("hazards_dict", {"reali": [], "potenziali": []})

    def build_day_bulletin(day_key: str, day_label: str) -> Dict[str, Any]:
        day_data = forecast[day_key]
        day_obs = build_day_obs(day_data, forecast["model_primary"])
        day_hourly = build_day_hourly_list(
            day_data,
            day_hourly_secondary=forecast.get(f"{day_key}_icon"),
            primary_label="arome", secondary_label="icon",
        )
        day_result = run_pipeline(day_obs, day_hourly)
        day_rain = {"1h": float(day_obs.get("precip_rate_mm_h", 0) or 0), "24h": float(day_obs.get("rain_24h_mm", 0) or 0)}
        day_score = maltempo_score(day_result["params"], day_rain)
        day_level, day_emoji = livello_attenzione(day_score)
        day_prob = hazard_probability(day_result["params"])
        day_risks = assess_phenomena_risks(day_result["params"], day_obs, day_hourly, hazard_prob_pct=day_prob)
        day_hazards = day_result.get("hazards_dict", {"reali": [], "potenziali": []})
        target_date = datetime.datetime.now(_TZ_ROME).date() + datetime.timedelta(days=_DAY_OFFSETS.get(day_label, 0))
        return build_bulletin_json(
            result=day_result, obs=day_obs, hourly=day_hourly, risks=day_risks,
            m_score=day_score, livello=day_level, emoji_liv=day_emoji,
            prob_pct=day_prob, hazards_reali=day_hazards.get("reali", []),
            hazards_potenziali=day_hazards.get("potenziali", []), narrativa=None,
            day_label=day_label, date_str=_format_date_short_it(target_date), model_label=forecast["model_primary"],
            region=region, arpal_alert=arpal_alert,
        )

    bulletin = build_bulletin_json(
        result=result, obs=obs, hourly=hourly, risks=risks,
        m_score=m_score, livello=livello, emoji_liv=emoji_liv,
        prob_pct=prob,
        hazards_reali=hazards_dict.get("reali", []),
        hazards_potenziali=hazards_dict.get("potenziali", []),
        narrativa=None,  # niente Gemini per le zone: costerebbe 4x le chiamate AI
        day_label="OGGI", date_str=_format_date_it(datetime.datetime.now(_TZ_ROME).date()),
        model_label=forecast["model_primary"], region=region, arpal_alert=arpal_alert,
    )
    bulletin.pop("_snapshot", None)
    bulletin["label"] = zona["label"]
    bulletin["note_locale"] = zona["note"]
    today_bulletin = dict(bulletin)
    bulletin["days"] = {
        "oggi": today_bulletin,
        "domani": build_day_bulletin("day1", "DOMANI"),
        "dopodomani": build_day_bulletin("day2", "DOPODOMANI"),
        "giorno4": build_day_bulletin("day3", "GIORNO 4"),
        "giorno5": build_day_bulletin("day4", "GIORNO 5"),
    }
    for day in bulletin["days"].values():
        day["label"] = zona["label"]
        day["note_locale"] = zona["note"]
    return bulletin


def build_all_zones_today(arpal_alert: Dict[str, Any] = None, max_workers: int = 5) -> Dict[str, Any]:
    """
    Scarica ed elabora tutte le zone in parallelo (thread pool): ogni zona fa
    solo chiamate di rete (I/O), quindi più thread possono aspettare le
    risposte di Open-Meteo insieme invece che una zona alla volta. Ogni zona
    scrive SOLO nella propria chiave del dizionario "risultati" (nessuno
    stato condiviso tra thread), quindi non c'è alcun rischio di mescolare i
    dati tra zone diverse. Un errore/timeout di rete su una zona continua a
    essere isolato e gestito come prima (fallback a un placeholder "n.d.").
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    risultati: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_zona = {
            executor.submit(build_zone_result, zona_id, zona, arpal_alert): (zona_id, zona)
            for zona_id, zona in CITY_ZONES.items()
        }
        for future in as_completed(future_to_zona):
            zona_id, zona = future_to_zona[future]
            print(f"  [zone] Elaboro {zona['label']}...")
            try:
                risultati[zona_id] = future.result()
            except Exception as e:
                print(f"  ✗ [zone] Errore su {zona['label']}: {e}")
                risultati[zona_id] = {
                    "label": zona["label"], "alert_level": "n.d.", "alert_emoji": "⚪",
                    "score": 0, "note_locale": zona["note"], "error": str(e),
                }

    scores = [r.get("current", {}).get("score", r.get("score", 0)) for r in risultati.values()]
    scores = [s for s in scores if isinstance(s, (int, float))]
    diff = (max(scores) - min(scores)) if len(scores) >= 2 else 0
    differenze_significative = diff >= ZONE_DIFFERENCE_SIGNIFICANT_THRESHOLD

    return {
        "zones": risultati,
        "differenze_significative": differenze_significative,
        "score_spread": round(diff, 1),
        "nota": (
            f"Le zone mostrano differenze meteorologiche rilevanti oggi (spread {diff:.1f}/5)."
            if differenze_significative else
            "Condizioni sostanzialmente omogenee su tutta la città: le piccole "
            "differenze tra zone rientrano nell'incertezza del modello."
        ),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build_all_zones_today(), ensure_ascii=False, indent=2))