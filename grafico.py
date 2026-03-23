#!/usr/bin/env python3
"""
grafico.py — Generatore grafico 24h per MeteoBot
=================================================
4 pannelli:
  1. Temperatura (°C) + Punto di rugiada (°C)
  2. Pressione MSL (hPa) + SBCAPE e MUCAPE (J/kg) su asse secondario
  3. Vento medio + Raffica max (km/h) + Pioggia 1h (mm) su asse secondario
  4. Temperature agli strati di quota: 850, 700, 500 hPa (Open-Meteo)
"""

import json
import os
import io
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_ROME = ZoneInfo("Europe/Rome")

BG_FIGURE    = "#1a1a2e"
BG_AXES      = "#16213e"
COLOR_GRID   = "#2a2a4a"
COLOR_TEMP   = "#ff6b6b"
COLOR_DEW    = "#4ecdc4"
COLOR_PRESS  = "#4a90d9"
COLOR_SBCAPE = "#f7b731"
COLOR_MUCAPE = "#fc5c65"
COLOR_WIND   = "#a8e063"
COLOR_GUST   = "#f7b731"
COLOR_RAIN   = "#45aaf2"
COLOR_T850   = "#ff9ff3"
COLOR_T700   = "#feca57"
COLOR_T500   = "#48dbfb"
COLOR_TEXT   = "#e0e0e0"
COLOR_SPINE  = "#333355"

_OM_CACHE = {}
_OM_CACHE_TTL = 1800


def _carica_storico(filepath="storico_24h.json"):
    for path in [filepath, os.path.join(os.path.dirname(__file__), filepath)]:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
    return []


def _parse_storico(storico):
    now = datetime.now(TZ_ROME)
    cutoff = now - timedelta(hours=24)
    times, temps, dews = [], [], []
    pressioni, sbcapes, mucapes = [], [], []
    venti, raffiche, piogge = [], [], []
    for s in storico:
        ts_str = s.get("ts")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ_ROME)
        except Exception:
            continue
        if ts < cutoff:
            continue
        temp  = s.get("temp")
        press = s.get("pressione")
        if temp is None or press is None:
            continue
        times.append(ts)
        temps.append(float(temp))
        dews.append(float(s["dew_point"]) if s.get("dew_point") is not None else float("nan"))
        pressioni.append(float(press))
        sbcapes.append(float(s.get("sbcape") or 0))
        mucapes.append(float(s.get("mucape") or 0))
        venti.append(float(s.get("vento") or 0))
        raffiche.append(float(s.get("raffica") or 0))
        piogge.append(float(s.get("pioggia_1h") or 0))
    if times:
        order = sorted(range(len(times)), key=lambda i: times[i])
        times     = [times[i]     for i in order]
        temps     = [temps[i]     for i in order]
        dews      = [dews[i]      for i in order]
        pressioni = [pressioni[i] for i in order]
        sbcapes   = [sbcapes[i]   for i in order]
        mucapes   = [mucapes[i]   for i in order]
        venti     = [venti[i]     for i in order]
        raffiche  = [raffiche[i]  for i in order]
        piogge    = [piogge[i]    for i in order]
    return {
        "times": times, "temps": temps, "dews": dews,
        "pressioni": pressioni, "sbcapes": sbcapes, "mucapes": mucapes,
        "venti": venti, "raffiche": raffiche, "piogge": piogge,
    }


def _fetch_altitude_temps(lat, lon):
    global _OM_CACHE
    key = f"{lat},{lon}"
    now_ts = time.time()
    if key in _OM_CACHE and now_ts - _OM_CACHE[key]["ts"] < _OM_CACHE_TTL:
        return _OM_CACHE[key]["data"]
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "hourly": "temperature_850hPa,temperature_700hPa,temperature_500hPa",
                "past_days": 1, "forecast_days": 0,
                "timezone": "Europe/Rome",
            },
            timeout=15,
        )
        r.raise_for_status()
        hourly = r.json().get("hourly", {})
        times_str = hourly.get("time", [])
        t850 = hourly.get("temperature_850hPa", [])
        t700 = hourly.get("temperature_700hPa", [])
        t500 = hourly.get("temperature_500hPa", [])
        now_rome = datetime.now(TZ_ROME)
        cutoff = now_rome - timedelta(hours=25)
        at, p850, p700, p500 = [], [], [], []
        for i, ts_str in enumerate(times_str):
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=TZ_ROME)
                if ts >= cutoff:
                    at.append(ts)
                    p850.append(t850[i] if i < len(t850) else None)
                    p700.append(t700[i] if i < len(t700) else None)
                    p500.append(t500[i] if i < len(t500) else None)
            except Exception:
                continue
        result = {"times": at, "t850": p850, "t700": p700, "t500": p500}
        _OM_CACHE[key] = {"ts": now_ts, "data": result}
        print(f"✓ Temperature alti livelli: {len(at)} campioni")
        return result
    except Exception as e:
        print(f"⚠️  Fetch altitude temps error: {e}")
        return None


