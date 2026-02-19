#!/usr/bin/env python3
"""
Bot Comandi Telegram – MeteoBot

Ascolta comandi Telegram via long-polling e invia report on-demand,
bypassando la logica di invio smart.

Comandi disponibili:
  /meteo    — Report meteo completo (stazione La Spezia)
  /arpal    — Stato allerta ARPAL Zona C
  /fulmini  — Analisi fulmini in tempo reale
  /omirl    — Precipitazioni rete OMIRL La Spezia
  /tutto    — Esegui tutti i monitor in sequenza
  /help     — Mostra comandi disponibili

Uso:
  python bot_commands.py              # Long-polling continuo (background)
  python bot_commands.py --once       # Processa comandi in coda ed esci
"""
import json
import os
import sys
import time
import traceback

import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS as LISTA_CHAT

TZ_ROME = ZoneInfo("Europe/Rome")

OFFSET_FILE = "bot_offset.json"

COMMANDS = {
    "/meteo": "📡 Report meteo stazione La Spezia",
    "/arpal": "🟢 Stato allerta ARPAL — Zona C",
    "/fulmini": "⚡ Monitor fulmini (Blitzortung)",
    "/omirl": "🌧️ Precipitazioni rete OMIRL — La Spezia",
    "/tutto": "📋 Esegui tutti i monitor",
    "/help": "❓ Mostra comandi disponibili",
}


# ── Telegram helpers ──────────────────────────────────────────────────────────


def get_updates(offset=None, timeout=30):
    """Recupera nuovi messaggi dal bot Telegram (long-polling)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=timeout + 10)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print(f"Errore getUpdates: {e}")
        return []


def send_message(chat_id, text, parse_mode="Markdown"):
    """Invia un messaggio testuale, gestendo messaggi troppo lunghi per Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Limite Telegram: 4096 caratteri per messaggio
    for i in range(0, len(text), 4096):
        chunk = text[i : i + 4096]
        try:
            r = requests.post(
                url,
                data={"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode},
                timeout=15,
            )
            r.raise_for_status()
            payload = r.json()
            if not payload.get("ok"):
                # Fallback senza parse_mode (il Markdown potrebbe non essere valido)
                requests.post(
                    url, data={"chat_id": chat_id, "text": chunk}, timeout=15
                )
        except Exception as e:
            print(f"Errore invio messaggio a {chat_id}: {e}")


def send_photo(chat_id, image_bytes, caption="", filename="photo.png"):
    """Invia una foto con caption opzionale."""
    import io

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "caption": caption[:1024],
                "parse_mode": "Markdown",
            },
            files={"photo": (filename, io.BytesIO(image_bytes), "image/png")},
            timeout=20,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Errore invio foto a {chat_id}: {e}")


def is_authorized(chat_id):
    """Verifica che il chat_id sia nella lista autorizzata."""
    return str(chat_id) in [str(c) for c in LISTA_CHAT]


# ── Gestori comandi ───────────────────────────────────────────────────────────


def cmd_help(chat_id):
    """Mostra la lista dei comandi disponibili."""
    lines = ["🤖 *Comandi MeteoBot*\n"]
    for cmd, desc in COMMANDS.items():
        lines.append(f"  {cmd} — {desc}")
    lines.append(f"\n🕒 {datetime.now(TZ_ROME).strftime('%d/%m/%Y %H:%M')}")
    send_message(chat_id, "\n".join(lines))


def cmd_meteo(chat_id):
    """Genera e invia il report meteo completo della stazione."""
    send_message(chat_id, "⏳ Generazione report meteo in corso...")
    try:
        import meteo

        meteo.esegui_report(force_send=True, target_chat_id=str(chat_id))
    except Exception as e:
        send_message(chat_id, f"❌ Errore report meteo: {e}")
        traceback.print_exc()


def cmd_arpal(chat_id):
    """Scarica e invia lo stato allerta ARPAL Zona C."""
    send_message(chat_id, "⏳ Scaricamento dati ARPAL...")
    try:
        import monitor_arpal

        html = monitor_arpal.fetch_html()
        if not html:
            send_message(chat_id, "❌ Impossibile scaricare la pagina ARPAL.")
            return
        parsed = monitor_arpal.parse_zone_c(html)
        vigilanza = monitor_arpal.parse_vigilanza(html)
        msg = monitor_arpal.build_message(parsed, vigilanza)
        send_message(chat_id, msg)
    except Exception as e:
        send_message(chat_id, f"❌ Errore ARPAL: {e}")
        traceback.print_exc()


