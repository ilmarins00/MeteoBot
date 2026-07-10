# logic.py
"""
Logica decisionale del motore MeteoBot.
Implementa:
  - Score convettivo multi-parametro (con amplificazione orografica Spezzino)
  - Classificazione modalità temporale (WMO + SPC taxonomy)
  - Hazard mapping completo (grandine, trombe, downburst, alluvioni rapide, ecc.)
  - Sistema allerte ARPAL Liguria: Verde / Gialla / Arancione / Rossa
  - Analisi fenomeni specifici del Levante Ligure (brezza, ciclogenesi Ligure,
    Medicane, neve in quota, nebbia marina, Libeccio/Scirocco intensi)

Soglie calibrate su:
  - ARPAL Liguria – Valori soglia per avviso meteorologico (2020)
  - WMO Guide to Severe Weather Warnings (2018)
  - SPC Supercell/Tornado Composite parameters
"""

from typing import Dict, List, Tuple, Optional, Any
from config import THRESHOLDS, ALERT_LEVELS, ALERT_EMOJI, thresholds

# ─────────────────────────────────────────────────────────────────────────────
# Score convettivo multi-parametro
# ─────────────────────────────────────────────────────────────────────────────

def convective_score(params: Dict[str, float]) -> int:
    """
    Score multi-parametro convettivo (0–12+).

    PRINCIPIO CHIAVE: i temporali forti e organizzati richiedono la cooperazione
    di più parametri simultaneamente. CAPE da solo = celle disorganizzate deboli.
    I punti "extra" vengono assegnati solo quando i pilastri fisici collaborano:

      Pilastro 1 – Energia:     CAPE (SB/MU/ML)
      Pilastro 2 – Organizzazione: Shear 0-6km, SRH 0-3km
      Pilastro 3 – Umidità:    PWAT, LCL basso
      Pilastro 4 – Dinamica:   TT, K-Index, EHI, SCP, lapse rate
      Pilastro 5 – Locale:     orografico Appennino, brezza marina

    Bonus sinergia: quando ≥2 pilastri sono elevati contemporaneamente.
    Malus isolamento: CAPE alto senza dinamica = celle effimere.
    """
    score = 0

    # — CAPE: energia convettiva disponibile
    cape_sb = params.get("SBCAPE", params.get("CAPE", 0))
    cape_mu = params.get("MUCAPE", cape_sb)
    cape_ml = params.get("MLCAPE", cape_sb)
    cape = max(cape_sb, cape_mu, cape_ml)

    if cape >= thresholds.SBCAPE_EXTREME:
        score += 3    # era 4: ridotto, il 4° punto viene dai bonus sinergia
    elif cape >= thresholds.SBCAPE_STRONG:
        score += 2
    elif cape >= thresholds.SBCAPE_MODERATE:
        score += 1
    elif cape >= thresholds.SBCAPE_WEAK:
        score += 0   # CAPE debole: nessun punto base, ma conta per sinergia

    # — Shear 0-6 km: organizzazione e longevità delle celle
    shear = params.get("shear_0_6", 0)
    if shear >= thresholds.SHEAR_06_EXTREME:
        score += 3
    elif shear >= thresholds.SHEAR_06_SUPERCELL:
        score += 2
    elif shear >= thresholds.SHEAR_06_ORGANIZED:
        score += 1

    # — SRH 0-3 km: rotazione potenziale
    srh = max(
        params.get("srh_0_3", 0),
        params.get("srh_0_1", 0) * 1.5,
    )
    if srh >= thresholds.SRH_03_HIGH:
        score += 2
    elif srh >= thresholds.SRH_03_MODERATE:
        score += 1

    # — PWAT: efficienza precipitativa e carburante umido
    pwat = params.get("PWAT", 0)
    if pwat >= thresholds.PWAT_EXTREME:
        score += 2
    elif pwat >= thresholds.PWAT_HUMID:
        score += 1

    # — CIN: inibizione (riduce score se forte)
    cin = abs(params.get("CIN", params.get("SBCIN", 0)))
    if cin >= abs(thresholds.CIN_STRONG):
        score -= 2
    elif cin >= abs(thresholds.CIN_MODERATE):
        score -= 1

    # — Totals-Totals e K-Index (instabilità termica a media quota)
    tt = params.get("TT", None)
    if tt is not None:
        if tt >= thresholds.TT_EXTREME:
            score += 2
        elif tt >= thresholds.TT_STRONG:
            score += 1

    ki = params.get("KI", None)
    if ki is not None:
        if ki >= thresholds.KI_EXTREME:
            score += 1
        elif ki >= thresholds.KI_STRONG:
            score += 1

    # — EHI: già composito (CAPE × SRH)
    ehi = params.get("EHI", None)
    if ehi is not None:
        if ehi >= thresholds.EHI_EXTREME:
            score += 2
        elif ehi >= thresholds.EHI_HIGH:
            score += 1

    # — SCP: già composito (CAPE × shear × SRH × PWAT)
    scp = params.get("SCP", None)
    if scp is not None and scp >= thresholds.SCP_HIGH:
        score += 2
    elif scp is not None and scp >= thresholds.SCP_MODERATE:
        score += 1

    # — Lapse rate 0-3 km > 8 K/km = strato superadiabatico
    lr = params.get("lr_0_3km", None)
    if lr is not None and lr >= 8.0:
        score += 1

    # — Amplificazione orografica Appennino Ligure
    oro = params.get("orographic_factor", 0.0)
    if oro >= 0.7:
        score += 2
    elif oro >= 0.4:
        score += 1

    # — Convergenza brezza marina (rischio innesco pomeridiano)
    sea_conv = params.get("sea_breeze_convergence", 0.0)
    if sea_conv >= 0.6:
        score += 1

    # ── BONUS SINERGIA: punti extra solo quando pilastri collaborano ──────
    # Un temporale organizzato richiede CAPE *e* dinamica

    # Sinergia livello 1: energia + organizzazione (MCS/multicella possibile)
    if cape >= thresholds.SBCAPE_MODERATE and shear >= thresholds.SHEAR_06_ORGANIZED:
        score += 1

    # Sinergia livello 2: energia + shear forte + rotazione (supercella possibile)
    if (cape >= thresholds.SBCAPE_STRONG
            and shear >= thresholds.SHEAR_06_SUPERCELL
            and srh >= thresholds.SRH_03_MODERATE):
        score += 2

    # Sinergia livello 3: tutti i pilastri = ambiente temporalesco severo
    if (cape >= thresholds.SBCAPE_EXTREME
            and shear >= thresholds.SHEAR_06_SUPERCELL
            and srh >= thresholds.SRH_03_HIGH
            and pwat >= thresholds.PWAT_HUMID):
        score += 2

    # ── MALUS ISOLAMENTO: CAPE alto senza dinamica = celle disorganizzate ──
    # Alta energia ma nessun supporto = temporali brevi e poco organizzati
    if (cape >= thresholds.SBCAPE_STRONG
            and shear < thresholds.SHEAR_06_WEAK
            and srh < 50
            and (ehi is None or ehi < thresholds.EHI_MODERATE)
            and (scp is None or scp < thresholds.SCP_MODERATE)):
        score -= 3 if cape >= thresholds.SBCAPE_EXTREME else 2  # celle singole effimere: riduce il rischio sistemico

    return max(score, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Classificazione modalità convettiva
# ─────────────────────────────────────────────────────────────────────────────

def classify_storm_mode(params: Dict[str, float]) -> str:
    """
    Classifica la modalità convettiva attesa in base a CAPE, shear, SRH, SCP, STP,
    e alla presenza reale di innesco (pioggia prevista nei dati).
    """
    cape   = max(params.get("SBCAPE", params.get("CAPE", 0)),
                 params.get("MUCAPE", 0))
    shear  = params.get("shear_0_6", 0)
    srh    = params.get("srh_0_3", params.get("srh_0_1", 0))
    scp    = params.get("SCP",  0) or 0
    stp    = params.get("STP",  0) or 0
    pwat   = params.get("PWAT", 0) or 0
    oro    = params.get("orographic_factor", 0.0) or 0.0
    precip = params.get("precip_rate_mm_h", 0) or 0
    wmo    = int(params.get("wmo_code", 0) or 0)
    wmo_convettivo = wmo in (80, 81, 82, 95, 96, 99)
    ha_innesco = precip > 1.0 or wmo_convettivo

    if cape < thresholds.SBCAPE_WEAK:
        if pwat >= thresholds.PWAT_HUMID:
            return "precipitazioni stratiforme con debole convezione embedded"
        return "attività convettiva assente o molto debole"

    # CORREZIONE: senza shear organizzato E senza innesco reale nei dati,
    # non si può parlare di "temporali forti/isolati" — è energia latente, punto.
    if not ha_innesco and shear < thresholds.SHEAR_06_ORGANIZED:
        return "energia convettiva elevata ma senza innesco previsto – cielo probabilmente stabile"

    if stp >= thresholds.STP_VIOLENT:
        return "supercella intensa con rischio tornado significativo"
    if scp >= thresholds.SCP_HIGH and srh >= thresholds.SRH_03_HIGH:
        return "supercelle probabili – ambiente fortemente rotante"
    if scp >= thresholds.SCP_MODERATE and shear >= thresholds.SHEAR_06_ORGANIZED:
        return "supercella isolata possibile"
    if shear >= thresholds.SHEAR_06_SUPERCELL and srh >= thresholds.SRH_03_MODERATE:
        return "multicelle organizzate con possibile supercella"
    if shear >= thresholds.SHEAR_06_ORGANIZED:
        if oro >= 0.5:
            return "multicelle organizzate con forte forzante orografico (Appennino Ligure)"
        return "multicelle organizzate – cluster temporalesco (MCS probabile)"
    if oro >= 0.5 and ha_innesco:
        return "temporali orografici su Appennino Ligure – rischio accumuli rapidi"
    if cape >= thresholds.SBCAPE_STRONG and ha_innesco:
        lr03_v = params.get("lr_0_3km", 0) or 0
        li_v   = params.get("LI") or 0
        if (li_v <= thresholds.LI_UNSTABLE
                or lr03_v >= 7.0
                or float(params.get("shear_0_6", 0) or 0) >= thresholds.SHEAR_06_WEAK):
            return "temporali isolati forti – celle singole dominanti"
        return "instabilità latente – temporali di calore possibili ma disorganizzati"
    if ha_innesco:
        return "temporali sparsi di calore – bassa organizzazione"
    return "energia convettiva presente ma innesco improbabile – giornata prevalentemente stabile"

# ─────────────────────────────────────────────────────────────────────────────
# Hazard mapping completo
# ─────────────────────────────────────────────────────────────────────────────

def severe_hazards(params: Dict[str, float]) -> Dict[str, List[str]]:
    """
    Determina i fenomeni severi separando i RISCHI REALI (innescati, con pioggia/temporale
    già in atto nei dati) dai RISCHI POTENZIALI (energia presente ma innesco non confermato).

    PRINCIPIO FONDAMENTALE (correzione bug "meteo immaginario"):
    Nessun hazard (grandine, downburst, trombe marine, V-shape) può essere "reale" senza
    un innesco realistico. L'innesco richiede ALMENO UNA delle due condizioni:
      a) Nei dati orari è già prevista pioggia/temporale (wmo_code convettivo, o precip > soglia)
      b) C'è organizzazione dinamica sufficiente (shear organizzato) a supportare che
         l'energia disponibile possa davvero scaricarsi in un temporale strutturato.

    Se NESSUNA delle due è vera (es. CAPE altissimo ma shear debole e zero pioggia nei dati
    orari), tutti gli hazard convettivi vanno in "potenziali" con una nota che spiega che
    l'innesco è improbabile — non vanno mai presentati come "reali" o come narrazione
    di un temporale in corso.
    """
    reali: List[str] = []
    potenziali: List[str] = []

    cape = max(params.get("SBCAPE", params.get("CAPE", 0)), params.get("MUCAPE", 0))
    shear = params.get("shear_0_6", 0)
    srh1 = params.get("srh_0_1", 0)
    srh3 = params.get("srh_0_3", 0)
    pwat = params.get("PWAT", 0)
    cin = abs(params.get("CIN", params.get("SBCIN", 0)) or 0)
    lcl = params.get("LCL", 1500)
    rh = params.get("humidity_pct", 50)
    precip = params.get("precip_rate_mm_h", 0)
    wind = params.get("wind_gust_kmh", 0)
    dcape = float(params.get("DCAPE", 0) or 0)
    lr03 = params.get("lr_0_3km", 0) or 0
    lr75 = params.get("lr_700_500", 0) or 0
    oro = params.get("orographic_factor", 0.0) or 0.0
    wmo_haz = int(params.get("wmo_code", 0) or 0)

    is_capped = cin >= abs(thresholds.CIN_STRONG) or lcl >= thresholds.LCL_HIGH or rh <= 40 or lr75 < 5.5

    # ── INNESCO REALE: richiede pioggia/temporale nei dati orari OPPURE shear organizzato.
    # Senza shear organizzato (>= SHEAR_06_ORGANIZED = 20 kt), l'energia CAPE anche enorme
    # produce al massimo celle isolate e brevi, NON un sistema strutturato che genera
    # downburst/grandine/trombe in modo affidabile.
    wmo_convettivo = wmo_haz in (80, 81, 82, 95, 96, 99)
    shear_organizzato = shear >= thresholds.SHEAR_06_ORGANIZED
    ha_precipitazione_prevista = precip > 1.0 or wmo_convettivo

    has_trigger = ha_precipitazione_prevista and not is_capped
    # Il "supporto dinamico" serve per dire che l'energia PUO' scaricarsi in modo organizzato;
    # senza di esso, anche con innesco, i fenomeni restano isolati/deboli.
    has_dynamic_support = shear_organizzato or (has_trigger and oro >= 0.5)

    def add_hazard(testo: str, is_real: bool):
        if is_real:
            reali.append(testo)
        else:
            potenziali.append(testo)

    # -- TORNADO / TROMBE MARINE --
    # Richiede STP/SRH elevati E supporto dinamico reale, altrimenti resta ipotesi teorica
    tornado_risk = params.get("STP", 0) >= thresholds.STP_MODERATE or (srh1 >= thresholds.SRH_01_HIGH and shear >= thresholds.SHEAR_01_TORNADO)
    if tornado_risk and has_dynamic_support:
        add_hazard("Trombe d'aria/marine (STP/SRH elevati)", has_trigger and not is_capped)

    # -- GRANDINE -- richiede shear organizzato, non solo CAPE
    if cape >= 1500 and shear_organizzato:
        dim = ">2 cm" if lr03 >= 8.0 and cape >= 2500 else "1-2 cm"
        add_hazard(f"Grandine di dimensioni significative ({dim})", has_trigger and not is_capped)

    # -- DOWNBURST E RAFFICHE --
    # Un downburst richiede che ci sia REALMENTE un temporale/rovescio in corso (has_trigger),
    # non solo DCAPE teorico. Senza innesco, il DCAPE alto è energia "sulla carta" ma non
    # rappresenta un rischio concreto per la giornata.
    if dcape >= thresholds.DCAPE_HIGH:
        from thermo import dcape_gust_kmh as _dcape_gust
        v_est = _dcape_gust(dcape)
        if has_trigger:
            add_hazard(
                f"Downburst severo possibile in caso di temporale – raffica stimata fino a {v_est:.0f} km/h",
                not is_capped,
            )
        else:
            # Energia da downburst presente ma NESSUN innesco nei dati: nota informativa,
            # mai presentata come rischio della giornata.
            potenziali.append(
                f"Energia per downburst teoricamente elevata (DCAPE {dcape:.0f} J/kg), ma "
                f"nessun innesco convettivo previsto nei dati orari: rischio pratico basso"
            )
    elif dcape >= thresholds.DCAPE_MODERATE and has_trigger:
        from thermo import dcape_gust_kmh as _dcape_gust
        v_est = _dcape_gust(dcape)
        add_hazard(
            f"Raffiche discendenti (downburst) in caso di temporale – stima {v_est:.0f} km/h",
            not is_capped,
        )

    # -- ALLUVIONI LAMPO E RIGENERANTI -- richiedono pioggia realmente prevista
    if has_trigger:
        if pwat >= thresholds.PWAT_HUMID and oro >= 0.6 and srh3 >= 200:
            add_hazard("Sistemi stazionari rigeneranti (V-Shaped) su Appennino", True)
        elif pwat >= thresholds.PWAT_NORMAL and precip >= 15:
            add_hazard("Allagamenti rapidi (Flash Flood) per accumuli orari", True)

    # -- RISCHI SINOTTICI (Sempre reali se presenti, indipendenti da innesco convettivo) --
    snow_level = params.get("snow_level_m", 2000)
    if snow_level <= thresholds.SNOW_LEVEL_COASTAL_M and params.get("temp_c", 10) <= 3:
        reali.append("Neve a quote collinari/costiere")

    if wind >= thresholds.ARPAL_WIND_ARANCIONE:
        reali.append(f"Vento burrascoso (> {thresholds.ARPAL_WIND_ARANCIONE} km/h)")

    if params.get("wave_height_m", 0) >= thresholds.WAVE_HEIGHT_ARANCIONE:
        reali.append("Mareggiata significativa")

    return {"reali": reali, "potenziali": potenziali}


# ─────────────────────────────────────────────────────────────────────────────
# Sistema allerte ARPAL (Verde / Gialla / Arancione / Rossa)
# ─────────────────────────────────────────────────────────────────────────────

def arpal_alert_rain(
    rain_1h: float = 0,
    rain_3h: float = 0,
    rain_6h: float = 0,
    rain_12h: float = 0,
    rain_24h: float = 0,
) -> str:
    """Livello allerta ARPAL per precipitazioni (Zona A/B Levante Ligure)."""
    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_ROSSO
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_ROSSO
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_ROSSO
     or rain_12h >= thresholds.ARPAL_RAIN_12H_ROSSO
     or rain_24h >= thresholds.ARPAL_RAIN_24H_ROSSO):
        return "rossa"
    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_ARANCIONE
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_ARANCIONE
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_ARANCIONE
     or rain_12h >= thresholds.ARPAL_RAIN_12H_ARANCIONE
     or rain_24h >= thresholds.ARPAL_RAIN_24H_ARANCIONE):
        return "arancione"
    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_GIALLO
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_GIALLO
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_GIALLO
     or rain_12h >= thresholds.ARPAL_RAIN_12H_GIALLO
     or rain_24h >= thresholds.ARPAL_RAIN_24H_GIALLO):
        return "gialla"
    return "verde"


