"""
MeteoBot — Versione Ecowitt Wittboy (STANDALONE)
==================================================
Script completamente autonomo, identico a meteo.py nella logica
(invio messaggi, calcolo API, SBCAPE, report, grafici, ecc.)
ma con sorgente dati Ecowitt Wittboy al posto di Tuya.
Nessun import da meteo.py — può funzionare anche se meteo.py
viene cancellato.
Per utilizzarlo:
  1. Impostare le variabili d'ambiente ECOWITT_APPLICATION_KEY,
     ECOWITT_API_KEY, ECOWITT_MAC con i dati della propria stazione.
  2. Eseguire: python meteo_ecowitt.py
     Oppure:  python meteo_ecowitt.py --force   (invio forzato)
              python meteo_ecowitt.py --sbcape   (solo calcolo SBCAPE)
"""
import time
import hashlib
import requests
import json
import os
import math
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
from scipy.interpolate import interp1d
TZ_ROME = ZoneInfo("Europe/Rome")
from config import (
    ECOWITT_APPLICATION_KEY,
    ECOWITT_API_KEY,
    ECOWITT_MAC,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    FILE_STORICO,
    load_state_section,
    save_state_section,
    thresholds,
    LATITUDE,
    LONGITUDE,
    ELEVATION,
    TIMEZONE,
    ECOWITT_RAIN_CALIBRATION,
    ECOWITT_RAIN_RATE_CALIBRATION,
)
from utils import fetch_wmo_station_data_laspezia
_RD = 287.05      
_RV = 461.5       
_CP = 1005.0      
_LV = 2.5e6       
_G  = 9.80665     
_EPSILON = 0.622  
_API_CACHE = {}
_CACHE_DURATION = 600  
def carica_storico():
    """Carica lo storico delle ultime 24h di misurazioni."""
    if os.path.exists(FILE_STORICO):
        try:
            with open(FILE_STORICO, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []
def salva_storico(storico):
    """Salva lo storico, mantenendo solo le ultime 24h."""
    now = datetime.now(TZ_ROME)
    cutoff_dt = now - timedelta(hours=24)
    filtered = []
    for s in storico:
        ts = s.get("ts")
        if not ts:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=TZ_ROME)
            if ts_dt >= cutoff_dt:
                filtered.append(s)
        except Exception:
            continue
    with open(FILE_STORICO, "w") as f:
        json.dump(filtered, f)
def calcola_tendenza_barometrica(storico, pressione_attuale):
    """Calcola la tendenza barometrica nelle ultime 3h.
    Restituisce (simbolo, delta_hPa, descrizione)."""
    now = datetime.now(TZ_ROME)
    tre_ore_fa_dt = now - timedelta(hours=3)
    recenti = []
    for s in storico:
        ts = s.get("ts")
        if not ts or "pressione" not in s:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=TZ_ROME)
            if ts_dt >= tre_ore_fa_dt:
                recenti.append((ts_dt, s))
        except Exception:
            continue
    if len(recenti) < 2:
        return "➡️", 0, "Dati insufficienti"
    recenti.sort(key=lambda x: x[0])
    pressione_3h = recenti[0][1]["pressione"]
    delta = pressione_attuale - pressione_3h
    if delta >= 3:
        return "⬆️", delta, "In forte aumento"
    elif delta >= 1:
        return "↗️", delta, "In aumento"
    elif delta > -1:
        return "➡️", delta, "Stabile"
    elif delta > -3:
        return "↘️", delta, "In calo"
    else:
        return "⬇️", delta, "In forte calo"
def classifica_massa_aria(temp, dew_point, pressione_msl, mese):
    """Classifica la massa d'aria secondo Bergeron (1928).
    Discriminante primario: punto di rugiada (Td).
    ──────────────────────────────────────────────
    In meteorologia operativa la classificazione si basa su θe a 850 hPa
    (da radiosondaggio o modello NWP), livello in cui il riscaldamento
    solare superficiale non arriva.  Quando si dispone solo di dati di
    superficie, θe mostra un **ciclo diurno spurio** (±10-15 °C) perché
    la temperatura al suolo è dominata dal riscaldamento/raffreddamento
    diabatico (radiativo), non adiabatico.  Ciò causa salti artificiosi
    nella classificazione tra giorno e notte.
    Il punto di rugiada (Td) non ha questo problema:
      • variazione diurna tipica < 2 °C (quasi conservativo)
      • rappresenta direttamente il contenuto d'umidità e la regione
        sorgente della massa d'aria
      • è il parametro standard usato da NWS, ECMWF, Météo-France
        per l'identificazione delle masse d'aria da osservazioni al suolo
    θe viene calcolata correttamente (Bolton 1980, con pressione alla
    stazione anziché MSL) e riportata a scopo informativo / convettivo.
    Discriminanti secondari:
      • spread T−Td  → continentale vs marittima  (Stull 2017)
      • anomalia T   → sottoclassificazione locale (ARPAL 1991-2020)
    Soglie Td per il Mediterraneo nord-occidentale (La Spezia):
      Td < −8 °C   → Artica  (cA / mA)
      Td −8…0 °C   → Polare  (cP / mP)
      Td  0…8 °C   → Polare modificata / transizione
      Td  8…15 °C  → Mediterranea / temperata
      Td 15…20 °C  → Subtropicale
      Td ≥ 20 °C   → Tropicale
    Riferimenti:
      Bolton D.  (1980)  Mon. Wea. Rev., 108, 1046-1053
      Bergeron T. (1928) Geofysiske Publikasjoner, 5(6)
      Stull R.    (2017) Practical Meteorology, Univ. of British Columbia
      Lionello P. et al. (2006) Mediterranean Climate Variability, Elsevier
    """
    t_media_clima = {
        1: 7.5,  2: 8.2,  3: 10.8, 4: 13.8,
        5: 17.8, 6: 21.5, 7: 24.2, 8: 24.0,
        9: 20.5, 10: 16.2, 11: 11.8, 12: 8.5
    }
    t_norma = t_media_clima.get(mese, 15.0)
    anomalia = temp - t_norma
    spread = temp - dew_point
    p_stazione = pressione_msl * (1 - 0.0065 * ELEVATION / 288.15) ** 5.2561
    try:
        T_K = temp + 273.15
        Td_K = dew_point + 273.15
        e_vapor = 6.112 * math.exp(17.67 * dew_point / (dew_point + 243.5))
        r = 0.622 * e_vapor / (p_stazione - e_vapor)
        T_LCL = 1.0 / (1.0 / (Td_K - 56) + math.log(T_K / Td_K) / 800.0) + 56.0
        theta_e = (T_K
                   * (1000.0 / p_stazione) ** (0.2854 * (1 - 0.28 * r))
                   * math.exp(r * (1 + 0.81 * r) * (3376.0 / T_LCL - 2.54)))
        theta_e_C = theta_e - 273.15
    except (ValueError, ZeroDivisionError, OverflowError):
        theta_e_C = temp + 10  
    if dew_point < -8:
        if spread > 10:
            tipo, nome, emoji = "cA", "Continentale Artica", "🧊"
            desc = "Aria gelida e secca di origine artico-continentale"
        else:
            tipo, nome, emoji = "mA", "Marittima Artica", "🏔️"
            desc = "Aria gelida di origine artica, moderata dal transito marittimo"
    elif dew_point < 0:
        if spread > 8:
            tipo, nome, emoji = "cP", "Continentale Polare", "❄️"
            desc = "Aria fredda e secca di origine continentale (Est Europa/Russia)"
        else:
            tipo, nome, emoji = "mP", "Marittima Polare", "🌊"
            desc = "Aria fredda e umida dall'Atlantico settentrionale"
    elif dew_point < 8:
        if spread > 15:
            tipo, nome, emoji = "cT", "Continentale Tropicale", "🏜️"
            desc = "Aria calda e secca di origine sahariana/nordafricana"
        elif spread > 10:
            tipo, nome, emoji = "cP", "Continentale Polare modificata", "🌥️"
            desc = "Massa polare continentale in fase di riscaldamento"
        elif anomalia < -2:
            tipo, nome, emoji = "mP", "Marittima Polare", "🌊"
            desc = "Aria fresca e umida di origine atlantica"
        else:
            tipo, nome, emoji = "mP/mTr", "Polare in transizione", "🌤️"
            desc = "Massa polare in riscaldamento sul Mediterraneo"
    elif dew_point < 15:
        if spread > 15:
            tipo, nome, emoji = "cT", "Continentale Tropicale", "🏜️"
            desc = "Aria calda e secca di origine sahariana/nordafricana"
        elif spread > 8 and anomalia > 3:
            tipo, nome, emoji = "cT/mT", "Subtropicale secca", "☀️"
            desc = "Massa d'aria subtropicale relativamente secca"
        elif anomalia > 2:
            tipo, nome, emoji = "mT/mTr", "Subtropicale marittima", "⛅"
            desc = "Aria tiepida subtropicale, attenuata dal Mediterraneo"
        else:
            tipo, nome, emoji = "mTr", "Marittima Mediterranea", "🌤️"
            desc = "Aria temperata stazionaria sul bacino mediterraneo"
    elif dew_point < 20:
        if spread > 15:
            tipo, nome, emoji = "cT", "Continentale Tropicale", "🏜️"
            desc = "Aria calda e secca di origine sahariana/nordafricana"
        elif spread > 10:
            tipo, nome, emoji = "cT/mT", "Tropicale mista", "🌅"
            desc = "Massa tropicale con componente continentale"
        else:
            tipo, nome, emoji = "mT", "Marittima Tropicale", "🌴"
            desc = "Aria calda e umida dal Mediterraneo meridionale o subtropicale"
    else:
        if spread > 15:
            tipo, nome, emoji = "cT", "Continentale Tropicale", "🏜️"
            desc = "Aria molto calda e secca di origine sahariana"
        elif spread > 10:
            tipo, nome, emoji = "cT/mT", "Tropicale mista", "🌅"
            desc = "Massa tropicale con componente continentale"
        else:
            tipo, nome, emoji = "mT", "Marittima Tropicale", "🌴"
            desc = "Aria calda e umida dal Mediterraneo meridionale o subtropicale"
    return {
        "tipo": tipo, "nome": nome, "emoji": emoji, "desc": desc,
        "theta_e": round(theta_e_C, 1),
        "anomalia": round(anomalia, 1),
        "spread": round(spread, 1)
    }
