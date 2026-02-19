#!/usr/bin/env python3
"""
Monitor Precipitazioni OMIRL – Zona La Spezia

Interroga l'API REST di OMIRL (Osservatorio Meteo-Idrologico Regione Liguria)
per ottenere i dati pluviometrici in tempo reale delle stazioni nel distretto SP.

Quando almeno una stazione supera la soglia (default 6 mm/h), scarica un'immagine
radar composita da RainViewer e invia una notifica Telegram con mappa e dettagli.

Esegue in modo idempotente: salva lo stato in `omirl_state.json` e non re-invia
per lo stesso evento se la notifica è già stata inviata nell'ultima ora.

Uso:
    python monitor_omirl.py            # Esecuzione standard (cron ogni 10-15 min)
    python monitor_omirl.py --force    # Forza invio anche se già notificato
"""
import requests
import json
import os
import io
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    LATITUDE, LONGITUDE,
    OMIRL_RAIN_ENDPOINT,
    OMIRL_DISTRICT_FILTER,
    RAINVIEWER_API,
    FILE_OMIRL_STATE,
    thresholds,
)

TZ_ROME = ZoneInfo("Europe/Rome")

# ── Stazioni di riferimento La Spezia (prioritarie nel messaggio) ──
STAZIONI_PRIORITARIE = {"SPZIA", "SPZIW", "FABIA", "PVENE", "MROSS", "LEVAN"}


def fetch_omirl_rain() -> Optional[List[Dict[str, Any]]]:
    """Scarica i dati pluviometrici OMIRL per tutte le stazioni liguri."""
    try:
        r = requests.get(OMIRL_RAIN_ENDPOINT, timeout=20, headers={
            "User-Agent": "MeteoBot/1.0",
            "Accept": "application/json",
        })
        r.raise_for_status()
        data = r.json()
        rows = data.get("tableRows", [])
        return rows
    except Exception as e:
        print(f"Errore fetch OMIRL: {e}")
        return None


