# engine.py
"""
Orchestratore principale del motore meteorologico MeteoBot.
Pipeline completa:
  1) Ingestione e validazione dati (obs + sounding)
  2) Calcolo termodinamica: SBCAPE, MUCAPE, MLCAPE, CIN, LCL, θe (thermo.py)
  3) Calcolo indici dinamici: shear, SRH reale (Bunkers), PWAT nativo (indices.py)
  4) Indici compositi: EHI, SCP, STP, K-Index, TT, SWEAT, lapse rates
  5) Fattori orografici Spezzino e brezza marina (indices.py)
  6) Scoring convettivo multi-parametro (logic.py)
  7) Classificazione modalità convettiva (logic.py)
  8) Hazard mapping completo (logic.py)
  9) Allerta ARPAL composita (logic.py)
 10) Generazione sezioni bollettino e prompt Gemini (templates.py)
 11) Export JSON
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from config import (
    THRESHOLDS, ALERT_EMOJI, thresholds,
    LATITUDE, LONGITUDE, ORO_ENHANCEMENT_FACTOR,
)
from indices import (
    compute_shear_profile, compute_srh,
    compute_lapse_rates,
    k_index, totals_totals, sweat_index,
    ehi, supercell_composite, significant_tornado_parameter,
    pwat_from_profile,
    orographic_enhancement, sea_breeze_convergence_score,
)
from thermo import compute_all_thermo
from logic import (
    convective_score, classify_storm_mode, severe_hazards,
    map_score_to_alert, full_alert, composite_arpal_alert,
)
from templates import (
    render_section1_simple, render_section2_detailed,
    render_section3_objective_table, build_gemini_prompt,
)

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Costruzione parametri da obs
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _extract_sounding_levels(
    sounding: Dict[str, Any]
) -> Tuple[List, List, List, List, List, List]:
    """Estrae e valida i profili verticali dal sounding."""
    pressure    = sounding.get("pressure_pa",    [])
    temperature = sounding.get("temperature_k",  [])
    dewpoint    = sounding.get("dewpoint_k",     [])
    u_prof      = sounding.get("u_ms",           [])
    v_prof      = sounding.get("v_ms",           [])
    heights     = sounding.get("height_m",       [])
    # Verifica lunghezze coerenti
    min_len = min(
        len(pressure), len(temperature), len(dewpoint),
        len(u_prof) if u_prof else 999,
        len(v_prof) if v_prof else 999,
        len(heights) if heights else 999,
    )
    return (
        pressure[:min_len], temperature[:min_len], dewpoint[:min_len],
        u_prof[:min_len]   if u_prof  else [],
        v_prof[:min_len]   if v_prof  else [],
        heights[:min_len]  if heights else [],
    )


def build_params_from_obs(obs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Costruisce il dizionario params con tutti gli indici calcolati.
    Gestisce sia profili verticali completi (sounding) sia
    osservazioni superficiali (fallback).
    """
    params: Dict[str, Any] = {}
    sounding = obs.get("sounding")

    if sounding:
        pres, temp, dewp, u_prof, v_prof, heights = _extract_sounding_levels(sounding)

        if pres and temp and dewp:
            # \u2014 Termodinamica completa
            thermo = compute_all_thermo(pres, temp, dewp)
            params.update(thermo)

            # \u2014 PWAT nativo (integrazione discreta)
            params["PWAT"] = pwat_from_profile(pres, temp, dewp)

            # \u2014 Indici classici (approssimazione da profilo)
            # T e Td interpolati a 500, 700, 850 hPa (in °C)
            T500  = _interp_level(pres, temp,  50000)
            T700  = _interp_level(pres, temp,  70000)
            T850  = _interp_level(pres, temp,  85000)
            Td850 = _interp_level(pres, dewp,  85000)
            Td700 = _interp_level(pres, dewp,  70000)
            if T500 and T700 and T850 and Td850 and Td700:
                Tc500  = T500  - 273.15
                Tc700  = T700  - 273.15
                Tc850  = T850  - 273.15
                Tdc850 = Td850 - 273.15
                Tdc700 = Td700 - 273.15
                params["KI"] = round(k_index(Tc850, Tdc850, Tc700, Tdc700, Tc500), 1)
                params["TT"] = round(totals_totals(Tc850, Tdc850, Tc500), 1)

            # \u2014 Lapse rates
            if heights:
                lr = compute_lapse_rates(temp, heights)
                params.update({k: round(v, 2) if v is not None else None
                                for k, v in lr.items()})

        if u_prof and v_prof and heights:
            # \u2014 Shear
            shear = compute_shear_profile(u_prof, v_prof, heights)
            params.update(shear)

            # \u2014 SRH reale (Bunkers)
            srh = compute_srh(u_prof, v_prof, heights)
            params.update(srh)

        # \u2014 Indici compositi
        cape = params.get("MUCAPE", params.get("SBCAPE", params.get("CAPE", 0)))
        srh1 = params.get("srh_0_1", 0)
        srh3 = params.get("srh_0_3", 0)
        shear06 = params.get("shear_0_6", 0)
        shear01 = params.get("shear_0_1", 0)
        lcl = params.get("LCL", 1000)
        cin = params.get("CIN", params.get("SBCIN", 0))

        params["EHI"] = round(ehi(cape, max(srh1, srh3)), 3)
        params["SCP"] = round(supercell_composite(cape, srh3, shear06), 3)
        params["STP"] = round(
            significant_tornado_parameter(
                params.get("SBCAPE", cape), srh1, shear06, lcl or 1000, cin or 0
            ), 3
        )

        # SWEAT (solo se il profilo vento è disponibile)
        wind_850, wind_500 = None, None
        if u_prof and v_prof and len(u_prof) == len(heights):
            wind_850 = _interp_wind_level(u_prof, v_prof, heights, 1500)
            wind_500 = _interp_wind_level(u_prof, v_prof, heights, 5500)
        if wind_850 and wind_500 and params.get("TT"):
            params["SWEAT"] = round(
                sweat_index(
                    Tdc850 if "Tdc850" in dir() else 10,
                    params["TT"],
                    wind_850[0], wind_500[0],
                    wind_850[1], wind_500[1],
                ), 1
            )

        # — DCAPE dal profilo (se non già calcolato in io_ingest)
        dcape_pre = obs.get("DCAPE")
        if dcape_pre is not None:
            params["DCAPE"] = dcape_pre
        else:
            try:
                from thermo import dcape_from_profile as _dcape_fn
                params["DCAPE"] = _dcape_fn(pres, temp, dewp)
            except Exception:
                params["DCAPE"] = 0.0

    else:
        # — Fallback: osservazioni superficiali
        params.update({
            "CAPE":   obs.get("CAPE",      0),
            "SBCAPE": obs.get("SBCAPE",    obs.get("CAPE", 0)),
            "MUCAPE": obs.get("MUCAPE",    obs.get("CAPE", 0)),
            "MLCAPE": obs.get("MLCAPE",    obs.get("CAPE", 0)),
            "CIN":    obs.get("CIN",       0),
            "SBCIN":  obs.get("SBCIN",     obs.get("CIN", 0)),
            "shear_0_6": obs.get("shear_0_6", 0),
            "shear_0_1": obs.get("shear_0_1", 0),
            "srh_0_1":   obs.get("srh_0_1",   0),
            "srh_0_3":   obs.get("srh_0_3",   0),
            "PWAT":      obs.get("PWAT",       0),
            "LCL":       obs.get("LCL",        None),
            "LI":        obs.get("LI",         None),
            "TT":        obs.get("TT",         None),
            "KI":        obs.get("KI",         None),
            "EHI":       obs.get("EHI",        None),
            "SCP":       obs.get("SCP",        None),
            "STP":       obs.get("STP",        None),
        })

    # — Parametri superficiali sempre presenti
    params.update({
        "precip_rate_mm_h":  obs.get("precip_rate_mm_h", 0),
        "wind_gust_kmh":     obs.get("wind_gust_kmh",    0),
        "heat_index":        obs.get("heat_index",       None),
        "temp_c":            obs.get("temp_c",           None),
        "humidity_pct":      obs.get("humidity_pct",     0),
        "pressure_hpa":      obs.get("pressure_hpa",     1013),
        "wave_height_m":     obs.get("wave_height_m",    0),
        "snow_level_m":      obs.get("snow_level_m",     2000),
        "rain_24h_mm":       obs.get("rain_24h_mm",      0),
        "wmo_code":          obs.get("wmo_code",         0),
        "soil_moisture":      obs.get("soil_moisture",    None),
        "DCAPE":              obs.get("DCAPE",             params.get("DCAPE", 0)),
        "front_present":             obs.get("front_present",             False),
        "low_level_convergence":     obs.get("low_level_convergence",     False),
        "upper_level_tropospheric_vorticity": obs.get(
            "upper_level_tropospheric_vorticity", False
        ),
        "temp_dewpoint_spread": (
            (obs.get("temp_c", 20) or 20)
            - ((obs.get("temp_c", 20) or 20) - 2)   # placeholder se non fornito
            if obs.get("temp_dewpoint_spread") is None
            else obs.get("temp_dewpoint_spread")
        ),
    })

    # \u2014 Fattore orografico e brezza marina
    wind_dir = obs.get("wind_dir_deg", 225)
    wind_ms  = obs.get("wind_speed_ms", obs.get("wind_gust_kmh", 0) / 3.6)
    cape_factor = min(params.get("MUCAPE", 0) / 2000.0, 1.0)
    params["orographic_factor"] = round(
        orographic_enhancement(wind_dir, wind_ms, instability_factor=max(cape_factor, 0.3)),
        3,
    )
    hour_utc = obs.get("hour_utc", datetime.now(timezone.utc).hour)
    params["sea_breeze_convergence"] = round(
        sea_breeze_convergence_score(wind_dir, wind_ms, 200, hour_utc),
        3,
    )

    return params


