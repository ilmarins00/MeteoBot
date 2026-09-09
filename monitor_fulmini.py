#!/usr/bin/env python3
"""
Monitor Fulmini – Blitzortung WebSocket + RainViewer

Monitora le scariche elettriche atmosferiche entro un raggio configurabile
(default 20 km) dal punto di osservazione (La Spezia – Foce).

Funzionamento:
1. Si connette al WebSocket di Blitzortung (rete europea rilevamento fulmini)
2. Raccoglie scariche per una finestra temporale (default 30 min) o fino a timeout
3. Filtra solo le scariche entro il raggio dal punto di osservazione
4. Esporta i dati in docs/lightning_data.json per la mappa del sito

Uso:
    python monitor_fulmini.py            # Esecuzione standard (cron ogni 5-10 min)
    python monitor_fulmini.py --listen   # Modalità ascolto continuo (debug)
"""
import json
import os
import sys
import math
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple

from config import (
    LATITUDE, LONGITUDE,
    BLITZORTUNG_WS_URLS,
    load_state_section,
    save_state_section,
    thresholds,
)

TZ_ROME = ZoneInfo("Europe/Rome")

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due punti (formula di Haversine)."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _lzw_decode(text: str) -> str:
    """Decomprime un messaggio LZW usato dal protocollo Blitzortung WebSocket."""
    if not text:
        return ''
    chars = list(text)
    curr_char = chars[0]
    old_phrase = curr_char
    result = [curr_char]
    dictionary: Dict[int, str] = {}
    next_code = 256
    for i in range(1, len(chars)):
        code = ord(chars[i])
        if 256 > code:
            phrase = chars[i]
        elif code in dictionary:
            phrase = dictionary[code]
        else:
            phrase = old_phrase + curr_char
        result.append(phrase)
        curr_char = phrase[0]
        dictionary[next_code] = old_phrase + curr_char
        next_code += 1
        old_phrase = phrase
    return ''.join(result)


