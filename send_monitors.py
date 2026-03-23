#!/usr/bin/env python3
"""
Orchestratore Monitor Meteo – Invio unificato

Esegue monitor_fulmini, poi invia le eventuali allerte via Telegram.

Flusso:
1. Esegue monitor_fulmini.run_analysis() (~2 min WebSocket)
2. Se allerta con foto → sendPhoto (HTML caption)
   Altrimenti → sendMessage (HTML)
3. Aggiorna lo stato del monitor dopo l'invio

Uso:
    python send_monitors.py            # Esecuzione standard (cron)
    python send_monitors.py --force    # Forza invio anche se già notificato
"""
import io
import json
import sys
import requests
from typing import Dict, Any, List, Optional, Tuple

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
)

import monitor_fulmini


def send_media_group(
    chat_id: str,
    items: List[Tuple[str, bytes, str]],
) -> bool:
    """
    Invia un album di foto via Telegram sendMediaGroup.
    items: lista di (nome_file, image_bytes, caption_text)
    """
    if not items:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMediaGroup"

    media = []
    files = {}
    for i, (filename, img_bytes, caption) in enumerate(items):
        attach_key = f"photo{i}"
        media.append({
            "type": "photo",
            "media": f"attach://{attach_key}",
            "caption": caption,
            "parse_mode": "HTML",
        })
        files[attach_key] = (filename, io.BytesIO(img_bytes), "image/png")

    data = {
        "chat_id": chat_id,
        "media": json.dumps(media),
    }

    try:
        resp = requests.post(url, data=data, files=files, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok"):
            print(f"✓ Album ({len(items)} foto) inviato a {chat_id}")
            return True
        else:
            print(f"✗ Errore sendMediaGroup per {chat_id}: {payload}")
            return False
    except Exception as e:
        print(f"✗ Errore invio album a {chat_id}: {e}")
        return False


def send_single_photo(chat_id: str, caption: str, image: bytes, filename: str) -> bool:
    """Invia una singola foto con caption HTML."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": (filename, io.BytesIO(image), "image/png")},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok"):
            print(f"✓ Foto ({filename}) inviata a {chat_id}")
            return True
        else:
            print(f"✗ Errore sendPhoto per {chat_id}: {payload}")
            return False
    except Exception as e:
        print(f"✗ Errore invio foto a {chat_id}: {e}")
        return False


def send_text(chat_id: str, text: str) -> bool:
    """Invia un messaggio di testo HTML."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok"):
            print(f"✓ Messaggio inviato a {chat_id}")
            return True
        else:
            print(f"✗ Errore sendMessage per {chat_id}: {payload}")
            return False
    except Exception as e:
        print(f"✗ Errore invio messaggio a {chat_id}: {e}")
        return False


def dispatch_results(
    fulmini_result: Optional[Dict[str, Any]],
) -> bool:
    """
    Invia i risultati a tutti i chat Telegram.
    Se c'è foto → foto singola con caption HTML, altrimenti testo HTML.
    """
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato, skip invio")
        return False

    any_success = False

    for chat_id in LISTA_CHAT:
        if fulmini_result.get("image"):
            if send_single_photo(chat_id, fulmini_result["message"], fulmini_result["image"], "radar_fulmini.png"):
                any_success = True
        else:
            if send_text(chat_id, fulmini_result["message"]):
                any_success = True

    return any_success


def main():
    force = "--force" in sys.argv

    print("=" * 50)
    print("  ORCHESTRATORE MONITOR METEO")
    print("=" * 50)

    print("\n🔌 Monitor Fulmini...")
    print("-" * 40)
    fulmini_result = monitor_fulmini.run_analysis(force=force)
    if fulmini_result:
        print(f"→ ALLERTA fulmini: {fulmini_result['n']} scariche")
    else:
        print("→ Nessuna allerta fulmini")

    if not fulmini_result:
        print("\n✅ Nessuna allerta attiva – niente da inviare")
        return

    print("\n📤 Invio notifiche...")
    print("-" * 40)
    success = dispatch_results(fulmini_result)

    if success:
        monitor_fulmini.mark_sent(fulmini_result)
        print("\n✅ Invio completato e stato aggiornato")
    else:
        print("\n⚠️ Invio fallito — stato NON aggiornato")


if __name__ == "__main__":
    main()