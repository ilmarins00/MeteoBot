import time
import hmac
import hashlib
import requests
import json
import os
import math
import io
import re
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
from scipy.interpolate import interp1d
import matplotlib
matplotlib.use('Agg')  # Backend non-interattivo per server
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Fuso orario italiano (gestisce automaticamente ora solare/legale)
TZ_ROME = ZoneInfo("Europe/Rome")

def estrai_pressione_hpa(dati_device):
    """Estrae la pressione in hPa dalla risposta Tuya con fallback su più chiavi."""
    candidate_keys = [
        "atmospheric_pressture",
        "atmospheric_pressure",
        "pressure",
        "barometer",
        "pressure_abs",
    ]
    for key in candidate_keys:
        value = dati_device.get(key)
        if isinstance(value, (int, float)) and value > 0:
            if value > 20000:
                return value / 100.0
            if value > 2000:
                return value / 10.0
            return float(value)
    return None

# NEW (add these):
from config import (
    TUYA_ACCESS_ID as ACCESS_ID,
    TUYA_ACCESS_SECRET as ACCESS_SECRET,
    TUYA_ENDPOINT as ENDPOINT,
    TUYA_DEVICE_ID as DEVICE_ID,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_IDS as LISTA_CHAT,
    FILE_STORICO,
    FILE_MEMORIA,
    FILE_SBCAPE,
    thresholds,
    LATITUDE,
    LONGITUDE,
    ELEVATION,
    TIMEZONE
)
from utils import extract_pressure_hpa
# NOTE: pressure extraction implemented here as `estrai_pressione_hpa`

def carica_storico():
    """Carica lo storico delle ultime 24h di misurazioni."""
    if os.path.exists(FILE_STORICO):
        try:
            with open(FILE_STORICO, "r") as f:
                return json.load(f)
        except:
            pass
    return []

def salva_storico(storico):
    """Salva lo storico, mantenendo solo le ultime 24h."""
    now = datetime.now(TZ_ROME)
    cutoff_dt = now - timedelta(hours=24)
    filtered = []
    for s in storico:
        ts = s.get("ts")
        if not ts:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=TZ_ROME)
            if ts_dt >= cutoff_dt:
                filtered.append(s)
        except Exception:
            continue
    with open(FILE_STORICO, "w") as f:
        json.dump(filtered, f)

def calcola_tendenza_barometrica(storico, pressione_attuale):
    """Calcola la tendenza barometrica nelle ultime 3h.
    Restituisce (simbolo, delta_hPa, descrizione)."""
    now = datetime.now(TZ_ROME)
    tre_ore_fa_dt = now - timedelta(hours=3)

    # Filtra misurazioni delle ultime 3h e parsifica i timestamp
    recenti = []
    for s in storico:
        ts = s.get("ts")
        if not ts or "pressione" not in s:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=TZ_ROME)
            if ts_dt >= tre_ore_fa_dt:
                recenti.append((ts_dt, s))
        except Exception:
            continue

    if len(recenti) < 2:
        return "➡️", 0, "Dati insufficienti"

    # Ordina per timestamp e prendi il valore più vecchio nelle ultime 3h
    recenti.sort(key=lambda x: x[0])
    pressione_3h = recenti[0][1]["pressione"]
    delta = pressione_attuale - pressione_3h
    
    if delta >= 3:
        return "⬆️", delta, "In forte aumento"
    elif delta >= 1:
        return "↗️", delta, "In aumento"
    elif delta > -1:
        return "➡️", delta, "Stabile"
    elif delta > -3:
        return "↘️", delta, "In calo"
    else:
        return "⬇️", delta, "In forte calo"

 

def genera_grafico_24h(storico):
    """Genera un grafico a 2 riquadri delle ultime 24h.
    Riquadro 1 (base): Temperatura, Umidità, Punto di rugiada, Pioggia 1h, Pioggia 24h, Raffica.
    Riquadro 2 (tecnico): Pressione MSL, API, SBCAPE, MUCAPE, Bulk Shear.
    Restituisce un buffer BytesIO con l'immagine PNG, oppure None."""
    if len(storico) < 3:
        return None

    try:
        timestamps = []
        temperature = []
        umidita = []
        dew_points = []
        piogge_1h = []
        piogge_24h = []
        raffiche = []
        pressioni = []
        api_values = []
        sbcape_values = []
        mucape_values = []
        shear_values = []

        for s in storico:
            try:
                ts = datetime.fromisoformat(s["ts"])
                timestamps.append(ts)
                temperature.append(s.get("temp"))
                umidita.append(s.get("umidita"))
                dew_points.append(s.get("dew_point"))
                piogge_1h.append(s.get("pioggia_1h", 0))
                piogge_24h.append(s.get("pioggia_24h", 0))
                raffiche.append(s.get("raffica"))
                pressioni.append(s.get("pressione"))
                api_values.append(s.get("api"))
                sbcape_values.append(s.get("sbcape"))
                mucape_values.append(s.get("mucape"))
                shear_values.append(s.get("bulk_shear"))
            except Exception:
                continue

        if len(timestamps) < 3:
            return None

        # Helper: filtra coppie (ts, val) non-None
        def _filt(ts_list, val_list):
            return list(zip(*[(t, v) for t, v in zip(ts_list, val_list) if isinstance(v, (int, float))])) or ([], [])

        fig, (ax_base, ax_tech) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
        fig.suptitle('Stazione Meteo La Spezia — Foce (24h)', fontsize=14, fontweight='bold')

        # ==================== RIQUADRO 1 — DATI BASE ====================
        # Asse sinistro: Temperatura (°C), Punto di rugiada (°C)
        ts_t, vals_t = _filt(timestamps, temperature)
        ts_d, vals_d = _filt(timestamps, dew_points)
        if ts_t:
            ax_base.plot(ts_t, vals_t, color='#e74c3c', linewidth=2, marker='.', markersize=4, label='Temperatura (°C)')
        if ts_d:
            ax_base.plot(ts_d, vals_d, color='#1abc9c', linewidth=1.5, linestyle='--', marker='.', markersize=3, label='Punto rugiada (°C)')
        ax_base.set_ylabel('°C', fontsize=10)
        ax_base.grid(True, alpha=0.3)
        ax_base.tick_params(labelsize=8)

        # Asse destro 1: Umidità (%)
        ax_base_rh = ax_base.twinx()
        ts_u, vals_u = _filt(timestamps, umidita)
        if ts_u:
            ax_base_rh.plot(ts_u, vals_u, color='#9b59b6', linewidth=1.3, alpha=0.7, label='Umidità (%)')
        ax_base_rh.set_ylabel('Umidità (%)', fontsize=9, color='#9b59b6')
        ax_base_rh.tick_params(axis='y', labelcolor='#9b59b6', labelsize=8)
        ax_base_rh.set_ylim(0, 105)

        # Barre pioggia (1h e 24h) sovrapposte
        ax_base_rain = ax_base.twinx()
        ax_base_rain.spines['right'].set_position(('axes', 1.10))
        ax_base_rain.bar(timestamps, piogge_24h, width=0.035, color='#2980b9', alpha=0.3, label='Pioggia 24h (mm)')
        ax_base_rain.bar(timestamps, piogge_1h, width=0.025, color='#2ecc71', alpha=0.7, label='Pioggia 1h (mm)')
        ax_base_rain.set_ylabel('Pioggia (mm)', fontsize=9, color='#2ecc71')
        ax_base_rain.tick_params(axis='y', labelcolor='#2ecc71', labelsize=8)

        # Raffiche (km/h) come scatter
        ax_base_wind = ax_base.twinx()
        ax_base_wind.spines['right'].set_position(('axes', 1.20))
        ts_r, vals_r = _filt(timestamps, raffiche)
        if ts_r:
            ax_base_wind.scatter(ts_r, vals_r, color='#e67e22', s=14, marker='^', alpha=0.8, label='Raffica (km/h)', zorder=5)
            ax_base_wind.plot(ts_r, vals_r, color='#e67e22', linewidth=1, alpha=0.4)
        ax_base_wind.set_ylabel('Raffica (km/h)', fontsize=9, color='#e67e22')
        ax_base_wind.tick_params(axis='y', labelcolor='#e67e22', labelsize=8)

        # Legenda riquadro 1
        lines_1 = []
        labels_1 = []
        for ax_tmp in [ax_base, ax_base_rh, ax_base_rain, ax_base_wind]:
            h, l = ax_tmp.get_legend_handles_labels()
            lines_1.extend(h)
            labels_1.extend(l)
        if lines_1:
            ax_base.legend(lines_1, labels_1, loc='upper left', fontsize=7, ncol=3, framealpha=0.7)

        # ==================== RIQUADRO 2 — DATI TECNICI ====================
        # Asse sinistro: Pressione MSL (hPa)
        ts_p, vals_p = _filt(timestamps, pressioni)
        if ts_p:
            ax_tech.plot(ts_p, vals_p, color='#3498db', linewidth=2, marker='.', markersize=4, label='Pressione MSL (hPa)')
        ax_tech.set_ylabel('Pressione (hPa)', fontsize=10, color='#3498db')
        ax_tech.tick_params(axis='y', labelcolor='#3498db', labelsize=8)
        ax_tech.grid(True, alpha=0.3)

        # Asse destro 1: API (mm)
        ax_tech_api = ax_tech.twinx()
        ts_a, vals_a = _filt(timestamps, api_values)
        if ts_a:
            ax_tech_api.plot(ts_a, vals_a, color='#16a085', linewidth=1.8, marker='.', markersize=3, label='API (mm)')
        ax_tech_api.set_ylabel('API (mm)', fontsize=9, color='#16a085')
        ax_tech_api.tick_params(axis='y', labelcolor='#16a085', labelsize=8)

        # Asse destro 2: SBCAPE + MUCAPE (J/kg)
        ax_tech_cape = ax_tech.twinx()
        ax_tech_cape.spines['right'].set_position(('axes', 1.10))
        ts_sb, vals_sb = _filt(timestamps, sbcape_values)
        ts_mu, vals_mu = _filt(timestamps, mucape_values)
        if ts_sb:
            ax_tech_cape.plot(ts_sb, vals_sb, color='#f39c12', linewidth=1.5, alpha=0.85, label='SBCAPE (J/kg)')
        if ts_mu:
            ax_tech_cape.plot(ts_mu, vals_mu, color='#c0392b', linewidth=1.5, alpha=0.85, linestyle='--', label='MUCAPE (J/kg)')
        ax_tech_cape.set_ylabel('CAPE (J/kg)', fontsize=9, color='#f39c12')
        ax_tech_cape.tick_params(axis='y', labelcolor='#f39c12', labelsize=8)

        # Asse destro 3: Bulk Shear (m/s)
        ax_tech_shear = ax_tech.twinx()
        ax_tech_shear.spines['right'].set_position(('axes', 1.20))
        ts_sh, vals_sh = _filt(timestamps, shear_values)
        if ts_sh:
            ax_tech_shear.plot(ts_sh, vals_sh, color='#8e44ad', linewidth=1.3, alpha=0.8, label='Shear (m/s)')
        ax_tech_shear.set_ylabel('Shear (m/s)', fontsize=9, color='#8e44ad')
        ax_tech_shear.tick_params(axis='y', labelcolor='#8e44ad', labelsize=8)

        # Legenda riquadro 2
        lines_2 = []
        labels_2 = []
        for ax_tmp in [ax_tech, ax_tech_api, ax_tech_cape, ax_tech_shear]:
            h, l = ax_tmp.get_legend_handles_labels()
            lines_2.extend(h)
            labels_2.extend(l)
        if lines_2:
            ax_tech.legend(lines_2, labels_2, loc='upper left', fontsize=7, ncol=3, framealpha=0.7)

        # Formattazione asse X
        ax_tech.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=TZ_ROME))
        ax_tech.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        ax_tech.set_xlabel('Ora', fontsize=10)
        plt.xticks(rotation=45)

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print(f"Errore generazione grafico: {e}")
        return None

