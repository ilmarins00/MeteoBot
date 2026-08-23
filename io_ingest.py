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
import time
from typing import Dict, Any, Optional, List, Tuple

from config import (
    LATITUDE, LONGITUDE, ELEVATION, OPEN_METEO_BASE, TIMEZONE, thresholds,
    AROME_PI_FORECAST_QUARTERS,
)
from indices import compute_shear_profile, compute_srh

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
                if Td_k is not None:
                    sounding_Td.append(Td_k + 273.15)
                    sounding_h.append(zm)

    if len(sounding_Td) < len(sounding_p):
                # Ricostruisci solo i livelli con entrambi T e Td
                aligned_p, aligned_T, aligned_Td, aligned_h = [], [], [], []
                # Ripeti il ciclo ma salta livelli senza Td
                for sfx, (pa, zm) in LEVEL_MAP.items():
                    T_k = get(f"temperature_{sfx}")
                    Td_k = get(f"dewpoint_{sfx}")
                    if T_k is not None and Td_k is not None:
                        aligned_p.append(pa)
                        aligned_T.append(T_k + 273.15)
                        aligned_Td.append(Td_k + 273.15)
                        aligned_h.append(zm)
                sounding_p, sounding_T, sounding_Td, sounding_h = aligned_p, aligned_T, aligned_Td, aligned_h

    # Aggiungi livello superficiale se non presente
    if temp_c is not None and Td_c is not None and sounding_p and sounding_p[0] < 100000:
            sounding_p.insert(0, p_hpa * 100)
            sounding_T.insert(0, temp_c + 273.15)
            sounding_Td.insert(0, Td_c + 273.15)
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
                "pressure_pa": sounding_p,
                "temperature_k": sounding_T,
                "dewpoint_k": sounding_Td,
                "height_m": sounding_h,
                "u_ms": [],  # non disponibili da Open-Meteo (nessun vento sui livelli isobarici)
                "v_ms": [],
            }
            obs["sounding_low_res"] = True

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
    "soil_moisture_0_to_10cm", "cloud_cover_mid",
]

_PLEVEL_VARS_MULTIDAY = [
    # Temperatura (8 livelli: 1000→300 hPa)
    "temperature_1000hPa", "temperature_925hPa",
    "temperature_850hPa",  "temperature_700hPa",
    "temperature_600hPa",  "temperature_500hPa",
    "temperature_400hPa",  "temperature_300hPa",
    # Dewpoint (livelli disponibili su Open-Meteo)
    "dew_point_1000hPa", "dew_point_925hPa",
    "dew_point_850hPa",  "dew_point_700hPa",
    "dew_point_500hPa",  "dew_point_300hPa",
    # Geopotenziale
    "geopotential_height_1000hPa", "geopotential_height_925hPa",
    "geopotential_height_850hPa",  "geopotential_height_700hPa",
    "geopotential_height_500hPa",  "geopotential_height_300hPa",
    # Vento velocità (8 livelli)
    "wind_speed_1000hPa", "wind_speed_925hPa",
    "wind_speed_850hPa",  "wind_speed_700hPa",
    "wind_speed_600hPa",  "wind_speed_500hPa",
    "wind_speed_400hPa",  "wind_speed_300hPa",
    # Vento direzione (8 livelli)
    "wind_direction_1000hPa", "wind_direction_925hPa",
    "wind_direction_850hPa",  "wind_direction_700hPa",
    "wind_direction_600hPa",  "wind_direction_500hPa",
    "wind_direction_400hPa",  "wind_direction_300hPa",
]


