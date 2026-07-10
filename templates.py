# templates.py
"""
Template per la generazione dei messaggi del bot Telegram.
"""

from typing import Dict, List, Optional, Tuple, Any
from config import ALERT_EMOJI, thresholds
import math

def _fmt(val: Any, fmt: str = ".1f", suffix: str = "") -> str:
    if val is None: return "N/D"
    try:
        return f"{float(val):{fmt}}{suffix}"
    except (ValueError, TypeError):
        return str(val)

# ─────────────────────────────────────────────────────────────────────────────
# Sezione 1: Analisi Semplice (per l'utente comune)
# ─────────────────────────────────────────────────────────────────────────────

def render_analisi_semplice(
    obs: Dict,
    params: Dict,
    hourly: Optional[List] = None,
    giorno_label: str = "oggi",
) -> str:
    return render_section1_simple(obs, params, 0, "", giorno_label)

def render_section1_simple(
    obs: Dict,
    params: Dict,
    score: float = 0,
    alert_level: str = "",
    giorno_label: str = "oggi",
) -> str:
    """
    Genera un'analisi narrativa semplificata basata sui dati.
    """
    lines: List[str] = []

    t_max = obs.get("temp_max_c", obs.get("temp_c", 0))
    t_min = obs.get("temp_min_c", obs.get("temp_c", 0))
    rh = obs.get("humidity_pct", 50)
    wmo_dom = int(obs.get("wmo_code", 0) or 0)
    cape = float(params.get("SBCAPE", params.get("CAPE", 0)) or 0)
    r_tot = float(obs.get("rain_24h_mm", 0) or 0)
    vis_m = float(obs.get("visibility_m", 10000) or 10000)
    snow_lvl = float(obs.get("snow_level_m", 2000) or 2000)
    g_max = float(obs.get("wind_gust_kmh", 0) or 0)
    w_max = float(obs.get("wind_speed_kmh", 0) or 0)
    oro = float(params.get("orographic_factor", 0) or 0)

    wd = obs.get("wind_dir_deg", 0)
    if wd is None: wd = 0
    directions = ["Nord", "Nord-Est", "Est", "Sud-Est", "Sud", "Sud-Ovest", "Ovest", "Nord-Ovest"]
    nome_v = directions[int((wd + 22.5) % 360 / 45)]

    # ── Temperatura e Comfort ─────────────────────────────────────────────
    if t_max >= 35:
        lines.append(f"{giorno_label} sarà una giornata di caldo estremo: massime fino a {t_max:.0f}°C.")
    elif t_max >= 30:
        lines.append(f"{giorno_label} si presenta molto caldo: massime attorno a {t_max:.0f}°C, minime di {t_min:.0f}°C.")
    else:
        lines.append(f"{giorno_label} temperature gradevoli: massime sui {t_max:.0f}°C, minime di {t_min:.0f}°C.")

    if rh >= 70 and t_max >= 28:
        lines.append("L'alto tasso di umidità accentuerà il disagio fisico (afa intensa).")
    elif rh <= 35:
        lines.append(f"Aria secca (umidità relativa intorno al {rh:.0f}%): scarsa nuvolosità, buona visibilità e nessun disagio da afa.")

    # ── Precipitazioni e Rischio Convettivo Nascosto ──────────────────────
    scp = float(params.get("SCP", 0) or 0)
    stp = float(params.get("STP", 0) or 0)
    cin = float(params.get("CIN", 0) or 0)
    lcl = float(params.get("LCL", 1500) or 1500)

    is_capped = cin <= thresholds.CIN_STRONG or lcl >= thresholds.LCL_HIGH or rh <= 35
    shear_06 = float(params.get("shear_0_6", 0) or 0)
    shear_organizzato = shear_06 >= thresholds.SHEAR_06_ORGANIZED

    if (stp >= thresholds.STP_MODERATE or scp >= thresholds.SCP_HIGH) and not is_capped and shear_organizzato:
        lines.append(
            "ALLERTA CONVETTIVA: l'atmosfera è molto instabile e lo shear del vento è "
            "sufficiente a organizzare temporali forti, con possibili grandinate di grosse "
            "dimensioni e raffiche violente."
        )
    elif (scp >= thresholds.SCP_MODERATE and shear_organizzato and wmo_dom >= 80) and not is_capped:
        lines.append(
            "ATTENZIONE: energia disponibile e organizzazione del vento favoriscono lo "
            "sviluppo di temporali anche intensi nelle ore centrali/pomeridiane."
        )
    elif cape >= thresholds.SBCAPE_STRONG and not shear_organizzato and wmo_dom < 80:
        lines.append(
            "L'aria è molto instabile (energia convettiva elevata), ma la scarsa "
            "ventilazione in quota rende improbabile che si organizzino temporali: "
            "giornata attesa prevalentemente stabile, salvo isolati episodi di calore."
        )
    elif is_capped and (scp >= thresholds.SCP_MODERATE or cape >= thresholds.SBCAPE_STRONG):
        lines.append(
            "Nonostante l'energia disponibile sia elevata, l'aria secca in quota o "
            "l'inibizione atmosferica dovrebbero impedire lo sviluppo di temporali."
        )
    elif wmo_dom == 99:
        lines.append(
            "ALLERTA TEMPORALE SEVERO: attesi temporali violenti con grandine di grandi "
            "dimensioni. Rischio molto elevato di allagamenti rapidi, possibili danni a strutture. "
            "Evitare spostamenti non necessari durante l'evento."
        )
    elif wmo_dom == 96:
        lines.append(
            "Previsti temporali con grandine: possibili danni a veicoli e strutture leggere "
            "in caso di grandinate. Accumuli di pioggia orari potenzialmente significativi."
        )
    elif wmo_dom == 95:
        if cape >= 1500:
            lines.append(
                f"Temporali probabili, localmente forti, con raffiche e rovesci abbondanti. "
                f"Energia disponibile (SBCAPE {cape:.0f} J/kg) sufficiente per celle organizzate. "
                "Massima attenzione tra il pomeriggio e la sera."
            )
        else:
            lines.append(
                "Temporali attesi, di intensità moderata. Possibili rovesci abbondanti con "
                "accumuli localizzati soprattutto sui versanti appenninici."
            )
    elif wmo_dom == 82:
        lines.append(
            f"Rovesci intensi in arrivo con accumuli previsti di circa {r_tot:.0f} mm nell'arco "
            "della giornata. Possibili disagi nelle zone a bassa quota e prossime ai corsi d'acqua."
        )
    elif wmo_dom in (80, 81):
        lines.append(
            f"Rovesci sparsi nel corso della giornata, più probabili nelle ore pomeridiane. "
            f"Accumulo totale atteso: circa {r_tot:.0f} mm."
        )
    elif wmo_dom in (63, 65):
        lines.append(
            f"Pioggia moderata o intensa: accumulo previsto di circa {r_tot:.0f} mm. "
            "Possibili criticità nei bacini idrografici dell'entroterra spezzino."
        )
    elif wmo_dom == 61:
        lines.append(
            f"Pioggia leggera prevista, con accumuli contenuti (circa {r_tot:.0f} mm). "
            "Nessun rischio idrogeologico significativo."
        )
    elif wmo_dom in (51, 53, 55):
        lines.append("Pioviggine diffusa, fenomeni deboli senza accumuli significativi.")
    elif wmo_dom in (71, 73, 75):
        quota = snow_lvl
        lines.append(
            f"Neve prevista con limite a circa {quota:.0f} m s.l.m. "
            f"{'– possibile accumulo anche in zone costiere e collinari' if quota < 500 else '– fenomeno confinato alle zone appenniniche'}."
        )
    elif wmo_dom in (45, 48):
        lines.append(
            f"Nebbia {'densa ' if vis_m < 200 else ''}su vallate e zone costiere, "
            f"visibilità localmente {'inferiore ai 200 m' if vis_m < 200 else 'ridotta'}."
        )
    elif r_tot > 0:
        lines.append(
            f"Precipitazioni deboli o intermittenti con accumulo di circa {r_tot:.0f} mm. "
            "Nessuna criticità prevista."
        )
    else:
        lines.append("Nessuna precipitazione significativa prevista.")

    # ── Vento ─────────────────────────────────────────────────────────────
    if g_max >= 90:
        lines.append(
            f"VENTO TEMPESTOSO: raffiche di {nome_v} fino a {g_max:.0f} km/h. "
            "Possibili danni a strutture, alberi e reti di distribuzione."
        )
    elif g_max >= 60:
        lines.append(f"Vento forte di {nome_v} con raffiche fino a {g_max:.0f} km/h.")
    elif g_max >= 40:
        lines.append(f"Vento moderato da {nome_v} con raffiche fino a {g_max:.0f} km/h.")
    else:
        lines.append("Vento debole o assente, condizioni di calma in mare e a terra.")

    # ── Note orografiche ──────────────────────────────────────────────────
    if oro >= 0.6 and (wmo_dom >= 61 or cape >= 800):
        lines.append(
            "Il forzante orografico dell'Appennino Ligure risulta molto attivo: "
            "gli accumuli saranno sensibilmente maggiori sulle zone interne."
        )

    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Sezione 2: Analisi Tecnica Dettagliata
