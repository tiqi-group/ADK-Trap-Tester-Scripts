"""Headless tests for golden-reference capture (``core.analysis.golden``).

Run with ``uv run pytest tests/test_golden_core.py``. Covers what lands in the
reference table (keys, aggregation) and what is deliberately left out, plus the
round trip that matters in practice: capture a board, then analyse it against
itself and see every pin pass.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis import golden


def _filter_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"DSUB connector": 0, "DSUB pin": 1, "Shorted": False,
         "C_filter_nF": 1.02, "R_filter_Ohm": 2010},
        {"DSUB connector": 1, "DSUB pin": 1, "Shorted": False,
         "C_filter_nF": 0.97, "R_filter_Ohm": 1990},
        # a point the measurement skipped / flagged shorted: C = R = -1
        {"DSUB connector": 0, "DSUB pin": 2, "Shorted": True,
         "C_filter_nF": -1.0, "R_filter_Ohm": -1.0},
    ])


def _resistance_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"Measurement round": 0, "DSUB pin": 1, "R_est": 480.0},
        {"Measurement round": 1, "DSUB pin": 1, "R_est": 500.0},
        {"Measurement round": 2, "DSUB pin": 1, "R_est": 520.0},
        {"Measurement round": 0, "DSUB pin": 2, "R_est": -1.0},  # no trigger
    ])


def test_filter_capture_is_keyed_per_connector():
    cap = golden.capture(_filter_df(), "measure_filter", source="board-A.json")
    assert cap.reference.values == {
        "0:1": {"c": 1.02, "r": 2010.0},
        "1:1": {"c": 0.97, "r": 1990.0},
    }
    assert cap.n_points == 2
    assert cap.n_rows == 3
    assert cap.n_skipped == 2  # both quantities of the shorted row
    assert cap.reference.source == "board-A.json"
    assert cap.reference.captured  # a timestamp is recorded


def test_round_based_capture_uses_the_wildcard_and_a_median():
    cap = golden.capture(_resistance_df(), "measure_resistance")
    assert cap.reference.values == {"*:1": {"r": 500.0}}  # median of 480/500/520
    assert cap.reference.lookup(7, 1, "r") == 500.0  # matches any round
    assert cap.n_skipped == 1


def test_negative_voltages_are_kept():
    # -1 is a skip marker for C/R, but a real reading for a signed quantity
    df = pd.DataFrame([
        {"Measurement round": 0, "DSUB pin": 1, "V_avg": -1.0},
        {"Measurement round": 1, "DSUB pin": 1, "V_avg": -1.2},
    ])
    cap = golden.capture(df, "measure_voltage")
    assert cap.reference.values == {"*:1": {"v": -1.1}}
    assert cap.n_skipped == 0


def test_non_finite_values_are_skipped():
    df = pd.DataFrame([
        {"Measurement round": 0, "DSUB pin": 1, "V_avg": np.nan},
        {"Measurement round": 0, "DSUB pin": 2, "V_avg": 1.0},
    ])
    cap = golden.capture(df, "measure_voltage")
    assert cap.reference.values == {"*:2": {"v": 1.0}}
    assert cap.n_skipped == 1


def test_capture_needs_a_known_measurement_and_a_pin_column():
    with pytest.raises(KeyError):
        golden.capture(_filter_df(), "measure_nothing")
    with pytest.raises(ValueError, match="DSUB pin"):
        golden.capture(pd.DataFrame([{"foo": 1}]), "measure_filter")


def test_a_board_passes_against_itself():
    """The round trip that matters: capture, then re-analyse the same result."""
    df = _filter_df()
    cap = golden.capture(df, "measure_filter", source="board-A.json")
    # zero tolerance: only the shorted pin (which has no entry) may fail
    s = A.FilterAnalysisSettings(rel_tol=0.0, reference=cap.reference)
    statuses = [f.status for f in A.analyse_filter(df, s).findings]
    assert statuses == ["ok", "ok", "shorted"]


def test_a_drifted_board_fails_against_the_reference():
    reference = golden.capture(_filter_df(), "measure_filter").reference
    drifted = pd.DataFrame([
        {"DSUB connector": 0, "DSUB pin": 1, "Shorted": False,
         "C_filter_nF": 1.02 * 1.5, "R_filter_Ohm": 2010},
    ])
    s = A.FilterAnalysisSettings(rel_tol=0.1, reference=reference)
    finding = A.analyse_filter(drifted, s).findings[0]
    assert finding.status == "above_limit"
    assert finding.expected == {"c": 1.02, "r": 2010.0}


def test_capture_round_trips_through_a_preset(tmp_path, monkeypatch):
    from trap_tester.core.analysis import presets

    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "layouts"))
    cap = golden.capture(_filter_df(), "measure_filter", source="board-A.json")
    settings = A.FilterAnalysisSettings(reference=cap.reference)
    path = presets.save(settings, "measure_filter", "golden board A")
    loaded = presets.load(path).settings
    assert loaded.reference.values == cap.reference.values
    assert loaded.reference.source == "board-A.json"
