import math
import requests


def extract_pressure_hpa(dati_device):
    """
    Estrae la pressione in hPa dalla risposta Tuya con fallback su più chiavi.
    """
    # Prova chiavi comuni
    for key in ["pressure", "pressure_hpa", "pressure_local", "pressure_station"]:
        val = dati_device.get(key)
        if val is not None:
            try:
                return float(val)
            except Exception:
                continue
    # Prova chiavi con conversione da decimi
    for key in ["pressure_value", "pressure_value_hpa"]:
        val = dati_device.get(key)
        if val is not None:
            try:
                return float(val) / 10.0
            except Exception:
                continue
    return None


_WMO_LA_SPEZIA_STATIONS = [
    "LIQW",  # Sarzana/Luni (SP)
    "LIRQ",  # Firenze Peretola (fallback remoto)
    "LIMJ",  # Genova Sestri (fallback remoto)
]


def _calc_relative_humidity(temp_c, dewpoint_c):
    """Calcola RH% da temperatura e dew point (Magnus)."""
    try:
        a = 17.625
        b = 243.04
        gamma_t = (a * temp_c) / (b + temp_c)
        gamma_td = (a * dewpoint_c) / (b + dewpoint_c)
        rh = 100.0 * math.exp(gamma_td - gamma_t)
        return max(0, min(100, int(round(rh))))
    except Exception:
        return None


def fetch_wmo_station_data_laspezia(timeout=15):
    """Recupera dati meteo da rete METAR/WMO con priorità area La Spezia.

    Restituisce un dizionario normalizzato con campi:
    temperature, dewpoint, pressure, humidity, wind_speed, wind_gust,
    station_id, station_name, source_note.
    """
    url = "https://aviationweather.gov/api/data/metar"
    params = {
        "ids": ",".join(_WMO_LA_SPEZIA_STATIONS),
        "format": "json",
    }

    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        records = resp.json()
    except Exception as exc:
        print(f"✗ Errore fetch fallback WMO/METAR: {exc}")
        return None

    if not isinstance(records, list) or not records:
        print("✗ Fallback WMO/METAR non disponibile: nessuna osservazione")
        return None

    by_station = {
        str(item.get("icaoId", "")).upper(): item
        for item in records
        if isinstance(item, dict) and item.get("icaoId")
    }

    selected = None
    for station_id in _WMO_LA_SPEZIA_STATIONS:
        if station_id in by_station:
            selected = by_station[station_id]
            break

    if not selected:
        print("✗ Fallback WMO/METAR non disponibile: stazioni candidate senza dati")
        return None

    try:
        temp_c = float(selected.get("temp"))
        dew_c = float(selected.get("dewp"))
        pressure_hpa = float(selected.get("altim"))
    except Exception:
        print(f"✗ Dati WMO/METAR incompleti: {selected}")
        return None

    wind_speed_kt = float(selected.get("wspd") or 0.0)
    wind_gust_kt = float(selected.get("wgst") or wind_speed_kt)
    humidity = _calc_relative_humidity(temp_c, dew_c)
    if humidity is None:
        humidity = 0

    station_id = str(selected.get("icaoId", "N/A")).upper()
    station_name = str(selected.get("name") or station_id)

    data = {
        "temperature": round(temp_c, 1),
        "dewpoint": round(dew_c, 1),
        "pressure": round(pressure_hpa, 1),
        "humidity": humidity,
        "wind_speed": round(wind_speed_kt * 1.852, 1),
        "wind_gust": round(wind_gust_kt * 1.852, 1),
        "station_id": station_id,
        "station_name": station_name,
        "source_note": f"Stazione esterna WMO/METAR {station_id} ({station_name})",
    }

    print(
        "✓ Fallback WMO attivo: "
        f"{data['station_id']} | T={data['temperature']}°C Td={data['dewpoint']}°C "
        f"P={data['pressure']} hPa RH={data['humidity']}% "
        f"Wind={data['wind_speed']} km/h Gust={data['wind_gust']} km/h"
    )
    return data