def arpal_alert_wind(wind_kmh: float, coastal: bool = True) -> str:
    """Livello allerta ARPAL per vento."""
    lim_r = thresholds.ARPAL_WIND_COAST_ROSSO    if coastal else thresholds.ARPAL_WIND_INLAND_ROSSO
    lim_a = thresholds.ARPAL_WIND_COAST_ARANCIONE if coastal else thresholds.ARPAL_WIND_INLAND_ARANCIONE
    lim_g = thresholds.ARPAL_WIND_COAST_GIALLO    if coastal else thresholds.ARPAL_WIND_INLAND_GIALLO
    if wind_kmh >= lim_r:
        return "rossa"
    if wind_kmh >= lim_a:
        return "arancione"
    if wind_kmh >= lim_g:
        return "gialla"
    return "verde"


def arpal_alert_temperature(temp_c: float) -> str:
    """Livello allerta ARPAL per caldo / freddo."""
    if temp_c >= thresholds.ARPAL_HEAT_ROSSO or temp_c <= thresholds.ARPAL_FROST_ROSSO:
        return "rossa"
    if temp_c >= thresholds.ARPAL_HEAT_ARANCIONE or temp_c <= thresholds.ARPAL_FROST_ARANCIONE:
        return "arancione"
    if temp_c >= thresholds.ARPAL_HEAT_GIALLO or temp_c <= thresholds.ARPAL_FROST_GIALLO:
        return "gialla"
    return "verde"


