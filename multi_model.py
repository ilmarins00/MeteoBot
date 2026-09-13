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
from typing import Dict, Any, List, Optional, Tuple
from config import (
    LATITUDE, LONGITUDE, TIMEZONE, OPEN_METEO_BASE,
    MULTI_MODEL_SET, MULTI_MODEL_REFERENCE,
)

_VARS = ["temperature_2m", "precipitation", "wind_gusts_10m",
         "weather_code", "cloud_cover"]

# AROME (il riferimento) copre solo ~48-51h: oltre non avrebbe senso offrire
# un selettore giorno, il confronto risulterebbe sempre "non disponibile".
DAY_LABELS = ["oggi", "domani", "dopodomani"]


def fetch_multi_model_raw(
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    forecast_days: int = 3,
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
        "forecast_days": forecast_days,
    }
    try:
        resp = requests.get(OPEN_METEO_BASE, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [multi_model] Errore fetch: {e}")
        return None


def _day_bounds(hourly: Dict[str, List], day_index: int) -> Optional[Tuple[int, int]]:
    """Indici [start, end) delle ore del giorno n. day_index nell'array 'time'."""
    times = hourly.get("time") or []
    if not times:
        return None
    dates_seen: List[str] = []
    for t in times:
        date_part = t[:10]
        if date_part not in dates_seen:
            dates_seen.append(date_part)
    if day_index >= len(dates_seen):
        return None
    target_date = dates_seen[day_index]
    indices = [i for i, t in enumerate(times) if t[:10] == target_date]
    if not indices:
        return None
    return indices[0], indices[-1] + 1


def _daily_summary(hourly: Dict[str, List], suffix: str, bounds: Optional[Tuple[int, int]]) -> Optional[Dict[str, float]]:
    """Riassunto giornaliero (max/sum/mean) per UN modello, dai campi suffissati."""
    def col(var):
        values = hourly.get(f"{var}_{suffix}" if suffix else var, [])
        if bounds is None:
            return values
        start, end = bounds
        return values[start:end]

    precip = [v for v in col("precipitation") if v is not None]
    gusts  = [v for v in col("wind_gusts_10m") if v is not None]
    clouds = [v for v in col("cloud_cover") if v is not None]
    temps  = [v for v in col("temperature_2m") if v is not None]
    wmo    = [v for v in col("weather_code") if v is not None]

    if not temps:  # modello non disponibile per quest'area o per questo giorno
        return None

    return {
        "precip_sum":   round(sum(precip), 1) if precip else 0.0,
        "gust_max":     round(max(gusts), 1) if gusts else 0.0,
        "cloud_mean":   round(sum(clouds) / len(clouds), 0) if clouds else 0.0,
        "temp_max":     round(max(temps), 1),
        "wmo_max":      max(wmo) if wmo else 0,
    }


def compare_models(raw: Optional[Dict[str, Any]], day_index: int = 0) -> Dict[str, Any]:
    """
    Calcola, per ogni modello disponibile, il riassunto del giorno n. day_index
    (0 = oggi, 1 = domani, 2 = dopodomani), poi deriva un indice di concordanza
    rispetto ad AROME per: temporali, pioggia, vento forte, sole.
    """
    if raw is None:
        return {"available": False, "note": "Confronto multi-modello non disponibile (errore rete)."}

    hourly = raw.get("hourly", {})
    bounds = _day_bounds(hourly, day_index)
    if bounds is None:
        return {"available": False, "note": "Nessun dato orario disponibile per questo giorno."}

    per_model: Dict[str, Dict[str, float]] = {}
    for model_id, label in MULTI_MODEL_SET.items():
        # Open-Meteo: quando c'è un solo modello nella lista i campi non hanno
        # suffisso; con più modelli SÌ. Proviamo entrambi per sicurezza.
        summary = _daily_summary(hourly, model_id, bounds) or _daily_summary(hourly, "", bounds)
        if summary is not None:
            per_model[label] = summary

    if MULTI_MODEL_SET.get(MULTI_MODEL_REFERENCE, "AROME") not in per_model:
        return {
            "available": False,
            "note": "AROME non disponibile per questo giorno (fuori dal suo orizzonte di previsione): confronto saltato.",
        }


    arome_label = MULTI_MODEL_SET[MULTI_MODEL_REFERENCE]
    arome = per_model[arome_label]
    others = {k: v for k, v in per_model.items() if k != arome_label}
    n_total = len(others)

    wmo_convettivo = {80, 81, 82, 95, 96, 99}

    conditions = {
        "temporali":   lambda v: v["wmo_max"] in wmo_convettivo or v["precip_sum"] > 10,
        "pioggia":     lambda v: v["precip_sum"] > 1.0,
        "vento_forte": lambda v: v["gust_max"] > 50,
        "sole":        lambda v: v["cloud_mean"] < 30 and v["precip_sum"] < 0.5,
    }

    def pct_agree_with_arome(condition_fn) -> Optional[int]:
        """% di altri modelli che danno lo STESSO verdetto sì/no di AROME (usata solo per la confidenza interna)."""
        if n_total == 0:
            return None
        arome_verdict = condition_fn(arome)
        agree = sum(1 for v in others.values() if condition_fn(v) == arome_verdict)
        return round(agree / n_total * 100)

    # Quanti modelli (AROME incluso) prevedono ciascun fenomeno, sul totale disponibile.
    model_counts = {
        key: sum(1 for v in per_model.values() if cond(v))
        for key, cond in conditions.items()
    }

    # Confidenza complessiva = accordo con AROME sul rischio principale (temporali)
    confidenza_pct = pct_agree_with_arome(conditions["temporali"])
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
        "model_counts": model_counts,
        "confidenza": {"pct": confidenza_pct, "label": confidenza_label},
        "per_model_detail": per_model,
        "note": (
            "Conteggio basato sui modelli disponibili, non su un vero sistema "
            "di ensemble probabilistico: indica quanti modelli (AROME incluso) "
            "prevedono ciascun fenomeno, non una probabilità statistica verificata."
        ),
    }


def fetch_and_compare(lat: float = LATITUDE, lon: float = LONGITUDE) -> Dict[str, Any]:
    """Confronto per il solo giorno corrente (retrocompatibilità)."""
    raw = fetch_multi_model_raw(lat, lon, forecast_days=1)
    return compare_models(raw, day_index=0)


def fetch_and_compare_days(lat: float = LATITUDE, lon: float = LONGITUDE) -> Dict[str, Any]:
    """
    Punto di ingresso usato da run_previsioni_new.py: un'unica chiamata a
    Open-Meteo, poi un confronto per ciascun giorno coperto da AROME
    (oggi/domani/dopodomani — oltre il suo orizzonte non ha senso offrirlo).
    """
    raw = fetch_multi_model_raw(lat, lon, forecast_days=len(DAY_LABELS))
    return {
        label: compare_models(raw, day_index=i)
        for i, label in enumerate(DAY_LABELS)
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_and_compare(), ensure_ascii=False, indent=2))