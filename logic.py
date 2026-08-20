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

def _duration_hours_from_times(vals: List[Tuple[str, float]]) -> float:
    """
    Calcola la durata REALE in ore di una finestra a partire dagli orari
    (non dal numero di righe): con il nowcast AROME-PI la tabella può
    contenere righe da 15 minuti invece che da un'ora intera, quindi
    contare le righe come se fossero sempre "ore" sovrastimerebbe la
    durata fino a 4 volte in quella finestra.
    """
    if not vals:
        return 0.0
    if len(vals) == 1:
        return 1.0
    try:
        def to_minutes(hhmm):
            h, mnt = hhmm.split(":")
            return int(h) * 60 + int(mnt)
        t0 = to_minutes(vals[0][0])
        t1 = to_minutes(vals[-1][0])
        step = to_minutes(vals[1][0]) - t0
        if step <= 0:
            step = 60
        return round(((t1 - t0) + step) / 60.0, 2)
    except Exception:
        return float(len(vals))

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

    if (cape >= thresholds.SBCAPE_STRONG
            and shear < thresholds.SHEAR_06_WEAK
            and srh < 50
            and (ehi is None or ehi < thresholds.EHI_MODERATE)
            and (scp is None or scp < thresholds.SCP_MODERATE)):
        score -= 3 if cape >= thresholds.SBCAPE_EXTREME else 2  # celle singole effimere: riduce il rischio sistemico

    return max(score, 0)

def assess_phenomena_risks(params: Dict, obs: Dict, hourly: list) -> Dict[str, str]:
    """
    Valuta il rischio per ciascun fenomeno atmosferico.
    Scala: Trascurabile | Marginale | Moderato | Elevato | Estremo
    """
    r = {}

    # --- TEMPORALI ---
    cape = max(params.get("SBCAPE", 0) or 0, params.get("MUCAPE", 0) or 0, params.get("CAPE", 0) or 0)
    shear = params.get("shear_0_6") or 0
    cin = abs(params.get("CIN", 0) or 0)
    wmo = int(params.get("wmo_code", 0) or 0)
    has_trigger = wmo in (80, 81, 82, 95, 96, 99) or (params.get("precip_rate_mm_h", 0) or 0) > 1.0

    if cape < 300 or cin > 200:
        r["Temporali"] = "Trascurabile"
    elif cape < 1000 and not has_trigger:
        r["Temporali"] = "Marginale"
    elif (cape < 1500) or (cape >= 1500 and shear < 20 and not has_trigger):
        r["Temporali"] = "Moderato"
    elif cape >= 1500 and shear >= 20 and has_trigger:
        r["Temporali"] = "Elevato"
    elif cape >= 2500 and shear >= 35 and has_trigger:
        r["Temporali"] = "Estremo"
    else:
        r["Temporali"] = "Moderato" if has_trigger else "Marginale"

    # --- PIOGGIA ---
    max_precip = max((h.get("precip", 0) or 0 for h in hourly), default=0)
    rain_24h = obs.get("rain_24h_mm", 0) or 0

    if max_precip < 2 and rain_24h < 10:
        r["Pioggia"] = "Trascurabile"
    elif max_precip < 10 and rain_24h < 30:
        r["Pioggia"] = "Marginale"
    elif max_precip < 30 and rain_24h < 60:
        r["Pioggia"] = "Moderato"
    elif max_precip < 50 and rain_24h < 100:
        r["Pioggia"] = "Elevato"
    else:
        r["Pioggia"] = "Estremo"

    # --- VENTO ---
    gust = obs.get("wind_gust_kmh", 0) or 0
    max_gust_hourly = max((h.get("wind_gust", h.get("wind", 0)) or 0 for h in hourly), default=0)
    gust_eff = max(gust, max_gust_hourly)

    if gust_eff < 30:
        r["Vento"] = "Trascurabile"
    elif gust_eff < 50:
        r["Vento"] = "Marginale"
    elif gust_eff < 70:
        r["Vento"] = "Moderato"
    elif gust_eff < 90:
        r["Vento"] = "Elevato"
    else:
        r["Vento"] = "Estremo"

    # --- TEMPERATURA (caldo estremo / freddo) ---
    t_max = obs.get("temp_max_c", obs.get("temp_c", 0)) or 0
    t_min = obs.get("temp_min_c", obs.get("temp_c", 0)) or 0

    if t_max >= 40 or t_min <= -10:
        r["Temperatura"] = "Estremo"
    elif t_max >= 38 or t_min <= -5:
        r["Temperatura"] = "Elevato"
    elif t_max >= 35 or t_min <= 0:
        r["Temperatura"] = "Moderato"
    elif t_max >= 32 or t_min <= 5:
        r["Temperatura"] = "Marginale"
    else:
        r["Temperatura"] = "Trascurabile"

    # --- AFA / DISAGIO TERMICO ---
    hi = obs.get("heat_index", params.get("heat_index"))
    if hi is None:
        hi = t_max

    if hi >= 41:
        r["Afa"] = "Estremo"
    elif hi >= 38:
        r["Afa"] = "Elevato"
    elif hi >= 35:
        r["Afa"] = "Moderato"
    elif hi >= 32:
        r["Afa"] = "Marginale"
    else:
        r["Afa"] = "Trascurabile"

    return r