def classifica_massa_aria(temp, dew_point, pressione_msl, mese):
    """Classifica la massa d'aria secondo Bergeron (1928) con parametro primario θe.

    Metodo scientifico:
      1. Calcolo θe con formula di Bolton (1980):
         θe = T × exp[(Lv × r) / (Cp × T_LCL)]
         dove T_LCL approssimato con Espy/Bolton.
      2. Classificazione primaria su θe (contenuto energetico totale):
         - Soglie da Ahrens & Henson, "Meteorology Today" (13th ed.)
         - Adattate per bacino Mediterraneo nord-occidentale (Lionello et al., 2006)
      3. Discriminante continentale/marittima su spread T-Td (Stull, 2017)
      4. Anomalia termica rispetto a medie ARPAL 1991-2020 per sottoclassificazione.

    Riferimenti:
      - Bolton D. (1980), Mon. Wea. Rev., 108, 1046-1053
      - Bergeron T. (1928), Geofysiske Publikasjoner, 5(6)
      - Ahrens C.D., Henson R. (2021), Meteorology Today, 13th ed.
      - Stull R. (2017), Practical Meteorology, Univ. of British Columbia
      - Lionello P. et al. (2006), Mediterranean Climate Variability, Elsevier
    """
    # Medie climatologiche mensili La Spezia (°C) - fonte ARPAL 1991-2020
    t_media_clima = {
        1: 7.5,  2: 8.2,  3: 10.8, 4: 13.8,
        5: 17.8, 6: 21.5, 7: 24.2, 8: 24.0,
        9: 20.5, 10: 16.2, 11: 11.8, 12: 8.5
    }

    t_norma = t_media_clima.get(mese, 15.0)
    anomalia = temp - t_norma

    # --- CALCOLO θe (Bolton 1980) ---
    # Pressione di vapore (Magnus-Tetens): e = 6.112 × exp(17.67 × Td / (Td + 243.5))
    # Mixing ratio: r = ε × e / (P - e),  ε = 0.622
    # T_LCL (Bolton 1980): T_LCL = 1 / (1/(Td-56) + ln(T/Td)/800) + 56
    # θe = T_K × (1000/P)^(0.2854(1-0.28r)) × exp(r(1+0.81r)(3376/T_LCL - 2.54))
    try:
        T_K = temp + 273.15
        Td_K = dew_point + 273.15
        e_vapor = 6.112 * math.exp(17.67 * dew_point / (dew_point + 243.5))
        r = 0.622 * e_vapor / (pressione_msl - e_vapor)  # mixing ratio kg/kg

        # T_LCL (Bolton 1980, eq. 15)
        T_LCL = 1.0 / (1.0 / (Td_K - 56) + math.log(T_K / Td_K) / 800.0) + 56.0

        # θe (Bolton 1980, eq. 43)
        theta_e = T_K * (1000.0 / pressione_msl) ** (0.2854 * (1 - 0.28 * r)) \
                  * math.exp(r * (1 + 0.81 * r) * (3376.0 / T_LCL - 2.54))
        theta_e_C = theta_e - 273.15  # In °C per soglie
    except (ValueError, ZeroDivisionError, OverflowError):
        theta_e_C = temp + 10  # Fallback conservativo
        r = 0

    # Spread T - Td (indicatore marittimo/continentale, Stull 2017)
    spread = temp - dew_point

    # --- CLASSIFICAZIONE BERGERON (soglie θe) ---
    # θe è il parametro primario: conserva l'identità della massa d'aria durante
    # i movimenti verticali e orizzontali (è quasi-conservativa).
    #
    # Soglie θe per il Mediterraneo (Lionello et al. 2006, adattate):
    #   cA/mA:  θe < 10°C    (artica)
    #   cP:     θe 10-25°C   (polare continentale, spread > 8°C)
    #   mP:     θe 10-30°C   (polare marittima, spread ≤ 8°C)
    #   mTr:    θe 30-45°C   (transizione mediterranea)
    #   mT:     θe 40-65°C   (tropicale marittima, spread ≤ 10°C)
    #   cT:     θe 35-55°C   (tropicale continentale, spread > 15°C)

    if theta_e_C < 5:
        # Aria artica
        if spread > 10:
            tipo, nome, emoji = "cA", "Continentale Artica", "🧊"
            desc = "Aria gelida e secca di origine artico-continentale"
        else:
            tipo, nome, emoji = "mA", "Marittima Artica", "🏔️"
            desc = "Aria gelida di origine artica, moderata dal transito marittimo"
    elif theta_e_C < 15:
        # Aria polare fredda
        if spread > 8:
            tipo, nome, emoji = "cP", "Continentale Polare", "❄️"
            desc = "Aria fredda e secca di origine continentale (Est Europa/Russia)"
        else:
            tipo, nome, emoji = "mP", "Marittima Polare", "🌊"
            desc = "Aria fredda e umida dall'Atlantico settentrionale"
    elif theta_e_C < 30:
        # Aria polare modificata / transizione
        if spread > 10:
            tipo, nome, emoji = "cP", "Continentale Polare modificata", "🌥️"
            desc = "Massa polare continentale in fase di riscaldamento"
        elif anomalia < -2:
            tipo, nome, emoji = "mP", "Marittima Polare", "🌊"
            desc = "Aria fresca e umida di origine atlantica"
        else:
            tipo, nome, emoji = "mP/mTr", "Polare in transizione", "🌤️"
            desc = "Massa polare in riscaldamento sul Mediterraneo"
    elif theta_e_C < 45:
        # Zona di transizione / aria mediterranea
        if spread > 15:
            tipo, nome, emoji = "cT", "Continentale Tropicale", "🏜️"
            desc = "Aria calda e secca di origine sahariana/nordafricana"
        elif spread > 8 and anomalia > 3:
            tipo, nome, emoji = "cT/mT", "Subtropicale secca", "☀️"
            desc = "Massa d'aria subtropicale relativamente secca"
        elif anomalia > 2:
            tipo, nome, emoji = "mT/mTr", "Subtropicale marittima", "⛅"
            desc = "Aria tiepida subtropicale, attenuata dal Mediterraneo"
        else:
            tipo, nome, emoji = "mTr", "Marittima Mediterranea", "🌤️"
            desc = "Aria temperata stazionaria sul bacino mediterraneo"
    else:
        # θe ≥ 45°C: aria tropicale
        if spread > 15:
            tipo, nome, emoji = "cT", "Continentale Tropicale", "🏜️"
            desc = "Aria molto calda e secca di origine sahariana"
        elif spread > 10:
            tipo, nome, emoji = "cT/mT", "Tropicale mista", "🌅"
            desc = "Massa tropicale con componente continentale"
        else:
            tipo, nome, emoji = "mT", "Marittima Tropicale", "🌴"
            desc = "Aria calda e umida dal Mediterraneo meridionale o subtropicale"

    return {
        "tipo": tipo,
        "nome": nome,
        "emoji": emoji,
        "desc": desc,
        "theta_e": round(theta_e_C, 1),
        "anomalia": round(anomalia, 1),
        "spread": round(spread, 1)
    }


def valuta_instabilita_convettiva(sbcape, mucape, cin, li_value, bulk_shear, severe_score=0):
    """Valutazione ingredient-based del rischio convettivo su scala 0-12."""
    sbcape_f = float(sbcape or 0)
    mucape_f = float(mucape or 0)
    max_cape = max(sbcape_f, mucape_f)
    cin_abs = abs(float(cin or 0))
    shear = float(bulk_shear or 0)
    li = li_value if isinstance(li_value, (int, float)) else None

    if max_cape < 300:
        cape_score = 0.0
    elif max_cape < 800:
        cape_score = 1.0
    elif max_cape < 1500:
        cape_score = 2.0
    elif max_cape < 2500:
        cape_score = 3.0
    else:
        cape_score = 4.0

    if mucape_f >= 1200 and mucape_f >= 0.9 * max_cape:
        cape_score += 0.5

    if cin_abs > 250:
        cin_score = 0.0
    elif cin_abs > 175:
        cin_score = 0.5
    elif cin_abs >= 25:
        cin_score = 1.5
    else:
        cin_score = 1.0

    if li is None:
        li_score = 0.0
    elif li <= -8:
        li_score = 3.0
    elif li <= -6:
        li_score = 2.2
    elif li <= -4:
        li_score = 1.5
    elif li <= -2:
        li_score = 0.8
    else:
        li_score = 0.0

    if shear < 8:
        shear_score = 0.0
    elif shear < 12:
        shear_score = 1.0
    elif shear < 18:
        shear_score = 2.0
    elif shear < 25:
        shear_score = 3.0
    else:
        shear_score = 3.5

    synergy_score = 0.0
    if max_cape >= 1500 and shear >= 15:
        synergy_score += 1.0
    if li is not None and li <= -5 and cin_abs <= 150:
        synergy_score += 0.8
    if max_cape >= 2500 and shear >= 20 and li is not None and li <= -6:
        synergy_score += 1.2

    score = cape_score + cin_score + li_score + shear_score + synergy_score
    if severe_score:
        score = max(score, min(float(severe_score), 12.0))
    score = round(min(score, 12.0), 1)

    warning = None
    level = "basso"
    event_label = "Instabilità convettiva"

    if score >= 10.5:
        warning = "⚠️⚡ AVVISO: TEMPORALI SEVERI"
        level = "molto_alto"
        event_label = "Temporali severi"
    elif score >= 8.0:
        warning = "⚡ AVVISO: RISCHIO FORTI TEMPORALI"
        level = "alto"
        event_label = "Rischio forti temporali"
    elif score >= 5.5:
        warning = "⛈️ AVVISO: INSTABILITÀ CONVETTIVA MARCATA"
        level = "moderato"
        event_label = "Instabilità convettiva marcata"

    return {
        "score": score,
        "level": level,
        "warning": warning,
        "event_label": event_label,
        "event_trigger": score >= 8.0,
        "max_cape": max_cape,
        "cin_abs": cin_abs,
        "li": li,
        "shear": shear,
    }


# ============================================================================
# MODULO SBCAPE/MUCAPE — integrato da calcola_SBCAPE.py
# ============================================================================

# Costanti fisiche (termodinamica atmosferica)
_RD = 287.05      # J/(kg·K) - costante gas per aria secca
_RV = 461.5       # J/(kg·K) - costante gas per vapore acqueo
_CP = 1005.0      # J/(kg·K) - calore specifico aria a pressione costante
_LV = 2.5e6       # J/kg     - calore latente di vaporizzazione
_G  = 9.80665     # m/s²     - accelerazione di gravità
_EPSILON = 0.622  # Rd/Rv

# Cache globale per API Open-Meteo
_API_CACHE = {}
_CACHE_DURATION = 600  # 10 minuti


