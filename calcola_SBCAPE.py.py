import requests
import json
import os
import time
import hmac
import hashlib
from datetime import datetime
import numpy as np
from scipy.interpolate import interp1d

# NEW (add these):
from config import (
    LATITUDE as LAT,
    LONGITUDE as LON,
    ELEVATION,
    TUYA_ACCESS_ID as ACCESS_ID,
    TUYA_ACCESS_SECRET as ACCESS_SECRET,
    TUYA_ENDPOINT as ENDPOINT,
    TUYA_DEVICE_ID as DEVICE_ID,
    FILE_SBCAPE
)
from utils import extract_pressure_hpa

# Compatibility alias: older code may reference FILE_OUTPUT
FILE_OUTPUT = FILE_SBCAPE

# Costanti fisiche
Rd = 287.05  # J/(kg·K) - costante gas per aria secca
Rv = 461.5   # J/(kg·K) - costante gas per vapore acqueo
Cp = 1005.0  # J/(kg·K) - calore specifico aria a pressione costante
Lv = 2.5e6   # J/kg - calore latente di vaporizzazione
g = 9.80665  # m/s² - accelerazione di gravità
epsilon = 0.622  # Rd/Rv

# Cache globale per API
_API_CACHE = {}
CACHE_DURATION = 600  # 10 minuti

