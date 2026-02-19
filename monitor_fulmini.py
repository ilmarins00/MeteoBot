#!/usr/bin/env python3
"""
Monitor Fulmini – Blitzortung WebSocket + RainViewer

Monitora le scariche elettriche atmosferiche entro un raggio configurabile
(default 20 km) dal punto di osservazione (La Spezia – Foce).

Funzionamento:
1. Si connette al WebSocket di Blitzortung (rete europea rilevamento fulmini)
2. Raccoglie scariche per una finestra temporale (default 30 min) o fino a timeout
3. Filtra solo le scariche entro il raggio dal punto di osservazione
4. Se il conteggio supera la soglia → scarica immagine radar RainViewer +
   genera link LightningMaps e invia notifica Telegram con foto + dettagli

Uso:
    python monitor_fulmini.py            # Esecuzione standard (cron ogni 5-10 min)
    python monitor_fulmini.py --force    # Forza invio anche se già notificato
    python monitor_fulmini.py --listen   # Modalità ascolto continuo (debug)
"""
import json
import os
import sys
import io
import math
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    LATITUDE, LONGITUDE,
    BLITZORTUNG_WS_URLS,
    BLITZORTUNG_REGION,
    RAINVIEWER_API,
    LIGHTNINGMAPS_URL,
    FILE_FULMINI_STATE,
    thresholds,
)

TZ_ROME = ZoneInfo("Europe/Rome")

# Raggio terrestre medio (km)
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


