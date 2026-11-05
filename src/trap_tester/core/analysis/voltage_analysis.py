"""Voltage-meter analysis.

The voltage measurement records the mean/std voltage per pin. There is no
intrinsic nominal, so each pin is judged against the ``v_min``/``v_max``
acceptance window — or against ``expected ± tolerance`` where the golden
reference carries an entry for the pin. The window defaults to the frontend's
input range, 0 … 5 V: anything outside it is not merely out of spec, it is a
voltage that permanently damages the tester, so it must be flagged.

Rows are keyed by measurement round rather than by connector, so reference
entries for this measurement use the wildcard key ``"*:<pin>"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import pandas as pd

from trap_tester.core.analysis._common import fpc_conductor, require_columns
from trap_tester.core.analysis.acceptance import (
    CAT_TOL,
    AcceptanceSettings,
    Reference,
    finding_fields,
    fpc_inverted_field,
    message_for,
    meta,
    overall_status,
)
from trap_tester.core.analysis.quantities import V_AVG

_COLUMNS = ["Measurement round", "DSUB pin", "V_avg"]

_CAT_V = V_AVG.label


@dataclass
class VoltageAnalysisSettings(AcceptanceSettings):
    """Acceptance window for the measured per-pin voltage."""

    measurement: ClassVar[str] = "measure_voltage"

    # --- FPC: the device's ribbon plugged in reversed ---
    fpc_inverted: bool = fpc_inverted_field()

    # --- Voltage (default: the frontend's safe input range) ---
    v_min: float = field(default=0.0, metadata=meta(_CAT_V, unit="V"))
    v_max: float = field(default=5.0, metadata=meta(_CAT_V, unit="V"))

    # --- Reference tolerances ---
    rel_tol: float = field(default=0.1, metadata=meta(CAT_TOL))
    v_abs_tol_v: float = field(default=0.0, metadata=meta(CAT_TOL, unit="V"))
    reference: Reference = field(
        default_factory=Reference, metadata=meta(CAT_TOL, hidden=True)
    )


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

        verdicts = s.judge_all({"v": v_avg}, rnd, pin)
        findings.append(
            Finding(
                rnd, pin, fpc, v_avg, overall_status(verdicts),
                message_for(where, verdicts), **finding_fields(verdicts),
            )
        )

    return AnalysisResult(
        measurement="measure_voltage",
        title="Voltage-meter analysis",
        findings=findings,
        value_label="V_avg [V]",
        params=s.params(),
        band=None if s.has_reference() else s.limits(V_AVG),
    )
