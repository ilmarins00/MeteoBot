#!/usr/bin/env python3
"""
Monitor Allerte ARPAL - Zona C (La Spezia)

Scarica la pagina https://allertaliguria.regione.liguria.it/, estrae i livelli
per i criteri richiesti, salva lo stato e invia notifiche Telegram se si
verifica un cambiamento e il livello generale è >= Giallo.

Esegue salvataggio dello stato in `arpal_state.json` nella cartella di lavoro.
"""
import requests
import re
import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS as LISTA_CHAT

URL = "https://allertaliguria.regione.liguria.it/"
STATE_FILE = "arpal_state.json"

COLOR_MAP = {"V": "Verde", "G": "Giallo", "A": "Arancione", "R": "Rosso"}
EMOJI = {"Verde": "🟢", "Giallo": "🟡", "Arancione": "🟠", "Rosso": "🔴"}
ORDER = {"Verde": 0, "Giallo": 1, "Arancione": 2, "Rosso": 3}

CRITERI = [
    "Bacini Piccoli",
    "Bacini Medi",
    "Bacini Grandi",
    "Comuni Costieri",
    "Comuni Interni",
]


def fetch_html() -> Optional[str]:
    headers = {
        "User-Agent": "MeteoBot/1.0 (+https://github.com)"
    }
    try:
        r = requests.get(URL, timeout=15, headers=headers)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"Errore fetching ARPAL: {e}")
        return None


