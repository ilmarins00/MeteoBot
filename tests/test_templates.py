import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from templates import render_analisi_semplice


def test_render_analisi_semplice_mentions_exposed_area_for_libeccio():
    text = render_analisi_semplice(
        obs={
            "temp_c": 24,
            "humidity_pct": 55,
            "wind_gust_kmh": 45,
            "wind_speed_kmh": 20,
            "wind_dir_deg": 225,
            "precip_rate_mm_h": 0,
            "cloud_cover_pct": 20,
            "wmo_code": 0,
            "visibility_m": 10000,
            "snow_level_m": 3000,
        },
        params={},
        hourly=None,
        giorno_label="Oggi",
    )

    assert "Portovenere" in text
    assert "all'imboccatura del Golfo" in text
