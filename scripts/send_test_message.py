#!/usr/bin/env python3
"""Invia un messaggio di test Telegram alle chat configurate."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import TELEGRAM_CHAT_IDS, TELEGRAM_TOKEN


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Invia un messaggio di test Telegram alle chat configurate"
    )
    parser.add_argument(
        "-m",
        "--message",
        default=None,
        help="Testo del messaggio da inviare (default: messaggio automatico con timestamp)",
    )
    return parser.parse_args()


def build_message(custom_message: str | None) -> str:
    if custom_message:
        return custom_message
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return f"🧪 Test MeteoBot\nInvio di prova riuscito ({ts})"


def send_test_message(text: str) -> int:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS:
        print("Telegram non configurato: mancano TELEGRAM_TOKEN o TELEGRAM_CHAT_IDS")
        return 1

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    failed = 0

    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok"):
                print(f"Messaggio di test inviato a {chat_id}")
            else:
                failed += 1
                print(f"Telegram API errore per {chat_id}: {payload}")
        except Exception as exc:
            failed += 1
            print(f"Errore invio Telegram a {chat_id}: {exc}")

    if failed:
        print(f"Invio completato con errori: {failed}/{len(TELEGRAM_CHAT_IDS)} chat fallite")
        return 1

    print(f"Invio completato con successo: {len(TELEGRAM_CHAT_IDS)} chat")
    return 0


def main() -> int:
    args = parse_args()
    message = build_message(args.message)
    return send_test_message(message)


if __name__ == "__main__":
    raise SystemExit(main())
