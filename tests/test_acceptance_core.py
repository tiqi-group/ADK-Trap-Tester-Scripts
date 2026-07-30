"""Headless tests for the acceptance model (``core.analysis.acceptance``).

Run with ``uv run pytest tests/test_acceptance_core.py``. Covers the two ways a
band is derived (global min/max vs. a golden reference), the wildcard key the
round-based measurements use, and the migration of pre-acceptance-model settings.
"""

from __future__ import annotations

import pandas as pd

from trap_tester.core import analysis as A
from trap_tester.core.analysis.acceptance import Reference
from trap_tester.core.analysis.quantities import C_FILTER, R_EST


def _filter_row(pin: int, c: float, r: float = 2000.0, connector: int = 0) -> dict:
    return {"DSUB connector": connector, "DSUB pin": pin, "Shorted": False,
            "C_filter_nF": c, "R_filter_Ohm": r}


def _resistance_row(rnd: int, pin: int, r: float) -> dict:
    return {"Measurement round": rnd, "DSUB pin": pin, "R_est": r,
            "Shorted": False, "High impedance": False}


# ---- bands -----------------------------------------------------------------
def test_limits_band_when_no_reference():
    s = A.FilterAnalysisSettings(c_min_nf=0.9, c_max_nf=1.1)
    assert s.band_for(C_FILTER, 0, 1) == (0.9, 1.1, None)
    assert not s.has_reference()


def test_reference_band_uses_abs_and_rel_tolerance():
    s = A.FilterAnalysisSettings(
        c_min_nf=0.9, c_max_nf=1.1, rel_tol=0.1, c_abs_tol_nf=0.05,
        reference=Reference(values={"0:1": {"c": 2.0}}),
    )
    lo, hi, expected = s.band_for(C_FILTER, 0, 1)
    assert expected == 2.0
    # 0.05 absolute + 10 % of 2.0 = 0.25
    assert (lo, hi) == (1.75, 2.25)
    # a pin the reference does not cover falls back to the global limits
    assert s.band_for(C_FILTER, 0, 2) == (0.9, 1.1, None)


def test_reference_overrides_limits_in_the_analysis():
    # C = 2.0 is far outside the 0.75…1.25 default window, but matches the
    # reference for that pin, so it passes; pin 3 has no entry and still fails.
    s = A.FilterAnalysisSettings(
        rel_tol=0.05, reference=Reference(values={"0:1": {"c": 2.0}})
    )
    res = A.analyse_filter(
        pd.DataFrame([_filter_row(1, 2.0), _filter_row(3, 2.0)]), s
    )
    assert [f.status for f in res.findings] == ["ok", "above_limit"]
    assert res.findings[0].expected == {"c": 2.0}
    assert res.findings[1].expected == {}
    # a per-pin band cannot be shaded as one region
    assert res.band is None


def test_reference_tolerance_can_fail_a_pin():
    s = A.FilterAnalysisSettings(
        rel_tol=0.01, c_abs_tol_nf=0.0, reference=Reference(values={"0:1": {"c": 1.0}})
    )
    res = A.analyse_filter(pd.DataFrame([_filter_row(1, 1.5)]), s)
    assert res.findings[0].status == "above_limit"
    assert "tolerance" in res.findings[0].message


def test_reference_is_per_connector():
    s = A.FilterAnalysisSettings(
        rel_tol=0.05,
        reference=Reference(values={"0:1": {"c": 2.0}, "1:1": {"c": 3.0}}),
    )
    df = pd.DataFrame([_filter_row(1, 2.0, connector=0), _filter_row(1, 3.0, connector=1)])
    assert [f.status for f in A.analyse_filter(df, s).findings] == ["ok", "ok"]


# ---- wildcard key (round-based measurements) --------------------------------
def test_wildcard_key_matches_every_round():
    s = A.ResistanceAnalysisSettings(
        rel_tol=0.1, reference=Reference(values={"*:1": {"r": 500.0}})
    )
    df = pd.DataFrame([_resistance_row(0, 1, 500.0), _resistance_row(1, 1, 900.0)])
    res = A.analyse_resistance(df, s)
    assert [f.status for f in res.findings] == ["ok", "high_impedance"]