def calcola_theta_e_850hpa(data_openmeteo):
    """Calcola la theta-e a 850 hPa usando i dati del modello Open-Meteo.
    Questo è il parametro corretto per la classificazione della massa d'aria,
    perché a 850 hPa non viene influenzato dal riscaldamento solare superficiale (diabatico).
    Args:
        data_openmeteo: dizionario con dati Open-Meteo inclusi i livelli di pressione
    Returns:
        theta_e_850 in °C, o None se i dati non sono disponibili
    """
    try:
        hourly = data_openmeteo.get("hourly", {})
        if not hourly:
            return None
        current_hour_idx = 0
        if "time" in hourly:
            from datetime import timezone as _tz
            now_utc = datetime.now(_tz.utc)
            now_hour_str = now_utc.strftime("%Y-%m-%dT%H:")
            for i, time_str in enumerate(hourly["time"]):
                if time_str.startswith(now_hour_str):
                    current_hour_idx = i
                    break
        key_temp_850 = "temperature_850hPa"
        key_rh_850 = "relative_humidity_850hPa"
        if key_temp_850 not in hourly or key_rh_850 not in hourly:
            print("⚠️  Dati 850 hPa non disponibili in Open-Meteo")
            return None
        if len(hourly[key_temp_850]) <= current_hour_idx or len(hourly[key_rh_850]) <= current_hour_idx:
            print("⚠️  Indice ora corrente fuori range per dati 850 hPa")
            return None
        T_850_C = hourly[key_temp_850][current_hour_idx]
        RH_850 = hourly[key_rh_850][current_hour_idx]
        if T_850_C is None or RH_850 is None:
            print("⚠️  Dati 850 hPa null per ora corrente")
            return None
        p_850 = 850.0  
        T_850_K = T_850_C + 273.15
        RH_850_frac = RH_850 / 100.0
        e_sat_850 = 6.112 * math.exp(17.67 * T_850_C / (T_850_C + 243.5))
        e_850 = e_sat_850 * RH_850_frac
        r_850 = 0.622 * e_850 / (p_850 - e_850)
        if e_850 > 0.01:
            Td_850_C = 243.5 * math.log(e_850 / 6.112) / (17.67 - math.log(e_850 / 6.112))
        else:
            Td_850_C = T_850_C - 20  
        Td_850_K = Td_850_C + 273.15
        T_LCL = 1.0 / (1.0 / (Td_850_K - 56) + math.log(T_850_K / Td_850_K) / 800.0) + 56.0
        theta_e_850 = (T_850_K
                       * (1000.0 / p_850) ** (0.2854 * (1 - 0.28 * r_850))
                       * math.exp(r_850 * (1 + 0.81 * r_850) * (3376.0 / T_LCL - 2.54)))
        theta_e_850_C = theta_e_850 - 273.15
        print(f"✓ θe a 850 hPa calcolata: {theta_e_850_C:.1f}°C (T_850={T_850_C:.1f}°C, RH_850={RH_850:.0f}%)")
        return round(theta_e_850_C, 1)
    except Exception as e:
        print(f"⚠️  Errore calcolo theta-e 850 hPa: {e}")
        return None

def estrai_temperature_alti_livelli(data_openmeteo):
    try:
        hourly = data_openmeteo.get("hourly", {})
        if not hourly:
            return None
        current_hour_idx = 0
        if "time" in hourly:
            from datetime import timezone as _tz
            now_utc = datetime.now(_tz.utc)
            now_hour_str = now_utc.strftime("%Y-%m-%dT%H:")
            for i, time_str in enumerate(hourly["time"]):
                if time_str.startswith(now_hour_str):
                    current_hour_idx = i
                    break
        key_temp_500 = "temperature_500hPa"
        key_temp_850 = "temperature_850hPa"
        if key_temp_500 not in hourly or key_temp_850 not in hourly:
            print("⚠️  Dati temperatura 500/850 hPa non disponibili")
            return None
        if len(hourly[key_temp_500]) <= current_hour_idx or len(hourly[key_temp_850]) <= current_hour_idx:
            print("⚠️  Indice ora corrente fuori range per temperature alti livelli")
            return None
        T_500_C = hourly[key_temp_500][current_hour_idx]
        T_850_C = hourly[key_temp_850][current_hour_idx]
        if T_500_C is None or T_850_C is None:
            print("⚠️  Temperature 500/850 hPa null per ora corrente")
            return None
        print(f"✓ Temperature alti livelli: T_500={T_500_C:.1f}°C, T_850={T_850_C:.1f}°C")
        return {
            'T_500': round(T_500_C, 1),
            'T_850': round(T_850_C, 1)
        }
    except Exception as e:
        print(f"⚠️  Errore estrazione temperature alti livelli: {e}")
        return None
def valuta_instabilita_convettiva(sbcape, mucape, cin, li_value, bulk_shear, severe_score=0):
    """Valutazione ingredient-based del rischio convettivo su scala 0-12."""
    sbcape_f = float(sbcape or 0)
    mucape_f = float(mucape or 0)
    max_cape = max(sbcape_f, mucape_f)
    cin_abs = abs(float(cin or 0))
    shear = float(bulk_shear or 0)
    li = li_value if isinstance(li_value, (int, float)) else None
    if max_cape < 300:
        cape_score = 0.0
    elif max_cape < 800:
        cape_score = 1.0
    elif max_cape < 1500:
        cape_score = 2.0
    elif max_cape < 2500:
        cape_score = 3.0
    else:
        cape_score = 4.0
    if mucape_f >= 1200 and mucape_f >= 0.9 * max_cape:
        cape_score += 0.5
    if cin_abs > 250:
        cin_score = 0.0
    elif cin_abs > 175:
        cin_score = 0.5
    elif cin_abs >= 25:
        cin_score = 1.5
    else:
        cin_score = 1.0
    if li is None:
        li_score = 0.0
    elif li <= -8:
        li_score = 3.0
    elif li <= -6:
        li_score = 2.2
    elif li <= -4:
        li_score = 1.5
    elif li <= -2:
        li_score = 0.8
    else:
        li_score = 0.0
    if shear < 8:
        shear_score = 0.0
    elif shear < 12:
        shear_score = 1.0
    elif shear < 18:
        shear_score = 2.0
    elif shear < 25:
        shear_score = 3.0
    else:
        shear_score = 3.5
    synergy_score = 0.0
    if max_cape >= 1500 and shear >= 15:
        synergy_score += 1.0
    if li is not None and li <= -5 and cin_abs <= 150:
        synergy_score += 0.8
    if max_cape >= 2500 and shear >= 20 and li is not None and li <= -6:
        synergy_score += 1.2
    score = cape_score + cin_score + li_score + shear_score + synergy_score
    if severe_score:
        score = max(score, min(float(severe_score), 12.0))
    score = round(min(score, 12.0), 1)
    warning = None
    level = "basso"
    event_label = "Instabilità convettiva"
    if score >= 10.5:
        warning = "⚠️⚡ AVVISO: TEMPORALI SEVERI"
        level = "molto_alto"
        event_label = "Temporali severi"
    elif score >= 8.0:
        warning = "⚡ AVVISO: RISCHIO FORTI TEMPORALI"
        level = "alto"
        event_label = "Rischio forti temporali"
    elif score >= 5.5:
        warning = "⛈️ AVVISO: INSTABILITÀ CONVETTIVA MARCATA"
        level = "moderato"
        event_label = "Instabilità convettiva marcata"
    return {
        "score": score, "level": level, "warning": warning,
        "event_label": event_label, "event_trigger": score >= 8.0,
        "max_cape": max_cape, "cin_abs": cin_abs, "li": li, "shear": shear,
    }
def fetch_profile_cached():
    """Scarica profilo verticale da Open-Meteo con cache.
    Usa AROME France (Météo-France, 2.5 km) con fallback best_match."""
    global _API_CACHE
    now = time.time()
    if 'open_meteo' in _API_CACHE and now - _API_CACHE['open_meteo_time'] < _CACHE_DURATION:
        print(f"✓ Usando cache Open-Meteo (età: {int(now - _API_CACHE['open_meteo_time'])}s)")
        return _API_CACHE['open_meteo']
    url = "https://api.open-meteo.com/v1/forecast"
    pressure_levels_temp = [
        "temperature_1000hPa", "temperature_950hPa", "temperature_925hPa",
        "temperature_900hPa", "temperature_850hPa", "temperature_800hPa",
        "temperature_750hPa", "temperature_700hPa", "temperature_650hPa",
        "temperature_600hPa", "temperature_550hPa", "temperature_500hPa",
        "temperature_400hPa", "temperature_300hPa", "temperature_200hPa"
    ]
    pressure_levels_rh = [
        "relative_humidity_1000hPa", "relative_humidity_950hPa", "relative_humidity_925hPa",
        "relative_humidity_900hPa", "relative_humidity_850hPa", "relative_humidity_800hPa",
        "relative_humidity_750hPa", "relative_humidity_700hPa", "relative_humidity_650hPa",
        "relative_humidity_600hPa", "relative_humidity_550hPa", "relative_humidity_500hPa"
    ]
    pressure_levels_wind = ["windspeed_10m", "windspeed_80m", "windspeed_120m"]
    hourly_vars = ",".join(pressure_levels_temp + pressure_levels_rh + pressure_levels_wind) + ",dew_point_2m,relative_humidity_2m"
    base_params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "temperature_2m,relative_humidity_2m,pressure_msl,dew_point_2m,windspeed_10m,winddirection_10m,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high",
        "hourly": hourly_vars,
        "timezone": "UTC"
    }
    try:
        params_arome = {**base_params, "models": "meteofrance_arome_france"}
        r = requests.get(url, params=params_arome, timeout=15)
        r.raise_for_status()
        data = r.json()
        hourly = data.get("hourly", {})
        test_key = "temperature_850hPa"
        if test_key in hourly and any(v is not None for v in hourly[test_key]):
            data['_model_used'] = 'AROME France (2.5km)'
            _API_CACHE['open_meteo'] = data
            _API_CACHE['open_meteo_time'] = now
            print("✓ Fetch Open-Meteo riuscito - modello AROME France (2.5km)")
            return data
        else:
            print("⚠️  AROME France ha restituito dati vuoti, passo al fallback")
    except Exception as e:
        print(f"⚠️  AROME France non disponibile ({e}), passo al fallback")
    try:
        r = requests.get(url, params=base_params, timeout=15)
        r.raise_for_status()
        data = r.json()
        data['_model_used'] = 'best_match (fallback)'
        _API_CACHE['open_meteo'] = data
        _API_CACHE['open_meteo_time'] = now
        print("✓ Fetch Open-Meteo riuscito - modello default (best_match)")
        return data
    except Exception as e:
        print(f"Errore fetch Open-Meteo: {e}")
        return None
def vapor_pressure(T_celsius):
    """Pressione di vapore saturo (hPa) — Bolton (1980)."""
    return 6.112 * np.exp(17.67 * T_celsius / (T_celsius + 243.5))
