# templates.py
"""
Generatori bollettino meteorologico MeteoBot \u2013 La Spezia / Levante Ligure.

Sezione 1: Previsione semplice in italiano (pubblica, comprensibile)
Sezione 2: Analisi tecnica dettagliata (parametri fisici, meccanismi)
Sezione 3: Tabella oraria oggettiva (CSV-like per Gemini)
Sezione 4: Prompt rigoroso per Gemini AI con vincoli anti-allucinazione
"""

from typing import Dict, List, Optional
from config import ALERT_EMOJI, thresholds

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Sezione 1 – Previsione semplice
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def render_section1_simple(
    obs: Dict,
    params: Dict,
    score: int,
    alert_level: str = "verde",
) -> str:
    parts: List[str] = []
    emoji = ALERT_EMOJI.get(alert_level, "\u26aa")

    # \u2014 Allerta
    alert_labels = {
        "verde":    "Nessuna allerta meteo in vigore",
        "gialla":   "\u26a0\ufe0f Allerta ARPAL Gialla in vigore",
        "arancione":"\ud83d\udea8 Allerta ARPAL Arancione in vigore",
        "rossa":    "\ud83d\udea8\ud83d\udea8 ALLERTA ARPAL ROSSA IN VIGORE",
    }
    parts.append(f"{emoji} {alert_labels.get(alert_level, '')}")

    # \u2014 Cielo
    cloud_cover = obs.get("cloud_cover_pct", 0) or 0
    if cloud_cover < 10:
        parts.append("Oggi si attende cielo interamente soleggiato")
    elif cloud_cover < 30:
        parts.append("Oggi si attende cielo in prevalenza soleggiato con qualche velatura")
    elif cloud_cover < 60:
        parts.append("Oggi si attende cielo da poco a parzialmente nuvoloso")
    elif cloud_cover < 85:
        parts.append("Oggi si attende cielo molto nuvoloso")
    else:
        parts.append("Oggi si attende cielo coperto")

    if obs.get("cloud_high_pct", 0) >= 60:
        parts.append("con velature alte in progressivo aumento dal pomeriggio")

    if obs.get("cloud_low_pct", 0) >= 50:
        parts.append("con nuvole basse e nebbie su vallate e coste nelle prime ore")

    # \u2014 Precipitazioni
    precip = obs.get("precip_rate_mm_h", 0) or 0
    if precip > 0:
        start = obs.get("precip_start", "19:00")
        end   = obs.get("precip_end",   "21:00")
        peak  = obs.get("precip_peak_mm", precip)
        if precip >= thresholds.ARPAL_RAIN_1H_ROSSO:
            parts.append(
                f"PIOGGE MOLTO INTENSE dalle {start} alle {end}; "
                f"accumuli fino a {peak:.1f} mm/h – rischio allagamenti critici"
            )
        elif precip >= thresholds.ARPAL_RAIN_1H_ARANCIONE:
            parts.append(
                f"piogge intense dalle {start} alle {end} "
                f"con picco di {peak:.1f} mm/h"
            )
        elif precip >= thresholds.ARPAL_RAIN_1H_GIALLO:
            parts.append(
                f"precipitazioni moderate dalle {start} alle {end} "
                f"(fino a {peak:.1f} mm/h)"
            )
        else:
            parts.append(f"deboli precipitazioni attese tra le {start} e le {end}")

    # \u2014 Temporali
    if score >= thresholds.SEVERE_SCORE_EMERGENCY:
        parts.append(
            "RISCHIO ELEVATO di temporali violenti con possibili fenomeni severi "
            "(grandine di grandi dimensioni, raffiche forti, trombe d'aria)"
        )
    elif score >= thresholds.SEVERE_SCORE_ALERT:
        parts.append(
            "Rischio di temporali forti tra sera e notte, "
            "con possibili grandine e raffiche intense"
        )
    elif score >= thresholds.SEVERE_SCORE_WARNING:
        parts.append("Rischio di temporali di moderata intensità nel corso della giornata")

    # \u2014 Fattore orografico
    oro = params.get("orographic_factor", 0)
    if oro >= 0.6:
        parts.append(
            "Il forzante orografico dell'Appennino Ligure è significativo: "
            "gli accumuli potrebbero essere sensibilmente maggiori sulle zone collinari"
        )

    # \u2014 Vento
    wind = obs.get("wind_gust_kmh", 0) or 0
    if wind >= thresholds.ARPAL_WIND_COAST_ROSSO:
        parts.append(f"VENTO TEMPESTOSO con raffiche fino a {wind:.0f} km/h")
    elif wind >= thresholds.ARPAL_WIND_COAST_ARANCIONE:
        parts.append(f"vento forte con raffiche fino a {wind:.0f} km/h")
    elif wind >= thresholds.ARPAL_WIND_COAST_GIALLO:
        parts.append(f"vento moderato, raffiche fino a {wind:.0f} km/h")

    # \u2014 Temperatura / calore
    hi = obs.get("heat_index") or params.get("heat_index")
    if hi and hi >= thresholds.HEAT_INDEX_DANGER:
        parts.append(f"sensazione di caldo estremo: indice calore {hi:.0f}°C")
    elif hi and hi >= thresholds.HEAT_INDEX_WARNING:
        parts.append(f"disagio da caldo percepito: indice {hi:.0f}°C")

    # \u2014 Mare
    wave = params.get("wave_height_m", 0) or 0
    if wave >= thresholds.WAVE_HEIGHT_ROSSO:
        parts.append(f"MARE TEMPESTOSO con onde fino a {wave:.1f} m")
    elif wave >= thresholds.WAVE_HEIGHT_ARANCIONE:
        parts.append(f"mare agitato, onde fino a {wave:.1f} m")

    return ". ".join(parts) + "."


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Sezione 2 – Analisi tecnica dettagliata
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _fmt(val, fmt=".1f", unit="") -> str:
    """Formatta un valore opzionale."""
    if val is None:
        return "n.d."
    try:
        return f"{val:{fmt}}{unit}"
    except (TypeError, ValueError):
        return str(val)


