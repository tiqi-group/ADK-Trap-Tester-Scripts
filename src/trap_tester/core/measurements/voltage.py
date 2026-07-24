"""Voltage meter (refactored from ``measurement/measure_voltage.py``).

Uses the tester as a voltmeter: for each pin the ADC MUX is pointed at it and
the mean/std of the captured voltage recorded. Same refactor as the filter
measurement — settings dataclass, reporter/gate callbacks, and per-round rows
committed once (fixing the original retake double-count).
"""

from __future__ import annotations

import time as t
from typing import Any

import numpy as np
import pandas as pd

from trap_tester.core.reporter import MeasurementContext
from trap_tester.core.appconfig import measurements_dir
from trap_tester.core.settings import VoltageSettings, save_result
from trap_tester.utils import (
    SW_ADC_TO_GND_IDX,
    SW_MEAS_SEL_IDX,
    blinking_led,
    disable_dac,
    set_adc,
)

_COLUMNS = ["Measurement round", "DSUB pin", "V_avg", "V_std"]

# Digital-output configuration defined by this measurement (not user settings).
ADC_TO_GND = False
DIGITAL_OUT = {
    "MEAS SEL (SW_MEAS_SEL)": "voltage",
    "ADC → GND (SW_ADC_TO_GND)": "on" if ADC_TO_GND else "off (floating)",
    "DAC output stage": "disabled",
}


def _init_device(device: Any) -> tuple[Any, Any]:
    device.analog_io[0][1].value = 5.0
    device.analog_io[0][0].value = True
    device.analog_io.master_enable = True
    t.sleep(0.1)

    io = device.digital_io
    for i in range(16):
        io[i].setup(enabled=True, state=(i >= 8))

    io[SW_ADC_TO_GND_IDX].output_state = ADC_TO_GND
    io[SW_MEAS_SEL_IDX].output_state = True  # voltage measurement
    disable_dac(io)
    return io, device.analog_input


def run_voltage_measurement(ctx: MeasurementContext) -> pd.DataFrame:
    """Measure the voltage on each configured DSUB pin over N rounds."""
    s: VoltageSettings = ctx.settings
    io, scope = _init_device(ctx.device)
    pins = s.dsub_pins()

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
            set_adc(io, pin)
            scope.record(
                sample_rate=s.f_sample, buffer_size=s.buffer_size, configure=True,
                start=True,
            )
            v_in = np.asarray(scope[1].get_data(), dtype=float)
            ctx.report.capture(scope[0].get_data(), scope[1].get_data(), s.f_sample)
            v_avg = float(np.mean(v_in))
            v_std = float(np.std(v_in))
            row = dict(zip(_COLUMNS, [k, pin, v_avg, v_std]))
            round_rows.append(row)
            ctx.report.result(row)
            ctx.report.log(f"Round {k}, pin {pin}: V_avg {v_avg:.4f} V, V_std {v_std:.4f} V")

        # Blink the on-device USER LED while blocking on the operator.
        with blinking_led(io):
            retake = ctx.gate.confirm("Retake measurement?")
        if retake:
            ctx.report.status(f"Retaking round {k + 1}")
            continue
        results.extend(round_rows)

        if k + 1 < s.n_rounds:
            with blinking_led(io):
                ctx.gate.wait_continue(f"Configure for round {k + 2} and continue")
        k += 1

    return _finalise(results, s, ctx)


def _finalise(results: list[dict[str, Any]], s: VoltageSettings, ctx) -> pd.DataFrame:
    df = pd.DataFrame(results, columns=_COLUMNS)
    ctx.device.analog_io[0][0].value = False
    if s.file_prefix:
        timestr = t.strftime("%Y%m%d-%H%M%S")
        path = save_result(
            df, s, measurements_dir() / f"{s.file_prefix}_v_meas_{timestr}.json",
            "measure_voltage",
        )
        ctx.report.log(f"Saved {path}")
        ctx.report.status(f"Done — {len(df)} rows saved to {path.name}")
    return df