# ─────────────────────────────────────────────────────────────────────────────
# Classificazione modalità convettiva
# ─────────────────────────────────────────────────────────────────────────────

def classify_storm_mode(params: Dict[str, float]) -> str:
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
    cin    = abs(params.get("CIN", params.get("SBCIN", 0)) or 0)   # NUOVO
    wmo_convettivo = wmo in (80, 81, 82, 95, 96, 99)
    ha_innesco = precip > 1.0 or wmo_convettivo
    wmo_con_pioggia = wmo in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
    ha_segnale_pioggia = precip > 0.1 or wmo_con_pioggia

    if cape < thresholds.SBCAPE_WEAK:
        if pwat >= thresholds.PWAT_HUMID and ha_segnale_pioggia:
            return "precipitazioni stratiforme con debole convezione embedded"
        return "attività convettiva assente o molto debole"

    if not ha_innesco:
        cin_debole = cin < abs(thresholds.CIN_MODERATE)  # CIN quasi assente
        organizzato = shear >= thresholds.SHEAR_06_ORGANIZED
        if organizzato and cin_debole and cape >= thresholds.SBCAPE_STRONG:
            prob = hazard_probability(params)
            if prob >= 30:
                return (
                    f"ambiente dinamicamente favorevole a temporali organizzati (shear "
                    f"ed energia elevati): nessun innesco confermato nei dati orari, ma il "
                    f"segnale combinato (~{prob}%) non è trascurabile — da monitorare nel "
                    f"corso della giornata, specie in caso di un trigger locale non ancora "
                    f"previsto dal modello"
                )
            elif prob >= 15:
                return (
                    f"ambiente dinamicamente favorevole a temporali organizzati (shear "
                    f"ed energia elevati) ma senza un innesco previsto nei dati orari — "
                    f"rischio basso ma non nullo (~{prob}%), non un evento atteso con "
                    f"certezza per la giornata"
                )
            else:
                return (
                    "ambiente dinamicamente favorevole a temporali organizzati (shear "
                    "ed energia elevati) ma privo di un innesco previsto nei dati orari — "
                    "il rischio pratico resta contenuto per la giornata"
                )
        if cin_debole and cape >= thresholds.SBCAPE_STRONG:
            return ("energia convettiva elevata e priva di inibizione (CIN quasi nullo) — "
                    "non si può escludere l'innesco di celle isolate da riscaldamento diurno, "
                    "pur in assenza di organizzazione dinamica (shear debole)")
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

