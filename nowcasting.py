#!/usr/bin/env python3
"""
nowcasting.py — Nowcasting pioggia intensa (OMIRL) per MeteoBot
===============================================================
Interroga la rete OMIRL (Osservatorio Meteo Idrologico della Regione Liguria)
per rilevare precipitazioni intense nell'area di La Spezia in tempo reale.

Funzionamento:
1. Scarica i dati in tempo reale delle stazioni OMIRL nell'area SP
2. Se la pioggia rilevata supera la soglia (default 6 mm/h) invia notifica
3. Anti-spam: non re-invia la stessa soglia per 30 minuti

Uso:
    python nowcasting.py            # standard (da cron ogni 10-15 min)
    python nowcasting.py --force    # forza invio anche se già notificato
    python nowcasting.py --check    # solo check, stampa risultato senza inviare

Uso come modulo:
    from nowcasting import check_nowcasting
    result = check_nowcasting()   # None = nessun evento / dict = evento rilevato
"""

import json
import sys
import math
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    LATITUDE, LONGITUDE,
    load_state_section,
    save_state_section,
    thresholds,
)

TZ_ROME = ZoneInfo("Europe/Rome")

# ── Endpoint OMIRL ────────────────────────────────────────────────────────────
_OMIRL_RAIN_ENDPOINT  = "https://omirl.regione.liguria.it/Omirl/rest/stations/sensorvalues/PioggiaCumulata1h"
_OMIRL_RAIN_RT_ENDPOINT = "https://omirl.regione.liguria.it/Omirl/rest/stations/sensorvalues/PioggiaRateOra"

# Stazioni OMIRL nella provincia di La Spezia (codici noti)
_OMIRL_SP_STATIONS = {
    "SPZIA": "La Spezia centro",
    "LERICI": "Lerici",
    "SARZANA": "Sarzana",
    "PONTREM": "Pontremoli",
    "LEVANTO": "Levanto",
    "SESTRI": "Sestri Levante",  # vicina ma utile come contesto
}

# Raggio massimo per stazioni di cui consideriamo il dato (km)
_MAX_RADIUS_KM = 25.0
_EARTH_R = 6371.0

# Soglie notifica (mm/h)
_SOGLIA_MODERATA  = 6.0
_SOGLIA_FORTE     = 15.0
_SOGLIA_MOLTO_FORTE = 30.0
_SOGLIA_NUBIFRAGIO = 50.0


