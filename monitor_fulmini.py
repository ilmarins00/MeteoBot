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
import re
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

    # Formati di subscription da tentare (diverse versioni del protocollo Blitzortung)
    SUBSCRIPTION_MSGS = [
        json.dumps({"a": 111}),          # protocollo v2 più comune
        json.dumps({"a": BLITZORTUNG_REGION}),  # regione Europa (1)
        json.dumps({"a": 0}),             # worldwide fallback
    ]

    for ws_url in BLITZORTUNG_WS_URLS:
        for sub_msg in SUBSCRIPTION_MSGS:
            try:
                print(f"Connessione a {ws_url} (sub={sub_msg}) ...")
                ws = websocket.create_connection(
                    ws_url,
                    timeout=15,
                    header=[
                        "Origin: https://www.blitzortung.org",
                        "User-Agent: Mozilla/5.0",
                    ],
                    sslopt={"check_hostname": False, "cert_reqs": 0},
                )

                # Alcuni server inviano un messaggio di benvenuto — leggi prima di sottoscrivere
                ws.settimeout(3)
                try:
                    greeting = ws.recv()
                    print(f"  Server greeting: {greeting[:80] if greeting else '(vuoto)'}")
                except Exception:
                    pass  # nessun greeting, va bene lo stesso

                # Invia subscription
                ws.send(sub_msg)
                print(f"Connesso, ascolto per {duration_seconds}s ...")

                start = time.time()
                ws.settimeout(5)
                connected = True

                while time.time() - start < duration_seconds:
                    try:
                        raw = ws.recv()
                        if not raw:
                            continue

                        # Blitzortung può inviare dati con timestamp in formato
                        # non-JSON standard (es. 1234567890123456789 senza virgolette).
                        # Tentiamo parsing JSON; se fallisce, proviamo un fix.
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            # Log solo i primi messaggi malformati per debug
                            if total_received == 0:
                                print(f"  Raw non-JSON (primo msg): {raw[:120]}")
                            # Prova a sistemare numeri grandi non quotati
                            fixed = re.sub(r':\s*(\d{16,})\s*([,}])', r':"\1"\2', raw)
                            try:
                                data = json.loads(fixed)
                            except json.JSONDecodeError:
                                continue  # Messaggio irrecuperabile, skip

                        total_received += 1

                        lat = data.get("lat")
                        lon = data.get("lon")
                        if lat is None or lon is None:
                            continue

                        dist = haversine_km(LATITUDE, LONGITUDE, lat, lon)
                        if dist <= radius_km:
                            strike_time = data.get("time", 0)
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
                    except (ValueError, KeyError, TypeError) as e:
                        # Errori di parsing dati — non fatali, continua
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

                # Se abbiamo ricevuto almeno qualcosa, ritorna subito
                if total_received > 0 or (connected and time.time() - start >= duration_seconds):
                    return strikes_nearby

                # Altrimenti prova la prossima subscription/server
                print("Nessun dato ricevuto, provo combinazione successiva...")

            except Exception as e:
                print(f"Errore connessione {ws_url}: {e}")
                continue

    print("Impossibile ricevere dati da Blitzortung (tutti i server/protocolli falliti)")
    return strikes_nearby


