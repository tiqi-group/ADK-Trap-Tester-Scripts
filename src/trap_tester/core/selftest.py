"""Self-test routines (refactored from ``test/``).

Two independent checks, both GUI-agnostic:

* :func:`check_waveform_install` — the ``check-waveform-install.py`` logic:
  locate and load the OS-specific WaveForms runtime and confirm ``dwfpy`` and
  device enumeration work. No hardware required; returns a structured result.
* :func:`run_frontend_selftest` — the ``test_trap_tester.py`` frontend check:
  loop the DAC-MUX output back into the ADC-MUX on every DSUB pin and correlate
  the two scope channels (a healthy channel correlates ~1.0), then a current
  measurement sanity check. Uses the same :class:`MeasurementContext` callbacks
  as the measurements so it streams to the GUI and plots inline instead of
  calling ``plt.show``.
"""

from __future__ import annotations

import ctypes
import time as t
from dataclasses import dataclass
from os import sep
from sys import platform
from typing import Any

import numpy as np
import pandas as pd

from trap_tester.core.reporter import MeasurementContext
from trap_tester.utils import (
    DSUB_GND_PIN,
    R_SENSE,
    SENSE_MAG,
    SW_ADC_TO_GND_IDX,
    SW_MEAS_SEL_IDX,
    set_adc,
    set_dac,
)

_EXPECTED_CURRENT_UA = 191.0  # nominal loopback current on real hardware


# --------------------------------------------------------------------------- #
# WaveForms install check
# --------------------------------------------------------------------------- #
@dataclass
class InstallCheck:
    """Outcome of :func:`check_waveform_install`."""

    ok: bool
    lines: list[str]


def _dwf_library() -> tuple[str, str]:
    """The OS-specific WaveForms runtime library name and SDK samples path."""
    if platform.startswith("win"):
        lib = "dwf"
        samples = sep.join(
            ["C:", "Program Files (x86)", "Digilent", "WaveFormsSDK", "samples", "py"]
        )
    elif platform.startswith("darwin"):
        lib = sep + sep.join(["Library", "Frameworks", "dwf.framework", "dwf"])
        samples = sep + sep.join(
            ["Applications", "WaveForms.app", "Contents", "Resources", "SDK", "samples", "py"]
        )
    else:  # linux
        lib = "libdwf.so"
        samples = sep + sep.join(["usr", "share", "digilent", "waveforms", "samples", "py"])
    return lib, samples


def check_waveform_install() -> InstallCheck:
    """Verify the WaveForms runtime + ``dwfpy`` are installed and usable."""
    lines: list[str] = []
    os_name = "Windows" if platform.startswith("win") else (
        "macOS" if platform.startswith("darwin") else "Linux"
    )
    lines.append(f"Operating system: {os_name} ({platform})")

    lib, samples = _dwf_library()
    lines.append(f"Expected WaveForms library: {lib}")
    lines.append(f"Expected SDK samples path: {samples}")

    lib_ok = False
    try:
        if platform.startswith("win"):
            ctypes.cdll.dwf  # noqa: B018 - mirrors the original loader
        else:
            ctypes.cdll.LoadLibrary(lib)
        lib_ok = True
        lines.append("✓ WaveForms runtime library loaded.")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"✗ Could not load the WaveForms runtime library: {exc}")

    dwfpy_ok = False
    try:
        import dwfpy as dwf

        version = getattr(dwf, "__version__", "unknown")
        dwfpy_ok = True
        lines.append(f"✓ dwfpy importable (version {version}).")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"✗ dwfpy not importable: {exc}")

    if dwfpy_ok:
        try:
            from trap_tester.core.device import enumerate_devices

            devices = enumerate_devices(force_mock=False)
            if devices:
                lines.append(f"✓ {len(devices)} Analog Discovery device(s) detected:")
                for dev in devices:
                    lines.append(
                        f"    - {dev.get('name', 'Analog Discovery')} "
                        f"({dev.get('serial', '?')})"
                    )
            else:
                lines.append("• No Analog Discovery devices attached (install still OK).")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"✗ Device enumeration failed: {exc}")

    ok = lib_ok and dwfpy_ok
    lines.append("")
    lines.append("Result: install OK." if ok else "Result: install incomplete — see above.")
    return InstallCheck(ok=ok, lines=lines)


# --------------------------------------------------------------------------- #
# Frontend loopback self-test
# --------------------------------------------------------------------------- #
@dataclass
class SelfTestSettings:
    """Settings for :func:`run_frontend_selftest`."""

    corr_threshold: float = 0.99  # correlation below this flags a bad connection
    f_sample: float = 1e6  # scope sample rate [Hz]
    buffer_size: int = 8192  # samples per capture (== 4096 * 2 in the original)
    run_current_check: bool = True  # also run the current-measurement sanity check


_COLUMNS = ["DSUB pin", "Correlation"]


