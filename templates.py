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

    # — Indici di instabilità
    lines.append("\n▌ INDICI DI INSTABILITÀ:")
    sbcape = params.get("SBCAPE", params.get("CAPE", 0))
    mucape = params.get("MUCAPE", sbcape)
    mlcape = params.get("MLCAPE", sbcape)
    dcape  = params.get("DCAPE", 0) or 0
    lines.append(f"   SBCAPE : {_fmt(sbcape, '.0f', ' J/kg')} | "
                 f"MUCAPE : {_fmt(mucape, '.0f', ' J/kg')} | "
                 f"MLCAPE : {_fmt(mlcape, '.0f', ' J/kg')}")
    sbcin = params.get("SBCIN", params.get("CIN", 0))
    lines.append(f"   SBCIN  : {_fmt(sbcin, '.0f', ' J/kg')}  "
                 f"(inibizione {'forte' if abs(sbcin) >= 200 else 'moderata' if abs(sbcin) >= 100 else 'debole'})")
    lines.append(f"   LI     : {_fmt(params.get('LI'), '.1f', ' (neg=instabile)')}")
    lines.append(f"   θe max : {_fmt(params.get('theta_e_max'), '.1f', ' K')}")
    # DCAPE — energia per raffiche discendenti
    if dcape > 0:
        try:
            from thermo import dcape_gust_kmh as _dg
            v_est = _dg(dcape)
            lines.append(
                f"   DCAPE  : {dcape:.0f} J/kg  "
                f"(raffica downburst stimata ≈{v_est:.0f} km/h)"
            )
        except Exception:
            lines.append(f"   DCAPE  : {dcape:.0f} J/kg")

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
        "time,T_C,RH_pct,wind_kmh,wind_gust_kmh,cloud_pct,wind_dir_deg,precip_mm_h,"
        "precip_cum_mm,CAPE_Jkg,CIN_Jkg,shear_kt,SRH_m2s2,"
        "PWAT_mm,wmo_code,alert"
    )
    rows = [header]
    for h in hourly_list:
        gust_v = h.get('wind_gust', 0) or 0
        cloud_v = h.get('cloud', '')
        rows.append(
            f"{h.get('time','?')},"
            f"{h.get('T','')},"
            f"{h.get('RH','')},"
            f"{h.get('wind','')},"
            f"{gust_v:.0f},"
            f"{cloud_v},"
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


# ─────────────────────────────────────────────────────────────────────────────
# ANALISI SEMPLICE – testo dinamico con molte varianti
# Usata in run_previsioni_new.py per la sezione pubblica per ogni giorno
# ─────────────────────────────────────────────────────────────────────────────

import math as _math

_VENTI_NOMI = [
    (22.5,  "Tramontana"), (67.5,  "Grecale"), (112.5, "Levante"),
    (157.5, "Scirocco"),   (202.5, "Ostro"),   (247.5, "Libeccio"),
    (292.5, "Ponente"),    (337.5, "Maestrale"),(360.0, "Tramontana"),
]

def _nome_vento(deg: float) -> str:
    d = (deg or 0) % 360
    for lim, nome in _VENTI_NOMI:
        if d < lim:
            return nome
    return "Tramontana"

def _wmo_sky(wmo: int) -> str:
    if wmo == 0:             return "sereno e soleggiato"
    if wmo == 1:             return "in prevalenza sereno"
    if wmo == 2:             return "parzialmente nuvoloso"
    if wmo == 3:             return "coperto"
    if wmo in (45, 48):     return "nebbioso"
    if wmo in (51, 53, 55): return "coperto con pioviggine"
    if wmo in (61, 63):     return "coperto con pioggia"
    if wmo == 65:            return "coperto con pioggia intensa"
    if wmo in (71, 73):     return "neve leggera o moderata"
    if wmo == 75:            return "neve abbondante"
    if wmo in (80, 81):     return "rovesci moderati"
    if wmo == 82:            return "rovesci violenti"
    if wmo == 95:            return "temporalesco"
    if wmo == 96:            return "temporali con grandine"
    if wmo == 99:            return "temporali violenti con grandine"
    return "variabile"


def render_analisi_semplice(
    obs: Dict,
    params: Dict,
    hourly: Optional[List[Dict]] = None,
    giorno_label: str = "Oggi",
) -> str:
    """
    Analisi meteorologica semplice con testo dinamico – MOLTE varianti.
    Copre: temperatura (min/max), cielo, precipitazioni, vento,
    umidità/afa, fenomeni severi, note orografiche locali.
    """
    lines: List[str] = []

    temp_c   = obs.get("temp_c")
    rh       = float(obs.get("humidity_pct", 0) or 0)
    gust     = float(obs.get("wind_gust_kmh", 0) or 0)
    wind_spd = float(obs.get("wind_speed_kmh", 0) or 0)
    wind_dir = float(obs.get("wind_dir_deg", 0) or 0)
    precip   = float(obs.get("precip_rate_mm_h", 0) or 0)
    cloud    = float(obs.get("cloud_cover_pct", 0) or 0)
    wmo      = int(obs.get("wmo_code", 0) or 0)
    app_temp = obs.get("heat_index") or obs.get("apparent_temperature")
    vis_m    = float(obs.get("visibility_m", 10000) or 10000)
    snow_lvl = float(obs.get("snow_level_m", 3000) or 3000)
    cape     = float(params.get("SBCAPE", params.get("CAPE", 0)) or 0)
    oro      = float(params.get("orographic_factor", 0) or 0)

    # Estremi giornalieri dal profilo orario
    if hourly:
        ts   = [h.get("T") for h in hourly if h.get("T") is not None]
        ws   = [h.get("wind") or 0 for h in hourly]
        gs   = [h.get("wind_gust") or 0 for h in hourly]
        ps   = [h.get("precip") or 0 for h in hourly]
        wmos = [int(h.get("wmo_code") or 0) for h in hourly]
        t_max   = max(ts)   if ts else temp_c
        t_min   = min(ts)   if ts else temp_c
        w_max   = max(ws)   if ws else wind_spd
        g_max   = max(gs)   if gs else gust
        r_tot   = sum(ps)
        wmo_dom = max(set(wmos), key=wmos.count) if wmos else wmo
    else:
        t_max = t_min = temp_c
        w_max = wind_spd; g_max = gust
        r_tot = precip; wmo_dom = wmo

    nome_v = _nome_vento(wind_dir)
    sky    = _wmo_sky(wmo_dom)

    # Descrizione nuvolosità: evolutiva se i dati orari lo permettono
    def _cloud_evo_str(hl):
        if not hl:
            return None
        def _avg(lo, hi):
            vs = [h.get("cloud") for h in hl
                  if h.get("cloud") is not None and lo <= (h.get("time") or "") < hi]
            return sum(vs) / len(vs) if vs else None
        def _lbl(c):
            if c is None: return None
            if c < 20: return "sereno"
            if c < 40: return "poco nuvoloso"
            if c < 70: return "variabile"
            if c < 85: return "molto nuvoloso"
            return "coperto"
        lm = _lbl(_avg("00:00", "12:00"))
        la = _lbl(_avg("12:00", "18:00"))
        le = _lbl(_avg("18:00", "26:00"))
        if lm == la == le or (lm is None and la is None and le is None):
            return None
        parts = []
        if lm:
            parts.append(f"{lm} al mattino")
        if la and la != lm:
            parts.append(f"{la} nel pomeriggio")
        if le and le != (la if la else lm):
            parts.append(f"{le} in serata")
        return ("Cielo " + ", ".join(parts) + ".") if len(parts) > 1 else None

    sky_evo  = _cloud_evo_str(hourly)
    sky_line = sky_evo if sky_evo else f"Cielo {sky}."

    # ── Frase apertura con cielo e temperatura ────────────────────────────
    if t_max is not None and t_min is not None:
        delta = t_max - t_min
        if t_max >= 38:
            lines.append(
                f"{giorno_label} porta un'ondata di calore eccezionale con temperature "
                f"massime intorno a {t_max:.0f}°C e minime di {t_min:.0f}°C. "
                + sky_line
            )
        elif t_max >= 32:
            lines.append(
                f"{giorno_label} si presenta molto caldo: massime attorno a {t_max:.0f}°C, "
                f"minime di {t_min:.0f}°C. " + sky_line
            )
        elif t_max >= 26:
            lines.append(
                f"Giornata estiva con massime di {t_max:.0f}°C e minime di {t_min:.0f}°C. "
                + sky_line
            )
        elif t_max >= 20:
            lines.append(
                f"Temperature gradevoli con massima di {t_max:.0f}°C e minima di {t_min:.0f}°C. "
                + sky_line
            )
        elif t_max >= 10:
            lines.append(
                f"Giornata fresca con massima di {t_max:.0f}°C e minima di {t_min:.0f}°C. "
                + sky_line
            )
        elif t_max >= 2:
            lines.append(
                f"Giornata fredda con temperature massime di {t_max:.0f}°C. "
                f"Possibile gelata notturna con minime di {t_min:.0f}°C. "
                + sky_line
            )
        else:
            lines.append(
                f"Giornata rigida con temperature sotto zero: massima {t_max:.0f}°C, "
                f"minima {t_min:.0f}°C. " + sky_line
            )
    else:
        lines.append(f"{giorno_label}. " + sky_line)

    # ── Umidità e afa ─────────────────────────────────────────────────────
    if rh >= 90 and t_max is not None and t_max >= 20:
        lines.append(
            "Umidità relativa molto elevata (oltre il 90%): condizioni di afa intensa, "
            "disagio marcato soprattutto nelle ore centrali della giornata."
        )
    elif rh >= 80 and app_temp is not None and app_temp > (t_max or 0) + 3:
        lines.append(
            f"Elevata umidità (circa {rh:.0f}%) con temperatura percepita fino a "
            f"{app_temp:.0f}°C: sensazione afosa nelle ore più calde."
        )
    elif rh >= 75 and t_max is not None and t_max >= 25:
        lines.append(
            f"Umidità moderata ({rh:.0f}%) associata al caldo crea un certo disagio durante "
            "il pomeriggio, in particolare nelle zone costiere e in Valle del Magra."
        )
    elif rh <= 30:
        lines.append(
            f"Aria secca (umidità relativa intorno al {rh:.0f}%): scarsa nuvolosità, "
            "buona visibilità e nessun disagio da afa."
        )

    # ── Precipitazioni e Rischio Convettivo Nascosto ──────────────────────
    
    # CORREZIONE: Integrazione dei parametri convettivi (SCP, STP, CAPE) 
    # per evitare che l'analisi semplice descriva una giornata tranquilla 
    # quando gli indici termodinamici sono esplosivi.
    
    scp = float(params.get("SCP", 0) or 0)
    stp = float(params.get("STP", 0) or 0)
    
    if stp >= thresholds.STP_MODERATE or scp >= thresholds.SCP_HIGH:
        lines.append(
            "ALLERTA CONVETTIVA: Nonostante le condizioni apparentemente stabili, "
            "l'atmosfera è estremamente instabile e favorevole allo sviluppo di supercelle "
            "isolate ma violente. Possibili grandinate di grosse dimensioni e colpi di vento distruttivi."
        )
    elif scp >= thresholds.SCP_MODERATE or (cape >= thresholds.SBCAPE_EXTREME and wmo_dom < 80):
        lines.append(
            "ATTENZIONE: L'elevata energia termodinamica (CAPE estremo) in presenza di "
            "shear del vento crea un ambiente esplosivo. Possibile sviluppo improvviso "
            "di temporali intensi, anche se la nuvolosità generale risulta scarsa."
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
    # ── Dettaglio orario precipitazioni ───────────────────────────────────────
    if hourly and r_tot > 0.5:
        rain_pairs = [(h.get("time", ""), float(h.get("precip") or 0))
                      for h in hourly if (h.get("precip") or 0) > 0.1]
        if rain_pairs:
            pp = max(rain_pairs, key=lambda x: x[1])
            detail_parts = []
            if len(rain_pairs) > 1:
                detail_parts.append(f"Pioggia ore {rain_pairs[0][0]}–{rain_pairs[-1][0]}")
            else:
                detail_parts.append(f"Pioggia alle {rain_pairs[0][0]}")
            detail_parts.append(f"accumulo {r_tot:.1f} mm")
            if pp[1] > 1.0:
                detail_parts.append(f"picco {pp[1]:.1f} mm/h alle {pp[0]}")
            lines.append("; ".join(detail_parts) + ".")
    # ── Vento ─────────────────────────────────────────────────────────────
    if g_max >= 90:
        lines.append(
            f"VENTO TEMPESTOSO: raffiche di {nome_v} fino a {g_max:.0f} km/h. "
            "Possibili danni a strutture, alberi e reti di distribuzione. "
            "Rischio per la navigazione costiera."
        )
    elif g_max >= 60:
        lines.append(
            f"Vento forte di {nome_v} con raffiche fino a {g_max:.0f} km/h: "
            "disagio per i pedoni, attenzione alla navigazione nel Golfo."
        )
    elif g_max >= 40:
        area_desc = (
            "sul promontorio di Portovenere e all'imboccatura del Golfo"
            if nome_v in ("Libeccio", "Maestrale")
            else "sulle zone esposte della costa"
        )
        lines.append(
            f"Vento moderato da {nome_v} con raffiche fino a {g_max:.0f} km/h, "
            f"in particolare {area_desc}."
        )
    elif w_max >= 15:
        lines.append(
            f"Vento da {nome_v} di debole intensità ({w_max:.0f} km/h medi), "
            "nessun disagio significativo."
        )
    else:
        lines.append("Vento debole o assente, condizioni di calma in mare e a terra.")
    # ── Evoluzione raffiche per fascia oraria ─────────────────────────────────────
    if hourly:
        def _mg(lo, hi):
            return max(
                (float(h.get("wind_gust") or 0) for h in hourly
                 if lo <= (h.get("time") or "") < hi),
                default=0.0,
            )
        def _mw(lo, hi):
            ws = [float(h.get("wind") or 0) for h in hourly
                  if lo <= (h.get("time") or "") < hi]
            return sum(ws) / len(ws) if ws else 0.0
        g_mat = _mg("00:00", "12:00")
        g_pom = _mg("12:00", "18:00")
        g_ser = _mg("18:00", "26:00")
        w_mat = _mw("00:00", "12:00")
        w_pom = _mw("12:00", "18:00")
        w_ser = _mw("18:00", "26:00")
        periods = [(n, gv, wv) for n, gv, wv in [
            ("mattino",    g_mat, w_mat),
            ("pomeriggio", g_pom, w_pom),
            ("serata",     g_ser, w_ser),
        ] if gv > 5 or wv > 5]
        if periods:
            g_vals = [gv for _, gv, _ in periods]
            if max(g_vals) - min(g_vals) > 20 or (max(g_vals) > 40 and min(g_vals) < 20):
                evo_parts = [f"{n}: medi {wv:.0f} km/h, raffiche {gv:.0f} km/h"
                             for n, gv, wv in periods if gv > 10 or wv > 5]
                if len(evo_parts) > 1:
                    lines.append("Evoluzione vento: " + "; ".join(evo_parts) + ".")
    # ── Note orografiche ──────────────────────────────────────────────────
    if oro >= 0.6 and (wmo_dom >= 61 or cape >= 800):
        lines.append(
            "Il forzante orografico dell'Appennino Ligure risulta molto attivo: "
            "gli accumuli di precipitazione saranno sensibilmente maggiori "
            "sulle fasce collinari e montane (Follo, Calice, Pignone, Brugnato), "
            "con possibile rischio idrogeologico nelle aste torrentizie."
        )
    elif oro >= 0.35 and wmo_dom >= 61:
        lines.append(
            "Il forzante orografico aumenterà gli accumuli sulle zone interne "
            "rispetto alla costa: monitorare in particolare i versanti esposti a Sud-Ovest."
        )

    return "\n".join(lines)


def build_gemini_prompt_tecnico(
    analisi_tecnica: str,
    params: Dict,
    maltempo_score_val: float,
    giorno_label: str = "oggi",
    is_tendency: bool = False,
    hourly_table: Optional[str] = None,
    spread_data: Optional[Dict] = None,       # spread multi-modello
    ffg_result: Optional[Dict] = None,        # Flash Flood Guidance
    heatwave_result: Optional[Dict] = None,   # analisi ondata di calore
    uwyo_summary: Optional[str] = None,       # estratto radiosondaggio UWYO
) -> str:
    """
    Prompt focalizzato per Gemini: genera SOLO la descrizione narrativa
    dell'ANALISI TECNICA. Script-generated sections (intro, analisi semplice)
    sono già completate; Gemini aggiunge il commento fisico/previsionale.
    """
    from logic import livello_attenzione
    livello, _ = livello_attenzione(maltempo_score_val)

    if is_tendency:
        istr_dettaglio = (
            "Scrivi una tendenza previsionale MOLTO concisa (max 80 parole) se c'è qualcosa "
            "di rilevante da segnalare, altrimenti rispondi SOLO con 'Nessuna criticità prevista.'"
        )
    elif maltempo_score_val >= 4.0:
        istr_dettaglio = (
            "Scrivi un'analisi narrativa (max 200 parole). "
            "Descrivi i meccanismi fisici chiave, gli orari critici e le zone a maggior "
            "rischio nel Levante Ligure. Includi consigli di autoprotezione."
        )
    elif maltempo_score_val >= 2.5:
        istr_dettaglio = (
            "Scrivi un'analisi narrativa concisa (max 150 parole) con i meccanismi fisici "
            "principali, gli orari probabili dei fenomeni e il livello di incertezza."
        )
    elif maltempo_score_val >= 1.0:
        istr_dettaglio = (
            "Scrivi un commento tecnico breve (max 100 parole) sui fenomeni rilevanti. "
            "Se non c'è nulla di importante, rispondi SOLO con 'Nessuna criticità rilevante.'"
        )
    else:
        istr_dettaglio = (
            "Se non ci sono rischi o fenomeni degni di nota, rispondi SOLO con "
            "'Giornata senza criticità meteorologiche.' senza aggiungere altro. "
            "In caso contrario, max 60 parole."
        )

    scp = float(params.get("SCP", 0) or 0)
    stp = float(params.get("STP", 0) or 0)
    oro = float(params.get("orographic_factor", 0) or 0)

    extra = []
    if stp >= 1.0:
        extra.append("ATTENZIONE: STP elevato – menzionare rischio trombe d'aria.")
    if scp >= 4.0:
        extra.append("ATTENZIONE: SCP molto elevato – ambiente favorevole a supercelle.")
    if oro >= 0.6:
        extra.append(
            "ATTENZIONE OROGRAFICA: amplificazione significativa sulle zone collinari "
            "(Val di Magra, Follo, Lerici, Cinque Terre)."
        )

    prompt = (
        f"Sei un meteorologo esperto del territorio spezzino e del Levante Ligure.\n"
        f"Giorno di riferimento: {giorno_label}\n"
        f"Livello di attenzione: {livello} (score {maltempo_score_val}/5)\n\n"
        f"DATI TECNICI DEL MOTORE METEOBOT:\n{analisi_tecnica}\n\n"
        f"REGOLA FONDAMENTALE: la risposta NON deve superare 200 parole in nessun caso. "
        f"Se la situazione è tranquilla, puoi rispondere con una sola frase.\n\n"
        f"ISTRUZIONI:\n"
        f"1. {istr_dettaglio}\n"
        f"2. Basati ESCLUSIVAMENTE sui dati numerici forniti. NON inventare valori.\n"
        f"3. Scrivi in italiano, tono professionale ma comprensibile.\n"
        f"4. NON usare Markdown (no *, no #, no _). Solo testo piano.\n"
        f"5. NON ripetere i dati già elencati sopra: scrivi solo la NARRATIVA.\n"
        f"6. Sii conciso: ogni parola deve aggiungere informazione utile.\n"
    )
    if extra:
        prompt += "AVVERTENZE SPECIALI:\n" + "\n".join(f"⚠ {e}" for e in extra) + "\n"

    # ── Radiosondaggio UWYO (solo estratto derivato, NON il profilo raw) ─────
    if uwyo_summary:
        prompt += (
            f"\nRADIOSONDAGGIO OSSERVATO (UWYO – Milano Linate):\n{uwyo_summary}\n"
            "Usa questi valori per calibrare l'analisi; hanno precedenza sul modello "
            "quando concordanti.\n"
        )

    # ── Spread multi-modello (solo variabili con disaccordo significativo) ────
    if spread_data:
        spread_lines = []
        labels = {
            "CAPE_peak":  "CAPE picco", "precip_sum": "Pioggia totale",
            "gust_max":   "Raffica max", "T_max":     "Tmax",
        }
        for key, info in spread_data.items():
            lbl   = labels.get(key, key)
            a_val = info.get("AROME", "n.d.")
            i_val = info.get("ICON", "n.d.")
            diff  = info.get("diff", 0)
            unit  = info.get("unit", "")
            high  = info.get("high", False)
            pfx   = "⚠ ALTA INCERTEZZA" if high else "Disaccordo"
            spread_lines.append(
                f"  {pfx} – {lbl}: AROME={a_val}{unit} vs ICON-EU={i_val}{unit} "
                f"(diff {diff}{unit})"
            )
        if spread_lines:
            prompt += (
                "\nINCERTEZZA MODELLI (disaccordo significativo – menzionalo!):\n"
                + "\n".join(spread_lines)
                + "\nISTRUZIONE: Cita l'incertezza dove i modelli divergono. "
                "Il riferimento principale rimane AROME+ICON-EU; non inventare scenari.\n"
            )

    # ── Flash Flood Guidance ──────────────────────────────────────────────────
    if ffg_result and ffg_result.get("score", 0) >= 0.20:
        score_ffg = ffg_result.get("score", 0)
        desc_ffg  = ffg_result.get("desc", "")
        prompt += (
            f"\nFLASH FLOOD GUIDANCE (ARPAL/WMO): score={score_ffg:.2f}/1.0 – {desc_ffg}\n"
            "Se il FFG score è ≥0.45, menziona esplicitamente il rischio alluvioni "
            "lampo per i torrenti del Levante Ligure (Vara, Magra, Parmignola).\n"
        )

    # ── Analisi ondata di calore ──────────────────────────────────────────────
    if heatwave_result and heatwave_result.get("severity") not in ("nessuna", None):
        hw_desc = heatwave_result.get("desc", "")
        hw_sev  = heatwave_result.get("severity", "")
        prompt += (
            f"\nONDATA DI CALORE (WMO/ARPAL): {hw_desc}\n"
            "Includi raccomandazioni per persone anziane e soggetti vulnerabili "
            "se la severità è 'moderata' o superiore.\n"
        )

    # ── Tabella oraria (solo se non è tendenza) ───────────────────────────────
    if hourly_table and not is_tendency:
        prompt += (
            f"\nTABELLA ORARIA COMPLETA (tutti i parametri ora per ora):\n"
            f"{hourly_table}\n\n"
            f"REGOLA CRITICA: usa questa tabella per descrivere l'EVOLUZIONE dei fenomeni "
            f"indicando gli orari specifici. La giornata NON è uniforme: "
            f"una raffica alle 16:00 non significa che ha soffiato tutto il giorno; "
            f"un picco CAPE alle 15:00 non significa instabilità dalla mattina. "
            f"Descrivi solo ciò che i dati mostrano, ora per ora.\n"
        )

    return prompt