def mixing_ratio(e, p):
    """Rapporto di miscelanza (kg/kg) da pressione di vapore e pressione totale."""
    return _EPSILON * e / (p - e)
def virtual_temperature(T_kelvin, q):
    """Temperatura virtuale (K) da temperatura e rapporto di miscelanza."""
    return T_kelvin * (1 + q / _EPSILON) / (1 + q)
def dewpoint_to_mixing_ratio(Td_celsius, p_hPa):
    """Rapporto di miscelanza dal punto di rugiada."""
    es = vapor_pressure(Td_celsius)
    return mixing_ratio(es, p_hPa)
def lcl_pressure(T_kelvin, Td_kelvin, p_hPa):
    """Pressione al LCL (hPa) — approssimazione di Bolton."""
    Tl = 1 / (1 / (Td_kelvin - 56) + np.log(T_kelvin / Td_kelvin) / 800) + 56
    theta = T_kelvin * (1000 / p_hPa) ** (_RD / _CP)
    return 1000 * (Tl / theta) ** (_CP / _RD)
def moist_adiabatic_lapse_rate(T_kelvin, p_hPa):
    """Lapse rate adiabatico saturo (K/Pa)."""
    es = vapor_pressure(T_kelvin - 273.15)
    ws = mixing_ratio(es, p_hPa)
    numerator = 1 + _LV * ws / (_RD * T_kelvin)
    denominator = 1 + _EPSILON * _LV * _LV * ws / (_CP * _RD * T_kelvin * T_kelvin)
    return (_RD * T_kelvin / (_CP * p_hPa)) * (numerator / denominator)
def lift_parcel(T_start_K, p_start_hPa, q_start, p_levels_hPa):
    """Solleva una particella (secca fino al LCL, satura oltre).
    Restituisce (T_parcel[], p_lcl)."""
    T_parcel = np.zeros(len(p_levels_hPa))
    T_parcel[0] = T_start_K
    es_start = vapor_pressure(T_start_K - 273.15)
    e_start = q_start * p_start_hPa / (_EPSILON + q_start)
    e_start = min(e_start, es_start)
    if e_start > 0:
        Td_start = 243.5 * np.log(e_start / 6.112) / (17.67 - np.log(e_start / 6.112))
        p_lcl = lcl_pressure(T_start_K, Td_start + 273.15, p_start_hPa)
    else:
        p_lcl = p_start_hPa / 2
    for i in range(1, len(p_levels_hPa)):
        p_lower = p_levels_hPa[i - 1]
        p_upper = p_levels_hPa[i]
        if p_lower >= p_lcl and p_upper >= p_lcl:
            T_parcel[i] = T_parcel[i - 1] * (p_upper / p_lower) ** (_RD / _CP)
        elif p_lower >= p_lcl and p_upper < p_lcl:
            T_at_lcl = T_parcel[i - 1] * (p_lcl / p_lower) ** (_RD / _CP)
            n_steps = 10
            p_range = np.linspace(p_lcl, p_upper, n_steps)
            T_temp = T_at_lcl
            for j in range(1, n_steps):
                dp = p_range[j] - p_range[j - 1]
                dT_dp = moist_adiabatic_lapse_rate(T_temp, p_range[j - 1])
                T_temp = T_temp + dT_dp * dp
            T_parcel[i] = T_temp
        else:
            n_steps = 5
            p_range = np.linspace(p_lower, p_upper, n_steps)
            T_temp = T_parcel[i - 1]
            for j in range(1, n_steps):
                dp = p_range[j] - p_range[j - 1]
                dT_dp = moist_adiabatic_lapse_rate(T_temp, p_range[j - 1])
                T_temp = T_temp + dT_dp * dp
            T_parcel[i] = T_temp
    return T_parcel, p_lcl
def calcola_cape_from_profile(T_parcel, p_env, T_env, RH_env, q_parcel_surface, p_lcl):
    """Calcola CAPE e CIN da profili di temperatura e umidità."""
    Tv_env = np.zeros(len(p_env))
    Tv_parcel = np.zeros(len(p_env))
    for i in range(len(p_env)):
        es_env = vapor_pressure(T_env[i] - 273.15)
        e_env = es_env * RH_env[i]
        q_env = mixing_ratio(e_env, p_env[i])
        Tv_env[i] = virtual_temperature(T_env[i], q_env)
        if p_env[i] <= p_lcl:
            es_parcel = vapor_pressure(T_parcel[i] - 273.15)
            q_parcel = mixing_ratio(es_parcel, p_env[i])
        else:
            q_parcel = q_parcel_surface
        Tv_parcel[i] = virtual_temperature(T_parcel[i], q_parcel)
    buoyancy = Tv_parcel - Tv_env
    lcl_idx = 0
    for i in range(len(p_env)):
        if p_env[i] <= p_lcl:
            lcl_idx = i
            break
    lfc_idx = None
    for i in range(max(1, lcl_idx), len(buoyancy)):
        if buoyancy[i] > 0 and buoyancy[i - 1] <= 0:
            lfc_idx = i
            break
    el_idx = None
    if lfc_idx is not None:
        for i in range(lfc_idx + 1, len(buoyancy)):
            if buoyancy[i] < 0:
                el_idx = i
                break
        if el_idx is None:
            el_idx = len(buoyancy) - 1
    cin = 0.0
    cape = 0.0
    if lfc_idx is not None:
        for i in range(1, lfc_idx):
            if buoyancy[i] < 0:
                Tv_avg = (Tv_env[i] + Tv_env[i - 1]) / 2
                dz = (_RD * Tv_avg / _G) * np.log(p_env[i - 1] / p_env[i])
                buoy_avg = (buoyancy[i] + buoyancy[i - 1]) / 2
                cin += _G * (buoy_avg / Tv_avg) * dz
        for i in range(lfc_idx + 1, el_idx + 1):
            if buoyancy[i] > 0 or buoyancy[i - 1] > 0:
                Tv_avg = (Tv_env[i] + Tv_env[i - 1]) / 2
                dz = (_RD * Tv_avg / _G) * np.log(p_env[i - 1] / p_env[i])
                buoy_avg = (buoyancy[i] + buoyancy[i - 1]) / 2
                if buoy_avg > 0:
                    cape += _G * (buoy_avg / Tv_avg) * dz
    return {
        'sbcape': cape, 'cin': cin,
        'lfc_idx': lfc_idx, 'el_idx': el_idx,
        'lfc_pressure': p_env[lfc_idx] if lfc_idx is not None else None,
        'el_pressure': p_env[el_idx] if el_idx is not None else None,
        'buoyancy': buoyancy
    }
def calcola_mucape(data, station_data, T_env, p_env, RH_env):
    """Calcola Most Unstable CAPE (MUCAPE) cercando la particella più instabile
    nei primi 300 hPa dalla superficie."""
    if station_data is None:
        return None
    p_surface = station_data['pressure']
    max_cape = 0
    mu_result = None
    for p_idx in range(len(p_env)):
        if p_env[p_idx] < p_surface - 300:
            break
        T_test = T_env[p_idx]
        RH_test = RH_env[p_idx]
        p_test = p_env[p_idx]
        es_test = vapor_pressure(T_test - 273.15)
        e_test = es_test * RH_test
        q_test = mixing_ratio(e_test, p_test)
        p_levels_above = p_env[p_idx:]
        T_levels_above = T_env[p_idx:]
        RH_levels_above = RH_env[p_idx:]
        T_parcel_mu, p_lcl_mu = lift_parcel(T_test, p_test, q_test, p_levels_above)
        result_mu = calcola_cape_from_profile(T_parcel_mu, p_levels_above, T_levels_above, RH_levels_above, q_test, p_lcl_mu)
        if result_mu['sbcape'] > max_cape:
            max_cape = result_mu['sbcape']
            mu_result = result_mu
            mu_result['mu_level'] = p_test
    return mu_result
def calcola_wind_shear(data, current_hour_idx, station_data):
    """Proxy wind shear 0-6 km (10 m → 120 m). Fortemente sottostimato."""
    try:
        hourly = data.get("hourly", {})
        if station_data and 'wind_speed' in station_data:
            u_surface = station_data['wind_speed'] / 3.6
        else:
            u_surface = hourly.get('windspeed_10m', [0])[current_hour_idx] / 3.6 if 'windspeed_10m' in hourly else 0
        u_120m = hourly.get('windspeed_120m', [0])[current_hour_idx] / 3.6 if 'windspeed_120m' in hourly else 0
        shear = abs(u_120m - u_surface)
        return {'surface_wind': u_surface, 'upper_wind': u_120m, 'bulk_shear': shear}
    except Exception:
        return None
def _validate_sbcape_results(results, T_surface_C):
    """Validazione fisica dei risultati SBCAPE."""
    warnings = []
    if results['sbcape'] > 6000:
        warnings.append(f"⚠️  SBCAPE molto elevato ({results['sbcape']:.0f} J/kg) - verifica dati")
    if results['sbcape'] > 1500 and T_surface_C < 10:
        warnings.append(f"⚠️  CAPE elevato con T bassa ({T_surface_C:.1f}°C) - situazione insolita")
    if results['cin'] < -500:
        warnings.append(f"⚠️  CIN molto forte ({results['cin']:.0f} J/kg) - convezione fortemente inibita")
    return warnings
