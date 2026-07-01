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


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Stub GRIB / NetCDF / Sounding / Radar (pronti per implementazione)
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
