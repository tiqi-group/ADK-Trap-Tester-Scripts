"""Attached-RC-filter analysis (refactored from ``filter_tester_analysis.py``).

Same decision tree as the original script — a capacitance below ``min_c_abs``
means "not detected", and a capacitance more than ``rel_tolerance`` away from
``c_nominal`` is "off-nominal" — but the verdict is returned as structured
:class:`~trap_tester.core.analysis.Finding` objects (with the FPC-conductor
mapping preserved) instead of being printed to a ``-result.txt``. Rows that the
measurement already flagged as shorted (``C_filter == -1``) are reported as
shorted rather than being mistaken for a missing capacitor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trap_tester.core.analysis._common import fpc_conductor, require_columns

_COLUMNS = ["DSUB connector", "DSUB pin", "Shorted", "C_filter_nF", "R_filter_Ohm"]


@dataclass
class FilterAnalysisSettings:
    """Acceptance criteria for the RC-filter characterisation.

    Defaults match ``analysis/filter_tester_analysis.py``.
    """

    c_nominal_nf: float = 1.0  # expected filter capacitance [nF]
    r_nominal_ohm: float = 2000.0  # expected filter resistance [Ohm]
    rel_tolerance: float = 0.25  # allowed fractional deviation of C
    min_c_abs_nf: float = 0.1  # below this [nF] the cap counts as not detected


def analyse_filter(df: pd.DataFrame, s: FilterAnalysisSettings):
    from trap_tester.core.analysis import AnalysisResult, Finding

    require_columns(df, _COLUMNS)
    findings: list[Finding] = []

    for _, row in df.iterrows():
        connector = int(row["DSUB connector"])
        pin = int(row["DSUB pin"])
        shorted = bool(row["Shorted"])
        c_nf = float(row["C_filter_nF"])
        r_ohm = float(row["R_filter_Ohm"])
        fpc = fpc_conductor(pin)
        where = f"pin {pin} / FPC conductor {fpc} on connector {connector}"

        hi = s.c_nominal_nf * (1 + s.rel_tolerance)
        lo = s.c_nominal_nf * (1 - s.rel_tolerance)
        if shorted:
            # DC current flows through the channel -> electrode shorted to GND.
            status = "shorted"
            message = f"Shorted to GND {where} (R {r_ohm:.4g} Ohm)"
        elif c_nf < s.min_c_abs_nf:
            # No capacitance seen -> the filter is open / disconnected.
            status = "not_detected"
            message = f"Cap not detected (open/disconnected) on {where}"
        elif c_nf > hi:
            # Above nominal: both filter caps charged -> likely several channels
            # shorted together (see AFE README, "Shorts between Electrodes").
            status = "over_nominal"
            message = (
                f"Cap above nominal on {where} (possible inter-electrode/board "
                f"short): C {c_nf:.4g} nF, R {r_ohm:.4g} Ohm"
            )
        elif c_nf < lo:
            status = "off_nominal"
            message = (
                f"Cap below nominal on {where}: C {c_nf:.4g} nF, R {r_ohm:.4g} Ohm"
            )
        else:
            status = "ok"
            message = f"Nominal on {where}: C {c_nf:.4g} nF, R {r_ohm:.4g} Ohm"

        findings.append(
            Finding(connector, pin, fpc, c_nf if c_nf >= 0 else np.nan, status, message)
        )

    tol = s.rel_tolerance
    return AnalysisResult(
        measurement="measure_filter",
        title="Filter characterisation analysis",
        findings=findings,
        value_label="C_filter [nF]",
        params={
            "c_nominal_nf": s.c_nominal_nf,
            "r_nominal_ohm": s.r_nominal_ohm,
            "rel_tolerance": s.rel_tolerance,
            "min_c_abs_nf": s.min_c_abs_nf,
        },
        band=(s.c_nominal_nf * (1 - tol), s.c_nominal_nf * (1 + tol)),
        nominal=s.c_nominal_nf,
    )
