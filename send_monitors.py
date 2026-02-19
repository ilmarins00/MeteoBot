#!/usr/bin/env python3
"""
Orchestratore Monitor Meteo – Invio unificato

Esegue monitor_fulmini e monitor_omirl in sequenza, poi invia le eventuali
allerte come album Telegram (media group) così che le foto arrivino insieme.

Flusso:
1. Esegue monitor_fulmini.run_analysis() — il più lento (~2 min WebSocket)
2. Esegue monitor_omirl.run_analysis() — veloce (~5s)
3. Raccoglie i risultati
4. Se entrambi hanno allerta con foto → sendMediaGroup (album)
   Se uno solo ha allerta → sendPhoto / sendMessage
5. Aggiorna lo stato di ciascun monitor dopo l'invio

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
import monitor_omirl


def send_media_group(
    chat_id: str,
    items: List[Tuple[str, bytes, str]],
) -> bool:
    """
    Invia un album di foto via Telegram sendMediaGroup.

    items: lista di (nome_file, image_bytes, caption_text)
    La caption viene assegnata a ciascuna foto.
    Restituisce True se l'invio ha avuto successo.
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
            "parse_mode": "Markdown",
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
    """Invia una singola foto con caption."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
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
    """Invia un messaggio di solo testo."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
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
    omirl_result: Optional[Dict[str, Any]],
    fulmini_result: Optional[Dict[str, Any]],
) -> bool:
    """
    Invia i risultati a tutti i chat Telegram.
    Se entrambi hanno foto → album (media group).
    Se uno solo ha foto → foto singola.
    Se nessuna foto → testo.
    Restituisce True se almeno un invio è riuscito.
    """
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato, skip invio")
        return False

    # Prepara gli item con foto
    photo_items: List[Tuple[str, bytes, str, str]] = []  # (filename, bytes, caption, monitor_name)
    text_only: List[Tuple[str, str]] = []  # (message, monitor_name)

    if fulmini_result:
        if fulmini_result.get("image"):
            photo_items.append((
                "radar_fulmini.png",
                fulmini_result["image"],
                fulmini_result["message"],
                "fulmini",
            ))
        else:
            text_only.append((fulmini_result["message"], "fulmini"))

    if omirl_result:
        if omirl_result.get("image"):
            photo_items.append((
                "radar_omirl.png",
                omirl_result["image"],
                omirl_result["message"],
                "omirl",
            ))
        else:
            text_only.append((omirl_result["message"], "omirl"))

    any_success = False

    for chat_id in LISTA_CHAT:
        # Se ci sono 2+ foto → album
        if len(photo_items) >= 2:
            album_items = [(f, b, c) for f, b, c, _ in photo_items]
            ok = send_media_group(chat_id, album_items)
            if ok:
                any_success = True
            else:
                # Fallback: invia singolarmente
                for filename, img, caption, _ in photo_items:
                    if send_single_photo(chat_id, caption, img, filename):
                        any_success = True

        # Se c'è 1 sola foto
        elif len(photo_items) == 1:
            filename, img, caption, _ = photo_items[0]
            if send_single_photo(chat_id, caption, img, filename):
                any_success = True

        # Messaggi solo testo
        for msg_text, _ in text_only:
            if send_text(chat_id, msg_text):
                any_success = True

    return any_success


def main():
    force = "--force" in sys.argv

    print("=" * 50)
    print("  ORCHESTRATORE MONITOR METEO")
    print("=" * 50)

    # 1. Monitor fulmini (più lento — ~2 min WebSocket)
    print("\n🔌 Monitor Fulmini...")
    print("-" * 40)
    fulmini_result = monitor_fulmini.run_analysis(force=force)
    if fulmini_result:
        print(f"→ ALLERTA fulmini: {fulmini_result['n']} scariche")
    else:
        print("→ Nessuna allerta fulmini")

    # 2. Monitor OMIRL (più veloce — ~5s)
    print("\n🌧️ Monitor OMIRL...")
    print("-" * 40)
    omirl_result = monitor_omirl.run_analysis(force=force)
    if omirl_result:
        n_exc = len(omirl_result["exceeding"])
        print(f"→ ALLERTA pioggia: {n_exc} stazioni oltre soglia")
    else:
        print("→ Nessuna allerta pioggia")

    # 3. Nessuna allerta?
    if not fulmini_result and not omirl_result:
        print("\n✅ Nessuna allerta attiva – niente da inviare")
        return

    # 4. Invio unificato
    print("\n📤 Invio notifiche...")
    print("-" * 40)
    success = dispatch_results(omirl_result, fulmini_result)

    # 5. Aggiorna stato di ciascun monitor dopo invio riuscito
    if success:
        if fulmini_result:
            monitor_fulmini.mark_sent(fulmini_result)
        if omirl_result:
            monitor_omirl.mark_sent(omirl_result)
        print("\n✅ Invio completato e stati aggiornati")
    else:
        print("\n⚠️ Invio fallito — stati NON aggiornati")


if __name__ == "__main__":
    main()
