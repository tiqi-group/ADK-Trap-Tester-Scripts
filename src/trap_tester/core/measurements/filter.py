"""Attached-RC-filter characterisation (refactored from ``measure_filter.py``).

The physics, decision tree and analytical fit are preserved verbatim from the
original script; what changed:

* module constants -> ``ctx.settings`` (a :class:`FilterSettings`);
* ``print`` -> ``ctx.report.log`` / ``ctx.report.status``;
* each capture is published via ``ctx.report.capture`` for live plotting;
* the blocking ``input()`` prompts -> ``ctx.gate.confirm`` / ``wait_continue``;
* **bug fix** — per-round rows are collected in a single buffer and committed
  to the results exactly once (when the operator declines a retake). The
  original appended rows both inside the pin loop and again afterwards, and
  incremented the connector counter mid-loop, double-counting on retake.
"""

from __future__ import annotations

import time as t
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal
from scipy.optimize import curve_fit

from trap_tester.core.reporter import MeasurementContext
from trap_tester.core.settings import FilterSettings, save_result
from trap_tester.utils import (
    EN_DAC1_IDX,
    GAIN_FRONTEND,
    R_REF,
    R_SENSE,
    SENSE_MAG,
    SW_ADC_TO_GND_IDX,
    SW_MEAS_SEL_IDX,
    set_dac,
    step_double_rc,
)

_COLUMNS = [
    "DSUB connector",
    "DSUB pin",
    "Shorted",
    "C_filter_nF",
    "R_filter_Ohm",
    "Bandwidth",
    "Perr_max",
]
_N_TAIL = 100  # samples averaged for steady-state estimates

# Digital-output configuration defined by this measurement (not user settings).
# SW_ADC_TO_GND: keep the ADC input floating (set True for e.g. PSI cryo setups).
ADC_TO_GND = False
DIGITAL_OUT = {
    "MEAS SEL (SW_MEAS_SEL)": "current",
    "ADC → GND (SW_ADC_TO_GND)": "on" if ADC_TO_GND else "off (floating)",
    "DAC output stage": "enabled — square-wave drive",
}


def _init_device(device: Any) -> tuple[Any, Any, Any]:
    """Power up the frontend, initialise DIO and return (io, wavegen, scope)."""
    device.analog_io[0][1].value = 5.0
    device.analog_io[0][0].value = True
    device.analog_io.master_enable = True
    t.sleep(0.1)

    io = device.digital_io
    for i in range(16):
        io[i].setup(enabled=True, state=(i >= 8))

    io[SW_ADC_TO_GND_IDX].output_state = ADC_TO_GND
    io[SW_MEAS_SEL_IDX].output_state = False  # current measurement
    return io, device.analog_output, device.analog_input


def _capture(scope: Any, ctx: MeasurementContext, fs: float, buf: int, b, a):
    """Take a single shot, publish it for live plotting, return filtered traces."""
    scope.single(sample_rate=fs, buffer_size=buf, configure=True, start=True)
    raw_v = scope[0].get_data()
    raw_i = scope[1].get_data()
    ctx.report.capture(raw_v, raw_i, fs)
    v_divider = signal.filtfilt(b, a, raw_v)
    i_to_trap = signal.filtfilt(b, a, raw_i) / (R_SENSE * SENSE_MAG)  # A
    return v_divider, i_to_trap


def _measure_baseline(scope, wavegen, ctx, s, b, a):
    """Parasitic-capacitance baseline (DAC on, MUX not yet connected)."""
    io_amp = 0.5 * s.amplitude / GAIN_FRONTEND
    scope[0].setup(range=5.0)
    scope[1].setup(range=5.0)
    wavegen[0].setup(
        frequency=s.f_square, function="square", offset=io_amp, amplitude=io_amp,
        start=True,
    )
    scope.setup_edge_trigger(
        mode="normal", channel=1, slope="rising", level=0.4, hysteresis=0
    )
    v_divider, i_to_trap = _capture(scope, ctx, s.f_sample, s.buffer_size, b, a)

    i_offset = np.mean(i_to_trap[:_N_TAIL])
    c_baseline = np.sum(i_to_trap - i_offset) / s.f_sample / s.amplitude  # C = Q/V
    i_ss_baseline = np.mean(i_to_trap[-_N_TAIL:])
    ctx.report.log(f"Baseline: C_par = {c_baseline * 1e12:.2f} pF")
    return c_baseline, i_ss_baseline


def _row(k: int, pin: int, shorted: bool, c_nf: float, r: float, bw: float, perr: float):
    return dict(zip(_COLUMNS, [k, pin, shorted, c_nf, r, bw, perr]))


def _classify_offnominal(ctx, s, k, pin, v_end, i_end, i_short) -> dict[str, Any]:
    """Not-settled branch: distinguish shorts before/after the filter."""
    r_from_i = (s.amplitude / i_end) - R_REF
    ratio = v_end / s.amplitude
    r_from_v = (ratio / (1 - ratio)) * R_REF
    r_mean = -1.0
    if np.abs((r_from_i / r_from_v) - 1) < 0.1:
        ctx.report.log("electrode possibly shorted after filter")
        r_mean = 0.5 * (r_from_i + r_from_v)
    elif 0.5 * i_short < i_end < 1.1 * i_short:
        ctx.report.log(f"wire possibly shorted before filter, i_end: {i_end:.2}A")
        r_mean = 0.0
    else:
        ctx.report.log("unrecognised fault")
    ctx.report.log(f"R_filter = {r_mean}")
    return _row(k, pin, True, -1, r_mean, -1, -1)