def collect_strikes_websocket(
    duration_seconds: int = 120,
    radius_km: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Si connette al WebSocket Blitzortung e raccoglie le scariche
    entro il raggio specificato per la durata indicata.

    Restituisce lista di dict con lat, lon, time, distance_km.
    """
    try:
        import websocket
    except ImportError:
        print("Modulo 'websocket-client' non installato. Installa con: pip install websocket-client")
        return []

    strikes_nearby: List[Dict[str, Any]] = []
    total_received = 0

    for ws_url in BLITZORTUNG_WS_URLS:
        try:
            print(f"Connessione a {ws_url} ...")
            ws = websocket.create_connection(
                ws_url,
                timeout=15,
                header={"Origin": "https://www.blitzortung.org"},
            )
            # Richiedi dati in tempo reale per la regione Europa
            ws.send(json.dumps({"a": BLITZORTUNG_REGION}))
            print(f"Connesso a {ws_url}, ascolto per {duration_seconds}s ...")

            start = time.time()
            ws.settimeout(5)  # timeout per ogni recv

            while time.time() - start < duration_seconds:
                try:
                    raw = ws.recv()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    total_received += 1

                    # Formato Blitzortung: {"lat": ..., "lon": ..., "time": ns_epoch, "sig": ...}
                    lat = data.get("lat")
                    lon = data.get("lon")
                    if lat is None or lon is None:
                        continue

                    dist = haversine_km(LATITUDE, LONGITUDE, lat, lon)
                    if dist <= radius_km:
                        strike_time = data.get("time", 0)
                        # time è in nanosecondi epoch
                        if strike_time > 1e15:
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
                    # Nessun dato in 5s, normale — continua ad attendere
                    continue
                except (
                    websocket.WebSocketConnectionClosedException,
                    websocket.WebSocketException,
                    OSError,
                    ConnectionResetError,
                ) as e:
                    # Connessione persa → esci dal loop, prova server successivo
                    print(f"Connessione persa ({type(e).__name__}), cambio server")
                    break
                except Exception as e:
                    # Qualsiasi altra eccezione imprevista: esci per sicurezza
                    print(f"Errore imprevisto recv: {e}")
                    break

            try:
                ws.close()
            except Exception:
                pass
            print(
                f"Sessione completata: {total_received} scariche totali, "
                f"{len(strikes_nearby)} entro {radius_km} km"
            )
            return strikes_nearby

        except Exception as e:
            print(f"Errore connessione {ws_url}: {e}")
            continue

    print("Impossibile connettersi a nessun server Blitzortung")
    return strikes_nearby


def collect_strikes_from_state() -> List[Dict[str, Any]]:
    """
    Alternativa: legge le scariche recenti dallo stato salvato precedentemente
    e le combina con quelle nuove per una finestra temporale più ampia.
    """
    state = load_state()
    recent = state.get("recent_strikes", [])
    cutoff = datetime.now(TZ_ROME) - timedelta(
        minutes=thresholds.LIGHTNING_WINDOW_MINUTES
    )
    # Filtra solo scariche nella finestra temporale
    valid = []
    for s in recent:
        try:
            t = datetime.fromisoformat(s["time"])
            if t >= cutoff:
                valid.append(s)
        except Exception:
            continue
    return valid


def fetch_rainviewer_image() -> Optional[bytes]:
    """Scarica l'immagine radar composita più recente centrata su La Spezia."""
    try:
        r = requests.get(RAINVIEWER_API, timeout=10)
        r.raise_for_status()
        data = r.json()
        radar_list = data.get("radar", {}).get("past", [])
        if not radar_list:
            return None
        latest = radar_list[-1]
        ts = latest.get("time", 0)
        z = 7
        n = 2 ** z
        x_tile = int((LONGITUDE + 180.0) / 360.0 * n)
        lat_rad = math.radians(LATITUDE)
        y_tile = int(
            (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
            / 2.0
            * n
        )
        tile_url = (
            f"https://tilecache.rainviewer.com/v2/radar/{ts}/512/{z}/{x_tile}/{y_tile}/2/1_1.png"
        )
        img_resp = requests.get(tile_url, timeout=15)
        img_resp.raise_for_status()
        if len(img_resp.content) < 500:
            return None
        return img_resp.content
    except Exception as e:
        print(f"Errore fetch radar: {e}")
        return None


def build_message(
    strikes: List[Dict], window_minutes: int
) -> str:
    """Costruisce il messaggio Telegram per allerta fulmini."""
    now_str = datetime.now(TZ_ROME).strftime("%d/%m/%Y %H:%M")
    n = len(strikes)

    # Statistiche distanza
    distances = [s["distance_km"] for s in strikes]
    min_dist = min(distances)
    avg_dist = sum(distances) / len(distances)
    closest = min(strikes, key=lambda s: s["distance_km"])

    # Raggruppa per fasce
    entro_5 = sum(1 for d in distances if d <= 5)
    entro_10 = sum(1 for d in distances if 5 < d <= 10)
    entro_20 = sum(1 for d in distances if 10 < d <= 20)

    # Intensità stimata
    if n >= 20:
        intensita = "🔴 TEMPORALE SEVERO"
    elif n >= 10:
        intensita = "🟠 TEMPORALE ATTIVO"
    elif n >= thresholds.LIGHTNING_STRIKE_THRESHOLD:
        intensita = "🟡 ATTIVITÀ ELETTRICA"
    else:
        intensita = "⚡ SCARICHE RILEVATE"

    msg = (
        f"⚡ *ALLERTA FULMINI – La Spezia*\n"
        f"{intensita}\n"
        f"📅 {now_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Scariche rilevate: *{n}* in {window_minutes} min\n"
        f"Più vicino: *{min_dist:.1f} km* ({closest['lat']:.3f}°N, {closest['lon']:.3f}°E)\n"
        f"Distanza media: {avg_dist:.1f} km\n\n"
        f"📊 *Distribuzione*\n"
        f"  0-5 km: {entro_5} scariche\n"
        f"  5-10 km: {entro_10} scariche\n"
        f"  10-20 km: {entro_20} scariche\n\n"
        f"🗺️ [Mappa fulmini in tempo reale]({LIGHTNINGMAPS_URL})\n"
        f"📡 Fonte: Blitzortung.org · Radar: RainViewer"
    )
    return msg


def load_state() -> Dict[str, Any]:
    if os.path.exists(FILE_FULMINI_STATE):
        try:
            with open(FILE_FULMINI_STATE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, Any]):
    with open(FILE_FULMINI_STATE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_send(state: Dict[str, Any], n_strikes: int, force: bool = False) -> bool:
    """Evita spam: non re-inviare se già inviato di recente per stesso livello."""
    if force:
        return True
    last_send = state.get("last_send_ts")
    if last_send:
        try:
            last_dt = datetime.fromisoformat(last_send)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=TZ_ROME)
            # Non re-inviare per 30 minuti, a meno che il numero non sia raddoppiato
            if datetime.now(TZ_ROME) - last_dt < timedelta(minutes=30):
                prev_n = state.get("last_strike_count", 0)
                if n_strikes < prev_n * 2:
                    print(
                        f"Notifica recente ({last_dt.strftime('%H:%M')}), "
                        f"conteggio simile ({n_strikes} vs {prev_n}), skip"
                    )
                    return False
        except Exception:
            pass
    return True


def send_telegram(text: str, image: Optional[bytes] = None):
    """Invia messaggio Telegram, opzionalmente con foto radar."""
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato, skip invio")
        return
    for chat_id in LISTA_CHAT:
        try:
            if image:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
                files = {"photo": ("radar_fulmini.png", io.BytesIO(image), "image/png")}
                data = {"chat_id": chat_id, "caption": text, "parse_mode": "Markdown"}
                resp = requests.post(url, data=data, files=files, timeout=15)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                data = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                }
                resp = requests.post(url, data=data, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("ok"):
                print(f"✓ Fulmini notifica inviata a {chat_id}")
            else:
                print(f"✗ Errore Telegram fulmini per {chat_id}: {payload}")
        except Exception as e:
            print(f"✗ Errore invio fulmini a {chat_id}: {e}")


def main():
    force = "--force" in sys.argv
    listen_mode = "--listen" in sys.argv

    radius = thresholds.LIGHTNING_RADIUS_KM
    threshold_count = thresholds.LIGHTNING_STRIKE_THRESHOLD
    window_min = thresholds.LIGHTNING_WINDOW_MINUTES

    # Durata ascolto WebSocket: in modalità standard è 2 minuti,
    # in modalità listen è la finestra completa
    listen_seconds = window_min * 60 if listen_mode else 120

    print(
        f"Monitor fulmini: raggio {radius} km, "
        f"soglia {threshold_count} scariche/{window_min} min, "
        f"ascolto {listen_seconds}s"
    )

    # 1. Raccolta scariche via WebSocket
    new_strikes = collect_strikes_websocket(
        duration_seconds=listen_seconds,
        radius_km=radius,
    )

    # 2. Combina con scariche recenti dallo stato (per copertura finestra completa)
    state = load_state()
    old_strikes = collect_strikes_from_state()

    # Unisci, evitando duplicati (per lat/lon arrotondati)
    seen = set()
    all_strikes = []
    for s in old_strikes + new_strikes:
        key = (round(s["lat"], 3), round(s["lon"], 3), s["time"][:16])
        if key not in seen:
            seen.add(key)
            all_strikes.append(s)

    # 3. Aggiorna stato con scariche recenti
    cutoff = datetime.now(TZ_ROME) - timedelta(minutes=window_min)
    recent_valid = []
    for s in all_strikes:
        try:
            t = datetime.fromisoformat(s["time"])
            if t >= cutoff:
                recent_valid.append(s)
        except Exception:
            recent_valid.append(s)  # conserva se non parsabile

    state["last_check_ts"] = datetime.now(TZ_ROME).isoformat()
    state["recent_strikes"] = recent_valid[-200:]  # limita dimensione
    state["total_in_window"] = len(recent_valid)

    n = len(recent_valid)
    print(f"Scariche nella finestra {window_min} min: {n} (soglia: {threshold_count})")

    if n < threshold_count:
        print("Sotto soglia, nessuna notifica")
        state["status"] = "ok"
        save_state(state)
        return

    # 4. Soglia superata!
    print(f"⚡ SOGLIA SUPERATA: {n} scariche entro {radius} km!")

    if not should_send(state, n, force):
        save_state(state)
        return

    # 5. Scarica immagine radar
    radar_img = fetch_rainviewer_image()

    # 6. Costruisci e invia messaggio
    msg = build_message(recent_valid, window_min)
    send_telegram(msg, radar_img)

    # 7. Aggiorna stato
    state["status"] = "alert"
    state["last_send_ts"] = datetime.now(TZ_ROME).isoformat()
    state["last_strike_count"] = n
    save_state(state)
    print("Stato salvato")


if __name__ == "__main__":
    main()
