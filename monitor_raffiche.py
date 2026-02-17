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

def get_wind_gust():
    try:
        token_url = "/v1.0/token?grant_type=1"
        r = requests.get(ENDPOINT + token_url, headers=get_auth_headers("GET", token_url)).json()
        token = r['result']['access_token']
        status_url = f"/v1.0/devices/{DEVICE_ID}/status"
        res = requests.get(ENDPOINT + status_url, headers=get_auth_headers("GET", status_url, token)).json()
        if not res.get("success"): return None
        d = {item['code']: item['value'] for item in res.get("result", [])}
        return d.get('windspeed_gust', 0) / 10
    except Exception as e:
        print(f"Errore API: {e}")
        return None

def update_json_max(gust):
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
                    existing = contenuto.get("gust")
                elif isinstance(contenuto, (int, float)):
                    existing = contenuto
                    existing_hour = None
        except:
            existing = None
            existing_hour = None

    # se il file si riferisce a un'ora diversa o non c'è ora, consideriamo reset
    if existing_hour != hour_key:
        existing = None

    # ora decidiamo se scrivere
    if existing is None or existing_hour != hour_key or gust > existing:
        # memorizziamo timestamp completo e valore
        with open(FILE_JSON, "w") as f:
            json.dump({"timestamp": now.isoformat(), "gust": gust}, f)
        if existing_hour != hour_key:
            print(f"Nuova ora rilevata, sovrascritto: {gust} a {hour_key}")
        else:
            print(f"Aggiornato: {gust} a {hour_key}")
    else:
        print(f"Nessuna raffica maggiore ({gust} <= {existing}), file non aggiornato")

if __name__ == "__main__":
    # Creiamo il file vuoto subito per "placare" Git; dovrà contenere un numero
    if not os.path.exists(FILE_JSON):
        with open(FILE_JSON, "w") as f:
            json.dump(0, f)
            
    for _ in range(4):
        gust = get_wind_gust()
        if gust is not None:
            update_json_max(gust)
        time.sleep(15)