def render_section2_detailed(
    obs: Dict,
    params: Dict,
    mode: str,
    hazards: List[str],
    alert_detail: Optional[Dict[str, str]] = None,
) -> str:
    lines: List[str] = []

    lines.append("═══ ANALISI TECNICA METEOROLOGICA ═══")

    # \u2014 Allerta ARPAL per rischio
    if alert_detail:
        lines.append("\n▌ LIVELLI ALLERTA ARPAL (Zona A/B – Levante Ligure):")
        for risk, lvl in alert_detail.items():
            emoji = ALERT_EMOJI.get(lvl, "⚪")
            lines.append(f"   {emoji} {risk.capitalize()}: {lvl.upper()}")

    # \u2014 Indici di instabilità
    lines.append("\n▌ INDICI DI INSTABILITÀ:")
    sbcape = params.get("SBCAPE", params.get("CAPE", 0))
    mucape = params.get("MUCAPE", sbcape)
    mlcape = params.get("MLCAPE", sbcape)
    lines.append(f"   SBCAPE : {_fmt(sbcape, '.0f', ' J/kg')} | "
                 f"MUCAPE : {_fmt(mucape, '.0f', ' J/kg')} | "
                 f"MLCAPE : {_fmt(mlcape, '.0f', ' J/kg')}")
    sbcin = params.get("SBCIN", params.get("CIN", 0))
    lines.append(f"   SBCIN  : {_fmt(sbcin, '.0f', ' J/kg')}  "
                 f"(inibizione {'forte' if abs(sbcin) >= 200 else 'moderata' if abs(sbcin) >= 100 else 'debole'})")
    lines.append(f"   LI     : {_fmt(params.get('LI'), '.1f', ' (neg=instabile)')}")
    lines.append(f"   θe max : {_fmt(params.get('theta_e_max'), '.1f', ' K')}")

    # \u2014 Indici classici
    lines.append("\n▌ INDICI CLASSICI:")
    lines.append(f"   K-Index : {_fmt(params.get('KI'), '.1f')}  "
                 f"(>25 temp. possibili, >35 probabili, >40 certi)")
    lines.append(f"   TT      : {_fmt(params.get('TT'), '.1f')}  "
                 f"(>44 temp. mod., >50 severi, >55 tornado)")
    lines.append(f"   SWEAT   : {_fmt(params.get('SWEAT'), '.0f')}  "
                 f"(>150 temp., >300 severi)")

    # \u2014 Shear e rotazione
    lines.append("\n▌ SHEAR E ROTAZIONE:")
    lines.append(f"   Shear 0–1 km : {_fmt(params.get('shear_0_1'), '.1f', ' kt')}")
    lines.append(f"   Shear 0–3 km : {_fmt(params.get('shear_0_3'), '.1f', ' kt')}")
    lines.append(f"   Shear 0–6 km : {_fmt(params.get('shear_0_6'), '.1f', ' kt')}  "
                 f"(soglia supercella ≥{thresholds.SHEAR_06_SUPERCELL:.0f} kt)")
    lines.append(f"   SRH 0–1 km   : {_fmt(params.get('srh_0_1'), '.1f', ' m²/s²')}")
    lines.append(f"   SRH 0–3 km   : {_fmt(params.get('srh_0_3'), '.1f', ' m²/s²')}  "
                 f"(soglia alta ≥{thresholds.SRH_03_HIGH:.0f} m²/s²)")

    # \u2014 Indici compositi
    lines.append("\n▌ INDICI COMPOSITI (SPC/WMO):")
    lines.append(f"   EHI : {_fmt(params.get('EHI'), '.2f')}  (>1.0 significativo, >2.5 alto)")
    lines.append(f"   SCP : {_fmt(params.get('SCP'), '.2f')}  (>1.0 supercella, >4.0 elevato)")
    lines.append(f"   STP : {_fmt(params.get('STP'), '.2f')}  (>0.5 tornado significativo)")

    # \u2014 Umidità e PWAT
    lines.append("\n▌ UMIDITÀ ATMOSFERICA:")
    lines.append(f"   PWAT : {_fmt(params.get('PWAT'), '.1f', ' mm')}  "
                 f"(umido ≥{thresholds.PWAT_HUMID:.0f} mm)")
    lines.append(f"   LCL  : {_fmt(params.get('LCL'), '.0f', ' m')}  "
                 f"(basso <{thresholds.LCL_LOW:.0f} m → alta efficienza precipitativa)")

    # \u2014 Lapse rates
    lr03  = params.get("lr_0_3km")
    lr_mid = params.get("lr_700_500")
    if lr03 is not None or lr_mid is not None:
        lines.append("\n▌ GRADIENTI TERMICI:")
        if lr03 is not None:
            instab = "MOLTO INSTABILE" if lr03 >= 8 else ("instabile" if lr03 >= 6.5 else "stabile")
            lines.append(f"   LR 0–3 km    : {lr03:.1f} K/km  ({instab})")
        if lr_mid is not None:
            lines.append(f"   LR 700–500 hPa: {lr_mid:.1f} K/km")

    # \u2014 Fattori orografici e locali
    lines.append("\n▌ FATTORI LOCALI – LEVANTE LIGURE:")
    oro = params.get("orographic_factor", 0)
    lines.append(
        f"   Amplificazione orografica Appennino: {oro:.0%}  "
        f"({'elevata' if oro >= 0.6 else 'moderata' if oro >= 0.3 else 'bassa'})"
    )
    sb = params.get("sea_breeze_convergence", 0)
    lines.append(
        f"   Convergenza brezza marina           : {sb:.0%}  "
        f"({'attiva' if sb >= 0.5 else 'assente o debole'})"
    )

    # \u2014 Modalità convettiva
    lines.append(f"\n▌ MODALITÀ CONVETTIVA ATTESA:\n   {mode}")

    # \u2014 Meccanismi di innesco
    mech = []
    if obs.get("front_present"):
        mech.append("forzante frontale")
    if obs.get("low_level_convergence"):
        mech.append("convergenza ai bassi livelli")
    if obs.get("upper_level_tropospheric_vorticity"):
        mech.append("vorticità in quota")
    if oro >= 0.5:
        mech.append("forzante orografico Appennino")
    if sb >= 0.4:
        mech.append("convergenza brezza marina/flusso sinottico")
    if mech:
        lines.append(f"   Meccanismi di innesco: {', '.join(mech)}")

    # \u2014 Fenomeni possibili
    lines.append("\n▌ FENOMENI POSSIBILI:")
    if hazards:
        for h in hazards:
            lines.append(f"   ⚠ {h}")
    else:
        lines.append("   Nessun fenomeno severo atteso")

    # \u2014 Riepilogo numerico (per Gemini)
    lines.append(
        f"\n▌ VALORI CHIAVE: "
        f"SBCAPE={_fmt(sbcape,'.0f')} J/kg | "
        f"MUCAPE={_fmt(mucape,'.0f')} J/kg | "
        f"shear06={_fmt(params.get('shear_0_6'),'.1f')} kt | "
        f"SRH03={_fmt(params.get('srh_0_3'),'.0f')} m²/s² | "
        f"CIN={_fmt(sbcin,'.0f')} J/kg | "
        f"PWAT={_fmt(params.get('PWAT'),'.1f')} mm | "
        f"LCL={_fmt(params.get('LCL'),'.0f')} m | "
        f"STP={_fmt(params.get('STP'),'.2f')} | "
        f"SCP={_fmt(params.get('SCP'),'.2f')}"
    )

    return "\n".join(lines)


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Sezione 3 – Tabella oraria oggettiva
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def render_section3_objective_table(hourly_list: List[Dict]) -> str:
    """
    Tabella oraria CSV-like con tutti i parametri rilevanti.
    Colonne: time, T_C, RH_pct, wind_kmh, wind_dir_deg, precip_mm_h,
             precip_cum_mm, CAPE_Jkg, CIN_Jkg, shear_kt, SRH_m2s2,
             PWAT_mm, wmo_code, alert
    """
    header = (
        "time,T_C,RH_pct,wind_kmh,wind_dir_deg,precip_mm_h,"
        "precip_cum_mm,CAPE_Jkg,CIN_Jkg,shear_kt,SRH_m2s2,"
        "PWAT_mm,wmo_code,alert"
    )
    rows = [header]
    for h in hourly_list:
        rows.append(
            f"{h.get('time','?')},"
            f"{h.get('T','')},"
            f"{h.get('RH','')},"
            f"{h.get('wind','')},"
            f"{h.get('wind_dir','')},"
            f"{h.get('precip', 0):.1f},"
            f"{h.get('precip_cum', 0):.1f},"
            f"{h.get('CAPE', 0):.0f},"
            f"{h.get('CIN', 0):.0f},"
            f"{h.get('shear', 0):.1f},"
            f"{h.get('SRH', 0):.0f},"
            f"{h.get('PWAT', 0):.1f},"
            f"{h.get('wmo_code', '')},"
            f"{h.get('alert', '')}"
        )
    return "\n".join(rows)


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Sezione 4 – Prompt Gemini (rigoroso)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def build_gemini_prompt(
    section1: str,
    section2: str,
    score: int,
    params: Dict,
    alert_level: str = "verde",
) -> str:
    """
    Prompt rigoroso per Gemini AI.
    Livello di rischio e lunghezza minima dipendono dallo score e dall'allerta ARPAL.
    """
    risk_labels = {
        "verde":    "TRASCURABILE – situazione ordinaria",
        "gialla":   "BASSO – attenzione consigliata",
        "arancione":"MODERATO-ALTO – prestare attenzione",
        "rossa":    "ELEVATO – situazione di emergenza potenziale",
    }
    risk_text = risk_labels.get(alert_level, "non determinato")

    if score >= thresholds.SEVERE_SCORE_EMERGENCY or alert_level == "rossa":
        min_words, detail_level = 350, "MASSIMO"
    elif score >= thresholds.SEVERE_SCORE_ALERT or alert_level == "arancione":
        min_words, detail_level = 250, "ALTO"
    elif score >= thresholds.SEVERE_SCORE_WARNING or alert_level == "gialla":
        min_words, detail_level = 150, "MODERATO"
    else:
        min_words, detail_level = 50,  "MINIMO"

    stp  = params.get("STP", 0) or 0
    scp  = params.get("SCP", 0) or 0
    oro  = params.get("orographic_factor", 0) or 0

    extra_warnings = []
    if stp >= thresholds.STP_HIGH:
        extra_warnings.append(
            "ATTENZIONE SPECIALE: STP elevato indica possibilità di trombe d'aria. "
            "Includere consigli di comportamento in caso di tromba."
        )
    if scp >= thresholds.SCP_HIGH:
        extra_warnings.append(
            "ATTENZIONE SPECIALE: SCP molto elevato indica alta probabilità di supercelle. "
            "Menzionare possibilità di grandine di grandi dimensioni."
        )
    if oro >= 0.6:
        extra_warnings.append(
            "ATTENZIONE OROGRAFICA: Il forzante dell'Appennino Ligure amplificherà "
            "significativamente gli accumuli sulle zone collinari dello Spezzino. "
            "Specificare le zone a maggior rischio (Lerici, Follo, Calice, Val di Magra)."
        )

    prompt = (
        "═══════════════════════════════════════════════════════════\n"
        "SISTEMA METEOBOT – LA SPEZIA E LEVANTE LIGURE\n"
        "BOLLETTINO METEOROLOGICO OGGETTIVO\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"LIVELLO DI RISCHIO ATTUALE: {risk_text}\n"
        f"PUNTEGGIO CONVETTIVO: {score}/12\n"
        f"LIVELLO DETTAGLIO RICHIESTO: {detail_level} (min. {min_words} parole)\n\n"
        "────────────────────────────────────────────────────────────\n"
        "SEZIONE 1 – PREVISIONE PUBBLICA:\n"
        f"{section1}\n\n"
        "SEZIONE 2 – ANALISI TECNICA:\n"
        f"{section2}\n"
        "────────────────────────────────────────────────────────────\n\n"
        "ISTRUZIONI RIGOROSE PER GEMINI:\n"
        "1. USA ESCLUSIVAMENTE i dati numerici presenti nelle Sezioni 1 e 2.\n"
        "2. NON inventare valori, NON consultare fonti esterne.\n"
        f"3. Scrivi almeno {min_words} parole.\n"
        "4. Struttura il bollettino con:\n"
        "   – Situazione attuale e tendenza\n"
        "   – Meccanismi fisici che determinano i fenomeni\n"
        "   – Orari critici e zone a maggior rischio nello Spezzino\n"
        "   – Fenomeni attesi con probabilità (alta/media/bassa)\n"
        "   – Consigli di autoprotezione calibrati all'allerta\n"
        "   – Indicatori di monitoraggio (radar, accumuli orari, fulmini)\n"
        "   – Incertezza previsionale\n"
        "5. Tono: tecnico ma comprensibile. Output in italiano.\n"
        "6. Se l'allerta è ARANCIONE o ROSSA: includi numero emergenze "
        "(112 / Protezione Civile Liguria).\n"
    )

    if extra_warnings:
        prompt += "\nAVVERTENZE SPECIALI:\n"
        for w in extra_warnings:
            prompt += f"⚠ {w}\n"

    return prompt



    # Velature alte
    if obs.get("cloud_high_pct", 0) >= 60:
        parts.append("alle 18 si svilupperanno velature estese")

    # Nuvole basse
    if obs.get("cloud_low_pct", 0) >= 50:
        parts.append("alle 19 arriveranno nuvole basse")

    # Precipitazioni
    if obs.get("precip_rate_mm_h", 0) > 0:
        start = obs.get("precip_start", "19:00")
        end = obs.get("precip_end", "21:00")
        peak = obs.get("precip_peak_mm", obs.get("precip_rate_mm_h"))
        parts.append(f"Precipitazione dalle {start} alle {end} con picco alle {end} di {peak:.1f} mm")

    # Rischio temporali
    if score >= 3:
        parts.append("Rischio di temporali forti tra le 21 e le 02 del giorno dopo")

    # Altri elementi
    if obs.get("wind_gust_kmh", 0) > 60:
        parts.append(f"raffiche di vento fino a {obs['wind_gust_kmh']} km/h")
    if obs.get("heat_index", None):
        parts.append(f"afa percepita: indice {obs['heat_index']}")

    return ". ".join(parts) + "."

    lines.append(f"Shear 0–6 km: {params.get('shear_0_6',0):.1f} kt")
    if params.get("srh_0_1", None) is not None:
        lines.append(f"SRH 0–1 km: {params.get('srh_0_1',0):.1f} m^2/s^2")
    if params.get("CIN", None) is not None:
        lines.append(f"CIN: {params.get('CIN',0)} J/kg")
    if params.get("LCL", None) is not None:
        lines.append(f"LCL: {params.get('LCL',0):.0f} m")
    if params.get("PWAT", None) is not None:
        lines.append(f"PWAT: {params.get('PWAT',0):.1f} mm")
    if params.get("LI", None) is not None:
        lines.append(f"Lifted Index: {params.get('LI')}")

    lines.append(f"Modalità convettiva attesa: {mode}")

    # Determinazione meccanismi fisici
    mech = []
    # Forcing sinottico
    if obs.get("front_present", False):
        mech.append("forzante frontale")
    if obs.get("low_level_convergence", False):
        mech.append("convergenza ai bassi livelli")
    if obs.get("upper_level_tropospheric_vorticity", False):
        mech.append("vorticità in quota")
    if mech:
        lines.append("Meccanismi di innesco: " + ", ".join(mech))

    # Fenomeni possibili
    lines.append("Fenomeni possibili: " + (", ".join(hazards) if hazards else "nessuno significativo"))

    # Inserire valori numerici chiave in linea
    numeric = f"Valori chiave: CAPE={params.get('CAPE',0)} J/kg; shear0-6={params.get('shear_0_6',0):.1f} kt; CIN={params.get('CIN',0)} J/kg; PWAT={params.get('PWAT',0):.1f} mm."
    lines.append(numeric)

    return "\n".join(lines)