def cmd_fulmini(chat_id):
    """Esegue il monitor fulmini e invia i risultati."""
    send_message(chat_id, "⏳ Analisi fulmini in corso (~1 min)...")
    try:
        import monitor_fulmini

        result = monitor_fulmini.run_analysis(force=True, listen_seconds=60)
        if result:
            if result.get("image"):
                send_photo(
                    chat_id,
                    result["image"],
                    caption=result["message"],
                    filename="radar_fulmini.png",
                )
            else:
                send_message(chat_id, result["message"])
            monitor_fulmini.mark_sent(result)
        else:
            send_message(
                chat_id,
                "✅ Nessuna attività elettrica rilevata entro il raggio di monitoraggio.",
            )
    except Exception as e:
        send_message(chat_id, f"❌ Errore fulmini: {e}")
        traceback.print_exc()


def cmd_omirl(chat_id):
    """Scarica dati OMIRL e invia eventuali superamenti di soglia."""
    send_message(chat_id, "⏳ Scaricamento dati OMIRL...")
    try:
        import monitor_omirl

        result = monitor_omirl.run_analysis(force=True)
        if result:
            if result.get("image"):
                send_photo(
                    chat_id,
                    result["image"],
                    caption=result["message"],
                    filename="radar_omirl.png",
                )
            else:
                send_message(chat_id, result["message"])
            monitor_omirl.mark_sent(result)
        else:
            send_message(
                chat_id,
                "✅ Nessuna stazione SP supera la soglia precipitazioni. Tutto OK.",
            )
    except Exception as e:
        send_message(chat_id, f"❌ Errore OMIRL: {e}")
        traceback.print_exc()


def cmd_tutto(chat_id):
    """Esegue tutti i monitor in sequenza."""
    send_message(chat_id, "⏳ Esecuzione completa di tutti i monitor...")
    cmd_meteo(chat_id)
    cmd_arpal(chat_id)
    cmd_omirl(chat_id)
    cmd_fulmini(chat_id)


# ── Dispatcher ────────────────────────────────────────────────────────────────

DISPATCH = {
    "/meteo": cmd_meteo,
    "/arpal": cmd_arpal,
    "/fulmini": cmd_fulmini,
    "/omirl": cmd_omirl,
    "/tutto": cmd_tutto,
    "/help": cmd_help,
    "/start": cmd_help,
}


def process_update(update):
    """Processa un singolo update Telegram."""
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return

    if not is_authorized(chat_id):
        send_message(
            chat_id,
            "⛔ Non autorizzato. Il tuo chat ID non è nella lista configurata.",
        )
        print(f"Accesso negato: chat_id={chat_id}")
        return

    # Estrai il comando (rimuovi @nomebot se presente)
    cmd = text.split()[0].split("@")[0].lower()

    handler = DISPATCH.get(cmd)
    if handler:
        print(f"📩 Comando {cmd} da chat {chat_id}")
        try:
            handler(chat_id)
        except Exception as e:
            print(f"Errore gestione {cmd}: {e}")
            traceback.print_exc()
            send_message(chat_id, f"❌ Errore interno: {e}")
    # Ignora i messaggi che non sono comandi


# ── Persistenza offset ────────────────────────────────────────────────────────


def load_offset():
    if os.path.exists(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, "r") as f:
                return json.load(f).get("offset")
        except Exception:
            pass
    return None


def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    once = "--once" in sys.argv

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN non configurato!")
        sys.exit(1)

    print("🤖 MeteoBot command listener avviato")
    print(f"   Chat autorizzate: {LISTA_CHAT}")
    print(f"   Modalità: {'singola (--once)' if once else 'continua (long-polling)'}")
    print(f"   Comandi: {', '.join(COMMANDS.keys())}")

    offset = load_offset()

    while True:
        try:
            timeout = 0 if once else 30
            updates = get_updates(offset=offset, timeout=timeout)

            for update in updates:
                process_update(update)
                offset = update["update_id"] + 1
                save_offset(offset)

            if once:
                break

        except KeyboardInterrupt:
            print("\nArresto...")
            break
        except Exception as e:
            print(f"Errore loop principale: {e}")
            traceback.print_exc()
            if not once:
                time.sleep(5)


if __name__ == "__main__":
    main()