def _tendenza_label(pressioni):
    if len(pressioni) < 2:
        return "stabile"
    delta = pressioni[-1] - pressioni[0]
    if delta >= 3:    return f"+{delta:.1f} forte aumento"
    elif delta >= 1:  return f"+{delta:.1f} in aumento"
    elif delta > -1:  return f"{delta:+.1f} stabile"
    elif delta > -3:  return f"{delta:.1f} in calo"
    else:             return f"{delta:.1f} forte calo"


def genera_grafico_24h(
    storico_path="storico_24h.json",
    titolo_stazione="La Spezia",
    lat=44.12514,
    lon=9.79706,
):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.ticker as mticker
        import numpy as np
    except ImportError:
        print("⚠️  matplotlib non disponibile, grafico saltato")
        return None

    storico = _carica_storico(storico_path)
    dati    = _parse_storico(storico)
    if len(dati["times"]) < 3:
        print(f"⚠️  Storico insufficiente ({len(dati['times'])} punti)")
        return None

    times     = dati["times"]
    temps     = dati["temps"]
    dews      = dati["dews"]
    pressioni = dati["pressioni"]
    sbcapes   = dati["sbcapes"]
    mucapes   = dati["mucapes"]
    venti     = dati["venti"]
    raffiche  = dati["raffiche"]
    piogge    = dati["piogge"]

    alt_data = _fetch_altitude_temps(lat, lon)
    now      = datetime.now(TZ_ROME)
    titolo   = f"Andamento 24h — {titolo_stazione}  |  {now.strftime('%d/%m/%Y %H:%M')}"

    fig, axes = plt.subplots(
        4, 1, figsize=(10, 13), dpi=110,
        gridspec_kw={"height_ratios": [3, 2.5, 2.5, 2.5]},
    )
    fig.patch.set_facecolor(BG_FIGURE)
    fig.suptitle(titolo, color=COLOR_TEXT, fontsize=12, y=0.987, va="top")

    def _style(ax):
        ax.set_facecolor(BG_AXES)
        ax.tick_params(colors=COLOR_TEXT, labelsize=8)
        ax.yaxis.label.set_color(COLOR_TEXT)
        for sp in ax.spines.values():
            sp.set_color(COLOR_SPINE)
        ax.grid(True, color=COLOR_GRID, linewidth=0.5, alpha=0.7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ_ROME))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=3, tz=TZ_ROME))
        ax.tick_params(axis="x", labelsize=7)

    x_min = min(times)
    x_max = max(times) + timedelta(minutes=15)

    # ── P1: Temperatura + Punto di rugiada ────────────────────────────────────
    ax1 = axes[0]
    _style(ax1)
    ax1.plot(times, temps, color=COLOR_TEMP, linewidth=1.8,
             label="Temperatura (°C)", zorder=3)
    dews_np  = np.array(dews, dtype=float)
    valid_dw = ~np.isnan(dews_np)
    if valid_dw.sum() >= 2:
        tn = np.array(times)
        ax1.plot(tn[valid_dw], dews_np[valid_dw], color=COLOR_DEW,
                 linewidth=1.2, linestyle="--",
                 label="Punto di rugiada (°C)", zorder=3)
        ta  = np.array(temps, dtype=float)
        tda = np.where(valid_dw, dews_np, ta)
        ax1.fill_between(times, ta, tda, alpha=0.12, color=COLOR_TEMP, zorder=2)
    t_min, t_max = min(temps), max(temps)
    ax1.annotate(f"{t_min:.1f}°C", xy=(times[temps.index(t_min)], t_min),
                 xytext=(0, -14), textcoords="offset points",
                 color=COLOR_TEMP, fontsize=7.5, ha="center")
    ax1.annotate(f"{t_max:.1f}°C", xy=(times[temps.index(t_max)], t_max),
                 xytext=(0, 6), textcoords="offset points",
                 color=COLOR_TEMP, fontsize=7.5, ha="center")
    ax1.set_ylabel("°C")
    ax1.legend(loc="upper left", fontsize=7.5, facecolor=BG_AXES,
               labelcolor=COLOR_TEXT, edgecolor=COLOR_SPINE, framealpha=0.8)
    ax1.set_xlim(x_min, x_max)

    # ── P2: Pressione + SBCAPE + MUCAPE ──────────────────────────────────────
    ax2 = axes[1]
    _style(ax2)
    ax2.plot(times, pressioni, color=COLOR_PRESS, linewidth=1.6,
             label="Pressione (hPa)", zorder=3)
    ax2.fill_between(times, pressioni, min(pressioni) - 1,
                     alpha=0.12, color=COLOR_PRESS, zorder=2)
    cutoff_3h = now - timedelta(hours=3)
    p3h = [p for t, p in zip(times, pressioni) if t >= cutoff_3h]
    tend = _tendenza_label(p3h)
    ax2.annotate(
        f"{pressioni[-1]:.0f} hPa  |  {tend} hPa",
        xy=(times[-1], pressioni[-1]), xytext=(-5, 6),
        textcoords="offset points", color=COLOR_PRESS, fontsize=7, ha="right",
    )
    ax2.set_ylabel("hPa")
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    ax2.legend(loc="upper left", fontsize=7.5, facecolor=BG_AXES,
               labelcolor=COLOR_TEXT, edgecolor=COLOR_SPINE, framealpha=0.8)
    # Asse secondario CAPE
    ax2b = ax2.twinx()
    ax2b.set_facecolor(BG_AXES)
    for sp in ax2b.spines.values():
        sp.set_color(COLOR_SPINE)
    max_cape = max(max(sbcapes + [1]), max(mucapes + [1]))
    if max_cape > 10:
        ax2b.fill_between(times, sbcapes, alpha=0.25, color=COLOR_SBCAPE, zorder=2)
        ax2b.plot(times, sbcapes, color=COLOR_SBCAPE, linewidth=1.1, zorder=3)
        if any(m > 0 for m in mucapes):
            ax2b.plot(times, mucapes, color=COLOR_MUCAPE, linewidth=1.2,
                      linestyle=":", zorder=3)
        ax2b.set_ylabel("CAPE J/kg", color=COLOR_SBCAPE, fontsize=7.5, rotation=270, labelpad=14)
        ax2b.tick_params(axis="y", colors=COLOR_SBCAPE, labelsize=7)
        ax2b.set_ylim(0, max_cape * 1.35)
        handles_cape = [plt.Line2D([0], [0], color=COLOR_SBCAPE, lw=2, label="SBCAPE")]
        if any(m > 0 for m in mucapes):
            handles_cape.append(plt.Line2D([0], [0], color=COLOR_MUCAPE,
                                           lw=1.5, linestyle=":", label="MUCAPE"))
        ax2b.legend(handles=handles_cape, loc="upper right", fontsize=7,
                    facecolor=BG_AXES, labelcolor=COLOR_TEXT,
                    edgecolor=COLOR_SPINE, framealpha=0.8)
    else:
        ax2b.set_yticks([])
        ax2b.set_ylabel("CAPE: 0 J/kg", color=COLOR_TEXT, fontsize=7,
                        rotation=270, labelpad=14)
    ax2.set_xlim(x_min, x_max)
    ax2b.set_xlim(x_min, x_max)

    # ── P3: Vento + Raffica + Pioggia (asse secondario) ───────────────────────
    ax3 = axes[2]
    _style(ax3)
    # Pioggia su asse secondario
    ax3b = ax3.twinx()
    ax3b.set_facecolor(BG_AXES)
    for sp in ax3b.spines.values():
        sp.set_color(COLOR_SPINE)
    if len(times) >= 2:
        dt_s = (times[-1] - times[0]).total_seconds() / max(len(times) - 1, 1)
        bar_w = min(dt_s * 0.60, 2700) / 86400
    else:
        bar_w = 0.025
    bcolors = ["#ff4757" if p >= 15 else "#ffa502" if p >= 6 else COLOR_RAIN
               for p in piogge]
    ax3b.bar(times, piogge, width=bar_w, color=bcolors,
             align="center", alpha=0.55, zorder=2)
    tot = sum(piogge)
    ax3b.set_ylabel(f"mm/h   tot: {tot:.1f} mm",
                    color=COLOR_RAIN, fontsize=7.5, rotation=270, labelpad=16)
    ax3b.tick_params(axis="y", colors=COLOR_RAIN, labelsize=7)
    ax3b.set_ylim(0, max(max(piogge) * 1.3, 5))
    # Vento e raffica sull'asse primario
    ax3.plot(times, raffiche, color=COLOR_GUST, linewidth=1.2, linestyle="--",
             label="Raffica max (km/h)", zorder=4, alpha=0.9)
    ax3.plot(times, venti, color=COLOR_WIND, linewidth=1.6,
             label="Vento medio (km/h)", zorder=5)
    ax3.fill_between(times, raffiche, venti, alpha=0.10, color=COLOR_GUST, zorder=3)
    if raffiche and max(raffiche) >= 25:
        r_max = max(raffiche)
        ax3.annotate(f"{r_max:.0f}", xy=(times[raffiche.index(r_max)], r_max),
                     xytext=(0, 5), textcoords="offset points",
                     color=COLOR_GUST, fontsize=7, ha="center")
    ax3.set_ylabel("km/h")
    ax3.legend(loc="upper left", fontsize=7.5, facecolor=BG_AXES,
               labelcolor=COLOR_TEXT, edgecolor=COLOR_SPINE, framealpha=0.8)
    ax3.set_xlim(x_min, x_max)
    ax3b.set_xlim(x_min, x_max)

    # ── P4: Temperature alti livelli ──────────────────────────────────────────
    ax4 = axes[3]
    _style(ax4)
    if alt_data and alt_data.get("times"):
        at = alt_data["times"]

        def _plot_lvl(vals, color, label):
            ct, cv = zip(*[(t, v) for t, v in zip(at, vals) if v is not None]) if any(v is not None for v in vals) else ([], [])
            if len(ct) >= 2:
                ax4.plot(ct, cv, color=color, linewidth=1.5, label=label, zorder=3)
                ax4.annotate(f"{cv[-1]:.1f}°", xy=(ct[-1], cv[-1]),
                             xytext=(4, 0), textcoords="offset points",
                             color=color, fontsize=7, va="center")

        _plot_lvl(alt_data["t850"], COLOR_T850, "850 hPa (~1500 m)")
        _plot_lvl(alt_data["t700"], COLOR_T700, "700 hPa (~3000 m)")
        _plot_lvl(alt_data["t500"], COLOR_T500, "500 hPa (~5500 m)")
        ax4.axhline(0, color="#aaaaaa", linewidth=0.8, linestyle=":", alpha=0.6)
        ax4.set_ylabel("°C")
        ax4.legend(loc="upper left", fontsize=7.5, facecolor=BG_AXES,
                   labelcolor=COLOR_TEXT, edgecolor=COLOR_SPINE, framealpha=0.8)
    else:
        ax4.text(0.5, 0.5, "Dati alti livelli non disponibili",
                 transform=ax4.transAxes, ha="center", va="center",
                 color=COLOR_TEXT, fontsize=9)
    ax4.set_xlim(x_min, x_max)
    ax4.set_xlabel("Ora (Europe/Rome)", color=COLOR_TEXT)
    ax4.tick_params(axis="x", labelsize=7)

    # Nascondi etichette X per i pannelli 1-3
    for ax in axes[:3]:
        ax.tick_params(axis="x", labelbottom=False)

    plt.tight_layout(rect=[0, 0, 1, 0.975])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    img_bytes = buf.read()
    print(f"✓ Grafico 24h generato: {len(img_bytes) // 1024} KB, "
          f"{len(times)} campioni storico")
    return img_bytes


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "grafico_24h.png"
    try:
        from config import LATITUDE, LONGITUDE
    except ImportError:
        LATITUDE, LONGITUDE = 44.12514, 9.79706
    img = genera_grafico_24h(lat=LATITUDE, lon=LONGITUDE)
    if img:
        with open(out, "wb") as f:
            f.write(img)
        print(f"Salvato: {out}")
    else:
        sys.exit(1)
