#!/usr/bin/env python3
"""
qualita_aria.py — Qualità dell'aria + Nebbia predittiva per MeteoBot
=====================================================================
Fornisce due funzionalità:

1. fetch_air_quality() → dict con PM2.5, PM10, O3, NO2, AQI europeo
   Sorgente: Open-Meteo Air Quality API (CAMS European)

2. valuta_nebbia(temp, dew_point, umidita, vento, ora, storico) → dict | None
   Nebbia predittiva: qualsiasi ora del giorno, non solo notte/mattina.
   Restituisce None se non c'è rischio, altrimenti un dict con
   livello ("possibile" | "probabile" | "certa") e messaggio HTML.

Utilizzo da altri script:
    from qualita_aria import fetch_air_quality, valuta_nebbia
"""

import math
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import LATITUDE, LONGITUDE

TZ_ROME = ZoneInfo("Europe/Rome")

# ── Soglie AQI europeo (indice 0-5, scala WHO / EAQI) ─────────────────────
# Fonte: European Air Quality Index (https://airindex.eea.europa.eu/)
_EAQI_LEVELS = [
    (0,   "🟢 Buona"),
    (20,  "🟡 Discreta"),
    (40,  "🟠 Moderata"),
    (60,  "🟠 Scarsa"),
    (80,  "🔴 Molto scarsa"),
    (100, "🔴 Estremamente scarsa"),
]

_POLLUTANT_THRESHOLDS = {
    # (Buona, Discreta, Moderata, Scarsa, Molto scarsa) μg/m³
    "pm2_5":  (10,  20,  25,  50,   75),
    "pm10":   (20,  40,  50,  100,  150),
    "ozone":  (60,  100, 130, 240,  380),
    "no2":    (40,  90,  120, 230,  340),
    "so2":    (100, 200, 350, 500,  750),
}


def _sub_index(pollutant: str, value: float) -> int:
    """Calcola il sub-indice EAQI (0-100) per un singolo inquinante."""
    if value is None or math.isnan(value):
        return 0
    thresholds = _POLLUTANT_THRESHOLDS.get(pollutant)
    if not thresholds:
        return 0
    # Mappa lineare su 5 fasce (0-20, 20-40, 40-60, 60-80, 80-100)
    breakpoints = [0] + list(thresholds) + [thresholds[-1] * 2]
    for i in range(len(breakpoints) - 1):
        if value <= breakpoints[i + 1]:
            frac = (value - breakpoints[i]) / max(breakpoints[i + 1] - breakpoints[i], 1e-9)
            return int(i * 20 + frac * 20)
    return 100


def _eaqi_label(index: int) -> str:
    label = _EAQI_LEVELS[-1][1]
    for threshold, lbl in _EAQI_LEVELS:
        if index <= threshold:
            label = lbl
            break
    return label