def _interp_level(
    pressure: List[float], values: List[float], target_pa: float
) -> Optional[float]:
    """Interpolazione lineare di un campo a una pressione target (Pa)."""
    for i in range(1, len(pressure)):
        if pressure[i-1] >= target_pa >= pressure[i]:
            frac = (pressure[i-1] - target_pa) / max(pressure[i-1] - pressure[i], 1)
            return values[i-1] + frac * (values[i] - values[i-1])
    return None


def _interp_wind_level(
    u_prof: List[float], v_prof: List[float], heights: List[float], target_m: float
) -> Optional[tuple]:
    """Restituisce (speed_kt, dir_deg) interpolato alla quota target (m)."""
    import math as _math
    from indices import interpolate_wind
    if not heights:
        return None
    u, v = interpolate_wind(u_prof, v_prof, heights, target_m)
    speed_kt = _math.hypot(u, v) * 1.94384
    dir_deg  = (_math.degrees(_math.atan2(-u, -v)) + 360) % 360
    return speed_kt, dir_deg


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Pipeline principale
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def run_pipeline(
    obs: Dict[str, Any],
    hourly_forecast: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Esegue la pipeline meteorologica completa.
    obs            : osservazioni correnti + sounding opzionale
    hourly_forecast: lista previsioni orarie per Sezione 3
    Ritorna dict con tutte le sezioni, parametri, allerte e metadati.
    """
    params = build_params_from_obs(obs)

    # Score e classificazione
    score   = convective_score(params)
    mode    = classify_storm_mode(params)
    hazards = severe_hazards(params)

    # Allerta ARPAL composita
    rain_obs = {
        "1h":  obs.get("rain_1h_mm",  obs.get("precip_rate_mm_h", 0)),
        "3h":  obs.get("rain_3h_mm",  0),
        "6h":  obs.get("rain_6h_mm",  0),
        "12h": obs.get("rain_12h_mm", 0),
        "24h": obs.get("rain_24h_mm", 0),
    }
    alert_level, alert_emoji = full_alert(params, score, rain_obs)
    _, alert_detail = composite_arpal_alert(
        rain_1h=rain_obs["1h"],  rain_3h=rain_obs["3h"],
        rain_6h=rain_obs["6h"],  rain_12h=rain_obs["12h"],
        rain_24h=rain_obs["24h"],
        wind_kmh=params.get("wind_gust_kmh", 0),
        temp_c=params.get("temp_c"),
        wave_height_m=params.get("wave_height_m", 0),
    )

    # Generazione sezioni bollettino
    section1 = render_section1_simple(obs, params, score, alert_level)
    section2 = render_section2_detailed(obs, params, mode, hazards, alert_detail)
    section3 = render_section3_objective_table(hourly_forecast)
    gemini_prompt = build_gemini_prompt(section1, section2, score, params, alert_level)

    return {
        "meta": {
            "generated_at": obs.get("time_generated", datetime.now(timezone.utc).isoformat()),
            "location":     obs.get("location", f"La Spezia ({LATITUDE}N, {LONGITUDE}E)"),
            "score":        score,
            "alert_level":  alert_level,
            "alert_emoji":  alert_emoji,
            "alert_detail": alert_detail,
            "mode":         mode,
            "orographic_factor":    params.get("orographic_factor", 0),
            "sea_breeze_convergence": params.get("sea_breeze_convergence", 0),
        },
        "section1":      section1,
        "section2":      section2,
        "section3":      section3,
        "gemini_prompt": gemini_prompt,
        "params":        params,
        "hazards":       hazards,
    }


def export_json(result: Dict[str, Any], path: str) -> None:
    """Salva il risultato completo in JSON (UTF-8, indent 2)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if sounding:
        pressure = sounding.get("pressure_pa", [])
        temperature = sounding.get("temperature_k", [])
        dewpoint = sounding.get("dewpoint_k", [])
        u_prof = sounding.get("u_ms", [])
        v_prof = sounding.get("v_ms", [])
        heights = sounding.get("height_m", [])

        # CAPE/CIN (usa metpy se disponibile)
        if pressure and temperature and dewpoint:
            # parcel from surface
            parcel_p = pressure[0]
            parcel_T = temperature[0]
            parcel_Td = dewpoint[0]
            cape, cin = cape_cin_from_profile(pressure, temperature, dewpoint, parcel_p, parcel_T, parcel_Td)
            params["CAPE"] = cape
            params["CIN"] = cin
        else:
            params["CAPE"] = obs.get("CAPE", 0)
            params["CIN"] = obs.get("CIN", 0)

        # Shear profile
        if u_prof and v_prof and heights:
            shear = compute_shear_profile(u_prof, v_prof, heights)
            params.update(shear)
            srh = compute_srh(u_prof, v_prof, heights)
            params.update(srh)
        else:
            params["shear_0_6"] = obs.get("shear_0_6", 0)
            params["srh_0_1"] = obs.get("srh_0_1", 0)

        # PWAT
        params["PWAT"] = pwat_from_profile(pressure, temperature, dewpoint)
        # LCL
        params["LCL"] = lcl_height(temperature[0], dewpoint[0], pressure[0]) if temperature and dewpoint else obs.get("LCL", None)
    else:
        # fallback su osservazioni superficiali
        params["CAPE"] = obs.get("CAPE", 0)
        params["CIN"] = obs.get("CIN", 0)
        params["shear_0_6"] = obs.get("shear_0_6", 0)
        params["srh_0_1"] = obs.get("srh_0_1", 0)
        params["PWAT"] = obs.get("PWAT", 0)
        params["LCL"] = obs.get("LCL", None)

    # Aggiungi altri parametri utili
    params["LI"] = obs.get("LI", None)
    params["precip_rate_mm_h"] = obs.get("precip_rate_mm_h", 0)
    params["wind_gust_kmh"] = obs.get("wind_gust_kmh", 0)
    params["heat_index"] = obs.get("heat_index", None)

    return params

def run_pipeline(obs: Dict[str, Any], hourly_forecast: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Esegue pipeline completa e ritorna JSON con sezioni e metadati.
    hourly_forecast: lista oraria per Sezione 3.
    """
    params = build_params_from_obs(obs)
    score = convective_score(params)
    mode = classify_storm_mode(params)
    hazards = severe_hazards(params)
    section1 = render_section1_simple(obs, params, score)
    section2 = render_section2_detailed(obs, params, mode, hazards)
    section3 = render_section3_objective_table(hourly_forecast)
    gemini_prompt = build_gemini_prompt(section1, section2, score, params)
    alert_level = map_score_to_alert(score)

    result = {
        "meta": {
            "generated_at": obs.get("time_generated", None),
            "location": obs.get("location", "unspecified"),
            "score": score,
            "alert_level": alert_level,
            "mode": mode,
        },
        "section1": section1,
        "section2": section2,
        "section3": section3,
        "gemini_prompt": gemini_prompt,
        "params": params,
        "hazards": hazards,
    }
    return result

def export_json(result: Dict[str, Any], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)