def _fit_filter(scope, ctx, s, k, pin, b, a, c_baseline, i_offset) -> dict[str, Any]:
    """Nominal branch: average N_AVG double-RC fits of the step response."""
    scope.setup_edge_trigger(
        mode="normal", channel=0, slope="rising", level=0.05, hysteresis=0.01
    )
    c_est = np.zeros(s.n_avg)
    r_est = np.zeros(s.n_avg)
    perr_acc = np.zeros(6)
    _t = np.arange(s.buffer_size) / s.f_sample
    for i in range(s.n_avg):
        v_divider, i_to_trap = _capture(scope, ctx, s.f_sample, s.buffer_size, b, a)
        c_est_i = np.sum(i_to_trap - i_offset) / s.f_sample / s.amplitude - c_baseline
        c_est_i = max(c_est_i, 1e-15)
        lower = [0.98 * c_baseline, 0.98 * c_est_i, 10460, 100, _t[0], 0.95 * s.amplitude]
        upper = [1.02 * c_baseline, 1.02 * c_est_i, 10500, 10000, _t[-1], 1.05 * s.amplitude]
        popt, pcov = curve_fit(step_double_rc, _t, v_divider, bounds=(lower, upper))
        c_est[i] = popt[1]
        r_est[i] = popt[3]
        perr_acc += np.sqrt(np.diag(pcov)) / s.n_avg

    c_mean = float(np.mean(c_est))
    r_mean = float(np.mean(r_est))
    bandwidth = 1 / (c_mean * r_mean * 2 * np.pi)
    perr_max = float(np.max(perr_acc[:4]))  # R and C params only
    ctx.report.log(
        f"Connector {k}, Pin {pin}: C_filter {c_mean * 1e9:.3f} nF, "
        f"R_filter {r_mean:.3g} Ohm, BW {bandwidth:.3g} Hz, Perr {perr_max:.3g}"
    )
    return _row(k, pin, False, c_mean * 1e9, r_mean, bandwidth, perr_max)


def _measure_pin(scope, io, ctx, s, k, pin, b, a, c_baseline, i_ss_baseline, i_short):
    """Measure one DSUB pin and return its result row."""
    set_dac(io, pin)
    v_divider, i_to_trap = _capture(scope, ctx, s.f_sample, s.buffer_size, b, a)
    i_offset = np.mean(i_to_trap[:_N_TAIL])
    i_end = np.mean(i_to_trap[-_N_TAIL:])
    v_end = np.mean(v_divider[-_N_TAIL:])

    settled = 0.98 * s.amplitude < v_end < 1.02 * s.amplitude
    if not settled:
        return _classify_offnominal(ctx, s, k, pin, v_end, i_end, i_short)

    if i_end > 2 * i_ss_baseline:
        # elevated current: either still charging, or a high-impedance short
        _, i_slow = _capture(scope, ctx, s.f_sample / 2, s.buffer_size, b, a)
        if np.mean(i_slow[-_N_TAIL:]) >= 1.5 * i_end:
            ctx.report.log("Fishy stuff, probably high impedance short")
            return _row(k, pin, False, -1, -1, -1, -1)
        ctx.report.log("Filter still charging")
    else:
        ctx.report.log("nominal")

    return _fit_filter(scope, ctx, s, k, pin, b, a, c_baseline, i_offset)


def run_filter_measurement(ctx: MeasurementContext) -> pd.DataFrame:
    """Characterise attached RC filters across the configured DSUB connectors.

    Returns the assembled results DataFrame; also writes a settings+data JSON
    into ``results/`` when ``settings.file_prefix`` is set.
    """
    s: FilterSettings = ctx.settings
    io, wavegen, scope = _init_device(ctx.device)

    nyq = 0.5 * s.f_sample
    b, a = signal.butter(4, s.cutoff / nyq, btype="low", analog=False)
    i_short = s.amplitude / R_REF
    pins = s.dsub_pins()

    # enable DAC output stage for the baseline (MUX not yet pointed at a pin)
    for i in range(2):
        io[EN_DAC1_IDX + i].output_state = True
    c_baseline, i_ss_baseline = _measure_baseline(scope, wavegen, ctx, s, b, a)

    results: list[dict[str, Any]] = []
    k = 0
    while k < s.n_dsub:
        if ctx.should_cancel():
            ctx.report.status("Cancelled")
            break

        round_rows: list[dict[str, Any]] = []
        for pin in pins:
            if ctx.should_cancel():
                ctx.report.status("Cancelled")
                return _finalise(results, s, ctx)
            ctx.report.status(f"Connector {k + 1}/{s.n_dsub} — pin {pin}")
            row = _measure_pin(
                scope, io, ctx, s, k, pin, b, a, c_baseline, i_ss_baseline, i_short
            )
            round_rows.append(row)
            ctx.report.result(row)

        # Commit the round only once the operator is happy with it.
        if ctx.gate.confirm("Retake measurement?"):
            ctx.report.status(f"Retaking connector {k + 1}")
            continue
        results.extend(round_rows)

        if k + 1 < s.n_dsub:
            ctx.gate.wait_continue(f"Switch to DSUB connector {k + 2} and continue")
        k += 1

    return _finalise(results, s, ctx)


def _finalise(results: list[dict[str, Any]], s: FilterSettings, ctx) -> pd.DataFrame:
    df = pd.DataFrame(results, columns=_COLUMNS)
    ctx.device.analog_io[0][0].value = False  # drop the 5V supply
    if s.file_prefix:
        timestr = t.strftime("%Y%m%d-%H%M%S")
        path = save_result(
            df, s, f"results/{s.file_prefix}_filter_test_{timestr}.json", "measure_filter"
        )
        ctx.report.log(f"Saved {path}")
        ctx.report.status(f"Done — {len(df)} rows saved to {path.name}")
    return df
