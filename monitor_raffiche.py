import time
import requests
import json
from datetime import datetime
import os

from config import (
    TUYA_ACCESS_ID as ACCESS_ID,
    TUYA_ACCESS_SECRET as ACCESS_SECRET,
    TUYA_ENDPOINT as ENDPOINT,
    TUYA_DEVICE_ID as DEVICE_ID,
    FILE_RAFFICA as FILE_JSON
)
from utils import fetch_wmo_station_data_laspezia

def get_auth_headers(method, url, token=None, body=""):
    import hmac, hashlib
    t = str(int(time.time() * 1000))
    content_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    string_to_sign = f"{method}\n{content_hash}\n\n{url}"
    prefix = ACCESS_ID + token if token else ACCESS_ID
    sign_str = prefix + t + string_to_sign
    sign = hmac.new(ACCESS_SECRET.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest().upper()
    headers = {
        'client_id': ACCESS_ID,
        'sign': sign,
        't': t,
        'sign_method': 'HMAC-SHA256',
        'Content-Type': 'application/json'
    }
    if token:
        headers['access_token'] = token
    return headers


def request_json(url, headers, label, retries=3, timeout=20, delay=2):
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Errore API Tuya ({label}) tentativo {attempt}/{retries}: {e}")
        except ValueError as e:
            print(f"Risposta JSON non valida ({label}) tentativo {attempt}/{retries}: {e}")

        if attempt < retries:
            time.sleep(delay)

    return None

def get_wind_avg():
    def _fallback_avg():
        data = fetch_wmo_station_data_laspezia()
        if not data:
            return None
        avg = data.get("wind_speed")
        if not isinstance(avg, (int, float)):
            return None
        print(
            "✓ Vento medio da stazione esterna WMO: "
            f"{avg:.1f} km/h ({data.get('station_id')} - {data.get('station_name')})"
        )
        return float(avg)

    # Verifica che le credenziali Tuya siano configurate
    if not ACCESS_ID or not ACCESS_SECRET or not DEVICE_ID:
        print("✗ TUYA non configurato: uso fallback da stazione esterna WMO")
        return _fallback_avg()

    token_url = "/v1.0/token?grant_type=1"
    r = request_json(
        ENDPOINT + token_url,
        get_auth_headers("GET", token_url),
        "token"
    )
    if r is None:
        return _fallback_avg()

    if not r or not r.get("success") or "result" not in r or "access_token" not in r["result"]:
        print(f"Errore Token Tuya: risposta non valida o credenziali errate. Dettaglio: {r}")
        return _fallback_avg()

    token = r["result"]["access_token"]
    status_url = f"/v1.0/devices/{DEVICE_ID}/status"
    res = request_json(
        ENDPOINT + status_url,
        get_auth_headers("GET", status_url, token),
        "status"
    )
    if res is None:
        return _fallback_avg()

    if not res or not res.get("success") or "result" not in res:
        print(f"Errore lettura device Tuya: risposta non valida. Dettaglio: {res}")
        return _fallback_avg()

    d = {item.get('code'): item.get('value') for item in res.get("result", []) if isinstance(item, dict)}
    avg_raw = d.get('windspeed_avg')

    if avg_raw is None or avg_raw == "":
        print("Valore 'windspeed_avg' non presente nella risposta Tuya")
        return _fallback_avg()

    try:
        return float(avg_raw) / 10
    except (TypeError, ValueError):
        print(f"Valore 'windspeed_avg' non numerico: {avg_raw}")
        return _fallback_avg()

def update_json(avg):
    now = datetime.now()
    hour_key = now.strftime("%Y-%m-%d %H")
    existing = None
    existing_hour = None

    # Assicurati che la cartella esista (se non siamo nella root)
    os.makedirs(os.path.dirname(FILE_JSON) if os.path.dirname(FILE_JSON) else ".", exist_ok=True)

    # carica dato se presente
    if os.path.exists(FILE_JSON):
        try:
            with open(FILE_JSON, "r") as f:
                contenuto = json.load(f)
                if isinstance(contenuto, dict):
                    # supporto formati vecchi
                    if "timestamp" in contenuto:
                        try:
                            dt = datetime.fromisoformat(contenuto.get("timestamp"))
                            existing_hour = dt.strftime("%Y-%m-%d %H")
                        except Exception:
                            existing_hour = contenuto.get("hour")
                    else:
                        existing_hour = contenuto.get("hour")
                    existing = contenuto.get("avg", contenuto.get("gust"))
                elif isinstance(contenuto, (int, float)):
                    existing = contenuto
                    existing_hour = None
        except:
            existing = None
            existing_hour = None

    # se il file si riferisce a un'ora diversa o non c'è ora, consideriamo reset
    if existing_hour != hour_key:
        existing = None

    # ora decidiamo se scrivere (salva ultimo valore medio)
    if existing is None or existing_hour != hour_key:
        with open(FILE_JSON, "w") as f:
            json.dump({"timestamp": now.isoformat(), "avg": avg}, f)
        if existing_hour != hour_key:
            print(f"Nuova ora rilevata, sovrascritto: {avg} a {hour_key}")
        else:
            print(f"Salvato vento medio: {avg} a {hour_key}")
    else:
        # Aggiorna sempre con l'ultimo valore medio
        with open(FILE_JSON, "w") as f:
            json.dump({"timestamp": now.isoformat(), "avg": avg}, f)
        print(f"Aggiornato vento medio: {avg} km/h")

if __name__ == "__main__":
    # Creiamo il file vuoto subito per "placare" Git; dovrà contenere un numero
    if not os.path.exists(FILE_JSON):
        with open(FILE_JSON, "w") as f:
            json.dump(0, f)
            
    for _ in range(4):
        avg = get_wind_avg()
        if avg is not None:
            update_json(avg)
        time.sleep(15)