def _haversine_km(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def _fetch_omirl_rain(endpoint: str, timeout: int = 15) -> list:
    """Scarica i dati OMIRL per tutte le stazioni e restituisce la lista tableRows."""
    try:
        resp = requests.get(
            endpoint,
            timeout=timeout,
            headers={"User-Agent": "MeteoBot/1.0", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("tableRows", [])
    except Exception as e:
        print(f"⚠️  OMIRL fetch error ({endpoint}): {e}")
        return []


def _classify_rain(mmh: float) -> tuple[str, str]:
    """Restituisce (livello, emoji) in base all'intensità."""
    if mmh >= _SOGLIA_NUBIFRAGIO:
        return "nubifragio", "🔴🌧️"
    elif mmh >= _SOGLIA_MOLTO_FORTE:
        return "molto_forte", "🟠🌧️"
    elif mmh >= _SOGLIA_FORTE:
        return "forte", "🟡🌧️"
    elif mmh >= _SOGLIA_MODERATA:
        return "moderata", "🌧️"
    return "debole", "🌦️"


def _load_state() -> dict:
    return load_state_section("nowcasting")


def _save_state(state: dict):
    save_state_section("nowcasting", state)


def _should_notify(state: dict, livello: str, force: bool) -> bool:
    """Evita spam: non re-invia lo stesso livello per 30 min."""
    if force:
        return True
    last_ts = state.get("last_send_ts")
    last_livello = state.get("last_livello", "")
    if not last_ts:
        return True
    try:
        last_dt = datetime.fromisoformat(last_ts)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=TZ_ROME)
        delta = (datetime.now(TZ_ROME) - last_dt).total_seconds()
        # Soglia più alta → notifica sempre (anche entro 30 min)
        livelli_order = ["debole", "moderata", "forte", "molto_forte", "nubifragio"]
        idx_curr = livelli_order.index(livello) if livello in livelli_order else 0
        idx_last = livelli_order.index(last_livello) if last_livello in livelli_order else 0
        if idx_curr > idx_last:
            return True  # escalation → notifica subito
        if delta < 1800:  # 30 minuti
            return False
    except Exception:
        pass
    return True


def check_nowcasting(force: bool = False) -> Optional[dict]:
    """
    Controlla le precipitazioni in tempo reale sulle stazioni OMIRL.

    Restituisce None se nessun evento significativo, altrimenti un dict con:
        max_rain_mmh, stazione, livello, emoji, messaggio (HTML), stazioni_attive
    """
    now = datetime.now(TZ_ROME)
    state = _load_state()

    # Prova prima il rate orario, poi cumulate 1h come fallback
    rows = _fetch_omirl_rain(_OMIRL_RAIN_RT_ENDPOINT)
    fonte = "rate"
    if not rows:
        rows = _fetch_omirl_rain(_OMIRL_RAIN_ENDPOINT)
        fonte = "cumulate_1h"
    if not rows:
        print("⚠️  OMIRL: nessun dato disponibile")
        state["last_check_ts"] = now.isoformat()
        state["status"] = "no_data"
        _save_state(state)
        return None

    # Filtra stazioni SP e prendi il valore max
    stazioni_sp = []
    for row in rows:
        codice = str(row.get("code") or row.get("stationCode") or "").upper()
        if codice not in _OMIRL_SP_STATIONS:
            continue
        val = row.get("value") or row.get("last") or row.get("rain") or row.get("val")
        if val is None:
            continue
        try:
            val_f = float(val)
        except (ValueError, TypeError):
            continue
        if val_f < 0:
            continue
        stazioni_sp.append({
            "codice": codice,
            "nome": _OMIRL_SP_STATIONS[codice],
            "valore": round(val_f, 1),
        })

    if not stazioni_sp:
        print(f"⚠️  OMIRL: nessuna stazione SP trovata nei {len(rows)} record")
        state["last_check_ts"] = now.isoformat()
        state["status"] = "no_sp_stations"
        _save_state(state)
        return None

    stazioni_sp.sort(key=lambda x: x["valore"], reverse=True)
    max_station = stazioni_sp[0]
    max_rain = max_station["valore"]
    livello, emoji = _classify_rain(max_rain)

    state["last_check_ts"] = now.isoformat()
    state["last_max_rain"] = max_rain
    state["last_livello"] = livello
    state["stazioni_sp"] = stazioni_sp
    state["fonte"] = fonte

    print(
        f"OMIRL nowcasting: max {max_rain} mm/h @ {max_station['nome']} "
        f"({livello}) — {len(stazioni_sp)} stazioni SP attive"
    )

    if max_rain < _SOGLIA_MODERATA:
        state["status"] = "ok"
        _save_state(state)
        return None

    if not _should_notify(state, livello, force):
        print(f"⏭️  Notifica nowcasting già inviata recentemente (livello: {livello})")
        _save_state(state)
        return None

    # Descrizione intensità
    descrizioni = {
        "moderata":    "Pioggia moderata",
        "forte":       "Pioggia forte",
        "molto_forte": "Pioggia molto forte",
        "nubifragio":  "NUBIFRAGIO",
    }
    descrizione = descrizioni.get(livello, "Pioggia")

    # Lista stazioni attive con pioggia significativa
    stazioni_txt = ""
    for s in stazioni_sp[:5]:
        if s["valore"] >= _SOGLIA_MODERATA:
            _lv, _em = _classify_rain(s["valore"])
            stazioni_txt += f"  {_em} {s['nome']}: {s['valore']} mm/h\n"

    now_str = now.strftime("%d/%m/%Y %H:%M")
    messaggio = (
        f"{emoji} <b>NOWCASTING PIOGGIA — La Spezia</b>\n"
        f"📅 {now_str}\n\n"
        f"<b>{descrizione}</b> rilevata dalla rete OMIRL\n"
        f"Stazione più intensa: <b>{max_station['nome']}</b> — "
        f"<b>{max_rain} mm/h</b>\n\n"
    )
    if stazioni_txt:
        messaggio += f"Stazioni attive con pioggia significativa:\n{stazioni_txt}\n"

    messaggio += (
        f"<i>Dati in tempo reale OMIRL Liguria "
        f"(fonte: {'rate orario' if fonte == 'rate' else 'cumulate 1h'})</i>"
    )

    state["status"] = "alert"
    _save_state(state)

    return {
        "max_rain_mmh": max_rain,
        "stazione":     max_station["nome"],
        "livello":      livello,
        "emoji":        emoji,
        "messaggio":    messaggio,
        "stazioni_sp":  stazioni_sp,
    }


def send_nowcasting(result: dict):
    """Invia la notifica nowcasting via Telegram HTML."""
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    any_ok = False
    for chat_id in LISTA_CHAT:
        try:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": result["messaggio"], "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            if resp.json().get("ok"):
                print(f"✓ Nowcasting inviato a {chat_id}")
                any_ok = True
            else:
                print(f"✗ Errore nowcasting per {chat_id}: {resp.json()}")
        except Exception as e:
            print(f"✗ Errore invio nowcasting: {e}")
    if any_ok:
        state = _load_state()
        state["last_send_ts"] = datetime.now(TZ_ROME).isoformat()
        _save_state(state)
    return any_ok


def main():
    force    = "--force" in sys.argv
    check_only = "--check" in sys.argv

    result = check_nowcasting(force=force)

    if result is None:
        print("✅ Nessun evento pioggia significativo")
        return

    print(f"\n⚠️  EVENTO RILEVATO: {result['max_rain_mmh']} mm/h @ {result['stazione']}")
    print(result["messaggio"])

    if not check_only:
        send_nowcasting(result)


if __name__ == "__main__":
    main()