def calcola_sbcape_advanced(data, station_data=None):
    """Calcola SBCAPE, MUCAPE, CIN e parametri convettivi avanzati.
    Profilo umidità reale, interpolazione cubica, MUCAPE, wind shear."""
    if not data:
        print("Errore: dati invalidi")
        return None
    try:
        hourly = data.get("hourly", {})
        current_hour_idx = 0
        if "time" in hourly:
            from datetime import timezone as _tz
            now_utc = datetime.now(_tz.utc)
            now_hour_str = now_utc.strftime("%Y-%m-%dT%H:")
            for i, time_str in enumerate(hourly["time"]):
                if time_str.startswith(now_hour_str):
                    current_hour_idx = i
                    break
        print(f"  Usando dati dell'ora: {hourly['time'][current_hour_idx] if 'time' in hourly else 'N/A'} (indice {current_hour_idx})")
        test_key = "temperature_850hPa"
        if (test_key in hourly and hourly[test_key] and
                len(hourly[test_key]) > current_hour_idx and
                hourly[test_key][current_hour_idx] is None):
            original_idx = current_hour_idx
            for idx in range(current_hour_idx, -1, -1):
                if hourly[test_key][idx] is not None:
                    current_hour_idx = idx
                    break
            if current_hour_idx != original_idx:
                print(f"  ⚠️  Ora {original_idx} ha dati null, uso ora {current_hour_idx} ({hourly['time'][current_hour_idx]})")
        if station_data:
            print("  → Usando dati REALI dalla stazione meteo (T, Td, P, RH)")
            T_surface_C = station_data['temperature']
            Td_surface_C = station_data['dewpoint']
            p_surface = station_data['pressure']
            RH_surface = station_data['humidity'] / 100
            data_source = "Stazione Ecowitt (reale)"
        else:
            print("  → Usando dati modello Open-Meteo (fallback)")
            current = data.get("current", {})
            T_surface_C = current.get("temperature_2m")
            RH_surface = current.get("relative_humidity_2m", 50) / 100
            Td_surface_C = current.get("dew_point_2m")
            p_msl = current.get("pressure_msl", 1013.25)
            if T_surface_C is None:
                print("Errore: dati di superficie mancanti")
                return None
            T_surface_K = T_surface_C + 273.15
            p_surface = p_msl * ((1 - 0.0065 * ELEVATION / T_surface_K) ** 5.255)
            data_source = "Open-Meteo (modello)"
        T_surface_K = T_surface_C + 273.15
        if Td_surface_C is not None:
            q_surface = dewpoint_to_mixing_ratio(Td_surface_C, p_surface)
        else:
            es_surface = vapor_pressure(T_surface_C)
            e_surface = es_surface * RH_surface
            q_surface = mixing_ratio(e_surface, p_surface)
        pressure_levels = [1000, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500]
        T_env_list = [T_surface_K]
        p_env_list = [p_surface]
        RH_env_list = [RH_surface]
        for p_level in pressure_levels:
            key_temp = f"temperature_{p_level}hPa"
            key_rh = f"relative_humidity_{p_level}hPa"
            if (key_temp in hourly and hourly[key_temp] and
                    len(hourly[key_temp]) > current_hour_idx and p_level <= p_surface):
                T_val = hourly[key_temp][current_hour_idx]
                if key_rh in hourly and hourly[key_rh] and len(hourly[key_rh]) > current_hour_idx:
                    RH_val = hourly[key_rh][current_hour_idx] / 100
                else:
                    RH_val = 0.5 if p_level > 500 else 0.3
                if T_val is not None:
                    p_env_list.append(p_level)
                    T_env_list.append(T_val + 273.15)
                    RH_env_list.append(RH_val)
        if len(p_env_list) < 3:
            print("Errore: profilo verticale insufficiente")
            return None
        p_env = np.array(p_env_list)
        T_env = np.array(T_env_list)
        RH_env = np.array(RH_env_list)
        sort_idx = np.argsort(p_env)[::-1]
        p_env = p_env[sort_idx]
        T_env = T_env[sort_idx]
        RH_env = RH_env[sort_idx]
        p_min = max(200, p_env[-1])
        p_fine = np.arange(p_surface, p_min, -10)
        if len(p_env) >= 4:
            T_interp_func = interp1d(p_env, T_env, kind='cubic', fill_value='extrapolate')
            RH_interp_func = interp1d(p_env, RH_env, kind='linear', fill_value='extrapolate', bounds_error=False)
            T_fine = T_interp_func(p_fine)
            RH_fine = RH_interp_func(p_fine)
            RH_fine = np.clip(RH_fine, 0.05, 1.0)
            print(f"  Interpolazione: {len(p_env)} livelli → {len(p_fine)} livelli (10 hPa)")
        else:
            T_fine = T_env
            RH_fine = RH_env
            p_fine = p_env
        Td_display = f"{Td_surface_C:.1f}" if Td_surface_C is not None else "N/A"
        print(f"  Sollevamento particella: T={T_surface_C:.1f}°C, Td={Td_display}°C, p={p_surface:.1f}hPa, RH={RH_surface*100:.0f}%")
        T_parcel_sb, p_lcl_sb = lift_parcel(T_surface_K, p_surface, q_surface, p_fine)
        result_sb = calcola_cape_from_profile(T_parcel_sb, p_fine, T_fine, RH_fine, q_surface, p_lcl_sb)
        print("  Cercando livello più instabile (MUCAPE)...")
        result_mu = calcola_mucape(data, station_data, T_fine, p_fine, RH_fine)
        shear = calcola_wind_shear(data, current_hour_idx, station_data)
        idx_500 = None
        for i, p in enumerate(p_fine):
            if abs(p - 500) < 15:
                idx_500 = i
                break
        li = (T_fine[idx_500] - T_parcel_sb[idx_500]) if idx_500 is not None else 0
        print(f"  LCL: {p_lcl_sb:.1f} hPa")
        if result_sb['lfc_pressure']:
            print(f"  LFC: {result_sb['lfc_pressure']:.1f} hPa")
            print(f"  EL: {result_sb['el_pressure']:.1f} hPa" if result_sb['el_pressure'] else "  EL: top atmosfera")
        else:
            print("  LFC: non trovato (atmosfera stabile)")
        if result_mu and result_mu['sbcape'] > result_sb['sbcape']:
            print(f"  MUCAPE: {result_mu['sbcape']:.0f} J/kg (livello {result_mu['mu_level']:.0f} hPa)")
        results = {
            "sbcape": round(float(max(0, result_sb['sbcape'])), 2),
            "mucape": round(float(max(0, result_mu['sbcape'])), 2) if result_mu else None,
            "mu_level": round(float(result_mu['mu_level']), 1) if result_mu else None,
            "cin": round(float(result_sb['cin']), 2),
            "lifted_index": round(float(li), 2),
            "lcl_pressure": round(float(p_lcl_sb), 1),
            "lfc_pressure": round(float(result_sb['lfc_pressure']), 1) if result_sb['lfc_pressure'] else None,
            "el_pressure": round(float(result_sb['el_pressure']), 1) if result_sb['el_pressure'] else None,
            "bulk_shear": round(float(shear['bulk_shear']), 1) if shear else None,
            "timestamp": datetime.now().isoformat(),
            "location": f"La Spezia ({LATITUDE}, {LONGITUDE}) - {ELEVATION}m",
            "unit": "J/kg",
            "calculation_method": "Advanced thermodynamic integration v2.0",
            "data_source": data_source,
            "profile_model": data.get("_model_used", "best_match"),
            "parameters": {
                "temperature_surface": round(float(T_surface_C), 1),
                "dewpoint_surface": round(float(Td_surface_C), 1) if Td_surface_C else None,
                "rh_surface": round(float(RH_surface * 100), 0),
                "pressure_surface": round(float(p_surface), 1),
                "mixing_ratio_surface": round(float(q_surface * 1000), 2),
                "profile_levels": int(len(p_fine)),
                "interpolated": len(p_fine) > len(p_env)
            }
        }
        warnings = _validate_sbcape_results(results, T_surface_C)
        if warnings:
            results['warnings'] = warnings
            for w in warnings:
                print(w)
        return results
    except Exception as e:
        print(f"Errore calcolo SBCAPE: {e}")
        traceback.print_exc()
        return None
def calcola_severe_score(results):
    """Severe Weather Score combinando multipli parametri (score custom 0-12)."""
    score = 0
    reasons = []
    sbcape = results.get('sbcape', 0)
    mucape = results.get('mucape', 0)
    cin = abs(results.get('cin', 0))
    shear = results.get('bulk_shear', 0)
    max_cape = max(sbcape, mucape) if mucape else sbcape
    if max_cape > 3000:
        score += 4; reasons.append(f"CAPE estremo ({max_cape:.0f} J/kg)")
    elif max_cape > 2500:
        score += 3; reasons.append(f"CAPE molto forte ({max_cape:.0f} J/kg)")
    elif max_cape > 1500:
        score += 2; reasons.append(f"CAPE forte ({max_cape:.0f} J/kg)")
    elif max_cape > 1000:
        score += 1; reasons.append(f"CAPE moderato ({max_cape:.0f} J/kg)")
    if cin < 50:
        score += 2; reasons.append("CAP debole/assente")
    elif cin < 100:
        score += 1; reasons.append("CAP moderato")
    if shear and shear > 15:
        score += 3; reasons.append(f"Shear elevato ({shear:.1f} m/s)")
    elif shear and shear > 10:
        score += 2; reasons.append(f"Shear moderato ({shear:.1f} m/s)")
    if score >= 7:
        level = "⚡🌪️ ALLERTA MASSIMA: RISCHIO SUPERCELLE/TORNADO"
    elif score >= 5:
        level = "⚡ ALLERTA: TEMPORALI SEVERI PROBABILI"
    elif score >= 3:
        level = "⚡ AVVISO: TEMPORALI FORTI POSSIBILI"
    else:
        level = None
    return {'score': score, 'level': level, 'reasons': reasons}
def calcola_e_salva_sbcape():
    """Entry-point standalone: calcola SBCAPE e salva su state.json [sbcape]."""
    print("=" * 70)
    print("📊 CALCOLO AVANZATO SBCAPE/MUCAPE & PARAMETRI CONVETTIVI v2.0")
    print("=" * 70)
    print(f"Coordinate: {LATITUDE}°N, {LONGITUDE}°E")
    print(f"Elevazione: {ELEVATION} m s.l.m.")
    print()
    print("📡 Lettura dati dalla stazione Ecowitt Wittboy (con retry)...")
    station_data = fetch_ecowitt_data()
    if not station_data:
        print("⚠️  Stazione non disponibile, userò dati modello come fallback")
    print("⏳ Scaricando profilo verticale da Open-Meteo (con cache)...")
    data = fetch_profile_cached()
    if not data:
        print("✗ Errore nel fetching dei dati")
        return
    print("⚙️  Calcolando SBCAPE, MUCAPE, CIN e parametri convettivi...")
    risultato = calcola_sbcape_advanced(data, station_data)
    if not risultato:
        print("✗ Errore nel calcolo")
        return
    severe = calcola_severe_score(risultato)
    risultato['severe_score'] = severe['score']
    if severe['level']:
        risultato['severe_warning'] = severe['level']
        risultato['severe_reasons'] = severe['reasons']
    print()
    print(f"SBCAPE: {risultato['sbcape']:.1f} J/kg")
    if risultato.get('mucape'):
        print(f"MUCAPE: {risultato['mucape']:.1f} J/kg (livello {risultato['mu_level']:.0f} hPa)")
    print(f"CIN:    {risultato['cin']:.1f} J/kg")
    print(f"LI:     {risultato['lifted_index']:.1f} °C")
    if risultato.get('bulk_shear'):
        print(f"Shear:  {risultato['bulk_shear']:.1f} m/s")
    if severe['level']:
        print(f"\n{severe['level']}")
        print(f"Severe Score: {severe['score']}/12")
        for reason in severe['reasons']:
            print(f"  • {reason}")
    save_state_section('sbcape', risultato)
    print(f"\n✓ Risultati salvati in state.json [sbcape]")
    print("=" * 70)
