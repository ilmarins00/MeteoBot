#!/usr/bin/env python3
"""
Monitor Allerte ARPAL - Zona C (La Spezia)

Scarica la pagina https://allertaliguria.regione.liguria.it/, estrae i livelli
per i criteri richiesti, salva lo stato e invia notifiche Telegram se si
verifica un cambiamento e il livello generale è >= Giallo.

Novità rispetto alla versione base:
- Parsing robusto dei Bacini Piccoli con timeline oraria completa
- Parsing dell'avviso di vigilanza meteorologica (testo in homepage)
- Supporto sotto-zone C / C+ / C- (quando presenti)
- Logica notifica migliorata: re-invia se livello peggiora, non solo cambia

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
URL_VIGILANZA = "https://allertaliguria.regione.liguria.it/"
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

# Sotto-zone della Zona C (usate quando ARPAL differenzia ulteriormente)
SOTTO_ZONE_C = ["C", "C+", "C-"]


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

    Restituisce dict con:
    - 'dettaglio': mappa criterio->colore
    - 'bacini_piccoli_hours': lista di ore con colore non-Verde
    - 'bacini_piccoli_timeline': lista [{'ora': 'HH', 'livello': 'Giallo/Arancione/Rosso'}]
    - 'sotto_zone': dict delle eventuali sotto-zone C, C+, C-
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
        bacini_piccoli_timeline: List[Dict[str, str]] = []
        sotto_zone: Dict[str, str] = {}

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

                            # determina colore ora corrente o max
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

                            # Timeline completa per Bacini Piccoli
                            if criterio == "Bacini Piccoli" and ore and colors_raw:
                                hours_non_verdi = []
                                timeline_completa = []
                                for i, c in enumerate(colors_raw):
                                    colore = COLOR_MAP.get(c, "Sconosciuto")
                                    ora_label = ore[i] if i < len(ore) else f"h{i}"
                                    timeline_completa.append({"ora": ora_label, "livello": colore})
                                    if colore != "Verde":
                                        hours_non_verdi.append(ora_label)
                                bacini_piccoli_hours = hours_non_verdi
                                bacini_piccoli_timeline = timeline_completa

                            dettaglio[criterio] = color or "Sconosciuto"

            # Cerca sotto-zone C, C+, C- nella tabella
            text_block = cand.get_text()
            for sz in SOTTO_ZONE_C:
                pattern = rf"Zona\s+{re.escape(sz)}\s*[:\-–]\s*(Verde|Giallo|Gialla|Arancione|Rossa|Rosso)"
                match = re.search(pattern, text_block, re.IGNORECASE)
                if match:
                    raw = match.group(1).strip().capitalize()
                    if raw == "Gialla":
                        raw = "Giallo"
                    if raw == "Rossa":
                        raw = "Rosso"
                    sotto_zone[sz] = raw

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
            "bacini_piccoli_timeline": bacini_piccoli_timeline,
            "sotto_zone": sotto_zone,
            "ora": datetime.now().hour,
        }
    except Exception as e:
        # Fallback al parsing regex precedente
        print(f"BS4 non disponibile o parsing fallito ({e}), uso fallback regex")
        return _parse_zone_c_regex(html)


def _parse_zone_c_regex(html: str) -> Dict[str, Any]:
    """Fallback regex per parsing Zona C (usato se BS4 non è disponibile)."""
    sections = list(re.finditer(r"accordion-zone-elem-C", html))
    dettaglio: Dict[str, str] = {}
    bacini_piccoli_hours: List[str] = []
    bacini_piccoli_timeline: List[Dict[str, str]] = []

    if not sections:
        # fallback immagini
        img_match = re.findall(r'AREA_C_(\w)\.png', html)
        if img_match:
            colore = COLOR_MAP.get(img_match[0], "Sconosciuto")
            dettaglio = {c: colore for c in CRITERI}
            return {
                "dettaglio": dettaglio,
                "max_livello": colore,
                "max_criterio": "Generale",
                "emoji": EMOJI.get(colore, "⚪"),
                "bacini_piccoli_hours": [],
                "bacini_piccoli_timeline": [],
                "sotto_zone": {},
                "ora": datetime.now().hour,
            }

    last_pos = sections[-1].start()
    window = html[last_pos:last_pos + 30000]
    tables = list(re.finditer(r"<table[^>]*>(.*?)</table>", window, re.DOTALL))

    for tmatch in tables:
        table_html = tmatch.group(1)
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        ore: List[str] = []
        for tr in trs:
            if 'Ore Locali' in tr or 'Ore' in tr:
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
                        mapped_colors = [COLOR_MAP.get(c, "Sconosciuto") for c in colors]
                        mapped_sorted = sorted(
                            mapped_colors, key=lambda x: ORDER.get(x, 0), reverse=True
                        )
                        color = mapped_sorted[0] if mapped_sorted else "Sconosciuto"
                    if criterio == "Bacini Piccoli" and ore and colors:
                        for i, c in enumerate(colors):
                            colore = COLOR_MAP.get(c, "Sconosciuto")
                            ora_label = ore[i] if i < len(ore) else f"h{i}"
                            bacini_piccoli_timeline.append(
                                {"ora": ora_label, "livello": colore}
                            )
                            if colore != "Verde":
                                bacini_piccoli_hours.append(ora_label)
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
        "bacini_piccoli_timeline": bacini_piccoli_timeline,
        "sotto_zone": {},
        "ora": datetime.now().hour,
    }


def parse_vigilanza(html: str) -> Optional[str]:
    """Estrae l'avviso di vigilanza meteorologica dalla homepage ARPAL.

    Cerca il banner/box testuale che annuncia la vigilanza meteo,
    tipicamente presente prima dell'emissione dell'allerta formale.
    Restituisce il testo estratto o None se non presente.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        keyword_re = re.compile(
            r"vigilanza|avviso\s+meteo(?:rologico)?|bollettino\s+di\s+vigilanza",
            re.IGNORECASE,
        )
        nav_noise_re = re.compile(
            r"\b(menu|homepage|messaggi|social\s+network|dati\s+in\s+tempo\s+reale|"
            r"guida\s+all'?allerta|link\s+utili|contatti)\b",
            re.IGNORECASE,
        )

        def normalize(text: str) -> str:
            return re.sub(r"\s+", " ", text).strip()

        def is_nav_like(text: str) -> bool:
            lowered = text.lower()
            if nav_noise_re.search(lowered):
                return True
            # testo tipico del menu: molte voci concatenate e quasi nessuna punteggiatura
            if len(text) > 120 and text.count(".") == 0 and text.count(":") <= 1:
                nav_hits = len(re.findall(r"homepage|messaggi|guida|contatti|social", lowered))
                if nav_hits >= 2:
                    return True
            return False

        candidates: List[tuple[int, str]] = []
        for tag in soup.find_all(["div", "section", "article", "p"]):
            text = normalize(tag.get_text(" ", strip=True))
            if not text or len(text) < 35 or len(text) > 1200:
                continue
            if not keyword_re.search(text):
                continue
            if is_nav_like(text):
                continue

            score = 1
            low = text.lower()
            if "data emissione" in low:
                score += 3
            if "consulta il bollettino" in low:
                score += 2
            if "scarica il pdf" in low:
                score += 1

            cleaned = re.sub(r"(scarica\s+il\s+pdf\s*\([^\)]*\)\s*)+", "", text, flags=re.IGNORECASE)
            cleaned = normalize(cleaned)
            if cleaned:
                candidates.append((score, cleaned))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
    except Exception:
        pass

    # Fallback regex
    patterns = [
        r'(?:vigilanza|avviso\s+meteo(?:rologico)?)[^<]{20,500}',
        r'bollettino\s+di\s+vigilanza[^<]{20,500}',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group(0))
            text = re.sub(r'\s+', ' ', text).strip()
            if (
                30 < len(text) < 1000
                and not re.search(r"homepage|messaggi|social network|guida all'allerta", text, re.IGNORECASE)
            ):
                return text
    return None


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