# ─────────────────────────────────────────────────────────────────────────────

def render_section2_detailed(
    obs: Dict,
    params: Dict,
    mode: str,
    hazards: List[str],
    alert_detail: Optional[Dict[str, str]] = None,
) -> str:
    lines: List[str] = []
    lines.append("═══ ANALISI TECNICA METEOROLOGICA ═══")

    if alert_detail:
        ("\n▌ LIVELLI ALLERTA ARPAL:")
        for risk, lvl in alert_detail.items():
            emoji = ALERT_EMOJI.get(lvl, "⚪")
            lines.append(f"   {emoji} {risk.capitalize()}: {lvl.upper()}")

    lines.append("\n▌ INDICI DI INSTABILITÀ:")
    sbcape = params.get("SBCAPE", params.get("CAPE", 0))
    mucape = params.get("MUCAPE", sbcape)
    mlcape = params.get("MLCAPE", sbcape)
    lines.append(f"   SBCAPE : {_fmt(sbcape, '.0f', ' J/kg')} | MUCAPE : {_fmt(mucape, '.0f', ' J/kg')}")
    lines.append(f"   LI     : {_fmt(params.get('LI'), '.1f')} | PWAT   : {_fmt(params.get('PWAT'), '.1f', ' mm')}")

    lines.append("\n▌ SHEAR E ROTAZIONE:")
    shear06 = params.get('shear_0_6')
    srh03 = params.get('srh_0_3')
    lines.append(f" Shear 0–6 km : {_fmt(shear06, '.1f', ' kt')}" if shear06 is not None else " Shear 0–6 km : N/D (profilo vento non disponibile)")
    lines.append(f" SRH 0–3 km : {_fmt(srh03, '.1f', ' m²/s²')}" if srh03 is not None else " SRH 0–3 km : N/D (profilo vento non disponibile)")

    lines.append("\n▌ INDICI COMPOSITI:")
    scp = params.get('SCP')
    stp = params.get('STP')
    lines.append(f" SCP : {_fmt(scp, '.2f')} | STP : {_fmt(stp, '.2f')}" if (scp is not None and stp is not None) else " SCP/STP : N/D (richiede profilo vento completo)")

    lines.append(f"\n▌ MODALITÀ CONVETTIVA:\n   {mode}")

    lr03 = params.get("lr_0_3km")
    lr_mid = params.get("lr_700_500")

    if lr03 is not None or lr_mid is not None:
        lines.append("\n▌ GRADIENTI TERMICI:")
        if lr03 is not None:
            instab = "MOLTO INSTABILE" if lr03 >= 8 else ("instabile" if lr03 >= 6.5 else "stabile")
            lines.append(f"   LR 0–3 km    : {lr03:.1f} K/km  ({instab})")
        if lr_mid is not None:
            lines.append(f"   LR 700–500 hPa: {lr_mid:.1f} K/km")
        t850 = params.get("T_850hPa")
        t700 = params.get("T_700hPa")
        t500 = params.get("T_500hPa")
        if t850 is not None and t700 is not None and t500 is not None:
            lines.append(f"   T 850/700/500 hPa: {t850:.1f}°C / {t700:.1f}°C / {t500:.1f}°C")

    lines.append("\n▌ FENOMENI POSSIBILI:")
    if hazards:
        for h in hazards:
            lines.append(f"   ⚠ {h}")
    else:
        lines.append("   Nessun fenomeno severo atteso")

    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Sezione 3: Tabella Obiettiva Oraria
