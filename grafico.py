#!/usr/bin/env python3
"""
grafico.py — Generatore grafico 24h per MeteoBot
=================================================
Legge storico_24h.json e produce un PNG con 4 pannelli:
  1. Temperatura (°C) + Punto di rugiada (°C)
  2. Pressione al livello del mare (hPa) con indicatore tendenza
  3. Velocità vento media + raffica max (km/h)
  4. Pioggia ultima ora (mm) — barchart

Il grafico viene restituito come bytes PNG oppure salvato su file.

Utilizzo autonomo:
    python grafico.py [output.png]

Utilizzo da altri script:
    from grafico import genera_grafico_24h
    img_bytes = genera_grafico_24h()   # None se storico insufficiente
"""

import json
import os
import io
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_ROME = ZoneInfo("Europe/Rome")

# Colori tema scuro coerente con la mappa fulmini
BG_FIGURE   = "#1a1a2e"
BG_AXES     = "#16213e"
COLOR_GRID  = "#2a2a4a"
COLOR_TEMP  = "#ff6b6b"
COLOR_DEW   = "#4ecdc4"
COLOR_PRESS = "#4a90d9"
COLOR_WIND  = "#a8e063"
COLOR_GUST  = "#f7b731"
COLOR_RAIN  = "#45aaf2"
COLOR_TEXT  = "#e0e0e0"
COLOR_SPINE = "#333355"


def _carica_storico(filepath: str = "storico_24h.json") -> list:
    """Carica lo storico. Cerca nella cwd e nella directory dello script."""
    for path in [filepath, os.path.join(os.path.dirname(__file__), filepath)]:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
    return []


def _parse_storico(storico: list) -> dict:
    """
    Filtra e ordina le ultime 24h di dati.
    Restituisce un dict con liste parallele pronte per matplotlib.
    """
    now = datetime.now(TZ_ROME)
    cutoff = now - timedelta(hours=24)

    times, temps, dews, pressioni, venti, raffiche, piogge = [], [], [], [], [], [], []

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

        temp     = s.get("temp")
        dew      = s.get("dew_point")
        press    = s.get("pressione")
        vento    = s.get("vento")
        raffica  = s.get("raffica")
        pioggia  = s.get("pioggia_1h", 0) or 0

        if temp is None or press is None:
            continue

        times.append(ts)
        temps.append(float(temp))
        dews.append(float(dew) if dew is not None else float("nan"))
        pressioni.append(float(press))
        venti.append(float(vento) if vento is not None else 0.0)
        raffiche.append(float(raffica) if raffica is not None else 0.0)
        piogge.append(float(pioggia))

    # Ordina per timestamp
    if times:
        order = sorted(range(len(times)), key=lambda i: times[i])
        times     = [times[i]     for i in order]
        temps     = [temps[i]     for i in order]
        dews      = [dews[i]      for i in order]
        pressioni = [pressioni[i] for i in order]
        venti     = [venti[i]     for i in order]
        raffiche  = [raffiche[i]  for i in order]
        piogge    = [piogge[i]    for i in order]

    return {
        "times": times,
        "temps": temps,
        "dews": dews,
        "pressioni": pressioni,
        "venti": venti,
        "raffiche": raffiche,
        "piogge": piogge,
    }


def _tendenza_label(pressioni: list) -> str:
    """Freccia di tendenza barometrica (ultime 3h)."""
    if len(pressioni) < 2:
        return "➡️"
    delta = pressioni[-1] - pressioni[0]
    if delta >= 3:
        return "⬆️ +{:.1f} hPa".format(delta)
    elif delta >= 1:
        return "↗️ +{:.1f} hPa".format(delta)
    elif delta > -1:
        return "➡️ {:.1f} hPa".format(delta)
    elif delta > -3:
        return "↘️ {:.1f} hPa".format(delta)
    else:
        return "⬇️ {:.1f} hPa".format(delta)


