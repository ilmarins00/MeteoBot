# io_ingest.py
"""
Ingestione dati per MeteoBot – La Spezia / Levante Ligure.

Sorgenti implementate (senza dipendenze opzionali):
  1. Open-Meteo (API libera, CORS-free, no chiave)
     - Previsioni orarie (GFS, ECMWF, IFS, Copernicus)
     - Dati storici (archive API)
     - Profili verticali di pressione/temperatura per CAPE approssimato
  2. Stub pronti per GRIB/NetCDF (pygrib/cfgrib/xarray) – NotImplementedError con hint
  3. Stub sounding da UWYO (University of Wyoming)
  4. Stub radar (pyart/wradlib)

Uso principale:
    from io_ingest import fetch_openmeteo_current, build_obs_from_openmeteo
"""

import datetime
import requests
from typing import Dict, Any, Optional, List

from config import LATITUDE, LONGITUDE, ELEVATION, OPEN_METEO_BASE, TIMEZONE

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Open-Meteo – API integrazione reale
# Documentazione: https://open-meteo.com/en/docs
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

# Variabili orarie richieste a Open-Meteo
_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dewpoint_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "precipitation_probability",
    "weather_code",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_high",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cape",
    "lifted_index",
    "convective_inhibition",
    "freezing_level_height",
    "snowfall_height",
    "visibility",
    # Livelli di pressione (per profilo verticale approssimato)
    "temperature_1000hPa", "temperature_925hPa", "temperature_850hPa",
    "temperature_700hPa",  "temperature_500hPa",
    "dewpoint_1000hPa",    "dewpoint_925hPa",    "dewpoint_850hPa",
    "dewpoint_700hPa",     "dewpoint_500hPa",
    "windspeed_10m",       # alias per compatibilità
    "geopotential_height_500hPa", "geopotential_height_850hPa",
]

_CURRENT_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "weather_code",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "cape",
]

# Modelli meteorologici disponibili su Open-Meteo (selezionato automaticamente)
_MODELS = "best_match"  # Open-Meteo seleziona il migliore disponibile


