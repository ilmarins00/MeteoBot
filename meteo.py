import time
import hmac
import hashlib
import requests
import json
import os
import math
import io
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
    thresholds,
    LATITUDE,
    LONGITUDE,
    TIMEZONE
)
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
    """Genera un grafico con temperatura, pressione, pioggia e indici delle ultime 24h.
    Restituisce un buffer BytesIO con l'immagine PNG."""
    if len(storico) < 3:
        return None
    
    try:
        timestamps = []
        temperature = []
        pressioni = []
        piogge = []
        umidita = []
        api_values = []
        sbcape_values = []
        mucape_values = []
        theta_e_values = []
        
        for s in storico:
            try:
                ts = datetime.fromisoformat(s["ts"])
                timestamps.append(ts)
                temperature.append(s.get("temp", None))
                pressioni.append(s.get("pressione", None))
                piogge.append(s.get("pioggia_1h", 0))
                umidita.append(s.get("umidita", None))
                api_values.append(s.get("api", None))
                sbcape_values.append(s.get("sbcape", None))
                mucape_values.append(s.get("mucape", None))
                theta_e_values.append(s.get("theta_e", None))
            except:
                continue
        
        if len(timestamps) < 3:
            return None
        
        fig, axes = plt.subplots(4, 1, figsize=(11, 11), sharex=True)
        fig.suptitle('Stazione Meteo La Spezia - Foce (24h)', fontsize=14, fontweight='bold')
        
        # --- Temperatura ---
        ax1 = axes[0]
        temp_valide = [(t, v) for t, v in zip(timestamps, temperature) if v is not None]
        if temp_valide:
            t_ts, t_vals = zip(*temp_valide)
            ax1.plot(t_ts, t_vals, color='#e74c3c', linewidth=2, marker='.', markersize=4)
            ax1.fill_between(t_ts, t_vals, alpha=0.15, color='#e74c3c')
        ax1.set_ylabel('Temperatura (°C)', fontsize=10)
        ax1.grid(True, alpha=0.3)
        ax1.tick_params(labelsize=8)
        
        # --- Pressione MSL ---
        ax2 = axes[1]
        pres_valide = [(t, v) for t, v in zip(timestamps, pressioni) if v is not None]
        if pres_valide:
            p_ts, p_vals = zip(*pres_valide)
            ax2.plot(p_ts, p_vals, color='#3498db', linewidth=2, marker='.', markersize=4)
            ax2.fill_between(p_ts, p_vals, alpha=0.15, color='#3498db')
        ax2.set_ylabel('Pressione MSL (hPa)', fontsize=10)
        ax2.grid(True, alpha=0.3)
        ax2.tick_params(labelsize=8)
        
        # --- Pioggia + Umidità ---
        ax3 = axes[2]
        ax3.bar(timestamps, piogge, width=0.03, color='#2ecc71', alpha=0.7, label='Pioggia 1h (mm)')
        ax3.set_ylabel('Pioggia (mm)', fontsize=10, color='#2ecc71')
        ax3.tick_params(axis='y', labelcolor='#2ecc71', labelsize=8)
        ax3.grid(True, alpha=0.3)
        
        ax3b = ax3.twinx()
        umid_valide = [(t, v) for t, v in zip(timestamps, umidita) if v is not None]
        if umid_valide:
            u_ts, u_vals = zip(*umid_valide)
            ax3b.plot(u_ts, u_vals, color='#9b59b6', linewidth=1.5, alpha=0.7, label='Umidità %')
        ax3b.set_ylabel('Umidità (%)', fontsize=10, color='#9b59b6')
        ax3b.tick_params(axis='y', labelcolor='#9b59b6', labelsize=8)
        ax3b.set_ylim(0, 105)

        # --- API + SBCAPE + MUCAPE + Theta-e ---
        ax4 = axes[3]
        api_valide = [(t, v) for t, v in zip(timestamps, api_values) if isinstance(v, (int, float))]
        if api_valide:
            a_ts, a_vals = zip(*api_valide)
            ax4.plot(a_ts, a_vals, color='#16a085', linewidth=2, marker='.', markersize=3)
        ax4.set_ylabel('API (mm)', fontsize=9, color='#16a085')
        ax4.tick_params(axis='y', labelcolor='#16a085', labelsize=8)
        ax4.grid(True, alpha=0.3)

        ax4b = ax4.twinx()
        sb_valide = [(t, v) for t, v in zip(timestamps, sbcape_values) if isinstance(v, (int, float))]
        mu_valide = [(t, v) for t, v in zip(timestamps, mucape_values) if isinstance(v, (int, float))]
        if sb_valide:
            sb_ts, sb_vals = zip(*sb_valide)
            ax4b.plot(sb_ts, sb_vals, color='#f39c12', linewidth=1.5, alpha=0.85)
        if mu_valide:
            mu_ts, mu_vals = zip(*mu_valide)
            ax4b.plot(mu_ts, mu_vals, color='#c0392b', linewidth=1.5, alpha=0.85, linestyle='--')
        ax4b.set_ylabel('CAPE (J/kg)', fontsize=9, color='#f39c12')
        ax4b.tick_params(axis='y', labelcolor='#f39c12', labelsize=8)

        ax4c = ax4.twinx()
        ax4c.spines['right'].set_position(('axes', 1.1))
        th_valide = [(t, v) for t, v in zip(timestamps, theta_e_values) if isinstance(v, (int, float))]
        if th_valide:
            th_ts, th_vals = zip(*th_valide)
            ax4c.plot(th_ts, th_vals, color='#8e44ad', linewidth=1.3, alpha=0.8)
        ax4c.set_ylabel('Theta-e (°C)', fontsize=9, color='#8e44ad')
        ax4c.tick_params(axis='y', labelcolor='#8e44ad', labelsize=8)
        
        # Formattazione asse X
        ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=TZ_ROME))
        ax4.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        ax4.set_xlabel('Ora', fontsize=10)
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
        pioggia_24h = d.get('rain_24h', 0) / 10
        pioggia_1h = d.get('rain_1h', 0) / 10  # Intensità pioggia ultima ora
        
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

        # --- LEGGI SBCAPE (Spostato PRIMA degli avvisi per poter generare l'alert) ---
        sbcape_str = ""
        sbcape_value = 0
        mucape_value = 0
        cin_value = 0
        li_value = None
        bulk_shear = 0
        severe_score = 0
        severe_warning = None
        try:
            if os.path.exists("sbcape.json"):
                with open("sbcape.json", "r") as f:
                    sbcape_data = json.load(f)
                    sbcape_value = sbcape_data.get("sbcape") or 0
                    mucape_value = sbcape_data.get("mucape") or 0
                    cin_value = sbcape_data.get("cin") or 0
                    li_value = sbcape_data.get("lifted_index")
                    bulk_shear = sbcape_data.get("bulk_shear") or 0
                    severe_score = sbcape_data.get("severe_score") or 0
                    severe_warning = sbcape_data.get("severe_warning")
        except Exception as e:
            print(f"Errore lettura SBCAPE: {e}")

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
            "theta_e": classifica_massa_aria(temp_ext, dew_point, pressione_msl, mese_corrente).get("theta_e")
        })
        salva_storico(storico)
        
        # ARPAL alerts are handled by monitor_arpal.py now; skip scraping here
        arpal_str = ""
        arpal_livello = "Verde"
        
        # --- LOGICA AVVISI ---
        avvisi = []
        
        # ARPAL handled separately by monitor_arpal.py
        
        # Nebbia/foschia (solo con umidità >= 99%)
        diff_temp_dew = temp_ext - dew_point
        if umid_ext >= 99 and diff_temp_dew <= 0.5:
            if v_medio < 5:
                avvisi.append("🌫️ AVVISO: NEBBIA")
            else:
                avvisi.append("🌫️ AVVISO: FOSCHIA")
        
        # vento: soglie crescenti
        if raffica > 80:
            avvisi.append("⚠️ AVVISO: BURRASCA FORTE")
        elif raffica > 60:
            avvisi.append("⚠️ AVVISO: BURRASCA")
        elif raffica > 40:
            avvisi.append("⚠️ AVVISO: VENTO FORTE")

        # temperatura
        if temp_ext > 35:
            avvisi.append("🔥 AVVISO: CALDO INTENSO")
        elif temp_ext <= 0:
            avvisi.append("❄️ AVVISO: GELO")

        # afa invariata
        if temp_ext > 25 and umid_ext > 60:
            avvisi.append("🥵 AVVISO: AFA")

        # pressione invariata (usa MSL per confronti standard)
        if pressione_msl < 990:
            avvisi.append("🌊 AVVISO: MAREGGIATE GRAVI")
        elif pressione_msl < 995:
            avvisi.append("🌊 AVVISO: MAREGGIATE")

        # precipitazioni e API/suolo
        if pioggia_1h > 15:
            avvisi.append("🌧️ AVVISO: PIOGGIA MOLTO FORTE")
        elif pioggia_1h >= 6:
            avvisi.append("🌧️ AVVISO: PIOGGIA FORTE")

        if sat_visualizzato >= 170:
            avvisi.append("⛰️ AVVISO: SUOLO SATURO")
            if pioggia_24h > 30:
                avvisi.append("🌧️ AVVISO: CUMULATE MOLTO ELEVATE")
            elif pioggia_24h > 15:
                avvisi.append("🌧️ AVVISO: CUMULATE ELEVATE")
        else:
            if pioggia_24h > 100:
                avvisi.append("🌧️ AVVISO: CUMULATE MOLTO ELEVATE")
            elif pioggia_24h > 80:
                avvisi.append("🌧️ AVVISO: CUMULATE ELEVATE")
            elif pioggia_24h > 50:
                avvisi.append("🌧️ AVVISO: CUMULATE SIGNIFICATIVE")
        
        # --- AVVISO INSTABILITÀ CONVETTIVA (Severe Weather Score) ---
        # Usa il nuovo severe weather score se disponibile
        if severe_warning:
            avvisi.append(severe_warning)
        else:
            # Fallback: logica multi-parametro (più realistica)
            # Nota: bulk_shear è un proxy 10m-120m, quindi soglie conservative.
            max_cape = max(sbcape_value, mucape_value)
            cin_abs = abs(cin_value)
            li_ok = li_value is not None and li_value <= -2
            shear_ok = bulk_shear >= 8

            if (
                max_cape >= 1200
                and cin_abs <= 125
                and li_ok
                and shear_ok
            ):
                avvisi.append("⚡ AVVISO: RISCHIO FORTI TEMPORALI")
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
        e_orario_grafico = ora_corrente == 23 and minuto_corrente in minuti_report
        
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
        max_cape = max(sbcape_value, mucape_value)
        cin_abs = abs(cin_value)
        li_ok = li_value is not None and li_value <= -2
        shear_ok = bulk_shear >= 8
        rischio_forti_temporali = (
            max_cape >= 1200
            and cin_abs <= 125
            and li_ok
            and shear_ok
        )

        if rischio_forti_temporali:
            eventi_significativi.append(
                f"Rischio forti temporali (CAPE {max_cape:.0f} J/kg, CIN {cin_value:.0f} J/kg, "
                f"LI {li_value:.1f}°C, Shear {bulk_shear:.1f} m/s)"
            )
        
        # Severe Score elevato
        if severe_score >= 7:
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
            
            # Genera e invia grafico 24h solo alle 23:58/23:59
            if e_orario_grafico:
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

if __name__ == "__main__":


    esegui_report()