def is_intense_storm_mode(mode: str) -> bool:
    """
    Ritorna True solo se la modalità convettiva descrive un rischio concreto di
    fenomeni intensi (supercella, multicelle organizzate, temporali forti o
    orografici, tornado, o un ambiente dinamicamente favorevole a temporali
    organizzati anche se non ancora innescato).
    Ritorna False per le descrizioni di stabilità, assenza di convezione o
    debole/stratiforme: queste non vanno mostrate come riga "Modalità" nel
    bollettino, per non dare risalto a un'etichetta che non segnala nulla di
    rilevante.
    """
    if not mode:
        return False
    m = mode.lower()
    keywords_intensi = (
        "supercell", "multicelle organizzate", "tornado",
        "temporali isolati forti", "temporali orografici",
        "mcs probabile", "dinamicamente favorevole a temporali organizzati",
    )
    return any(k in m for k in keywords_intensi)


def hazard_probability(params: Dict[str, float]) -> int:
    """
    Stima percentuale (0-100%) della probabilità che i fenomeni convettivi
    elencati nel bollettino (grandine, downburst, temporali organizzati) si
    verifichino davvero, combinando gli stessi ingredienti fisici già usati in
    severe_hazards/maltempo_score: energia (CAPE), organizzazione dinamica
    (shear), inibizione (CIN), umidità (PWAT) e presenza di un innesco
    confermato nei dati orari (pioggia/wmo_code convettivo).

    NON è una probabilità statistica verificata (tipo POP di un modello
    d'ensemble): è una stima euristica costruita su soglie SPC/WMO già
    presenti in config.py, pensata per dare un numero sintetico invece di un
    lungo testo esplicativo. Va letta come "quanto è forte il segnale nei
    dati", non come frequenza statistica di accadimento.
    """
    cape = max(
        float(params.get("SBCAPE", params.get("CAPE", 0)) or 0),
        float(params.get("MUCAPE", 0) or 0),
    )
    shear = float(params.get("shear_0_6", 0) or 0)
    cin = abs(float(params.get("CIN", params.get("SBCIN", 0)) or 0))
    pwat = float(params.get("PWAT", 0) or 0)
    precip = float(params.get("precip_rate_mm_h", 0) or 0)
    wmo = int(params.get("wmo_code", 0) or 0)

    prob = 0.0
    if cape >= thresholds.SBCAPE_WEAK:
        prob += 0.15
    if cape >= thresholds.SBCAPE_MODERATE:
        prob += 0.15
    if cape >= thresholds.SBCAPE_STRONG:
        prob += 0.15
    if shear >= thresholds.SHEAR_06_WEAK:
        prob += 0.10
    if shear >= thresholds.SHEAR_06_ORGANIZED:
        prob += 0.15
    if cin < abs(thresholds.CIN_MODERATE):
        prob += 0.10
    if pwat >= thresholds.PWAT_HUMID:
        prob += 0.10

    wmo_convettivo = wmo in (80, 81, 82, 95, 96, 99)
    ha_innesco = precip > 1.0 or wmo_convettivo
    if not ha_innesco:
        # Senza innesco confermato nei dati orari, il rischio pratico resta
        # basso indipendentemente da quanto "carica" sia l'atmosfera sulla carta.
        prob *= 0.35

    return int(round(min(prob, 1.0) * 100))

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

    # NUOVO: caso "energia scoperta" — CAPE alto, CIN quasi nullo, ma shear debole
    # e nessuna precipitazione già prevista nei dati orari. Non è un innesco confermato,
    # ma nemmeno un ambiente "tappato": va segnalato come possibilità concreta,
    # non come teoria remota.
    cin_quasi_nulla = cin < abs(thresholds.CIN_MODERATE)
    energia_scoperta = (
        cape >= thresholds.SBCAPE_STRONG
        and cin_quasi_nulla
        and not shear_organizzato
        and not ha_precipitazione_prevista
    )
    if energia_scoperta:
        potenziali.append(
            f"Energia convettiva elevata (CAPE {cape:.0f} J/kg) con inibizione quasi assente "
            f"(CIN {cin:.0f} J/kg): possibile sviluppo di celle isolate da riscaldamento diurno "
            f"nelle ore centrali/pomeridiane, specie su rilievi ed entroterra, nonostante "
            f"l'organizzazione dinamica resti debole (shear {shear:.1f} kt)"
        )

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

    if wind >= thresholds.ARPAL_WIND_COAST_ARANCIONE:
        reali.append(f"Vento burrascoso (> {thresholds.ARPAL_WIND_COAST_ARANCIONE:.0f} km/h)")

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
    temp_anomaly: Optional[Dict[str, Any]] = None,
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
    cin      = abs(float(params.get("CIN", 0) or 0))
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
    is_capped = cin >= abs(thresholds.CIN_STRONG) or lcl >= thresholds.LCL_HIGH or rh <= 35

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

    # Innesco reale: pioggia già prevista nei dati orari, o wmo_code convettivo.
    # Senza innesco, SCP/STP/CAPE alti restano energia "sulla carta": lo score
    # deve riflettere il rischio pratico della giornata, non quello teorico.
    wmo_convettivo_score = wmo in (80, 81, 82, 91, 92, 95, 96, 99)
    ha_innesco_score = rain_1h > 1.0 or wmo_convettivo_score

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

    if not ha_innesco_score:
        # Nessuna precipitazione/temporale previsto nei dati orari: anche con
        # SCP/STP elevati, il rischio pratico per la giornata resta basso.
        # Riduciamo fortemente il contributo invece di lasciarlo quasi al
        # massimo di categoria.
        conv_score *= 0.3
    elif is_capped and wmo < 80:
        # Innesco presente ma forte tappo residuo: dimezziamo comunque
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

    # ── 6. Anomalia termica in quota ────────────────────────────────────
    # Contributo piccolo e volutamente limitato (max 0.3): un'avvezione
    # fredda/calda marcata in quota segnala un contesto sinottico attivo
    # (fronte organizzato), non un rischio diretto al suolo come gli altri.
    if temp_anomaly is not None:
        lvl = temp_anomaly.get("level")
        if lvl == "eccezionale":
            score += 0.3
        elif lvl == "significativa":
            score += 0.2
        elif lvl == "degna di nota":
            score += 0.1

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
    Analizza la serie oraria di CAPE/CIN/LI/shear/SRH per determinare le finestre
    orarie con instabilità realmente significativa.

    CONCORDANZA (soglie SPC/WMO definite in config.py):
      - CAPE >= SBCAPE_STRONG (1500 J/kg) è la condizione di ingresso obbligatoria.
      - CIN forte (valore assoluto >= |CIN_STRONG|, 200 J/kg) esclude comunque
        l'ora: un'inibizione forte blocca la convezione a prescindere dal resto.
      - Tra i parametri disponibili per quell'ora (LI, shear 0-6 km, SRH 0-3 km),
        l'ora è "instabile" solo se ALMENO METÀ dei parametri disponibili
        concordano nel superare la propria soglia SPC di instabilità forte.
        Se nessuno dei tre è disponibile per quell'ora, si usa il solo CAPE.

    Un CAPE alto isolato, senza conferma da almeno metà degli indicatori
    disponibili, non genera una finestra: da solo, quasi certamente, non porta
    a nulla di rilevante.
    """
    result: Dict[str, Any] = {
        "windows": [],
        "peak_time": None,
        "peak_cape": 0.0,
        "total_unstable_hours": 0,
    }
    if not hourly:
        return result

    thr = thresholds
    rows = []
    for h in hourly:
        t = h.get("time", "??:??")
        cape = float(h.get("CAPE") or 0)
        cin_raw = h.get("CIN")
        cin = abs(float(cin_raw)) if cin_raw is not None else None
        li_raw = h.get("LI")
        li = float(li_raw) if li_raw is not None else None
        shear_raw = h.get("shear")
        shear06 = float(shear_raw) if shear_raw is not None else None
        srh_raw = h.get("SRH")
        srh03 = float(srh_raw) if srh_raw is not None else None
        rows.append((t, cape, cin, li, shear06, srh03))

    peak = max(rows, key=lambda r: r[1], default=None)
    if peak:
        result["peak_time"] = peak[0]
        result["peak_cape"] = peak[1]

    def _is_unstable(cape, cin, li, shear06, srh03) -> bool:
        if cape < thr.SBCAPE_STRONG:
            return False
        if cin is not None and cin >= abs(thr.CIN_STRONG):
            return False
        votes_total = 0
        votes_favorable = 0
        if li is not None:
            votes_total += 1
            if li <= thr.LI_VERY_UNSTABLE:
                votes_favorable += 1
        if shear06 is not None:
            votes_total += 1
            if shear06 >= thr.SHEAR_06_ORGANIZED:
                votes_favorable += 1
        if srh03 is not None:
            votes_total += 1
            if srh03 >= thr.SRH_03_MODERATE:
                votes_favorable += 1
        if votes_total == 0:
            return True  # nessun dato di conferma disponibile: usa solo CAPE
        return (votes_favorable / votes_total) >= 0.5

    windows = []
    cur_vals: List[Tuple[str, float]] = []
    for t, cape, cin, li, shear06, srh03 in rows:
        if _is_unstable(cape, cin, li, shear06, srh03):
            cur_vals.append((t, cape))
        else:
            if cur_vals:
                windows.append(cur_vals)
                cur_vals = []
    if cur_vals:
        windows.append(cur_vals)

    for vals in windows:
        cape_vals = [v for _, v in vals]
        if len(cape_vals) < 2:
            trend = "picco isolato"
        else:
            delta = cape_vals[-1] - cape_vals[0]
            if delta > 300:
                trend = "in rafforzamento"
            elif delta < -300:
                trend = "in attenuazione"
            else:
                trend = "stazionaria"
        peak_hour, peak_cape_window = max(vals, key=lambda x: x[1])
        result["windows"].append({
            "start": vals[0][0],
            "end": vals[-1][0],
            "duration_h": _duration_hours_from_times(vals),
            "cape_avg": round(sum(cape_vals) / len(cape_vals), 0),
            "trend": trend,
            "peak_hour": peak_hour,
            "peak_cape_window": round(peak_cape_window, 0),
            "vals": vals,
        })

    result["total_unstable_hours"] = sum(w["duration_h"] for w in result["windows"])
    return result

def multi_param_evolution(hourly: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Estende instability_evolution() con la curva oraria di shear, SRH e PWAT,
    campionata ogni 3 ore. Serve a rilevare pattern come "CAPE in forte aumento
    ma shear stazionario e basso" — che indicano energia scoperta ma non organizzata,
    distinguendo dal caso in cui shear e CAPE crescono insieme (rischio più concreto).
    """
    from indices import hourly_trend_series, describe_trend_series

    if not hourly:
        return {"cape": "", "shear": "", "srh": "", "pwat": "", "synergy_warning": None}

    cape_series  = hourly_trend_series(hourly, "CAPE")
    shear_series = hourly_trend_series(hourly, "shear")
    srh_series   = hourly_trend_series(hourly, "SRH")
    pwat_series  = hourly_trend_series(hourly, "PWAT")

    cape_txt  = describe_trend_series(cape_series,  "J/kg",   "CAPE")
    shear_txt = describe_trend_series(shear_series, "kt",     "Shear 0-6km")
    srh_txt   = describe_trend_series(srh_series,   "m²/s²",  "SRH 0-3km")
    pwat_txt  = describe_trend_series(pwat_series,  "mm",     "PWAT")

    # Rileva il pattern "energia su, organizzazione ferma"
    synergy_warning = None
    if cape_series and shear_series:
        cape_delta = cape_series[-1][1] - cape_series[0][1]
        shear_vals = [v for _, v in shear_series]
        shear_flat = (max(shear_vals) - min(shear_vals)) < 5.0 if shear_vals else True
        if cape_delta > 1000 and shear_flat and max(shear_vals, default=0) < thresholds.SHEAR_06_ORGANIZED:
            synergy_warning = (
                "Il CAPE cresce sensibilmente nel corso della giornata mentre lo shear "
                "resta stazionario e sotto la soglia di organizzazione: l'energia si accumula "
                "ma la capacità di strutturarla in temporali organizzati non migliora — "
                "il rischio principale resta la cella isolata da riscaldamento diurno, non il sistema organizzato."
            )

    return {
        "cape": cape_txt,
        "shear": shear_txt,
        "srh": srh_txt,
        "pwat": pwat_txt,
        "synergy_warning": synergy_warning,
    }