def fetch_openmeteo_current(
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    timeout: int = 20,
) -> Dict[str, Any]:
    """
    Recupera i dati attuali e le previsioni orarie da Open-Meteo.
    Ritorna il payload JSON completo dell'API.
    """
    # Variabili orarie – alcune potrebbero non essere supportate dal modello;
    # quelle non disponibili semplicemente non compariranno nella risposta
    hourly_request = [
        "temperature_2m", "relative_humidity_2m", "dewpoint_2m",
        "apparent_temperature", "precipitation", "rain", "snowfall",
        "weather_code", "surface_pressure", "cloud_cover",
        "cloud_cover_low", "cloud_cover_high",
        "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
        "cape", "lifted_index", "convective_inhibition",
        "freezing_level_height", "visibility",
        "temperature_850hPa", "temperature_700hPa", "temperature_500hPa",
        "dewpoint_850hPa", "dewpoint_700hPa", "dewpoint_500hPa",
    ]
    params = {
        "latitude":  lat,
        "longitude": lon,
        "hourly":    ",".join(hourly_request),
        "current":   ",".join(_CURRENT_VARS),
        "timezone":  TIMEZONE,
        "forecast_days": 2,
        "models":    _MODELS,
    }
    resp = requests.get(OPEN_METEO_BASE, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _get_current_hour_index(data: Dict[str, Any]) -> int:
    """Trova l'indice orario corrispondente all'ora corrente nei dati orari."""
    from zoneinfo import ZoneInfo
    now = datetime.datetime.now(ZoneInfo(TIMEZONE))
    times = data.get("hourly", {}).get("time", [])
    target = now.strftime("%Y-%m-%dT%H:00")
    for i, t in enumerate(times):
        if t == target:
            return i
    # fallback: primo indice disponibile
    return 0


def build_obs_from_openmeteo(
    data: Dict[str, Any],
    hour_offset: int = 0,
) -> Dict[str, Any]:
    """
    Costruisce il dizionario `obs` compatibile con engine.run_pipeline()
    a partire dai dati Open-Meteo.
    hour_offset: ore in avanti rispetto all'ora corrente (0 = adesso).
    """
    h = data.get("hourly", {})
    curr = data.get("current", {})
    idx = _get_current_hour_index(data) + hour_offset
    idx = max(0, min(idx, len(h.get("time", [1])) - 1))

    def get(key: str, default=None):
        vals = h.get(key)
        if vals and idx < len(vals):
            v = vals[idx]
            return v if v is not None else default
        return default

    temp_c = get("temperature_2m")
    rh     = get("relative_humidity_2m")
    Td_c   = get("dewpoint_2m")
    wind_kmh = get("wind_speed_10m", 0)
    gust_kmh = get("wind_gusts_10m", 0)
    wind_dir = get("wind_direction_10m", 225)
    precip   = get("precipitation", 0)
    cape_jkg = get("cape", curr.get("cape", 0)) or 0
    li       = get("lifted_index")
    cin      = get("convective_inhibition", 0) or 0
    cloud    = get("cloud_cover", curr.get("cloud_cover", 0)) or 0
    cloud_low  = get("cloud_cover_low", 0) or 0
    cloud_high = get("cloud_cover_high", 0) or 0
    p_hpa    = get("surface_pressure", curr.get("surface_pressure", 1013)) or 1013
    wmo_code = get("weather_code", curr.get("weather_code", 0)) or 0
    app_temp = get("apparent_temperature", temp_c)
    vis_m    = get("visibility", 10000) or 10000
    snow_lvl = get("snowfall_height", 2000) or 2000
    freeze   = get("freezing_level_height", 2500) or 2500

    # Profilo verticale approssimato (da livelli isobarici Open-Meteo)
    # Quota approssimata: 1000hPa≈100m, 925hPa≈760m, 850hPa≈1460m,
    #                     700hPa≈3010m, 500hPa≈5570m
    LEVEL_MAP = {
        "1000hPa": (100000.0,  100.0),
        "925hPa":  ( 92500.0,  760.0),
        "850hPa":  ( 85000.0, 1460.0),
        "700hPa":  ( 70000.0, 3010.0),
        "500hPa":  ( 50000.0, 5570.0),
    }
    sounding_p, sounding_T, sounding_Td, sounding_h = [], [], [], []
    for sfx, (pa, zm) in LEVEL_MAP.items():
        T_k  = get(f"temperature_{sfx}")
        Td_k = get(f"dewpoint_{sfx}")
        if T_k is not None:
            sounding_p.append(pa)
            sounding_T.append(T_k + 273.15)
            sounding_Td.append((Td_k + 273.15) if Td_k is not None else T_k + 273.15 - 5)
            sounding_h.append(zm)

    # Aggiungi livello superficiale se non presente
    if temp_c is not None and sounding_p and sounding_p[0] < 100000:
        sounding_p.insert(0, p_hpa * 100)
        sounding_T.insert(0, temp_c + 273.15)
        sounding_Td.insert(0, (Td_c + 273.15) if Td_c is not None else temp_c + 271.15)
        sounding_h.insert(0, float(ELEVATION))

    now_str = datetime.datetime.now().isoformat() + "Z"

    obs: Dict[str, Any] = {
        "time_generated":  now_str,
        "location":        f"La Spezia ({LATITUDE}N, {LONGITUDE}E)",
        "source":          "open-meteo",
        "wmo_code":        wmo_code,
        # Cielo
        "cloud_cover_pct":  cloud,
        "cloud_low_pct":    cloud_low,
        "cloud_high_pct":   cloud_high,
        # Precipitazioni
        "precip_rate_mm_h": precip,
        "rain_1h_mm":       precip,
        # Vento
        "wind_gust_kmh":    gust_kmh,
        "wind_speed_kmh":   wind_kmh,
        "wind_dir_deg":     wind_dir,
        "wind_speed_ms":    wind_kmh / 3.6,
        # Termica
        "temp_c":           temp_c,
        "humidity_pct":     rh,
        "pressure_hpa":     p_hpa,
        "heat_index":       app_temp,
        "temp_dewpoint_spread": (temp_c - Td_c) if (temp_c and Td_c) else None,
        # Instabilità (pre-calcolati da Open-Meteo)
        "CAPE":  cape_jkg,
        "SBCAPE": cape_jkg,
        "MUCAPE": cape_jkg,
        "MLCAPE": cape_jkg,
        "LI":    li,
        "CIN":   cin,
        "SBCIN": cin,
        # Quota neve e gelo
        "snow_level_m":   snow_lvl,
        "freeze_level_m": freeze,
        # Visibilità
        "visibility_m": vis_m,
        # Ora UTC per brezza marina
        "hour_utc": datetime.datetime.utcnow().hour,
    }

    # Aggiungi profilo verticale se disponibile
    if len(sounding_p) >= 3:
        obs["sounding"] = {
            "pressure_pa":   sounding_p,
            "temperature_k": sounding_T,
            "dewpoint_k":    sounding_Td,
            "height_m":      sounding_h,
            "u_ms":          [],   # non disponibili da Open-Meteo
            "v_ms":          [],
        }

    return obs


def build_hourly_forecast_from_openmeteo(
    data: Dict[str, Any],
    n_hours: int = 24,
) -> List[Dict[str, Any]]:
    """
    Costruisce la lista hourly_forecast per engine.run_pipeline()
    con i prossimi n_hours dalle previsioni Open-Meteo.
    """
    h = data.get("hourly", {})
    idx0 = _get_current_hour_index(data)
    times   = h.get("time",                [])
    temps   = h.get("temperature_2m",      [])
    rhs     = h.get("relative_humidity_2m",[])
    winds   = h.get("wind_speed_10m",      [])
    dirs    = h.get("wind_direction_10m",  [])
    precips = h.get("precipitation",       [])
    capes   = h.get("cape",                [])
    cins    = h.get("convective_inhibition",[])
    wmos    = h.get("weather_code",        [])
    vis_l   = h.get("visibility",          [])

    # Accumulo cumulativo precipitazioni
    cum = 0.0
    result = []
    for i in range(idx0, min(idx0 + n_hours, len(times))):
        p   = precips[i] if i < len(precips) else 0
        cum += (p or 0)

        # Livello allerta precipitazione oraria
        from config import thresholds as thr
        p_val = p or 0
        if p_val >= thr.ARPAL_RAIN_1H_ROSSO:
            alert = "🔴"
        elif p_val >= thr.ARPAL_RAIN_1H_ARANCIONE:
            alert = "🟠"
        elif p_val >= thr.ARPAL_RAIN_1H_GIALLO:
            alert = "🟡"
        else:
            alert = "🟢"

        result.append({
            "time":       times[i][-5:] if i < len(times) else "??:??",
            "T":          temps[i]  if i < len(temps)  else None,
            "RH":         rhs[i]    if i < len(rhs)    else None,
            "wind":       winds[i]  if i < len(winds)  else None,
            "wind_dir":   dirs[i]   if i < len(dirs)   else None,
            "precip":     p or 0,
            "precip_cum": round(cum, 1),
            "CAPE":       capes[i]  if i < len(capes)  else 0,
            "CIN":        cins[i]   if i < len(cins)   else 0,
            "shear":      0,        # non disponibile direttamente da Open-Meteo
            "SRH":        0,
            "PWAT":       0,
            "wmo_code":   wmos[i]   if i < len(wmos)   else None,
            "alert":      alert,
        })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Fetch multi-modello 3 giorni (AROME + ICON-EU)
# ─────────────────────────────────────────────────────────────────────────────

_SURF_VARS_MULTIDAY = [
    "temperature_2m", "relative_humidity_2m", "dewpoint_2m",
    "apparent_temperature", "precipitation", "weather_code",
    "cloud_cover", "cloud_cover_low", "cloud_cover_high",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "surface_pressure", "cape", "lifted_index", "convective_inhibition",
    "freezing_level_height", "snowfall_height", "visibility",
]

_PLEVEL_VARS_MULTIDAY = [
    "temperature_850hPa", "temperature_700hPa", "temperature_500hPa",
    "dewpoint_850hPa",    "dewpoint_700hPa",    "dewpoint_500hPa",
    "geopotential_height_500hPa", "geopotential_height_850hPa",
    "wind_speed_850hPa",  "wind_speed_700hPa",  "wind_speed_500hPa",
    "wind_direction_850hPa", "wind_direction_700hPa", "wind_direction_500hPa",
]


def _fetch_one_model(
    model: str,
    start_date: str,
    end_date: str,
    lat: float,
    lon: float,
    timeout: int = 35,
) -> Optional[Dict[str, Any]]:
    """Fetch da un singolo modello Open-Meteo. Ritorna None in caso di errore."""
    all_vars = _SURF_VARS_MULTIDAY + _PLEVEL_VARS_MULTIDAY
    params: Dict[str, Any] = {
        "latitude":   lat,
        "longitude":  lon,
        "hourly":     ",".join(all_vars),
        "models":     model,
        "start_date": start_date,
        "end_date":   end_date,
        "timezone":   TIMEZONE,
    }
    try:
        resp = requests.get(OPEN_METEO_BASE, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        n = len(data.get("hourly", {}).get("time", []))
        if n < 12:
            return None
        return data
    except Exception as e:
        print(f"  [io] {model}: errore fetch: {e}")
        return None


def _merge_hourly(
    primary: Optional[Dict[str, Any]],
    secondary: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Unisce due dataset orari: usa il valore di `primary` quando non è None,
    altrimenti quello di `secondary`. Allineamento per timestamp.
    """
    if primary is None:
        return secondary

    p_h = primary.get("hourly", {})
    s_h = secondary.get("hourly", {})
    p_times = p_h.get("time", [])
    s_times = s_h.get("time", [])
    s_idx   = {t: i for i, t in enumerate(s_times)}

    all_keys = set(list(p_h.keys()) + list(s_h.keys())) - {"time"}
    merged_h: Dict[str, Any] = {"time": p_times}

    for key in all_keys:
        p_vals = p_h.get(key, [])
        s_vals = s_h.get(key, [])
        row = []
        for j, t in enumerate(p_times):
            pv = p_vals[j] if j < len(p_vals) else None
            sv = (s_vals[s_idx[t]] if t in s_idx and s_idx[t] < len(s_vals) else None)
            row.append(pv if pv is not None else sv)
        merged_h[key] = row

    result = dict(secondary)
    result["hourly"] = merged_h
    return result


def extract_day_hourly(
    raw_data: Dict[str, Any],
    day_offset: int = 0,
    tz: str = TIMEZONE,
) -> Dict[str, Any]:
    """
    Estrae i dati orari per un giorno specifico (0=oggi, 1=domani, 2=dopodomani).
    """
    from zoneinfo import ZoneInfo as _ZI
    import datetime as _dt
    today  = _dt.datetime.now(_ZI(tz)).date()
    target = today + _dt.timedelta(days=day_offset)
    target_str = target.strftime("%Y-%m-%d")

    h      = raw_data.get("hourly", {})
    times  = h.get("time", [])
    idxs   = [i for i, t in enumerate(times) if str(t).startswith(target_str)]
    if not idxs:
        return {}

    return {key: [vals[i] for i in idxs if i < len(vals)]
            for key, vals in h.items() if isinstance(vals, list)}


def build_day_obs(
    day_hourly: Dict[str, Any],
    model_name: str = "icon_eu",
) -> Dict[str, Any]:
    """
    Costruisce il dizionario obs per engine.run_pipeline() dal profilo orario di un giorno.
    Usa il picco 12-18 UTC come condizioni rappresentative.
    """
    if not day_hourly:
        return {}

    times = day_hourly.get("time", [])

    def _agg(key: str, mode: str = "mean") -> Optional[float]:
        vals = day_hourly.get(key, [])
        peak = [
            vals[i] for i, t in enumerate(times)
            if i < len(vals) and vals[i] is not None
            and any(str(t).endswith(f"{h:02d}:00") for h in range(11, 18))
        ]
        src = peak or [v for v in vals if v is not None]
        if not src:
            return None
        if mode == "max":   return max(src)
        if mode == "min":   return min(src)
        if mode == "sum":   return sum(src)
        if mode == "dom":   return max(set([int(v) for v in src]), key=[int(v) for v in src].count)
        return sum(src) / len(src)

    temp_max    = _agg("temperature_2m", "max")
    temp_min    = _agg("temperature_2m", "min")
    rh          = _agg("relative_humidity_2m")
    app_temp    = _agg("apparent_temperature", "max")
    gust        = _agg("wind_gusts_10m",  "max")
    wind_spd    = _agg("wind_speed_10m",  "max")
    wind_dir    = _agg("wind_direction_10m")
    precip_sum  = _agg("precipitation", "sum") or 0.0
    precip_max  = _agg("precipitation", "max") or 0.0
    cape        = _agg("cape", "max") or 0.0
    li          = _agg("lifted_index",  "min")
    cin         = _agg("convective_inhibition", "min")
    cloud       = _agg("cloud_cover")
    cloud_low   = _agg("cloud_cover_low")
    cloud_high  = _agg("cloud_cover_high")
    p_hpa       = _agg("surface_pressure")
    snow_lvl    = _agg("snowfall_height",  "min") or 2000.0
    vis_m       = _agg("visibility",       "min") or 10000.0
    wmo_vals    = [int(v) for v in (day_hourly.get("weather_code") or []) if v is not None]
    wmo_dom     = max(set(wmo_vals), key=wmo_vals.count) if wmo_vals else 0

    import math as _math

    # Profilo verticale da livelli isobarici (con vento per shear/SRH)
    LVLS = {"850hPa": (85000.0, 1460.0),
             "700hPa": (70000.0, 3010.0),
             "500hPa": (50000.0, 5570.0)}
    s_p, s_T, s_Td, s_h, s_u, s_v = [], [], [], [], [], []
    for sfx, (pa, zm) in LVLS.items():
        T  = _agg(f"temperature_{sfx}")
        Td = _agg(f"dewpoint_{sfx}")
        ws = _agg(f"wind_speed_{sfx}")      # km/h da Open-Meteo
        wd = _agg(f"wind_direction_{sfx}")  # gradi meteorologici
        if T is not None:
            s_p.append(pa); s_T.append(T + 273.15)
            s_Td.append((Td + 273.15) if Td is not None else T + 271.15)
            s_h.append(zm)
            if ws is not None and wd is not None:
                rad = _math.radians(wd)
                ws_ms = ws / 3.6
                s_u.append(-ws_ms * _math.sin(rad))
                s_v.append(-ws_ms * _math.cos(rad))
            else:
                s_u.append(0.0)
                s_v.append(0.0)

    t_rep = temp_max
    if t_rep is not None:
        p_pa = (p_hpa * 100) if p_hpa else 101300.0
        s_p.insert(0, p_pa); s_T.insert(0, t_rep + 273.15)
        s_Td.insert(0, t_rep + 268.15); s_h.insert(0, float(ELEVATION))
        # Vento superficiale (10 m) → componenti u/v
        if wind_spd is not None and wind_dir is not None:
            rad = _math.radians(wind_dir)
            ws_ms = wind_spd / 3.6
            s_u.insert(0, -ws_ms * _math.sin(rad))
            s_v.insert(0, -ws_ms * _math.cos(rad))
        else:
            s_u.insert(0, 0.0)
            s_v.insert(0, 0.0)

    # Finestra temporale precipitazioni
    precip_vals = day_hourly.get("precipitation", [])
    rain_times  = [times[i] for i, v in enumerate(precip_vals)
                   if i < len(times) and v is not None and v > 0.1]
    if rain_times and precip_vals:
        peak_i    = max(range(len(precip_vals)),
                        key=lambda i: float(precip_vals[i] or 0))
        p_peak_mm = float(precip_vals[peak_i] or 0)
        p_peak_h  = str(times[peak_i])[-5:] if peak_i < len(times) else None
    else:
        p_peak_mm = precip_max
        p_peak_h  = None

    obs: Dict[str, Any] = {
        "time_generated": datetime.datetime.now().isoformat() + "Z",
        "location":    f"La Spezia ({LATITUDE}N, {LONGITUDE}E)",
        "source":      model_name,
        "wmo_code":    wmo_dom,
        "cloud_cover_pct": cloud,
        "cloud_low_pct":   cloud_low,
        "cloud_high_pct":  cloud_high,
        "precip_rate_mm_h": precip_max,
        "rain_1h_mm":       precip_max,
        "rain_24h_mm":      precip_sum,
        "precip_start":  str(rain_times[0])[-5:]  if rain_times else None,
        "precip_end":    str(rain_times[-1])[-5:] if rain_times else None,
        "precip_peak_mm": p_peak_mm,
        "precip_peak_h":  p_peak_h,
        "wind_gust_kmh":    gust,
        "wind_speed_kmh":   wind_spd,
        "wind_dir_deg":     wind_dir,
        "wind_speed_ms":    (wind_spd / 3.6) if wind_spd else 0,
        "temp_c":      t_rep,
        "temp_max_c":  temp_max,
        "temp_min_c":  temp_min,
        "humidity_pct": rh,
        "pressure_hpa": p_hpa,
        "heat_index":   app_temp,
        "apparent_temperature": app_temp,
        "CAPE": cape, "SBCAPE": cape, "MUCAPE": cape, "MLCAPE": cape,
        "LI": li, "CIN": cin, "SBCIN": cin,
        "snow_level_m": snow_lvl,
        "visibility_m": vis_m,
        "hour_utc": 14,
    }
    if len(s_p) >= 3:
        obs["sounding"] = {
            "pressure_pa": s_p, "temperature_k": s_T,
            "dewpoint_k": s_Td, "height_m": s_h,
            "u_ms": s_u, "v_ms": s_v,
        }
    return obs


def build_day_hourly_list(day_hourly: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Costruisce la lista hourly_forecast per engine.run_pipeline() da un giorno."""
    times   = day_hourly.get("time", [])
    temps   = day_hourly.get("temperature_2m", [])
    rhs     = day_hourly.get("relative_humidity_2m", [])
    winds   = day_hourly.get("wind_speed_10m", [])
    dirs    = day_hourly.get("wind_direction_10m", [])
    gusts   = day_hourly.get("wind_gusts_10m", [])
    clouds  = day_hourly.get("cloud_cover", [])
    precips = day_hourly.get("precipitation", [])
    capes   = day_hourly.get("cape", [])
    cins    = day_hourly.get("convective_inhibition", [])
    wmos    = day_hourly.get("weather_code", [])

    from config import thresholds as thr
    cum = 0.0
    result = []
    for i, t in enumerate(times):
        p = float(precips[i] or 0) if i < len(precips) else 0.0
        cum += p
        alert = ("🔴" if p >= thr.ARPAL_RAIN_1H_ROSSO
                 else "🟠" if p >= thr.ARPAL_RAIN_1H_ARANCIONE
                 else "🟡" if p >= thr.ARPAL_RAIN_1H_GIALLO else "🟢")
        result.append({
            "time":       str(t)[-5:] if t else "??:??",
            "T":          temps[i]  if i < len(temps)  else None,
            "RH":         rhs[i]    if i < len(rhs)    else None,
            "wind":       float(winds[i]) if i < len(winds) and winds[i] is not None else None,
            "wind_dir":   dirs[i]   if i < len(dirs)   else None,
            "wind_gust":  float(gusts[i]) if i < len(gusts) and gusts[i] is not None else 0.0,
            "cloud":      clouds[i] if i < len(clouds) and clouds[i] is not None else None,
            "precip":     p,
            "precip_cum": round(cum, 1),
            "CAPE":       capes[i]  if i < len(capes) else 0,
            "CIN":        cins[i]   if i < len(cins)  else 0,
            "shear": 0, "SRH": 0, "PWAT": 0,
            "wmo_code":   wmos[i]   if i < len(wmos)  else None,
            "alert":      alert,
        })
    return result


def fetch_forecast_3days(
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    timeout: int = 35,
) -> Dict[str, Any]:
    """
    Scarica previsioni 3 giorni da AROME + ICON-EU e le unisce.
    Ritorna:
      'day0', 'day1': hourly mergiati AROME+ICON-EU
      'day2':         hourly solo ICON-EU
      'model_primary', 'model_fallback'
    """
    import datetime as _dt
    today   = _dt.date.today()
    start_s = today.strftime("%Y-%m-%d")
    end_d2  = (today + _dt.timedelta(days=3)).strftime("%Y-%m-%d")
    end_d1  = (today + _dt.timedelta(days=2)).strftime("%Y-%m-%d")

    print("  [io] Scarico ICON-EU (3 giorni)...")
    icon_data = _fetch_one_model("icon_eu", start_s, end_d2, lat, lon, timeout)
    if icon_data is None:
        raise RuntimeError("ICON-EU non disponibile")
    print(f"  [io] ICON-EU: {len(icon_data['hourly']['time'])} ore")

    arome_data = None
    for model in ["meteofrance_arome_france", "meteofrance_arome_france_hd"]:
        print(f"  [io] Provo {model}...")
        d = _fetch_one_model(model, start_s, end_d1, lat, lon, timeout)
        if d is not None:
            arome_data = d
            print(f"  [io] {model}: {len(d['hourly']['time'])} ore")
            break
    if arome_data is None:
        print("  [io] AROME non disponibile, solo ICON-EU")

    merged = _merge_hourly(arome_data, icon_data)
    return {
        "day0": extract_day_hourly(merged,     0),
        "day1": extract_day_hourly(merged,     1),
        "day2": extract_day_hourly(icon_data,  2),
        "model_primary":  "AROME+ICON-EU" if arome_data else "ICON-EU",
        "model_fallback": "ICON-EU",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stub GRIB / NetCDF / Sounding / Radar (pronti per implementazione)
# ─────────────────────────────────────────────────────────────────────────────

def read_model_grib(path: str) -> Dict[str, Any]:
    raise NotImplementedError("pip install cfgrib eccodes")

def read_sounding_uwyo(station: str = "16080", date=None, hour: int = 12) -> Dict[str, Any]:
    raise NotImplementedError("Parser UWYO sounding da weather.uwyo.edu")

def read_radar(radar_source: str) -> Dict[str, Any]:
    raise NotImplementedError("pip install pyart wradlib")

def ingest_station_obs(station_list: list) -> Dict[str, Any]:
    raise NotImplementedError("Integrare stazioni ARPAL/OMIRL")

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def read_model_grib(path: str) -> Dict[str, Any]:
    """
    Leggi file GRIB/GRIB2 (ECMWF IFS, GFS, COSMO-ME, WRF, ...).
    Implementazione: pip install cfgrib eccodes
    Esempio:
        import cfgrib, xarray as xr
        ds = xr.open_dataset(path, engine='cfgrib')
        return {...}
    """
    raise NotImplementedError(
        "Integrare lettore GRIB2: pip install cfgrib eccodes\n"
        "Variabili utili: u10, v10, t2m, d2m, sp, cape, cin, tp"
    )


def read_sounding_uwyo(
    station: str = "16080",   # Roma Ciampino – stazione radiosondaggio più vicina
    date: Optional[datetime.date] = None,
    hour: int = 12,
) -> Dict[str, Any]:
    """
    Scarica radiosondaggio da University of Wyoming.
    station: codice SYNOP (16080=Roma, 16114=Milano, 16144=La Spezia proxy)
    Implementazione: richiede parsing HTML di weather.uwyo.edu
    """
    raise NotImplementedError(
        "Integrare parser UWYO: requests + BeautifulSoup\n"
        "URL: https://weather.uwyo.edu/cgi-bin/sounding.py"
        "?TYPE=TEXT%3ALIST&YEAR=...&MONTH=...&FROM=...&TO=...&STNM=..."
    )


def read_radar(radar_source: str) -> Dict[str, Any]:
    """
    Leggi prodotti radar (CINRAD, DWD, MeteoAM, RainViewer).
    Implementazione: pip install pyart wradlib
    """
    raise NotImplementedError(
        "Integrare radar: pip install pyart wradlib\n"
        "Oppure usare RainViewer API per overlay immagine."
    )


def ingest_station_obs(station_list: list) -> Dict[str, Any]:
    """
    Leggi osservazioni stazioni al suolo (ARPAL, OMIRL, Ecowitt, ecc.).
    """
    raise NotImplementedError(
        "Integrare stazioni ARPAL/OMIRL tramite scraping o API dedicata."
    )