def collect_strikes_openmeteo(radius_km: float = 20.0) -> List[Dict[str, Any]]:
    """
    Fallback: usa Open-Meteo per rilevare temporali in corso tramite WMO weather code.

    WMO codes rilevanti:
      95 = Temporale lieve/moderato
      96 = Temporale con grandine lieve
      99 = Temporale con grandine forte

    In assenza di dati reali di posizione, genera scariche "virtuali" posizionate
    nel cerchio di osservazione (solo per trigger notifica). La fonte viene indicata
    chiaramente nel messaggio.
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
        # Prendi il codice più critico tra corrente e ultima ora
        all_codes = [current_code] + (hourly_codes if isinstance(hourly_codes, list) else [])
        max_code = max((c for c in all_codes if isinstance(c, int)), default=0)

        THUNDERSTORM_CODES = {95, 96, 99}
        if max_code not in THUNDERSTORM_CODES:
            print(f"Open-Meteo: weather_code={max_code} (nessun temporale)")
            return []

        # Mappa codice → stima scariche (per superare la soglia)
        stima = {
            95: thresholds.LIGHTNING_STRIKE_THRESHOLD + 2,   # lieve/moderato
            96: thresholds.LIGHTNING_STRIKE_THRESHOLD * 3,  # con grandine
            99: thresholds.LIGHTNING_STRIKE_THRESHOLD * 5,  # con grandine forte
        }.get(max_code, thresholds.LIGHTNING_STRIKE_THRESHOLD + 1)

        print(f"Open-Meteo: weather_code={max_code} → TEMPORALE, stima ~{stima} scariche")

        # Genera scariche virtuali distribuite nel raggio
        now = datetime.now(TZ_ROME)
        virtual_strikes = []
        for i in range(stima):
            # Punto casuale nel cerchio entro raggio_km
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


def fetch_rainviewer_image() -> Tuple[Optional[bytes], Optional[str]]:
    """Scarica l'immagine radar composita più recente centrata su La Spezia.
    Restituisce (image_bytes, radar_time_str) o (None, None)."""
    try:
        r = requests.get(RAINVIEWER_API, timeout=10)
        r.raise_for_status()
        data = r.json()
        radar_list = data.get("radar", {}).get("past", [])
        if not radar_list:
            return None, None
        latest = radar_list[-1]
        ts = latest.get("time", 0)
        # Timestamp radar in ora locale
        radar_dt = datetime.fromtimestamp(ts, tz=TZ_ROME)
        radar_time_str = radar_dt.strftime("%d/%m/%Y %H:%M")
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
            return None, radar_time_str
        return img_resp.content, radar_time_str
    except Exception as e:
        print(f"Errore fetch radar: {e}")
        return None, None


def build_message(
    strikes: List[Dict], window_minutes: int, radar_time: Optional[str] = None
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
    )

    # Nota sulla fonte
    source = strikes[0].get("source", "blitzortung")
    if source == "openmeteo":
        wmo = strikes[0].get("wmo_code", 95)
        wmo_labels = {95: "Temporale lieve/moderato", 96: "Temporale con grandine", 99: "Temporale con grandine forte"}
        msg += (
            f"ℹ️ _Dati da Open-Meteo (WMO {wmo}: {wmo_labels.get(wmo, 'Temporale')})_\n"
            f"_Le posizioni sono stime – Blitzortung non disponibile_\n\n"
        )
    else:
        msg += f"📡 Fonte: Blitzortung.org (rete europea)\n\n"

    radar_label = f"RainViewer · {radar_time}" if radar_time else "RainViewer"
    msg += f"🗺️ [Mappa fulmini in tempo reale]({LIGHTNINGMAPS_URL})\n"
    msg += f"📡 Radar: {radar_label}"
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


def run_analysis(force: bool = False, listen_seconds: int = 120) -> Optional[Dict[str, Any]]:
    """Esegue l'analisi fulmini completa.
    Ritorna un dict con {message, image, radar_time, strikes, n} se c'è un'allerta,
    oppure None se non c'è nulla da inviare."""
    radius = thresholds.LIGHTNING_RADIUS_KM
    threshold_count = thresholds.LIGHTNING_STRIKE_THRESHOLD
    window_min = thresholds.LIGHTNING_WINDOW_MINUTES

    print(
        f"Monitor fulmini: raggio {radius} km, "
        f"soglia {threshold_count} scariche/{window_min} min, "
        f"ascolto {listen_seconds}s"
    )

    # 1. Raccolta scariche via WebSocket Blitzortung
    new_strikes = collect_strikes_websocket(
        duration_seconds=listen_seconds,
        radius_km=radius,
    )

    # 2. Fallback Open-Meteo se Blitzortung non ha fornito dati
    ws_fallito = len(new_strikes) == 0
    if ws_fallito:
        print("WebSocket senza dati → provo fallback Open-Meteo...")
        new_strikes = collect_strikes_openmeteo(radius_km=radius)

    # 3. Combina con scariche recenti dallo stato (per copertura finestra completa)
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

    # 4. Aggiorna stato con scariche recenti
    cutoff = datetime.now(TZ_ROME) - timedelta(minutes=window_min)
    recent_valid = []
    for s in all_strikes:
        try:
            t = datetime.fromisoformat(s["time"])
            if t >= cutoff:
                recent_valid.append(s)
        except Exception:
            recent_valid.append(s)

    state["last_check_ts"] = datetime.now(TZ_ROME).isoformat()
    state["recent_strikes"] = recent_valid[-200:]
    state["total_in_window"] = len(recent_valid)

    n = len(recent_valid)
    print(f"Scariche nella finestra {window_min} min: {n} (soglia: {threshold_count})")

    if n < threshold_count:
        print("Sotto soglia, nessuna notifica")
        state["status"] = "ok"
        save_state(state)
        return None

    print(f"⚡ SOGLIA SUPERATA: {n} scariche entro {radius} km!")

    if not should_send(state, n, force):
        save_state(state)
        return None

    radar_img, radar_time = fetch_rainviewer_image()
    msg = build_message(recent_valid, window_min, radar_time)
    save_state(state)

    return {
        "message": msg,
        "image": radar_img,
        "radar_time": radar_time,
        "strikes": recent_valid,
        "n": n,
    }


def mark_sent(result: Dict[str, Any]):
    """Aggiorna lo stato dopo un invio Telegram riuscito."""
    state = load_state()
    state["status"] = "alert"
    state["last_send_ts"] = datetime.now(TZ_ROME).isoformat()
    state["last_strike_count"] = result["n"]
    save_state(state)
    print("Fulmini: stato aggiornato")


def main():
    force = "--force" in sys.argv
    listen_mode = "--listen" in sys.argv

    window_min = thresholds.LIGHTNING_WINDOW_MINUTES
    listen_seconds = window_min * 60 if listen_mode else 120

    result = run_analysis(force=force, listen_seconds=listen_seconds)
    if result is None:
        return
    send_telegram(result["message"], result.get("image"))
    mark_sent(result)


if __name__ == "__main__":
    main()
