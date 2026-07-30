"""DC-resistance / short-detection analysis.

The resistance measurement records an estimated resistance-to-ground per pin.
The acceptance limits here *are* the short / high-impedance thresholds — below
``r_min_ohm`` the pin is shorted, above ``r_max_ohm`` it is high impedance — so
they can be revisited without re-measuring. Where the golden reference carries
an entry for the pin the band becomes ``expected ± tolerance`` instead.

Rows are keyed by measurement round rather than by connector, so reference
entries for this measurement use the wildcard key ``"*:<pin>"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
import pandas as pd

from trap_tester.core.analysis._common import fpc_conductor, require_columns
from trap_tester.core.analysis.acceptance import (
    CAT_TOL,
    AcceptanceSettings,
    Reference,
    finding_fields,
    message_for,
    meta,
    overall_status,
)
from trap_tester.core.analysis.quantities import R_EST

_COLUMNS = ["Measurement round", "DSUB pin", "R_est"]

_CAT_R = R_EST.label


@dataclass
class ResistanceAnalysisSettings(AcceptanceSettings):
    """Acceptance window for the per-pin resistance to ground.

    Defaults match ``ResistanceSettings`` in the measurement.
    """

    measurement: ClassVar[str] = "measure_resistance"
    legacy_names: ClassVar[dict[str, str]] = {
        "r_short_ohm": "r_min_ohm",
        "r_high_imp_ohm": "r_max_ohm",
    }

    # --- Resistance to ground ---
    r_min_ohm: float = field(  # below this -> shorted
        default=10.0, metadata=meta(_CAT_R, unit="Ohm")
    )
    r_max_ohm: float = field(  # above this -> high impedance
        default=1e6, metadata=meta(_CAT_R, unit="Ohm")
    )

    # --- Reference tolerances ---
    rel_tol: float = field(default=0.1, metadata=meta(CAT_TOL))
    r_abs_tol_ohm: float = field(default=0.0, metadata=meta(CAT_TOL, unit="Ohm"))
    reference: Reference = field(
        default_factory=Reference, metadata=meta(CAT_TOL, hidden=True)
    )


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

        if r_ohm < 0:
            # R = -1 marks a point the measurement skipped (no trigger). It is
            # not a reading, so it must not be judged as a dead short.
            findings.append(
                Finding(
                    rnd, pin, fpc, np.nan, "not_detected",
                    f"No reading on {where} — point skipped (no trigger)",
                    values={"r": r_ohm},
                )
            )
            continue

        verdicts = s.judge_all({"r": r_ohm}, rnd, pin)
        # plot on a log-friendly axis; 0 Ohm has no place on a log scale
        findings.append(
            Finding(
                rnd, pin, fpc, r_ohm if r_ohm > 0 else np.nan,
                overall_status(verdicts), message_for(where, verdicts),
                **finding_fields(verdicts),
            )
        )

    return AnalysisResult(
        measurement="measure_resistance",
        title="Resistance / short-detection analysis",
        findings=findings,
        value_label="R_est [Ohm]",
        params=s.params(),
        band=None if s.has_reference() else s.limits(R_EST),
        log_y=True,
    )
