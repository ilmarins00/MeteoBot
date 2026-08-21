# multi_model.py
"""
Confronto multi-modello per stimare la "concordanza" tra le previsioni
disponibili su Open-Meteo, usando AROME come riferimento primario del
bollettino (mai sostituito). Serve a rispondere a: "quanti modelli, tra
quelli disponibili, sono d'accordo con AROME su un fenomeno?"

ATTENZIONE ONESTÀ SCIENTIFICA: l'accordo tra modelli NON è una probabilità
statistica verificata (tipo un vero sistema di ensemble con perturbazioni
calibrate). È una stima euristica: "quanti modelli indipendenti dicono la
stessa cosa" — un'indicazione di CONFIDENZA nella previsione, non una
percentuale di accadimento nel senso meteorologico rigoroso. Va presentata
al sito con questa cautela esplicita.
"""

import requests
from typing import Dict, Any, List, Optional
from config import (
    LATITUDE, LONGITUDE, TIMEZONE, OPEN_METEO_BASE,
    MULTI_MODEL_SET, MULTI_MODEL_REFERENCE,
)

_VARS = ["temperature_2m", "precipitation", "wind_gusts_10m",
         "weather_code", "cloud_cover"]


def fetch_multi_model_raw(
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    timeout: int = 30,
) -> Optional[Dict[str, Any]]:
    """
    Una sola chiamata Open-Meteo con tutti i modelli del set. Open-Meteo,
    quando si passano più modelli, restituisce ogni variabile con suffisso
    per modello (es. 'temperature_2m_icon_eu'). Se un modello non copre
    l'area (es. ICON-D2 fuori dominio), i suoi campi arrivano come null:
    li scartiamo più sotto, non li trattiamo come zero.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(_VARS),
        "models": ",".join(MULTI_MODEL_SET.keys()),
        "timezone": TIMEZONE,
        "forecast_days": 1,
    }
    try:
        resp = requests.get(OPEN_METEO_BASE, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [multi_model] Errore fetch: {e}")
        return None


def _daily_summary(hourly: Dict[str, List], suffix: str) -> Optional[Dict[str, float]]:
    """Riassunto giornaliero (max/sum/mean) per UN modello, dai campi suffissati."""
    def col(var):
        key = f"{var}_{suffix}" if suffix else var
        return hourly.get(key, [])

    precip = [v for v in col("precipitation") if v is not None]
    gusts  = [v for v in col("wind_gusts_10m") if v is not None]
    clouds = [v for v in col("cloud_cover") if v is not None]
    temps  = [v for v in col("temperature_2m") if v is not None]
    wmo    = [v for v in col("weather_code") if v is not None]

    if not temps:  # modello non disponibile per quest'area
        return None

    return {
        "precip_sum":   round(sum(precip), 1) if precip else 0.0,
        "gust_max":     round(max(gusts), 1) if gusts else 0.0,
        "cloud_mean":   round(sum(clouds) / len(clouds), 0) if clouds else 0.0,
        "temp_max":     round(max(temps), 1),
        "wmo_max":      max(wmo) if wmo else 0,
    }


def compare_models(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcola, per ogni modello disponibile, il riassunto giornaliero, poi
    deriva un indice di concordanza rispetto ad AROME per: temporali,
    pioggia, vento forte, sole.
    """
    if raw is None:
        return {"available": False, "note": "Confronto multi-modello non disponibile (errore rete)."}

    hourly = raw.get("hourly", {})
    per_model: Dict[str, Dict[str, float]] = {}
    for model_id, label in MULTI_MODEL_SET.items():
        # Open-Meteo: quando c'è un solo modello nella lista i campi non hanno
        # suffisso; con più modelli SÌ. Proviamo entrambi per sicurezza.
        summary = _daily_summary(hourly, model_id) or _daily_summary(hourly, "")
        if summary is not None:
            per_model[label] = summary

    if MULTI_MODEL_SET.get(MULTI_MODEL_REFERENCE, "AROME") not in per_model:
        return {
            "available": False,
            "note": "AROME non disponibile in questa chiamata: confronto saltato.",
        }

    arome_label = MULTI_MODEL_SET[MULTI_MODEL_REFERENCE]
    arome = per_model[arome_label]
    others = {k: v for k, v in per_model.items() if k != arome_label}
    n_total = len(others)

    def pct_agree(condition_fn) -> Optional[int]:
        if n_total == 0:
            return None
        agree = sum(1 for v in others.values() if condition_fn(v))
        return round(agree / n_total * 100)

    wmo_convettivo = {80, 81, 82, 95, 96, 99}

    probability = {
        "temporali": pct_agree(lambda v: v["wmo_max"] in wmo_convettivo or v["precip_sum"] > 10),
        "pioggia":   pct_agree(lambda v: v["precip_sum"] > 1.0),
        "vento_forte": pct_agree(lambda v: v["gust_max"] > 50),
        "sole":      pct_agree(lambda v: v["cloud_mean"] < 30 and v["precip_sum"] < 0.5),
    }

    # Confidenza complessiva: quanti modelli, su quelli disponibili, hanno
    # risposto "sì/no" nello stesso verso di AROME sul rischio principale
    arome_temporali = arome["wmo_max"] in wmo_convettivo or arome["precip_sum"] > 10
    concordi_con_arome = sum(
        1 for v in others.values()
        if (v["wmo_max"] in wmo_convettivo or v["precip_sum"] > 10) == arome_temporali
    )
    confidenza_pct = round(concordi_con_arome / n_total * 100) if n_total else None
    if confidenza_pct is None:
        confidenza_label = "n.d."
    elif confidenza_pct >= 80:
        confidenza_label = "alta"
    elif confidenza_pct >= 50:
        confidenza_label = "media"
    else:
        confidenza_label = "bassa"

    return {
        "available": True,
        "reference_model": arome_label,
        "reference_summary": arome,
        "models_compared": list(per_model.keys()),
        "n_models_available": len(per_model),
        "probability": probability,
        "confidenza": {"pct": confidenza_pct, "label": confidenza_label},
        "per_model_detail": per_model,
        "note": (
            "Percentuali basate sull'accordo tra i modelli disponibili, non su "
            "un vero sistema di ensemble probabilistico: indicano quanto la "
            "previsione AROME è condivisa dagli altri modelli, non una "
            "probabilità statistica verificata."
        ),
    }


def fetch_and_compare(lat: float = LATITUDE, lon: float = LONGITUDE) -> Dict[str, Any]:
    """Punto di ingresso unico usato da run_previsioni_new.py."""
    raw = fetch_multi_model_raw(lat, lon)
    return compare_models(raw)


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_and_compare(), ensure_ascii=False, indent=2))