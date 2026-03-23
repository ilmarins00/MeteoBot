#!/usr/bin/env python3
"""
bot.py — Comandi interattivi Telegram per MeteoBot
===================================================
Gestisce i comandi in arrivo dal bot Telegram tramite long-polling.
Progettato per essere eseguito su GitHub Actions (run unico, 3 min max).

Comandi supportati:
    /meteo      — report meteo istantaneo (legge state.json + storico)
    /previsioni — lancia previsioni AI (Open-Meteo + Gemini)
    /aria       — qualità dell'aria attuale (CAMS via Open-Meteo)
    /allerte    — allerte ARPAL attive + soglie raggiunte
    /help       — elenco comandi

Uso:
    python bot.py       # polling per 3 minuti, poi esce
    python bot.py --once  # una sola passata senza loop (CI-friendly)

Il file bot_offset.json salva l'ultimo update_id processato per evitare
di riprocessare messaggi già gestiti.
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    LATITUDE, LONGITUDE,
    load_state_section,
    FILE_STORICO,
)

TZ_ROME = ZoneInfo("Europe/Rome")

_OFFSET_FILE = "bot_offset.json"
_POLL_TIMEOUT = 20        # secondi per ogni long-poll
_MAX_RUNTIME  = 170       # secondi totali prima di uscire (Actions = 6 min, usiamo 3)
_ALLOWED_CHATS = set(str(c) for c in LISTA_CHAT)


# ── Utility ───────────────────────────────────────────────────────────────────

def _escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_offset() -> int:
    if os.path.exists(_OFFSET_FILE):
        try:
            with open(_OFFSET_FILE) as f:
                return int(json.load(f).get("offset", 0))
        except Exception:
            pass
    return 0


def _save_offset(offset: int):
    with open(_OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)


def _send(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Invia un messaggio Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=15,
        )
        resp.raise_for_status()
        ok = resp.json().get("ok", False)
        if not ok:
            print(f"✗ sendMessage error: {resp.json()}")
        return ok
    except Exception as e:
        print(f"✗ send error: {e}")
        return False


def _get_updates(offset: int) -> list:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        resp = requests.get(
            url,
            params={"offset": offset, "timeout": _POLL_TIMEOUT, "allowed_updates": ["message"]},
            timeout=_POLL_TIMEOUT + 5,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as e:
        print(f"⚠️  getUpdates error: {e}")
        return []


def _is_authorized(chat_id: str) -> bool:
    """Accetta solo chat nella lista configurata."""
    if not _ALLOWED_CHATS:
        return True  # se non configurate, accetta tutte
    return str(chat_id) in _ALLOWED_CHATS


# ── Handlers ──────────────────────────────────────────────────────────────────

def _cmd_help(chat_id: str):
    testo = (
        "🤖 <b>MeteoBot — Comandi disponibili</b>\n\n"
        "/meteo — Report meteo aggiornato\n"
        "/aria — Qualità dell'aria (CAMS)\n"
        "/allerte — Allerte attive e soglie\n"
        "/previsioni — Previsioni AI (richiede ~30s)\n"
        "/help — Questo messaggio\n"
    )
    _send(chat_id, testo)


def _cmd_meteo(chat_id: str):
    """Risponde con il report meteo attuale da state.json + storico."""
    _send(chat_id, "⏳ Recupero dati meteo...")
    try:
        meteo = load_state_section("meteo")
        sbcape_d = load_state_section("sbcape")

        if not meteo:
            _send(chat_id, "⚠️ Dati meteo non disponibili (state.json vuoto o assente).")
            return

        # Leggi ultimo campione storico per dati real-time
        ultimo = {}
        if os.path.exists(FILE_STORICO):
            try:
                with open(FILE_STORICO) as f:
                    storico = json.load(f)
                if storico:
                    ultimo = storico[-1]
            except Exception:
                pass

        now_str = datetime.now(TZ_ROME).strftime("%d/%m/%Y %H:%M")
        ts_str = ultimo.get("ts", meteo.get("ultimo_update_ora", "N/D"))
        try:
            ts_dt = datetime.fromisoformat(str(ts_str))
            ts_str = ts_dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass

        temp    = ultimo.get("temp",      "N/D")
        umid    = ultimo.get("umidita",   "N/D")
        press   = ultimo.get("pressione", "N/D")
        vento   = ultimo.get("vento",     "N/D")
        raffica = ultimo.get("raffica",   "N/D")
        pioggia_1h  = ultimo.get("pioggia_1h",  0)
        pioggia_24h = ultimo.get("pioggia_24h", 0)
        dew     = ultimo.get("dew_point", "N/D")
        api_mm  = meteo.get("api_ultimo_valore", "N/D")
        sat_pct = meteo.get("ultima_saturazione_perc", "N/D")
        t_min   = meteo.get("t_min_oggi",  "N/D")
        t_max   = meteo.get("t_max_oggi",  "N/D")

        avvisi = meteo.get("ultimi_avvisi", [])
        str_avvisi = ""
        if avvisi:
            str_avvisi = "\n".join(avvisi) + "\n\n"

        sbcape_val = sbcape_d.get("sbcape", 0) if sbcape_d else 0
        li_val     = sbcape_d.get("lifted_index", "N/D") if sbcape_d else "N/D"

        testo = (
            f"📡 <b>METEO LA SPEZIA — aggiornamento</b>\n"
            f"📅 {ts_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{str_avvisi}"
            f"🌡️ <b>Temperatura</b>: {temp}°C "
            f"(min {t_min}°C / max {t_max}°C)\n"
            f"💧 <b>Umidità</b>: {umid}% | Rugiada: {dew}°C\n"
            f"🔵 <b>Pressione</b>: {press} hPa\n"
            f"🌬️ <b>Vento</b>: {vento} km/h | Raffica: {raffica} km/h\n"
            f"🌧️ <b>Pioggia</b>: {pioggia_1h} mm/h | 24h: {pioggia_24h} mm\n"
            f"🌱 <b>API suolo</b>: {api_mm} mm ({sat_pct}%)\n"
            f"⚡ <b>SBCAPE</b>: {sbcape_val} J/kg | LI: {li_val}\n"
        )

        # Aggiungi qualità aria se disponibile
        try:
            from qualita_aria import fetch_air_quality, formatta_sezione_aria
            aq = fetch_air_quality()
            if aq:
                testo += "\n" + formatta_sezione_aria(aq)
        except Exception:
            pass

        _send(chat_id, testo)

    except Exception as e:
        _send(chat_id, f"⚠️ Errore nel recupero dati: {_escape_html(str(e))}")


def _cmd_aria(chat_id: str):
    """Risponde con la qualità dell'aria attuale."""
    _send(chat_id, "⏳ Recupero dati qualità dell'aria...")
    try:
        from qualita_aria import fetch_air_quality, formatta_sezione_aria
        aq = fetch_air_quality()
        if not aq:
            _send(chat_id, "⚠️ Dati qualità dell'aria non disponibili al momento.")
            return

        testo = (
            f"🏭 <b>QUALITÀ DELL'ARIA — La Spezia</b>\n"
            f"📅 {datetime.now(TZ_ROME).strftime('%d/%m/%Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        testo += formatta_sezione_aria(aq)

        if aq.get("avvisi"):
            testo += "\n" + "\n".join(aq["avvisi"])

        testo += "\n\n<i>Fonte: CAMS European Air Quality — Open-Meteo</i>"
        _send(chat_id, testo)

    except Exception as e:
        _send(chat_id, f"⚠️ Errore: {_escape_html(str(e))}")


def _cmd_allerte(chat_id: str):
    """Risponde con le allerte attive (state.json + soglie ARPAL)."""
    try:
        meteo  = load_state_section("meteo")
        arpal  = load_state_section("arpal")
        now_str = datetime.now(TZ_ROME).strftime("%d/%m/%Y %H:%M")

        avvisi_meteo = meteo.get("ultimi_avvisi", []) if meteo else []
        arpal_livello = arpal.get("max_livello", "Verde") if arpal else "Verde"
        arpal_emoji = {"Verde": "🟢", "Giallo": "🟡", "Arancione": "🟠", "Rosso": "🔴"}.get(arpal_livello, "🟢")
        vigilanza = arpal.get("vigilanza", "") if arpal else ""

        testo = (
            f"🚨 <b>ALLERTE — La Spezia</b>\n"
            f"📅 {now_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{arpal_emoji} <b>Allerta ARPAL:</b> {arpal_livello}\n"
        )

        if arpal and arpal.get("dettaglio"):
            det = arpal["dettaglio"]
            for k, v in det.items():
                em = {"Verde": "🟢", "Giallo": "🟡", "Arancione": "🟠", "Rosso": "🔴"}.get(v, "⚪")
                testo += f"  {em} {_escape_html(k)}: {v}\n"

        if avvisi_meteo:
            testo += "\n⚠️ <b>Avvisi stazione:</b>\n"
            for av in avvisi_meteo:
                testo += f"  {_escape_html(av)}\n"
        else:
            testo += "\n✅ Nessun avviso attivo dalla stazione\n"

        # Soglie in corso
        nowcasting = load_state_section("nowcasting")
        if nowcasting and nowcasting.get("last_max_rain", 0) >= 6:
            testo += (
                f"\n🌧️ <b>Nowcasting OMIRL:</b> "
                f"{nowcasting['last_max_rain']} mm/h @ "
                f"{_escape_html(nowcasting.get('stazioni_sp', [{}])[0].get('nome', 'N/D') if nowcasting.get('stazioni_sp') else 'N/D')}\n"
            )

        if vigilanza:
            testo += f"\n<i>{_escape_html(vigilanza[:200])}</i>"

        _send(chat_id, testo)

    except Exception as e:
        _send(chat_id, f"⚠️ Errore: {_escape_html(str(e))}")


def _cmd_previsioni(chat_id: str):
    """Lancia la generazione previsioni AI e invia il risultato."""
    _send(chat_id, "⏳ Generazione previsioni AI in corso (~30 secondi)...")
    try:
        import previsioni
        previsioni.main(target_chat_id=chat_id)
    except Exception as e:
        _send(chat_id, f"⚠️ Errore generazione previsioni: {_escape_html(str(e))}")


# ── Dispatcher ────────────────────────────────────────────────────────────────

_COMMANDS = {
    "/help":        _cmd_help,
    "/start":       _cmd_help,
    "/meteo":       _cmd_meteo,
    "/aria":        _cmd_aria,
    "/allerte":     _cmd_allerte,
    "/previsioni":  _cmd_previsioni,
}


def _handle_update(update: dict):
    """Processa un singolo update Telegram."""
    message = update.get("message", {})
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id", ""))
    text    = message.get("text", "").strip()

    if not chat_id or not text:
        return

    if not _is_authorized(chat_id):
        print(f"⚠️  Chat non autorizzata: {chat_id}")
        return

    # Estrai comando (gestisce /comando@BotName)
    cmd = text.split()[0].split("@")[0].lower()
    print(f"→ Comando '{cmd}' da chat {chat_id}")

    handler = _COMMANDS.get(cmd)
    if handler:
        try:
            handler(chat_id)
        except Exception as e:
            print(f"✗ Handler error per {cmd}: {e}")
            _send(chat_id, f"⚠️ Errore interno: {_escape_html(str(e))}")
    else:
        _send(chat_id, f"Comando non riconosciuto: <code>{_escape_html(cmd)}</code>\nUsa /help per la lista comandi.")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        print("✗ TELEGRAM_TOKEN non configurato")
        sys.exit(1)

    once = "--once" in sys.argv
    offset = _load_offset()
    start_time = time.time()

    print(f"🤖 MeteoBot polling avviato (offset={offset}, max={_MAX_RUNTIME}s)")

    while True:
        elapsed = time.time() - start_time
        if elapsed >= _MAX_RUNTIME:
            print(f"⏹️  Tempo massimo raggiunto ({elapsed:.0f}s), uscita")
            break

        updates = _get_updates(offset)

        for upd in updates:
            upd_id = upd.get("update_id", 0)
            _handle_update(upd)
            offset = upd_id + 1

        if updates:
            _save_offset(offset)

        if once:
            break

        # Breve pausa per evitare burst
        time.sleep(1)

    print("🤖 MeteoBot polling terminato")


if __name__ == "__main__":
    main()