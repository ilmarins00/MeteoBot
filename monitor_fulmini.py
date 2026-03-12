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
    LIGHTNINGMAPS_URL,
    load_state_section,
    save_state_section,
    thresholds,
)

TZ_ROME = ZoneInfo("Europe/Rome")

# Raggio terrestre medio (km)
EARTH_RADIUS_KM = 6371.0


def reverse_geocode(lat: float, lon: float) -> str:
    """Ottiene il nome della località dalle coordinate usando Nominatim (OpenStreetMap).
    Restituisce il nome del luogo o le coordinate formattate come fallback."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat, "lon": lon,
                "format": "json", "zoom": 14,
                "accept-language": "it",
            },
            headers={"User-Agent": "MeteoBot/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        # Prova diversi livelli di dettaglio
        name = (
            addr.get("village")
            or addr.get("town")
            or addr.get("hamlet")
            or addr.get("suburb")
            or addr.get("city")
            or addr.get("municipality")
            or addr.get("county")
        )
        if name:
            # Aggiungi il comune se diverso e disponibile
            comune = addr.get("city") or addr.get("town") or addr.get("municipality")
            if comune and comune != name:
                return f"{name} ({comune})"
            return name
    except Exception as e:
        print(f"Errore reverse geocoding: {e}")

    return f"{lat:.3f}°N, {lon:.3f}°E"


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
    """Decomprime un messaggio LZW usato dal protocollo Blitzortung WebSocket.
    Ogni carattere Unicode nel testo rappresenta un codice LZW."""
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

    Restituisce lista di dict con lat, lon, time, distance_km.
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


def generate_lightning_map(
    strikes: List[Dict[str, Any]],
    radius_km: float = 30.0,
) -> Optional[bytes]:
    """Genera una mappa statica con i fulmini rilevati e cerchi di distanza.
    Restituisce l'immagine PNG come bytes, o None in caso di errore."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("matplotlib/numpy non disponibili, skip mappa")
        return None

    try:
        fig, ax = plt.subplots(1, 1, figsize=(6, 6), dpi=120)
        fig.patch.set_facecolor('#1a1a2e')
        ax.set_facecolor('#16213e')

        # Cerchi di distanza (5, 10, 20, 30 km)
        # Conversione km → gradi (approssimata alla latitudine locale)
        km_per_deg_lat = 111.0
        km_per_deg_lon = 111.0 * math.cos(math.radians(LATITUDE))

        circle_radii_km = [5, 10, 20, 30]
        for r_km in circle_radii_km:
            if r_km > radius_km:
                continue
            theta = np.linspace(0, 2 * np.pi, 100)
            cx = LONGITUDE + (r_km / km_per_deg_lon) * np.cos(theta)
            cy = LATITUDE + (r_km / km_per_deg_lat) * np.sin(theta)
            ax.plot(cx, cy, color='#4a90d9', linewidth=0.8, alpha=0.6)
            # Etichetta distanza
            ax.text(
                LONGITUDE, LATITUDE + r_km / km_per_deg_lat,
                f"{r_km} km", color='#7eb8da', fontsize=7,
                ha='center', va='bottom', alpha=0.8,
            )

        # Punto di osservazione
        ax.plot(LONGITUDE, LATITUDE, 'o', color='#00ff88', markersize=8, zorder=10)
        ax.plot(LONGITUDE, LATITUDE, 'o', color='#00ff88', markersize=14,
                alpha=0.3, zorder=9)

        # Fulmini
        if strikes:
            lats = [s["lat"] for s in strikes]
            lons = [s["lon"] for s in strikes]
            dists = [s["distance_km"] for s in strikes]

            # Colora per distanza: rosso = vicino, giallo = lontano
            colors = []
            for d in dists:
                ratio = min(d / radius_km, 1.0)
                if ratio < 0.33:
                    colors.append('#ff3333')  # rosso - vicino
                elif ratio < 0.66:
                    colors.append('#ffaa00')  # arancione - medio
                else:
                    colors.append('#ffff00')  # giallo - lontano

            ax.scatter(lons, lats, c=colors, s=25, marker='$⚡$',
                       zorder=8, alpha=0.9)

        # Limiti mappa: cerchio più grande + margine 10%
        margin_km = radius_km * 1.15
        ax.set_xlim(
            LONGITUDE - margin_km / km_per_deg_lon,
            LONGITUDE + margin_km / km_per_deg_lon,
        )
        ax.set_ylim(
            LATITUDE - margin_km / km_per_deg_lat,
            LATITUDE + margin_km / km_per_deg_lat,
        )

        ax.set_aspect('equal')
        ax.tick_params(colors='#888888', labelsize=7)
        ax.set_xlabel('Longitudine', color='#888888', fontsize=8)
        ax.set_ylabel('Latitudine', color='#888888', fontsize=8)

        n = len(strikes)
        closest = min((s["distance_km"] for s in strikes), default=0)
        ax.set_title(
            f"Fulmini rilevati: {n} scariche (min. {closest:.1f} km)",
            color='#e0e0e0', fontsize=10, pad=10,
        )

        # Griglia leggera
        ax.grid(True, alpha=0.15, color='#4a90d9', linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color('#333355')

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        print(f"Errore generazione mappa fulmini: {e}")
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
    closest_location = reverse_geocode(closest["lat"], closest["lon"])

    # Raggruppa per fasce
    entro_5 = sum(1 for d in distances if d <= 5)
    entro_10 = sum(1 for d in distances if 5 < d <= 10)
    entro_20 = sum(1 for d in distances if 10 < d <= 20)
    entro_30 = sum(1 for d in distances if 20 < d <= 30)

    # Intensità stimata
    if n >= 20:
        intensita = "🔴 TEMPORALE SEVERO"
    elif n >= 10:
        intensita = "🟠 TEMPORALE ATTIVO"
    elif n >= thresholds.LIGHTNING_STRIKE_THRESHOLD:
        intensita = "🟡 ATTIVITÀ ELETTRICA"
    else:
        intensita = "⚡ SCARICHE RILEVATE"

    # Distribuzione come testo continuo
    fasce = []
    if entro_5:
        fasce.append(f"{entro_5} entro 5 km")
    if entro_10:
        fasce.append(f"{entro_10} tra 5 e 10 km")
    if entro_20:
        fasce.append(f"{entro_20} tra 10 e 20 km")
    if entro_30:
        fasce.append(f"{entro_30} tra 20 e 30 km")
    distrib_text = ", ".join(fasce)

    msg = (
        f"⚡ *ALLERTA FULMINI – La Spezia*\n"
        f"{intensita}\n"
        f"📅 {now_str}\n\n"
        f"Rilevate *{n}* scariche elettriche entro {int(thresholds.LIGHTNING_RADIUS_KM)} km "
        f"negli ultimi {window_minutes} minuti, "
        f"la più vicina registrata a *{min_dist:.1f} km* dal punto di osservazione "
        f"nei pressi di {closest_location}, "
        f"distanza media {avg_dist:.1f} km. "
        f"Distribuzione: {distrib_text}."
    )

    source = strikes[0].get("source", "blitzortung")
    if source == "openmeteo":
        wmo = strikes[0].get("wmo_code", 95)
        wmo_labels = {95: "Temporale lieve/moderato", 96: "Temporale con grandine", 99: "Temporale con grandine forte"}
        msg += (
            f" Dati stimati da Open-Meteo (WMO {wmo}: {wmo_labels.get(wmo, 'Temporale')}), "
            f"le posizioni sono approssimate in assenza di Blitzortung."
        )
    else:
        msg += f" Fonte: Blitzortung.org, rete europea di rilevamento fulmini."

    msg += f"\n\n🗺️ [Mappa fulmini in tempo reale]({LIGHTNINGMAPS_URL})"
    return msg


def load_state() -> Dict[str, Any]:
    return load_state_section('fulmini')


def save_state(state: Dict[str, Any]):
    save_state_section('fulmini', state)


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
                files = {"photo": ("mappa_fulmini.png", io.BytesIO(image), "image/png")}
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

    # 4. Filtra scariche recenti (max 15 min)
    now = datetime.now(TZ_ROME)
    cutoff_fresh = now - timedelta(minutes=15)
    cutoff_window = now - timedelta(minutes=window_min)
    recent_valid = []
    for s in all_strikes:
        try:
            t = datetime.fromisoformat(s["time"])
            if t.tzinfo is None:
                t = t.replace(tzinfo=TZ_ROME)
            if t >= cutoff_fresh:
                recent_valid.append(s)
        except Exception:
            continue
    if not recent_valid:
        for s in all_strikes:
            try:
                t = datetime.fromisoformat(s["time"])
                if t.tzinfo is None:
                    t = t.replace(tzinfo=TZ_ROME)
                if t >= cutoff_window:
                    recent_valid.append(s)
            except Exception:
                continue

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

    radar_img = generate_lightning_map(recent_valid, radius_km=radius)
    msg = build_message(recent_valid, window_min)
    save_state(state)

    return {
        "message": msg,
        "image": radar_img,
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