def arpal_alert_snow(snow_cm: float) -> str:
    """Livello allerta ARPAL per neve (quota 0-200 m)."""
    if snow_cm >= thresholds.ARPAL_SNOW_ROSSO:     return "rossa"
    if snow_cm >= thresholds.ARPAL_SNOW_ARANCIONE: return "arancione"
    if snow_cm >= thresholds.ARPAL_SNOW_GIALLO:    return "gialla"
    return "verde"


def composite_arpal_alert(
    rain_1h: float = 0,
    rain_3h: float = 0,
    rain_6h: float = 0,
    rain_12h: float = 0,
    rain_24h: float = 0,
    wind_kmh: float = 0,
    temp_c: Optional[float] = None,
    snow_cm: float = 0,
    wave_height_m: float = 0,
    coastal: bool = True,
) -> Tuple[str, Dict[str, str]]:
    """
    Calcola il livello allerta composito (il massimo tra tutti i rischi)
    e ritorna (livello_max, dict con dettaglio per rischio).
    """
    detail: Dict[str, str] = {
        "pioggia": arpal_alert_rain(rain_1h, rain_3h, rain_6h, rain_12h, rain_24h),
        "vento":   arpal_alert_wind(wind_kmh, coastal),
    }
    if temp_c is not None:
        detail["temperatura"] = arpal_alert_temperature(temp_c)
    if snow_cm > 0:
        detail["neve"] = arpal_alert_snow(snow_cm)
    
    # Livello allerta massimo
    max_lvl = "verde"
    order = ["verde", "gialla", "arancione", "rossa"]
    for l in detail.values():
        if order.index(l) > order.index(max_lvl):
            max_lvl = l
    
    return max_lvl, detail