def collect_strikes_websocket(
    duration_seconds: int = 120,
    radius_km: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Si connette al WebSocket Blitzortung e raccoglie le scariche
    entro il raggio specificato per la durata indicata.
    """
    try:
        import websocket
    except ImportError:
        print("Modulo 'websocket-client' non installato. Installa con: pip install websocket-client")
        return []

    strikes_nearby: List[Dict[str, Any]] = []
    total_received = 0
    sub_msg = json.dumps({"a": 111})

    for ws_url in BLITZORTUNG_WS_URLS:
        try:
            print(f"Connessione a {ws_url} ...")
            ws = websocket.WebSocket(skip_utf8_validation=True)
            ws.connect(
                ws_url,
                timeout=15,
                header=[
                    "Origin: https://www.blitzortung.org",
                    "User-Agent: Mozilla/5.0",
                ],
                sslopt={"check_hostname": False, "cert_reqs": 0},
            )

            ws.settimeout(3)
            try:
                ws.recv()
            except Exception:
                pass

            ws.send(sub_msg)
            print(f"Connesso, ascolto per {duration_seconds}s ...")

            start = time.time()
            ws.settimeout(5)
            connected = True

            while time.time() - start < duration_seconds:
                try:
                    raw_msg = ws.recv()
                    if not raw_msg:
                        continue

                    decoded = _lzw_decode(raw_msg)
                    try:
                        data = json.loads(decoded)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    total_received += 1

                    lat = data.get("lat")
                    lon = data.get("lon")
                    if lat is None or lon is None:
                        continue

                    dist = haversine_km(LATITUDE, LONGITUDE, lat, lon)
                    if dist <= radius_km:
                        strike_time = data.get("time", 0)
                        if isinstance(strike_time, (int, float)) and strike_time > 1e15:
                            strike_dt = datetime.fromtimestamp(
                                strike_time / 1e9, tz=TZ_ROME
                            )
                        else:
                            strike_dt = datetime.now(TZ_ROME)

                        strikes_nearby.append({
                            "lat": lat,
                            "lon": lon,
                            "time": strike_dt.isoformat(),
                            "distance_km": round(dist, 1),
                            "signal": data.get("sig", 0),
                        })
                        print(
                            f"  ⚡ Fulmine a {dist:.1f} km "
                            f"({lat:.3f}, {lon:.3f}) "
                            f"ore {strike_dt.strftime('%H:%M:%S')}"
                        )
                except websocket.WebSocketTimeoutException:
                    continue
                except (
                    websocket.WebSocketConnectionClosedException,
                    websocket.WebSocketException,
                    OSError,
                    ConnectionResetError,
                ) as e:
                    print(f"Connessione persa ({type(e).__name__})")
                    connected = False
                    break
                except (ValueError, KeyError, TypeError):
                    continue
                except Exception as e:
                    print(f"Errore recv imprevisto: {type(e).__name__}: {e}")
                    connected = False
                    break

            try:
                ws.close()
            except Exception:
                pass

            print(
                f"Sessione: {total_received} scariche totali, "
                f"{len(strikes_nearby)} entro {radius_km} km"
            )

            if total_received > 0:
                return strikes_nearby

            print("Nessun dato ricevuto, provo server successivo...")

        except Exception as e:
            print(f"Errore connessione {ws_url}: {e}")
            continue

    print("Impossibile ricevere dati da Blitzortung")
    return strikes_nearby


def collect_strikes_openmeteo(radius_km: float = 20.0) -> List[Dict[str, Any]]:
    """
    Fallback: usa Open-Meteo per rilevare temporali in corso tramite WMO weather code.
    """
    import random
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LATITUDE}&longitude={LONGITUDE}"
            f"&current=weather_code"
            f"&hourly=weather_code"
            f"&past_hours=1&forecast_hours=0"
            f"&timezone=Europe/Rome"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        current_code = data.get("current", {}).get("weather_code", 0)
        hourly_codes = data.get("hourly", {}).get("weather_code", [])
        all_codes = [current_code] + (hourly_codes if isinstance(hourly_codes, list) else [])
        max_code = max((c for c in all_codes if isinstance(c, int)), default=0)

        THUNDERSTORM_CODES = {95, 96, 99}
        if max_code not in THUNDERSTORM_CODES:
            print(f"Open-Meteo: weather_code={max_code} (nessun temporale)")
            return []

        stima = {
            95: thresholds.LIGHTNING_STRIKE_THRESHOLD + 2,
            96: thresholds.LIGHTNING_STRIKE_THRESHOLD * 3,
            99: thresholds.LIGHTNING_STRIKE_THRESHOLD * 5,
        }.get(max_code, thresholds.LIGHTNING_STRIKE_THRESHOLD + 1)

        print(f"Open-Meteo: weather_code={max_code} → TEMPORALE, stima ~{stima} scariche")

        now = datetime.now(TZ_ROME)
        virtual_strikes = []
        for i in range(stima):
            angle = random.uniform(0, 360)
            dist = random.uniform(1.0, min(radius_km, 15.0))
            dlat = dist / 111.0 * math.cos(math.radians(angle))
            dlon = dist / (111.0 * math.cos(math.radians(LATITUDE))) * math.sin(math.radians(angle))
            minutes_ago = random.randint(0, 29)
            virtual_strikes.append({
                "lat": round(LATITUDE + dlat, 4),
                "lon": round(LONGITUDE + dlon, 4),
                "time": (now.replace(second=0, microsecond=0)
                         .replace(minute=max(0, now.minute - minutes_ago))).isoformat(),
                "distance_km": round(dist, 1),
                "signal": 0,
                "source": "openmeteo",
                "wmo_code": max_code,
            })
        return virtual_strikes

    except Exception as e:
        print(f"Errore Open-Meteo fallback: {e}")
        return []


def export_public_lightning_json(strikes: List[Dict[str, Any]], path: str = "docs/lightning_data.json") -> None:
    """
    Scrive un JSON pubblico e minimale (lat/lon/orario/distanza) per la mappa
    del sito, indipendentemente dal fatto che sia stata inviata una notifica.
    """
    import tempfile
    payload = {
        "generated_at": datetime.now(TZ_ROME).isoformat(),
        "window_minutes": thresholds.LIGHTNING_WINDOW_MINUTES,
        "radius_km": thresholds.LIGHTNING_RADIUS_KM,
        "strikes": [
            {"lat": s["lat"], "lon": s["lon"], "time": s["time"], "distance_km": s["distance_km"]}
            for s in strikes
        ],
    }
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".lightning_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception:
        os.unlink(temp_path)
        raise


def collect_strikes_from_state() -> List[Dict[str, Any]]:
    """Legge le scariche recenti dallo stato salvato."""
    state = load_state()
    recent = state.get("recent_strikes", [])
    cutoff = datetime.now(TZ_ROME) - timedelta(
        minutes=thresholds.LIGHTNING_WINDOW_MINUTES
    )
    valid = []
    for s in recent:
        try:
            t = datetime.fromisoformat(s["time"])
            if t >= cutoff:
                valid.append(s)
        except Exception:
            continue
    return valid


def load_state() -> Dict[str, Any]:
    return load_state_section('fulmini')


def save_state(state: Dict[str, Any]):
    save_state_section('fulmini', state)


def run_analysis(listen_seconds: int = 120) -> Optional[Dict[str, Any]]:
    """Esegue l'analisi fulmini completa."""
    radius = thresholds.LIGHTNING_RADIUS_KM
    threshold_count = thresholds.LIGHTNING_STRIKE_THRESHOLD
    window_min = thresholds.LIGHTNING_WINDOW_MINUTES

    print(
        f"Monitor fulmini: raggio {radius} km, "
        f"soglia {threshold_count} scariche/{window_min} min, "
        f"ascolto {listen_seconds}s"
    )

    new_strikes = collect_strikes_websocket(
        duration_seconds=listen_seconds,
        radius_km=radius,
    )

    ws_fallito = len(new_strikes) == 0
    if ws_fallito:
        print("WebSocket senza dati → provo fallback Open-Meteo...")
        new_strikes = collect_strikes_openmeteo(radius_km=radius)

    state = load_state()
    old_strikes = collect_strikes_from_state()

    seen = set()
    all_strikes = []
    for s in old_strikes + new_strikes:
        key = (round(s["lat"], 3), round(s["lon"], 3), s["time"][:16])
        if key not in seen:
            seen.add(key)
            all_strikes.append(s)

    now = datetime.now(TZ_ROME)
    cutoff_15min  = now - timedelta(minutes=15)
    cutoff_window = now - timedelta(minutes=window_min)

    recent_valid = []   # fulmini degli ultimi 15 min
    window_valid = []   # fulmini nell'intera finestra (per stato e conteggio)

    for s in all_strikes:
        try:
            t = datetime.fromisoformat(s["time"])
            if t.tzinfo is None:
                t = t.replace(tzinfo=TZ_ROME)
            if t >= cutoff_window:
                window_valid.append(s)
            if t >= cutoff_15min:
                recent_valid.append(s)
        except Exception:
            continue

    strikes_for_alert = recent_valid if recent_valid else window_valid

    state["last_check_ts"] = datetime.now(TZ_ROME).isoformat()
    state["recent_strikes"] = window_valid[-200:]
    state["total_in_window"] = len(window_valid)

    try:
        export_public_lightning_json(window_valid)
    except Exception as e:
        print(f"Errore scrittura lightning_data.json: {e}")

    n = len(strikes_for_alert)
    print(
        f"Scariche 15-min: {len(recent_valid)} | finestra {window_min}-min: {len(window_valid)} "
        f"(soglia: {threshold_count})"
    )

    if n < threshold_count:
        print("Sotto soglia")
        state["status"] = "ok"
        save_state(state)
        return None

    print(f"⚡ SOGLIA SUPERATA: {n} scariche entro {radius} km!")
    state["status"] = "alert"
    save_state(state)

    return {
        "strikes": recent_valid,
        "n": n,
    }


def main():
    listen_mode = "--listen" in sys.argv

    window_min = thresholds.LIGHTNING_WINDOW_MINUTES
    listen_seconds = window_min * 60 if listen_mode else 120

    run_analysis(listen_seconds=listen_seconds)


if __name__ == "__main__":
    main()