# ─────────────────────────────────────────────────────────────────────────────

def render_section3_objective_table(hourly: List[Dict]) -> str:
    if not hourly: return "Dati orari non disponibili."
    
    header = "ORA  | METEO | TEMP | VENTO | PIOGGIA | CAPE "
    sep    = "─────┼───────┼──────┼───────┼─────────┼──────"
    rows = [header, sep]
    
    for h in hourly[:24]:
        t = h.get("time", "")[-5:]
        temp = f"{float(h.get('temperature', 0)):>4.1f}"
        wind = f"{float(h.get('wind_gust', 0)):>3.0f}"
        prec = f"{float(h.get('precip', 0)):>4.1f}"
        cape = f"{float(h.get('cape', 0)):>4.0f}"
        wmo = int(h.get("weather_code", 0))
        
        # Emoji meteo semplice
        icon = "☀️" if wmo < 2 else "⛅" if wmo < 50 else "🌧️" if wmo < 80 else "⛈️"
        
        rows.append(f"{t} |  {icon}   | {temp} |  {wind}  |  {prec}   | {cape}")
        
    return "\n".join(rows)

# ─────────────────────────────────────────────────────────────────────────────
# Prompt per Gemini (L'Intelligenza del Sistema)
# ─────────────────────────────────────────────────────────────────────────────