def full_alert(params: Dict[str, float], score: float, rain_obs: Dict[str, float]) -> Tuple[str, str]:
    """
    Determina il livello allerta finale basato sia sullo score convettivo
    che sulle soglie ARPAL.
    """
    # 1. Mappa lo score numerico (0-5) in allerta
    score_alert = map_score_to_alert(score)
    
    # 2. Calcola allerta ARPAL da soglie fisiche
    arpal_lvl, _ = composite_arpal_alert(
        rain_1h=rain_obs.get("1h", 0),
        rain_3h=rain_obs.get("3h", 0),
        rain_6h=rain_obs.get("6h", 0),
        rain_24h=rain_obs.get("24h", 0),
        wind_kmh=params.get("wind_gust_kmh", 0),
        temp_c=params.get("temp_c"),
        wave_height_m=params.get("wave_height_m", 0)
    )
    
    # Prendi il massimo tra i due
    order = ["verde", "gialla", "arancione", "rossa"]
    final_lvl = arpal_lvl
    if order.index(score_alert) > order.index(arpal_lvl):
        final_lvl = score_alert
        
    return final_lvl, ALERT_EMOJI.get(final_lvl, "⚪")


def map_score_to_alert(score: float) -> str:
    """Mappa lo score 0-5 in livelli allerta."""
    if score >= 4.0: return "rossa"
    if score >= 2.5: return "arancione"
    if score >= 1.0: return "gialla"
    return "verde"