def test_exact_key_wins_over_wildcard():
    ref = Reference(values={"*:1": {"r": 500.0}, "0:1": {"r": 900.0}})
    s = A.ResistanceAnalysisSettings(rel_tol=0.1, reference=ref)
    assert s.band_for(R_EST, 0, 1)[2] == 900.0
    assert s.band_for(R_EST, 1, 1)[2] == 500.0


def test_skipped_resistance_point_is_not_a_short():
    # R = -1 marks a no-trigger point; it has no reading to judge
    res = A.analyse_resistance(
        pd.DataFrame([_resistance_row(0, 1, -1.0)]), A.ResistanceAnalysisSettings()
    )
    assert res.findings[0].status == "not_detected"
    assert "skipped" in res.findings[0].message


# ---- (de)serialisation / migration -----------------------------------------
def test_settings_round_trip_with_reference():
    s = A.FilterAnalysisSettings(
        c_min_nf=0.5, reference=Reference(values={"0:1": {"c": 1.0}}, source="a.json")
    )
    back = A.FilterAnalysisSettings.from_dict(s.to_dict())
    assert back == s
    assert back.reference.source == "a.json"
    assert back.reference.n_points == 1


def test_from_dict_ignores_unknown_keys():
    s = A.VoltageAnalysisSettings.from_dict({"v_min": -1.0, "nonsense": 5})
    assert s.v_min == -1.0


def test_legacy_filter_settings_migrate_to_a_window():
    s = A.FilterAnalysisSettings.from_dict(
        {"c_nominal_nf": 2.0, "rel_tolerance": 0.25, "r_nominal_ohm": 2000,
         "min_c_abs_nf": 0.2}
    )
    assert (s.c_min_nf, s.c_max_nf) == (1.5, 2.5)
    assert s.min_c_abs_nf == 0.2
    # the never-enforced R nominal must not become a band
    assert (s.r_min_ohm, s.r_max_ohm) == (0.0, 1e9)


def test_legacy_resistance_thresholds_migrate():
    s = A.ResistanceAnalysisSettings.from_dict(
        {"r_short_ohm": 5.0, "r_high_imp_ohm": 2e6}
    )
    assert (s.r_min_ohm, s.r_max_ohm) == (5.0, 2e6)


def test_reference_from_bare_values_mapping():
    ref = Reference.from_dict({"0:1": {"c": 1.0}})
    assert ref.lookup(0, 1, "c") == 1.0
    assert ref.lookup(0, 2, "c") is None


# ---- report ----------------------------------------------------------------
def test_report_names_which_quantity_went_out_of_band():
    # pin 1 fails on C only, pin 3 on R only — the pin status cannot say which
    df = pd.DataFrame([_filter_row(1, 2.0, r=2000.0), _filter_row(3, 1.0, r=900.0)])
    s = A.FilterAnalysisSettings(r_min_ohm=1500, r_max_ohm=2500)
    res = A.analyse_filter(df, s)
    assert res.failures_by_quantity == {"c": 1, "r": 1}
    assert "Out of band: C 1, R 1" in A.render_report(res)


def test_report_omits_the_breakdown_when_nothing_failed():
    res = A.analyse_filter(pd.DataFrame([_filter_row(1, 1.0)]), A.FilterAnalysisSettings())
    assert res.failures_by_quantity == {}
    assert "Out of band" not in A.render_report(res)


def test_findings_carry_the_band_they_were_judged_against():
    # what the viewer draws per pin: the covered pin gets the reference band,
    # the uncovered one keeps the global limits
    s = A.FilterAnalysisSettings(
        c_min_nf=0.5, c_max_nf=1.5, rel_tol=0.1, c_abs_tol_nf=0.0,
        reference=Reference(values={"0:1": {"c": 1.0}}),
    )
    res = A.analyse_filter(pd.DataFrame([_filter_row(1, 1.0), _filter_row(3, 1.0)]), s)
    assert res.findings[0].limits["c"] == (0.9, 1.1)
    assert res.findings[1].limits["c"] == (0.5, 1.5)


def test_report_lists_limits_and_reference():
    s = A.FilterAnalysisSettings(reference=Reference(values={"0:1": {"c": 1.0}},
                                                     source="golden.json"))
    text = A.render_report(A.analyse_filter(pd.DataFrame([_filter_row(1, 1.0)]), s))
    assert "Capacitance limits" in text
    assert "golden.json" in text
    assert "rel_tol" in text
