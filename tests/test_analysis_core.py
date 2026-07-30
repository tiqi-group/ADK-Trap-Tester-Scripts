"""Headless regression tests for the analysis engine (``core.analysis``).

Run with ``uv run pytest tests/test_analysis_core.py``. No hardware needed —
these feed crafted results frames through the per-measurement analyses and
check the classification, the registry dispatch and the report rendering.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.settings import FilterSettings, load, save_result


def _filter_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # nominal, over-nominal (high C -> possible short), not detected, shorted
            {"DSUB connector": 0, "DSUB pin": 1, "Shorted": False,
             "C_filter_nF": 1.02, "R_filter_Ohm": 2010, "Bandwidth": 1e5, "Perr_max": 1e-3},
            {"DSUB connector": 0, "DSUB pin": 3, "Shorted": False,
             "C_filter_nF": 1.9, "R_filter_Ohm": 900, "Bandwidth": 1e5, "Perr_max": 1e-3},
            {"DSUB connector": 0, "DSUB pin": 5, "Shorted": False,
             "C_filter_nF": 0.02, "R_filter_Ohm": 2000, "Bandwidth": 1e5, "Perr_max": 1e-3},
            {"DSUB connector": 0, "DSUB pin": 6, "Shorted": True,
             "C_filter_nF": -1, "R_filter_Ohm": 0, "Bandwidth": -1, "Perr_max": -1},
        ]
    )


def test_filter_classification():
    res = A.analyse_filter(_filter_df(), A.FilterAnalysisSettings())
    statuses = [f.status for f in res.findings]
    assert statuses == ["ok", "above_limit", "not_detected", "shorted"]
    assert res.summary == {"ok": 1, "above_limit": 1, "not_detected": 1, "shorted": 1}
    assert res.n_faults == 3
    # the FPC-conductor mapping is applied
    assert res.findings[0].fpc_conductor is not None
    # every judged quantity is kept on the finding, not just the plotted one
    assert set(res.findings[0].values) == {"c", "r"}
    assert res.findings[1].failed == ["c"]


def test_filter_below_band_is_below_limit():
    # a detectable cap below the acceptance window, but above the detection floor
    df = pd.DataFrame(
        [{"DSUB connector": 0, "DSUB pin": 1, "Shorted": False,
          "C_filter_nF": 0.6, "R_filter_Ohm": 2000}]
    )
    res = A.analyse_filter(df, A.FilterAnalysisSettings())
    assert res.findings[0].status == "below_limit"


def test_filter_limits_are_configurable():
    # a wide-open C window turns the above-limit pin nominal
    res = A.analyse_filter(
        _filter_df(), A.FilterAnalysisSettings(c_min_nf=0.0, c_max_nf=2.0)
    )
    assert [f.status for f in res.findings] == ["ok", "ok", "not_detected", "shorted"]


def test_filter_resistance_is_gated_too():
    # R defaults wide open; narrowing it fails a pin whose C is fine
    df = pd.DataFrame(
        [{"DSUB connector": 0, "DSUB pin": 1, "Shorted": False,
          "C_filter_nF": 1.0, "R_filter_Ohm": 900}]
    )
    assert A.analyse_filter(df, A.FilterAnalysisSettings()).findings[0].status == "ok"
    res = A.analyse_filter(
        df, A.FilterAnalysisSettings(r_min_ohm=1500, r_max_ohm=2500)
    )
    assert res.findings[0].status == "below_limit"
    assert res.findings[0].failed == ["r"]
    assert "R 900 Ohm" in res.findings[0].message


def test_resistance_classification():
    df = pd.DataFrame(
        [
            {"Measurement round": 0, "DSUB pin": 1, "R_est": 5.0,
             "Shorted": True, "High impedance": False},
            {"Measurement round": 0, "DSUB pin": 2, "R_est": 500.0,
             "Shorted": False, "High impedance": False},
            {"Measurement round": 0, "DSUB pin": 3, "R_est": 2e6,
             "Shorted": False, "High impedance": True},
        ]
    )
    res = A.analyse_resistance(df, A.ResistanceAnalysisSettings())
    assert [f.status for f in res.findings] == ["shorted", "ok", "high_impedance"]
    assert res.log_y is True


def test_voltage_window():
    df = pd.DataFrame(
        [
            {"Measurement round": 0, "DSUB pin": 1, "V_avg": 0.5, "V_std": 0.01},
            {"Measurement round": 0, "DSUB pin": 2, "V_avg": 50.0, "V_std": 0.01},
        ]
    )
    res = A.analyse_voltage(df, A.VoltageAnalysisSettings(v_min=-5, v_max=5))
    assert [f.status for f in res.findings] == ["ok", "above_limit"]


def test_registry_dispatch_and_unknown():
    assert A.has_analysis("measure_filter")
    assert not A.has_analysis("nope")
    assert A.analysis_settings_for("measure_voltage") is A.VoltageAnalysisSettings
    with pytest.raises(KeyError):
        A.analyse("nope", _filter_df(), None)


def test_missing_columns_raises():
    with pytest.raises(ValueError):
        A.analyse_filter(pd.DataFrame([{"foo": 1}]), A.FilterAnalysisSettings())


def test_render_report_contains_faults_and_summary():
    res = A.analyse_filter(_filter_df(), A.FilterAnalysisSettings())
    text = A.render_report(res, "demo.json")
    assert "demo.json" in text
    assert "Cap not detected" in text
    assert "Faults total: 3" in text


def test_analyse_from_saved_file(tmp_path):
    """The save format round-trips straight into the analysis engine."""
    path = save_result(_filter_df(), FilterSettings(), tmp_path / "r.json", "measure_filter")
    measurement, _settings, df = load(path)
    res = A.analyse(measurement, df, A.analysis_settings_for(measurement)())
    assert res.measurement == "measure_filter"
    assert res.n_faults == 3