def build_gemini_prompt_tecnico(
    analisi_tecnica: str,
    params: Dict,
    maltempo_score_val: float,
    giorno_label: str = "oggi",
    is_tendency: bool = False,
    hourly_table: Optional[str] = None,
    spread_data: Optional[Dict] = None,
    ffg_result: Optional[Dict] = None,
    heatwave_result: Optional[Dict] = None,
    uwyo_summary: Optional[str] = None,
    evolution_result: Optional[Dict] = None,
    multi_evolution: Optional[Dict] = None,
    wind_summary: Optional[str] = None,
) -> str:
    from logic import livello_attenzione
    livello, emoji = livello_attenzione(maltempo_score_val)

    prompt = f"""
Sei MeteoBot, un sistema di Intelligenza Artificiale meteorologica avanzata per il Levante Ligure.
Il tuo compito è scrivere un'analisi narrativa professionale ed ELEGANTE basata sui dati forniti.

GIORNO: {giorno_label}
LIVELLO ATTENZIONE: {emoji} {livello} (Score: {maltempo_score_val}/5)

DATI TECNICI:
{analisi_tecnica}

VENTO (dato certo, usa ESATTAMENTE questo, non inventare direzioni o intensità diverse):
{wind_summary if wind_summary else "dato non disponibile"}

EVOLUZIONE ORARIA:
{hourly_table if hourly_table else "Non fornita"}
"""

    # ── Evoluzione e persistenza instabilità (dati esatti, non stimati da Gemini) ──
    if evolution_result and evolution_result.get("windows"):
        ev_lines = []
        for w in evolution_result["windows"]:
            ev_lines.append(
                f"  - {w['start']}-{w['end']} ({w['duration_h']}h): "
                f"CAPE medio {w['cape_avg']:.0f} J/kg, {w['trend']}"
            )
        prompt += (
            "\nEVOLUZIONE INSTABILITÀ (dati calcolati, usa questi orari esatti "
            "senza approssimare o arrotondare diversamente):\n"
            + "\n".join(ev_lines)
            + f"\nPicco assoluto: {evolution_result.get('peak_cape', 0):.0f} J/kg "
              f"alle {evolution_result.get('peak_time', 'n.d.')}\n"
            "ISTRUZIONE: cita SEMPRE durata e orari quando descrivi l'instabilità, "
            "es. 'instabilità elevata per 6 ore, dalle 14 alle 20, in rafforzamento'.\n"
        )

    # ── Evoluzione multi-parametro (CAPE, shear, SRH, PWAT nel tempo) ──
    if multi_evolution:
        prompt += "\nEVOLUZIONE ORARIA COMPLETA (usa questi dati per capire SE e QUANDO l'energia si organizza):\n"
        for key in ("cape", "shear", "srh", "pwat"):
            txt = multi_evolution.get(key)
            if txt:
                prompt += f"  - {txt}\n"
        if multi_evolution.get("synergy_warning"):
            prompt += (
                f"\nATTENZIONE PATTERN RILEVATO: {multi_evolution['synergy_warning']}\n"
                "ISTRUZIONE OBBLIGATORIA: se questo pattern è presente, NON scrivere che l'innesco "
                "è 'totalmente assente'. Scrivi invece che l'energia è presente e priva di freni "
                "(CIN basso) ma manca l'organizzazione dinamica, quindi il rischio principale è la "
                "cella isolata da riscaldamento diurno (specialmente su rilievi/entroterra), non il "
                "sistema organizzato o il nubifragio esteso.\n"
            )

    # ── Spread modelli (AROME vs ICON-EU) ──
    if spread_data:
        sp_lines = []
        for lbl, info in spread_data.items():
            sp_lines.append(
                f"  - {lbl}: AROME={info['AROME']}{info['unit']} vs ICON-EU={info['ICON']}{info['unit']} "
                f"(differenza {info['diff']}{info['unit']}{', SIGNIFICATIVA' if info.get('high') else ''})"
            )
        prompt += (
            "\nDISACCORDO TRA MODELLI (menziona l'incertezza quando è rilevante):\n"
            + "\n".join(sp_lines) + "\n"
        )

    # ── Flash Flood Guidance ──
    if ffg_result:
        prompt += f"\nRISCHIO ALLUVIONE LAMPO: {ffg_result.get('desc', '')}\n"

    # ── Ondata di calore ──
    if heatwave_result and heatwave_result.get("is_heatwave"):
        prompt += f"\nONDATA DI CALORE IN CORSO: {heatwave_result.get('desc', '')}\n"

    # ── Sounding osservato (UWYO) ──
    if uwyo_summary:
        prompt += f"\nRADIOSONDAGGIO OSSERVATO (dato reale, non da modello): {uwyo_summary}\n"

    prompt += """
ISTRUZIONI PER L'ANALISI — SEGUI RIGOROSAMENTE:

REGOLA CRITICA: Usa ESCLUSIVAMENTE i valori numerici forniti nei dati tecnici.
    NON inventare raffiche, temperature o velocità del vento non presenti nei dati.
    Se un parametro è 'N/D', NON menzionarlo o ipotizzarne il valore.
    Se CAPE e shear provengono da fonti diverse, non trarre conclusioni che le contraddicano.
    Se lo shear è 'N/D', NON parlare di organizzazione del vento o raffiche specifiche.

1. REALISMO PRIMA DI TUTTO, MA SENZA FALSE CERTEZZE: descrivi COSA SUCCEDERÀ REALMENTE
   secondo i dati. Se CAPE è alto ma CIN è forte/moderato (inibizione presente), puoi
   scrivere con sicurezza che la giornata sarà stabile. MA se CAPE è alto E CIN è quasi
   nullo (vicino a zero) E non c'è shear organizzato, NON scrivere che l'innesco è
   "totalmente assente" o che il cielo sarà "sereno per l'intero arco della giornata":
   questa è una combinazione in cui una cella isolata da riscaldamento diurno resta
   possibile, anche se improbabile un sistema organizzato o un nubifragio esteso.
   In questo caso specifico scrivi che il rischio è basso ma non nullo, concentrato
   nelle ore centrali/pomeridiane e più probabile su rilievi/entroterra.
   Non descrivere mai downburst, grandine, trombe marine o nubifragi diffusi come se
   accadessero certamente, se i dati orari non mostrano già pioggia prevista.
2. NIENTE CONTRADDIZIONI: non scrivere mai nella stessa risposta sia "cielo sereno tutto
   il giorno" sia "rischio di downburst/nubifragi/trombe marine" per lo stesso giorno.
   Se l'innesco manca, di' semplicemente che il rischio resta teorico e improbabile,
   senza elencare i fenomeni come se fossero attesi.
3. SOLO SE C'È INNESCO REALE (pioggia/temporali nei dati): specifica quando (fascia oraria)
   e quali fenomeni concreti sono plausibili (grandine, raffiche, allagamenti).
4. STILE: italiano semplice e diretto, tono da meteorologo che parla al pubblico, non
   accademico. Evita termini come "instabilità latente profonda" se poi non succede nulla:
   di' semplicemente "l'aria è instabile ma mancano le condizioni per scatenare temporali".
5. LUNGHEZZA MASSIMA TASSATIVA: 100 PAROLE. Non superare mai questo limite. Se necessario
   taglia dettagli tecnici secondari pur di restare entro 100 parole.

RISPONDI SOLO CON L'ANALISI NARRATIVA, MASSIMO 100 PAROLE.
"""
    return prompt.strip()