def maltempo_score(
    params: Dict[str, float],
    rain_obs: Optional[Dict[str, float]] = None,
) -> float:
    """
    Score maltempo multi-categoria (0–5), cap a 5.
    
    CORREZIONE: il peso dei parametri convettivi estremi è stato ricalibrato
    per riflettere il rischio severo, evitando che un ambiente da supercella 
    (es. CAPE estremo + shear + SCP/STP elevati) venga declassato a "moderato".
    """
    rain = rain_obs or {}
    score = 0.0

    # ── 1. Pioggia / Alluvioni ─────────
    rain_1h  = max(float(rain.get("1h",  0) or 0),
                   float(params.get("precip_rate_mm_h", 0) or 0))
    rain_3h  = float(rain.get("3h",  0) or 0)
    rain_6h  = float(rain.get("6h",  0) or 0)
    rain_24h = float(rain.get("24h", params.get("rain_24h_mm", 0)) or 0)

    if (rain_1h  >= thresholds.ARPAL_RAIN_1H_ROSSO
     or rain_3h  >= thresholds.ARPAL_RAIN_3H_ROSSO
     or rain_6h  >= thresholds.ARPAL_RAIN_6H_ROSSO
     or rain_24h >= thresholds.ARPAL_RAIN_24H_ROSSO):
        score += 1.5
    elif (rain_1h  >= thresholds.ARPAL_RAIN_1H_ARANCIONE
       or rain_3h  >= thresholds.ARPAL_RAIN_3H_ARANCIONE
       or rain_6h  >= thresholds.ARPAL_RAIN_6H_ARANCIONE
       or rain_24h >= thresholds.ARPAL_RAIN_24H_ARANCIONE):
        score += 1.0
    elif (rain_1h  >= thresholds.ARPAL_RAIN_1H_GIALLO
       or rain_3h  >= thresholds.ARPAL_RAIN_3H_GIALLO
       or rain_6h  >= thresholds.ARPAL_RAIN_6H_GIALLO
       or rain_24h >= thresholds.ARPAL_RAIN_24H_GIALLO):
        score += 0.5

    # ── 2. Temporali / Convezione ─────────────────────────────────────────
    # CORREZIONE: Pesi aumentati per SCP, STP e combinazioni estreme di CAPE+Shear.
    # Il cap di questa singola categoria viene rilassato per ambienti severi.
    
    cape = max(
        float(params.get("SBCAPE", params.get("CAPE", 0)) or 0),
        float(params.get("MUCAPE", 0) or 0),
    )
    wmo      = int(params.get("wmo_code", 0) or 0)
    scp      = float(params.get("SCP", 0) or 0)
    stp      = float(params.get("STP", 0) or 0)
    li       = params.get("LI")
    li_f     = float(li) if li is not None else 0.0
    shear_06 = float(params.get("shear_0_6", 0) or 0)
    srh_03   = float(params.get("srh_0_3", 0) or 0)
    dcape    = float(params.get("DCAPE", 0) or 0)
    cin      = float(params.get("CIN", 0) or 0)
    lcl      = float(params.get("LCL", 1500) or 1500)
    rh       = float(params.get("humidity_pct", 50) or 50)

    # Parametri di supporto
    supp_params = sum([
        shear_06 >= thresholds.SHEAR_06_ORGANIZED,
        srh_03   >= thresholds.SRH_03_MODERATE,
        li_f     <= thresholds.LI_UNSTABLE,
        dcape    >= thresholds.DCAPE_MODERATE,
        float(params.get("PWAT", 0) or 0) >= thresholds.PWAT_HUMID,
    ])

    conv_score = 0.0

    # FILTRO INTELLIGENTE: se c'è un forte tappo, riduciamo il contributo convettivo
    is_capped = cin <= thresholds.CIN_STRONG or lcl >= thresholds.LCL_HIGH or rh <= 35

    # Lapse rate come indicatore di instabilità reale bassi/media quota
    lr03 = float(params.get("lr_0_3km", 0) or 0)
    lr75 = float(params.get("lr_700_500", 0) or 0)
    lr_bonus = 0.0
    if lr03 >= thresholds.LAPSE_03_EXTREME or lr75 >= thresholds.LAPSE_75_VERY_UNSTABLE:
        lr_bonus = 0.3
    elif lr03 >= thresholds.LAPSE_03_VERY_UNSTABLE or lr75 >= thresholds.LAPSE_75_UNSTABLE:
        lr_bonus = 0.15

    # Termine di organizzazione: CAPE da solo senza shear non basta più
    # a raggiungere le fasce alte. Serve shear organizzato per salire.
    organized = shear_06 >= thresholds.SHEAR_06_ORGANIZED

    if stp >= thresholds.STP_MODERATE or scp >= thresholds.SCP_HIGH:
        conv_score += 2.5
    elif (scp >= thresholds.SCP_MODERATE
          or wmo == 99
          or (cape >= thresholds.SBCAPE_EXTREME and supp_params >= 2 and organized)
          or (cape >= thresholds.SBCAPE_STRONG and supp_params >= 3)):
        conv_score += 2.0
    elif (wmo in (95, 96)
          or li_f <= thresholds.LI_VERY_UNSTABLE
          or (cape >= thresholds.SBCAPE_STRONG and supp_params >= 1)
          or (cape >= thresholds.SBCAPE_EXTREME and organized)):
        conv_score += 1.0
    elif (wmo in (80, 81, 82, 91, 92)
          or li_f <= thresholds.LI_UNSTABLE
          or (cape >= thresholds.SBCAPE_MODERATE and organized)):
        conv_score += 0.5
    elif cape >= thresholds.SBCAPE_EXTREME and not organized:
        # CAPE estremo ma isolato (shear debole): energia enorme ma nessuna
        # struttura per organizzarla. Contributo minimo, non trascurabile,
        # perché il rischio di downburst puntiforme resta reale.
        conv_score += 0.3

    conv_score += lr_bonus

    # Se c'è tappo e non ci sono temporali in atto, dimezziamo il rischio convettivo
    if is_capped and wmo < 80:
        conv_score *= 0.5

    score += min(conv_score, 1.5)  # rispetta il cap di categoria dichiarato in docstring

    # ── 3. Vento (costa spezzina) ─────────────────────────────────────────
    wind = float(params.get("wind_gust_kmh", 0) or 0)

    if wind >= thresholds.ARPAL_WIND_COAST_ROSSO:
        score += 1.5
    elif wind >= thresholds.ARPAL_WIND_COAST_ARANCIONE:
        score += 1.0
    elif wind >= thresholds.ARPAL_WIND_COAST_GIALLO:
        score += 0.5

    # ── 4. Caldo estremo ──────────────────────────────────────────────────
    temp = params.get("temp_c")
    temp_f = float(temp) if temp is not None else None

    if temp_f is not None:
        if temp_f >= thresholds.ARPAL_HEAT_ROSSO:
            score += 1.5
        elif temp_f >= thresholds.ARPAL_HEAT_ARANCIONE:
            score += 1.0
        elif temp_f >= thresholds.ARPAL_HEAT_GIALLO:
            score += 0.5

    # ── 5. Afa ────────────────────────
    app_temp = params.get("heat_index") or params.get("apparent_temperature")
    if app_temp is not None:
        app_f = float(app_temp)
        t_base = temp_f if temp_f is not None else 0.0
        disagio = app_f - t_base
        if app_f >= thresholds.HEAT_INDEX_EXTREME or disagio >= 6:
            score += 1.5
        elif app_f >= thresholds.HEAT_INDEX_DANGER or disagio >= 4:
            score += 1.0
        elif app_f >= thresholds.HEAT_INDEX_WARNING or disagio >= 2:
            score += 0.5

    return round(min(score, 5.0), 1)