def filter_sp_stations(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filtra solo le stazioni del distretto SP (La Spezia)."""
    return [r for r in rows if r.get("district") == OMIRL_DISTRICT_FILTER]


def find_exceeding_stations(
    stations: List[Dict[str, Any]], soglia_mm: float
) -> List[Dict[str, Any]]:
    """Restituisce le stazioni con pioggia ultima ora >= soglia."""
    exceeding = []
    for s in stations:
        try:
            val = float(s.get("last", 0) or 0)
        except (TypeError, ValueError):
            continue
        if val >= soglia_mm:
            exceeding.append({
                "code": s.get("code", "?"),
                "name": s.get("name", "Sconosciuta"),
                "last": val,
                "max": s.get("max"),
                "municipality": s.get("municipality", ""),
                "basin": s.get("basin", ""),
                "area": s.get("area", ""),
            })
    # Ordina per intensità decrescente
    exceeding.sort(key=lambda x: x["last"], reverse=True)
    return exceeding


def fetch_rainviewer_image() -> Tuple[Optional[bytes], Optional[str]]:
    """Scarica l'immagine radar composita più recente da RainViewer centrata su La Spezia.
    Restituisce (image_bytes, radar_time_str) o (None, None)."""
    try:
        r = requests.get(RAINVIEWER_API, timeout=10)
        r.raise_for_status()
        data = r.json()
        radar_list = data.get("radar", {}).get("past", [])
        if not radar_list:
            print("Nessun frame radar disponibile da RainViewer")
            return None, None
        # Prendi il frame più recente
        latest = radar_list[-1]
        ts = latest.get("time", 0)
        # Timestamp radar in ora locale
        radar_dt = datetime.fromtimestamp(ts, tz=TZ_ROME)
        radar_time_str = radar_dt.strftime("%d/%m/%Y %H:%M")
        # Tile zoom 7 centrato su La Spezia (~44.12, 9.80)
        import math
        z = 7
        n = 2 ** z
        x_tile = int((LONGITUDE + 180.0) / 360.0 * n)
        lat_rad = math.radians(LATITUDE)
        y_tile = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)

        tile_url = f"https://tilecache.rainviewer.com/v2/radar/{ts}/512/{z}/{x_tile}/{y_tile}/2/1_1.png"
        img_resp = requests.get(tile_url, timeout=15)
        img_resp.raise_for_status()
        if len(img_resp.content) < 500:
            print(f"Immagine radar troppo piccola ({len(img_resp.content)} bytes), skip")
            return None, radar_time_str
        return img_resp.content, radar_time_str
    except Exception as e:
        print(f"Errore fetch radar RainViewer: {e}")
        return None, None


def arpal_level(value_mm: float) -> Tuple[str, str]:
    """Determina il livello ARPAL e l'emoji per un'intensità oraria."""
    if value_mm >= thresholds.ARPAL_RAIN_1H_ROSSO:
        return "Rosso", "🔴"
    elif value_mm >= thresholds.ARPAL_RAIN_1H_ARANCIONE:
        return "Arancione", "🟠"
    elif value_mm >= thresholds.ARPAL_RAIN_1H_GIALLO:
        return "Giallo", "🟡"
    else:
        return "Verde", "🟢"


def build_message(exceeding: List[Dict], all_sp: List[Dict], radar_time: Optional[str] = None) -> str:
    """Costruisce il messaggio Telegram con dettaglio stazioni."""
    now_str = datetime.now(TZ_ROME).strftime("%d/%m/%Y %H:%M")
    max_station = exceeding[0]
    livello, emoji_lv = arpal_level(max_station["last"])

    header = (
        f"{emoji_lv}🌧️ *PRECIPITAZIONI INTENSE – Rete OMIRL*\n"
        f"Distretto La Spezia · {now_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Stazioni che superano la soglia
    lines = []
    for s in exceeding:
        _, em = arpal_level(s["last"])
        prio = " ⭐" if s["code"] in STAZIONI_PRIORITARIE else ""
        lines.append(
            f"{em} *{s['name']}* ({s['code']}){prio}\n"
            f"   Ultima ora: {s['last']:.1f} mm/h · Max: {s.get('max', '?')} mm/h\n"
            f"   Comune: {s['municipality']} · Bacino: {s['basin']}"
        )

    # Riepilogo tutte le SP
    n_totale = len(all_sp)
    n_pioggia = sum(1 for s in all_sp if float(s.get("last", 0) or 0) > 0)

    radar_label = f"RainViewer · {radar_time}" if radar_time else "RainViewer"
    footer = (
        f"\n📊 Stazioni SP: {n_pioggia}/{n_totale} con pioggia"
        f"\n🔗 Fonte: OMIRL – Regione Liguria"
        f"\n📡 Radar: {radar_label}"
    )

    return header + "\n".join(lines) + footer


def load_state() -> Dict[str, Any]:
    if os.path.exists(FILE_OMIRL_STATE):
        try:
            with open(FILE_OMIRL_STATE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, Any]):
    with open(FILE_OMIRL_STATE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_send(state: Dict[str, Any], exceeding: List[Dict], force: bool = False) -> bool:
    """Decide se inviare la notifica (evita spam per lo stesso evento)."""
    if force:
        return True
    last_send = state.get("last_send_ts")
    if last_send:
        try:
            last_dt = datetime.fromisoformat(last_send)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=TZ_ROME)
            # Non re-inviare se l'ultimo invio è stato meno di 50 minuti fa
            if datetime.now(TZ_ROME) - last_dt < timedelta(minutes=50):
                # Ma se il livello massimo è cambiato (peggiorato), invia comunque
                prev_max = state.get("max_rain_mm", 0)
                curr_max = exceeding[0]["last"] if exceeding else 0
                _, prev_lv = arpal_level(prev_max)
                _, curr_lv = arpal_level(curr_max)
                if curr_lv == prev_lv:
                    print("Notifica già inviata di recente con stesso livello, skip")
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
                files = {"photo": ("radar_omirl.png", io.BytesIO(image), "image/png")}
                data = {"chat_id": chat_id, "caption": text, "parse_mode": "Markdown"}
                resp = requests.post(url, data=data, files=files, timeout=15)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
                resp = requests.post(url, data=data, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("ok"):
                print(f"✓ OMIRL notifica inviata a {chat_id}")
            else:
                print(f"✗ Errore Telegram OMIRL per {chat_id}: {payload}")
        except Exception as e:
            print(f"✗ Errore invio OMIRL a {chat_id}: {e}")


def run_analysis(force: bool = False) -> Optional[Dict[str, Any]]:
    """Esegue l'analisi OMIRL completa.
    Ritorna un dict con {message, image, radar_time, exceeding} se c'è un'allerta,
    oppure None se non c'è nulla da inviare."""
    rows = fetch_omirl_rain()
    if rows is None:
        print("Impossibile ottenere dati OMIRL, esco")
        return None

    sp_stations = filter_sp_stations(rows)
    if not sp_stations:
        print("Nessuna stazione SP trovata nei dati OMIRL")
        return None
    print(f"Stazioni SP trovate: {len(sp_stations)}")

    soglia = thresholds.OMIRL_RAIN_TRIGGER
    exceeding = find_exceeding_stations(sp_stations, soglia)

    state = load_state()
    state["last_check_ts"] = datetime.now(TZ_ROME).isoformat()
    state["n_stations_sp"] = len(sp_stations)
    state["n_stations_rain"] = sum(
        1 for s in sp_stations if float(s.get("last", 0) or 0) > 0
    )

    if not exceeding:
        print(f"Nessuna stazione SP supera {soglia} mm/h — tutto OK")
        state["status"] = "ok"
        save_state(state)
        return None

    print(f"⚠️  {len(exceeding)} stazioni superano {soglia} mm/h:")
    for s in exceeding:
        print(f"  {s['name']} ({s['code']}): {s['last']:.1f} mm/h")

    if not should_send(state, exceeding, force):
        save_state(state)
        return None

    radar_img, radar_time = fetch_rainviewer_image()
    msg = build_message(exceeding, sp_stations, radar_time)
    save_state(state)

    return {
        "message": msg,
        "image": radar_img,
        "radar_time": radar_time,
        "exceeding": exceeding,
    }


def mark_sent(result: Dict[str, Any]):
    """Aggiorna lo stato dopo un invio Telegram riuscito."""
    state = load_state()
    state["status"] = "alert"
    state["last_send_ts"] = datetime.now(TZ_ROME).isoformat()
    state["max_rain_mm"] = result["exceeding"][0]["last"]
    state["exceeding_stations"] = [s["code"] for s in result["exceeding"]]
    save_state(state)
    print("OMIRL: stato aggiornato")


def main():
    force = "--force" in sys.argv
    result = run_analysis(force)
    if result is None:
        return
    send_telegram(result["message"], result.get("image"))
    mark_sent(result)


if __name__ == "__main__":
    main()