def fetch_air_quality(timeout: int = 15) -> dict | None:
    """
    Scarica qualità dell'aria da Open-Meteo Air Quality API (CAMS).
    Restituisce un dict con i valori attuali oppure None se non disponibile.

    Campi restituiti:
        pm2_5, pm10, ozone, no2, so2, european_aqi (int),
        eaqi_label (str), timestamp (str), avvisi (list[str])
    """
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "pm2_5,pm10,ozone,nitrogen_dioxide,sulphur_dioxide,european_aqi",
        "timezone": "Europe/Rome",
    }
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"⚠️  Air quality fetch error: {e}")
        return None

    current = data.get("current", {})
    if not current:
        print("⚠️  Air quality: dati current non disponibili")
        return None

    pm25  = current.get("pm2_5")
    pm10  = current.get("pm10")
    o3    = current.get("ozone")
    no2   = current.get("nitrogen_dioxide")
    so2   = current.get("sulphur_dioxide")
    eaqi  = current.get("european_aqi")

    # Calcola EAQI se non fornito dall'API
    if eaqi is None:
        sub_indices = [
            _sub_index("pm2_5", pm25  or 0),
            _sub_index("pm10",  pm10  or 0),
            _sub_index("ozone", o3    or 0),
            _sub_index("no2",   no2   or 0),
        ]
        eaqi = max(sub_indices)

    avvisi = []
    if pm25 is not None and pm25 > 25:
        avvisi.append(f"⚠️ PM2.5 elevato ({pm25:.0f} μg/m³, soglia OMS 24h: 25)")
    if pm10 is not None and pm10 > 50:
        avvisi.append(f"⚠️ PM10 elevato ({pm10:.0f} μg/m³, soglia OMS 24h: 50)")
    if o3 is not None and o3 > 120:
        avvisi.append(f"⚠️ Ozono elevato ({o3:.0f} μg/m³)")
    if no2 is not None and no2 > 200:
        avvisi.append(f"⚠️ NO₂ elevato ({no2:.0f} μg/m³)")

    result = {
        "pm2_5":        round(pm25, 1)  if pm25  is not None else None,
        "pm10":         round(pm10, 1)  if pm10  is not None else None,
        "ozone":        round(o3,   1)  if o3    is not None else None,
        "no2":          round(no2,  1)  if no2   is not None else None,
        "so2":          round(so2,  1)  if so2   is not None else None,
        "european_aqi": int(eaqi)       if eaqi  is not None else None,
        "eaqi_label":   _eaqi_label(int(eaqi)) if eaqi is not None else "N/D",
        "timestamp":    current.get("time", ""),
        "avvisi":       avvisi,
    }
    print(
        f"✓ Air quality: PM2.5={result['pm2_5']} PM10={result['pm10']} "
        f"O3={result['ozone']} NO2={result['no2']} EAQI={result['european_aqi']} ({result['eaqi_label']})"
    )
    return result


def _trend_umidita(storico: list, ore: int = 2) -> float:
    """
    Calcola la variazione di umidità relativa nelle ultime `ore` ore.
    Positivo = umidità in aumento.
    """
    now = datetime.now(TZ_ROME)
    cutoff = now - timedelta(hours=ore)
    recenti = []
    for s in storico:
        ts_str = s.get("ts")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ_ROME)
            if ts >= cutoff:
                u = s.get("umidita")
                if u is not None:
                    recenti.append((ts, float(u)))
        except Exception:
            continue
    if len(recenti) < 2:
        return 0.0
    recenti.sort(key=lambda x: x[0])
    return recenti[-1][1] - recenti[0][1]


def _trend_pressione(storico: list, ore: int = 3) -> float:
    """
    Calcola la variazione di pressione nelle ultime `ore` ore.
    Negativo = pressione in calo (favorisce stabilità nebbia).
    """
    now = datetime.now(TZ_ROME)
    cutoff = now - timedelta(hours=ore)
    recenti = []
    for s in storico:
        ts_str = s.get("ts")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ_ROME)
            if ts >= cutoff:
                p = s.get("pressione")
                if p is not None:
                    recenti.append((ts, float(p)))
        except Exception:
            continue
    if len(recenti) < 2:
        return 0.0
    recenti.sort(key=lambda x: x[0])
    return recenti[-1][1] - recenti[0][1]