def livello_attenzione(score: float) -> Tuple[str, str]:
    """
    Converte lo score maltempo (0–5+) in livello di attenzione.
    BASSO <1 | MODERATO 1–2.5 | ALTO 2.5–4 | MOLTO ALTO 4–5 | NON CLASSIFICABILE >5
    Ritorna (etichetta, emoji).
    """
    if score > 5.0:
        return "NON CLASSIFICABILE", "⛔"
    if score >= 4.0:
        return "MOLTO ALTO", "🔴"
    if score >= 2.5:
        return "ALTO", "🟠"
    if score >= 1.0:
        return "MODERATO", "🟡"
    
    # CORREZIONE: aggiunto il return mancante per i valori bassi (< 1.0)
    return "BASSO", "🟢"

def flash_flood_guidance(
    params: Dict[str, Any],
    rain_obs: Dict[str, float],
    soil_moisture: Optional[float] = None
) -> Tuple[float, str]:
    """
    Calcola il rischio di alluvione lampo (Flash Flood) basato su intensità oraria,
    saturazione del suolo e forzante orografico.
    Ritorna (score, descrizione).
    """
    rain_1h = float(rain_obs.get("1h", 0) or 0)
    oro_factor = float(params.get("orographic_factor", 0) or 0)
    
    base_risk = 0.0
    if rain_1h >= 50: base_risk = 0.9
    elif rain_1h >= 30: base_risk = 0.6
    elif rain_1h >= 15: base_risk = 0.3
    
    # Aumento rischio per suolo saturo
    if soil_moisture is not None and float(soil_moisture or 0) > 0.8:
        base_risk += 0.2
        
    # Aumento rischio per orografia (effetto stazionarietà)
    if oro_factor > 0.6:
        base_risk += 0.2
        
    risk_val = min(base_risk, 1.0)
    
    level = "BASSO"
    if risk_val >= 0.8: level = "ESTREMO"
    elif risk_val >= 0.5: level = "ELEVATO"
    elif risk_val >= 0.2: level = "MODERATO"
    
    desc = f"Rischio alluvione lampo {level} (score {risk_val:.2f})"
    return risk_val, desc

