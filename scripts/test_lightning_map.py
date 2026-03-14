#!/usr/bin/env python3
"""Test invio mappa fulmini — invia una mappa di prova via Telegram."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_fulmini import generate_lightning_map, send_telegram

# Genera mappa senza fulmini
image = generate_lightning_map([], radius_km=30.0)
if image:
    print(f"✓ Mappa generata: {len(image)} bytes")
    send_telegram(
        "🧪 *Test mappa fulmini*\nNessun fulmine rilevato al momento. "
        "Questa è una prova di invio della mappa.",
        image,
    )
else:
    print("✗ Errore generazione mappa")
    sys.exit(1)
