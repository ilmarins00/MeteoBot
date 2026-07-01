import importlib
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _render_analisi_semplice(monkeypatch, **kwargs):
    monkeypatch.syspath_prepend(str(_PROJECT_ROOT))
    templates = importlib.import_module("templates")
    return templates.render_analisi_semplice(**kwargs)


def test_render_analisi_semplice_mentions_exposed_area_for_libeccio(monkeypatch):
    text = _render_analisi_semplice(
        monkeypatch,
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


def test_render_analisi_semplice_mentions_coast_for_other_winds(monkeypatch):
    text = _render_analisi_semplice(
        monkeypatch,
        obs={
            "temp_c": 24,
            "humidity_pct": 55,
            "wind_gust_kmh": 45,
            "wind_speed_kmh": 20,
            "wind_dir_deg": 90,
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

    assert "sulle zone esposte della costa" in text