def fetch_station_data_with_retry(max_retries=3):
    """Legge i dati reali dalla stazione meteo Tuya con retry logic."""
    if not ACCESS_ID or not ACCESS_SECRET or not DEVICE_ID:
        print("✗ TUYA non configurato: verifica TUYA_ACCESS_ID / TUYA_ACCESS_SECRET / TUYA_DEVICE_ID")
        return None
    for attempt in range(max_retries):
        try:
            token_url = "/v1.0/token?grant_type=1"
            r = requests.get(ENDPOINT + token_url,
                             headers=get_auth_headers("GET", token_url), timeout=10).json()
        except Exception as e:
            print(f"✗ Errore connessione Tuya (token, attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue

        if not r or not r.get("success") or "result" not in r or "access_token" not in r["result"]:
            print(f"✗ Errore Token Tuya (attempt {attempt+1}): {r}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue

        token = r["result"]["access_token"]
        status_url = f"/v1.0/devices/{DEVICE_ID}/status"
        try:
            res = requests.get(ENDPOINT + status_url,
                               headers=get_auth_headers("GET", status_url, token), timeout=10).json()
        except Exception as e:
            print(f"✗ Errore connessione Tuya (status, attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue

        if not res or not res.get("success") or "result" not in res:
            print(f"✗ Errore lettura device Tuya (attempt {attempt+1}): {res}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue

        d = {item['code']: item['value'] for item in res.get("result", [])}
        station_data = {
            'temperature': d.get('temp_current_external', 0) / 10,
            'dewpoint': d.get('dew_point_temp', 0) / 10,
            'pressure': extract_pressure_hpa(d) or 1013.0,
            'humidity': d.get('humidity_outdoor', 0),
            'wind_speed': d.get('windspeed_avg', 0) / 10,
            'wind_gust': d.get('windspeed_gust', 0) / 10,
        }

        if (station_data['temperature'] < -50 or station_data['temperature'] > 60 or
                station_data['humidity'] < 0 or station_data['humidity'] > 100 or
                station_data['pressure'] < 900 or station_data['pressure'] > 1050):
            print(f"⚠️  Dati stazione anomali (attempt {attempt+1})")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None

        print(f"✓ Dati stazione Tuya ricevuti: T={station_data['temperature']:.1f}°C, "
              f"Td={station_data['dewpoint']:.1f}°C, P={station_data['pressure']:.1f}hPa, "
              f"RH={station_data['humidity']}%")
        return station_data
    return None


def fetch_profile_cached():
    """Scarica profilo verticale da Open-Meteo con cache.
    Usa AROME France (Météo-France, 2.5 km) con fallback best_match."""
    global _API_CACHE

    now = time.time()
    if 'open_meteo' in _API_CACHE and now - _API_CACHE['open_meteo_time'] < _CACHE_DURATION:
        print(f"✓ Usando cache Open-Meteo (età: {int(now - _API_CACHE['open_meteo_time'])}s)")
        return _API_CACHE['open_meteo']

    url = "https://api.open-meteo.com/v1/forecast"

    pressure_levels_temp = [
        "temperature_1000hPa", "temperature_950hPa", "temperature_925hPa",
        "temperature_900hPa", "temperature_850hPa", "temperature_800hPa",
        "temperature_750hPa", "temperature_700hPa", "temperature_650hPa",
        "temperature_600hPa", "temperature_550hPa", "temperature_500hPa",
        "temperature_400hPa", "temperature_300hPa", "temperature_200hPa"
    ]
    pressure_levels_rh = [
        "relative_humidity_1000hPa", "relative_humidity_950hPa", "relative_humidity_925hPa",
        "relative_humidity_900hPa", "relative_humidity_850hPa", "relative_humidity_800hPa",
        "relative_humidity_750hPa", "relative_humidity_700hPa", "relative_humidity_650hPa",
        "relative_humidity_600hPa", "relative_humidity_550hPa", "relative_humidity_500hPa"
    ]
    pressure_levels_wind = ["windspeed_10m", "windspeed_80m", "windspeed_120m"]

    hourly_vars = ",".join(pressure_levels_temp + pressure_levels_rh + pressure_levels_wind) + ",dew_point_2m,relative_humidity_2m"

    base_params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "temperature_2m,relative_humidity_2m,pressure_msl,dew_point_2m,windspeed_10m,winddirection_10m",
        "hourly": hourly_vars,
        "timezone": "UTC"
    }

    # 1. AROME France (Météo-France, 2.5 km, ottimo per Mediterraneo)
    try:
        params_arome = {**base_params, "models": "meteofrance_arome_france"}
        r = requests.get(url, params=params_arome, timeout=15)
        r.raise_for_status()
        data = r.json()
        hourly = data.get("hourly", {})
        test_key = "temperature_850hPa"
        if test_key in hourly and any(v is not None for v in hourly[test_key]):
            data['_model_used'] = 'AROME France (2.5km)'
            _API_CACHE['open_meteo'] = data
            _API_CACHE['open_meteo_time'] = now
            print("✓ Fetch Open-Meteo riuscito - modello AROME France (2.5km)")
            return data
        else:
            print("⚠️  AROME France ha restituito dati vuoti, passo al fallback")
    except Exception as e:
        print(f"⚠️  AROME France non disponibile ({e}), passo al fallback")

    # 2. Fallback best_match
    try:
        r = requests.get(url, params=base_params, timeout=15)
        r.raise_for_status()
        data = r.json()
        data['_model_used'] = 'best_match (fallback)'
        _API_CACHE['open_meteo'] = data
        _API_CACHE['open_meteo_time'] = now
        print("✓ Fetch Open-Meteo riuscito - modello default (best_match)")
        return data
    except Exception as e:
        print(f"Errore fetch Open-Meteo: {e}")
        return None


# --- Funzioni termodinamiche ---

def vapor_pressure(T_celsius):
    """Pressione di vapore saturo (hPa) — Bolton (1980)."""
    return 6.112 * np.exp(17.67 * T_celsius / (T_celsius + 243.5))


def mixing_ratio(e, p):
    """Rapporto di miscelanza (kg/kg) da pressione di vapore e pressione totale."""
    return _EPSILON * e / (p - e)


def virtual_temperature(T_kelvin, q):
    """Temperatura virtuale (K) da temperatura e rapporto di miscelanza."""
    return T_kelvin * (1 + q / _EPSILON) / (1 + q)


def dewpoint_to_mixing_ratio(Td_celsius, p_hPa):
    """Rapporto di miscelanza dal punto di rugiada."""
    es = vapor_pressure(Td_celsius)
    return mixing_ratio(es, p_hPa)


def lcl_pressure(T_kelvin, Td_kelvin, p_hPa):
    """Pressione al LCL (hPa) — approssimazione di Bolton."""
    Tl = 1 / (1 / (Td_kelvin - 56) + np.log(T_kelvin / Td_kelvin) / 800) + 56
    theta = T_kelvin * (1000 / p_hPa) ** (_RD / _CP)
    return 1000 * (Tl / theta) ** (_CP / _RD)


def moist_adiabatic_lapse_rate(T_kelvin, p_hPa):
    """Lapse rate adiabatico saturo (K/Pa)."""
    es = vapor_pressure(T_kelvin - 273.15)
    ws = mixing_ratio(es, p_hPa)
    numerator = 1 + _LV * ws / (_RD * T_kelvin)
    denominator = 1 + _EPSILON * _LV * _LV * ws / (_CP * _RD * T_kelvin * T_kelvin)
    return (_RD * T_kelvin / (_CP * p_hPa)) * (numerator / denominator)


def lift_parcel(T_start_K, p_start_hPa, q_start, p_levels_hPa):
    """Solleva una particella (secca fino al LCL, satura oltre).
    Restituisce (T_parcel[], p_lcl)."""
    T_parcel = np.zeros(len(p_levels_hPa))
    T_parcel[0] = T_start_K

    es_start = vapor_pressure(T_start_K - 273.15)
    e_start = q_start * p_start_hPa / (_EPSILON + q_start)
    e_start = min(e_start, es_start)

    if e_start > 0:
        Td_start = 243.5 * np.log(e_start / 6.112) / (17.67 - np.log(e_start / 6.112))
        p_lcl = lcl_pressure(T_start_K, Td_start + 273.15, p_start_hPa)
    else:
        p_lcl = p_start_hPa / 2

    for i in range(1, len(p_levels_hPa)):
        p_lower = p_levels_hPa[i - 1]
        p_upper = p_levels_hPa[i]

        if p_lower >= p_lcl and p_upper >= p_lcl:
            T_parcel[i] = T_parcel[i - 1] * (p_upper / p_lower) ** (_RD / _CP)
        elif p_lower >= p_lcl and p_upper < p_lcl:
            T_at_lcl = T_parcel[i - 1] * (p_lcl / p_lower) ** (_RD / _CP)
            n_steps = 10
            p_range = np.linspace(p_lcl, p_upper, n_steps)
            T_temp = T_at_lcl
            for j in range(1, n_steps):
                dp = p_range[j] - p_range[j - 1]
                dT_dp = moist_adiabatic_lapse_rate(T_temp, p_range[j - 1])
                T_temp = T_temp + dT_dp * dp
            T_parcel[i] = T_temp
        else:
            n_steps = 5
            p_range = np.linspace(p_lower, p_upper, n_steps)
            T_temp = T_parcel[i - 1]
            for j in range(1, n_steps):
                dp = p_range[j] - p_range[j - 1]
                dT_dp = moist_adiabatic_lapse_rate(T_temp, p_range[j - 1])
                T_temp = T_temp + dT_dp * dp
            T_parcel[i] = T_temp

    return T_parcel, p_lcl


def calcola_cape_from_profile(T_parcel, p_env, T_env, RH_env, q_parcel_surface, p_lcl):
    """Calcola CAPE e CIN da profili di temperatura e umidità."""
    Tv_env = np.zeros(len(p_env))
    Tv_parcel = np.zeros(len(p_env))

    for i in range(len(p_env)):
        es_env = vapor_pressure(T_env[i] - 273.15)
        e_env = es_env * RH_env[i]
        q_env = mixing_ratio(e_env, p_env[i])
        Tv_env[i] = virtual_temperature(T_env[i], q_env)

        if p_env[i] <= p_lcl:
            es_parcel = vapor_pressure(T_parcel[i] - 273.15)
            q_parcel = mixing_ratio(es_parcel, p_env[i])
        else:
            q_parcel = q_parcel_surface
        Tv_parcel[i] = virtual_temperature(T_parcel[i], q_parcel)

    buoyancy = Tv_parcel - Tv_env

    lcl_idx = 0
    for i in range(len(p_env)):
        if p_env[i] <= p_lcl:
            lcl_idx = i
            break

    lfc_idx = None
    for i in range(max(1, lcl_idx), len(buoyancy)):
        if buoyancy[i] > 0 and buoyancy[i - 1] <= 0:
            lfc_idx = i
            break

    el_idx = None
    if lfc_idx is not None:
        for i in range(lfc_idx + 1, len(buoyancy)):
            if buoyancy[i] < 0:
                el_idx = i
                break
        if el_idx is None:
            el_idx = len(buoyancy) - 1

    cin = 0.0
    cape = 0.0
    if lfc_idx is not None:
        for i in range(1, lfc_idx):
            if buoyancy[i] < 0:
                Tv_avg = (Tv_env[i] + Tv_env[i - 1]) / 2
                dz = (_RD * Tv_avg / _G) * np.log(p_env[i - 1] / p_env[i])
                buoy_avg = (buoyancy[i] + buoyancy[i - 1]) / 2
                cin += _G * (buoy_avg / Tv_avg) * dz

        for i in range(lfc_idx + 1, el_idx + 1):
            if buoyancy[i] > 0 or buoyancy[i - 1] > 0:
                Tv_avg = (Tv_env[i] + Tv_env[i - 1]) / 2
                dz = (_RD * Tv_avg / _G) * np.log(p_env[i - 1] / p_env[i])
                buoy_avg = (buoyancy[i] + buoyancy[i - 1]) / 2
                if buoy_avg > 0:
                    cape += _G * (buoy_avg / Tv_avg) * dz

    return {
        'sbcape': cape,
        'cin': cin,
        'lfc_idx': lfc_idx,
        'el_idx': el_idx,
        'lfc_pressure': p_env[lfc_idx] if lfc_idx is not None else None,
        'el_pressure': p_env[el_idx] if el_idx is not None else None,
        'buoyancy': buoyancy
    }


def calcola_mucape(data, station_data, T_env, p_env, RH_env):
    """Calcola Most Unstable CAPE (MUCAPE) cercando la particella più instabile
    nei primi 300 hPa dalla superficie."""
    if station_data is None:
        return None

    p_surface = station_data['pressure']
    max_cape = 0
    mu_result = None

    for p_idx in range(len(p_env)):
        if p_env[p_idx] < p_surface - 300:
            break

        T_test = T_env[p_idx]
        RH_test = RH_env[p_idx]
        p_test = p_env[p_idx]

        es_test = vapor_pressure(T_test - 273.15)
        e_test = es_test * RH_test
        q_test = mixing_ratio(e_test, p_test)

        p_levels_above = p_env[p_idx:]
        T_levels_above = T_env[p_idx:]
        RH_levels_above = RH_env[p_idx:]

        T_parcel_mu, p_lcl_mu = lift_parcel(T_test, p_test, q_test, p_levels_above)
        result_mu = calcola_cape_from_profile(T_parcel_mu, p_levels_above, T_levels_above, RH_levels_above, q_test, p_lcl_mu)

        if result_mu['sbcape'] > max_cape:
            max_cape = result_mu['sbcape']
            mu_result = result_mu
            mu_result['mu_level'] = p_test

    return mu_result


def calcola_wind_shear(data, current_hour_idx, station_data):
    """Proxy wind shear 0-6 km (10 m → 120 m). Fortemente sottostimato."""
    try:
        hourly = data.get("hourly", {})
        if station_data and 'wind_speed' in station_data:
            u_surface = station_data['wind_speed'] / 3.6
        else:
            u_surface = hourly.get('windspeed_10m', [0])[current_hour_idx] / 3.6 if 'windspeed_10m' in hourly else 0
        u_120m = hourly.get('windspeed_120m', [0])[current_hour_idx] / 3.6 if 'windspeed_120m' in hourly else 0
        shear = abs(u_120m - u_surface)
        return {'surface_wind': u_surface, 'upper_wind': u_120m, 'bulk_shear': shear}
    except Exception:
        return None


def _validate_sbcape_results(results, T_surface_C):
    """Validazione fisica dei risultati SBCAPE."""
    warnings = []
    if results['sbcape'] > 6000:
        warnings.append(f"⚠️  SBCAPE molto elevato ({results['sbcape']:.0f} J/kg) - verifica dati")
    if results['sbcape'] > 1500 and T_surface_C < 10:
        warnings.append(f"⚠️  CAPE elevato con T bassa ({T_surface_C:.1f}°C) - situazione insolita")
    if results['cin'] < -500:
        warnings.append(f"⚠️  CIN molto forte ({results['cin']:.0f} J/kg) - convezione fortemente inibita")
    return warnings


def calcola_sbcape_advanced(data, station_data=None):
    """Calcola SBCAPE, MUCAPE, CIN e parametri convettivi avanzati.
    Profilo umidità reale, interpolazione cubica, MUCAPE, wind shear."""
    if not data:
        print("Errore: dati invalidi")
        return None

    try:
        hourly = data.get("hourly", {})

        # Ora corrente UTC
        current_hour_idx = 0
        if "time" in hourly:
            from datetime import timezone as _tz
            now_utc = datetime.now(_tz.utc)
            now_hour_str = now_utc.strftime("%Y-%m-%dT%H:")
            for i, time_str in enumerate(hourly["time"]):
                if time_str.startswith(now_hour_str):
                    current_hour_idx = i
                    break

        print(f"  Usando dati dell'ora: {hourly['time'][current_hour_idx] if 'time' in hourly else 'N/A'} (indice {current_hour_idx})")

        # Se l'ora corrente ha dati null, cerca l'ultima ora valida
        test_key = "temperature_850hPa"
        if (test_key in hourly and hourly[test_key] and
                len(hourly[test_key]) > current_hour_idx and
                hourly[test_key][current_hour_idx] is None):
            original_idx = current_hour_idx
            for idx in range(current_hour_idx, -1, -1):
                if hourly[test_key][idx] is not None:
                    current_hour_idx = idx
                    break
            if current_hour_idx != original_idx:
                print(f"  ⚠️  Ora {original_idx} ha dati null, uso ora {current_hour_idx} ({hourly['time'][current_hour_idx]})")

        # Superficie: priorità stazione reale
        if station_data:
            print("  → Usando dati REALI dalla stazione meteo (T, Td, P, RH)")
            T_surface_C = station_data['temperature']
            Td_surface_C = station_data['dewpoint']
            p_surface = station_data['pressure']
            RH_surface = station_data['humidity'] / 100
            data_source = "Stazione Tuya (reale)"
        else:
            print("  → Usando dati modello Open-Meteo (fallback)")
            current = data.get("current", {})
            T_surface_C = current.get("temperature_2m")
            RH_surface = current.get("relative_humidity_2m", 50) / 100
            Td_surface_C = current.get("dew_point_2m")
            p_msl = current.get("pressure_msl", 1013.25)
            if T_surface_C is None:
                print("Errore: dati di superficie mancanti")
                return None
            T_surface_K = T_surface_C + 273.15
            p_surface = p_msl * ((1 - 0.0065 * ELEVATION / T_surface_K) ** 5.255)
            data_source = "Open-Meteo (modello)"

        T_surface_K = T_surface_C + 273.15

        if Td_surface_C is not None:
            q_surface = dewpoint_to_mixing_ratio(Td_surface_C, p_surface)
        else:
            es_surface = vapor_pressure(T_surface_C)
            e_surface = es_surface * RH_surface
            q_surface = mixing_ratio(e_surface, p_surface)

        # Profilo verticale
        pressure_levels = [1000, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500]
        T_env_list = [T_surface_K]
        p_env_list = [p_surface]
        RH_env_list = [RH_surface]

        for p_level in pressure_levels:
            key_temp = f"temperature_{p_level}hPa"
            key_rh = f"relative_humidity_{p_level}hPa"
            if (key_temp in hourly and hourly[key_temp] and
                    len(hourly[key_temp]) > current_hour_idx and p_level <= p_surface):
                T_val = hourly[key_temp][current_hour_idx]
                if key_rh in hourly and hourly[key_rh] and len(hourly[key_rh]) > current_hour_idx:
                    RH_val = hourly[key_rh][current_hour_idx] / 100
                else:
                    RH_val = 0.5 if p_level > 500 else 0.3
                if T_val is not None:
                    p_env_list.append(p_level)
                    T_env_list.append(T_val + 273.15)
                    RH_env_list.append(RH_val)

        if len(p_env_list) < 3:
            print("Errore: profilo verticale insufficiente")
            return None

        p_env = np.array(p_env_list)
        T_env = np.array(T_env_list)
        RH_env = np.array(RH_env_list)

        sort_idx = np.argsort(p_env)[::-1]
        p_env = p_env[sort_idx]
        T_env = T_env[sort_idx]
        RH_env = RH_env[sort_idx]

        # Interpolazione ad alta risoluzione (ogni 10 hPa)
        p_min = max(200, p_env[-1])
        p_fine = np.arange(p_surface, p_min, -10)

        if len(p_env) >= 4:
            T_interp_func = interp1d(p_env, T_env, kind='cubic', fill_value='extrapolate')
            RH_interp_func = interp1d(p_env, RH_env, kind='linear', fill_value='extrapolate', bounds_error=False)
            T_fine = T_interp_func(p_fine)
            RH_fine = RH_interp_func(p_fine)
            RH_fine = np.clip(RH_fine, 0.05, 1.0)
            print(f"  Interpolazione: {len(p_env)} livelli → {len(p_fine)} livelli (10 hPa)")
        else:
            T_fine = T_env
            RH_fine = RH_env
            p_fine = p_env

        # SBCAPE (surface-based)
        Td_display = f"{Td_surface_C:.1f}" if Td_surface_C is not None else "N/A"
        print(f"  Sollevamento particella: T={T_surface_C:.1f}°C, Td={Td_display}°C, p={p_surface:.1f}hPa, RH={RH_surface*100:.0f}%")
        T_parcel_sb, p_lcl_sb = lift_parcel(T_surface_K, p_surface, q_surface, p_fine)
        result_sb = calcola_cape_from_profile(T_parcel_sb, p_fine, T_fine, RH_fine, q_surface, p_lcl_sb)

        # MUCAPE
        print("  Cercando livello più instabile (MUCAPE)...")
        result_mu = calcola_mucape(data, station_data, T_fine, p_fine, RH_fine)

        # Wind shear
        shear = calcola_wind_shear(data, current_hour_idx, station_data)

        # Lifted Index
        idx_500 = None
        for i, p in enumerate(p_fine):
            if abs(p - 500) < 15:
                idx_500 = i
                break
        li = (T_fine[idx_500] - T_parcel_sb[idx_500]) if idx_500 is not None else 0

        # Stampa
        print(f"  LCL: {p_lcl_sb:.1f} hPa")
        if result_sb['lfc_pressure']:
            print(f"  LFC: {result_sb['lfc_pressure']:.1f} hPa")
            print(f"  EL: {result_sb['el_pressure']:.1f} hPa" if result_sb['el_pressure'] else "  EL: top atmosfera")
        else:
            print("  LFC: non trovato (atmosfera stabile)")
        if result_mu and result_mu['sbcape'] > result_sb['sbcape']:
            print(f"  MUCAPE: {result_mu['sbcape']:.0f} J/kg (livello {result_mu['mu_level']:.0f} hPa)")

        results = {
            "sbcape": round(float(max(0, result_sb['sbcape'])), 2),
            "mucape": round(float(max(0, result_mu['sbcape'])), 2) if result_mu else None,
            "mu_level": round(float(result_mu['mu_level']), 1) if result_mu else None,
            "cin": round(float(result_sb['cin']), 2),
            "lifted_index": round(float(li), 2),
            "lcl_pressure": round(float(p_lcl_sb), 1),
            "lfc_pressure": round(float(result_sb['lfc_pressure']), 1) if result_sb['lfc_pressure'] else None,
            "el_pressure": round(float(result_sb['el_pressure']), 1) if result_sb['el_pressure'] else None,
            "bulk_shear": round(float(shear['bulk_shear']), 1) if shear else None,
            "timestamp": datetime.now().isoformat(),
            "location": f"La Spezia ({LATITUDE}, {LONGITUDE}) - {ELEVATION}m",
            "unit": "J/kg",
            "calculation_method": "Advanced thermodynamic integration v2.0",
            "data_source": data_source,
            "profile_model": data.get("_model_used", "best_match"),
            "parameters": {
                "temperature_surface": round(float(T_surface_C), 1),
                "dewpoint_surface": round(float(Td_surface_C), 1) if Td_surface_C else None,
                "rh_surface": round(float(RH_surface * 100), 0),
                "pressure_surface": round(float(p_surface), 1),
                "mixing_ratio_surface": round(float(q_surface * 1000), 2),
                "profile_levels": int(len(p_fine)),
                "interpolated": len(p_fine) > len(p_env)
            }
        }

        warnings = _validate_sbcape_results(results, T_surface_C)
        if warnings:
            results['warnings'] = warnings
            for w in warnings:
                print(w)

        return results

    except Exception as e:
        print(f"Errore calcolo SBCAPE: {e}")
        traceback.print_exc()
        return None


def calcola_severe_score(results, raffica_kmh=0):
    """Severe Weather Score combinando multipli parametri (score custom 0-12).
    NON standardizzato; usare solo come indicatore qualitativo."""
    score = 0
    reasons = []

    sbcape = results.get('sbcape', 0)
    mucape = results.get('mucape', 0)
    cin = abs(results.get('cin', 0))
    shear = results.get('bulk_shear', 0)

    max_cape = max(sbcape, mucape) if mucape else sbcape

    if max_cape > 3000:
        score += 4; reasons.append(f"CAPE estremo ({max_cape:.0f} J/kg)")
    elif max_cape > 2500:
        score += 3; reasons.append(f"CAPE molto forte ({max_cape:.0f} J/kg)")
    elif max_cape > 1500:
        score += 2; reasons.append(f"CAPE forte ({max_cape:.0f} J/kg)")
    elif max_cape > 1000:
        score += 1; reasons.append(f"CAPE moderato ({max_cape:.0f} J/kg)")

    if cin < 50:
        score += 2; reasons.append("CAP debole/assente")
    elif cin < 100:
        score += 1; reasons.append("CAP moderato")

    if shear and shear > 15:
        score += 3; reasons.append(f"Shear elevato ({shear:.1f} m/s)")
    elif shear and shear > 10:
        score += 2; reasons.append(f"Shear moderato ({shear:.1f} m/s)")

    if raffica_kmh > 60:
        score += 2; reasons.append(f"Raffiche forti ({raffica_kmh:.0f} km/h)")
    elif raffica_kmh > 40:
        score += 1; reasons.append(f"Raffiche moderate ({raffica_kmh:.0f} km/h)")

    if score >= 7:
        level = "⚡🌪️ ALLERTA MASSIMA: RISCHIO SUPERCELLE/TORNADO"
    elif score >= 5:
        level = "⚡ ALLERTA: TEMPORALI SEVERI PROBABILI"
    elif score >= 3:
        level = "⚡ AVVISO: TEMPORALI FORTI POSSIBILI"
    else:
        level = None

    return {'score': score, 'level': level, 'reasons': reasons}


def calcola_e_salva_sbcape():
    """Entry-point standalone: calcola SBCAPE e salva su FILE_SBCAPE.
    Può essere invocato con `python meteo.py --sbcape`."""
    print("=" * 70)
    print("📊 CALCOLO AVANZATO SBCAPE/MUCAPE & PARAMETRI CONVETTIVI v2.0")
    print("=" * 70)
    print(f"Coordinate: {LATITUDE}°N, {LONGITUDE}°E")
    print(f"Elevazione: {ELEVATION} m s.l.m.")
    print()

    print("📡 Lettura dati dalla stazione meteo Tuya (con retry)...")
    station_data = fetch_station_data_with_retry(max_retries=3)
    if not station_data:
        print("⚠️  Stazione non disponibile, userò dati modello come fallback")

    print("⏳ Scaricando profilo verticale da Open-Meteo (con cache)...")
    data = fetch_profile_cached()
    if not data:
        print("✗ Errore nel fetching dei dati")
        return

    print("⚙️  Calcolando SBCAPE, MUCAPE, CIN e parametri convettivi...")
    risultato = calcola_sbcape_advanced(data, station_data)
    if not risultato:
        print("✗ Errore nel calcolo")
        return

    raffica = station_data['wind_gust'] if station_data else 0
    severe = calcola_severe_score(risultato, raffica)
    risultato['severe_score'] = severe['score']
    if severe['level']:
        risultato['severe_warning'] = severe['level']
        risultato['severe_reasons'] = severe['reasons']

    print()
    print(f"SBCAPE: {risultato['sbcape']:.1f} J/kg")
    if risultato.get('mucape'):
        print(f"MUCAPE: {risultato['mucape']:.1f} J/kg (livello {risultato['mu_level']:.0f} hPa)")
    print(f"CIN:    {risultato['cin']:.1f} J/kg")
    print(f"LI:     {risultato['lifted_index']:.1f} °C")
    if risultato.get('bulk_shear'):
        print(f"Shear:  {risultato['bulk_shear']:.1f} m/s")
    if severe['level']:
        print(f"\n{severe['level']}")
        print(f"Severe Score: {severe['score']}/12")
        for reason in severe['reasons']:
            print(f"  • {reason}")

    with open(FILE_SBCAPE, "w") as f:
        json.dump(risultato, f, indent=4)
    print(f"\n✓ Risultati salvati in {FILE_SBCAPE}")
    print("=" * 70)


def get_auth_headers(method, url, token=None, body=""):
    t = str(int(time.time() * 1000))
    content_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    string_to_sign = f"{method}\n{content_hash}\n\n{url}"
    prefix = ACCESS_ID + token if token else ACCESS_ID
    sign_str = prefix + t + string_to_sign
    sign = hmac.new(ACCESS_SECRET.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest().upper()
    headers = {'client_id': ACCESS_ID, 'sign': sign, 't': t, 'sign_method': 'HMAC-SHA256', 'Content-Type': 'application/json'}
    if token: headers['access_token'] = token
    return headers

def esegui_report():
    # Verifica che le credenziali Tuya siano configurate; se mancano, esci pulito
    if not ACCESS_ID or not ACCESS_SECRET or not DEVICE_ID:
        print("✗ TUYA non configurato: verifica TUYA_ACCESS_ID / TUYA_ACCESS_SECRET / TUYA_DEVICE_ID")
        return

    token_url = "/v1.0/token?grant_type=1"
    try:
        r = requests.get(ENDPOINT + token_url, headers=get_auth_headers("GET", token_url), timeout=10).json()
    except Exception as e:
        print(f"Errore connessione Tuya (token): {e}")
        return

    if not r or not r.get("success") or "result" not in r or "access_token" not in r["result"]:
        print(f"Errore Token Tuya: risposta non valida o credenziali errate. Dettaglio: {r}")
        return

    token = r["result"]["access_token"]
    status_url = f"/v1.0/devices/{DEVICE_ID}/status"
    try:
        res = requests.get(ENDPOINT + status_url, headers=get_auth_headers("GET", status_url, token), timeout=10).json()
    except Exception as e:
        print(f"Errore connessione Tuya (status): {e}")
        return

    if not res or not res.get("success") or "result" not in res:
        print(f"Errore lettura device Tuya: risposta non valida. Dettaglio: {res}")
        return

    d = {item['code']: item['value'] for item in res.get("result", [])}

    print("DATI GREZZI RICEVUTI:", json.dumps(d, indent=4))

    # --- ESTRAZIONE DATI TECNICI ---
    temp_ext = d.get('temp_current_external', 0) / 10
    umid_ext = d.get('humidity_outdoor', 0)
    pressione_locale = estrai_pressione_hpa(d)
    if True:
        if pressione_locale is None:
            print("Pressione non disponibile da Tuya, uso fallback 1013.0 hPa")
            pressione_locale = 1013.0
        # Riduzione pressione al livello del mare con formula ipsometrica
        # P0 = P * exp(g * h / (Rd * T))
        # h = 100 m (altitudine Foce), T = temp_ext + 273.15
        h = 100.0
        Rd = 287.05
        g = 9.80665
        T_k = temp_ext + 273.15 if temp_ext > -50 and temp_ext < 60 else 288.15
        pressione_msl = round(pressione_locale * math.exp(g * h / (Rd * T_k)), 1)
        v_medio = d.get('windspeed_avg', 0) / 10
        pioggia_24h_sensore = d.get('rain_24h', 0) / 10  # Dato grezzo dal sensore (resetta ogni 24h)
        pioggia_1h = d.get('rain_1h', 0) / 10  # Intensità pioggia ultima ora
        
        # Calcola pioggia 24h reale sommando i pioggia_1h dallo storico
        # Il sensore resetta il contatore rain_24h ogni giorno, quindi non è affidabile
        # Sommiamo i campioni orari delle ultime 24h dallo storico + il valore corrente
        _storico_tmp = carica_storico()
        _cutoff_24h = now_it - timedelta(hours=24)
        _pioggia_24h_somma = 0.0
        _ts_precedente = None
        for _s in sorted(_storico_tmp, key=lambda x: x.get("ts", "")):
            _ts_str = _s.get("ts")
            if not _ts_str:
                continue
            try:
                _ts_dt = datetime.fromisoformat(_ts_str)
                if _ts_dt.tzinfo is None:
                    _ts_dt = _ts_dt.replace(tzinfo=TZ_ROME)
                if _ts_dt >= _cutoff_24h:
                    _p1h = _s.get("pioggia_1h", 0) or 0
                    if isinstance(_p1h, (int, float)) and _p1h > 0:
                        _pioggia_24h_somma += _p1h
            except Exception:
                continue
        # Aggiungi il campione corrente (non ancora nello storico)
        _pioggia_24h_somma += max(pioggia_1h, 0)
        pioggia_24h = round(_pioggia_24h_somma, 1)
        print(f"  Pioggia 24h calcolata: {pioggia_24h} mm (sensore: {pioggia_24h_sensore} mm, somma storico+attuale)")
        
        # estrai raffica di vento da file locale (ora + valore)
        raffica = 0
        try:
            if os.path.exists("raffica.json"):
                with open("raffica.json", "r") as f:
                    raff_val = json.load(f)
                    if isinstance(raff_val, dict):
                        raffica = raff_val.get("gust", 0)
                    elif isinstance(raff_val, (int, float)):
                        raffica = raff_val
        except Exception:
            raffica = 0
        
        # Parametri Termometrici Avanzati
        dew_point = d.get('dew_point_temp', 0) / 10
        feel_like = d.get('feellike_temp', 0) / 10
        heat_index = d.get('heat_index', 0) / 10
        wind_chill = d.get('windchill_index', 0) / 10
        uv_idx = d.get('uv_index', 0)
        batt = d.get('battery_percentage', 0)

        # --- CALCOLO API AVANZATO (Indice Saturazione Suolo) ---
        # Parametri specifici per La Spezia - Foce (suolo costiero/urbano)
        # Usa FILE_MEMORIA importato da config, non sovrascrivere
        
        now_it = datetime.now(TZ_ROME)
        mese_corrente = now_it.month
        oggi_str = now_it.strftime("%Y-%m-%d")
        giorno_anno = now_it.timetuple().tm_yday
        
        # EVAPOTRASPIRAZIONE POTENZIALE (ETP) - Metodo Hargreaves-Samani (FAO)
        # Usa solo temperatura, umidità e calcoli astronomici (non serve radiazione misurata)
        
        # Coordinate La Spezia - Foce (usare costanti di config se presenti)
        LAT = LATITUDE
        
        # Radiazione extraterrestre (Ra) - calcolo astronomico
        lat_rad = (math.pi / 180.0) * LAT  # converti gradi in radianti
        
        # Declinazione solare (δ)
        delta = 0.409 * math.sin((2 * math.pi / 365) * giorno_anno - 1.39)
        
        # Distanza relativa Terra-Sole (dr)
        dr = 1 + 0.033 * math.cos((2 * math.pi / 365) * giorno_anno)
        
        # Angolo al tramonto (ωs)
        ws = math.acos(-math.tan(lat_rad) * math.tan(delta))
        
        # Radiazione extraterrestre giornaliera Ra (MJ/m²/giorno)
        Gsc = 0.0820  # costante solare MJ/m²/min
        Ra = (24 * 60 / math.pi) * Gsc * dr * (
            ws * math.sin(lat_rad) * math.sin(delta) + 
            math.cos(lat_rad) * math.cos(delta) * math.sin(ws)
        )
        
        # Temperatura: recupera min/max dal file memoria o usa valori di default
        dati_salvati = {}
        
        if os.path.exists(FILE_MEMORIA):
            try:
                with open(FILE_MEMORIA, "r") as f:
                    dati_salvati = json.load(f)
            except:
                dati_salvati = {}
        
        # Gestione temperatura min/max giornaliera
        t_min_oggi = dati_salvati.get("t_min_oggi", temp_ext)
        t_max_oggi = dati_salvati.get("t_max_oggi", temp_ext)
        
        # Se è un nuovo giorno, resetta le temperature PRIMA di Hargreaves
        ultima_data_check = dati_salvati.get("data_calcolo", "")
        if ultima_data_check != oggi_str:
            t_min_oggi = temp_ext
            t_max_oggi = temp_ext
        
        # Aggiorna min/max se necessario
        if temp_ext < t_min_oggi:
            t_min_oggi = temp_ext
        if temp_ext > t_max_oggi:
            t_max_oggi = temp_ext
        
        t_media = (t_max_oggi + t_min_oggi) / 2.0
        delta_t = t_max_oggi - t_min_oggi
        
        # Formula Hargreaves-Samani base
        # ETP₀ = 0.0023 × Ra × (T_med + 17.8) × √ΔT
        etp_base = 0.0023 * Ra * (t_media + 17.8) * math.sqrt(max(delta_t, 1.0))
        etp_base = round(etp_base, 2)
        
        # --- COEFFICIENTE COLTURALE STAGIONALE (Kc) ---
        # La Spezia - Foce: zona costiera urbanizzata con giardini, parchi e vegetazione mista
        # Ponderato: ~40% superfici impermeabili, ~35% verde urbano, ~25% suolo naturale
        kc_mensile = {
            1: 0.35, 2: 0.35,    # Inverno - vegetazione minima, suolo freddo
            3: 0.45, 4: 0.55,    # Primavera - ripresa vegetativa graduale
            5: 0.65, 6: 0.70,    # Tarda primavera - piena vegetazione
            7: 0.70, 8: 0.65,    # Estate - picco, possibile stress idrico
            9: 0.55, 10: 0.50,   # Autunno - senescenza fogliare
            11: 0.40, 12: 0.35   # Tardo autunno - dormienza
        }
        kc = kc_mensile.get(mese_corrente, 0.50)
        
        # ETP con coefficiente colturale (per il report)
        etp_giornaliera = round(etp_base * kc, 2)
        
        # --- SEPARAZIONE EVAPORAZIONE SUOLO / TRASPIRAZIONE (FAO-56 Dual Kc) ---
        # ETR = (Kcb × Ks × ETP_base)
        #   Kcb = coeff. basale coltura (traspirazione dalla vegetazione)
        #   Ks  = coeff. stress idrico (riduce traspirazione se suolo secco)
        
        # Kcb (traspirazione basale) - parte vegetativa del Kc
        kcb_mensile = {
            1: 0.15, 2: 0.15,    # Inverno - minima traspirazione
            3: 0.25, 4: 0.35,    # Primavera - aumento LAI
            5: 0.50, 6: 0.55,    # Tarda primavera - massima copertura fogliare
            7: 0.55, 8: 0.50,    # Estate - possibile chiusura stomi per caldo
            9: 0.40, 10: 0.30,   # Autunno - caduta foglie
            11: 0.20, 12: 0.15   # Tardo autunno - dormienza
        }
        kcb = kcb_mensile.get(mese_corrente, 0.30)
        
        # Ke (evaporazione suolo) non calcolato: serve radiazione solare reale per stima affidabile
        # Solo componente traspirazione vegetazione (Kcb*Ks)
        
        # CAPACITÀ DI CAMPO E PARAMETRI SUOLO
        # Suolo La Spezia-Foce: argilloso-limoso costiero, depositi alluvionali
        capacita_campo = 200   # mm - contenuto idrico massimo del profilo
        wilting_point = 80     # mm - punto di appassimento permanente
        
        # Conducibilità idraulica a saturazione (Ksat) - Modello Brooks-Corey
        # Argilla-limo costiero La Spezia Foce: Ksat tipico 2-3 mm/giorno
        K_sat = 2.5            # mm/giorno
        beta_drenaggio = 3.5   # Esponente di forma (3-4 per suoli argilloso-limosi)
        
        # Rileggi dati salvati per ottenere valori completi
        debug_msg = f"FILE_MEMORIA={os.path.abspath(FILE_MEMORIA)}, exists={os.path.exists(FILE_MEMORIA)}"
        print(debug_msg)
        
        if os.path.exists(FILE_MEMORIA):
            try:
                with open(FILE_MEMORIA, "r") as f:
                    dati_salvati = json.load(f)
                debug_msg += f" | ✓ Letto: {dati_salvati}"
                print(debug_msg)
            except Exception as e:
                debug_msg += f" | ✗ Errore: {e}"
                print(debug_msg)
                dati_salvati = {}
        else:
            debug_msg += " | ✗ NON trovato"
            print(debug_msg)

        ultima_data = dati_salvati.get("data_calcolo", "")
        api_ultimo_valore = dati_salvati.get("api_ultimo_valore", 179.45) # Seed richiesto: 179.45
        sat_base_oggi = dati_salvati.get("sat_base_oggi", 0)
        etp_accumulata = dati_salvati.get("etp_accumulata_ieri", 0)
        e_nuovo_giorno = (ultima_data != oggi_str)  # Flag per accumulo ETP
        
        debug_api = f"API_DEBUG: data={ultima_data}, api_ultimo={api_ultimo_valore:.2f}, etp_acc={etp_accumulata:.2f}"
        print(debug_api)

        if ultima_data != oggi_str:
            # Nuovo giorno rilevato
            if ultima_data == "":
                # Prima esecuzione: usa il seed direttamente
                sat_base_oggi = api_ultimo_valore
                etp_accumulata = 0  # Reset per prima esecuzione
                t_min_oggi = temp_ext  # Reset temperature
                t_max_oggi = temp_ext
                print(f"Prima esecuzione: seed iniziale = {sat_base_oggi:.2f}")
            else:
                # DECADIMENTO GIORNALIERO: ETR reale + drenaggio gravitazionale (Brooks-Corey)
                
                # 1. Drenaggio gravitazionale con conducibilità idraulica
                # D = Ksat × (θ/θ_sat)^β  [modello Brooks-Corey]
                theta_prec = api_ultimo_valore / capacita_campo  # Saturazione frazionaria 0-1
                if theta_prec > 0.4:
                    drenaggio_extra = K_sat * (theta_prec ** beta_drenaggio)
                else:
                    drenaggio_extra = 0  # Sotto il 40%, drenaggio gravitazionale trascurabile
                
                perdita_totale = etp_accumulata + drenaggio_extra
                sat_base_oggi = max(0, api_ultimo_valore - perdita_totale)
                print(f"Nuovo giorno: {api_ultimo_valore:.2f} - ETR({etp_accumulata:.2f}) - dren_Ksat({drenaggio_extra:.2f}) = {sat_base_oggi:.2f}")
                etp_accumulata = 0  # Reset per nuovo giorno
                t_min_oggi = temp_ext  # Reset temperature per nuovo giorno
                t_max_oggi = temp_ext
            ultima_data = oggi_str

        # INFILTRAZIONE DINAMICA - dipende da saturazione attuale e intensità pioggia
        saturazione_percentuale = (sat_base_oggi / capacita_campo) * 100
        
        # 1. Runoff da intensità (impermeabilizzazione urbana)
        if pioggia_1h > 25:  # Downpour estremo
            runoff_intensita = 0.5  # 50% runoff
        elif pioggia_1h > 15:  # Downpour
            runoff_intensita = 0.35  # 35% runoff
        elif pioggia_1h > 8:  # Pioggia forte
            runoff_intensita = 0.20  # 20% runoff
        elif pioggia_1h > 3:  # Pioggia moderata
            runoff_intensita = 0.08  # 8% runoff
        else:  # Pioggia debole
            runoff_intensita = 0.02  # 2% runoff (assorbimento quasi totale)
        
        # 2. Runoff da saturazione (suolo già saturo infiltra meno)
        if saturazione_percentuale > 95:
            runoff_saturazione = 0.7  # Suolo quasi saturo
        elif saturazione_percentuale > 85:
            runoff_saturazione = 0.4
        elif saturazione_percentuale > 70:
            runoff_saturazione = 0.15
        else:
            runoff_saturazione = 0.0  # Suolo asciutto, infiltrazione ottimale
        
        # Runoff totale (prende il massimo tra i due meccanismi)
        runoff_totale = max(runoff_intensita, runoff_saturazione)
        efficienza_infiltrazione = 1 - runoff_totale
        
        # Pioggia effettivamente infiltrata
        pioggia_infiltrata = pioggia_24h * efficienza_infiltrazione
        
        # --- COEFFICIENTE STRESS IDRICO (Ks) ---
        # Riduce la traspirazione quando il suolo è troppo secco
        theta_attuale = sat_base_oggi / capacita_campo if capacita_campo > 0 else 0
        theta_wp = wilting_point / capacita_campo
        # Soglia RAW (Readily Available Water): 60% dell'acqua disponibile
        p_depletion = 0.60  # Fattore deplezione (0.5-0.7 per vegetazione urbana mista)
        theta_critico = theta_wp + p_depletion * (1.0 - theta_wp)
        
        if theta_attuale >= theta_critico:
            ks = 1.0  # Acqua sufficiente, nessuno stress
        elif theta_attuale > theta_wp:
            ks = (theta_attuale - theta_wp) / (theta_critico - theta_wp)
        else:
            ks = 0.0  # Sotto wilting point: traspirazione azzerata
        
        # --- COMPONENTI ETR GIORNALIERE (mm/giorno) ---
        # Evaporazione suolo: calcolata scientificamente secondo l'approccio
        # dual Kc (FAO-56). Ev = Ke * ETo, dove ETo = `etp_base`.
        evaporazione_suolo = 0.0

        # Calcolo di Ke (evaporazione suolo) secondo approccio FAO-56 (dual Kc):
        # Ke_initial = max(0, Kc - Kcb)
        # Ke effettivo è ridotto da un fattore Kr che dipende dall'acqua disponibile
        # nel profilo superficiale rispetto alla Readily Available Water (RAW).
        try:
            # TAW: total available water nel profilo considerato (mm)
            TAW = max(0.0, capacita_campo - wilting_point)
            # AW: acqua disponibile attuale rispetto al punto di appassimento (mm)
            AW = max(0.0, sat_base_oggi - wilting_point)
            RAW = p_depletion * TAW

            ke_initial = max(0.0, kc - kcb)

            if RAW <= 0 or TAW <= 0:
                Kr = 0.0
            else:
                # Se AW >= RAW, nessuna riduzione; altrimenti scala linearmente
                if AW >= RAW:
                    Kr = 1.0
                else:
                    Kr = AW / RAW

            ke = ke_initial * Kr
            # Evaporazione suolo in mm/giorno (E = Ke * ETo)
            evaporazione_suolo = round(ke * etp_base, 2)
        except Exception:
            ke = 0.0

        traspirazione = round(kcb * ks * etp_base, 2)      # Traspirazione vegetazione
        # ETR totale (mm/giorno) = traspirazione + evaporazione suolo
        etr_giornaliera = round(traspirazione + evaporazione_suolo, 2)
        
        # --- ACCUMULO ETP: media mobile pesata nel corso del giorno ---
        # Hargreaves-Samani migliora col passare delle ore (T_min/T_max più accurate)
        n_run_oggi = dati_salvati.get("n_run_oggi", 0)
        etp_media_oggi = dati_salvati.get("etp_media_oggi", 0)
        
        if not e_nuovo_giorno and n_run_oggi > 0:
            # Stesso giorno: aggiorna media pesata incrementale
            n_run_oggi += 1
            etp_media_oggi = etp_media_oggi + (etr_giornaliera - etp_media_oggi) / n_run_oggi
        else:
            # Nuovo giorno: inizializza
            n_run_oggi = 1
            etp_media_oggi = etr_giornaliera
        
        etp_accumulata = round(etp_media_oggi, 2)
        
        # --- APPLICAZIONE INTRA-GIORNALIERA DELL'ETR ---
        # Il suolo si asciuga progressivamente durante il giorno, non solo a mezzanotte
        ore_trascorse = now_it.hour + now_it.minute / 60.0
        fraz_giorno = ore_trascorse / 24.0
        etr_parziale = etr_giornaliera * fraz_giorno
        
        # API totale = base + pioggia infiltrata - ETR proporzionale al tempo trascorso
        sat_visualizzato = sat_base_oggi + pioggia_infiltrata - etr_parziale
        sat_visualizzato = max(0.0, min(sat_visualizzato, capacita_campo))
        sat_visualizzato = round(sat_visualizzato, 2)
        
        # Ricalcola saturazione percentuale finale
        saturazione_percentuale = (sat_visualizzato / capacita_campo) * 100
        
        print(f"API AVANZATO (Bilancio idrico multi-componente):")
        print(f"  Base oggi: {sat_base_oggi:.2f} mm")
        print(f"  Pioggia 24h: {pioggia_24h:.2f} mm → infiltrata: {pioggia_infiltrata:.2f} mm")
        print(f"  Runoff: {runoff_totale*100:.1f}% (int:{runoff_intensita*100:.0f}%, sat:{runoff_saturazione*100:.0f}%)")
        print(f"  ETP base Hargreaves: {etp_base:.2f} mm | Kc={kc:.2f} → ETP={etp_giornaliera:.2f} mm")
        print(f"  Ra={Ra:.1f} MJ/m²/d | T_med={t_media:.1f}°C | ΔT={delta_t:.1f}°C")
        print(f"  Dual Kc: Ke={ke:.2f} (evap suolo) | Kcb={kcb:.2f} (trasp) | Ks={ks:.2f} (stress)")
        print(f"  Evaporazione suolo: {evaporazione_suolo:.2f} mm | Traspirazione: {traspirazione:.2f} mm")
        print(f"  ETR giornaliera: {etr_giornaliera:.2f} mm | ETR parziale ({fraz_giorno*100:.0f}% giorno): {etr_parziale:.2f} mm")
        print(f"  ETR media accumulata (run #{n_run_oggi}): {etp_accumulata:.2f} mm")
        print(f"  Drenaggio Brooks-Corey: K_sat={K_sat} mm/d, β={beta_drenaggio}")
        print(f"  Saturazione: {saturazione_percentuale:.1f}% ({sat_visualizzato:.2f}/{capacita_campo} mm)")
        print(f"  API totale: {sat_visualizzato:.2f} mm")

        # --- CALCOLO SBCAPE INLINE (integrato da calcola_SBCAPE.py) ---
        sbcape_str = ""
        sbcape_value = 0
        mucape_value = 0
        cin_value = 0
        li_value = None
        bulk_shear = 0
        severe_score = 0
        severe_warning = None
        convective_risk = {
            "score": 0.0,
            "level": "basso",
            "warning": None,
            "event_label": "Instabilità convettiva",
            "event_trigger": False,
            "max_cape": 0.0,
            "cin_abs": 0.0,
            "li": None,
            "shear": 0.0,
        }

        # Costruisci station_data dal Tuya già letto in questo run
        _station_data_for_sbcape = {
            'temperature': temp_ext,
            'dewpoint': dew_point,
            'pressure': pressione_locale if pressione_locale else 1013.0,
            'humidity': umid_ext,
            'wind_speed': v_medio,
            'wind_gust': d.get('windspeed_gust', 0) / 10,
        }

        try:
            print("\n⚙️  Calcolo SBCAPE/MUCAPE inline...")
            _om_data = fetch_profile_cached()
            if _om_data:
                _sbcape_result = calcola_sbcape_advanced(_om_data, _station_data_for_sbcape)
                if _sbcape_result:
                    sbcape_value = _sbcape_result.get("sbcape") or 0
                    mucape_value = _sbcape_result.get("mucape") or 0
                    cin_value = _sbcape_result.get("cin") or 0
                    li_value = _sbcape_result.get("lifted_index")
                    bulk_shear = _sbcape_result.get("bulk_shear") or 0

                    _severe = calcola_severe_score(_sbcape_result, raffica)
                    severe_score = _severe['score']
                    severe_warning = _severe.get('level')

                    # Salva su FILE_SBCAPE per compatibilità
                    _sbcape_result['severe_score'] = severe_score
                    if severe_warning:
                        _sbcape_result['severe_warning'] = severe_warning
                        _sbcape_result['severe_reasons'] = _severe.get('reasons', [])
                    with open(FILE_SBCAPE, "w") as f:
                        json.dump(_sbcape_result, f, indent=4)
                    print(f"  ✓ SBCAPE={sbcape_value:.0f} MUCAPE={mucape_value:.0f} CIN={cin_value:.0f} LI={li_value} Shear={bulk_shear} SevScore={severe_score}")
                else:
                    print("  ⚠️  Calcolo SBCAPE fallito, provo fallback da JSON")
                    raise RuntimeError("calcolo fallito")
            else:
                print("  ⚠️  Profilo Open-Meteo non disponibile, provo fallback da JSON")
                raise RuntimeError("profilo non disponibile")
        except Exception as _e:
            # Fallback: leggi da sbcape.json pre-esistente (se presente)
            print(f"  Fallback sbcape.json: {_e}")
            try:
                if os.path.exists(FILE_SBCAPE):
                    with open(FILE_SBCAPE, "r") as f:
                        sbcape_data = json.load(f)
                        sbcape_value = sbcape_data.get("sbcape") or 0
                        mucape_value = sbcape_data.get("mucape") or 0
                        cin_value = sbcape_data.get("cin") or 0
                        li_value = sbcape_data.get("lifted_index")
                        bulk_shear = sbcape_data.get("bulk_shear") or 0
                        severe_score = sbcape_data.get("severe_score") or 0
                        severe_warning = sbcape_data.get("severe_warning")
                    print(f"  ✓ Letto da {FILE_SBCAPE} (fallback)")
            except Exception as e2:
                print(f"  ✗ Anche fallback JSON fallito: {e2}")

        convective_risk = valuta_instabilita_convettiva(
            sbcape_value,
            mucape_value,
            cin_value,
            li_value,
            bulk_shear,
            severe_score,
        )

        # --- TENDENZA BAROMETRICA ---
        storico = carica_storico()
        simbolo_baro, delta_baro, desc_baro = calcola_tendenza_barometrica(storico, pressione_msl)
        
        # Aggiungi punto allo storico
        storico.append({
            "ts": now_it.isoformat(),
            "temp": temp_ext,
            "pressione": pressione_msl,
            "pioggia_1h": pioggia_1h,
            "pioggia_24h": pioggia_24h,
            "umidita": umid_ext,
            "vento": v_medio,
            "raffica": raffica,
            "dew_point": dew_point,
            "api": sat_visualizzato,
            "sbcape": sbcape_value,
            "mucape": mucape_value,
            "bulk_shear": bulk_shear,
            "theta_e": classifica_massa_aria(temp_ext, dew_point, pressione_msl, mese_corrente).get("theta_e")
        })
        salva_storico(storico)
        
        # ARPAL alerts are handled by monitor_arpal.py now; skip scraping here
        arpal_str = ""
        arpal_livello = "Verde"
        
        # --- LOGICA AVVISI (soglie ARPAL Protezione Civile Liguria – Zona C) ---
        avvisi = []
        
        # ARPAL handled separately by monitor_arpal.py
        
        # Nebbia/foschia (solo con umidità >= 99%)
        diff_temp_dew = temp_ext - dew_point
        if umid_ext >= 99 and diff_temp_dew <= 0.5:
            if v_medio < 5:
                avvisi.append("🌫️ AVVISO: NEBBIA (T-Td ≤0.5°C, U≥99%)")
            else:
                avvisi.append("🌫️ AVVISO: FOSCHIA (T-Td ≤0.5°C, U≥99%)")
        
        # ── VENTO — soglie ARPAL raffiche ──
        if raffica >= thresholds.ARPAL_WIND_ROSSO:
            avvisi.append(f"🔴⚠️ AVVISO: BURRASCA FORTE — raffica {raffica} km/h (soglia ARPAL 🔴 ≥{thresholds.ARPAL_WIND_ROSSO:.0f} km/h)")
        elif raffica >= thresholds.ARPAL_WIND_ARANCIONE:
            avvisi.append(f"🟠⚠️ AVVISO: BURRASCA — raffica {raffica} km/h (soglia ARPAL 🟠 ≥{thresholds.ARPAL_WIND_ARANCIONE:.0f} km/h)")
        elif raffica >= thresholds.ARPAL_WIND_GIALLO:
            avvisi.append(f"🟡⚠️ AVVISO: VENTO FORTE — raffica {raffica} km/h (soglia ARPAL 🟡 ≥{thresholds.ARPAL_WIND_GIALLO:.0f} km/h)")

        # ── TEMPERATURA — soglie ARPAL ondata di calore / gelo ──
        if temp_ext >= thresholds.ARPAL_HEAT_ROSSO:
            avvisi.append(f"🔴🔥 AVVISO: CALDO ESTREMO — {temp_ext}°C (soglia ARPAL 🔴 ≥{thresholds.ARPAL_HEAT_ROSSO:.0f}°C)")
        elif temp_ext >= thresholds.ARPAL_HEAT_ARANCIONE:
            avvisi.append(f"🟠🔥 AVVISO: CALDO MOLTO INTENSO — {temp_ext}°C (soglia ARPAL 🟠 ≥{thresholds.ARPAL_HEAT_ARANCIONE:.0f}°C)")
        elif temp_ext >= thresholds.ARPAL_HEAT_GIALLO:
            avvisi.append(f"🟡🔥 AVVISO: CALDO INTENSO — {temp_ext}°C (soglia ARPAL 🟡 ≥{thresholds.ARPAL_HEAT_GIALLO:.0f}°C)")
        elif temp_ext <= thresholds.ARPAL_FROST_ROSSO:
            avvisi.append(f"🔴❄️ AVVISO: GELO ESTREMO — {temp_ext}°C (soglia ARPAL 🔴 ≤{thresholds.ARPAL_FROST_ROSSO:.0f}°C)")
        elif temp_ext <= thresholds.ARPAL_FROST_ARANCIONE:
            avvisi.append(f"🟠❄️ AVVISO: GELO INTENSO — {temp_ext}°C (soglia ARPAL 🟠 ≤{thresholds.ARPAL_FROST_ARANCIONE:.0f}°C)")
        elif temp_ext <= thresholds.ARPAL_FROST_GIALLO:
            avvisi.append(f"🟡❄️ AVVISO: GELO — {temp_ext}°C (soglia ARPAL 🟡 ≤{thresholds.ARPAL_FROST_GIALLO:.0f}°C)")

        # Afa (non è soglia ARPAL diretta, indicazione di disagio bioclimatico)
        if temp_ext > 25 and umid_ext > 60:
            avvisi.append("🥵 AVVISO: AFA")

        # ── MAREGGIATE — pressione MSL indicativa ──
        if pressione_msl < thresholds.ARPAL_STORM_SURGE_ROSSO:
            avvisi.append(f"🔴🌊 AVVISO: MAREGGIATE GRAVI — {pressione_msl} hPa (soglia ARPAL 🔴 <{thresholds.ARPAL_STORM_SURGE_ROSSO:.0f} hPa)")
        elif pressione_msl < thresholds.ARPAL_STORM_SURGE_ARANCIONE:
            avvisi.append(f"🟠🌊 AVVISO: MAREGGIATE — {pressione_msl} hPa (soglia ARPAL 🟠 <{thresholds.ARPAL_STORM_SURGE_ARANCIONE:.0f} hPa)")
        elif pressione_msl < thresholds.ARPAL_STORM_SURGE_GIALLO:
            avvisi.append(f"🟡🌊 AVVISO: ATTENZIONE MARE — {pressione_msl} hPa (soglia ARPAL 🟡 <{thresholds.ARPAL_STORM_SURGE_GIALLO:.0f} hPa)")

        # ── PRECIPITAZIONI orarie — soglie ARPAL Bacini Piccoli ──
        if pioggia_1h >= thresholds.ARPAL_RAIN_1H_ROSSO:
            avvisi.append(f"🔴🌧️ AVVISO: NUBIFRAGIO — {pioggia_1h} mm/h (soglia ARPAL 🔴 ≥{thresholds.ARPAL_RAIN_1H_ROSSO:.0f} mm/h)")
        elif pioggia_1h >= thresholds.ARPAL_RAIN_1H_ARANCIONE:
            avvisi.append(f"🟠🌧️ AVVISO: PIOGGIA MOLTO FORTE — {pioggia_1h} mm/h (soglia ARPAL 🟠 ≥{thresholds.ARPAL_RAIN_1H_ARANCIONE:.0f} mm/h)")
        elif pioggia_1h >= thresholds.ARPAL_RAIN_1H_GIALLO:
            avvisi.append(f"🟡🌧️ AVVISO: PIOGGIA FORTE — {pioggia_1h} mm/h (soglia ARPAL 🟡 ≥{thresholds.ARPAL_RAIN_1H_GIALLO:.0f} mm/h)")
        elif pioggia_1h >= 6:
            avvisi.append(f"🌧️ AVVISO: PIOGGIA MODERATA — {pioggia_1h} mm/h")

        # ── CUMULATE 24h — soglie ARPAL Bacini Grandi + suolo ──
        if sat_visualizzato >= 170:
            avvisi.append("⛰️ AVVISO: SUOLO SATURO")

        if pioggia_24h >= thresholds.ARPAL_RAIN_24H_ROSSO:
            avvisi.append(f"🔴🌧️ AVVISO: CUMULATE ECCEZIONALI — {pioggia_24h} mm/24h (soglia ARPAL 🔴 ≥{thresholds.ARPAL_RAIN_24H_ROSSO:.0f} mm)")
        elif pioggia_24h >= thresholds.ARPAL_RAIN_24H_ARANCIONE:
            avvisi.append(f"🟠🌧️ AVVISO: CUMULATE MOLTO ELEVATE — {pioggia_24h} mm/24h (soglia ARPAL 🟠 ≥{thresholds.ARPAL_RAIN_24H_ARANCIONE:.0f} mm)")
        elif pioggia_24h >= thresholds.ARPAL_RAIN_24H_GIALLO:
            avvisi.append(f"🟡🌧️ AVVISO: CUMULATE ELEVATE — {pioggia_24h} mm/24h (soglia ARPAL 🟡 ≥{thresholds.ARPAL_RAIN_24H_GIALLO:.0f} mm)")
        elif pioggia_24h >= 50:
            avvisi.append(f"🌧️ AVVISO: CUMULATE SIGNIFICATIVE — {pioggia_24h} mm/24h")
        
        # --- AVVISO INSTABILITÀ CONVETTIVA (Severe Weather Score) ---
        # Usa il nuovo severe weather score se disponibile
        if severe_warning:
            avvisi.append(severe_warning)
        else:
            if convective_risk["warning"]:
                avvisi.append(convective_risk["warning"])
        # ---------------------------------------------------------
        
        # Costruisci stringa con parametri avanzati (evita duplicati con gli avvisi)
        avvisi_lower = " ".join(avvisi).lower() if avvisi else ""
        sbcape_lines = []
        if "sbcape" not in avvisi_lower:
            sbcape_lines.append(f"SBCAPE: {sbcape_value} J/kg")
        if mucape_value and mucape_value > sbcape_value and "mucape" not in avvisi_lower:
            sbcape_lines.append(f"MUCAPE: {mucape_value} J/kg")
        if "cin" not in avvisi_lower:
            sbcape_lines.append(f"CIN: {cin_value} J/kg")
        if li_value is not None and "lifted index" not in avvisi_lower:
            sbcape_lines.append(f"Lifted Index: {li_value:+.1f}°C")
        if bulk_shear:
            sbcape_lines.append(f"Bulk Shear: {bulk_shear:.1f} m/s")
        if severe_score > 0 and "severe score" not in avvisi_lower:
            sbcape_lines.append(f"Severe Score: {severe_score}/12")
        elif convective_risk["score"] > 0 and "severe score" not in avvisi_lower:
            sbcape_lines.append(f"Convective Score (fallback): {convective_risk['score']}/12")
        sbcape_str = "\n".join(sbcape_lines) + ("\n" if sbcape_lines else "")

        str_avvisi = "\n".join(avvisi) + "\n\n" if avvisi else ""

        # --- CLASSIFICAZIONE MASSA D'ARIA ---
        massa_aria = classifica_massa_aria(temp_ext, dew_point, pressione_msl, mese_corrente)
        massa_str = (
            f"🌍 *MASSA D'ARIA*\n"
            f"{massa_aria['emoji']} {massa_aria['nome']} ({massa_aria['tipo']})\n"
            f"{massa_aria['desc']}\n"
            f"θe: {massa_aria['theta_e']}°C · Anomalia: {massa_aria['anomalia']:+.1f}°C · Spread T-Td: {massa_aria['spread']}°C\n"
        )
        print(f"Massa d'aria: {massa_aria['tipo']} ({massa_aria['nome']}) - θe={massa_aria['theta_e']}°C, anomalia={massa_aria['anomalia']:+.1f}°C")

        # --- SALVA DATI PER PROSSIMO RUN ---
        nuovi_dati = {
            "api_ultimo_valore": sat_visualizzato,  # API finale di oggi (base per domani)
            "sat_base_oggi": sat_base_oggi,        # Base senza pioggia di oggi
            "etp_accumulata_ieri": etp_accumulata, # ETR media del giorno (verrà sottratta domani)
            "data_calcolo": ultima_data,
            "ultimo_update_ora": str(now_it),
            "ultimo_etp_giornaliera": etp_giornaliera,
            "ultimo_etr_giornaliera": etr_giornaliera,
            "ultima_saturazione_perc": round(saturazione_percentuale, 1),
            "t_min_oggi": t_min_oggi,              # Temperatura minima giornaliera
            "t_max_oggi": t_max_oggi,              # Temperatura massima giornaliera
            "ultima_pressione": pressione_msl,     # Per calcolare calo pressione
            "ultimi_avvisi": avvisi,               # Per rilevare nuovi avvisi
            "n_run_oggi": n_run_oggi,              # Run eseguiti oggi (per media ETP)
            "etp_media_oggi": round(etp_media_oggi, 2),  # Media pesata ETR oggi
            "ultimo_kc": kc,
            "ultimo_ke": round(ke, 2),
            "ultimo_kcb": kcb,
            "ultimo_ks": round(ks, 2)
        }

        with open(FILE_MEMORIA, "w") as f:
            json.dump(nuovi_dati, f, indent=4)

        # Data e Ora Italiana (automatica solare/legale)
        data_ora_it = now_it.strftime('%d/%m/%Y %H:%M')

        # --- COSTRUZIONE REPORT ---
        testo_meteo = (
            f"📡 *STAZIONE METEO LA SPEZIA — FOCE*\n"
            f"📅 {data_ora_it}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{str_avvisi}"
            f"🌡️ *TEMPERATURE*\n"
            f"Aria: {temp_ext}°C\n"
            f"Percepita: {feel_like}°C\n"
            f"Heat Index: {heat_index}°C\n"
            f"Wind Chill: {wind_chill}°C\n"
            f"Punto di rugiada: {dew_point}°C\n\n"
            f"💧 *UMIDITÀ E PRECIPITAZIONI*\n"
            f"Umidità: {umid_ext}%\n"
            f"Pioggia ultima ora: {pioggia_1h} mm\n"
            f"Pioggia 24h: {pioggia_24h} mm\n\n"
            f"🌬️ *VENTO*\n"
            f"Velocità media: {v_medio} km/h\n"
            f"Raffica max: {raffica} km/h\n\n"
            f"🔵 *PRESSIONE ATMOSFERICA*\n"
            f"Livello mare: {pressione_msl} hPa {simbolo_baro}\n\n"
            f"☀️ *RADIAZIONE*\n"
            f"Indice UV: {uv_idx}\n\n"
            f"🌱 *BILANCIO IDRICO SUOLO*\n"
            f"API: {sat_visualizzato} mm ({saturazione_percentuale:.1f}%)\n"
            f"ETR: {etr_giornaliera} mm\n"
            f"ETP: {etp_giornaliera} mm\n\n"
            f"⚡ *INSTABILITÀ CONVETTIVA*\n"
            f"{sbcape_str}\n"
            f"{massa_str}\n"
            f"🔋 Batteria: {batt}%"
        )
        
        # --- LOGICA INVIO SMART ---
        # Determina se inviare il messaggio Telegram
        
        ora_corrente = now_it.hour
        minuto_corrente = now_it.minute
        
        # 1. Orari programmati (report regolari, ora italiana)
        # Invio 4 volte al giorno nelle finestre :58/:59 per compatibilità con cronjob.com
        orari_report = [5, 11, 17, 23]
        minuti_report = [58, 59]
        e_orario_programmato = ora_corrente in orari_report and minuto_corrente in minuti_report
        e_orario_grafico = ora_corrente in [11, 23] and minuto_corrente in minuti_report
        
        # 2. Eventi meteo significativi
        eventi_significativi = []
        
        # Pioggia in corso (soglia abbassata per monitoraggio perturbazioni)
        if pioggia_1h >= thresholds.RAIN_SIGNIFICANT:
            eventi_significativi.append(f"Pioggia: {pioggia_1h} mm/h")
        
        # Vento forte
        if raffica > thresholds.WIND_STRONG:
            eventi_significativi.append(f"Raffica: {raffica} km/h")

        # Temperature estreme
        # Soglia di gelo: trigger se temperatura è minore o uguale alla soglia
        if temp_ext <= thresholds.TEMP_FREEZING:
            eventi_significativi.append(f"Temperatura bassa: {temp_ext}°C")
        if temp_ext >= thresholds.TEMP_HOT:
            eventi_significativi.append(f"Temperatura alta: {temp_ext}°C")
        
        # Pressione: invia solo se il valore attuale cala e il delta 3h è almeno -1 hPa
        pressione_precedente = dati_salvati.get("ultima_pressione")
        pressione_in_calo_attuale = isinstance(pressione_precedente, (int, float)) and pressione_msl < pressione_precedente
        if pressione_in_calo_attuale and delta_baro <= -1:
            eventi_significativi.append(f"Pressione in calo: {delta_baro:.1f} hPa/3h")
        
        # Nebbia in corso
        if umid_ext >= 99 and diff_temp_dew <= 0.5:
            eventi_significativi.append(f"Nebbia (T-Td={diff_temp_dew:.1f}°C, U={umid_ext}%)")
        
        # Allerta ARPAL gestita separatamente (monitor_arpal.py)
        
        # Instabilità convettiva: trigger unico multi-parametro (più realistico)
        if convective_risk["event_trigger"]:
            li_text = f"{convective_risk['li']:.1f}"
            if convective_risk["li"] is None:
                li_text = "n/d"
            eventi_significativi.append(
                f"{convective_risk['event_label']} (Score {convective_risk['score']}/12, "
                f"CAPE {convective_risk['max_cape']:.0f} J/kg, CIN {cin_value:.0f} J/kg, "
                f"LI {li_text}°C, Shear {convective_risk['shear']:.1f} m/s)"
            )
        
        # Severe Score elevato
        if severe_score >= 7 and not convective_risk["event_trigger"]:
            eventi_significativi.append(f"Severe Score: {severe_score}/12")
        
        # Confronta avvisi (nuovi avvisi rispetto a prima)
        avvisi_precedenti = set(dati_salvati.get("ultimi_avvisi", []))
        avvisi_attuali = set(avvisi)
        nuovi_avvisi = avvisi_attuali - avvisi_precedenti
        if nuovi_avvisi:
            eventi_significativi.append(f"Nuovi avvisi: {len(nuovi_avvisi)}")
        
        # 3. Decide se inviare
        devo_inviare = e_orario_programmato or len(eventi_significativi) > 0
        
        # Debug
        if devo_inviare:
            motivo = []
            if e_orario_programmato:
                motivo.append(f"Orario programmato: {ora_corrente:02d}:{minuto_corrente:02d}")
            if eventi_significativi:
                motivo.append(f"Eventi: {', '.join(eventi_significativi)}")
            print(f"📤 Invio Telegram - Motivo: {' | '.join(motivo)}")
        else:
            print(f"⏭️  Nessun invio Telegram - Ora: {ora_corrente}:58, nessun evento significativo")
        
        # Invia solo se necessario
        if devo_inviare:
            if not TELEGRAM_TOKEN or not LISTA_CHAT:
                print("✗ Telegram non configurato (manca token o lista chat); salto invio")
            else:
                url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                url_tg_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
                for chat_id in LISTA_CHAT:
                    try:
                        response = requests.post(
                            url_tg,
                            data={'chat_id': chat_id, 'text': testo_meteo, 'parse_mode': 'Markdown'},
                            timeout=10
                        )
                        response.raise_for_status()
                        tg_payload = response.json()
                        if tg_payload.get("ok"):
                            print(f"✓ Messaggio inviato a {chat_id}")
                        else:
                            print(f"✗ Telegram API testo errore per {chat_id}: {tg_payload}")
                    except Exception as e:
                        print(f"✗ Errore Telegram testo: {e}")
            
            # Genera e invia grafico 24h alle 11:58/59 e 23:58/59
            if e_orario_grafico:
                try:
                    grafico = genera_grafico_24h(storico)
                    if grafico:
                        for chat_id in LISTA_CHAT:
                            try:
                                grafico.seek(0)
                                response = requests.post(
                                    url_tg_photo,
                                    data={'chat_id': chat_id},
                                    files={'photo': ('meteo_24h.png', grafico, 'image/png')},
                                    timeout=15
                                )
                                response.raise_for_status()
                                tg_payload = response.json()
                                if tg_payload.get("ok"):
                                    print(f"✓ Grafico inviato a {chat_id}")
                                else:
                                    print(f"✗ Telegram API grafico errore per {chat_id}: {tg_payload}")
                            except Exception as e:
                                print(f"✗ Errore Telegram grafico: {e}")
                    else:
                        print("⏭️  Grafico non generato (dati insufficienti)")
                except Exception as e_graf:
                    print(f"⚠️  Errore grafico (non bloccante): {e_graf}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--sbcape":
        # Modalità standalone: calcola solo SBCAPE e salva su JSON
        calcola_e_salva_sbcape()
    else:
        esegui_report()