def parse_zone_c(html: str) -> Dict[str, Any]:
    """Estrae i livelli dai blocchi della Zona C.

    Restituisce dict con 'dettaglio' mappa criterio->colore, 'bacini_piccoli_hours' lista di ore con colore non-Verde.
    """
    # Primo tentativo: usare BeautifulSoup se disponibile (più robusto)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Trova contenitori che sembrano riferirsi alla Zona C
        candidates = []
        for tag in soup.find_all(True):
            attrs = " ".join([f"{k}={v}" for k, v in tag.attrs.items() if isinstance(v, str)])
            if "accordion-zone-elem-C" in attrs or "Zona C" in tag.get_text():
                candidates.append(tag)

        dettaglio: Dict[str, str] = {}
        bacini_piccoli_hours: List[str] = []

        # Cerca tabelle nelle candidate e parsale
        for cand in candidates:
            tables = cand.find_all("table")
            for table in tables:
                # estrai righe e celle
                trs = table.find_all("tr")
                ore = []
                # cerca riga con 'Ore'
                for tr in trs:
                    if "Ore" in tr.get_text():
                        tds = tr.find_all("td")
                        ore = [td.get_text(strip=True) for td in tds if td.get_text(strip=True).isdigit()]
                        break

                for criterio in CRITERI:
                    for tr in trs:
                        if criterio in tr.get_text():
                            # cerca elementi con class like allertaX
                            cells = tr.find_all(True)
                            colors_raw = []
                            for el in tr.find_all(True):
                                cls = el.get("class")
                                if cls:
                                    for c in cls:
                                        m = re.match(r"allerta([A-Za-z])", c)
                                        if m:
                                            colors_raw.append(m.group(1))
                            # fallback: testo nelle td
                            if not colors_raw:
                                tds = tr.find_all("td")
                                for td in tds:
                                    txt = td.get_text(strip=True).upper()
                                    if "VERDE" in txt:
                                        colors_raw.append("V")
                                    elif "GIALLA" in txt or "GIALLO" in txt:
                                        colors_raw.append("G")
                                    elif "ARANCIONE" in txt:
                                        colors_raw.append("A")
                                    elif "ROSSA" in txt or "ROSSO" in txt:
                                        colors_raw.append("R")

                            # determina colore
                            ora_corrente = datetime.now().hour
                            color = None
                            if ore and colors_raw:
                                ora_str = f"{ora_corrente:02d}"
                                if ora_str in ore:
                                    idx = ore.index(ora_str)
                                    if idx < len(colors_raw):
                                        color = COLOR_MAP.get(colors_raw[idx], "Sconosciuto")
                            if not color and colors_raw:
                                mapped = [COLOR_MAP.get(c, "Sconosciuto") for c in colors_raw]
                                mapped_sorted = sorted(mapped, key=lambda x: ORDER.get(x, 0), reverse=True)
                                color = mapped_sorted[0] if mapped_sorted else "Sconosciuto"

                            if criterio == "Bacini Piccoli" and ore and colors_raw:
                                hours_non_verdi = []
                                for i, c in enumerate(colors_raw):
                                    colore = COLOR_MAP.get(c, "Sconosciuto")
                                    if colore != "Verde" and i < len(ore):
                                        hours_non_verdi.append(ore[i])
                                bacini_piccoli_hours = hours_non_verdi

                            dettaglio[criterio] = color or "Sconosciuto"

        # Se non abbiamo trovato nulla con BS4, caduta nel parsing regex
        if not dettaglio:
            raise RuntimeError("BS4 parsing non ha trovato dati; fallback regex")

        # Determina livello massimo
        max_livello = "Verde"
        max_criterio = ""
        for k, v in dettaglio.items():
            if ORDER.get(v, 0) > ORDER.get(max_livello, 0):
                max_livello = v
                max_criterio = k

        return {
            "dettaglio": dettaglio,
            "max_livello": max_livello,
            "max_criterio": max_criterio,
            "emoji": EMOJI.get(max_livello, "⚪"),
            "bacini_piccoli_hours": bacini_piccoli_hours,
            "ora": datetime.now().hour,
        }
    except Exception as e:
        # Fallback al parsing regex precedente
        print(f"BS4 non disponibile o parsing fallito ({e}), uso fallback regex")
        sections = list(re.finditer(r"accordion-zone-elem-C", html))
        if not sections:
            # fallback immagini
            img_match = re.findall(r'AREA_C_(\w)\.png', html)
            dettaglio = {c: "Sconosciuto" for c in CRITERI}
            bacini_piccoli_hours = []
            if img_match:
                colore = COLOR_MAP.get(img_match[0], "Sconosciuto")
                dettaglio = {c: colore for c in CRITERI}
                max_livello = colore
                max_criterio = "Generale"
                return {
                    "dettaglio": dettaglio,
                    "max_livello": max_livello,
                    "max_criterio": max_criterio,
                    "emoji": EMOJI.get(max_livello, "⚪"),
                    "bacini_piccoli_hours": bacini_piccoli_hours,
                    "ora": datetime.now().hour,
                }

        # Se arriva qui, usa il parsing regex originale su una finestra
        last_pos = sections[-1].start()
        window = html[last_pos:last_pos + 30000]
        tables = list(re.finditer(r"<table[^>]*>(.*?)</table>", window, re.DOTALL))
        dettaglio = {}
        bacini_piccoli_hours = []
        for tmatch in tables:
            table_html = tmatch.group(1)
            trs = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
            ore = []
            for tr in trs:
                if 'Ore Locali' in tr:
                    ore = re.findall(r"<td>(\d{2})</td>", tr)
                    break
            ora_corrente = datetime.now().hour
            for criterio in CRITERI:
                for tr in trs:
                    if criterio in tr:
                        colors = re.findall(r'class="allerta(\w+)"', tr)
                        if not colors:
                            text_cells = re.findall(r"<td[^>]*>([^<]+)</td>", tr)
                            mapped = []
                            for txt in text_cells:
                                t = txt.strip().upper()
                                if "VERDE" in t:
                                    mapped.append("V")
                                elif "GIALLA" in t or "GIALLO" in t:
                                    mapped.append("G")
                                elif "ARANCIONE" in t:
                                    mapped.append("A")
                                elif "ROSSA" in t or "ROSSO" in t:
                                    mapped.append("R")
                            colors = mapped
                        color = None
                        if ore and colors:
                            ora_str = f"{ora_corrente:02d}"
                            if ora_str in ore:
                                idx = ore.index(ora_str)
                                if idx < len(colors):
                                    color = COLOR_MAP.get(colors[idx], "Sconosciuto")
                        if not color and colors:
                            mapped = [COLOR_MAP.get(c, "Sconosciuto") for c in colors]
                            mapped_sorted = sorted(mapped, key=lambda x: ORDER.get(x, 0), reverse=True)
                            color = mapped_sorted[0] if mapped_sorted else "Sconosciuto"
                        if criterio == "Bacini Piccoli" and ore and colors:
                            hours_non_verdi = []
                            for i, c in enumerate(colors):
                                colore = COLOR_MAP.get(c, "Sconosciuto")
                                if colore != "Verde" and i < len(ore):
                                    hours_non_verdi.append(ore[i])
                            bacini_piccoli_hours = hours_non_verdi
                        dettaglio[criterio] = color or "Sconosciuto"

        max_livello = "Verde"
        max_criterio = ""
        for k, v in dettaglio.items():
            if ORDER.get(v, 0) > ORDER.get(max_livello, 0):
                max_livello = v
                max_criterio = k

        return {
            "dettaglio": dettaglio,
            "max_livello": max_livello,
            "max_criterio": max_criterio,
            "emoji": EMOJI.get(max_livello, "⚪"),
            "bacini_piccoli_hours": bacini_piccoli_hours,
            "ora": datetime.now().hour,
        }

    # Determina livello massimo
    max_livello = "Verde"
    max_criterio = ""
    for k, v in dettaglio.items():
        if ORDER.get(v, 0) > ORDER.get(max_livello, 0):
            max_livello = v
            max_criterio = k

    return {
        "dettaglio": dettaglio,
        "max_livello": max_livello,
        "max_criterio": max_criterio,
        "emoji": EMOJI.get(max_livello, "⚪"),
        "bacini_piccoli_hours": bacini_piccoli_hours,
        "ora": datetime.now().hour,
    }


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def build_message(parsed: Dict[str, Any]) -> str:
    title = f"{parsed['emoji']} ALLERTA ARPAL - Zona C: {parsed['max_livello'].upper()}"
    lines = [title, f"Criterio più grave: {parsed['max_criterio']}", ""]
    # Mostra dettagli criteri
    for crit, col in parsed.get("dettaglio", {}).items():
        emoji = EMOJI.get(col, "⚪")
        lines.append(f"{emoji} {crit}: {col}")

    # Aggiungi informazioni ore per Bacini Piccoli
    hours = parsed.get("bacini_piccoli_hours", [])
    if hours:
        hours_str = ", ".join(sorted(hours))
        lines.append("")
        lines.append(f"🕒 Ore allertamento (Bacini Piccoli): {hours_str}")

    lines.append("")
    lines.append(f"Fonte: {URL}")
    lines.append(f"Orario rilevamento: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    return "\n".join(lines)


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato, skip invio")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in LISTA_CHAT:
        try:
            requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
            print(f"Messaggio inviato a {chat_id}")
        except Exception as e:
            print(f"Errore invio Telegram a {chat_id}: {e}")


def main():
    html = fetch_html()
    if not html:
        return
    try:
        parsed = parse_zone_c(html)
    except Exception as e:
        print(f"Errore parsing ARPAL: {e}")
        return

    state = load_state()
    prev_max = state.get("max_livello")
    prev_detail = state.get("dettaglio", {})
    notifica_inviata = state.get("notifica_inviata", False)

    # Decide se inviare: invia solo se max_livello è >= Giallo, se è cambiato e se non già inviato
    send = False
    if not notifica_inviata and ORDER.get(parsed["max_livello"], 0) >= ORDER.get("Giallo", 1):
        if parsed["max_livello"] != prev_max or parsed.get("dettaglio") != prev_detail:
            send = True

    if send:
        # Costruisci messaggio usando livello più grave come titolo
        msg = build_message(parsed)
        send_telegram(msg)
        # Segna che la notifica è stata inviata
        parsed["notifica_inviata"] = True
    else:
        print("Nessun cambiamento significativo, livello sotto Giallo o notifica già inviata - nessun invio")
        # Mantieni il flag se già presente
        if notifica_inviata:
            parsed["notifica_inviata"] = True

    # Salva sempre lo stato aggiornato
    save_state(parsed)


if __name__ == "__main__":
    main()
