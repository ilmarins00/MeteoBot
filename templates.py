# templates.py
"""
Template per la generazione dei messaggi del bot Telegram.
"""

from typing import Dict, List, Optional, Tuple, Any
from config import ALERT_EMOJI, thresholds
import math

# --- INIZIO FUNZIONE DI SOCCORSO CORREZIONE _FTM ---
def _ftm(val, fmt_str=".0f", unit=""):
    if val is None:
        return "-"
    try:
        return f"{float(val):{fmt_str}}{unit}"
    except Exception:
        return f"{val}{unit}"

_fmt = _ftm

_COMPASS_16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
               "S","SSO","SO","OSO","O","ONO","NO","NNO"]

def _wind_dir_16(deg):
    if deg is None: return "N/D"
    return _COMPASS_16[int((float(deg)+11.25)%360/22.5)]

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

_RISK_EMOJI = {
    "Trascurabile": "⬜",
    "Marginale": "🟩",
    "Moderato": "❗",
    "Elevato": "‼️",
    "Estremo": "🟥",
}

def _intensity_label(name: str, val) -> str:
    """Restituisce l'intensità del parametro invece della sua definizione."""
    if val is None:
        return "N/D"
    v = float(val)
    t = thresholds

    if name in ("SBCAPE", "MUCAPE"):
        if v < t.SBCAPE_WEAK: return "Trascurabile"
        if v < t.SBCAPE_MODERATE: return "Debole"
        if v < t.SBCAPE_STRONG: return "Moderato"
        if v < t.SBCAPE_EXTREME: return "Forte"
        return "Estremo"
    if name == "CIN":
        av = abs(v)
        if av < abs(t.CIN_WEAK): return "Assente/Debole"
        if av < abs(t.CIN_MODERATE): return "Moderata"
        if av < abs(t.CIN_STRONG): return "Forte"
        return "Molto forte (blocca convezione)"
    if name == "LI":
        if v <= t.LI_EXTREME: return "Estremo"
        if v <= t.LI_VERY_UNSTABLE: return "Molto instabile"
        if v <= t.LI_UNSTABLE: return "Instabile"
        if v < 0: return "Debolmente instabile"
        return "Stabile"
    if name == "Shear06":
        if v < t.SHEAR_06_WEAK: return "Debole"
        if v < t.SHEAR_06_ORGANIZED: return "Moderato"
        if v < t.SHEAR_06_SUPERCELL: return "Organizzato"
        if v < t.SHEAR_06_EXTREME: return "Forte (supercella)"
        return "Estremo"
    if name == "SRH03":
        if v < t.SRH_03_LOW: return "Basso"
        if v < t.SRH_03_MODERATE: return "Moderato"
        if v < t.SRH_03_HIGH: return "Alto"
        return "Molto alto"
    if name == "PWAT":
        if v < t.PWAT_DRY: return "Secco"
        if v < t.PWAT_NORMAL: return "Normale"
        if v < t.PWAT_HUMID: return "Umido"
        if v < t.PWAT_EXTREME: return "Molto umido"
        return "Estremo (tropicale)"
    if name == "SCP":
        if v < t.SCP_MODERATE: return "Basso"
        if v < t.SCP_HIGH: return "Moderato (favorevole a supercelle)"
        return "Elevato"
    if name == "K-Index":
        if v < t.KI_MODERATE: return "Basso"
        if v < t.KI_STRONG: return "Moderato"
        if v < t.KI_EXTREME: return "Alto"
        return "Molto alto (certi)"
    if name == "Totals-Totals":
        if v < t.TT_MODERATE: return "Basso"
        if v < t.TT_STRONG: return "Moderato"
        if v < t.TT_EXTREME: return "Alto"
        return "Molto alto (rischio tornado)"
    if name == "DCAPE":
        if v < t.DCAPE_LOW: return "Basso"
        if v < t.DCAPE_MODERATE: return "Moderato"
        if v < t.DCAPE_HIGH: return "Alto"
        return "Molto alto (raffiche severe)"
    return ""


