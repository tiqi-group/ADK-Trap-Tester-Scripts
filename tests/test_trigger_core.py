"""Regression tests for the trigger controls + cancel/timeout/free-run behavior.

Run with ``uv run pytest tests/test_trigger_core.py``. The MockDevice grows a
``fail_trigger`` knob (its scope status stays RUNNING) so the no-trigger path —
timeout, free-run debug frames, then skip (C=R=-1) — is exercised without
hardware, and cancellation can be checked while the scope "waits for a trigger".
"""

from __future__ import annotations

import time

from trap_tester.core.device import MockDevice
from trap_tester.core.measurements import (
    run_filter_measurement,
    run_resistance_measurement,
)
from trap_tester.core.measurements._capture import free_run, resolve_trigger
from trap_tester.core.reporter import AutoGate, ConsoleReporter, MeasurementContext
from trap_tester.core.settings import FilterSettings, ResistanceSettings, load, save_result

_FAST = dict(n_dsub=1, n_avg=2, file_prefix="", invalid_pins=list(range(4, 51)))


def _filter(settings: FilterSettings, dev: MockDevice, cancel=lambda: False):
    rep = ConsoleReporter()
    ctx = MeasurementContext(dev, settings, rep, AutoGate(), should_cancel=cancel)
    return run_filter_measurement(ctx), rep


# ---- resolve_trigger ------------------------------------------------------
def test_resolve_trigger_defaults_to_current():
    assert resolve_trigger(FilterSettings()) == (1, 0.4, "rising")
    assert resolve_trigger(ResistanceSettings()) == (1, 0.4, "rising")


def test_resolve_trigger_channel_from_source():
    s = FilterSettings(trigger_source="current", trigger_level=0.7, trigger_slope="falling")
    assert resolve_trigger(s) == (1, 0.7, "falling")
    s = FilterSettings(trigger_source="voltage", trigger_level=0.2, trigger_slope="rising")
    assert resolve_trigger(s) == (0, 0.2, "rising")


# ---- no-trigger -> free-run -> skip ---------------------------------------
def test_filter_no_trigger_skips_and_frees_run():
    dev = MockDevice()
    dev.analog_input.fail_trigger = True
    s = FilterSettings(**_FAST, trigger_timeout=0.05)
    df, rep = _filter(s, dev)
    assert len(df) == 3
    assert (df["C_filter_nF"] == -1).all()  # every point skipped
    assert (df["R_filter_Ohm"] == -1).all()
    assert rep.last_capture is not None  # free-run frames were published for debug


def test_resistance_no_trigger_skips():
    dev = MockDevice()
    dev.analog_input.fail_trigger = True
    s = ResistanceSettings(
        n_rounds=1, file_prefix="", invalid_pins=list(range(4, 51)),
        trigger_timeout=0.05,
    )
    df = run_resistance_measurement(
        MeasurementContext(dev, s, ConsoleReporter(), AutoGate())
    )
    assert len(df) == 3
    assert (df["R_est"] == -1).all()


# ---- cancel while waiting for a trigger -----------------------------------
def test_cancel_during_trigger_wait_returns_promptly():
    dev = MockDevice()
    dev.analog_input.fail_trigger = True  # would otherwise wait the full timeout
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # cancel once the capture starts polling

    # a huge timeout: if cancellation did not work we'd block ~30s
    s = FilterSettings(**_FAST, trigger_timeout=30.0)
    start = time.monotonic()
    df, _rep = _filter(s, dev, cancel=cancel)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"cancel did not interrupt the trigger wait ({elapsed:.1f}s)"
    assert len(df) == 0  # cancelled before any round was committed


# ---- forced source still runs against the mock ----------------------------
def test_forced_trigger_source_completes():
    dev = MockDevice()  # mock ignores the channel, so this just checks wiring
    s = FilterSettings(**_FAST, trigger_source="current", trigger_level=0.3)
    df, _rep = _filter(s, dev)
    assert len(df) == 3
    assert (df["C_filter_nF"] > 0).all()  # captured + fitted normally