# ─────────────────────────────────────────────────────────────────────────────
# Template Telegram Elegante
# ─────────────────────────────────────────────────────────────────────────────

def render_telegram_message(
    giorno: str,
    alert_emoji: str,
    alert_level: str,
    score: float,
    descrizione_ia: str,
    analisi_semplice: str,
    analisi_tecnica: str,
    tabella_oraria: str
) -> str:
    """
    Genera il messaggio finale per Telegram con uno stile elegante e professionale.
    """
    return f"""
<b>{alert_emoji} BOLLETTINO METEO BOT | {giorno.upper()}</b>
━━━━━━━━━━━━━━━━━━━━━━
<b>{alert_emoji} LIVELLO ATTENZIONE: {alert_level.upper()}</b>
<i>Indice di criticità: {score}/5.0</i>

<b>◈ SINTESI PREVISIONALE</b>
{analisi_semplice}

<b>◈ ANALISI DELL'ESPERTO (IA)</b>
{descrizione_ia}

<b>◈ DETTAGLIO TECNICO</b>
<code>{analisi_tecnica}</code>

<b>◈ EVOLUZIONE ORARIA</b>
<code>{tabella_oraria}</code>
━━━━━━━━━━━━━━━━━━━━━━
<i>Generato da MeteoBot Engine v2.0 | La Spezia</i>
""".strip()