def _ecowitt_val(section, key, default=0.0):
    """Estrae un valore numerico dalla risposta Ecowitt API v3."""
    try:
        return float(section.get(key, {}).get("value", default))
    except (TypeError, ValueError, AttributeError):
        return float(default)
def calc_heat_index(temp_c, humidity):
    """Calcola l'Heat Index (NWS / Rothfusz regression). Restituisce °C."""
    if temp_c < 27:
        return temp_c
    T = temp_c * 9.0 / 5.0 + 32.0
    RH = float(humidity)
    HI = (-42.379
           + 2.04901523 * T
           + 10.14333127 * RH
           - 0.22475541 * T * RH
           - 6.83783e-3 * T ** 2
           - 5.481717e-2 * RH ** 2
           + 1.22874e-3 * T ** 2 * RH
           + 8.5282e-4 * T * RH ** 2
           - 1.99e-6 * T ** 2 * RH ** 2)
    return round((HI - 32.0) * 5.0 / 9.0, 1)
def calc_wind_chill(temp_c, wind_kmh):
    """Calcola il Wind Chill (NWS). Applicabile sotto 10°C e vento > 4.8 km/h."""
    if temp_c > 10 or wind_kmh < 4.8:
        return temp_c
    WC = (13.12
          + 0.6215 * temp_c
          - 11.37 * wind_kmh ** 0.16
          + 0.3965 * temp_c * wind_kmh ** 0.16)
    return round(WC, 1)