def build_message(parsed: Dict[str, Any], vigilanza: Optional[str] = None) -> str:
    """Costruisce il messaggio Telegram con dettaglio completo Zona C."""
    title = f"{parsed['emoji']} ALLERTA ARPAL — Zona C: {parsed['max_livello'].upper()}"
    dettaglio = parsed.get("dettaglio", {})

    # Dettaglio criteri con emoji per livello
    criteri_lines = []
    for k, v in dettaglio.items():
        em = EMOJI.get(v, "⚪")
        criteri_lines.append(f"  {em} {k}: {v}")
    criteri_block = "\n".join(criteri_lines)

    # Sotto-zone (se presenti)
    sotto_zone = parsed.get("sotto_zone", {})
    sotto_str = ""
    if sotto_zone:
        sz_items = [f"  {EMOJI.get(v, '⚪')} Zona {k}: {v}" for k, v in sotto_zone.items()]
        sotto_str = "\nSotto-zone:\n" + "\n".join(sz_items) + "\n"

    # Timeline Bacini Piccoli (focus)
    timeline = parsed.get("bacini_piccoli_timeline", [])
    timeline_non_verde = [t for t in timeline if t.get("livello", "Verde") != "Verde"]
    if timeline_non_verde:
        timeline_str = ", ".join(
            [f"{EMOJI.get(t['livello'], '⚪')}{t['ora']}:00" for t in timeline_non_verde]
        )
        ore_line = f"🕐 Bacini Piccoli – ore di allertamento: {timeline_str}"
    elif timeline:
        ore_line = "🕐 Bacini Piccoli: tutto in Verde per le ore previste."
    else:
        ore_line = "🕐 Bacini Piccoli: nessun dato orario disponibile."

    # Vigilanza meteorologica
    vig_str = ""
    if vigilanza:
        # Tronca se troppo lungo per Telegram
        vig_trunc = vigilanza[:400] + "..." if len(vigilanza) > 400 else vigilanza
        vig_str = f"\n📋 *Vigilanza meteorologica:*\n{vig_trunc}\n"

    criterio_max = parsed.get('max_criterio') or 'n/d'

    text = (
        f"{title}\n"
        f"Livello massimo: {parsed['max_livello']}"
        f" (criterio più grave: {criterio_max})\n\n"
        f"📊 *Dettaglio criteri:*\n{criteri_block}\n"
        f"{sotto_str}\n"
        f"{ore_line}\n"
        f"{vig_str}\n"
        f"🔗 Fonte: {URL}\n"
        f"🕒 Rilevamento: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    return text


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not LISTA_CHAT:
        print("Telegram non configurato, skip invio")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in LISTA_CHAT:
        try:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok"):
                print(f"Messaggio inviato a {chat_id}")
            else:
                print(f"Errore Telegram API per {chat_id}: {payload}")
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

    # Parsing avviso di vigilanza
    vigilanza = parse_vigilanza(html)
    if vigilanza:
        print(f"Avviso di vigilanza trovato: {vigilanza[:120]}...")
    else:
        print("Nessun avviso di vigilanza presente")

    state = load_state()
    prev_max = state.get("max_livello", "Verde")
    prev_detail = state.get("dettaglio", {})
    prev_vigilanza = state.get("vigilanza")
    notifica_inviata = state.get("notifica_inviata", False)

    # ── Logica invio migliorata ──
    # Invia se:
    # 1. Livello >= Giallo E (livello peggiorato rispetto a prima O dettaglio cambiato)
    # 2. Nuovo avviso di vigilanza significativo
    # 3. Livello tornato a Verde dopo un'allerta (messaggio di cessazione)
    send = False
    motivo = ""

    livello_attuale = parsed.get("max_livello", "Verde")
    livello_num = ORDER.get(livello_attuale, 0)
    livello_prev_num = ORDER.get(prev_max, 0)

    if livello_num >= ORDER.get("Giallo", 1):
        if not notifica_inviata:
            # Prima notifica di questa allerta
            send = True
            motivo = "Nuova allerta"
        elif livello_num > livello_prev_num:
            # Livello peggiorato (es. Giallo → Arancione)
            send = True
            motivo = f"Peggioramento: {prev_max} → {livello_attuale}"
        elif parsed.get("dettaglio") != prev_detail:
            # Dettaglio cambiato (nuovi criteri coinvolti)
            send = True
            motivo = "Dettaglio criteri aggiornato"

    # Cessazione allerta: era >= Giallo, ora è Verde
    if livello_prev_num >= ORDER.get("Giallo", 1) and livello_num == 0:
        if notifica_inviata:
            send = True
            motivo = f"Cessazione allerta (era {prev_max})"

    # Nuovo avviso di vigilanza (significativamente diverso)
    if vigilanza and vigilanza != prev_vigilanza:
        if not send:
            # Invia solo vigilanza se non stiamo già inviando per allerta
            send = True
            motivo = "Nuovo avviso di vigilanza"

    if send:
        print(f"📤 Invio notifica ARPAL: {motivo}")
        msg = build_message(parsed, vigilanza)
        send_telegram(msg)
        parsed["notifica_inviata"] = True
    else:
        reason = "livello sotto Giallo" if livello_num < 1 else "nessun cambiamento"
        if notifica_inviata:
            reason += ", notifica già inviata"
        print(f"Nessun invio: {reason}")
        if notifica_inviata and livello_num >= 1:
            parsed["notifica_inviata"] = True

    # Salva stato con vigilanza
    parsed["vigilanza"] = vigilanza
    save_state(parsed)


if __name__ == "__main__":
    main()
