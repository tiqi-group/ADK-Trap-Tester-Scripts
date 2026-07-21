"""Headless regression tests for the self-test core (``core.selftest``).

Run with ``uv run pytest test/test_selftest_core.py``. The frontend loopback is
driven against the :class:`MockDevice`, whose voltage-mode capture returns
matched channels, so every pin correlates ~1.0.
"""

from __future__ import annotations

from trap_tester.core.device import open_device
from trap_tester.core.reporter import AutoGate, ConsoleReporter, MeasurementContext
from trap_tester.core.selftest import (
    InstallCheck,
    SelfTestSettings,
    check_waveform_install,
    run_frontend_selftest,
)
from trap_tester.utils import DSUB_GND_PIN


def test_install_check_returns_lines():
    result = check_waveform_install()
    assert isinstance(result, InstallCheck)
    assert isinstance(result.ok, bool)
    assert result.lines  # always reports what it found
    assert any("Operating system" in line for line in result.lines)


def _run_frontend(settings: SelfTestSettings):
    rep = ConsoleReporter()
    with open_device(force_mock=True) as dev:
        ctx = MeasurementContext(device=dev, settings=settings, report=rep, gate=AutoGate())
        return run_frontend_selftest(ctx), rep


def test_frontend_selftest_covers_all_pins():
    df, _rep = _run_frontend(SelfTestSettings(buffer_size=1024, run_current_check=False))
    assert list(df.columns) == ["DSUB pin", "Correlation"]
    assert len(df) == 49  # 50 pins minus the DSUB GND pin
    assert DSUB_GND_PIN not in df["DSUB pin"].tolist()


def test_frontend_loopback_correlates():
    df, _rep = _run_frontend(SelfTestSettings(buffer_size=1024, run_current_check=False))
    # matched mock channels -> correlation ~1 on every pin, none below threshold
    assert (df["Correlation"] > 0.99).all()


def test_frontend_streams_results_and_current_check():
    df, rep = _run_frontend(SelfTestSettings(buffer_size=1024, run_current_check=True))
    # one streamed result row per measured pin
    assert len(rep.rows) == len(df) == 49
    assert rep.last_capture is not None  # captures were published for live plotting


def test_frontend_cancel_stops_early():
    rep = ConsoleReporter()
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 5  # cancel after a few pins

    with open_device(force_mock=True) as dev:
        ctx = MeasurementContext(
            device=dev, settings=SelfTestSettings(buffer_size=512, run_current_check=False),
            report=rep, gate=AutoGate(), should_cancel=cancel,
        )
        df = run_frontend_selftest(ctx)
    assert len(df) < 49  # stopped before sweeping every pin
