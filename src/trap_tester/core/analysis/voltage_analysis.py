"""Voltage-meter analysis.

The voltage measurement records the mean/std voltage per pin. There is no
intrinsic nominal, so this analysis flags pins whose average voltage falls
outside a user-defined acceptance window (defaults are wide open, so nothing is
flagged until the operator sets a window).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trap_tester.core.analysis._common import fpc_conductor, require_columns

_COLUMNS = ["Measurement round", "DSUB pin", "V_avg"]


@dataclass
class VoltageAnalysisSettings:
    """Acceptance window for the measured per-pin voltage."""

    v_min: float = -10.0  # below this [V] -> off-nominal
    v_max: float = 10.0  # above this [V] -> off-nominal


def analyse_voltage(df: pd.DataFrame, s: VoltageAnalysisSettings):
    from trap_tester.core.analysis import AnalysisResult, Finding

    require_columns(df, _COLUMNS)
    findings: list[Finding] = []

    for _, row in df.iterrows():
        rnd = int(row["Measurement round"])
        pin = int(row["DSUB pin"])
        v_avg = float(row["V_avg"])
        fpc = fpc_conductor(pin)
        where = f"pin {pin} / FPC conductor {fpc} (round {rnd})"

        if not (s.v_min <= v_avg <= s.v_max):
            status = "off_nominal"
            message = (
                f"Voltage out of range on {where}: {v_avg:.4g} V "
                f"(window [{s.v_min}, {s.v_max}] V)"
            )
        else:
            status = "ok"
            message = f"Nominal on {where}: {v_avg:.4g} V"

        findings.append(Finding(rnd, pin, fpc, v_avg, status, message))

    return AnalysisResult(
        measurement="measure_voltage",
        title="Voltage-meter analysis",
        findings=findings,
        value_label="V_avg [V]",
        params={"v_min": s.v_min, "v_max": s.v_max},
        band=(s.v_min, s.v_max),
    )