def get_auth_headers(method, url, token=None, body=""):
    """Genera headers per autenticazione Tuya"""
    t = str(int(time.time() * 1000))
    content_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    string_to_sign = f"{method}\n{content_hash}\n\n{url}"
    prefix = ACCESS_ID + token if token else ACCESS_ID
    sign_str = prefix + t + string_to_sign
    sign = hmac.new(ACCESS_SECRET.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest().upper()
    headers = {'client_id': ACCESS_ID, 'sign': sign, 't': t, 'sign_method': 'HMAC-SHA256', 'Content-Type': 'application/json'}
    if token: 
        headers['access_token'] = token
    return headers

def fetch_station_data_with_retry(max_retries=3):
    """Legge i dati reali dalla stazione meteo Tuya con retry logic"""
    for attempt in range(max_retries):
        try:
            token_url = "/v1.0/token?grant_type=1"
            r = requests.get(ENDPOINT + token_url, headers=get_auth_headers("GET", token_url), timeout=10).json()
            if not r.get("success"):
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # exponential backoff
                    continue
                print("✗ Errore Token Tuya")
                return None
            
            token = r['result']['access_token']
            status_url = f"/v1.0/devices/{DEVICE_ID}/status"
            res = requests.get(ENDPOINT + status_url, headers=get_auth_headers("GET", status_url, token), timeout=10).json()
            
            if res.get("success"):
                d = {item['code']: item['value'] for item in res.get("result", [])}
                
                # Estrai i parametri necessari
                station_data = {
                    'temperature': d.get('temp_current_external', 0) / 10,  # °C
                    'dewpoint': d.get('dew_point_temp', 0) / 10,  # °C
                    'pressure': extract_pressure_hpa(d) or 1013.0,  # hPa locale a 100m dalla stazione
                    'humidity': d.get('humidity_outdoor', 0),  # %
                    'wind_speed': d.get('windspeed_avg', 0) / 10,  # km/h
                    'wind_gust': d.get('windspeed_gust', 0) / 10,  # km/h
                }
                
                # Validazione fisica dei dati
                if (station_data['temperature'] < -50 or station_data['temperature'] > 60 or
                    station_data['humidity'] < 0 or station_data['humidity'] > 100 or
                    station_data['pressure'] < 900 or station_data['pressure'] > 1050):
                    print(f"⚠️  Dati stazione anomali (attempt {attempt+1})")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return None
                
                print(f"✓ Dati stazione Tuya ricevuti: T={station_data['temperature']:.1f}°C, Td={station_data['dewpoint']:.1f}°C, P={station_data['pressure']:.1f}hPa, RH={station_data['humidity']}%")
                return station_data
            else:
                print(f"✗ Errore lettura device Tuya (attempt {attempt+1})")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
        except Exception as e:
            print(f"✗ Errore connessione Tuya (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    
    return None

def fetch_profile_cached():
    """Scarica i dati meteorologici completi da Open-Meteo con cache.
    Usa AROME France (Météo-France, 2.5km) come modello principale,
    con fallback al modello default se AROME non è disponibile."""
    global _API_CACHE
    
    now = time.time()
    if 'open_meteo' in _API_CACHE and now - _API_CACHE['open_meteo_time'] < CACHE_DURATION:
        print(f"✓ Usando cache Open-Meteo (età: {int(now - _API_CACHE['open_meteo_time'])}s)")
        return _API_CACHE['open_meteo']
    
    url = "https://api.open-meteo.com/v1/forecast"
    
    # Livelli di pressione da richiedere (temperatura E umidità)
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
    
    pressure_levels_wind = [
        "windspeed_10m", "windspeed_80m", "windspeed_120m"
    ]
    
    hourly_vars = ",".join(pressure_levels_temp + pressure_levels_rh + pressure_levels_wind) + ",dew_point_2m,relative_humidity_2m"
    
    base_params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,relative_humidity_2m,pressure_msl,dew_point_2m,windspeed_10m,winddirection_10m",
        "hourly": hourly_vars,
        "timezone": "UTC"
    }
    
    # 1. Prova AROME France (Météo-France, 2.5km, ottimo per convezione Mediterraneo)
    try:
        params_arome = {**base_params, "models": "meteofrance_arome_france"}
        r = requests.get(url, params=params_arome, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        # Verifica che i dati di pressione non siano tutti null
        hourly = data.get("hourly", {})
        test_key = "temperature_850hPa"
        if test_key in hourly and any(v is not None for v in hourly[test_key]):
            data['_model_used'] = 'AROME France (2.5km)'
            _API_CACHE['open_meteo'] = data
            _API_CACHE['open_meteo_time'] = now
            print(f"✓ Fetch Open-Meteo riuscito - modello AROME France (2.5km)")
            return data
        else:
            print(f"⚠️  AROME France ha restituito dati vuoti, passo al fallback")
    except Exception as e:
        print(f"⚠️  AROME France non disponibile ({e}), passo al fallback")
    
    # 2. Fallback: modello default (best_match)
    try:
        r = requests.get(url, params=base_params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        data['_model_used'] = 'best_match (fallback)'
        _API_CACHE['open_meteo'] = data
        _API_CACHE['open_meteo_time'] = now
        
        print(f"✓ Fetch Open-Meteo riuscito - modello default (best_match)")
        return data
    except Exception as e:
        print(f"Errore fetch Open-Meteo: {e}")
        return None

def vapor_pressure(T_celsius):
    """Calcola la pressione di vapore saturo (hPa) usando la formula di Bolton (1980)"""
    return 6.112 * np.exp(17.67 * T_celsius / (T_celsius + 243.5))

def mixing_ratio(e, p):
    """Calcola il rapporto di miscelanza (kg/kg) da pressione di vapore e pressione totale"""
    return epsilon * e / (p - e)

def virtual_temperature(T_kelvin, q):
    """Calcola la temperatura virtuale (K) da temperatura e rapporto di miscelanza"""
    return T_kelvin * (1 + q / epsilon) / (1 + q)

def dewpoint_to_mixing_ratio(Td_celsius, p_hPa):
    """Calcola il rapporto di miscelanza dal punto di rugiada"""
    es = vapor_pressure(Td_celsius)
    return mixing_ratio(es, p_hPa)

def lcl_pressure(T_kelvin, Td_kelvin, p_hPa):
    """Calcola la pressione al LCL (hPa) usando l'approssimazione di Bolton"""
    Tl = 1 / (1 / (Td_kelvin - 56) + np.log(T_kelvin / Td_kelvin) / 800) + 56
    theta = T_kelvin * (1000 / p_hPa) ** (Rd / Cp)
    return 1000 * (Tl / theta) ** (Cp / Rd)

def moist_adiabatic_lapse_rate(T_kelvin, p_hPa):
    """Calcola il lapse rate adiabatico saturo (K/Pa) alla temperatura e pressione date"""
    es = vapor_pressure(T_kelvin - 273.15)
    ws = mixing_ratio(es, p_hPa)
    
    numerator = 1 + Lv * ws / (Rd * T_kelvin)
    denominator = 1 + epsilon * Lv * Lv * ws / (Cp * Rd * T_kelvin * T_kelvin)
    
    return (Rd * T_kelvin / (Cp * p_hPa)) * (numerator / denominator)

def lift_parcel(T_start_K, p_start_hPa, q_start, p_levels_hPa):
    """
    Solleva una particella d'aria attraverso i livelli di pressione.
    Usa adiabatica secca fino al LCL, poi adiabatica satura.
    
    Returns: array di temperature della particella (K) ad ogni livello, p_lcl
    """
    T_parcel = np.zeros(len(p_levels_hPa))
    T_parcel[0] = T_start_K
    
    # Calcola il LCL dalla particella di superficie
    es_start = vapor_pressure(T_start_K - 273.15)
    e_start = q_start * p_start_hPa / (epsilon + q_start)
    e_start = min(e_start, es_start)  # non può superare la saturazione
    
    if e_start > 0:
        Td_start = 243.5 * np.log(e_start / 6.112) / (17.67 - np.log(e_start / 6.112))
        p_lcl = lcl_pressure(T_start_K, Td_start + 273.15, p_start_hPa)
    else:
        p_lcl = p_start_hPa / 2  # se aria molto secca, LCL alto
    
    # Solleva la particella attraverso i livelli
    for i in range(1, len(p_levels_hPa)):
        p_lower = p_levels_hPa[i-1]
        p_upper = p_levels_hPa[i]
        
        if p_lower >= p_lcl and p_upper >= p_lcl:
            # Sotto il LCL: processo adiabatico secco
            T_parcel[i] = T_parcel[i-1] * (p_upper / p_lower) ** (Rd / Cp)
        elif p_lower >= p_lcl and p_upper < p_lcl:
            # Attraversamento del LCL
            T_at_lcl = T_parcel[i-1] * (p_lcl / p_lower) ** (Rd / Cp)
            n_steps = 10
            p_range = np.linspace(p_lcl, p_upper, n_steps)
            T_temp = T_at_lcl
            for j in range(1, n_steps):
                dp = p_range[j] - p_range[j-1]
                dT_dp = moist_adiabatic_lapse_rate(T_temp, p_range[j-1])
                T_temp = T_temp + dT_dp * dp
            T_parcel[i] = T_temp
        else:
            # Sopra il LCL: processo adiabatico saturo
            n_steps = 5
            p_range = np.linspace(p_lower, p_upper, n_steps)
            T_temp = T_parcel[i-1]
            for j in range(1, n_steps):
                dp = p_range[j] - p_range[j-1]
                dT_dp = moist_adiabatic_lapse_rate(T_temp, p_range[j-1])
                T_temp = T_temp + dT_dp * dp
            T_parcel[i] = T_temp
    
    return T_parcel, p_lcl

def calcola_cape_from_profile(T_parcel, p_env, T_env, RH_env, q_parcel_surface, p_lcl):
    """
    Calcola CAPE e CIN da profili di temperatura e umidità.
    
    Returns: dict con sbcape, cin, lfc_pressure, el_pressure, buoyancy profile
    """
    # Calcola temperatura virtuale per ambiente e particella
    Tv_env = np.zeros(len(p_env))
    Tv_parcel = np.zeros(len(p_env))
    
    for i in range(len(p_env)):
        # Ambiente: usa profilo RH reale
        es_env = vapor_pressure(T_env[i] - 273.15)
        e_env = es_env * RH_env[i]
        q_env = mixing_ratio(e_env, p_env[i])
        Tv_env[i] = virtual_temperature(T_env[i], q_env)
        
        # Particella: satura sopra LCL
        if p_env[i] <= p_lcl:
            es_parcel = vapor_pressure(T_parcel[i] - 273.15)
            q_parcel = mixing_ratio(es_parcel, p_env[i])
        else:
            q_parcel = q_parcel_surface
        Tv_parcel[i] = virtual_temperature(T_parcel[i], q_parcel)
    
    # Trova LFC e EL
    buoyancy = Tv_parcel - Tv_env
    
    # LFC: primo punto dove la particella diventa più calda (buoyancy > 0)
    # Deve essere >= LCL
    lcl_idx = 0
    for i in range(len(p_env)):
        if p_env[i] <= p_lcl:
            lcl_idx = i
            break
    
    lfc_idx = None
    for i in range(max(1, lcl_idx), len(buoyancy)):
        if buoyancy[i] > 0 and buoyancy[i-1] <= 0:
            lfc_idx = i
            break
    
    # EL: punto dove la particella torna fredda dopo LFC
    el_idx = None
    if lfc_idx is not None:
        for i in range(lfc_idx + 1, len(buoyancy)):
            if buoyancy[i] < 0:
                el_idx = i
                break
        if el_idx is None:
            el_idx = len(buoyancy) - 1
    
    # Calcola CIN e CAPE tramite integrazione usando formula idrostatica esatta
    cin = 0.0
    cape = 0.0
    
    if lfc_idx is not None:
        # CIN: dalla superficie al LFC
        for i in range(1, lfc_idx):
            if buoyancy[i] < 0:
                Tv_avg = (Tv_env[i] + Tv_env[i-1]) / 2
                # Formula esatta: dz = (Rd * Tv / g) * ln(p_lower / p_upper)
                dz = (Rd * Tv_avg / g) * np.log(p_env[i-1] / p_env[i])
                buoy_avg = (buoyancy[i] + buoyancy[i-1]) / 2
                dCIN = g * (buoy_avg / Tv_avg) * dz
                cin += dCIN
        
        # CAPE: dal LFC al EL
        for i in range(lfc_idx + 1, el_idx + 1):
            if buoyancy[i] > 0 or buoyancy[i-1] > 0:
                Tv_avg = (Tv_env[i] + Tv_env[i-1]) / 2
                # Formula esatta: dz = (Rd * Tv / g) * ln(p_lower / p_upper)
                dz = (Rd * Tv_avg / g) * np.log(p_env[i-1] / p_env[i])
                buoy_avg = (buoyancy[i] + buoyancy[i-1]) / 2
                if buoy_avg > 0:
                    dCAPE = g * (buoy_avg / Tv_avg) * dz
                    cape += dCAPE
    
    return {
        'sbcape': cape,
        'cin': cin,
        'lfc_idx': lfc_idx,
        'el_idx': el_idx,
        'lfc_pressure': p_env[lfc_idx] if lfc_idx is not None else None,
        'el_pressure': p_env[el_idx] if el_idx is not None else None,
        'buoyancy': buoyancy
    }

def calcola_mucape(data, station_data, T_env, p_env, RH_env):
    """
    Calcola Most Unstable CAPE (MUCAPE) cercando la particella più instabile
    nei primi 300 hPa dalla superficie.
    """
    if station_data is None:
        return None
    
    p_surface = station_data['pressure']
    max_cape = 0
    mu_level = p_surface
    mu_result = None
    
    # Cerca ogni 25 hPa nei primi 300 hPa
    for p_idx in range(len(p_env)):
        if p_env[p_idx] < p_surface - 300:
            break
        
        # Estrai T e RH a questo livello
        T_test = T_env[p_idx]
        RH_test = RH_env[p_idx]
        p_test = p_env[p_idx]
        
        # Calcola mixing ratio
        es_test = vapor_pressure(T_test - 273.15)
        e_test = es_test * RH_test
        q_test = mixing_ratio(e_test, p_test)
        
        # BUGFIX: passa solo i livelli >= p_test (dal livello di partenza in su)
        p_levels_above = p_env[p_idx:]
        T_levels_above = T_env[p_idx:]
        RH_levels_above = RH_env[p_idx:]
        
        # Solleva particella da questo livello
        T_parcel_mu, p_lcl_mu = lift_parcel(T_test, p_test, q_test, p_levels_above)
        
        # Calcola CAPE
        result_mu = calcola_cape_from_profile(T_parcel_mu, p_levels_above, T_levels_above, RH_levels_above, q_test, p_lcl_mu)
        
        if result_mu['sbcape'] > max_cape:
            max_cape = result_mu['sbcape']
            mu_level = p_test
            mu_result = result_mu
            mu_result['mu_level'] = mu_level
    
    return mu_result

def calcola_wind_shear(data, current_hour_idx, station_data):
    """
    Calcola un PROXY molto approssimato del wind shear 0-6km (differenza tra vento a 10m e 120m).
    ATTENZIONE: Questo NON rappresenta il vero wind shear 0-6km (manca il vento in libera atmosfera, tipicamente a 500 hPa/5.5 km).
    Il valore sarà sistematicamente sottostimato (anche di 3-5 volte). Usare solo come indicatore qualitativo.
    """
    try:
        hourly = data.get("hourly", {})
        # Vento superficie dalla stazione
        if station_data and 'wind_speed' in station_data:
            u_surface = station_data['wind_speed'] / 3.6  # km/h -> m/s
        else:
            u_surface = hourly.get('windspeed_10m', [0])[current_hour_idx] / 3.6 if 'windspeed_10m' in hourly else 0
        # Vento a 120m (proxy molto povero per 6km)
        u_120m = hourly.get('windspeed_120m', [0])[current_hour_idx] / 3.6 if 'windspeed_120m' in hourly else 0
        # Stima shear (molto approssimata)
        shear = abs(u_120m - u_surface)
        # Avviso esplicito
        print("[AVVISO] Il wind shear calcolato è solo un proxy tra 10m e 120m. Il vero shear 0-6km non è disponibile e questo valore è fortemente sottostimato.")
        return {
            'surface_wind': u_surface,
            'upper_wind': u_120m,
            'bulk_shear': shear
        }
    except:
        return None

def validate_results(results, T_surface_C):
    """
    Validazione fisica dei risultati SBCAPE.
    Ritorna warnings se ci sono valori anomali.
    """
    warnings = []
    
    if results['sbcape'] > 6000:
        warnings.append(f"⚠️  SBCAPE molto elevato ({results['sbcape']:.0f} J/kg) - verifica dati")
    
    if results['sbcape'] > 1500 and T_surface_C < 10:
        warnings.append(f"⚠️  CAPE elevato con T bassa ({T_surface_C:.1f}°C) - situazione insolita")
    
    if results['cin'] < -500:
        warnings.append(f"⚠️  CIN molto forte ({results['cin']:.0f} J/kg) - convezione fortemente inibita")
    
    return warnings

def calcola_sbcape_advanced(data, station_data=None):
    """
    Calcola SBCAPE, MUCAPE, CIN e parametri convettivi avanzati.
    Versione migliorata con:
    - Profilo umidità reale dalla stazione + Open-Meteo
    - Interpolazione ad alta risoluzione
    - MUCAPE
    - Wind shear
    - Validazione fisica
    """
    if not data:
        print("Errore: dati invalidi")
        return None
    
    try:
        hourly = data.get("hourly", {})
        
        # Trova l'indice dell'ora corrente (UTC, coerente con timezone API)
        current_hour_idx = 0
        if "time" in hourly:
            from datetime import timezone as tz
            now_utc = datetime.now(tz.utc)
            now_hour_str = now_utc.strftime("%Y-%m-%dT%H:")
            for i, time_str in enumerate(hourly["time"]):
                if time_str.startswith(now_hour_str):
                    current_hour_idx = i
                    break
        
        print(f"  Usando dati dell'ora: {hourly['time'][current_hour_idx] if 'time' in hourly else 'N/A'} (indice {current_hour_idx})")
        
        # Verifica che l'ora corrente abbia dati non-null (AROME ha copertura limitata)
        test_key = "temperature_850hPa"
        if (test_key in hourly and hourly[test_key] and 
            len(hourly[test_key]) > current_hour_idx and 
            hourly[test_key][current_hour_idx] is None):
            # L'ora corrente ha dati null, cerca l'ultima ora valida
            original_idx = current_hour_idx
            for idx in range(current_hour_idx, -1, -1):
                if hourly[test_key][idx] is not None:
                    current_hour_idx = idx
                    break
            if current_hour_idx != original_idx:
                print(f"  ⚠️  Ora {original_idx} ha dati null, uso ora {current_hour_idx} ({hourly['time'][current_hour_idx]})")
        
        # Dati di superficie: PRIORITÀ ALLA STAZIONE REALE!
        if station_data:
            print("  → Usando dati REALI dalla stazione meteo (T, Td, P, RH)")
            T_surface_C = station_data['temperature']
            Td_surface_C = station_data['dewpoint']
            p_surface = station_data['pressure']
            RH_surface = station_data['humidity'] / 100  # frazione
            data_source = "Stazione Tuya (reale)"
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
        
        # Calcola mixing ratio di superficie
        if Td_surface_C is not None:
            q_surface = dewpoint_to_mixing_ratio(Td_surface_C, p_surface)
        else:
            es_surface = vapor_pressure(T_surface_C)
            e_surface = es_surface * RH_surface
            q_surface = mixing_ratio(e_surface, p_surface)
        
        # Estrai profilo verticale completo con TEMPERATURA E UMIDITÀ
        pressure_levels = [1000, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500]
        T_env = []
        p_env = []
        RH_env = []
        
        # Aggiungi la superficie
        p_env.append(p_surface)
        T_env.append(T_surface_K)
        RH_env.append(RH_surface)
        
        # Estrai dai livelli disponibili
        for p_level in pressure_levels:
            key_temp = f"temperature_{p_level}hPa"
            key_rh = f"relative_humidity_{p_level}hPa"
            
            if (key_temp in hourly and hourly[key_temp] and 
                len(hourly[key_temp]) > current_hour_idx and p_level <= p_surface):
                
                T_val = hourly[key_temp][current_hour_idx]
                
                # Umidità: usa valore reale se disponibile, altrimenti stima
                if key_rh in hourly and hourly[key_rh] and len(hourly[key_rh]) > current_hour_idx:
                    RH_val = hourly[key_rh][current_hour_idx] / 100
                else:
                    # Stima conservativa
                    RH_val = 0.5 if p_level > 500 else 0.3
                
                if T_val is not None:
                    p_env.append(p_level)
                    T_env.append(T_val + 273.15)
                    RH_env.append(RH_val)
        
        if len(p_env) < 3:
            print("Errore: profilo verticale insufficiente")
            return None
        
        p_env = np.array(p_env)
        T_env = np.array(T_env)
        RH_env = np.array(RH_env)
        
        # Ordina per pressione decrescente
        sort_idx = np.argsort(p_env)[::-1]
        p_env = p_env[sort_idx]
        T_env = T_env[sort_idx]
        RH_env = RH_env[sort_idx]
        
        # INTERPOLAZIONE ad alta risoluzione (ogni 10 hPa)
        p_min = max(200, p_env[-1])
        p_fine = np.arange(p_surface, p_min, -10)
        
        if len(p_env) >= 4:  # serve almeno 4 punti per cubic
            T_interp_func = interp1d(p_env, T_env, kind='cubic', fill_value='extrapolate')
            RH_interp_func = interp1d(p_env, RH_env, kind='linear', fill_value='extrapolate', bounds_error=False)
            
            T_fine = T_interp_func(p_fine)
            RH_fine = RH_interp_func(p_fine)
            RH_fine = np.clip(RH_fine, 0.05, 1.0)  # limita valori fisici
            
            print(f"  Interpolazione: {len(p_env)} livelli → {len(p_fine)} livelli (risoluzione 10 hPa)")
        else:
            T_fine = T_env
            RH_fine = RH_env
            p_fine = p_env
        
        # Calcola SBCAPE (surface-based)
        Td_display = f"{Td_surface_C:.1f}" if Td_surface_C is not None else "N/A"
        print(f"  Sollevamento particella: T={T_surface_C:.1f}°C, Td={Td_display}°C, p={p_surface:.1f}hPa, RH={RH_surface*100:.0f}%")
        T_parcel_sb, p_lcl_sb = lift_parcel(T_surface_K, p_surface, q_surface, p_fine)
        result_sb = calcola_cape_from_profile(T_parcel_sb, p_fine, T_fine, RH_fine, q_surface, p_lcl_sb)
        
        # Calcola MUCAPE (most unstable)
        print(f"  Cercando livello più instabile (MUCAPE)...")
        result_mu = calcola_mucape(data, station_data, T_fine, p_fine, RH_fine)
        
        # Calcola wind shear
        shear = calcola_wind_shear(data, current_hour_idx, station_data)
        
        # Calcola Lifted Index
        idx_500 = None
        for i, p in enumerate(p_fine):
            if abs(p - 500) < 15:
                idx_500 = i
                break
        
        if idx_500 is not None:
            li = (T_fine[idx_500] - T_parcel_sb[idx_500])
        else:
            li = 0
        
        # Stampa risultati
        print(f"  LCL: {p_lcl_sb:.1f} hPa")
        if result_sb['lfc_pressure']:
            print(f"  LFC: {result_sb['lfc_pressure']:.1f} hPa")
            print(f"  EL: {result_sb['el_pressure']:.1f} hPa" if result_sb['el_pressure'] else "  EL: top atmosfera")
        else:
            print(f"  LFC: non trovato (atmosfera stabile)")
        
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
            "location": f"La Spezia ({LAT}, {LON}) - {ELEVATION}m",
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
        
        # Validazione fisica
        warnings = validate_results(results, T_surface_C)
        if warnings:
            results['warnings'] = warnings
            for w in warnings:
                print(w)
        
        return results
        
    except Exception as e:
        print(f"Errore calcolo SBCAPE: {e}")
        import traceback
        traceback.print_exc()
        return None

def calcola_severe_score(results, raffica_kmh=0):
    """
    Calcola Severe Weather Score combinando multipli parametri.
    ATTENZIONE: Questo indice è una composizione custom, NON standardizzata in letteratura scientifica.
    I valori sono solo indicativi e non sostituiscono indici ufficiali come STP, SCP, DCP.
    Score >= 7: Supercelle possibili
    Score >= 5: Temporali severi
    Score >= 3: Temporali forti
    """
    score = 0
    reasons = []
    
    sbcape = results.get('sbcape', 0)
    mucape = results.get('mucape', 0)
    cin = abs(results.get('cin', 0))
    shear = results.get('bulk_shear', 0)
    
    # CAPE component (usa il maggiore tra SB e MU)
    max_cape = max(sbcape, mucape) if mucape else sbcape
    
    if max_cape > 3000:
        score += 4
        reasons.append(f"CAPE estremo ({max_cape:.0f} J/kg)")
    elif max_cape > 2500:
        score += 3
        reasons.append(f"CAPE molto forte ({max_cape:.0f} J/kg)")
    elif max_cape > 1500:
        score += 2
        reasons.append(f"CAPE forte ({max_cape:.0f} J/kg)")
    elif max_cape > 1000:
        score += 1
        reasons.append(f"CAPE moderato ({max_cape:.0f} J/kg)")
    
    # CIN component (cap break)
    if cin < 50:
        score += 2
        reasons.append("CAP debole/assente")
    elif cin < 100:
        score += 1
        reasons.append("CAP moderato")
    
    # Wind shear
    if shear and shear > 15:
        score += 3
        reasons.append(f"Shear elevato ({shear:.1f} m/s)")
    elif shear and shear > 10:
        score += 2
        reasons.append(f"Shear moderato ({shear:.1f} m/s)")
    
    # Wind gust (proxy per convezione già in atto)
    if raffica_kmh > 60:
        score += 2
        reasons.append(f"Raffiche forti ({raffica_kmh:.0f} km/h)")
    elif raffica_kmh > 40:
        score += 1
        reasons.append(f"Raffiche moderate ({raffica_kmh:.0f} km/h)")
    
    # Determina livello warning
    if score >= 7:
        level = "⚡🌪️ ALLERTA MASSIMA: RISCHIO SUPERCELLE/TORNADO"
    elif score >= 5:
        level = "⚡ ALLERTA: TEMPORALI SEVERI PROBABILI"
    elif score >= 3:
        level = "⚡ AVVISO: TEMPORALI FORTI POSSIBILI"
    else:
        level = None
    
    return {
        'score': score,
        'level': level,
        'reasons': reasons
    }

def main():
    print("=" * 70)
    print("📊 CALCOLO AVANZATO SBCAPE/MUCAPE & PARAMETRI CONVETTIVI v2.0")
    print("=" * 70)
    print(f"Coordinate: {LAT}°N, {LON}°E")
    print(f"Elevazione: {ELEVATION} m s.l.m.")
    print(f"Miglioramenti: Profilo RH reale, Interpolazione, MUCAPE, Wind Shear")
    print()
    
    # Leggi dati dalla stazione meteo con retry
    print("📡 Lettura dati dalla stazione meteo Tuya (con retry)...")
    station_data = fetch_station_data_with_retry(max_retries=3)
    
    if not station_data:
        print("⚠️  Stazione non disponibile, userò dati modello come fallback")
    
    # Scarica profilo verticale con cache
    print("⏳ Scaricando profilo verticale da Open-Meteo (con cache)...")
    data = fetch_profile_cached()
    
    if not data:
        print("✗ Errore nel fetching dei dati")
        return
    
    # Calcola SBCAPE avanzato
    print("⚙️  Calcolando SBCAPE, MUCAPE, CIN e parametri convettivi...")
    risultato = calcola_sbcape_advanced(data, station_data)
    
    if not risultato:
        print("✗ Errore nel calcolo")
        return
    
    # Severe Weather Score
    raffica = station_data['wind_gust'] if station_data else 0
    severe = calcola_severe_score(risultato, raffica)
    risultato['severe_score'] = severe['score']
    if severe['level']:
        risultato['severe_warning'] = severe['level']
        risultato['severe_reasons'] = severe['reasons']
    
    # Stampa risultati
    print()
    print("=" * 70)
    print("📈 RISULTATI")
    print("=" * 70)
    print(f"SBCAPE:         {risultato['sbcape']:>8.1f} J/kg")
    if risultato.get('mucape'):
        print(f"MUCAPE:         {risultato['mucape']:>8.1f} J/kg (livello {risultato['mu_level']:.0f} hPa)")
    print(f"CIN:            {risultato['cin']:>8.1f} J/kg")
    print(f"Lifted Index:   {risultato['lifted_index']:>8.1f} °C")
    if risultato.get('bulk_shear'):
        print(f"Bulk Shear:     {risultato['bulk_shear']:>8.1f} m/s")
    print()
    print(f"LCL:            {risultato['lcl_pressure']:>8.1f} hPa")
    if risultato.get('lfc_pressure'):
        print(f"LFC:            {risultato['lfc_pressure']:>8.1f} hPa")
    else:
        print(f"LFC:            {'N/A':>8}")
    if risultato.get('el_pressure'):
        print(f"EL:             {risultato['el_pressure']:>8.1f} hPa")
    else:
        print(f"EL:             {'N/A':>8}")
    
    # Severe Weather Score
    if severe['level']:
        print()
        print("=" * 70)
        print(f"{severe['level']}")
        print("=" * 70)
        print(f"Severe Score: {severe['score']}/12")
        print("\nFattori:")
        for reason in severe['reasons']:
            print(f"  • {reason}")
    
    # Interpretazione
    print()
    print("=" * 70)
    print("💬 INTERPRETAZIONE")
    print("=" * 70)
    max_cape = max(risultato['sbcape'], risultato.get('mucape') or 0)
    cin_val = abs(risultato['cin'])
    
    if max_cape < 300:
        cape_desc = "Molto debole - Atmosfera stabile"
    elif max_cape < 1000:
        cape_desc = "Debole - Convezione limitata"
    elif max_cape < 2500:
        cape_desc = "Moderata - Temporali possibili"
    elif max_cape < 4000:
        cape_desc = "Forte - Temporali intensi probabili"
    else:
        cape_desc = "Estrema - Supercelle e tornado possibili"
    
    if cin_val < 50:
        cin_desc = "Debole - Convezione facilmente innescabile"
    elif cin_val < 150:
        cin_desc = "Moderata - Serve trigger per innescare"
    else:
        cin_desc = "Forte - Convezione inibita (cap forte)"
    
    print(f"CAPE: {cape_desc}")
    print(f"CIN:  {cin_desc}")
    print()
    
    # Salva JSON
    with open(FILE_SBCAPE, "w") as f:
        json.dump(risultato, f, indent=4)
    
    print(f"✓ Risultati salvati in {FILE_SBCAPE}")
    print("=" * 70)

if __name__ == "__main__":
    main()