def genera_grafico_24h(
    storico_path: str = "storico_24h.json",
    titolo_stazione: str = "La Spezia",
) -> bytes | None:
    """
    Genera il grafico 24h e restituisce i bytes PNG.
    Ritorna None se i dati sono insufficienti o matplotlib non è disponibile.
    """
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
    dati = _parse_storico(storico)

    if len(dati["times"]) < 3:
        print(f"⚠️  Dati storico insufficienti ({len(dati['times'])} punti), grafico saltato")
        return None

    times     = dati["times"]
    temps     = dati["temps"]
    dews      = dati["dews"]
    pressioni = dati["pressioni"]
    venti     = dati["venti"]
    raffiche  = dati["raffiche"]
    piogge    = dati["piogge"]

    now = datetime.now(TZ_ROME)
    titolo = f"Andamento 24h — {titolo_stazione}  |  {now.strftime('%d/%m/%Y %H:%M')}"

    # ── Layout ────────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(
        4, 1,
        figsize=(10, 11),
        dpi=110,
        gridspec_kw={"height_ratios": [3, 2, 2, 2]},
    )
    fig.patch.set_facecolor(BG_FIGURE)
    fig.suptitle(titolo, color=COLOR_TEXT, fontsize=12, y=0.98, va="top")

    def _style_ax(ax):
        ax.set_facecolor(BG_AXES)
        ax.tick_params(colors=COLOR_TEXT, labelsize=8)
        ax.yaxis.label.set_color(COLOR_TEXT)
        ax.xaxis.label.set_color(COLOR_TEXT)
        for spine in ax.spines.values():
            spine.set_color(COLOR_SPINE)
        ax.grid(True, color=COLOR_GRID, linewidth=0.5, alpha=0.7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ_ROME))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=3, tz=TZ_ROME))
        ax.tick_params(axis="x", labelsize=7)

    # ── Pannello 1: Temperatura + Punto di rugiada ────────────────────────────
    ax1 = axes[0]
    _style_ax(ax1)
    ax1.plot(times, temps, color=COLOR_TEMP, linewidth=1.8, label="Temperatura (°C)", zorder=3)
    # Dew point — gestisci NaN
    dews_np = np.array(dews, dtype=float)
    valid_dew = ~np.isnan(dews_np)
    if valid_dew.sum() >= 2:
        times_np = np.array(times)
        ax1.plot(
            times_np[valid_dew], dews_np[valid_dew],
            color=COLOR_DEW, linewidth=1.2, linestyle="--",
            label="Punto di rugiada (°C)", zorder=3,
        )
    # Shading spread T–Td
    if valid_dew.sum() >= 2:
        t_arr  = np.array(temps, dtype=float)
        td_arr = np.where(valid_dew, dews_np, t_arr)
        ax1.fill_between(times, t_arr, td_arr, alpha=0.12, color=COLOR_TEMP, zorder=2)
    # Annotazioni min/max
    t_min, t_max = min(temps), max(temps)
    i_min = temps.index(t_min)
    i_max = temps.index(t_max)
    ax1.annotate(f"{t_min:.1f}°C", xy=(times[i_min], t_min),
                 xytext=(0, -14), textcoords="offset points",
                 color=COLOR_TEMP, fontsize=7.5, ha="center")
    ax1.annotate(f"{t_max:.1f}°C", xy=(times[i_max], t_max),
                 xytext=(0, 6), textcoords="offset points",
                 color=COLOR_TEMP, fontsize=7.5, ha="center")
    ax1.set_ylabel("°C")
    ax1.legend(loc="upper left", fontsize=7.5, facecolor=BG_AXES,
               labelcolor=COLOR_TEXT, edgecolor=COLOR_SPINE, framealpha=0.8)

    # ── Pannello 2: Pressione ─────────────────────────────────────────────────
    ax2 = axes[1]
    _style_ax(ax2)
    ax2.plot(times, pressioni, color=COLOR_PRESS, linewidth=1.6, zorder=3)
    ax2.fill_between(times, pressioni, min(pressioni) - 1,
                     alpha=0.15, color=COLOR_PRESS, zorder=2)
    # Tendenza ultime 3h
    cutoff_3h = now - timedelta(hours=3)
    press_3h = [p for t, p in zip(times, pressioni) if t >= cutoff_3h]
    tend = _tendenza_label(press_3h)
    press_attuale = pressioni[-1]
    ax2.annotate(
        f"{press_attuale:.1f} hPa  {tend}",
        xy=(times[-1], press_attuale),
        xytext=(-5, 6), textcoords="offset points",
        color=COLOR_PRESS, fontsize=7.5, ha="right",
    )
    ax2.set_ylabel("hPa")
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    # ── Pannello 3: Vento + Raffica ───────────────────────────────────────────
    ax3 = axes[2]
    _style_ax(ax3)
    ax3.plot(times, raffiche, color=COLOR_GUST, linewidth=1.2,
             linestyle="--", label="Raffica max (km/h)", zorder=3, alpha=0.9)
    ax3.plot(times, venti, color=COLOR_WIND, linewidth=1.6,
             label="Vento medio (km/h)", zorder=4)
    ax3.fill_between(times, raffiche, venti, alpha=0.12, color=COLOR_GUST, zorder=2)
    # Raffica massima
    if raffiche:
        r_max = max(raffiche)
        i_rmax = raffiche.index(r_max)
        if r_max >= 30:
            ax3.annotate(
                f"↑{r_max:.0f}", xy=(times[i_rmax], r_max),
                xytext=(0, 5), textcoords="offset points",
                color=COLOR_GUST, fontsize=7, ha="center",
            )
    ax3.set_ylabel("km/h")
    ax3.legend(loc="upper left", fontsize=7.5, facecolor=BG_AXES,
               labelcolor=COLOR_TEXT, edgecolor=COLOR_SPINE, framealpha=0.8)

    # ── Pannello 4: Pioggia 1h ────────────────────────────────────────────────
    ax4 = axes[3]
    _style_ax(ax4)
    pioggia_tot = sum(piogge)
    bar_colors = [
        "#ff4757" if p >= 15 else
        "#ffa502" if p >= 6  else
        COLOR_RAIN
        for p in piogge
    ]
    # Larghezza barre proporzionale alla densità temporale (max 45 min in secondi/giorni)
    if len(times) >= 2:
        dt_medio = (times[-1] - times[0]).total_seconds() / max(len(times) - 1, 1)
        bar_width = min(dt_medio * 0.7, 2700) / 86400  # in unità matplotlib (giorni)
    else:
        bar_width = 0.025
    ax4.bar(times, piogge, width=bar_width, color=bar_colors,
            align="center", zorder=3, alpha=0.85)
    ax4.set_ylabel("mm/h")
    # Totale 24h in etichetta asse y secondario
    ax4_r = ax4.twinx()
    ax4_r.set_facecolor(BG_AXES)
    ax4_r.set_yticks([])
    ax4_r.set_ylabel(f"Tot. 24h: {pioggia_tot:.1f} mm",
                     color=COLOR_RAIN, fontsize=8, rotation=270, labelpad=14)
    ax4_r.tick_params(colors=COLOR_TEXT)
    for spine in ax4_r.spines.values():
        spine.set_color(COLOR_SPINE)
    # Soglia minima asse y
    ymax_rain = max(max(piogge) * 1.25, 5)
    ax4.set_ylim(0, ymax_rain)
    ax4.set_xlabel("Ora (Europe/Rome)")
    ax4.xaxis.label.set_color(COLOR_TEXT)

    # ── Allinea assi X ────────────────────────────────────────────────────────
    x_min = min(times)
    x_max = max(times) + timedelta(minutes=15)
    for ax in axes:
        ax.set_xlim(x_min, x_max)

    plt.tight_layout(rect=[0, 0, 1, 0.97])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    img_bytes = buf.read()
    print(f"✓ Grafico 24h generato: {len(img_bytes) // 1024} KB, {len(times)} punti")
    return img_bytes


if __name__ == "__main__":
    import sys
    output_path = sys.argv[1] if len(sys.argv) > 1 else "grafico_24h.png"
    img = genera_grafico_24h()
    if img:
        with open(output_path, "wb") as f:
            f.write(img)
        print(f"Salvato in {output_path}")
    else:
        print("Grafico non generato")
        sys.exit(1)