# ---- a no-trigger must not poison the trigger for later pins --------------
def test_no_trigger_does_not_leave_scope_in_auto_mode_filter():
    """Regression: free-run left the scope in auto trigger, so every pin after a
    non-triggering one auto-fired on untriggered data and read as faulty."""
    dev = MockDevice()
    dev.analog_input.fail_next_triggers(1)  # the baseline capture times out
    df, _rep = _filter(FilterSettings(**_FAST, trigger_timeout=0.05), dev)
    modes = dev.analog_input.capture_modes
    assert modes, "no captures were recorded"
    assert "auto" not in modes, f"a real capture ran in auto (free-run) mode: {modes}"
    # later pins are still measured normally, not skipped/faulty
    assert len(df) == 3
    assert (df["C_filter_nF"] > 0).all()


def test_no_trigger_does_not_leave_scope_in_auto_mode_resistance():
    dev = MockDevice()
    dev.analog_input.fail_next_triggers(1)  # the first pin times out
    s = ResistanceSettings(
        n_rounds=1, file_prefix="", invalid_pins=list(range(4, 51)), trigger_timeout=0.05
    )
    run_resistance_measurement(MeasurementContext(dev, s, ConsoleReporter(), AutoGate()))
    modes = dev.analog_input.capture_modes
    assert "auto" not in modes, f"a real capture ran in auto (free-run) mode: {modes}"


def test_free_run_restores_normal_trigger_mode():
    dev = MockDevice()
    scope = dev.analog_input
    scope.trigger.auto_timeout = 0.0  # normal mode
    free_run(
        scope, MeasurementContext(dev, None, ConsoleReporter(), AutoGate()),
        sample_rate=1e6, buffer_size=128, publish=lambda: None,
    )
    assert scope.trigger.auto_timeout == 0.0  # restored, not left at the auto value


# ---- interactive free-run (scope) mode ------------------------------------
class _ScriptedFreerunGate(AutoGate):
    """Free-runs a couple of frames, freezes, then ends — no timer involved."""

    def __init__(self) -> None:
        super().__init__()
        self.begun: str | None = None
        self.ended = False
        self.frozen = False
        self._polls = 0

    def begin_freerun(self, prompt: str) -> None:
        self.begun = prompt

    def end_freerun(self) -> None:
        self.ended = True

    def freerun_capture_due(self) -> bool:
        return not self.frozen  # once frozen, no fresh frames are grabbed

    def freerun_done(self) -> bool:
        self._polls += 1
        if self._polls == 2:
            self.frozen = True  # operator freezes after two live frames
        return self._polls >= 4  # operator presses Continue after four polls


def test_freerun_is_interactive_and_freezes():
    dev = MockDevice()
    scope = dev.analog_input
    gate = _ScriptedFreerunGate()
    ctx = MeasurementContext(dev, None, ConsoleReporter(), gate)
    frames: list = []
    free_run(
        scope, ctx, sample_rate=1e6, buffer_size=256, prompt="inspect me",
        publish=lambda: frames.append(1),
    )
    assert gate.begun == "inspect me"  # the UI was told to show free-run controls
    assert gate.ended  # ...and told to hide them afterwards
    # 2 live frames, then frozen -> no more frames until Continue ends it
    assert len(frames) == 2


# ---- new trigger settings round-trip through save/load --------------------
def test_trigger_settings_roundtrip(tmp_path):
    dev = MockDevice()
    df, _rep = _filter(FilterSettings(**_FAST), dev)
    s = FilterSettings(**_FAST, trigger_source="voltage", trigger_level=0.11,
                       trigger_slope="either", trigger_timeout=3.5)
    path = save_result(df, s, tmp_path / "trig.json", "measure_filter")
    _measurement, loaded, _df = load(path)
    assert loaded.trigger_source == "voltage"
    assert loaded.trigger_level == 0.11
    assert loaded.trigger_slope == "either"
    assert loaded.trigger_timeout == 3.5