def render_tech_table_html(params: Dict, hourly: Optional[List[Dict]] = None) -> str:
    """
    Tabella HTML a 3 colonne: parametro | valore | intensità.
    Se `hourly` è fornito, CAPE/CIN/LI/Shear06/SRH03/Raffica vengono presi
    dall'ora di picco SBCAPE/MUCAPE (stessa ora), per coerenza interna.
    """
    peak = {}
    if hourly:
        peak = max(hourly, key=lambda h: float(h.get("CAPE") or 0), default={}) or {}

    def pv(params_key, hourly_key=None, default=None):
        if peak and hourly_key and peak.get(hourly_key) is not None:
            return peak.get(hourly_key)
        return params.get(params_key, default)

    rows = [
        ("SBCAPE",  pv("SBCAPE", "CAPE"),  "J/kg"),
        ("MUCAPE",  pv("MUCAPE", "CAPE"),  "J/kg"),
        ("CIN",     pv("CIN", "CIN"),      "J/kg"),
        ("LI",      pv("LI", "LI"),        ""),
        ("Shear06", pv("shear_0_6", "shear"), "kt"),
        ("SRH03",   pv("srh_0_3", "SRH"),  "m²/s²"),
        ("PWAT",    pv("PWAT", "PWAT"),    "mm"),
        ("SCP",     pv("SCP", "SCP"),      ""),
        ("K-Index", pv("KI", "KI"),        ""),
        ("Totals-Totals", pv("TT", "TT"),  ""),
        ("DCAPE",   pv("DCAPE", "DCAPE"),  "J/kg"),
    ]
    html = '<table style="border-collapse:collapse;width:100%;font-size:14px">'
    html += '<tr style="background:#e0e0e0"><th style="padding:6px;border:1px solid #999;text-align:left">Parametro</th>'
    html += '<th style="padding:6px;border:1px solid #999;text-align:left">Valore</th>'
    html += '<th style="padding:6px;border:1px solid #999;text-align:left">Intensità</th></tr>'
    for name, val, unit in rows:
        vstr = _fmt(val, '.1f', f' {unit}') if val is not None else "N/D"
        intensity = _intensity_label(name, val)
        html += f'<tr><td style="padding:6px;border:1px solid #ccc">{name}</td>'
        html += f'<td style="padding:6px;border:1px solid #ccc">{vstr}</td>'
        html += f'<td style="padding:6px;border:1px solid #ccc;color:#555">{intensity}</td></tr>'
    html += '</table>'
    return html

_RISK_DESCRIPTIONS = {
    "Trascurabile": "assenza o quasi di fenomeni intensi",
    "Marginale": "bassa probabilità di fenomeni intensi isolati",
    "Moderato": "probabilità significativa di fenomeni localmente intensi",
    "Elevato": "fenomeni intensi estesi e diffusi",
    "Estremo": "fenomeni molto intensi, persistenti e generalizzati",
}

def render_phenomena_risks(risks: Dict[str, str]) -> str:
    """Renderizza la tabella dei rischi per fenomeno."""
    lines = ["📋 RISCHIO FENOMENI INTENSI"]
    for phen, level in risks.items():
        emoji = _RISK_EMOJI.get(level, "⚪")
        desc = _RISK_DESCRIPTIONS.get(level, "")
        lines.append(f"  {emoji} {phen:<12} {level} — {desc}")
    return "\n".join(lines)

def render_phenomena_risks_html(risks: Dict[str, str]) -> str:
    """Versione HTML della tabella rischi fenomeni (stessa struttura del testo Telegram)."""
    rows = ""
    for phen, level in risks.items():
        emoji = _RISK_EMOJI.get(level, "⚪")
        desc = _RISK_DESCRIPTIONS.get(level, "")
        rows += (
            f'<tr><td style="padding:4px 8px">{emoji}</td>'
            f'<td style="padding:4px 8px"><b>{phen}</b></td>'
            f'<td style="padding:4px 8px">{level}</td>'
            f'<td style="padding:4px 8px;color:#555">{desc}</td></tr>'
        )
    return (
        '<div style="margin:8px 0"><b>📋 RISCHIO FENOMENI INTENSI</b>'
        '<table style="border-collapse:collapse;width:100%;font-size:14px;margin-top:4px">'
        + rows + '</table></div>'
    )