def heatwave_analysis(
    temp_history: List[Any],
    temp_max_today: float,
    temp_min_today: float,
    heat_index_today: Optional[float] = None
) -> Dict[str, Any]:
    """
    Analisi ondata di calore basata su Heat Index e persistenza delle temperature.
    Gestisce temp_history sia come lista di float che come lista di dict.
    """
    hi = float(heat_index_today or temp_max_today or 0)
    
    level = "NORMALE"
    if hi >= 41: level = "PERICOLO ESTREMO"
    elif hi >= 35: level = "PERICOLO"
    elif hi >= 30: level = "CAUTELA"
    
    # Estrazione temperature minime dallo storico
    min_temps = []
    for entry in temp_history:
        if isinstance(entry, dict):
            min_temps.append(float(entry.get("T_min", entry.get("temp_min", 0))))
        else:
            min_temps.append(float(entry))
            
    # Persistenza (se le ultime 3 notti sono state calde, > 20°C)
    nights_warm = sum(1 for t in min_temps[-3:] if t > 20) if min_temps else 0
    
    return {
        "heat_index": round(hi, 1),
        "level": level,
        "is_heatwave": hi >= 35 or nights_warm >= 3,
        "nights_warm": nights_warm,
        "severity": level.lower() if hi >= 30 else "nessuna",
        "desc": f"Disagio da calore {level} (HI {hi:.1f}°C)"
    }

# ─────────────────────────────────────────────────────────────────────────────
# Analisi evoluzione e persistenza dell'instabilità (serie oraria)
# ─────────────────────────────────────────────────────────────────────────────

