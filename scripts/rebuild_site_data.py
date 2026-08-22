"""Rigenera il payload web senza inviare notifiche o messaggi esterni."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import datetime
from zoneinfo import ZoneInfo

from api_builder import build_bulletin_json, build_full_site_json
from config import CITY_ZONES, LATITUDE, LONGITUDE
from engine import run_pipeline
from io_ingest import build_day_hourly_list, build_day_obs, fetch_arpal_alert, fetch_forecast_3days
from logic import assess_phenomena_risks, hazard_probability, livello_attenzione, maltempo_score

_TZ_ROME = ZoneInfo("Europe/Rome")
_GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
            "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_DAY_OFFSETS = {"day0": 0, "day1": 1, "day2": 2}


def _format_date_it(d: datetime.date) -> str:
    return f"{_GIORNI_IT[d.weekday()]} {d.day} {_MESI_IT[d.month - 1]} {d.year}"


def build_day(forecast, day_key, label, arpal_alert=None, region="liguria"):
    day_data = forecast[day_key]
    obs = build_day_obs(day_data, forecast["model_primary"])
    hourly = build_day_hourly_list(
        day_data,
        day_hourly_secondary=forecast.get(f"{day_key}_icon"),
        primary_label="arome",
        secondary_label="icon",
    )
    result = run_pipeline(obs, hourly)
    rain = {"1h": float(obs.get("precip_rate_mm_h", 0) or 0), "24h": float(obs.get("rain_24h_mm", 0) or 0)}
    score = maltempo_score(result["params"], rain)
    level, emoji = livello_attenzione(score)
    probability = hazard_probability(result["params"])
    risks = assess_phenomena_risks(result["params"], obs, hourly, hazard_prob_pct=probability)
    hazards = result.get("hazards_dict", {"reali": [], "potenziali": []})
    return build_bulletin_json(
        result=result, obs=obs, hourly=hourly, risks=risks, m_score=score,
        livello=level, emoji_liv=emoji, prob_pct=probability,
        hazards_reali=hazards.get("reali", []),
        hazards_potenziali=hazards.get("potenziali", []), narrativa=None,
        day_label=label, date_str="", model_label=forecast["model_primary"],
        arpal_alert=arpal_alert, region=region,
    )


def build_location(lat, lon, label=None, note=None, arpal_alert=None, region="liguria"):
    forecast = fetch_forecast_3days(lat=lat, lon=lon)
    days = {
        "oggi": build_day(forecast, "day0", "OGGI", arpal_alert, region=region),
        "domani": build_day(forecast, "day1", "DOMANI", arpal_alert, region=region),
        "dopodomani": build_day(forecast, "day2", "DOPODOMANI", arpal_alert, region=region),
    }
    result = dict(days["oggi"])
    result["days"] = days
    if label:
        result["label"] = label
        result["note_locale"] = note
        for day in days.values():
            day["label"] = label
            day["note_locale"] = note
    return result


def _load_previous(path="docs/site_data.json"):
    """Ultimo site_data.json pubblicato, usato come rete di sicurezza se un
    fetch fallisce (es. timeout Open-Meteo su una singola zona): meglio dati
    di 10-15 minuti fa che un sito rotto o senza quella sezione."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    print("[arpal] Verifico lo stato di allerta ufficiale...")
    arpal_alert = fetch_arpal_alert()
    if arpal_alert.get("ok"):
        print(f"[arpal] Livello rilevato: {arpal_alert['level']} — {arpal_alert.get('title')}")
    else:
        print(f"[arpal] Non disponibile: {arpal_alert.get('error')}")

    previous = _load_previous()

    try:
        general = build_location(LATITUDE, LONGITUDE, arpal_alert=arpal_alert)
    except Exception as e:
        print(f"[generale] Fetch fallito ({e}), riuso l'ultima versione pubblicata")
        general = previous.get("forecast") if previous else None
    if general is None:
        print("[generale] Nessun dato disponibile (nuovo/nè fresco nè precedente): esco senza scrivere nulla")
        sys.exit(1)

    prev_zones = (previous or {}).get("areas", {}).get("zones", {})
    zones = {}
    for zone_id, zone in CITY_ZONES.items():
        print(f"[zone] {zone['label']}")
        try:
            zones[zone_id] = build_location(
                zone["lat"], zone["lon"], zone["label"], zone["note"],
                arpal_alert=arpal_alert, region=zone.get("region", "liguria"),
            )
        except Exception as e:
            print(f"[zone] {zone['label']}: fetch fallito ({e})")
            if zone_id in prev_zones:
                print(f"[zone] {zone['label']}: riuso l'ultima versione pubblicata")
                zones[zone_id] = prev_zones[zone_id]
            else:
                print(f"[zone] {zone['label']}: nessun dato precedente, zona omessa in questo aggiornamento")

    scores = [zone["current"].get("score", 0) for zone in zones.values()]
    zone_payload = {
        "zones": zones,
        "differenze_significative": max(scores) - min(scores) >= 1 if scores else False,
        "score_spread": round(max(scores) - min(scores), 1) if scores else 0,
        "nota": "Previsioni calcolate sulle coordinate delle singole zone.",
    }
    build_full_site_json(general, zone_payload, None, "docs/site_data.json")
    print("docs/site_data.json rigenerato")


if __name__ == "__main__":
    main()