def render_section3_objective_table(hourly_list: List[Dict]) -> str:
    """
    hourly_list: lista di dict con keys: time,T,RH,wind,precip,CAPE,shear
    Ritorna CSV-like table stringa.
    """
    header = "time,T_C,RH_pct,wind_kmh,precip_mm_h,CAPE_Jkg,shear_kt"
    rows = [header]
    for h in hourly_list:
        rows.append(
            f"{h.get('time')},{h.get('T',None)},{h.get('RH',None)},{h.get('wind',None)},{h.get('precip',0)},{h.get('CAPE',0)},{h.get('shear',0):.1f}"
        )
    return "\n".join(rows)

def build_gemini_prompt(section1: str, section2: str, score: int, params: Dict) -> str:
    """
    Costruisce prompt rigoroso per Gemini. Vincoli:
    - Usa SOLO i testi forniti (section1 e section2).
    - Se rischio significativo (score >= 3) richiede almeno 200 parole per giornata.
    - Se rischio trascurabile scrive breve paragrafo.
    """
    severity = "significativi" if score >= 3 else "trascurabili"
    min_words = 200 if score >= 3 else 30
    prompt = (
        "USARE SOLO I SEGUENTI TESTI. NON CONSULTARE ALTRE FONTI.\n\n"
        "SEZIONE 1 PREVISIONE SEMPLICE:\n"
        f"{section1}\n\n"
        "SEZIONE 2 ANALISI TECNICA:\n"
        f"{section2}\n\n"
        "ISTRUZIONI RIGOROSE:\n"
        f"- Valuta i rischi per la giornata. Se i rischi sono {severity}, scrivi almeno {min_words} parole per giornata.\n"
        "- Indica probabilità, intensità attesa, orari critici, meccanismi fisici che portano ai fenomeni, consigli di autoprotezione, incertezza e indicatori di monitoraggio (radar, fulminazioni, accumuli orari).\n"
        "- Non inventare numeri: riporta solo i valori presenti nelle sezioni 1 e 2.\n"
        "- Mantieni tono severo e preciso. Output in italiano.\n"
    )
    return prompt