def analizza_evoluzione_oraria(hourly: List[Dict]) -> str:
    """Valuta il trend orario dividendolo per fasce e crea una struttura descrittiva."""
    if not hourly:
        return "Nessun dato orario per analizzare l'evoluzione."
        
    fasce = {"Mattina (06-12)": [], "Pomeriggio (12-18)": [], "Sera (18-24)": [], "Notte (00-06)": []}
    
    for h in hourly[:24]: # Controlla le prossime 24h
        ora_str = h.get("time", "00:00")
        try:
            ora = int(ora_str.split(":")[0])
        except ValueError:
            continue
            
        p = float(h.get("precip", 0) or 0)
        c = float(h.get("CAPE", 0) or 0)
        
        if 6 <= ora < 12: fasce["Mattina (06-12)"].append((p, c))
        elif 12 <= ora < 18: fasce["Pomeriggio (12-18)"].append((p, c))
        elif 18 <= ora <= 23: fasce["Sera (18-24)"].append((p, c))
        else: fasce["Notte (00-06)"].append((p, c))
        
    trend = []
    for nome, dati in fasce.items():
        if not dati: continue
        pioggia_max = max((d[0] for d in dati), default=0)
        cape_max = max((d[1] for d in dati), default=0)
        
        desc_pioggia = ""
        if pioggia_max > 10: desc_pioggia = "Rovesci intensi"
        elif pioggia_max > 2: desc_pioggia = "Piogge moderate"
        elif pioggia_max > 0.1: desc_pioggia = "Deboli piovaschi"
        
        desc_cape = "Elevata instabilità" if cape_max > 1000 else ("Instabilità latente" if cape_max > 400 else "")
        
        if desc_pioggia or desc_cape:
            elementi = [e for e in [desc_pioggia, desc_cape] if e]
            trend.append(f"• {nome}: {', '.join(elementi)}")
            
    if not trend:
        return "Condizioni stabili sull'intero arco della giornata."
    return "\n".join(trend)