def _fetch_one_model(
    model: str,
    start_date: str,
    end_date: str,
    lat: float,
    lon: float,
    timeout: int = 35,
) -> Optional[Dict[str, Any]]:
    """
    Fetch da un singolo modello Open-Meteo. Ritorna None in caso di errore.
    Un timeout/errore di rete è spesso transitorio (Open-Meteo sotto carico):
    un solo nuovo tentativo, dopo una breve pausa, evita di perdere un'intera
    zona per un singolo timeout isolato.
    """
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
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            resp = requests.get(OPEN_METEO_BASE, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            n = len(data.get("hourly", {}).get("time", []))
            if n < 12:
                return None
            return data
        except Exception as e:
            last_error = e
            if attempt == 0:
                time.sleep(3)
    print(f"  [io] {model}: errore fetch: {last_error}")
    return None


_AROME_PRIORITY_FIELDS = {
    "cape", "convective_inhibition", "lifted_index",
    "precipitation", "rain", "showers",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "temperature_2m", "dew_point_2m", "dewpoint_2m", "relative_humidity_2m",
}


def _merge_hourly(
    primary: Optional[Dict[str, Any]],
    secondary: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """
    Unisce due dataset orari: usa il valore di `primary` (AROME) quando non e' None,
    altrimenti quello di `secondary` (ICON-EU). Allineamento per timestamp.

    Per i campi in _AROME_PRIORITY_FIELDS, se AROME ha un valore (anche 0 o basso)
    NON viene mai sostituito da ICON-EU, perche' AROME e' il modello di riferimento
    per fenomeni convettivi/locali nelle prime 48-72h. ICON-EU riempie solo i buchi
    reali (valore None) di questi campi, e tutti i buchi degli altri campi.

    Ritorna anche un dict {variabile: n_ore_colmate_da_secondary}.
    """
    fallback_stats: Dict[str, int] = {}
    if primary is None:
        return secondary, fallback_stats

    p_h = primary.get("hourly", {})
    s_h = secondary.get("hourly", {})
    p_times = p_h.get("time", [])
    s_times = s_h.get("time", [])
    s_idx = {t: i for i, t in enumerate(s_times)}

    all_keys = set(list(p_h.keys()) + list(s_h.keys())) - {"time"}
    merged_h: Dict[str, Any] = {"time": p_times}

    for key in all_keys:
        p_vals = p_h.get(key, [])
        s_vals = s_h.get(key, [])
        row = []
        filled = 0
        for j, t in enumerate(p_times):
            pv = p_vals[j] if j < len(p_vals) else None
            sv = s_vals[s_idx[t]] if (t in s_idx and s_idx[t] < len(s_vals)) else None
            if pv is None and sv is not None:
                filled += 1
            row.append(pv if pv is not None else sv)
        merged_h[key] = row
        if filled > 0:
            fallback_stats[key] = filled

    result = dict(secondary)
    result["hourly"] = merged_h
    return result, fallback_stats

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
    temps = day_hourly.get("temperature_2m", [])

    def _agg(key: str, mode: str = "mean", restrict_afternoon: bool = True) -> Optional[float]:
        vals = day_hourly.get(key, [])
        all_valid = [v for v in vals if v is not None]
        if not all_valid:
            return None

        if mode == "min":
            # Per la minima NON si deve restringere alle ore 11-18 (pomeriggio):
            # la minima di solito cade di notte/mattina presto. Usa tutte le
            # ore disponibili del giorno.
            return min(all_valid)

        if mode == "max":
            if not restrict_afternoon:
                # CAPE, raffiche, pioggia: il picco può cadere a qualunque ora
                # (convezione notturna, scirocco nelle ore piccole, ecc.). Niente
                # finestra: vero massimo giornaliero, altrimenti il dato di testa
                # può risultare più basso di un picco già visibile nella tabella
                # oraria sotto — l'incongruenza che hai notato.
                return max(all_valid)
            # Per la massima, preferisci la finestra 11-18 se disponibile
            # (rappresentativa del picco diurno per la temperatura), altrimenti
            # usa tutte le ore.
            peak = [
                vals[i] for i, t in enumerate(times)
                if i < len(vals) and vals[i] is not None
                and any(str(t).endswith(f"{h:02d}:00") for h in range(11, 18))
            ]
            src = peak or all_valid
            return max(src)

        if mode == "sum":
            return sum(all_valid)
        if mode == "dom":
            return max(set([int(v) for v in all_valid]), key=[int(v) for v in all_valid].count)

        # mode == "mean" (default): usa la finestra pomeridiana se disponibile,
        # altrimenti la media su tutte le ore
        peak = [
            vals[i] for i, t in enumerate(times)
            if i < len(vals) and vals[i] is not None
            and any(str(t).endswith(f"{h:02d}:00") for h in range(11, 18))
        ]
        src = peak or all_valid
        return sum(src) / len(src)

    temp_max    = _agg("temperature_2m", "max")
    temp_min    = _agg("temperature_2m", "min")
    rh          = _agg("relative_humidity_2m")
    app_temp    = _agg("apparent_temperature", "max")
    gust        = _agg("wind_gusts_10m",  "max", restrict_afternoon=False)
    wind_spd    = _agg("wind_speed_10m",  "max", restrict_afternoon=False)
    wind_dir    = _agg("wind_direction_10m")
    precip_sum  = _agg("precipitation", "sum") or 0.0
    precip_max  = _agg("precipitation", "max", restrict_afternoon=False) or 0.0
    cape        = _agg("cape", "max", restrict_afternoon=False) or 0.0
    cape_vals_raw = day_hourly.get("cape", [])
    li_vals_raw   = day_hourly.get("lifted_index", [])
    cin_vals_raw  = day_hourly.get("convective_inhibition", [])
    cape_peak_idx = None
    if cape_vals_raw:
        valid_idx = [i for i, v in enumerate(cape_vals_raw) if v is not None]
        if valid_idx:
            cape_peak_idx = max(valid_idx, key=lambda i: cape_vals_raw[i])

    li = None
    if cape_peak_idx is not None and cape_peak_idx < len(li_vals_raw):
        li = li_vals_raw[cape_peak_idx]

    cin = None
    if cape_peak_idx is not None and cape_peak_idx < len(cin_vals_raw):
        cin = cin_vals_raw[cape_peak_idx]
    if cin is None:
        cin = _agg("convective_inhibition", "min")

    # Controllo di plausibilità: SOLO log in console, non tocca il dato
    # mostrato nel bollettino. LI più negativo di -12 è già un valore estremo
    # (giornate da outbreak severo); se compare con CAPE modesto è quasi
    # certamente rumore del modello su quell'ora specifica, non un bug di
    # questo codice — ma vale la pena saperlo per giudicare l'affidabilità
    # del dato Open-Meteo in quel momento.
    if li is not None and li <= -12.0 and cape < thresholds.SBCAPE_STRONG:
        print(f"  ⚠ [plausibilità] LI={li:.1f} con CAPE={cape:.0f} J/kg è una combinazione "
              f"fisicamente sospetta (LI molto estremo, energia modesta) — dato grezzo del "
              f"modello all'indice orario {cape_peak_idx}, non modificato da questo codice.")

    cloud       = _agg("cloud_cover")
    cloud_low   = _agg("cloud_cover_low")
    cloud_high  = _agg("cloud_cover_high")
    cloud_mid = _agg("cloud_cover_mid")
    p_hpa       = _agg("surface_pressure")
    snow_lvl    = _agg("snowfall_height",  "min") or 2000.0
    vis_m       = _agg("visibility",       "min") or 10000.0
    wmo_vals    = [int(v) for v in (day_hourly.get("weather_code") or []) if v is not None]
    wmo_dom     = max(wmo_vals) if wmo_vals else 0

    import math as _math

    # Soil moisture (per Flash Flood Guidance)
    soil_moist = _agg("soil_moisture_0_to_10cm")  # m³/m³

    # Profilo verticale da 8 livelli isobarici (shear 0-1km, DCAPE, EHI accurati)
    LVLS = {
        "1000hPa": (100000.0,  100.0),
        "925hPa":  ( 92500.0,  760.0),
        "850hPa":  ( 85000.0, 1460.0),
        "700hPa":  ( 70000.0, 3010.0),
        "600hPa":  ( 60000.0, 4500.0),
        "500hPa":  ( 50000.0, 5570.0),
        "400hPa":  ( 40000.0, 7180.0),
        "300hPa":  ( 30000.0, 9180.0),
    }
    # Open-Meteo usa 'dew_point_' come prefisso per i livelli isobarici
    _DEW_POINT_LEVELS = {"1000hPa", "925hPa", "850hPa", "700hPa", "500hPa", "300hPa"}

    s_p, s_T, s_Td, s_h, s_u, s_v = [], [], [], [], [], []
    for sfx, (pa, zm) in LVLS.items():
        T  = _agg(f"temperature_{sfx}")
        if T is None:
            continue  # livello non coperto dall'orizzonte del modello per questo giorno
        # Open-Meteo: 'dew_point_' per livelli isobarici, 'dewpoint_' non sempre disponibile
        Td = (_agg(f"dew_point_{sfx}") if sfx in _DEW_POINT_LEVELS
              else _agg(f"dewpoint_{sfx}"))
        ws = _agg(f"wind_speed_{sfx}")      # km/h da Open-Meteo
        wd = _agg(f"wind_direction_{sfx}")  # gradi meteorologici
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

    # Temperatura rappresentativa: il valore dell'ora corrente, non la massima
    # giornaliera. La massima resta disponibile separatamente in temp_max_c.
    t_rep = temp_max
    try:
        from zoneinfo import ZoneInfo
        now_rome = datetime.datetime.now(ZoneInfo("Europe/Rome"))
        today_prefix = now_rome.strftime("%Y-%m-%d")
        current_candidates = [
            (i, float(v)) for i, (t, v) in enumerate(zip(times, temps))
            if v is not None and str(t).startswith(today_prefix)
        ]
        if current_candidates:
            current_index, t_rep = min(
                current_candidates,
                key=lambda item: abs(item[0] - now_rome.hour),
            )
    except (ImportError, TypeError, ValueError):
        current_index = None
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
        "time_generated": datetime.datetime.now(
            __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("Europe/Rome")
        ).isoformat(),
        "location":    f"La Spezia ({LATITUDE}N, {LONGITUDE}E)",
        "source":      model_name,
        "wmo_code":    wmo_dom,
        "cloud_cover_pct": cloud,
        "cloud_low_pct":   cloud_low,
        "cloud_high_pct":  cloud_high,
        "cloud_mid_pct": cloud_mid,
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
        "soil_moisture": soil_moist,   # m³/m³ per FFG
        "hour_utc": 14,
    }
    if len(s_p) >= 3:
        # Calcola DCAPE dal profilo
        try:
            from thermo import dcape_from_profile as _dcape_fn
            obs["DCAPE"] = _dcape_fn(s_p, s_T, s_Td)
        except Exception:
            obs["DCAPE"] = None
        obs["sounding"] = {
            "pressure_pa": s_p, "temperature_k": s_T,
            "dewpoint_k": s_Td, "height_m": s_h,
            "u_ms": s_u, "v_ms": s_v,
        }
    return obs

# ─────────────────────────────────────────────────────────────────────────────
# Shear / SRH orari — necessari per la concordanza multi-parametro nell'evoluzione
# dell'instabilità (invece di un unico valore fisso per l'intera giornata).
# ─────────────────────────────────────────────────────────────────────────────

_LVLS_WIND_HOURLY = {
    "1000hPa": 100.0,
    "925hPa":  760.0,
    "850hPa":  1460.0,
    "700hPa":  3010.0,
    "600hPa":  4500.0,
    "500hPa":  5570.0,
    "400hPa":  7180.0,
    "300hPa":  9180.0,
}


def _hourly_shear_srh(
    day_hourly: Dict[str, Any],
    idx: int,
    surface_speed_kmh: Optional[float],
    surface_dir_deg: Optional[float],
) -> Dict[str, Optional[float]]:
    """
    Shear (0-1/0-3/0-6 km, kt) e SRH (0-1/0-3 km, m²/s²) per UNA singola ora,
    usando vento superficiale + vento sui livelli di pressione della stessa ora
    (già presenti in day_hourly grazie a _PLEVEL_VARS_MULTIDAY).

    Se per quell'ora sono disponibili meno di 3 livelli, ritorna None su tutto:
    un finto "0" verrebbe letto come "vento assente", mentre qui è solo un dato
    mancante — la differenza conta per la concordanza a valle.
    """
    import math as _math

    heights: List[float] = []
    u_list: List[float] = []
    v_list: List[float] = []

    if surface_speed_kmh is not None and surface_dir_deg is not None:
        ws_ms = float(surface_speed_kmh) / 3.6
        rad = _math.radians(float(surface_dir_deg))
        u_list.append(-ws_ms * _math.sin(rad))
        v_list.append(-ws_ms * _math.cos(rad))
        heights.append(float(ELEVATION))

    for sfx, zm in _LVLS_WIND_HOURLY.items():
        ws_vals = day_hourly.get(f"wind_speed_{sfx}", [])
        wd_vals = day_hourly.get(f"wind_direction_{sfx}", [])
        if (idx < len(ws_vals) and idx < len(wd_vals)
                and ws_vals[idx] is not None and wd_vals[idx] is not None):
            ws_ms = float(ws_vals[idx]) / 3.6
            rad = _math.radians(float(wd_vals[idx]))
            u_list.append(-ws_ms * _math.sin(rad))
            v_list.append(-ws_ms * _math.cos(rad))
            heights.append(zm)

    if len(heights) < 3:
        return {
            "shear_0_1": None, "shear_0_3": None, "shear_0_6": None,
            "srh_0_1": None, "srh_0_3": None,
        }

    shear = compute_shear_profile(u_list, v_list, heights)
    srh = compute_srh(u_list, v_list, heights)
    return {
        "shear_0_1": round(shear.get("shear_0_1", 0), 1),
        "shear_0_3": round(shear.get("shear_0_3", 0), 1),
        "shear_0_6": round(shear.get("shear_0_6", 0), 1),
        "srh_0_1":   round(srh.get("srh_0_1", 0), 1),
        "srh_0_3":   round(srh.get("srh_0_3", 0), 1),
    }

def _hourly_full_profile(day_hourly, idx, surf_t_c, surf_td_c, surf_p_hpa):
    LVLS = {
        "1000hPa": (100000.0,100.0), "925hPa": (92500.0,760.0),
        "850hPa": (85000.0,1460.0),  "700hPa": (70000.0,3010.0),
        "600hPa": (60000.0,4500.0),  "500hPa": (50000.0,5570.0),
        "400hPa": (40000.0,7180.0),  "300hPa": (30000.0,9180.0),
    }
    _DEW = {"1000hPa","925hPa","850hPa","700hPa","500hPa","300hPa"}
    p, T, Td, h = [], [], [], []
    if surf_t_c is not None and surf_td_c is not None:
        p.append((surf_p_hpa or 1013.0)*100); T.append(surf_t_c+273.15)
        Td.append(surf_td_c+273.15); h.append(float(ELEVATION))
    for sfx,(pa,zm) in LVLS.items():
        tv  = day_hourly.get(f"temperature_{sfx}", [])
        tdv = day_hourly.get(f"dew_point_{sfx}" if sfx in _DEW else f"dewpoint_{sfx}", [])
        if idx < len(tv) and tv[idx] is not None:
            Tk = tv[idx]+273.15
            Tdk = tdv[idx]+273.15 if idx < len(tdv) and tdv[idx] is not None else Tk-3.0
            p.append(pa); T.append(Tk); Td.append(Tdk); h.append(zm)
    return p, T, Td, h

_WMO_RAIN_CODES = (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82)


def _upgrade_wmo_for_storm(wmo, cape, shear, precip, thr) -> int:
    """
    Se in quell'ora piove (weather_code "pioggia/rovesci") e l'energia/
    organizzazione convettiva locale sono già sufficienti per un temporale
    (stesse soglie SBCAPE/shear usate in logic.severe_hazards), il codice
    WMO generico di pioggia viene promosso a temporale. Evita l'incoerenza
    per cui il bollettino segnala rischio temporali ma l'ora oraria mostra
    solo "pioggia".
    """
    wmo = int(wmo or 0)
    if wmo not in _WMO_RAIN_CODES or (precip or 0) <= 0:
        return wmo
    cape = float(cape or 0)
    shear = float(shear or 0)
    if cape >= thr.SBCAPE_STRONG and shear >= thr.SHEAR_06_ORGANIZED:
        return 96  # temporale con grandine
    if cape >= thr.SBCAPE_MODERATE:
        return 95  # temporale
    return wmo


def build_day_hourly_list(
    day_hourly: Dict[str, Any],
    day_hourly_secondary: Optional[Dict[str, Any]] = None,
    primary_label: str = "primary",
    secondary_label: str = "secondary",
) -> List[Dict[str, Any]]:
    """
    Costruisce la lista hourly_forecast per engine.run_pipeline() da un giorno.
    Se day_hourly_secondary è fornito, aggiunge CAPE del modello secondario
    per il calcolo dello spread multi-modello.
    """
    times   = day_hourly.get("time", [])
    temps   = day_hourly.get("temperature_2m", [])
    rhs     = day_hourly.get("relative_humidity_2m", [])
    winds   = day_hourly.get("wind_speed_10m", [])
    dirs    = day_hourly.get("wind_direction_10m", [])
    gusts   = day_hourly.get("wind_gusts_10m", [])
    clouds  = day_hourly.get("cloud_cover", [])
    clouds_low  = day_hourly.get("cloud_cover_low", [])
    clouds_mid  = day_hourly.get("cloud_cover_mid", [])
    clouds_high = day_hourly.get("cloud_cover_high", [])
    precips = day_hourly.get("precipitation", [])
    capes   = day_hourly.get("cape", [])
    cins    = day_hourly.get("convective_inhibition", [])
    wmos    = day_hourly.get("weather_code", [])
    lifted = day_hourly.get("lifted_index", [])

    # CAPE dal modello secondario (per spread)
    times2 = (day_hourly_secondary or {}).get("time", [])
    capes2 = (day_hourly_secondary or {}).get("cape", [])
    gusts2 = (day_hourly_secondary or {}).get("wind_gusts_10m", [])
    precip2= (day_hourly_secondary or {}).get("precipitation", [])
    t2_idx: Dict[str, int] = {str(t)[-5:]: i for i, t in enumerate(times2)}

    from config import thresholds as thr
    cum = 0.0
    result = []
    for i, t in enumerate(times):
        p = float(precips[i] or 0) if i < len(precips) else 0.0
        cum += p
        alert = ("🔴" if p >= thr.ARPAL_RAIN_1H_ROSSO
                 else "🟠" if p >= thr.ARPAL_RAIN_1H_ARANCIONE
                 else "🟡" if p >= thr.ARPAL_RAIN_1H_GIALLO else "🟢")
        t_key = str(t)[-5:] if t else "??:??"

        # Valori dal modello secondario per lo stesso timestamp
        j = t2_idx.get(t_key)
        cape2_v = float(capes2[j] or 0) if j is not None and j < len(capes2) else None
        gust2_v = float(gusts2[j] or 0) if j is not None and j < len(gusts2) else None
        prec2_v = float(precip2[j] or 0) if j is not None and j < len(precip2) else None

        # Shear/SRH reali per QUESTA ora (non più fissi a 0)
        surf_speed = float(winds[i]) if i < len(winds) and winds[i] is not None else None
        surf_dir   = float(dirs[i])  if i < len(dirs)  and dirs[i]  is not None else None
        wp = _hourly_shear_srh(day_hourly, i, surf_speed, surf_dir)
        surf_t  = float(temps[i]) if i < len(temps) and temps[i] is not None else None
        dew2m   = day_hourly.get("dewpoint_2m", [])
        surf_td = float(dew2m[i]) if i < len(dew2m) and dew2m[i] is not None else None
        sp2m    = day_hourly.get("surface_pressure", [])
        surf_p  = float(sp2m[i]) if i < len(sp2m) and sp2m[i] is not None else None

        p_prof, T_prof, Td_prof, h_prof = _hourly_full_profile(day_hourly, i, surf_t, surf_td, surf_p)

        cape_i = float(capes[i]) if i < len(capes) and capes[i] is not None else 0.0
        wmo_i = wmos[i] if i < len(wmos) else None
        wmo_i = _upgrade_wmo_for_storm(wmo_i, cape_i, wp["shear_0_6"], p, thr)

        pwat_h = ki_h = tt_h = dcape_h = scp_h = stp_h = None
        if len(p_prof) >= 4:
            from indices import pwat_from_profile, k_index, totals_totals, supercell_composite, significant_tornado_parameter
            from thermo import mucape_mucin
            pwat_h = pwat_from_profile(p_prof, T_prof, Td_prof)
            t850v = day_hourly.get("temperature_850hPa", []); td850v = day_hourly.get("dew_point_850hPa", [])
            t700v = day_hourly.get("temperature_700hPa", []); td700v = day_hourly.get("dew_point_700hPa", [])
            t500v = day_hourly.get("temperature_500hPa", [])
            if all(i < len(v) and v[i] is not None for v in (t850v,td850v,t700v,td700v,t500v)):
                ki_h = round(k_index(t850v[i], td850v[i], t700v[i], td700v[i], t500v[i]), 1)
                tt_h = round(totals_totals(t850v[i], td850v[i], t500v[i]), 1)
            from thermo import dcape_from_profile
            dcape_h = dcape_from_profile(p_prof, T_prof, Td_prof)
            cape_h  = float(capes[i]) if i < len(capes) and capes[i] is not None else 0.0
            mucape_h, _, _ = mucape_mucin(p_prof, T_prof, Td_prof)
            if wp["shear_0_6"] is not None and wp["srh_0_3"] is not None:
                scp_h = round(supercell_composite(mucape_h, wp["srh_0_3"], wp["shear_0_6"]), 2)
            from thermo import lcl_height
            cin_h = cins[i] if i < len(cins) and cins[i] is not None else 0
            stp_h = round(significant_tornado_parameter(cape_h, wp["srh_0_1"], wp["shear_0_6"], lcl_height(T_prof[0], Td_prof[0]), cin_h), 2)

        result.append({
            "time":       t_key,
            "T":          temps[i]  if i < len(temps)  else None,
            "RH":         rhs[i]    if i < len(rhs)    else None,
            "wind":       float(winds[i]) if i < len(winds) and winds[i] is not None else None,
            "wind_dir":   dirs[i]   if i < len(dirs)   else None,
            "wind_gust":  float(gusts[i]) if i < len(gusts) and gusts[i] is not None else 0.0,
            "cloud":      clouds[i] if i < len(clouds) and clouds[i] is not None else None,
            "cloud_low":  clouds_low[i]  if i < len(clouds_low)  and clouds_low[i]  is not None else None,
            "cloud_mid":  clouds_mid[i]  if i < len(clouds_mid)  and clouds_mid[i]  is not None else None,
            "cloud_high": clouds_high[i] if i < len(clouds_high) and clouds_high[i] is not None else None,
            "precip":     p,
            "precip_cum": round(cum, 1),
            "CAPE":       float(capes[i]) if i < len(capes) and capes[i] is not None else 0.0,
            "SBCAPE":     float(capes[i]) if i < len(capes) and capes[i] is not None else 0.0,
            "MUCAPE":     mucape_h,
            "CIN":        cins[i]   if i < len(cins)  else 0,
            "shear":      wp["shear_0_6"],
            "SRH":        wp["srh_0_3"],
            "shear_0_1":  wp["shear_0_1"],
            "shear_0_3":  wp["shear_0_3"],
            "PWAT": pwat_h if pwat_h is not None else 0,
            "KI": ki_h,
            "TT": tt_h,
            "DCAPE": dcape_h,
            "STP": stp_h,
            "SCP": scp_h,
            "srh_0_1":    wp["srh_0_1"],
            "wmo_code":   wmo_i,
            "alert":      alert,
            "LI":         lifted[i] if i < len(lifted) and lifted[i] is not None else None,
            f"CAPE_{secondary_label}":  cape2_v,
            f"gust_{secondary_label}":  gust2_v,
            f"precip_{secondary_label}": prec2_v,
        })
    return result

# ─────────────────────────────────────────────────────────────────────────────
# Freschezza dei dati NWP — verifica l'età reale della run AROME/ICON-EU
# ─────────────────────────────────────────────────────────────────────────────

def check_model_freshness(
    data: Optional[Dict[str, Any]],
    model_api_name: str,
    model_display: str,
    now: "datetime.datetime",
) -> Tuple[bool, str]:
    """
    Inferisce l'orario di inizializzazione della run NWP dall'ultimo timestamp
    non-null di temperature_2m e verifica che la run non sia troppo vecchia.
    Ritorna (ok: bool, messaggio: str).
    """
    from config import MODEL_HORIZONS_HOURS, MAX_RUN_AGE_H
    from zoneinfo import ZoneInfo as _ZI

    if data is None:
        return False, f"{model_display}: dati non disponibili"

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    if not times or not temps:
        return False, f"{model_display}: dati orari non disponibili per verifica freshness"

    last_valid_idx = None
    for i in range(len(temps) - 1, -1, -1):
        if temps[i] is not None:
            last_valid_idx = i
            break
    if last_valid_idx is None:
        return False, f"{model_display}: temperature_2m interamente null"

    try:
        last_valid_dt = datetime.datetime.fromisoformat(times[last_valid_idx]).replace(tzinfo=_ZI(TIMEZONE))
    except ValueError:
        return False, f"{model_display}: formato timestamp non riconosciuto"

    horizon_h = MODEL_HORIZONS_HOURS.get(model_api_name)
    if horizon_h is None:
        return True, f"{model_display}: orizzonte nominale non noto, età non verificabile"

    run_dt = last_valid_dt - datetime.timedelta(hours=horizon_h)
    age_h = (now - run_dt).total_seconds() / 3600

    if age_h > MAX_RUN_AGE_H:
        return False, (
            f"{model_display}: run obsoleta, inizializzata ~{run_dt.strftime('%d/%m %H:%M')} "
            f"({age_h:.0f}h fa, soglia {MAX_RUN_AGE_H}h)"
        )
    return True, f"{model_display}: run aggiornata (~{age_h:.0f}h fa)"

def fetch_forecast_3days(
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    timeout: int = 35,
) -> Dict[str, Any]:
    """
    Scarica previsioni 3 giorni da AROME + ICON-EU (+ ICON-2I per LI e TENDENZA)
    e le unisce.
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    today   = _dt.datetime.now(_ZI(TIMEZONE)).date()
    start_s = today.strftime("%Y-%m-%d")
    end_d2  = (today + _dt.timedelta(days=3)).strftime("%Y-%m-%d")
    end_d1  = (today + _dt.timedelta(days=2)).strftime("%Y-%m-%d")

    print("  [io] Scarico ICON-EU (3 giorni)...")
    icon_data = _fetch_one_model("icon_eu", start_s, end_d2, lat, lon, timeout)
    if icon_data is not None:
        print(f"  [io] ICON-EU: {len(icon_data['hourly']['time'])} ore")
    else:
        print("  ⚠ ICON-EU non disponibile: continuo con AROME se disponibile")

    arome_data = None
    arome_model_name = None
    for model in ["meteofrance_arome_france", "meteofrance_arome_france_hd"]:
        print(f"  [io] Provo {model}...")
        d = _fetch_one_model(model, start_s, end_d1, lat, lon, timeout)
        if d is not None:
            arome_data = d
            arome_model_name = model
            print(f"  [io] {model}: {len(d['hourly']['time'])} ore")
            break
    if arome_data is None:
        print("  [io] AROME non disponibile, solo ICON-EU")

    if icon_data is None and arome_data is not None:
        icon_data = arome_data
        print("  ⚠ Fallback modello: AROME usato anche come base di continuità")
    if icon_data is None:
        raise RuntimeError("Nessun modello meteorologico disponibile")

    # ICON-2I (ItaliaMeteo-ARPAE, 2km): usato per il Lifted Index (AROME non lo
    # fornisce in modo affidabile su quest'area) e come base per la TENDENZA
    # (giorno 2), dato che AROME non copre quell'orizzonte.
    print("  [io] Provo ICON-2I (ItaliaMeteo-ARPAE)...")
    icon2i_data = _fetch_one_model("italia_meteo_arpae_icon_2i", start_s, end_d2, lat, lon, timeout)
    if icon2i_data is not None:
        print(f"  [io] ICON-2I: {len(icon2i_data['hourly']['time'])} ore")
    else:
        print("  [io] ICON-2I non disponibile")

    print("  [io] Provo best_match (per Lifted Index)...")
    li_data = _fetch_one_model("best_match", start_s, end_d2, lat, lon, timeout)
    if li_data is not None:
        print(f"  [io] best_match: {len(li_data['hourly']['time'])} ore")
    else:
        print("  [io] best_match non disponibile")

# ── Verifica freschezza delle run NWP appena scaricate ─────────────────
    from zoneinfo import ZoneInfo as _ZI_fresh
    now_check = datetime.datetime.now(_ZI_fresh(TIMEZONE))
    freshness: Dict[str, Any] = {}

    ok_icon, msg_icon = check_model_freshness(icon_data, "icon_eu", "ICON-EU", now_check)
    freshness["icon_eu"] = {"ok": ok_icon, "msg": msg_icon}
    print(f"  [freshness] {msg_icon}")

    if arome_data is not None:
        ok_arome, msg_arome = check_model_freshness(arome_data, arome_model_name, "AROME", now_check)
        freshness["arome"] = {"ok": ok_arome, "msg": msg_arome}
        print(f"  [freshness] {msg_arome}")
    else:
        freshness["arome"] = {"ok": False, "msg": "AROME: non disponibile"}
  
    merged, fallback_stats = _merge_hourly(arome_data, icon_data)
    if fallback_stats:
        print(f"  [io] Variabili colmate da ICON-EU: {fallback_stats}")

    if li_data is not None:
        li_h = li_data.get("hourly", {})
        li_times = li_h.get("time", [])
        li_vals = li_h.get("lifted_index", [])
        li_map = {
            str(t)[-5:]: li_vals[i]
            for i, t in enumerate(li_times)
            if i < len(li_vals) and li_vals[i] is not None
        }
        if li_map:
            for dataset in (merged, icon_data):
                h = dataset.get("hourly", {})
                times = h.get("time", [])
                old_li = h.get("lifted_index", [None] * len(times))
                h["lifted_index"] = [
                    li_map.get(str(t)[-5:], old_li[i] if i < len(old_li) else None)
                    for i, t in enumerate(times)
                ]
            print(f"  [io] Lifted Index sovrascritto da best_match su {len(li_map)} ore")
        else:
            print("  [io] best_match non ha restituito valori di lifted_index utilizzabili")
    else:
        print("  [io] best_match non disponibile, Lifted Index resta quello di AROME/ICON-EU (se presente)")

    if icon2i_data is not None and 'li_map' in dir() and li_map:
        h2i = icon2i_data.get("hourly", {})
        times2i = h2i.get("time", [])
        old_li2i = h2i.get("lifted_index", [None] * len(times2i))
        h2i["lifted_index"] = [
            li_map.get(str(t)[-5:], old_li2i[i] if i < len(old_li2i) else None)
            for i, t in enumerate(times2i)
        ]

    # Giorno 2 (TENDENZA): usa ICON-2I se copre a sufficienza, altrimenti ICON-EU
    day2_icon2i = extract_day_hourly(icon2i_data, 2) if icon2i_data is not None else {}
    if day2_icon2i.get("time") and len(day2_icon2i["time"]) >= 12:
        day2_final = day2_icon2i
        model_fallback_label = "ICON-2I"
    else:
        day2_final = extract_day_hourly(icon_data, 2)
        model_fallback_label = "ICON-EU"

    print("  [io] Provo AROME-PI (nowcast 15 minuti)...")
    arome_pi_data = fetch_arome_pi_nowcast(lat, lon, timeout)

    return {
        "day0":         extract_day_hourly(merged,     0),
        "day1":         extract_day_hourly(merged,     1),
        "day2":         day2_final,
        "day0_icon":    extract_day_hourly(icon_data,  0),
        "day1_icon":    extract_day_hourly(icon_data,  1),
        "model_primary":  "AROME+ICON-EU" if arome_data else "ICON-EU",
        "model_fallback": model_fallback_label,
        "arome_pi":       arome_pi_data,
        "freshness":      freshness,
    }

# ─────────────────────────────────────────────────────────────────────────────
# AROME-PI (Prévision Immédiate) – nowcast a 15 minuti
# ─────────────────────────────────────────────────────────────────────────────

_MINUTELY15_AROME_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "precipitation", "rain", "snowfall",
    "cape", "wind_speed_10m", "wind_speed_80m",
    "wind_direction_10m", "wind_direction_80m", "wind_gusts_10m",
    "visibility",
]


def fetch_arome_pi_nowcast(
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    timeout: int = 20,
) -> Optional[Dict[str, Any]]:
    """
    Scarica il nowcast AROME-PI tramite &minutely_15= di Open-Meteo.
    AROME-PI copre realmente solo le prime 6 ore (24 step da 15 min);
    oltre, Open-Meteo interpolerebbe solo l'orario, quindi non lo chiediamo.

    NOTA: Open-Meteo non espone "AROME-PI" come modello a sé (&models=...).
    I dati AROME-PI popolano automaticamente &minutely_15= quando si
    interroga meteofrance_seamless su un punto dentro il dominio AROME.
    Se il punto fosse fuori dominio, la risposta arriva comunque ma i
    valori sarebbero di fatto interpolazione dell'orario: non c'è un flag
    esplicito nel JSON per distinguerlo.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "minutely_15": ",".join(_MINUTELY15_AROME_VARS),
        "models": "meteofrance_seamless",
        "forecast_minutely_15": AROME_PI_FORECAST_QUARTERS,
        "timezone": TIMEZONE,
    }
    try:
        resp = requests.get(OPEN_METEO_BASE, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        n = len(data.get("minutely_15", {}).get("time", []))
        if n == 0:
            print("  [AROME-PI] Nessun dato minutely_15 restituito, nowcast non disponibile.")
            return None
        print(f"  [AROME-PI] OK: {n} step da 15 minuti ricevuti.")
        return data
    except Exception as e:
        print(f"  [AROME-PI] Non disponibile ({e}), proseguo solo con AROME orario.")
        return None


def build_nowcast_quarter_hourly(
    pi_data: Optional[Dict[str, Any]],
    hourly_list: List[Dict[str, Any]],
    day_date,
    window_hours: float = 2.0,
    next_day_hourly_list: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Sostituisce le ore correnti della tabella oraria con passi da 15 minuti,
    per una finestra di `window_hours` ore a partire da ADESSO.

    Ritorna una TUPLA (righe_di_oggi, righe_di_domani):
      - righe_di_oggi: quarti d'ora + ore rimanenti che appartengono alla
        giornata `day_date` → vanno mostrate nella sezione "OGGI".
      - righe_di_domani: quarti d'ora che cadono DOPO la mezzanotte, quindi
        appartengono già al giorno dopo (lista vuota se la finestra non
        supera la mezzanotte). Il chiamante deve inserirli nella sezione
        "DOMANI" al posto delle sue prime ore, per evitare che compaiano
        due volte.

    `next_day_hourly_list` (opzionale): la tabella oraria di DOMANI, già
    costruita con build_day_hourly_list. Serve SOLO per recuperare i dati
    che AROME-PI non fornisce (CIN, LI, shear, SRH, PWAT, K-Index, TT,
    DCAPE, SCP, nuvolosità, weather_code) quando un quarto d'ora cade dopo
    la mezzanotte: senza, quei campi restavano vuoti perché la tabella
    oraria di "oggi" non arriva mai oltre le 23:00.
    """
    if not pi_data:
        return hourly_list, []

    m = pi_data.get("minutely_15", {})
    times = m.get("time", [])
    if not times:
        return hourly_list, []

    from zoneinfo import ZoneInfo as _ZI
    now_local = datetime.datetime.now(_ZI(TIMEZONE)).replace(tzinfo=None, second=0, microsecond=0)
    window_end = now_local + datetime.timedelta(hours=window_hours)

    # Tabella oraria di "oggi" + (se fornita) di "domani": permette di
    # recuperare i dati AROME anche per i quarti d'ora dopo mezzanotte.
    hourly_by_hour = {h["time"][:2] + ":00": h for h in hourly_list if h.get("time")}
    if next_day_hourly_list:
        for h in next_day_hourly_list:
            if not h.get("time"):
                continue
            key = h["time"][:2] + ":00"
            hourly_by_hour.setdefault(key, h)

    def g(key, i, default=None):
        vals = m.get(key, [])
        v = vals[i] if i < len(vals) else None
        return v if v is not None else default

    righe_oggi: List[Dict[str, Any]] = []
    righe_domani: List[Dict[str, Any]] = []
    cum_precip = 0.0

    for i, t in enumerate(times):
        try:
            t_dt = datetime.datetime.strptime(str(t), "%Y-%m-%dT%H:%M")
        except ValueError:
            continue
        if t_dt < now_local or t_dt >= window_end:
            continue  # fuori dalla finestra delle prossime `window_hours` ore

        hhmm = str(t)[-5:]
        hh_key = hhmm[:2] + ":00"
        parent = hourly_by_hour.get(hh_key, {})

        precip_15 = float(g("precipitation", i, 0.0) or 0.0)
        cum_precip += precip_15
        precip_rate_h = round(precip_15 * 4.0, 2)  # equivalente mm/h per le soglie ARPAL

        alert = ("🔴" if precip_rate_h >= thresholds.ARPAL_RAIN_1H_ROSSO
                 else "🟠" if precip_rate_h >= thresholds.ARPAL_RAIN_1H_ARANCIONE
                 else "🟡" if precip_rate_h >= thresholds.ARPAL_RAIN_1H_GIALLO else "🟢")

        riga = {
            "time":       hhmm,
            "T":          g("temperature_2m", i, parent.get("T")),
            "RH":         g("relative_humidity_2m", i, parent.get("RH")),
            "wind":       g("wind_speed_10m", i, parent.get("wind")),
            "wind_dir":   g("wind_direction_10m", i, parent.get("wind_dir")),
            "wind_gust":  g("wind_gusts_10m", i, parent.get("wind_gust")),
            "cloud":      parent.get("cloud"),
            "cloud_low":  parent.get("cloud_low"),
            "cloud_mid":  parent.get("cloud_mid"),
            "cloud_high": parent.get("cloud_high"),
            "precip":     precip_rate_h,
            "precip_cum": round(cum_precip, 1),
            "CAPE":       g("cape", i, parent.get("CAPE")),
            "CIN":        parent.get("CIN"),
            "shear":      parent.get("shear"),
            "shear_0_1":  parent.get("shear_0_1"),
            "shear_0_3":  parent.get("shear_0_3"),
            "PWAT":       parent.get("PWAT"),
            "KI":         parent.get("KI"),
            "TT":         parent.get("TT"),
            "DCAPE":      parent.get("DCAPE"),
            "SCP":        parent.get("SCP"),
            "srh_0_1":    parent.get("srh_0_1"),
            "SRH":        parent.get("SRH"),
            "wmo_code":   parent.get("wmo_code"),
            "alert":      alert,
            "LI":         parent.get("LI"),
            "source":     "AROME-PI" if g("temperature_2m", i) is not None else "AROME (fallback orario)",
        }

        if t_dt.date() == day_date:
            righe_oggi.append(riga)
        else:
            righe_domani.append(riga)

    if not righe_oggi and not righe_domani:
        return hourly_list, []

    # Ore rimanenti di OGGI dopo la finestra dei 15 minuti (risoluzione oraria)
    resto = []
    for h in hourly_list:
        t_h = h.get("time", "00:00")
        try:
            h_dt = datetime.datetime.combine(
                day_date, datetime.datetime.strptime(t_h, "%H:%M").time()
            )
        except ValueError:
            continue
        if h_dt >= window_end:
            resto.append(h)

    return righe_oggi + resto, righe_domani

# ─────────────────────────────────────────────────────────────────────────────
# Stub GRIB / NetCDF / Sounding / Radar (pronti per implementazione)
# ─────────────────────────────────────────────────────────────────────────────

# Stub forward declarations per compatibilità legacy
def read_model_grib(path: str) -> Dict[str, Any]:
    raise NotImplementedError("pip install cfgrib eccodes")

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


def fetch_uwyo_sounding(
    station_id: str = "16080",
    hour_utc: int = 12,
    timeout: int = 15,
) -> Optional[Dict[str, Any]]:
    """
    Scarica il radiosondaggio in tempo reale dall'archivio University of Wyoming.

    Stazioni consigliate (la più vicina a La Spezia con dati regolari):
      16080 – Milano Linate  (≈ 250 km, disponibile 00Z e 12Z)
      16090 – Cuneo/Levaldigi (stagionale, disponibile solo 12Z)

    Ritorna un dict compatibile con il sounding di engine.run_pipeline(),
    o None in caso di errore / dati non recenti.

    NOTA: i dati UWYO sono disponibili solo a 00Z e 12Z UTC.
    Il sounding integra / sostituisce il profilo da modello se entro UWYO_MAX_AGE_HOURS.
    """
    import re
    from config import thresholds as thr

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    # Scegli il run più vicino (00Z o 12Z)
    if hour_utc not in (0, 12):
        hour_utc = 0 if now_utc.hour < 6 or now_utc.hour >= 18 else 12
    sounding_dt = now_utc.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if now_utc < sounding_dt:
        sounding_dt -= datetime.timedelta(days=1)
    age_h = (now_utc - sounding_dt).total_seconds() / 3600
    if age_h > thr.UWYO_MAX_AGE_HOURS:
        # Prova l'altro run
        hour_utc = 12 if hour_utc == 0 else 0
        sounding_dt = now_utc.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
        if now_utc < sounding_dt:
            sounding_dt -= datetime.timedelta(days=1)
        age_h = (now_utc - sounding_dt).total_seconds() / 3600
        if age_h > thr.UWYO_MAX_AGE_HOURS:
            print(f"  [UWYO] Nessun sounding recente (età minima: {age_h:.0f}h > {thr.UWYO_MAX_AGE_HOURS}h)")
            return None

    url = (
        "https://weather.uwyo.edu/cgi-bin/sounding.py"
        f"?TYPE=TEXT%3ALIST"
        f"&YEAR={sounding_dt.year}"
        f"&MONTH={sounding_dt.month:02d}"
        f"&FROM={sounding_dt.day:02d}{sounding_dt.hour:02d}"
        f"&TO={sounding_dt.day:02d}{sounding_dt.hour:02d}"
        f"&STNM={station_id}"
    )
    print(f"  [UWYO] Fetch sounding {station_id} {sounding_dt.strftime('%Y-%m-%d %HZ')} ...")

    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": "MeteoBot/2.0 research use"})
        resp.raise_for_status()
        html = resp.text

        # Estrai la tabella dati dal formato UWYO text
        # Cerca il blocco tra i tag <pre>
        pre_match = re.search(r"<pre>(.*?)</pre>", html, re.DOTALL)
        if not pre_match:
            print("  [UWYO] Tag <pre> non trovato")
            return None

        lines = pre_match.group(1).strip().splitlines()
        # Riga di intestazione: PRES HGHT TEMP DWPT RELH MIXR DRCT SKNT THTA THTE THTV
        # Cerchiamo la riga con i dati numerici (dopo le 5 righe di header)
        data_start = 0
        for idx, line in enumerate(lines):
            if re.match(r"^\s*\d", line):
                data_start = idx
                break

        pres_pa, temp_k, dewp_k, hgt_m = [], [], [], []
        u_ms, v_ms = [], []

        for line in lines[data_start:]:
            parts = line.split()
            if len(parts) < 8:
                continue
            try:
                pres = float(parts[0]) * 100.0  # hPa → Pa
                hgt  = float(parts[1])           # m
                temp = float(parts[2]) + 273.15  # °C → K
                dwpt = float(parts[3]) + 273.15  # °C → K
                drct = float(parts[6])            # gradi
                sknt = float(parts[7]) * 0.5144  # kt → m/s
            except (ValueError, IndexError):
                continue
            if pres < 5000:
                break  # sopra 50 hPa, nessun interesse pratico

            import math as _math
            rad = _math.radians(drct)
            pres_pa.append(pres)
            hgt_m.append(hgt)
            temp_k.append(temp)
            dewp_k.append(dwpt)
            u_ms.append(-sknt * _math.sin(rad))
            v_ms.append(-sknt * _math.cos(rad))

        if len(pres_pa) < 6:
            print(f"  [UWYO] Dati insufficienti: {len(pres_pa)} livelli")
            return None

        print(f"  [UWYO] OK: {len(pres_pa)} livelli, "
              f"p={pres_pa[0]/100:.0f}→{pres_pa[-1]/100:.0f} hPa, "
              f"età {age_h:.1f}h")
        return {
            "source":     f"UWYO-{station_id}",
            "valid_utc":  sounding_dt.isoformat(),
            "age_hours":  round(age_h, 1),
            "pressure_pa":   pres_pa,
            "temperature_k": temp_k,
            "dewpoint_k":    dewp_k,
            "height_m":      hgt_m,
            "u_ms":          u_ms,
            "v_ms":          v_ms,
        }

    except requests.exceptions.Timeout:
        print("  [UWYO] Timeout connessione")
    except Exception as e:
        print(f"  [UWYO] Errore: {e}")
    return None


def compute_model_spread(
    arome_hourly: Optional[Dict[str, Any]],
    icon_hourly: Optional[Dict[str, Any]],
    day_offset: int = 0,
    tz: str = TIMEZONE,
) -> Dict[str, Any]:
    """
    Calcola lo spread tra AROME e ICON-EU per le variabili chiave del giorno.
    Ritorna un dict con variabili dove c'è disaccordo significativo.
    Soglie di significatività:
      CAPE:    >500 J/kg   (WMO: impatto su previsione temporali)
      precip:  >5 mm/h     (ARPAL: soglia allerta)
      T_max:   >2°C        (WMO: soglia forecast skill)
      gust:    >15 km/h    (ARPAL: rilevante per allerte vento)
    """
    if arome_hourly is None or icon_hourly is None:
        return {}

    def _daily_max(data, key, day_offset=day_offset, tz=tz):
        """Massimo giornaliero di una variabile dal dataset orario raw."""
        from zoneinfo import ZoneInfo as _ZI
        import datetime as _dt
        today  = _dt.datetime.now(_ZI(tz)).date()
        target = (today + _dt.timedelta(days=day_offset)).strftime("%Y-%m-%d")
        h = data.get("hourly", {})
        times = h.get("time", [])
        vals = h.get(key, [])
        day_vals = [vals[i] for i, t in enumerate(times)
                    if str(t).startswith(target) and i < len(vals) and vals[i] is not None]
        return max(day_vals) if day_vals else None

    def _daily_sum(data, key):
        from zoneinfo import ZoneInfo as _ZI
        import datetime as _dt
        today  = _dt.datetime.now(_ZI(tz)).date()
        target = (today + _dt.timedelta(days=day_offset)).strftime("%Y-%m-%d")
        h = data.get("hourly", {})
        times = h.get("time", [])
        vals = h.get(key, [])
        day_vals = [vals[i] for i, t in enumerate(times)
                    if str(t).startswith(target) and i < len(vals) and vals[i] is not None]
        return sum(day_vals) if day_vals else None

    spread: Dict[str, Any] = {}

    checks = [
        ("CAPE_peak",    "cape",              "max", 500.0,  "J/kg"),
        ("precip_sum",   "precipitation",     "sum", 5.0,    "mm"),
        ("gust_max",     "wind_gusts_10m",    "max", 15.0,   "km/h"),
        ("T_max",        "temperature_2m",    "max", 2.0,    "°C"),
    ]

    for label, key, mode, threshold, unit in checks:
        fn = _daily_max if mode == "max" else _daily_sum
        v_a = fn(arome_hourly, key)
        v_i = fn(icon_hourly,  key)
        if v_a is None or v_i is None:
            continue
        diff = abs(v_a - v_i)
        if diff >= threshold:
            spread[label] = {
                "AROME": round(v_a, 1),
                "ICON":  round(v_i, 1),
                "diff":  round(diff, 1),
                "unit":  unit,
                "high":  diff >= threshold * 2,
            }

    return spread


def fetch_temperature_history(
    past_days: int = 7,
    lat: float = LATITUDE,
    lon: float = LONGITUDE,
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    """
    Scarica gli ultimi past_days di temperature giornaliere per l'analisi
    delle ondate di calore (EHF - Excess Heat Factor, WMO 2014).
    Usa l'endpoint Open-Meteo con past_days.
    """
    try:
        params = {
            "latitude":    lat,
            "longitude":   lon,
            "daily":       "temperature_2m_max,temperature_2m_min,apparent_temperature_max",
            "past_days":   past_days,
            "forecast_days": 3,
            "timezone":    TIMEZONE,
        }
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params, timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        dates  = daily.get("time", [])
        t_max  = daily.get("temperature_2m_max", [])
        t_min  = daily.get("temperature_2m_min", [])
        t_app  = daily.get("apparent_temperature_max", [])
        result = []
        for i, d in enumerate(dates):
            result.append({
                "date":   d,
                "T_max":  t_max[i]  if i < len(t_max)  else None,
                "T_min":  t_min[i]  if i < len(t_min)  else None,
                "T_app":  t_app[i]  if i < len(t_app)  else None,
            })
        return result
    except Exception as e:
        print(f"  [io] Errore fetch temperature history: {e}")
        return []


_ARPAL_ALERT_URL = "https://allertaliguria.regione.liguria.it/allerta_protezione_civile.php"
_ARPAL_LEVEL_MAP = {"green": "verde", "yellow": "gialla", "orange": "arancione", "red": "rossa"}


def fetch_arpal_alert(timeout: int = 15) -> Dict[str, Any]:
    """
    Legge automaticamente lo stato di allerta ufficiale di Protezione Civile
    Liguria/ARPAL dalla pagina pubblica (allerta_protezione_civile.php), senza
    bisogno di un controllo manuale. La pagina mostra un riquadro colorato
    (classe CSS "al-msgbar-green/yellow/orange/red") con titolo e tipo di
    rischio: qui viene solo letto, non interpretato/inventato.
    Ritorna {"ok": False, ...} se il sito non è raggiungibile o la pagina ha
    cambiato formato: il chiamante deve trattare l'allerta come "non
    disponibile", mai assumere un livello di default.
    """
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(_ARPAL_ALERT_URL, timeout=timeout, headers={"User-Agent": "MeteoBot/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        bar = soup.find(class_=lambda c: c and c.startswith("al-msgbar-"))
        if bar is None:
            return {"ok": False, "error": "formato pagina ARPAL non riconosciuto"}
        color = next((c.replace("al-msgbar-", "") for c in bar.get("class", [])
                      if c.startswith("al-msgbar-")), None)
        level = _ARPAL_LEVEL_MAP.get(color)
        if level is None:
            return {"ok": False, "error": f"colore allerta non riconosciuto: {color}"}
        headings = [h.get_text(strip=True) for h in bar.find_all(["h1", "h2"])]
        return {
            "ok": True,
            "level": level,
            "message_datetime": headings[0] if len(headings) > 0 else None,
            "title": headings[1] if len(headings) > 1 else None,
            "risk_types": headings[2] if len(headings) > 2 else None,
            "source_url": _ARPAL_ALERT_URL,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