def valuta_nebbia(
    temp: float,
    dew_point: float,
    umidita: float,
    vento: float,
    ora: int,
    storico: list | None = None,
) -> dict | None:
    """
    Valuta il rischio nebbia/foschia in qualsiasi momento della giornata.

    Parametri:
        temp      — temperatura aria (°C)
        dew_point — punto di rugiada (°C)
        umidita   — umidità relativa (%)
        vento     — velocità vento media (km/h)
        ora       — ora corrente (0-23)
        storico   — lista di campioni storico_24h per calcolo trend

    Restituisce None se rischio assente, altrimenti:
        {
          "livello":  "possibile" | "probabile" | "certa",
          "emoji":    str,
          "tipo":     "nebbia" | "foschia",
          "condizioni": str,   # descrizione HTML
          "avviso":   str,     # riga di avviso per il report
        }

    Algoritmo:
    - Spread T-Td < 4°C → condizione necessaria
    - Score composto da:
        spread (0-3 pt) + umidità (0-2 pt) + ora (0-2 pt) +
        vento calmo (0-1 pt) + trend umidità crescente (0-1 pt) +
        pressione alta stabile (0-1 pt)
    - Score ≥ 6 → certa; ≥ 4 → probabile; ≥ 2 → possibile
    """
    spread = temp - dew_point

    # Condizione necessaria: spread < 4°C
    if spread >= 4.0:
        return None

    score = 0
    motivi = []

    # 1. Spread T-Td (0-3 pt)
    if spread <= 0.5:
        score += 3; motivi.append(f"spread T-Td ≤ 0.5°C ({spread:.1f}°C)")
    elif spread <= 1.5:
        score += 2; motivi.append(f"spread T-Td ≤ 1.5°C ({spread:.1f}°C)")
    elif spread <= 3.0:
        score += 1; motivi.append(f"spread T-Td ≤ 3.0°C ({spread:.1f}°C)")

    # 2. Umidità relativa (0-2 pt)
    if umidita >= 95:
        score += 2; motivi.append(f"U={umidita:.0f}%")
    elif umidita >= 85:
        score += 1; motivi.append(f"U={umidita:.0f}%")

    # 3. Ore favorevoli: notte/alba/tramonto/sera (0-2 pt)
    if 0 <= ora <= 8 or 19 <= ora <= 23:
        score += 2; motivi.append("ore notturne/serali")
    elif 9 <= ora <= 11 or 17 <= ora <= 18:
        score += 1; motivi.append("ore di transizione")
    # else: pomeriggio soleggiato — no bonus

    # 4. Vento calmo (0-1 pt)
    if vento < 5:
        score += 1; motivi.append(f"vento calmo ({vento:.1f} km/h)")

    # 5. Trend umidità crescente (0-1 pt)
    if storico:
        delta_u = _trend_umidita(storico, ore=2)
        if delta_u >= 5:
            score += 1; motivi.append(f"umidità ↑{delta_u:.0f}% in 2h")

    # 6. Pressione alta e stabile (favorisce nebbia radiativa) (0-1 pt)
    if storico:
        delta_p = _trend_pressione(storico, ore=3)
        if abs(delta_p) < 0.5 and score > 0:
            score += 1; motivi.append("pressione stabile")

    if score < 2:
        return None

    # Classificazione
    if score >= 6:
        livello = "certa"
        emoji = "🌫️"
    elif score >= 4:
        livello = "probabile"
        emoji = "🌫️"
    else:
        livello = "possibile"
        emoji = "🌁"

    tipo = "nebbia" if spread <= 1.5 and umidita >= 90 else "foschia"
    condizioni_txt = "; ".join(motivi)

    avviso = (
        f"{emoji} AVVISO NEBBIA ({livello.upper()}): "
        f"{tipo.capitalize()} {livello} — {condizioni_txt}"
    )

    return {
        "livello":    livello,
        "emoji":      emoji,
        "tipo":       tipo,
        "score":      score,
        "condizioni": condizioni_txt,
        "avviso":     avviso,
    }


def formatta_sezione_aria(aq: dict) -> str:
    """Restituisce la sezione HTML per il report Telegram."""
    pm25_str = f"{aq['pm2_5']:.1f} μg/m³" if aq.get("pm2_5") is not None else "N/D"
    pm10_str = f"{aq['pm10']:.1f} μg/m³"  if aq.get("pm10")  is not None else "N/D"
    o3_str   = f"{aq['ozone']:.1f} μg/m³" if aq.get("ozone") is not None else "N/D"
    no2_str  = f"{aq['no2']:.1f} μg/m³"   if aq.get("no2")   is not None else "N/D"

    sezione = (
        f"🏭 <b>QUALITÀ DELL'ARIA (CAMS)</b>\n"
        f"Indice EAQI: {aq.get('european_aqi', 'N/D')} — {aq.get('eaqi_label', 'N/D')}\n"
        f"PM2.5: {pm25_str}\n"
        f"PM10:  {pm10_str}\n"
        f"O₃:    {o3_str}\n"
        f"NO₂:   {no2_str}\n"
    )
    return sezione