def _init_device(device: Any) -> tuple[Any, Any, Any]:
    device.analog_io[0][1].value = 5.0
    device.analog_io[0][0].value = True
    device.analog_io.master_enable = True
    t.sleep(0.1)

    io = device.digital_io
    for i in range(16):
        io[i].setup(enabled=True, state=(i >= 8))

    io[SW_ADC_TO_GND_IDX].output_state = False  # do not ground the ADC input
    io[SW_MEAS_SEL_IDX].output_state = True  # route ADC MUX to the scope
    return io, device.analog_output, device.analog_input


def _correlation(ch1: np.ndarray, ch2: np.ndarray) -> float:
    """Normalised max cross-correlation of two scope channels (~1 == matched)."""
    ch1 = np.asarray(ch1, dtype=float)
    ch2 = np.asarray(ch2, dtype=float)
    std1 = np.std(ch1)
    std2 = np.std(ch2)
    if std1 == 0 or std2 == 0:
        return 0.0
    original = (ch1 - np.mean(ch1)) / (std1 * len(ch1))
    sampled = (ch2 - np.mean(ch2)) / std2
    return float(np.squeeze(np.max(np.correlate(original, sampled, mode="valid"))))


def _current_check(scope, wavegen, io, ctx, s: SelfTestSettings) -> None:
    """Loopback current-measurement sanity check (nominal ~191 uA on hardware)."""
    ctx.report.status("Self-test — current measurement")
    io[SW_ADC_TO_GND_IDX].output_state = True
    io[SW_MEAS_SEL_IDX].output_state = False  # current measurement

    scope[0].setup(range=5.0)
    scope[1].setup(range=5.0)
    wavegen[0].setup(
        frequency=1, function="square", offset=0.5, amplitude=0.5, start=True
    )
    scope.setup_edge_trigger(
        mode="normal", channel=1, slope="rising", level=0.1, hysteresis=0.01
    )
    t.sleep(0.5)
    scope.single(
        sample_rate=s.f_sample, buffer_size=s.buffer_size, configure=True, start=True
    )
    raw_i = np.asarray(scope[1].get_data(), dtype=float)
    ctx.report.capture(scope[0].get_data(), scope[1].get_data(), s.f_sample)

    current_ua = raw_i / R_SENSE / SENSE_MAG * 1e6  # uA
    half = s.buffer_size // 2
    avg_current = float(np.mean(current_ua[-half + 40:-1]))
    rel_err = (avg_current - _EXPECTED_CURRENT_UA) / _EXPECTED_CURRENT_UA
    ctx.report.log(
        f"Expected current: {_EXPECTED_CURRENT_UA:.0f} uA, "
        f"measured: {avg_current:.2f} uA (rel. error {rel_err:.4f})"
    )


def run_frontend_selftest(ctx: MeasurementContext) -> pd.DataFrame:
    """Correlate the DAC->ADC loopback on every DSUB pin; return per-pin results."""
    s: SelfTestSettings = ctx.settings if ctx.settings is not None else SelfTestSettings()
    io, wavegen, scope = _init_device(ctx.device)

    results: list[dict[str, Any]] = []
    for pin in range(1, 51):
        if ctx.should_cancel():
            ctx.report.status("Cancelled")
            break
        if pin == DSUB_GND_PIN:
            continue

        ctx.report.status(f"Self-test — loopback correlation, pin {pin}/50")
        set_adc(io, pin)
        set_dac(io, pin)
        scope[0].setup(range=5.0)
        scope[1].setup(range=5.0)
        scope.setup_edge_trigger(
            mode="normal", channel=0, slope="rising", level=0.1, hysteresis=0.01
        )
        wavegen[0].setup(function="sine", offset=0.5, amplitude=0.5, start=True)
        t.sleep(0.1)
        scope.single(
            sample_rate=s.f_sample, buffer_size=s.buffer_size, configure=True, start=True
        )
        t.sleep(0.1)
        wavegen[0].setup(function="sine", offset=0.0, amplitude=0.0, start=True)

        ch1 = scope[0].get_data()
        ch2 = scope[1].get_data()
        ctx.report.capture(ch1, ch2, s.f_sample)
        corr = _correlation(ch1, ch2)

        row = dict(zip(_COLUMNS, [pin, corr]))
        results.append(row)
        ctx.report.result(row)
        note = "" if corr >= s.corr_threshold else "  <-- faulty connection"
        ctx.report.log(f"Correlation on DSUB pin {pin}: {corr:.4f}{note}")

    if s.run_current_check and not ctx.should_cancel():
        _current_check(scope, wavegen, io, ctx, s)

    ctx.device.analog_io[0][0].value = False  # drop the 5V supply

    df = pd.DataFrame(results, columns=_COLUMNS)
    bad = df[df["Correlation"] < s.corr_threshold] if not df.empty else df
    ctx.report.status(
        f"Self-test done — {len(df)} pins, {len(bad)} below "
        f"threshold {s.corr_threshold}"
    )
    return df