def format_evolution_text(evo: Dict[str, Any]) -> str:
    """
    Rende in testo l'evoluzione instabilità.
    Finestre <= 3h: intervallo orario + SOLO il valore di picco.
    Finestre >= 4h: intervallo orario + valore CAPE di OGNI ora della finestra.
    """
    if not evo.get("windows"):
        return "Nessuna finestra di instabilità significativa individuata (CAPE concorde con almeno metà degli altri indici disponibili)."
    parts = []
    for w in evo["windows"]:
        vals = w.get("vals", [])
        if w["duration_h"] <= 3:
            parts.append(
                f"instabilità dalle {w['start']} alle {w['end']} ({w['duration_h']}h) "
                f"— picco {w.get('peak_cape_window', w['cape_avg']):.0f} J/kg "
                f"alle {w.get('peak_hour', w['start'])}"
            )
        else:
            punti = ", ".join(f"{t}={v:.0f}" for t, v in vals)
            parts.append(
                f"instabilità dalle {w['start']} alle {w['end']} "
                f"({w['duration_h']}h, {w['trend']}): {punti} J/kg"
            )
    peak_txt = (
        f" Picco assoluto {evo['peak_cape']:.0f} J/kg alle {evo['peak_time']}."
        if evo.get("peak_time") else ""
    )
    return "; ".join(parts) + "." + peak_txt

