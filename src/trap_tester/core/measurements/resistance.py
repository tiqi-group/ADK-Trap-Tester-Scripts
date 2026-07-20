"""DC resistance / short detection (refactored from ``measure_resistance.py``).

Drives a square wave and, per pin, estimates the resistance to ground from both
the steady-state current and the voltage divider, flagging shorted and
high-impedance pins. Same refactor pattern as the other measurements.
"""

from __future__ import annotations

import time as t
from typing import Any

import numpy as np
import pandas as pd

from trap_tester.core.reporter import MeasurementContext
from trap_tester.core.settings import ResistanceSettings, save_result
from trap_tester.utils import (
    GAIN_FRONTEND,
    R_REF,
    R_SENSE,
    SENSE_MAG,
    SW_ADC_TO_GND_IDX,
    SW_MEAS_SEL_IDX,
    set_adc,
    set_dac,
)

_COLUMNS = ["Measurement round", "DSUB pin", "R_est", "Shorted", "High impedance"]
_R_AFE = R_REF + R_SENSE

# Digital-output configuration defined by this measurement (not user settings).
ADC_TO_GND = False
DIGITAL_OUT = {
    "MEAS SEL (SW_MEAS_SEL)": "current",
    "ADC → GND (SW_ADC_TO_GND)": "on" if ADC_TO_GND else "off (floating)",
    "DAC output stage": "enabled — square-wave drive",
}


def _init_device(device: Any) -> tuple[Any, Any, Any]:
    device.analog_io[0][1].value = 5.0
    device.analog_io[0][0].value = True
    device.analog_io.master_enable = True
    t.sleep(0.1)

    io = device.digital_io
    for i in range(16):
        io[i].setup(enabled=True, state=(i >= 8))

    io[SW_ADC_TO_GND_IDX].output_state = ADC_TO_GND
    io[SW_MEAS_SEL_IDX].output_state = False  # current measurement

    scope = device.analog_input
    scope[0].setup(range=5.0)
    scope[1].setup(range=5.0)
    scope.setup_edge_trigger(
        mode="normal", channel=1, slope="rising", level=0.4, hysteresis=0.01
    )
    return io, device.analog_output, scope


def _estimate_pin(s: ResistanceSettings, i_meas: np.ndarray, v_meas: np.ndarray) -> dict:
    n = s.n_samples_for_avg
    i_end = np.mean(i_meas[-n:])
    v_end = np.mean(v_meas[-n:])

    r_tot_from_i = s.amplitude / i_end
    r_to_gnd_from_i = max(0.0, r_tot_from_i - _R_AFE)
    ratio = v_end / s.amplitude
    r_to_gnd_from_v = (ratio / (1 - ratio)) * _R_AFE

    high_imp = r_to_gnd_from_v > s.r_high_imp
    if r_to_gnd_from_i < s.r_short:
        return {"shorted": True, "r": float(r_to_gnd_from_i), "high_imp": high_imp}
    return {"shorted": False, "r": float(r_to_gnd_from_v), "high_imp": high_imp}


def run_resistance_measurement(ctx: MeasurementContext) -> pd.DataFrame:
    """Estimate each pin's resistance to ground and flag shorts / high impedance."""
    s: ResistanceSettings = ctx.settings
    io, wavegen, scope = _init_device(ctx.device)
    pins = s.dsub_pins()

    f_square = s.f_sample / (s.buffer_size * 10)
    wavegen[0].setup(
        frequency=f_square, function="square",
        offset=0.5 * s.amplitude / GAIN_FRONTEND,
        amplitude=0.5 * s.amplitude / GAIN_FRONTEND, start=True,
    )

    results: list[dict[str, Any]] = []
    k = 0
    while k < s.n_rounds:
        if ctx.should_cancel():
            ctx.report.status("Cancelled")
            break

        round_rows: list[dict[str, Any]] = []
        for pin in pins:
            if ctx.should_cancel():
                ctx.report.status("Cancelled")
                return _finalise(results, s, ctx)
            ctx.report.status(f"Round {k + 1}/{s.n_rounds} — pin {pin}")
            set_dac(io, pin)
            set_adc(io, pin)
            scope.single(
                sample_rate=s.f_sample, buffer_size=s.buffer_size, configure=True,
                start=True,
            )
            i_meas = np.asarray(scope[1].get_data(), dtype=float) / (R_SENSE * SENSE_MAG)
            v_meas = np.asarray(scope[0].get_data(), dtype=float)
            ctx.report.capture(scope[0].get_data(), scope[1].get_data(), s.f_sample)

            est = _estimate_pin(s, i_meas, v_meas)
            row = dict(zip(_COLUMNS, [k, pin, est["r"], est["shorted"], est["high_imp"]]))
            round_rows.append(row)
            ctx.report.result(row)
            ctx.report.log(
                f"Round {k}, pin {pin}: R_est {est['r']:.4g} Ohm, "
                f"shorted {est['shorted']}, high-Z {est['high_imp']}"
            )

        if ctx.gate.confirm("Retake measurement?"):
            ctx.report.status(f"Retaking round {k + 1}")
            continue
        results.extend(round_rows)

        if k + 1 < s.n_rounds:
            ctx.gate.wait_continue(f"Configure for round {k + 2} and continue")
        k += 1

    return _finalise(results, s, ctx)


def _finalise(results: list[dict[str, Any]], s: ResistanceSettings, ctx) -> pd.DataFrame:
    df = pd.DataFrame(results, columns=_COLUMNS)
    ctx.device.analog_io[0][0].value = False
    if s.file_prefix:
        timestr = t.strftime("%Y%m%d-%H%M%S")
        path = save_result(
            df, s, f"results/{s.file_prefix}_r_meas_{timestr}.json", "measure_resistance"
        )
        ctx.report.log(f"Saved {path}")
        ctx.report.status(f"Done — {len(df)} rows saved to {path.name}")
    return df
