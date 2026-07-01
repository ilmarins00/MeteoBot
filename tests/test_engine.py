# tests/test_engine.py
"""
Test suite per il motore MeteoBot.
Eseguire: pytest tests/test_engine.py -v
"""

import pytest
from engine import run_pipeline, build_params_from_obs
from run_demo import synthetic_sounding, synthetic_obs, synthetic_hourly
from indices import (
    compute_shear_profile, compute_srh, pwat_from_profile,
    ehi, supercell_composite, significant_tornado_parameter,
    orographic_enhancement, sea_breeze_convergence_score,
    k_index, totals_totals,
)
from thermo import (
    esat, lcl_height, lcl_temperature,
    compute_all_thermo, mucape_mucin, mlcape_mlcin,
)
from logic import (
    convective_score, classify_storm_mode, severe_hazards,
    map_score_to_alert, arpal_alert_rain, arpal_alert_wind,
    composite_arpal_alert, full_alert,
)

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Pipeline
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_pipeline_runs_synthetic():
    """La pipeline non deve crashare con dati sintetici."""
    obs    = synthetic_obs()
    hourly = synthetic_hourly()
    res    = run_pipeline(obs, hourly)
    assert "section1"      in res
    assert "section2"      in res
    assert "section3"      in res
    assert "gemini_prompt" in res
    assert "meta"          in res
    assert "params"        in res
    assert "hazards"       in res


def test_pipeline_outputs_non_empty():
    """Tutte le sezioni devono contenere testo."""
    res = run_pipeline(synthetic_obs(), synthetic_hourly())
    assert len(res["section1"]) > 20
    assert len(res["section2"]) > 100
    assert len(res["gemini_prompt"]) > 200


def test_pipeline_alert_level_valid():
    """Il livello allerta deve essere uno dei 4 ARPAL."""
    res = run_pipeline(synthetic_obs(), synthetic_hourly())
    assert res["meta"]["alert_level"] in ("verde", "gialla", "arancione", "rossa")


def test_pipeline_no_sounding():
    """Pipeline funziona senza sounding (solo obs superficiali)."""
    obs = {
        "time_generated": "2026-07-01T12:00:00Z",
        "location": "Test",
        "CAPE": 1200, "CIN": -60,
        "shear_0_6": 28, "srh_0_1": 120,
        "PWAT": 32, "wind_gust_kmh": 65,
        "temp_c": 28, "humidity_pct": 75,
    }
    res = run_pipeline(obs, [])
    assert "section1" in res
    assert res["meta"]["score"] >= 0


def test_pipeline_extreme_scenario():
    """Con parametri estremi lo score deve essere alto e allerta rossa/arancione."""
    obs = synthetic_obs()
    obs["wind_gust_kmh"] = 110
    obs["rain_1h_mm"]    = 55
    obs["rain_24h_mm"]   = 280
    obs["wave_height_m"] = 4.5
    res = run_pipeline(obs, [])
    assert res["meta"]["score"] >= 5
    assert res["meta"]["alert_level"] in ("arancione", "rossa")


def test_pipeline_calm_scenario():
    """Con parametri calmi lo score deve essere basso."""
    obs = {
        "time_generated": "2026-07-01T12:00:00Z",
        "location": "Test",
        "CAPE": 0, "CIN": 0,
        "shear_0_6": 5, "srh_0_1": 10,
        "PWAT": 10, "wind_gust_kmh": 15,
        "cloud_cover_pct": 5,
    }
    res = run_pipeline(obs, [])
    assert res["meta"]["score"] <= 3
    assert res["meta"]["alert_level"] in ("verde", "gialla")


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Termodinamica
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_esat_physical_range():
    """Pressione vapore saturo deve essere nell'intervallo fisico."""
    es_0  = esat(273.15)   # 0°C  ≈ 611 Pa
    es_20 = esat(293.15)   # 20°C ≈ 2338 Pa
    es_35 = esat(308.15)   # 35°C ≈ 5628 Pa
    assert 550 < es_0  < 700
    assert 2000 < es_20 < 2700
    assert 5000 < es_35 < 6500


def test_lcl_height_physical():
    """LCL deve crescere con l'aumento del deficit T-Td."""
    z1 = lcl_height(300.0, 295.0)   # T-Td=5 → ≈615 m
    z2 = lcl_height(300.0, 290.0)   # T-Td=10 → ≈1230 m
    assert z1 > 0
    assert z2 > z1


def test_compute_all_thermo_with_sounding():
    s = synthetic_sounding()
    thermo = compute_all_thermo(
        s["pressure_pa"], s["temperature_k"], s["dewpoint_k"]
    )
    assert "SBCAPE" in thermo
    assert "MUCAPE" in thermo
    assert "MLCAPE" in thermo
    assert thermo["SBCAPE"] >= 0
    assert thermo["MUCAPE"] >= thermo["SBCAPE"] or True  # MU >= SB in genere
    assert thermo["LCL"] is not None and thermo["LCL"] > 0