def instability_evolution(hourly: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analizza la serie oraria di CAPE/CIN/LI per determinare:
      - finestre orarie con instabilità elevata (CAPE >= SBCAPE_STRONG)
      - durata in ore di ciascuna finestra consecutiva
      - trend (crescente / decrescente / stabile) nell'arco della finestra
      - il momento del picco assoluto

    hourly: lista di dict con almeno 'time', 'CAPE', 'CIN' (opz. 'LI').
    Ritorna un dict pronto sia per il rendering diretto sia per il prompt Gemini.
    """
    result: Dict[str, Any] = {
        "windows": [],       # lista di {"start","end","duration_h","cape_avg","trend"}
        "peak_time": None,
        "peak_cape": 0.0,
        "total_unstable_hours": 0,
    }
    if not hourly:
        return result

    thr = thresholds
    rows = [
        (h.get("time", "??:??"), float(h.get("CAPE") or 0), float(h.get("CIN") or 0))
        for h in hourly
    ]

    # Picco assoluto
    peak = max(rows, key=lambda r: r[1], default=None)
    if peak:
        result["peak_time"] = peak[0]
        result["peak_cape"] = peak[1]

    # Trova finestre consecutive con CAPE >= soglia "strong"
    windows = []
    cur_start = None
    cur_vals = []
    for t, cape, cin in rows:
        if cape >= thr.SBCAPE_STRONG:
            if cur_start is None:
                cur_start = t
            cur_vals.append(cape)
        else:
            if cur_start is not None:
                windows.append((cur_start, t, cur_vals))
                cur_start, cur_vals = None, []
    if cur_start is not None:
        windows.append((cur_start, rows[-1][0], cur_vals))

    for start, end, vals in windows:
        if len(vals) < 2:
            trend = "picco isolato"
        else:
            delta = vals[-1] - vals[0]
            if delta > 300:
                trend = "in rafforzamento"
            elif delta < -300:
                trend = "in attenuazione"
            else:
                trend = "stazionaria"
        result["windows"].append({
            "start": start,
            "end": end,
            "duration_h": len(vals),
            "cape_avg": round(sum(vals) / len(vals), 0),
            "trend": trend,
        })

    result["total_unstable_hours"] = sum(w["duration_h"] for w in result["windows"])
    return result


def format_evolution_text(evo: Dict[str, Any]) -> str:
    """Rende in testo breve (per uso diretto, non-Gemini) l'evoluzione instabilità."""
    if not evo.get("windows"):
        return "Nessuna finestra di instabilità significativa individuata."
    parts = []
    for w in evo["windows"]:
        parts.append(
            f"instabilità elevata dalle {w['start']} alle {w['end']} "
            f"({w['duration_h']}h, CAPE medio {w['cape_avg']:.0f} J/kg, {w['trend']})"
        )
    peak_txt = (
        f" Picco assoluto {evo['peak_cape']:.0f} J/kg alle {evo['peak_time']}."
        if evo.get("peak_time") else ""
    )
    return "; ".join(parts) + "." + peak_txt

def rileva_fenomeni_costieri(params: Dict[str, float]) -> List[str]:
    """
    Logica avanzata costa Ligure: V-Shape autorigenerante e trombe marine.

    CORREZIONE BUG: questi fenomeni venivano segnalati anche con zero pioggia prevista
    e shear troppo debole per organizzare qualsiasi struttura (es. CAPE 4000 J/kg ma
    shear 11 kt e nessuna precipitazione nei dati orari). Ora richiedono un innesco
    minimo realistico: pioggia/temporale nei dati orari, non solo energia teorica.
    """
    avvisi_avanzati = []

    pwat = params.get("PWAT", 0)
    mlcape = params.get("MLCAPE", params.get("SBCAPE", 0))
    shear_0_6 = params.get("shear_0_6", 0)
    lr_0_3km = params.get("lr_0_3km", 0)
    shear_0_1 = params.get("shear_0_1", 0)
    precip = params.get("precip_rate_mm_h", 0)
    wmo_haz = int(params.get("wmo_code", 0) or 0)

    # Innesco minimo richiesto: pioggia/temporale già previsto nei dati,
    # altrimenti qualunque "rischio" qui sotto è pura teoria da non comunicare come reale.
    ha_innesco = precip > 1.0 or wmo_haz in (80, 81, 82, 95, 96, 99)
    if not ha_innesco:
        return avvisi_avanzati

    # 1. V-SHAPE (temporali autorigeneranti)
    if pwat >= 35.0 and mlcape >= 1000 and (15 <= shear_0_6 <= 35):
        avvisi_avanzati.append("Setup da temporale autorigenerante (V-Shape): rischio elevato di nubifragio concentrato nello stesso punto.")
    elif pwat >= 30.0 and mlcape >= 600 and (10 <= shear_0_6 <= 40):
        avvisi_avanzati.append("Possibili celle temporalesche stazionarie: rischio di piogge concentrate.")

    # 2. TROMBE MARINE (Waterspout) — richiedono comunque shear basso nei bassi strati,
    # ma solo se c'è già un contesto di rovesci/instabilità in atto (ha_innesco sopra)
    if params.get("SBCAPE", 0) > 400 and lr_0_3km > 7.5 and shear_0_1 < 15:
        avvisi_avanzati.append("Possibili trombe marine (fair weather waterspout) al largo, in presenza dei rovesci previsti.")
    elif params.get("SBCAPE", 0) > 800 and lr_0_3km > 8.0 and shear_0_1 >= 15:
        avvisi_avanzati.append("Possibili trombe marine anche intense, con rischio di landfall in caso di rovesci organizzati.")

    return avvisi_avanzati