def render_fenomeni_html(reali, potenziali, mode, is_intense, prob_pct,
                          ffg_result=None, hw_result=None,
                          rain_evo_txt="", wind_evo_txt=""):
    """
    Sezione "Fenomeni": SOLO hazard concreti con innesco confermato nei dati
    (reali). Niente più:
      - frase di "Modalità convettiva" (ha già la sua riga dedicata 🌪 altrove
        nel bollettino, qui era solo un doppione discorsivo);
      - righe di evoluzione vento/pioggia (ridondanti con la sezione
        "Evoluzione oraria", che mostra già gli stessi dati in tabella);
      - sezione "Potenziali" (hazard senza innesco confermato: energia
        presente ma non un evento atteso — tenerli qui creava l'impressione
        di un elenco di rischi concreti quando in realtà erano solo teorici).

    ffg_result e hw_result (rischio alluvione lampo, ondata di calore) restano:
    sono fenomeni con dati di innesco/soglia già superati, non energia teorica.
    """
    parts = []

    possibili = list(reali)
    if ffg_result:
        possibili.append(f"FFG {ffg_result['score']:.2f}/1.0 – {ffg_result['desc']}")
    if hw_result and hw_result.get("severity") not in ("nessuna", None, ""):
        possibili.append(f"Calore: {hw_result.get('desc', '')}")

    if possibili:
        items = "".join(f"<li>{h}</li>" for h in possibili)
        parts.append(f"<div><b>Possibili</b><ul>{items}</ul></div>")
    else:
        parts.append("<p>Nessun fenomeno severo rilevato</p>")

    return "\n".join(parts)

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
    precip_peak_rate = float(obs.get("precip_rate_mm_h", 0) or 0)
    precip_peak_h = obs.get("precip_peak_h")
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
    if t_max >= thresholds.ARPAL_HEAT_ROSSO:
        lines.append(f"{giorno_label} sarà una giornata di caldo estremo: massime fino a {t_max:.0f}°C.")
    elif t_max >= thresholds.ARPAL_HEAT_ARANCIONE:
        lines.append(f"{giorno_label} si presenta molto caldo: massime fino a {t_max:.0f}°C, minime di {t_min:.0f}°C.")
    elif t_max >= thresholds.ARPAL_HEAT_GIALLO:
        lines.append(f"{giorno_label} sarà caldo: massime attorno a {t_max:.0f}°C, minime di {t_min:.0f}°C.")
    else:
        lines.append(f"{giorno_label} temperature gradevoli: massime sui {t_max:.0f}°C, minime di {t_min:.0f}°C.")

    hi_val = obs.get("heat_index", params.get("heat_index"))
    if hi_val is None:
        hi_val = t_max
    if hi_val >= thresholds.HEAT_INDEX_EXTREME:
        lines.append(f"Afa molto intensa (temperatura percepita {hi_val:.0f}°C): disagio fisico marcato per l'intera giornata.")
    elif hi_val >= thresholds.HEAT_INDEX_DANGER:
        lines.append(f"Afa intensa (temperatura percepita {hi_val:.0f}°C): disagio fisico significativo nelle ore centrali.")
    elif rh >= 70 and t_max >= 28:
        lines.append("L'umidità elevata accentuerà un disagio fisico moderato (afa).")
    elif rh <= 35:
        lines.append(f"Aria secca (umidità relativa intorno al {rh:.0f}%): scarsa nuvolosità, buona visibilità e nessun disagio da afa.")

    cl_v = obs.get("cloud_low_pct"); cm_v = obs.get("cloud_mid_pct"); ch_v = obs.get("cloud_high_pct")
    if cl_v is not None or cm_v is not None or ch_v is not None:
        lines.append(
            f"Nuvolosità: strati bassi {_fmt(cl_v,'.0f','%')}, "
            f"medi {_fmt(cm_v,'.0f','%')}, alti {_fmt(ch_v,'.0f','%')}."
        )

    # ── Precipitazioni e Rischio Convettivo Nascosto ──────────────────────
    scp = float(params.get("SCP", 0) or 0)
    stp = float(params.get("STP", 0) or 0)
    cin = abs(float(params.get("CIN", 0) or 0))
    lcl = float(params.get("LCL", 1500) or 1500)
    precip_now = float(obs.get("precip_rate_mm_h", 0) or 0)

    is_capped = cin >= abs(thresholds.CIN_STRONG) or lcl >= thresholds.LCL_HIGH or rh <= 35
    shear_06 = float(params.get("shear_0_6", 0) or 0)
    shear_organizzato = shear_06 >= thresholds.SHEAR_06_ORGANIZED

    wmo_con_pioggia = wmo_dom in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
    ha_innesco = precip_now > 1.0 or wmo_con_pioggia
    pioggia_violenta = precip_now >= thresholds.ARPAL_RAIN_1H_ROSSO
    pioggia_intensa  = precip_now >= thresholds.ARPAL_RAIN_1H_ARANCIONE

    if pioggia_violenta:
        lines.append(
            f"PIOGGIA VIOLENTA: è previsto un picco di intensità molto elevata, fino a "
            f"{precip_now:.0f} mm/h (soglia ARPAL Rossa: {thresholds.ARPAL_RAIN_1H_ROSSO:.0f} mm/h). "
            "Rischio concreto di allagamenti lampo nella finestra oraria interessata, "
            "indipendentemente dal fatto che il resto della giornata resti più tranquillo."
        )
    elif pioggia_intensa:
        lines.append(
            f"PIOGGIA INTENSA: è prevista una fase di pioggia forte, con punte fino a "
            f"{precip_now:.0f} mm/h (soglia ARPAL Arancione: {thresholds.ARPAL_RAIN_1H_ARANCIONE:.0f} mm/h). "
            "Possibili criticità localizzate (allagamenti, disagi alla viabilità) nella "
            "finestra oraria interessata."
        )
    elif (stp >= thresholds.STP_MODERATE or scp >= thresholds.SCP_HIGH) and not is_capped and shear_organizzato and ha_innesco:
        lines.append(
            "ALLERTA CONVETTIVA: l'atmosfera è molto instabile e lo shear del vento è "
            "sufficiente a organizzare temporali forti, con possibili grandinate di grosse "
            "dimensioni e raffiche violente."
        )
    elif (stp >= thresholds.STP_MODERATE or scp >= thresholds.SCP_HIGH) and not is_capped and shear_organizzato and not ha_innesco:
        from logic import hazard_probability
        prob = hazard_probability(params)
        if prob >= 30:
            lines.append(
                f"L'ambiente è dinamicamente favorevole a temporali organizzati (energia e "
                f"shear elevati). Nessun innesco confermato nei dati orari, ma il segnale "
                f"combinato non è trascurabile (~{prob}%): da monitorare nel corso della "
                f"giornata."
            )
        elif prob >= 15:
            lines.append(
                f"L'ambiente è dinamicamente favorevole a temporali organizzati (energia e "
                f"shear elevati), ma senza un innesco previsto nei dati orari — rischio basso "
                f"ma non nullo (~{prob}%), non un evento atteso con certezza per la giornata."
            )
        else:
            lines.append(
                "L'ambiente è dinamicamente favorevole a temporali organizzati (energia e "
                "shear elevati), ma senza un innesco previsto nei dati orari il rischio "
                "pratico resta contenuto per la giornata."
            )
    elif (scp >= thresholds.SCP_MODERATE and shear_organizzato and ha_innesco) and not is_capped:
        lines.append(
            "ATTENZIONE: energia disponibile e organizzazione del vento favoriscono lo "
            "sviluppo di temporali anche intensi nelle ore centrali/pomeridiane."
        )
    elif cape >= thresholds.SBCAPE_STRONG and not shear_organizzato and not ha_innesco:
        lines.append(
            "L'atmosfera dispone di molta energia convettiva, ma la debole organizzazione del vento "
            "limita lo sviluppo di temporali strutturati. Nelle ore più calde resta possibile qualche "
            "cella isolata sui rilievi o nell'entroterra."
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
        if precip_peak_rate >= thresholds.ARPAL_RAIN_1H_ROSSO:
            lines.append(
                f"Pioggia fortissima attesa in una fase della giornata"
                f"{f' (verso le {precip_peak_h})' if precip_peak_h else ''}, con punte fino a "
                f"{precip_peak_rate:.0f} mm/h (accumulo totale ~{r_tot:.0f} mm): rischio concreto "
                "di allagamenti lampo nella finestra interessata, nonostante il resto della "
                "giornata resti perlopiù asciutto."
            )
        elif precip_peak_rate >= thresholds.ARPAL_RAIN_1H_ARANCIONE:
            lines.append(
                f"Prevista una fase di pioggia intensa"
                f"{f' (verso le {precip_peak_h})' if precip_peak_h else ''}, con punte fino a "
                f"{precip_peak_rate:.0f} mm/h (accumulo totale ~{r_tot:.0f} mm): possibili "
                "criticità localizzate, pur restando il resto della giornata asciutto."
            )
        elif precip_peak_rate >= thresholds.ARPAL_RAIN_1H_GIALLO:
            lines.append(
                f"Precipitazioni concentrate in una finestra della giornata, con punte moderate "
                f"fino a {precip_peak_rate:.0f} mm/h (accumulo totale ~{r_tot:.0f} mm)."
            )
        else:
            lines.append(
                f"Precipitazioni deboli o intermittenti con accumulo di circa {r_tot:.0f} mm. "
                "Nessuna criticità prevista."
            )
    else:
        lines.append("Nessuna precipitazione significativa prevista.")

    # ── Vento ─────────────────────────────────────────────────────────────
    if ha_innesco:
        dcape_val = float(params.get("DCAPE", 0) or 0)
        if dcape_val >= thresholds.DCAPE_HIGH:
            from thermo import dcape_gust_kmh as _dcape_gust_kmh
            v_est = _dcape_gust_kmh(dcape_val)
            lines.append(
                f"⚠️ Possibili raffiche da downburst fino a {v_est:.0f} km/h in caso di "
                "temporale: attenzione a oggetti non fissati ed elementi instabili."
            )
        elif dcape_val >= thresholds.DCAPE_MODERATE:
            from thermo import dcape_gust_kmh as _dcape_gust_kmh
            v_est = _dcape_gust_kmh(dcape_val)
            lines.append(
                f"⚠️ In caso di temporale non è escluso qualche raffica discendente "
                f"(downburst), stimata fino a {v_est:.0f} km/h."
            )

        lr03_val = float(params.get("lr_0_3km", 0) or 0)
        if cape >= thresholds.SBCAPE_STRONG and shear_organizzato:
            dim = (
                "di grandi dimensioni (>2 cm)"
                if lr03_val >= 8.0 and cape >= thresholds.SBCAPE_EXTREME
                else "di 1-2 cm"
            )
            lines.append(f"⚠️ Non è esclusa grandine {dim} nelle celle più forti.")

    # ── Vento ─────────────────────────────────────────────────────────────
    if g_max >= thresholds.ARPAL_WIND_COAST_ROSSO:
        lines.append(
            f"VENTO TEMPESTOSO: raffiche di {nome_v} fino a {g_max:.0f} km/h. "
            "Possibili danni a strutture, alberi e reti di distribuzione."
        )
    elif g_max >= thresholds.ARPAL_WIND_COAST_ARANCIONE:
        lines.append(f"Vento forte di {nome_v} con raffiche fino a {g_max:.0f} km/h.")
    elif g_max >= thresholds.ARPAL_WIND_COAST_GIALLO:
        lines.append(f"Vento moderato da {nome_v} con raffiche fino a {g_max:.0f} km/h.")
    else:
        lines.append(f"Vento debole da {nome_v}, media {w_max:.0f} km/h, raffiche fino a {g_max:.0f} km/h.")

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
        lines.append("\n▌ LIVELLI ALLERTA ARPAL:")
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
    hazard_probability_pct: int = 0,
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
    rain_evolution_text: Optional[str] = None,
    wind_evolution_text: Optional[str] = None,
    temp_anomaly_result: Optional[Dict] = None,
) -> str:
    from logic import livello_attenzione
    livello, emoji = livello_attenzione(maltempo_score_val)

    prompt = f"""
Sei MeteoBot, un sistema di Intelligenza Artificiale meteorologica avanzata per il Levante Ligure.
Il tuo compito è scrivere un'analisi narrativa professionale ed ELEGANTE basata sui dati forniti.

GIORNO: {giorno_label}
LIVELLO ATTENZIONE: {emoji} {livello} (Score: {maltempo_score_val}/5)
PROBABILITÀ FENOMENI CONVETTIVI INTENSI: {hazard_probability_pct}% (usa ESATTAMENTE questo
numero per calibrare il linguaggio secondo le istruzioni sotto — non arrotondare il
messaggio verso "improbabile" se questo valore è 20% o più)

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
            if w["duration_h"] <= 3:
                ev_lines.append(
                    f"  - {w['start']}-{w['end']} ({w['duration_h']}h) — SOLO PICCO: "
                    f"CAPE {w.get('peak_cape_window', w['cape_avg']):.0f} J/kg "
                    f"alle {w.get('peak_hour', w['start'])} "
                    f"(finestra breve — NON descriverla come un periodo esteso)"
                )
            else:
                punti = ", ".join(f"{t}={v:.0f}" for t, v in w.get("vals", []))
                ev_lines.append(
                    f"  - {w['start']}-{w['end']} ({w['duration_h']}h, {w['trend']}): {punti} J/kg"
                )
        prompt += (
            "\nEVOLUZIONE INSTABILITÀ (dati calcolati con concordanza multi-parametro "
            "CAPE+CIN+LI+shear+SRH, usa questi orari esatti senza approssimare):\n"
            + "\n".join(ev_lines)
            + f"\nPicco assoluto: {evolution_result.get('peak_cape', 0):.0f} J/kg "
              f"alle {evolution_result.get('peak_time', 'n.d.')}\n"
            "ISTRUZIONE: cita SEMPRE durata e orari quando descrivi l'instabilità.\n"
        )

    if rain_evolution_text:
        prompt += f"\nEVOLUZIONE PIOGGIA SIGNIFICATIVA (soglia ARPAL 10 mm/h): {rain_evolution_text}\n"
    if wind_evolution_text:
        prompt += f"\nEVOLUZIONE VENTO SOSTENUTO (soglia ARPAL costiera 40 km/h): {wind_evolution_text}\n"
    if temp_anomaly_result:
        prompt += (
            f"\nANOMALIA TERMICA IN QUOTA RISPETTO AL MESE: {temp_anomaly_result['desc']}. "
            "ISTRUZIONE: se la citi, specifica che è un'anomalia rispetto alla norma "
            "climatologica del periodo, non un valore assoluto generico.\n"
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
   Se l'innesco manca, NON descrivere i fenomeni come attesi con certezza, ma calibra la
   sicurezza del linguaggio sulla percentuale di probabilità fornita più sotto — non usare
   MAI la formula fissa "rischio teorico e improbabile" a prescindere dal numero:
     - probabilità < 15%: puoi dire che il rischio è trascurabile/improbabile.
     - probabilità 15-30%: di' che il rischio è basso ma non nullo, non liquidarlo come
       "improbabile" — usa "non un evento atteso con certezza" invece di "improbabile".
     - probabilità >= 30%: di' esplicitamente che il segnale non è trascurabile e che la
       situazione merita attenzione/monitoraggio, pur restando non confermata da un
       innesco nei dati orari. Non usare mai "improbabile" o "nullo" in questo caso.
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

def render_hourly_meteo_table_html(hourly: List[Dict], max_rows: int = 48) -> str:
    if not hourly:
        return "<p>Dati orari non disponibili.</p>"
    html = '<table style="border-collapse:collapse;width:100%;font-size:13px">'
    html += ('<tr style="background:#e0e0e0">'
             '<th style="padding:4px;border:1px solid #999">Ora</th>'
             '<th style="padding:4px;border:1px solid #999">Temp</th>'
             '<th style="padding:4px;border:1px solid #999">Umidità</th>'
             '<th style="padding:4px;border:1px solid #999">Vento</th>'
             '<th style="padding:4px;border:1px solid #999">Direzione</th>'
             '<th style="padding:4px;border:1px solid #999">Nuv Bassa</th>'
             '<th style="padding:4px;border:1px solid #999">Nuv Media</th>'
             '<th style="padding:4px;border:1px solid #999">Nuv Alta</th>'
             '<th style="padding:4px;border:1px solid #999">Pioggia</th></tr>')
    for h in hourly[:max_rows]:
        t = h.get("time", "")
        temp = _fmt(h.get("T"), ".1f", "°C")
        rh = _fmt(h.get("RH"), ".0f", "%")
        wind = _fmt(h.get("wind_gust", h.get("wind", 0)), ".0f", " km/h")
        prec = _fmt(h.get("precip", 0), ".1f", " mm")
        nlow = _ftm(h.get("cloud_low"), ".0f", "%")
        nmed = _ftm(h.get("cloud_mid"), ".0f", "%")
        nhig = _ftm(h.get("cloud_high"), ".0f", "%")
        dir_txt = _wind_dir_16(h.get("wind_dir"))
        html += (f'<tr><td style="padding:4px;border:1px solid #ccc">{t}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{temp}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{rh}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{wind}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{dir_txt}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{nlow}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{nmed}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{nhig}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{prec}</td></tr>')
    html += '</table>'
    return html


def render_hourly_tech_table_html(hourly: List[Dict], max_rows: int = 48) -> str:
    if not hourly:
        return "<p>Dati tecnici orari non disponibili.</p>"
    html = '<table style="border-collapse:collapse;width:100%;font-size:13px">'
    html += ('<tr style="background:#e0e0e0">'
             '<th style="padding:4px;border:1px solid #999">Ora</th>'
             '<th style="padding:4px;border:1px solid #999">CAPE</th>'
             '<th style="padding:4px;border:1px solid #999">CIN</th>'
             '<th style="padding:4px;border:1px solid #999">LI</th>'
             '<th style="padding:4px;border:1px solid #999">Shear06</th>'
             '<th style="padding:4px;border:1px solid #999">PWAT</th>'
             '<th style="padding:4px;border:1px solid #999">SCP</th>'
             '<th style="padding:4px;border:1px solid #999">K-Index</th>'
             '<th style="padding:4px;border:1px solid #999">Totals-Totals</th>'
             '<th style="padding:4px;border:1px solid #999">DCAPE</th>'
             '<th style="padding:4px;border:1px solid #999">SRH03</th></tr>')
    for h in hourly[:max_rows]:
        t = h.get("time", "")
        cape = _fmt(h.get("CAPE", 0), ".0f")
        cin  = _fmt(h.get("CIN", 0), ".0f")
        li   = _fmt(h.get("LI"), ".1f")
        shear = _fmt(h.get("shear"), ".0f", " kt")
        srh  = _fmt(h.get("SRH"), ".0f")
        pwat = _fmt(h.get("PWAT"), ".0f", " mm")
        scp = _ftm(h.get("SCP"), ".0f")
        k_index = _ftm(h.get("KI"), ".0f")
        totals_totals = _ftm(h.get("TT"), ".0f")
        dcape = _ftm(h.get("DCAPE"), ".0f")
        html += (f'<tr><td style="padding:4px;border:1px solid #ccc">{t}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{cape}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{cin}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{li}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{shear}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{pwat}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{scp}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{k_index}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{totals_totals}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{dcape}</td>'
                 f'<td style="padding:4px;border:1px solid #ccc">{srh}</td></tr>')
    html += '</table>'
    return html


def render_day_html_block(day_label, date_str, alert_emoji, model_label,
                           risks_html, sintesi_text, tech_table_html,
                           hourly_meteo_html, hourly_tech_html,
                           fenomeni_html, narrativa) -> str:
    return f"""
