"""DC-resistance / short-detection analysis.

The resistance measurement records an estimated resistance-to-ground per pin.
This analysis re-classifies each pin against user-tweakable thresholds (so the
short / high-impedance limits can be revisited without re-measuring) and
produces per-pin findings + a plot of R_est per pin.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trap_tester.core.analysis._common import fpc_conductor, require_columns

_COLUMNS = ["Measurement round", "DSUB pin", "R_est"]


@dataclass
class ResistanceAnalysisSettings:
    """Thresholds for flagging shorted / high-impedance pins.

    Defaults match ``ResistanceSettings`` in the measurement.
    """

    r_short_ohm: float = 10.0  # at/below this -> shorted
    r_high_imp_ohm: float = 1e6  # at/above this -> high impedance


def analyse_resistance(df: pd.DataFrame, s: ResistanceAnalysisSettings):
    from trap_tester.core.analysis import AnalysisResult, Finding

    require_columns(df, _COLUMNS)
    findings: list[Finding] = []

    for _, row in df.iterrows():
        rnd = int(row["Measurement round"])
        pin = int(row["DSUB pin"])
        r_ohm = float(row["R_est"])
        fpc = fpc_conductor(pin)
        where = f"pin {pin} / FPC conductor {fpc} (round {rnd})"

        if r_ohm <= s.r_short_ohm:
            status = "shorted"
            message = f"Shorted on {where}: R {r_ohm:.4g} Ohm"
        elif r_ohm >= s.r_high_imp_ohm:
            status = "high_impedance"
            message = f"High impedance on {where}: R {r_ohm:.4g} Ohm"
        else:
            status = "ok"
            message = f"Nominal on {where}: R {r_ohm:.4g} Ohm"

        # plot on a log-friendly axis; clamp non-positive values so log scales work
        value = r_ohm if r_ohm > 0 else np.nan
        findings.append(Finding(rnd, pin, fpc, value, status, message))

    return AnalysisResult(
        measurement="measure_resistance",
        title="Resistance / short-detection analysis",
        findings=findings,
        value_label="R_est [Ohm]",
        params={
            "r_short_ohm": s.r_short_ohm,
            "r_high_imp_ohm": s.r_high_imp_ohm,
        },
        band=(s.r_short_ohm, s.r_high_imp_ohm),
        log_y=True,
    )