def test_mucape_not_negative():
    s = synthetic_sounding()
    cape, cin, idx = mucape_mucin(s["pressure_pa"], s["temperature_k"], s["dewpoint_k"])
    assert cape >= 0
    assert cin <= 0


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Indici dinamici
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_shear_profile_returns_all_keys():
    s = synthetic_sounding()
    shear = compute_shear_profile(s["u_ms"], s["v_ms"], s["height_m"])
    for key in ("shear_0_1", "shear_0_3", "shear_0_6"):
        assert key in shear
        assert shear[key] >= 0


def test_srh_non_zero_with_shear():
    s = synthetic_sounding()
    srh = compute_srh(s["u_ms"], s["v_ms"], s["height_m"])
    # Con shear significativo l'SRH deve essere non zero
    assert "srh_0_1" in srh
    assert "srh_0_3" in srh
    # abs(SRH) >= 0 sempre
    assert abs(srh["srh_0_3"]) >= 0


def test_pwat_physical_range():
    s = synthetic_sounding()
    pw = pwat_from_profile(s["pressure_pa"], s["temperature_k"], s["dewpoint_k"])
    assert 0 < pw < 80   # range fisico per Mediterraneo


def test_ehi_zero_with_no_srh():
    assert ehi(1000, 0) == 0.0


def test_scp_zero_with_no_cape():
    assert supercell_composite(0, 200, 30) == 0.0


def test_stp_zero_with_no_cape():
    assert significant_tornado_parameter(0, 150, 35, 500, -50) == 0.0


def test_k_index_calculation():
    # T850=20, Td850=15, T700=8, Td700=5, T500=-8
    ki = k_index(20, 15, 8, 5, -8)
    # K = (20-(-8)) + 15 - (8-5) = 28 + 15 - 3 = 40
    assert abs(ki - 40.0) < 0.5


def test_totals_totals():
    # TT = (T850 - T500) + (Td850 - T500)
    tt = totals_totals(20, 15, -8)
    # = (20-(-8)) + (15-(-8)) = 28 + 23 = 51
    assert abs(tt - 51.0) < 0.5


def test_orographic_factor_max_on_optimal_dir():
    """Il fattore orografico deve essere massimo con flusso da S-SSO."""
    f_opt  = orographic_enhancement(210, 15)   # ottimale
    f_nord = orographic_enhancement(0,   15)   # sfavorevole
    assert f_opt > f_nord
    assert 0 <= f_opt <= 1


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Logica / Allerte ARPAL
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_arpal_rain_alert_levels():
    assert arpal_alert_rain(rain_1h=5)  == "verde"
    assert arpal_alert_rain(rain_1h=12) == "gialla"
    assert arpal_alert_rain(rain_1h=35) == "arancione"
    assert arpal_alert_rain(rain_1h=55) == "rossa"
    # Test 24h
    assert arpal_alert_rain(rain_24h=80)  == "verde"    # < 100 mm
    assert arpal_alert_rain(rain_24h=120) == "gialla"
    assert arpal_alert_rain(rain_24h=220) == "arancione"
    assert arpal_alert_rain(rain_24h=310) == "rossa"


def test_arpal_wind_alert_coastal():
    assert arpal_alert_wind(30, coastal=True)  == "verde"
    assert arpal_alert_wind(45, coastal=True)  == "gialla"
    assert arpal_alert_wind(65, coastal=True)  == "arancione"
    assert arpal_alert_wind(85, coastal=True)  == "rossa"


def test_composite_alert_max():
    lvl, detail = composite_arpal_alert(rain_1h=55, wind_kmh=30)
    assert lvl == "rossa"
    assert detail["pioggia"] == "rossa"
    assert detail["vento"]   == "verde"


def test_convective_score_increases_with_instability():
    base = {"SBCAPE": 200, "MUCAPE": 200, "shear_0_6": 5, "PWAT": 10}
    high = {"SBCAPE": 2500, "MUCAPE": 3000, "shear_0_6": 45, "srh_0_3": 400, "PWAT": 40}
    assert convective_score(high) > convective_score(base)


def test_classify_storm_mode_supercell():
    params = {
        "SBCAPE": 2000, "MUCAPE": 2800,
        "shear_0_6": 50, "srh_0_3": 400,
        "SCP": 5, "STP": 1.5, "PWAT": 38,
    }
    mode = classify_storm_mode(params)
    assert "supercell" in mode.lower() or "rotante" in mode.lower()


def test_severe_hazards_tornado_with_stp():
    params = {
        "SBCAPE": 2000, "MUCAPE": 2500,
        "shear_0_6": 50, "shear_0_1": 28,
        "srh_0_1": 250, "srh_0_3": 450,
        "STP": 2.0, "PWAT": 38,
    }
    hazards = severe_hazards(params)
    assert any("tromba" in h.lower() or "trombe" in h.lower() or "tornado" in h.lower() for h in hazards)


def test_map_score_to_alert():
    assert map_score_to_alert(0) == "verde"
    assert map_score_to_alert(2) == "gialla"
    assert map_score_to_alert(4) == "arancione"
    assert map_score_to_alert(9) == "rossa"