<section style="margin-bottom:32px;border-bottom:2px solid #ccc;padding-bottom:16px">
  <h2>{alert_emoji} {day_label.upper()} — {date_str}</h2>
  <p>Modello: {model_label}</p>
  {risks_html}
  <div style="white-space:pre-line;background:#f7f7f7;padding:8px;border-radius:6px">{sintesi_text}</div>
  <h3>Dati tecnici — I DATI PRESENTI SONO STATI PRESI IN CONCOMITANZA COL PICCO CAPE</h3>
  {tech_table_html}
  <h3>Evoluzione oraria</h3>
  <h4>Meteo (temperatura, umidità, vento, pioggia)</h4>
  {hourly_meteo_html}
  <h4>Dati tecnici</h4>
  {hourly_tech_html}
  <h3>Fenomeni</h3>
  {fenomeni_html}
  <h3>Analisi AI</h3>
  <p>{narrativa}</p>
</section>
"""


def render_bulletin_html(day_blocks: List[str], header_info: str, title: str = "Bollettino MeteoBot") -> str:
    blocks = "\n".join(day_blocks)
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; margin:12px; color:#222; }}
table {{ margin-bottom:8px; }}
h2 {{ margin-bottom:4px; }}
</style></head>
<body>
<p>{header_info}</p>
{blocks}
</body></html>"""