def fetch_ecowitt_hourly_max_gust():
    """Recupera la raffica massima registrata dalla Ecowitt nell'ultima ora.
    Usa l'API v3 history con intervallo di 1 ora.
    L'endpoint history restituisce il valore MAX di wind_gust nel periodo.
    Restituisce il valore in km/h oppure None se non disponibile.
    """
    if not ECOWITT_APPLICATION_KEY or not ECOWITT_API_KEY or not ECOWITT_MAC:
        return None
    now_utc = datetime.now(timezone.utc)
    end_date = now_utc.strftime("%Y-%m-%d%%20%H:%M:%S")
    start_date = (now_utc - timedelta(hours=1)).strftime("%Y-%m-%d%%20%H:%M:%S")
    url = "https://api.ecowitt.net/api/v3/device/history"
    params = {
        "application_key": ECOWITT_APPLICATION_KEY,
        "api_key": ECOWITT_API_KEY,
        "mac": ECOWITT_MAC,
        "start_date": start_date,
        "end_date": end_date,
        "call_back": "wind",
        "cycle_type": "auto",
        "wind_speed_unitid": 6,  
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        resp = r.json()
    except Exception as e:
        print(f"⚠️  Errore fetch history Ecowitt (raffica max 1h): {e}")
        return None
    if resp.get("code") != 0:
        print(f"⚠️  Errore Ecowitt history API: {resp.get('msg', 'sconosciuto')}")
        return None
    try:
        wind_data = resp.get("data", {}).get("wind", {})
        gust_list = wind_data.get("wind_gust", {}).get("list", {})
        if not gust_list:
            print("⚠️  History Ecowitt: nessun dato wind_gust nell'ultima ora")
            return None
        max_gust = max(float(v) for v in gust_list.values())
        print(f"✓ Raffica max oraria Ecowitt (history): {max_gust} km/h")
        return round(max_gust, 1)
    except Exception as e:
        print(f"⚠️  Errore parsing history Ecowitt wind_gust: {e}")
        return None
def fetch_ecowitt_data(max_retries=3):
    """Legge i dati in tempo reale dalla stazione Ecowitt Wittboy.
    Usa l'API v3 di Ecowitt (https://api.ecowitt.net/api/v3/device/real_time).
    Restituisce un dizionario con campi normalizzati oppure None.
    """
    if not ECOWITT_APPLICATION_KEY or not ECOWITT_API_KEY or not ECOWITT_MAC:
        print("✗ ECOWITT non configurato: provo fallback stazione esterna WMO")
        return None
    url = "https://api.ecowitt.net/api/v3/device/real_time"
    params = {
        "application_key": ECOWITT_APPLICATION_KEY,
        "api_key": ECOWITT_API_KEY,
        "mac": ECOWITT_MAC,
        "call_back": "all",
        "temp_unitid": 1,       
        "pressure_unitid": 3,   
        "wind_speed_unitid": 6, 
        "rainfall_unitid": 12,  
    }
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            resp = r.json()
        except Exception as e:
            print(f"✗ Errore connessione Ecowitt (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
        if resp.get("code") != 0:
            print(f"✗ Errore Ecowitt API (attempt {attempt + 1}): {resp.get('msg', 'sconosciuto')}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
        data = resp.get("data", {})
        outdoor = data.get("outdoor", {})
        wind = data.get("wind", {})
        pressure = data.get("pressure", {})
        rainfall = data.get("rainfall", {})
        solar = data.get("solar_and_uvi", {})
        temp = _ecowitt_val(outdoor, "temperature")
        humidity = int(_ecowitt_val(outdoor, "humidity"))
        dew_point = _ecowitt_val(outdoor, "dew_point")
        feels_like = _ecowitt_val(outdoor, "feels_like", temp)
        pressure_abs = _ecowitt_val(pressure, "absolute", 1013.0)
        wind_speed = _ecowitt_val(wind, "wind_speed")
        wind_gust = _ecowitt_val(wind, "wind_gust")
        rain_rate = _ecowitt_val(rainfall, "rain_rate") * ECOWITT_RAIN_RATE_CALIBRATION
        rain_hourly = _ecowitt_val(rainfall, "hourly") * ECOWITT_RAIN_CALIBRATION
        rain_daily = _ecowitt_val(rainfall, "daily") * ECOWITT_RAIN_CALIBRATION
        uv_index = int(_ecowitt_val(solar, "uvi"))
        if (temp < -50 or temp > 60
                or humidity < 0 or humidity > 100
                or pressure_abs < 900 or pressure_abs > 1100):
            print(f"⚠️  Dati Ecowitt anomali (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
        heat_index = calc_heat_index(temp, humidity)
        wind_chill_val = calc_wind_chill(temp, wind_speed)
        result = {
            'temperature': round(temp, 1),
            'humidity': humidity,
            'dewpoint': round(dew_point, 1),
            'feels_like': round(feels_like, 1),
            'heat_index': round(heat_index, 1),
            'wind_chill': round(wind_chill_val, 1),
            'pressure': int(round(pressure_abs)),
            'wind_speed': round(wind_speed, 1),
            'wind_gust': round(wind_gust, 1),
            'rain_rate': round(rain_rate, 1),
            'rain_1h': round(rain_hourly, 1),
            'rain_24h': round(rain_daily, 1),
            'uv_index': uv_index,
            'battery': 100,
        }
        print(
            f"✓ Dati Ecowitt Wittboy ricevuti: "
            f"T={result['temperature']:.1f}°C, "
            f"Td={result['dewpoint']:.1f}°C, "
            f"P={result['pressure']}hPa, "
            f"RH={result['humidity']}%, "
            f"Wind={result['wind_speed']} km/h, "
            f"Gust={result['wind_gust']} km/h"
        )
        return result
    print("⚠️  Ecowitt non disponibile dopo i retry, provo fallback stazione esterna WMO")
    return None
def _build_ecowitt_dict_from_external(station):
    """Converte i dati WMO fallback nel formato Ecowitt normalizzato."""
    temp = station.get('temperature', 0) or 0
    humidity = int(station.get('humidity', 0) or 0)
    return {
        'temperature': round(temp, 1),
        'humidity': humidity,
        'dewpoint': round(station.get('dewpoint', 0) or 0, 1),
        'feels_like': round(temp, 1),
        'heat_index': round(temp, 1),
        'wind_chill': round(temp, 1),
        'pressure': round(station.get('pressure', 1013.0) or 1013.0, 1),
        'wind_speed': round(station.get('wind_speed', 0) or 0, 1),
        'wind_gust': round(station.get('wind_gust', 0) or 0, 1),
        'rain_rate': 0.0,
        'rain_1h': 0.0,
        'rain_24h': 0.0,
        'uv_index': 0,
        'battery': 0,
    }
def esegui_report(force_send=False, target_chat_id=None):
    """Genera e invia il report meteo.
    Args:
        force_send: Se True, invia sempre ignorando la logica smart.
        target_chat_id: Se fornito, invia solo a questa chat.
    """
    _send_to = [str(target_chat_id)] if target_chat_id else LISTA_CHAT
    source_info_line = ""
    ecowitt = fetch_ecowitt_data()
    if ecowitt is None:
        external_station_data = fetch_wmo_station_data_laspezia()
        if not external_station_data:
            print("✗ Nessun dato disponibile né da Ecowitt né da stazioni WMO esterne")
            return
        ecowitt = _build_ecowitt_dict_from_external(external_station_data)
        source_info_line = (
            "⚠️ *Dati da stazione meteo esterna WMO*\n"
            f"Fonte: {external_station_data.get('station_id')} — {external_station_data.get('station_name')}\n"
        )
    print("DATI GREZZI RICEVUTI:", json.dumps(ecowitt, indent=4))
    now_it = datetime.now(TZ_ROME)
    temp_ext = ecowitt['temperature']
    umid_ext = ecowitt['humidity']
    pressione_locale = ecowitt['pressure']
    v_medio = ecowitt['wind_speed']
    raffica_1h = fetch_ecowitt_hourly_max_gust()
    if raffica_1h is not None:
        raffica = raffica_1h
    else:
        raffica = ecowitt['wind_gust']  
        print(f"⚠️  Uso raffica istantanea Ecowitt (history non disponibile): {raffica} km/h")
    dew_point = ecowitt['dewpoint']
    feel_like = ecowitt['feels_like']
    heat_index = ecowitt['heat_index']
    wind_chill = ecowitt['wind_chill']
    rain_rate = ecowitt.get('rain_rate', 0.0)
    pioggia_1h = ecowitt['rain_1h']
    uv_idx = ecowitt['uv_index']
    batt = ecowitt.get('battery', 0)
    h = ELEVATION  
    Rd = 287.05
    g_val = 9.80665
    T_k = temp_ext + 273.15 if -50 < temp_ext < 60 else 288.15
    pressione_msl = int(round(pressione_locale * math.exp(g_val * h / (Rd * T_k))))
    _storico_tmp = carica_storico()
    _cutoff_24h = now_it - timedelta(hours=24)
    _pioggia_24h_somma = 0.0
    for _s in sorted(_storico_tmp, key=lambda x: x.get("ts", "")):
        _ts_str = _s.get("ts")
        if not _ts_str:
            continue
        try:
            _ts_dt = datetime.fromisoformat(_ts_str)
            if _ts_dt.tzinfo is None:
                _ts_dt = _ts_dt.replace(tzinfo=TZ_ROME)
            if _ts_dt >= _cutoff_24h:
                _p1h = _s.get("pioggia_1h", 0) or 0
                if isinstance(_p1h, (int, float)) and _p1h > 0:
                    _pioggia_24h_somma += _p1h
        except Exception:
            continue
    _pioggia_24h_somma += max(pioggia_1h, 0)
    pioggia_24h = round(_pioggia_24h_somma, 1)
    pioggia_24h_sensore = ecowitt['rain_24h']
    print(f"  Pioggia 24h calcolata: {pioggia_24h} mm (sensore: {pioggia_24h_sensore} mm, somma storico+attuale)")
    mese_corrente = now_it.month
    oggi_str = now_it.strftime("%Y-%m-%d")
    giorno_anno = now_it.timetuple().tm_yday
    LAT = LATITUDE
    lat_rad = (math.pi / 180.0) * LAT
    delta_sol = 0.409 * math.sin((2 * math.pi / 365) * giorno_anno - 1.39)
    dr = 1 + 0.033 * math.cos((2 * math.pi / 365) * giorno_anno)
    ws = math.acos(-math.tan(lat_rad) * math.tan(delta_sol))
    Gsc = 0.0820
    Ra = (24 * 60 / math.pi) * Gsc * dr * (
        ws * math.sin(lat_rad) * math.sin(delta_sol) +
        math.cos(lat_rad) * math.cos(delta_sol) * math.sin(ws)
    )
    dati_salvati = load_state_section('meteo')
    t_min_oggi = dati_salvati.get("t_min_oggi", temp_ext)
    t_max_oggi = dati_salvati.get("t_max_oggi", temp_ext)
    ultima_data_check = dati_salvati.get("data_calcolo", "")
    if ultima_data_check != oggi_str:
        t_min_oggi = temp_ext
        t_max_oggi = temp_ext
    if temp_ext < t_min_oggi:
        t_min_oggi = temp_ext
    if temp_ext > t_max_oggi:
        t_max_oggi = temp_ext
    t_media = (t_max_oggi + t_min_oggi) / 2.0
    delta_t = t_max_oggi - t_min_oggi
    etp_base = 0.0023 * Ra * (t_media + 17.8) * math.sqrt(max(delta_t, 1.0))
    etp_base = round(etp_base, 2)
    kc_mensile = {
        1: 0.35, 2: 0.35, 3: 0.45, 4: 0.55,
        5: 0.65, 6: 0.70, 7: 0.70, 8: 0.65,
        9: 0.55, 10: 0.50, 11: 0.40, 12: 0.35
    }
    kc = kc_mensile.get(mese_corrente, 0.50)
    etp_giornaliera = round(etp_base * kc, 2)
    kcb_mensile = {
        1: 0.15, 2: 0.15, 3: 0.25, 4: 0.35,
        5: 0.50, 6: 0.55, 7: 0.55, 8: 0.50,
        9: 0.40, 10: 0.30, 11: 0.20, 12: 0.15
    }
    kcb = kcb_mensile.get(mese_corrente, 0.30)
    capacita_campo = 200
    wilting_point = 80
    K_sat = 2.5
    beta_drenaggio = 3.5
    dati_salvati = load_state_section('meteo')
    print(f"STATE meteo: {dati_salvati}")
    ultima_data = dati_salvati.get("data_calcolo", "")
    api_ultimo_valore = dati_salvati.get("api_ultimo_valore", 179.45)
    sat_base_oggi = dati_salvati.get("sat_base_oggi", 0)
    etp_accumulata = dati_salvati.get("etp_accumulata_ieri", 0)
    e_nuovo_giorno = (ultima_data != oggi_str)
    debug_api = f"API_DEBUG: data={ultima_data}, api_ultimo={api_ultimo_valore:.2f}, etp_acc={etp_accumulata:.2f}"
    print(debug_api)
    if ultima_data != oggi_str:
        if ultima_data == "":
            sat_base_oggi = api_ultimo_valore
            etp_accumulata = 0
            t_min_oggi = temp_ext
            t_max_oggi = temp_ext
            print(f"Prima esecuzione: seed iniziale = {sat_base_oggi:.2f}")
        else:
            theta_prec = api_ultimo_valore / capacita_campo
            if theta_prec > 0.4:
                drenaggio_extra = K_sat * (theta_prec ** beta_drenaggio)
            else:
                drenaggio_extra = 0
            perdita_totale = etp_accumulata + drenaggio_extra
            sat_base_oggi = max(0, api_ultimo_valore - perdita_totale)
            print(f"Nuovo giorno: {api_ultimo_valore:.2f} - ETR({etp_accumulata:.2f}) - dren_Ksat({drenaggio_extra:.2f}) = {sat_base_oggi:.2f}")
            etp_accumulata = 0
            t_min_oggi = temp_ext
            t_max_oggi = temp_ext
        ultima_data = oggi_str
    saturazione_percentuale = (sat_base_oggi / capacita_campo) * 100
    if pioggia_1h > 25:
        runoff_intensita = 0.5
    elif pioggia_1h > 15:
        runoff_intensita = 0.35
    elif pioggia_1h > 8:
        runoff_intensita = 0.20
    elif pioggia_1h > 3:
        runoff_intensita = 0.08
    else:
        runoff_intensita = 0.02
    if saturazione_percentuale > 95:
        runoff_saturazione = 0.7
    elif saturazione_percentuale > 85:
        runoff_saturazione = 0.4
    elif saturazione_percentuale > 70:
        runoff_saturazione = 0.15
    else:
        runoff_saturazione = 0.0
    runoff_totale = max(runoff_intensita, runoff_saturazione)
    efficienza_infiltrazione = 1 - runoff_totale
    pioggia_infiltrata = pioggia_24h * efficienza_infiltrazione
    theta_attuale = sat_base_oggi / capacita_campo if capacita_campo > 0 else 0
    theta_wp = wilting_point / capacita_campo
    p_depletion = 0.60
    theta_critico = theta_wp + p_depletion * (1.0 - theta_wp)
    if theta_attuale >= theta_critico:
        ks = 1.0
    elif theta_attuale > theta_wp:
        ks = (theta_attuale - theta_wp) / (theta_critico - theta_wp)
    else:
        ks = 0.0
    evaporazione_suolo = 0.0
    ke = 0.0
    try:
        TAW = max(0.0, capacita_campo - wilting_point)
        AW = max(0.0, sat_base_oggi - wilting_point)
        RAW = p_depletion * TAW
        ke_initial = max(0.0, kc - kcb)
        if RAW <= 0 or TAW <= 0:
            Kr = 0.0
        else:
            Kr = 1.0 if AW >= RAW else AW / RAW
        ke = ke_initial * Kr
        evaporazione_suolo = round(ke * etp_base, 2)
    except Exception:
        ke = 0.0
    traspirazione = round(kcb * ks * etp_base, 2)
    etr_giornaliera = round(traspirazione + evaporazione_suolo, 2)
    n_run_oggi = dati_salvati.get("n_run_oggi", 0)
    etp_media_oggi = dati_salvati.get("etp_media_oggi", 0)
    if not e_nuovo_giorno and n_run_oggi > 0:
        n_run_oggi += 1
        etp_media_oggi = etp_media_oggi + (etr_giornaliera - etp_media_oggi) / n_run_oggi
    else:
        n_run_oggi = 1
        etp_media_oggi = etr_giornaliera
    etp_accumulata = round(etp_media_oggi, 2)
    ore_trascorse = now_it.hour + now_it.minute / 60.0
    fraz_giorno = ore_trascorse / 24.0
    etr_parziale = etr_giornaliera * fraz_giorno
    sat_visualizzato = sat_base_oggi + pioggia_infiltrata - etr_parziale
    sat_visualizzato = max(0.0, min(sat_visualizzato, capacita_campo))
    sat_visualizzato = round(sat_visualizzato, 2)
    saturazione_percentuale = (sat_visualizzato / capacita_campo) * 100
    print(f"API AVANZATO (Bilancio idrico multi-componente):")
    print(f"  Base oggi: {sat_base_oggi:.2f} mm")
    print(f"  Pioggia 24h: {pioggia_24h:.2f} mm → infiltrata: {pioggia_infiltrata:.2f} mm")
    print(f"  Runoff: {runoff_totale*100:.1f}% (int:{runoff_intensita*100:.0f}%, sat:{runoff_saturazione*100:.0f}%)")
    print(f"  ETP base Hargreaves: {etp_base:.2f} mm | Kc={kc:.2f} → ETP={etp_giornaliera:.2f} mm")
    print(f"  Ra={Ra:.1f} MJ/m²/d | T_med={t_media:.1f}°C | ΔT={delta_t:.1f}°C")
    print(f"  Dual Kc: Ke={ke:.2f} (evap suolo) | Kcb={kcb:.2f} (trasp) | Ks={ks:.2f} (stress)")
    print(f"  Evaporazione suolo: {evaporazione_suolo:.2f} mm | Traspirazione: {traspirazione:.2f} mm")
    print(f"  ETR giornaliera: {etr_giornaliera:.2f} mm | ETR parziale ({fraz_giorno*100:.0f}% giorno): {etr_parziale:.2f} mm")
    print(f"  ETR media accumulata (run #{n_run_oggi}): {etp_accumulata:.2f} mm")
    print(f"  Drenaggio Brooks-Corey: K_sat={K_sat} mm/d, β={beta_drenaggio}")
    print(f"  Saturazione: {saturazione_percentuale:.1f}% ({sat_visualizzato:.2f}/{capacita_campo} mm)")
    print(f"  API totale: {sat_visualizzato:.2f} mm")
    sbcape_str = ""
    sbcape_value = 0
    mucape_value = 0
    cin_value = 0
    li_value = None
    bulk_shear = 0
    severe_score = 0
    severe_warning = None
    cc_low = 0
    cc_mid = 0
    cc_high = 0
    convective_risk = {
        "score": 0.0, "level": "basso", "warning": None,
        "event_label": "Instabilità convettiva", "event_trigger": False,
        "max_cape": 0.0, "cin_abs": 0.0, "li": None, "shear": 0.0,
    }
    _station_data_for_sbcape = {
        'temperature': temp_ext,
        'dewpoint': dew_point,
        'pressure': pressione_locale if pressione_locale else 1013.0,
        'humidity': umid_ext,
        'wind_speed': v_medio,
    }
    try:
        print("\n⚙️  Calcolo SBCAPE/MUCAPE inline...")
        _om_data = fetch_profile_cached()
        if _om_data:
            _current_om = _om_data.get("current", {})
            cc_low = _current_om.get("cloud_cover_low", 0) or 0
            cc_mid = _current_om.get("cloud_cover_mid", 0) or 0
            cc_high = _current_om.get("cloud_cover_high", 0) or 0
            print(f"  ☁️ Nuvolosità: bassa={cc_low}% media={cc_mid}% alta={cc_high}%")
            _sbcape_result = calcola_sbcape_advanced(_om_data, _station_data_for_sbcape)
            if _sbcape_result:
                sbcape_value = _sbcape_result.get("sbcape") or 0
                mucape_value = _sbcape_result.get("mucape") or 0
                cin_value = _sbcape_result.get("cin") or 0
                li_value = _sbcape_result.get("lifted_index")
                bulk_shear = _sbcape_result.get("bulk_shear") or 0
                _severe = calcola_severe_score(_sbcape_result)
                severe_score = _severe['score']
                severe_warning = _severe.get('level')
                _sbcape_result['severe_score'] = severe_score
                if severe_warning:
                    _sbcape_result['severe_warning'] = severe_warning
                    _sbcape_result['severe_reasons'] = _severe.get('reasons', [])
                save_state_section('sbcape', _sbcape_result)
                print(f"  ✓ SBCAPE={sbcape_value:.0f} MUCAPE={mucape_value:.0f} CIN={cin_value:.0f} LI={li_value} Shear={bulk_shear} SevScore={severe_score}")
            else:
                print("  ⚠️  Calcolo SBCAPE fallito, provo fallback da JSON")
                raise RuntimeError("calcolo fallito")
        else:
            print("  ⚠️  Profilo Open-Meteo non disponibile, provo fallback da JSON")
            raise RuntimeError("profilo non disponibile")
    except Exception as _e:
        print(f"  Fallback state.json [sbcape]: {_e}")
        try:
            sbcape_data = load_state_section('sbcape')
            if sbcape_data:
                sbcape_value = sbcape_data.get("sbcape") or 0
                mucape_value = sbcape_data.get("mucape") or 0
                cin_value = sbcape_data.get("cin") or 0
                li_value = sbcape_data.get("lifted_index")
                bulk_shear = sbcape_data.get("bulk_shear") or 0
                severe_score = sbcape_data.get("severe_score") or 0
                severe_warning = sbcape_data.get("severe_warning")
                print(f"  ✓ Letto da state.json [sbcape] (fallback)")
        except Exception as e2:
            print(f"  ✗ Anche fallback JSON fallito: {e2}")
    convective_risk = valuta_instabilita_convettiva(
        sbcape_value, mucape_value, cin_value, li_value, bulk_shear, severe_score,
    )
    storico = carica_storico()
    simbolo_baro, delta_baro, desc_baro = calcola_tendenza_barometrica(storico, pressione_msl)
    storico.append({
        "ts": now_it.isoformat(),
        "temp": temp_ext,
        "pressione": pressione_msl,
        "pioggia_1h": pioggia_1h,
        "pioggia_24h": pioggia_24h,
        "umidita": umid_ext,
        "vento": v_medio,
        "raffica": raffica,
        "dew_point": dew_point,
        "api": sat_visualizzato,
        "sbcape": sbcape_value,
        "mucape": mucape_value,
        "bulk_shear": bulk_shear,
        "theta_e": classifica_massa_aria(temp_ext, dew_point, pressione_msl, mese_corrente).get("theta_e"),
        "cc_low": cc_low,
        "cc_mid": cc_mid,
        "cc_high": cc_high,
    })
    salva_storico(storico)
    avvisi = []
    diff_temp_dew = temp_ext - dew_point
    if umid_ext >= 99 and diff_temp_dew <= 0.5:
        if v_medio < 5:
            avvisi.append("🌫️ AVVISO: NEBBIA (T-Td ≤0.5°C, U≥99%)")
        else:
            avvisi.append("🌫️ AVVISO: FOSCHIA (T-Td ≤0.5°C, U≥99%)")
    if temp_ext >= thresholds.ARPAL_HEAT_ROSSO:
        avvisi.append(f"🔴🔥 AVVISO: CALDO ESTREMO — {temp_ext}°C (soglia ARPAL 🔴 ≥{thresholds.ARPAL_HEAT_ROSSO:.0f}°C)")
    elif temp_ext >= thresholds.ARPAL_HEAT_ARANCIONE:
        avvisi.append(f"🟠🔥 AVVISO: CALDO MOLTO INTENSO — {temp_ext}°C (soglia ARPAL 🟠 ≥{thresholds.ARPAL_HEAT_ARANCIONE:.0f}°C)")
    elif temp_ext >= thresholds.ARPAL_HEAT_GIALLO:
        avvisi.append(f"🟡🔥 AVVISO: CALDO INTENSO — {temp_ext}°C (soglia ARPAL 🟡 ≥{thresholds.ARPAL_HEAT_GIALLO:.0f}°C)")
    elif temp_ext <= thresholds.ARPAL_FROST_ROSSO:
        avvisi.append(f"🔴❄️ AVVISO: GELO ESTREMO — {temp_ext}°C (soglia ARPAL 🔴 ≤{thresholds.ARPAL_FROST_ROSSO:.0f}°C)")
    elif temp_ext <= thresholds.ARPAL_FROST_ARANCIONE:
        avvisi.append(f"🟠❄️ AVVISO: GELO INTENSO — {temp_ext}°C (soglia ARPAL 🟠 ≤{thresholds.ARPAL_FROST_ARANCIONE:.0f}°C)")
    elif temp_ext <= thresholds.ARPAL_FROST_GIALLO:
        avvisi.append(f"🟡❄️ AVVISO: GELO — {temp_ext}°C (soglia ARPAL 🟡 ≤{thresholds.ARPAL_FROST_GIALLO:.0f}°C)")
    if temp_ext > 25 and umid_ext > 60:
        avvisi.append("🥵 AVVISO: AFA")
    if pressione_msl < thresholds.ARPAL_STORM_SURGE_ROSSO:
        avvisi.append(f"🔴🌊 AVVISO: MAREGGIATE GRAVI — {pressione_msl} hPa (soglia ARPAL 🔴 <{thresholds.ARPAL_STORM_SURGE_ROSSO:.0f} hPa)")
    elif pressione_msl < thresholds.ARPAL_STORM_SURGE_ARANCIONE:
        avvisi.append(f"🟠🌊 AVVISO: MAREGGIATE — {pressione_msl} hPa (soglia ARPAL 🟠 <{thresholds.ARPAL_STORM_SURGE_ARANCIONE:.0f} hPa)")
    elif pressione_msl < thresholds.ARPAL_STORM_SURGE_GIALLO:
        avvisi.append(f"🟡🌊 AVVISO: ATTENZIONE MARE — {pressione_msl} hPa (soglia ARPAL 🟡 <{thresholds.ARPAL_STORM_SURGE_GIALLO:.0f} hPa)")
    if pioggia_1h >= thresholds.ARPAL_RAIN_1H_ROSSO:
        avvisi.append(f"🔴🌧️ AVVISO: NUBIFRAGIO — {pioggia_1h} mm/h (soglia ARPAL 🔴 ≥{thresholds.ARPAL_RAIN_1H_ROSSO:.0f} mm/h)")
    elif pioggia_1h >= thresholds.ARPAL_RAIN_1H_ARANCIONE:
        avvisi.append(f"🟠🌧️ AVVISO: PIOGGIA MOLTO FORTE — {pioggia_1h} mm/h (soglia ARPAL 🟠 ≥{thresholds.ARPAL_RAIN_1H_ARANCIONE:.0f} mm/h)")
    elif pioggia_1h >= thresholds.ARPAL_RAIN_1H_GIALLO:
        avvisi.append(f"🟡🌧️ AVVISO: PIOGGIA FORTE — {pioggia_1h} mm/h (soglia ARPAL 🟡 ≥{thresholds.ARPAL_RAIN_1H_GIALLO:.0f} mm/h)")
    elif pioggia_1h >= 6:
        avvisi.append(f"🌧️ AVVISO: PIOGGIA MODERATA — {pioggia_1h} mm/h")
    if sat_visualizzato >= 170:
        avvisi.append("⛰️ AVVISO: SUOLO SATURO")
    if pioggia_24h >= thresholds.ARPAL_RAIN_24H_ROSSO:
        avvisi.append(f"🔴🌧️ AVVISO: CUMULATE ECCEZIONALI — {pioggia_24h} mm/24h (soglia ARPAL 🔴 ≥{thresholds.ARPAL_RAIN_24H_ROSSO:.0f} mm)")
    elif pioggia_24h >= thresholds.ARPAL_RAIN_24H_ARANCIONE:
        avvisi.append(f"🟠🌧️ AVVISO: CUMULATE MOLTO ELEVATE — {pioggia_24h} mm/24h (soglia ARPAL 🟠 ≥{thresholds.ARPAL_RAIN_24H_ARANCIONE:.0f} mm)")
    elif pioggia_24h >= thresholds.ARPAL_RAIN_24H_GIALLO:
        avvisi.append(f"🟡🌧️ AVVISO: CUMULATE ELEVATE — {pioggia_24h} mm/24h (soglia ARPAL 🟡 ≥{thresholds.ARPAL_RAIN_24H_GIALLO:.0f} mm)")
    elif pioggia_24h >= 50:
        avvisi.append(f"🌧️ AVVISO: CUMULATE SIGNIFICATIVE — {pioggia_24h} mm/24h")
    if severe_warning:
        avvisi.append(severe_warning)
    else:
        if convective_risk["warning"]:
            avvisi.append(convective_risk["warning"])
    avvisi_lower = " ".join(avvisi).lower() if avvisi else ""
    sbcape_lines = []
    if "sbcape" not in avvisi_lower:
        sbcape_lines.append(f"SBCAPE: {sbcape_value} J/kg")
    if mucape_value and mucape_value > sbcape_value and "mucape" not in avvisi_lower:
        sbcape_lines.append(f"MUCAPE: {mucape_value} J/kg")
    if "cin" not in avvisi_lower:
        sbcape_lines.append(f"CIN: {cin_value} J/kg")
    if li_value is not None and "lifted index" not in avvisi_lower:
        sbcape_lines.append(f"Lifted Index: {li_value:+.1f}°C")
    if bulk_shear:
        sbcape_lines.append(f"Bulk Shear: {bulk_shear:.1f} m/s")
    if severe_score > 0 and "severe score" not in avvisi_lower:
        sbcape_lines.append(f"Severe Score: {severe_score}/12")
    elif convective_risk["score"] > 0 and "severe score" not in avvisi_lower:
        sbcape_lines.append(f"Convective Score (fallback): {convective_risk['score']}/12")
    sbcape_str = "\n".join(sbcape_lines) + ("\n" if sbcape_lines else "")
    str_avvisi = "\n".join(avvisi) + "\n\n" if avvisi else ""
    massa_aria = classifica_massa_aria(temp_ext, dew_point, pressione_msl, mese_corrente)
    theta_e_850 = None
    temp_alti_livelli = None
    if _om_data:
        theta_e_850 = calcola_theta_e_850hpa(_om_data)
        temp_alti_livelli = estrai_temperature_alti_livelli(_om_data)
    if theta_e_850 is not None:
        theta_e_str = f"θe sup: {massa_aria['theta_e']}°C · θe 850hPa: {theta_e_850}°C"
    else:
        theta_e_str = f"θe: {massa_aria['theta_e']}°C"
    if temp_alti_livelli:
        temp_livelli_str = f" · T_850hPa: {temp_alti_livelli['T_850']}°C · T_500hPa: {temp_alti_livelli['T_500']}°C"
    else:
        temp_livelli_str = ""
    massa_str = (
        f"🌍 *MASSA D'ARIA*\n"
        f"{massa_aria['emoji']} {massa_aria['nome']} ({massa_aria['tipo']})\n"
        f"{massa_aria['desc']}\n"
        f"{theta_e_str} · Anomalia: {massa_aria['anomalia']:+.1f}°C · Spread T-Td: {massa_aria['spread']}°C{temp_livelli_str}\n"
    )
    theta_e_display = theta_e_850 if theta_e_850 is not None else massa_aria['theta_e']
    print(f"Massa d'aria: {massa_aria['tipo']} ({massa_aria['nome']}) - θe_850={theta_e_850}°C, θe_sup={massa_aria['theta_e']}°C, anomalia={massa_aria['anomalia']:+.1f}°C")
    nuovi_dati = {
        "api_ultimo_valore": sat_visualizzato,
        "sat_base_oggi": sat_base_oggi,
        "etp_accumulata_ieri": etp_accumulata,
        "data_calcolo": ultima_data,
        "ultimo_update_ora": str(now_it),
        "ultimo_etp_giornaliera": etp_giornaliera,
        "ultimo_etr_giornaliera": etr_giornaliera,
        "ultima_saturazione_perc": round(saturazione_percentuale, 1),
        "t_min_oggi": t_min_oggi,
        "t_max_oggi": t_max_oggi,
        "ultima_pressione": pressione_msl,
        "ultimi_avvisi": avvisi,
        "n_run_oggi": n_run_oggi,
        "etp_media_oggi": round(etp_media_oggi, 2),
        "ultimo_kc": kc,
        "ultimo_ke": round(ke, 2),
        "ultimo_kcb": kcb,
        "ultimo_ks": round(ks, 2),
    }
    save_state_section('meteo', nuovi_dati)
    data_ora_it = now_it.strftime('%d/%m/%Y %H:%M')
    testo_meteo = (
        f"📡 *STAZIONE METEO ECOWITT WITTBOY — LA SPEZIA*\n"
        f"📅 {data_ora_it}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{source_info_line}"
        f"{str_avvisi}"
        f"🌡️ *TEMPERATURE*\n"
        f"Aria: {temp_ext}°C\n"
        f"Percepita: {feel_like}°C\n"
        f"Heat Index: {heat_index}°C\n"
        f"Wind Chill: {wind_chill}°C\n"
        f"Punto di rugiada: {dew_point}°C\n\n"
        f"💧 *UMIDITÀ E PRECIPITAZIONI*\n"
        f"Umidità: {umid_ext}%\n"
        f"Pioggia ultima ora: {pioggia_1h} mm\n"
        f"Pioggia 24h: {pioggia_24h} mm\n"
        f"Rain rate: {rain_rate} mm/h\n\n"
        f"🌬️ *VENTO*\n"
        f"Velocità media: {v_medio} km/h\n"
        f"Raffica max (1h): {raffica} km/h\n\n"
        f"🔵 *PRESSIONE ATMOSFERICA*\n"
        f"Livello mare: {pressione_msl} hPa {simbolo_baro}\n\n"
        f"☀️ *RADIAZIONE*\n"
        f"Indice UV: {uv_idx}\n\n"
        f"☁️ *NUVOLOSITÀ (Open-Meteo)*\n"
        f"Bassa (<2 km): {cc_low}%\n"
        f"Media (2-6 km): {cc_mid}%\n"
        f"Alta (>6 km): {cc_high}%\n\n"
        f"🌱 *BILANCIO IDRICO SUOLO*\n"
        f"API: {sat_visualizzato} mm ({saturazione_percentuale:.1f}%)\n"
        f"ETR: {etr_giornaliera} mm\n"
        f"ETP: {etp_giornaliera} mm\n\n"
        f"⚡ *INSTABILITÀ CONVETTIVA*\n"
        f"{sbcape_str}\n"
        f"{massa_str}\n"
        f"🔋 Batteria: {batt}%"
    )
    ora_corrente = now_it.hour
    minuto_corrente = now_it.minute
    orari_report = [5, 11, 17, 23]
    minuti_report = [58, 59]
    e_orario_programmato = ora_corrente in orari_report and minuto_corrente in minuti_report
    eventi_significativi = []
    ultimo_invio_slot = dati_salvati.get("ultimo_invio_slot")
    ultimo_invio_ts_raw = dati_salvati.get("ultimo_invio_ts")
    if pioggia_1h >= thresholds.RAIN_SIGNIFICANT:
        eventi_significativi.append(f"Pioggia: {pioggia_1h} mm/h")
    if temp_ext <= thresholds.TEMP_FREEZING:
        eventi_significativi.append(f"Temperatura bassa: {temp_ext}°C")
    if temp_ext >= thresholds.TEMP_HOT:
        eventi_significativi.append(f"Temperatura alta: {temp_ext}°C")
    pressione_precedente = dati_salvati.get("ultima_pressione")
    pressione_in_calo_attuale = isinstance(pressione_precedente, (int, float)) and pressione_msl < pressione_precedente
    if pressione_in_calo_attuale and delta_baro <= -1:
        eventi_significativi.append(f"Pressione in calo: {delta_baro:.1f} hPa/3h")
    if umid_ext >= 99 and diff_temp_dew <= 0.5:
        eventi_significativi.append(f"Nebbia (T-Td={diff_temp_dew:.1f}°C, U={umid_ext}%)")
    if convective_risk["event_trigger"]:
        li_text = f"{convective_risk['li']:.1f}" if convective_risk["li"] is not None else "n/d"
        eventi_significativi.append(
            f"{convective_risk['event_label']} (Score {convective_risk['score']}/12, "
            f"CAPE {convective_risk['max_cape']:.0f} J/kg, CIN {cin_value:.0f} J/kg, "
            f"LI {li_text}°C, Shear {convective_risk['shear']:.1f} m/s)"
        )
    if severe_score >= 7 and not convective_risk["event_trigger"]:
        eventi_significativi.append(f"Severe Score: {severe_score}/12")
    avvisi_precedenti = set(dati_salvati.get("ultimi_avvisi", []))
    avvisi_attuali = set(avvisi)
    nuovi_avvisi = avvisi_attuali - avvisi_precedenti
    if nuovi_avvisi:
        eventi_significativi.append(f"Nuovi avvisi: {len(nuovi_avvisi)}")
    devo_inviare = force_send or e_orario_programmato or len(eventi_significativi) > 0
    invio_slot = None
    invio_duplicato = False
    if e_orario_programmato:
        invio_slot = f"scheduled:{now_it.strftime('%Y-%m-%d')}:{ora_corrente:02d}"
    elif eventi_significativi:
        eventi_fingerprint = "|".join(sorted(eventi_significativi))
        event_hash = hashlib.sha1(eventi_fingerprint.encode("utf-8")).hexdigest()[:12]
        invio_slot = f"event:{event_hash}"
    if devo_inviare and not force_send and invio_slot and ultimo_invio_slot == invio_slot:
        if invio_slot.startswith("scheduled:"):
            invio_duplicato = True
        elif invio_slot.startswith("event:") and ultimo_invio_ts_raw:
            try:
                ultimo_invio_dt = datetime.fromisoformat(ultimo_invio_ts_raw)
                if ultimo_invio_dt.tzinfo is None:
                    ultimo_invio_dt = ultimo_invio_dt.replace(tzinfo=TZ_ROME)
                if (now_it - ultimo_invio_dt).total_seconds() < 600:
                    invio_duplicato = True
            except Exception:
                invio_duplicato = False
    if invio_duplicato:
        print(f"⏭️  Invio duplicato evitato (slot: {invio_slot})")
        devo_inviare = False
    if devo_inviare:
        motivo = []
        if force_send:
            motivo.append("Invio forzato (--force)")
        if e_orario_programmato:
            motivo.append(f"Orario programmato: {ora_corrente:02d}:{minuto_corrente:02d}")
        if eventi_significativi:
            motivo.append(f"Eventi: {', '.join(eventi_significativi)}")
        print(f"📤 Invio Telegram - Motivo: {' | '.join(motivo)}")
    else:
        print(f"⏭️  Nessun invio Telegram - Ora: {ora_corrente}:58, nessun evento significativo")
    if devo_inviare:
        url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        invio_avvenuto = False
        if not TELEGRAM_TOKEN or not _send_to:
            print("✗ Telegram non configurato (manca token o lista chat); salto invio")
        else:
            for chat_id in _send_to:
                try:
                    response = requests.post(
                        url_tg,
                        data={'chat_id': chat_id, 'text': testo_meteo, 'parse_mode': 'Markdown'},
                        timeout=10,
                    )
                    response.raise_for_status()
                    tg_payload = response.json()
                    if tg_payload.get("ok"):
                        print(f"✓ Messaggio inviato a {chat_id}")
                        invio_avvenuto = True
                    else:
                        print(f"✗ Telegram API testo errore per {chat_id}: {tg_payload}")
                except Exception as e:
                    print(f"✗ Errore Telegram testo: {e}")
        if invio_avvenuto and invio_slot:
            nuovi_dati["ultimo_invio_slot"] = invio_slot
            nuovi_dati["ultimo_invio_ts"] = now_it.isoformat()
            save_state_section('meteo', nuovi_dati)
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--sbcape":
        calcola_e_salva_sbcape()
    elif len(sys.argv) > 1 and sys.argv[1] == "--force":
        esegui_report(force_send=True)
    else:
        esegui_report()