def costuisci_bollettino_compatto(obs: Dict, params: Dict, hourly: List[Dict], mode: str, hazards_dict: Dict[str, List[str]], score: float, alert_level: str, alert_emoji: str) -> str:
    """Costruisce un messaggio modulare, compatto, analitico e senza sprechi di spazio."""
    
    t_max = _fmt(obs.get("temp_max_c", obs.get("temp_c", 0)), ".0f")
    t_min = _fmt(obs.get("temp_min_c", obs.get("temp_c", 0)), ".0f")
    cape = _fmt(params.get("SBCAPE", 0), ".0f")
    cin = _fmt(params.get("CIN", 0), ".0f")
    pwat = _fmt(params.get("PWAT", 0), ".1f")
    shear = _fmt(params.get("shear_0_6", 0), ".0f")
    lr = _fmt(params.get("lr_700_500", 0), ".1f")
    wind = _fmt(obs.get("wind_gust_kmh", 0), ".0f")
    
    evoluzione_testo = analizza_evoluzione_oraria(hourly)
    
    reali = hazards_dict.get("reali", [])
    potenziali = hazards_dict.get("potenziali", [])
    
    rischi_str = ""
    if reali:
        rischi_str += "\n⚠️ RISCHI IN ATTO/CERTI:\n" + "\n".join([f"  - {h}" for h in reali])
    if potenziali:
        rischi_str += "\n⏳ RISCHI LATENTI (Richiedono innesco):\n" + "\n".join([f"  - {h}" for h in potenziali])
    if not reali and not potenziali:
        rischi_str += "\n🟢 Nessun fenomeno severo atteso."

    # Assemblaggio ultra-compatto
    msg = f"""{alert_emoji} PREVISIONI LA SPEZIA | Livello: {alert_level.upper()} ({score}/5)
🌡 T. Min: {t_min}°C | T. Max: {t_max}°C | 🌬 Raffiche: {wind} km/h

📊 TERMODINAMICA E DINAMICA:
SBCAPE: {cape} J/kg | CIN: {cin} J/kg | PWAT: {pwat} mm
Shear 0-6km: {shear} kt | Gradiente 700-500hPa: {lr} K/km
Modalità convettiva: {mode.capitalize()}

⏱ EVOLUZIONE PREVISTA:
{evoluzione_testo}
{rischi_str}"""

    return msg.strip()
