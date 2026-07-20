"""Headless regression tests for the refactored filter measurement.

Run with ``uv run pytest test/test_filter_core.py``. These need no hardware —
they drive :func:`run_filter_measurement` against the :class:`MockDevice`.
"""

from __future__ import annotations

from trap_tester.core.device import open_device
from trap_tester.core.measurements import (
    run_filter_measurement,
    run_resistance_measurement,
    run_voltage_measurement,
)
from trap_tester.core.reporter import AutoGate, ConsoleReporter, MeasurementContext
from trap_tester.core.settings import (
    FilterSettings,
    ResistanceSettings,
    VoltageSettings,
    load,
    save_result,
)

# only pins 1,2,3 -> fast
_FAST = dict(n_dsub=1, n_avg=2, file_prefix="", invalid_pins=list(range(4, 51)))


def _run(gate: AutoGate):
    s = FilterSettings(**_FAST)
    rep = ConsoleReporter()
    with open_device(force_mock=True) as dev:
        ctx = MeasurementContext(device=dev, settings=s, report=rep, gate=gate)
        return run_filter_measurement(ctx)


def test_columns_and_rowcount():
    df = _run(AutoGate(retake=False))
    assert list(df.columns) == [
        "DSUB connector", "DSUB pin", "Shorted",
        "C_filter_nF", "R_filter_Ohm", "Bandwidth", "Perr_max",
    ]
    assert len(df) == 3  # one row per measured pin


def test_no_duplication_on_retake():
    """The original bug double-counted rows when the operator retook a round."""
    df = _run(AutoGate(retake_once=True))
    assert len(df) == 3, f"retake duplicated rows: got {len(df)}"


def test_nominal_capacitance_recovered():
    df = _run(AutoGate(retake=False))
    # mock filter is 1 nF +/- 15%; fit should land in a sane window
    assert not df["Shorted"].any()
    assert df["C_filter_nF"].between(0.7, 1.4).all()


def test_voltage_measurement():
    s = VoltageSettings(n_rounds=1, file_prefix="", invalid_pins=list(range(4, 51)))
    with open_device(force_mock=True) as dev:
        df = run_voltage_measurement(
            MeasurementContext(dev, s, ConsoleReporter(), AutoGate())
        )
    assert list(df.columns) == ["Measurement round", "DSUB pin", "V_avg", "V_std"]
    assert len(df) == 3
    assert df["V_std"].lt(0.1).all()  # quasi-DC -> small spread


def test_resistance_measurement():
    s = ResistanceSettings(n_rounds=1, file_prefix="", invalid_pins=list(range(4, 51)))
    with open_device(force_mock=True) as dev:
        df = run_resistance_measurement(
            MeasurementContext(dev, s, ConsoleReporter(), AutoGate())
        )
    assert list(df.columns) == [
        "Measurement round", "DSUB pin", "R_est", "Shorted", "High impedance",
    ]
    assert len(df) == 3
    # open circuit (nothing connected in the mock) -> high impedance, positive R
    assert df["High impedance"].all()
    assert df["R_est"].gt(0).all()


def test_voltage_no_duplication_on_retake():
    s = VoltageSettings(n_rounds=1, file_prefix="", invalid_pins=list(range(4, 51)))
    with open_device(force_mock=True) as dev:
        df = run_voltage_measurement(
            MeasurementContext(dev, s, ConsoleReporter(), AutoGate(retake_once=True))
        )
    assert len(df) == 3  # retake must not duplicate rows


def test_settings_roundtrip(tmp_path):
    df = _run(AutoGate(retake=False))
    s = FilterSettings(**_FAST, amplitude=1.75)
    path = save_result(df, s, tmp_path / "rt.json", "measure_filter")
    measurement, loaded_settings, loaded_df = load(path)
    assert measurement == "measure_filter"
    assert isinstance(loaded_settings, FilterSettings)
    assert loaded_settings.amplitude == 1.75
    assert loaded_settings.n_avg == 2
    assert loaded_df is not None and len(loaded_df) == 3
