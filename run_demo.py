# run_demo.py
"""
Demo eseguibile del motore meteorologico MeteoBot.

Modalità:
  python run_demo.py              # Dati reali da Open-Meteo (se internet disponibile)
  python run_demo.py --synthetic  # Profilo sintetico La Spezia (sempre funzionante)
"""

import sys
import json
import datetime

from engine import run_pipeline, export_json


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def synthetic_sounding():
    """
    Profilo verticale sintetico rappresentativo di una situazione
    pre-temporalesca tipica del Levante Ligure in estate
    (Scirocco umido, CAPE moderato, shear sufficiente per multicelle).
    """
    return {
        "pressure_pa":   [101500, 92500, 85000, 70000, 60000, 50000],
        "temperature_k": [301.15, 294.15, 286.15, 274.15, 263.15, 252.15],
        "dewpoint_k":    [294.15, 288.15, 279.15, 268.15, 256.15, 245.15],
        "u_ms":          [  3.0,    1.0,   -2.0,   -7.0,  -12.0,  -16.0],
        "v_ms":          [  5.0,    8.0,   12.0,   15.0,   18.0,   22.0],
        "height_m":      [    5,   760,  1460,  3010,  4500,  5570],
    }


def synthetic_obs() -> dict:
    now = datetime.datetime.utcnow().isoformat() + "Z"
    return {
        "time_generated":     now,
        "location":           "La Spezia – Foce (sintetico)",
        "cloud_cover_pct":    55,
        "cloud_high_pct":     75,
        "cloud_low_pct":      15,
        "precip_rate_mm_h":   18.5,
        "rain_1h_mm":         18.5,
        "rain_3h_mm":         42.0,
        "rain_6h_mm":         70.0,
        "rain_24h_mm":        95.0,
        "precip_start":       "18:30",
        "precip_end":         "22:00",
        "precip_peak_mm":     28.5,
        "wind_gust_kmh":      72.0,
        "wind_dir_deg":       210,      # Libeccio/Scirocco
        "wind_speed_ms":      12.0,
        "heat_index":         None,
        "temp_c":             27.5,
        "humidity_pct":       82,
        "pressure_hpa":       1008.5,
        "wave_height_m":      1.8,
        "front_present":      True,
        "low_level_convergence": True,
        "upper_level_tropospheric_vorticity": True,
        "hour_utc":           16,
        "sounding":           synthetic_sounding(),
    }


def synthetic_hourly(n: int = 12) -> list:
    import math
    rows = []
    cum = 0.0
    for i in range(n):
        h = 16 + i
        precip = max(0, 18.5 * math.exp(-0.3 * abs(i - 3)) - 2.0)
        cum += precip
        rows.append({
            "time":       f"{(h % 24):02d}:00",
            "T":          27.5 - i * 0.4,
            "RH":         82   + min(i * 1.5, 15),
            "wind":       35   + min(i * 5, 40),
            "wind_dir":   210,
            "precip":     round(precip, 1),
            "precip_cum": round(cum, 1),
            "CAPE":       max(0, 1600 - i * 120),
            "CIN":        -40,
            "shear":      32.0,
            "SRH":        180,
            "PWAT":       36,
            "wmo_code":   95 if precip > 5 else (80 if precip > 0 else 2),
            "alert":      "🟠" if precip >= 30 else ("🟡" if precip >= 10 else "🟢"),
        })
    return rows


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def main():
    use_synthetic = "--synthetic" in sys.argv

    if not use_synthetic:
        try:
            from io_ingest import fetch_openmeteo_current, build_obs_from_openmeteo, build_hourly_forecast_from_openmeteo
            print("Scarico dati da Open-Meteo...")
            data = fetch_openmeteo_current()
            obs = build_obs_from_openmeteo(data)
            hourly = build_hourly_forecast_from_openmeteo(data, n_hours=24)
            print(f"  Dati Open-Meteo: {len(hourly)} ore di previsione")
        except Exception as e:
            print(f"Open-Meteo non disponibile ({e}), uso dati sintetici.")
            obs    = synthetic_obs()
            hourly = synthetic_hourly()
    else:
        print("Modalità sintetica attivata (--synthetic)")
        obs    = synthetic_obs()
        hourly = synthetic_hourly()

    result = run_pipeline(obs, hourly)

    print("\n" + "═" * 70)
    print("METEOBOT – BOLLETTINO METEOROLOGICO LA SPEZIA")
    print("═" * 70)
    print("\n=== ALLERTA ===")
    m = result["meta"]
    print(f"  Livello : {m.get('alert_emoji','⚪')} {m['alert_level'].upper()}")
    print(f"  Score   : {m['score']}/12")
    print(f"  Modo    : {m['mode']}")
    print(f"  Oro.    : {m.get('orographic_factor', 0):.0%}")
    print(f"  Brezza  : {m.get('sea_breeze_convergence', 0):.0%}")

    print("\n=== SEZIONE 1 – PREVISIONE PUBBLICA ===")
    print(result["section1"])

    print("\n=== SEZIONE 2 – ANALISI TECNICA ===")
    print(result["section2"])

    if result.get("hazards"):
        print("\n=== FENOMENI SEVERI ===")
        for h in result["hazards"]:
            print(f"  ⚠ {h}")

    print("\n=== SEZIONE 3 – TABELLA ORARIA (prime 5 righe) ===")
    rows = result["section3"].split("\n")
    for r in rows[:6]:
        print(" ", r)

    print("\n=== PROMPT GEMINI (prime 30 righe) ===")
    lines = result["gemini_prompt"].split("\n")
    for ln in lines[:30]:
        print(ln)
    if len(lines) > 30:
        print(f"  ... ({len(lines) - 30} righe omesse)")

    export_json(result, "demo_output.json")
    print(f"\nOutput completo salvato in demo_output.json")


if __name__ == "__main__":
    main()