def _format_param_windows(
    windows: List[List[Tuple[str, float]]], label: str, unit: str, fmt: str = ".0f"
) -> List[str]:
    """
    Formattazione comune (pioggia, vento): durata <=3h → intervallo + solo picco;
    durata >=4h → intervallo + valore di OGNI ora.
    """
    lines = []
    for vals in windows:
        duration = _duration_hours_from_times(vals)
        start_t, end_t = vals[0][0], vals[-1][0]
        peak_t, peak_v = max(vals, key=lambda x: x[1])
        if duration <= 3:
            lines.append(
                f"{label} dalle {start_t} alle {end_t} ({duration}h) — "
                f"picco {peak_v:{fmt}}{unit} alle {peak_t}"
            )
        else:
            punti = ", ".join(f"{t}={v:{fmt}}{unit}" for t, v in vals)
            lines.append(f"{label} dalle {start_t} alle {end_t} ({duration}h): {punti}")
    return lines


def rain_evolution(hourly: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Finestre orarie con pioggia >= soglia ARPAL Gialla (ARPAL_RAIN_1H_GIALLO,
    10 mm/h) — la soglia ufficiale più bassa di attenzione oraria in Liguria.
    """
    windows: List[List[Tuple[str, float]]] = []
    cur: List[Tuple[str, float]] = []
    for h in hourly:
        t = h.get("time", "??:??")
        p = float(h.get("precip") or 0)
        if p >= thresholds.ARPAL_RAIN_1H_GIALLO:
            cur.append((t, p))
        else:
            if cur:
                windows.append(cur)
                cur = []
    if cur:
        windows.append(cur)
    return {"windows": windows}


def wind_evolution(hourly: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Finestre orarie con raffiche >= soglia ARPAL Gialla costiera
    (ARPAL_WIND_COAST_GIALLO, 40 km/h).
    """
    windows: List[List[Tuple[str, float]]] = []
    cur: List[Tuple[str, float]] = []
    for h in hourly:
        t = h.get("time", "??:??")
        g = float(h.get("wind_gust") or 0)
        if g >= thresholds.ARPAL_WIND_COAST_GIALLO:
            cur.append((t, g))
        else:
            if cur:
                windows.append(cur)
                cur = []
    if cur:
        windows.append(cur)
    return {"windows": windows}


def format_rain_evolution(evo: Dict[str, Any]) -> str:
    windows = evo.get("windows", [])
    if not windows:
        return ""
    return "; ".join(_format_param_windows(windows, "Pioggia significativa", " mm/h", ".1f")) + "."


def format_wind_evolution(evo: Dict[str, Any]) -> str:
    windows = evo.get("windows", [])
    if not windows:
        return ""
    return "; ".join(_format_param_windows(windows, "Vento sostenuto", " km/h", ".0f")) + "."

def upper_level_temperature_anomaly(
    params: Dict[str, Any],
    month: int,
) -> Optional[Dict[str, Any]]:
    """
    Confronta T_500hPa (e, se disponibile, T_850hPa) con la climatologia
    mensile indicativa (config.T500_CLIMATOLOGY_C / T850_CLIMATOLOGY_C).

    -20°C a 500hPa è normale a gennaio, ma indica un'avvezione fredda molto
    marcata a luglio/agosto: lo stesso numero ha significato opposto a seconda
    del mese, va sempre letto come scarto dalla norma del periodo, non come
    valore assoluto isolato.

    ATTENZIONE: la climatologia usata qui è un riferimento INDICATIVO (vedi nota
    in config.py), non una soglia "certificata" nello stesso senso di ARPAL/SPC.

    Ritorna None se il dato o l'anomalia non sono rilevanti (sotto soglia).
    """
    from config import (
        T500_CLIMATOLOGY_C, T850_CLIMATOLOGY_C,
        TEMP_ALOFT_ANOMALY_NOTABLE, TEMP_ALOFT_ANOMALY_SIGNIFICANT,
        TEMP_ALOFT_ANOMALY_EXCEPTIONAL,
    )

    t500 = params.get("T_500hPa")
    if t500 is None:
        return None
    t500 = float(t500)
    clima_500 = T500_CLIMATOLOGY_C.get(month)
    if clima_500 is None:
        return None
    anomaly_500 = t500 - clima_500

    t850 = params.get("T_850hPa")
    clima_850 = T850_CLIMATOLOGY_C.get(month)
    anomaly_850 = (
        float(t850) - clima_850
        if (t850 is not None and clima_850 is not None) else None
    )

    abs_anom = abs(anomaly_500)
    if abs_anom >= TEMP_ALOFT_ANOMALY_EXCEPTIONAL:
        livello = "eccezionale"
    elif abs_anom >= TEMP_ALOFT_ANOMALY_SIGNIFICANT:
        livello = "significativa"
    elif abs_anom >= TEMP_ALOFT_ANOMALY_NOTABLE:
        livello = "degna di nota"
    else:
        return None  # nella norma del mese: nessuna segnalazione

    verso = "fredda" if anomaly_500 < 0 else "calda"
    desc = (
        f"Avvezione {verso} in quota {livello}: T 500hPa {t500:.1f}°C contro una "
        f"norma climatologica del mese di circa {clima_500:.1f}°C "
        f"(anomalia {anomaly_500:+.1f}°C)"
    )
    if anomaly_850 is not None:
        desc += f"; a 850hPa {t850:.1f}°C vs norma {clima_850:.1f}°C ({anomaly_850:+.1f}°C)"

    return {
        "anomaly_500": round(anomaly_500, 1),
        "anomaly_850": round(anomaly_850, 1) if anomaly_850 is not None else None,
        "level": livello,
        "sign": verso,
        "desc": desc,
    }

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

def convection_probability(params):
    cape = max(
        params.get("SBCAPE", 0),
        params.get("MUCAPE", 0),
        params.get("MLCAPE", 0)
    )

    shear = params.get("shear_0_6", 0) or 0
    cin = abs(params.get("CIN", 0) or 0)
    pwat = params.get("PWAT", 0)

    prob = 0.0

    if cape >= 300:
        prob += 0.25

    if cape >= 1000:
        prob += 0.20

    if shear >= 15:
        prob += 0.20

    if shear >= 25:
        prob += 0.20

    if cin <= 25:
        prob += 0.10

    if pwat >= 30:
        prob += 0.05

    return round(min(prob, 1.0), 2)
