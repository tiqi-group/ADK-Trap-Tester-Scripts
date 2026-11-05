"""Headless tests for the ad-hoc FPC inversion (``core.analysis.fpc_permutation``).

Run with ``uv run pytest tests/test_fpc_permutation_core.py``. A device plugged
into the front-end FPC reversed sees conductor ``52 - c`` where the tester drives
``c``; the analysis relabels each measured pin so everything downstream works in
the device's numbering.
"""

from __future__ import annotations

from dataclasses import fields

import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis import golden, presets
from trap_tester.core.analysis._common import fpc_conductor
from trap_tester.core.analysis.fpc_permutation import (
    invert_conductor,
    invert_fpc,
    inverted_dsub_pin,
    prepare_frame,
)
from trap_tester.mux_mapping import dsub_to_signal

ALL_PINS = range(1, 51)


def _filter_df(pins) -> pd.DataFrame:
    return pd.DataFrame([
        {"DSUB connector": 0, "DSUB pin": p, "Shorted": False,
         "C_filter_nF": 1.0 + p / 100, "R_filter_Ohm": 2000}
        for p in pins
    ])


def test_conductor_inversion_is_52_minus_c():
    assert invert_conductor(51) == 1
    assert invert_conductor(1) == 51
    assert invert_conductor(2) == 50
    assert invert_conductor(26) == 26


def test_inverted_pin_lands_on_the_mirrored_conductor():
    for pin in ALL_PINS:
        conductor = fpc_conductor(pin)
        if conductor is None:
            continue
        assert fpc_conductor(inverted_dsub_pin(pin)) == 52 - conductor


def test_inversion_is_a_bijective_involution():
    image = [inverted_dsub_pin(p) for p in ALL_PINS]
    assert sorted(image) == list(ALL_PINS)  # no two pins collide
    assert all(inverted_dsub_pin(inverted_dsub_pin(p)) == p for p in ALL_PINS)


def test_pins_off_the_fpc_keep_their_number():
    # pin 9 is GND: its signal has no FPC conductor
    assert fpc_conductor(9) is None
    assert inverted_dsub_pin(9) == 9
    # pin 42 rides conductor 26, the ribbon's centre: its own mirror image
    assert fpc_conductor(42) == 26
    assert inverted_dsub_pin(42) == 42


def test_invert_fpc_relabels_pins_without_mutating():
    df = _filter_df([1, 2, 3])
    out = invert_fpc(df)
    assert list(df["DSUB pin"]) == [1, 2, 3]  # input untouched
    assert list(out["DSUB pin"]) == [inverted_dsub_pin(p) for p in (1, 2, 3)]
    assert list(out["C_filter_nF"]) == list(df["C_filter_nF"])  # values travel along


def test_prepare_frame_only_inverts_when_ticked():
    df = _filter_df([1])
    assert prepare_frame(df, A.FilterAnalysisSettings()) is df
    flipped = prepare_frame(df, A.FilterAnalysisSettings(fpc_inverted=True))
    assert list(flipped["DSUB pin"]) == [inverted_dsub_pin(1)]


@pytest.mark.parametrize("settings_type", [
    A.FilterAnalysisSettings, A.LoopbackAnalysisSettings,
    A.ResistanceAnalysisSettings, A.VoltageAnalysisSettings,
])
def test_every_analysis_has_the_tickbox_first_and_off(settings_type):
    assert fields(settings_type)[0].name == "fpc_inverted"  # heads the form
    assert settings_type().fpc_inverted is False
    assert "FPC inverted" in settings_type().params()


def test_analyse_reports_findings_in_device_numbering():
    df = _filter_df([1, 33])
    straight = A.analyse("measure_filter", df, A.FilterAnalysisSettings())
    flipped = A.analyse(
        "measure_filter", df, A.FilterAnalysisSettings(fpc_inverted=True)
    )
    assert [f.dsub_pin for f in straight.findings] == [1, 33]
    assert [f.dsub_pin for f in flipped.findings] == [
        inverted_dsub_pin(1), inverted_dsub_pin(33)
    ]
    # the FPC conductor on the finding is the device's (mirrored) one
    for raw, finding in zip((1, 33), flipped.findings):
        assert finding.fpc_conductor == 52 - fpc_conductor(raw)
    assert flipped.params["FPC inverted"].startswith("yes")
    assert straight.params["FPC inverted"] == "no"


def test_round_based_measurement_is_inverted_too():
    df = pd.DataFrame([{"Measurement round": 0, "DSUB pin": 1, "V_avg": 1.0}])
    res = A.analyse(
        "measure_voltage", df, A.VoltageAnalysisSettings(fpc_inverted=True)
    )
    assert res.findings[0].dsub_pin == inverted_dsub_pin(1)


def test_reference_from_an_inverted_board_matches_a_straight_one():
    # The same device measured both ways round: once inverted, the readings
    # land on the same device pins, so a reference from one judges the other.
    device = {p: 1.0 + p / 100 for p in ALL_PINS if dsub_to_signal.get(p)}
    straight_df = _filter_df(device)
    straight_df["C_filter_nF"] = [device[p] for p in straight_df["DSUB pin"]]
    # what the tester records when the ribbon is reversed
    inverted_df = straight_df.copy()
    inverted_df["DSUB pin"] = [inverted_dsub_pin(p) for p in straight_df["DSUB pin"]]

    ticked = A.FilterAnalysisSettings(fpc_inverted=True)
    captured = golden.capture(prepare_frame(inverted_df, ticked), "measure_filter")
    reference = captured.reference
    for pin, c in device.items():
        assert reference.lookup(0, pin, "c") == pytest.approx(c)

    res = A.analyse(
        "measure_filter", straight_df,
        A.FilterAnalysisSettings(reference=reference, rel_tol=0.001),
    )
    assert all(f.status == "ok" for f in res.findings)


def test_tickbox_is_stored_in_a_preset(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "layouts"))
    path = presets.save(
        A.FilterAnalysisSettings(fpc_inverted=True), "measure_filter", "flipped"
    )
    assert presets.load(path).settings.fpc_inverted is True


def test_old_preset_without_the_key_loads_straight():
    settings = A.FilterAnalysisSettings.from_dict({"c_min_nf": 0.8})
    assert settings.fpc_inverted is False
