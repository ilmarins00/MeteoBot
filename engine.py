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
    render_analisi_semplice, render_section1_simple,
    render_section2_detailed, render_section3_objective_table,
    build_gemini_prompt_tecnico, render_telegram_message
)

def build_gemini_prompt(section1, section2, score, params, alert_level=""):
    """Alias legacy per compatibilità."""
    from logic import hazard_probability
    prob = hazard_probability(params)
    return build_gemini_prompt_tecnico(
        analisi_tecnica=section2,
        params=params,
        maltempo_score_val=score,
        hazard_probability_pct=prob,
        giorno_label="oggi",
        is_tendency=False,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Costruzione parametri da obs
# ─────────────────────────────────────────────────────────────────────────────

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
            # — Termodinamica: usa CAPE del modello, non ricalcolato da pochi livelli
            # compute_all_thermo su 5-6 livelli isobarici produce CAPE inattendibile
            # (es. 4112 J/kg invece del 350 reale del modello).
            # Lo usiamo solo per LCL e θe, MA SOVRASCRIVIAMO CAPE/CIN/LI con i valori
            # nativi del modello (già presenti in obs).
            n_levels = len(pres)
            model_cape = obs.get("CAPE", obs.get("SBCAPE", 0)) or 0
            model_mucape = obs.get("MUCAPE", model_cape) or 0
            model_mlcape = obs.get("MLCAPE", model_cape) or 0
            model_cin = obs.get("CIN", obs.get("SBCIN", 0)) or 0
            model_li = obs.get("LI", None)

            # Solo con un sounding ad alta risoluzione (≥20 livelli, es. UWYO)
            # usiamo il CAPE calcolato da thermo.py
            if n_levels >= 20:
                thermo = compute_all_thermo(pres, temp, dewp)
                params.update(thermo)
            else:
                # Sounding a bassa risoluzione: usa solo LCL/θe dal thermo,
                # ma mantieni CAPE/CIN/LI del modello
                thermo = compute_all_thermo(pres, temp, dewp)
                # Estrai solo LCL e parametri non-CAPE dal thermo
                for k, v in thermo.items():
                    if k not in ("SBCAPE", "SBCIN", "MUCAPE", "MUCIN",
                                 "MLCAPE", "MLCIN", "CAPE", "CIN", "LI"):
                        params[k] = v
                # Forza i valori del modello
                params["CAPE"] = model_cape
                params["SBCAPE"] = model_cape
                params["MUCAPE"] = model_mucape
                params["MLCAPE"] = model_mlcape
                params["CIN"] = model_cin
                params["SBCIN"] = model_cin

                # Controllo plausibilità LI: più il CAPE è basso, meno
                # negativo può essere un LI credibile (soglia continua).
                cape_check = max(model_cape, model_mucape)
                if model_li is None:
                    params["LI"] = None
                else:
                    li_limit = -6.0 - (cape_check / 150.0)
                    if cape_check < 1500 and model_li < li_limit:
                        params["LI"] = None  # inattendibile, scarta
                    else:
                        params["LI"] = model_li

            # — PWAT nativo (integrazione discreta)
            params["PWAT"] = pwat_from_profile(pres, temp, dewp)

            # — Indici classici (approssimazione da profilo)
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
                params["T_850hPa"] = round(Tc850, 1)
                params["T_700hPa"] = round(Tc700, 1)
                params["T_500hPa"] = round(Tc500, 1)
                params["Td_850hPa"] = round(Tdc850, 1)

            # — Lapse rates
            if heights:
                lr = compute_lapse_rates(temp, heights)
                params.update({k: round(v, 2) if v is not None else None
                                for k, v in lr.items()})

         # — Indici dinamici e compositi: SOLO se il profilo vento è disponibile
            if u_prof and v_prof and heights and len(u_prof) >= 3:
                # — Shear
                shear = compute_shear_profile(u_prof, v_prof, heights)
                params.update(shear)

                # — SRH reale (Bunkers)
                srh = compute_srh(u_prof, v_prof, heights)
                params.update(srh)

                # — Indici compositi (calcolati con dati coerenti)
                cape = params.get("MUCAPE", params.get("SBCAPE", params.get("CAPE", 0)))
                srh1 = params.get("srh_0_1", 0)
                srh3 = params.get("srh_0_3", 0)
                shear06 = params.get("shear_0_6", 0)
                lcl = params.get("LCL", 1000)
                cin = params.get("CIN", params.get("SBCIN", 0))

                params["EHI"] = round(ehi(cape, max(srh1, srh3)), 3)
                params["SCP"] = round(supercell_composite(cape, srh3, shear06), 3)
                params["STP"] = round(
                    significant_tornado_parameter(
                        params.get("SBCAPE", cape), srh1, shear06, lcl or 1000, cin or 0
                    ), 3
                )
            else:
                # Profilo vento non disponibile (Open-Meteo non fornisce u/v sui livelli)
                # NON inventare shear=0 e NON calcolare indici compositi nonsensici
                params["shear_0_6"] = None
                params["shear_0_3"] = None
                params["shear_0_1"] = None
                params["srh_0_3"] = None
                params["srh_0_1"] = None
                params["EHI"] = None
                params["SCP"] = None
                params["STP"] = None

        # — DCAPE: solo se sounding ad alta risoluzione, altrimenti N/D
            dcape_pre = obs.get("DCAPE")
            if dcape_pre is not None:
                params["DCAPE"] = dcape_pre
            elif len(pres) >= 20:
                try:
                    from thermo import dcape_from_profile as _dcape_fn
                    params["DCAPE"] = _dcape_fn(pres, temp, dewp)
                except Exception:
                    params["DCAPE"] = None
            else:
                # Sounding low-res: DCAPE inattendibile
                params["DCAPE"] = None

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
    })

    # — Fattore orografico e brezza marina
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


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline principale
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    obs: Dict[str, Any],
    hourly_forecast: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Esegue la pipeline meteorologica completa.
    """
    params = build_params_from_obs(obs)
    score = convective_score(params)
    mode = classify_storm_mode(params)
    
    # Ora hazards è un dizionario {"reali": [...], "potenziali": [...]}
    hazards_dict = severe_hazards(params)
    
    # Passiamo una lista piatta al calcolo allerta per retrocompatibilità, se serve
    all_hazards_flat = hazards_dict["reali"] + hazards_dict["potenziali"]

    rain_obs = {
        "1h": float(obs.get("precip_rate_mm_h", 0) or 0),
        "24h": float(obs.get("rain_24h_mm", 0) or 0),
    }
    alert_level, alert_emoji = full_alert(params, score, rain_obs)
    _, alert_detail = composite_arpal_alert(
        rain_1h=rain_obs["1h"], rain_24h=rain_obs["24h"],
        wind_kmh=params.get("wind_gust_kmh", 0), temp_c=params.get("temp_c"), wave_height_m=params.get("wave_height_m", 0),
    )

    # V-Shape e trombe marine (logica aggiuntiva, indipendente dal bollettino)
    from logic import rileva_fenomeni_costieri
    nuovi_rischi = rileva_fenomeni_costieri(params)
    all_hazards_flat.extend(nuovi_rischi)

    section1 = render_section1_simple(obs, params, score, alert_level)
    section2 = render_section2_detailed(obs, params, mode, all_hazards_flat, alert_detail)
    section3 = render_section3_objective_table(hourly_forecast)
    gemini_prompt = build_gemini_prompt(section1, section2, score, params, alert_level)

    return {
        "meta": {
            "generated_at": obs.get("time_generated", datetime.now(timezone.utc).isoformat()),
            "location": obs.get("location", "La Spezia"),
            "score": score,
            "alert_level": alert_level,
            "alert_emoji": alert_emoji,
            "alert_detail": alert_detail,
            "mode": mode,
            "orographic_factor": params.get("orographic_factor", 0),
        },
        "hazards_dict": hazards_dict,
        "hazards": all_hazards_flat,
        "params": params,
        "section1": section1,
        "section2": section2,
        "section3": section3,
        "gemini_prompt": gemini_prompt,
    }


def export_json(result: Dict[str, Any], path: str) -> None:
    """Salva il risultato completo in JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
