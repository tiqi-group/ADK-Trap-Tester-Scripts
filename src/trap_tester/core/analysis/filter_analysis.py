"""Attached-RC-filter analysis (refactored from ``filter_tester_analysis.py``).

Both fitted quantities are now gated: the capacitance *and* the filter
resistance are judged against min/max acceptance limits — or, where the golden
reference carries an entry for the pin, against ``expected ± tolerance`` (see
:mod:`~trap_tester.core.analysis.acceptance`). The R window defaults wide open,
so a result analysed with the defaults reports exactly what it did before.

Two verdicts stay ahead of the bands because they describe a point that has no
meaningful value to compare: a row the measurement already flagged as shorted
(``Shorted``/``C_filter == -1``), and a capacitance below ``min_c_abs_nf``,
which means the filter is open / disconnected rather than merely out of spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
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
from trap_tester.core.analysis.quantities import C_FILTER, R_FILTER

_COLUMNS = ["DSUB connector", "DSUB pin", "Shorted", "C_filter_nF", "R_filter_Ohm"]

_CAT_C = C_FILTER.label
_CAT_R = R_FILTER.label


@dataclass
class FilterAnalysisSettings(AcceptanceSettings):
    """Acceptance criteria for the RC-filter characterisation.

    The C window defaults to the ±25 % band the original script applied around a
    1 nF nominal; the R window defaults wide open because ``r_nominal_ohm`` was
    only ever reported, never enforced.
    """

    measurement: ClassVar[str] = "measure_filter"

    # --- FPC: the device's ribbon plugged in reversed ---
    fpc_inverted: bool = fpc_inverted_field()

    # --- Capacitance ---
    c_min_nf: float = field(default=0.75, metadata=meta(_CAT_C, unit="nF"))
    c_max_nf: float = field(default=1.25, metadata=meta(_CAT_C, unit="nF"))
    min_c_abs_nf: float = field(  # below this the cap counts as not detected
        default=0.1, metadata=meta(_CAT_C, unit="nF")
    )

    # --- Filter resistance ---
    r_min_ohm: float = field(default=0.0, metadata=meta(_CAT_R, unit="Ohm"))
    r_max_ohm: float = field(default=1e9, metadata=meta(_CAT_R, unit="Ohm"))

    # --- Reference tolerances (used only where the reference has the pin) ---
    rel_tol: float = field(default=0.1, metadata=meta(CAT_TOL))
    c_abs_tol_nf: float = field(default=0.0, metadata=meta(CAT_TOL, unit="nF"))
    r_abs_tol_ohm: float = field(default=0.0, metadata=meta(CAT_TOL, unit="Ohm"))
    reference: Reference = field(
        default_factory=Reference, metadata=meta(CAT_TOL, hidden=True)
    )

    @classmethod
    def migrate(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Fold the old ``nominal ± rel_tolerance`` criteria into a C window."""
        data = super().migrate(data)
        if "c_nominal_nf" in data:
            nominal = float(data.pop("c_nominal_nf"))
            tol = float(data.get("rel_tolerance", 0.25))
            data.setdefault("c_min_nf", nominal * (1 - tol))
            data.setdefault("c_max_nf", nominal * (1 + tol))
        data.pop("rel_tolerance", None)
        # Never enforced before; dropping it keeps a migrated preset from
        # suddenly failing pins on R.
        data.pop("r_nominal_ohm", None)
        return data


@dataclass
class FilterRow:
    """One row of a ``measure_filter`` result, read and described once."""

    connector: int
    pin: int
    shorted: bool
    c_nf: float
    r_ohm: float
    fpc: int | None
    where: str  # "pin 3 / FPC conductor 7 on connector 0", for messages
    plotted: float  # the C to plot: NaN for a skipped point (C = -1)


def read_filter_rows(df: pd.DataFrame) -> list[FilterRow]:
    """Every row of a filter result (raises if a required column is missing)."""
    require_columns(df, _COLUMNS)
    rows: list[FilterRow] = []
    for _, row in df.iterrows():
        connector = int(row["DSUB connector"])
        pin = int(row["DSUB pin"])
        c_nf = float(row["C_filter_nF"])
        fpc = fpc_conductor(pin)
        rows.append(FilterRow(
            connector=connector,
            pin=pin,
            shorted=bool(row["Shorted"]),
            c_nf=c_nf,
            r_ohm=float(row["R_filter_Ohm"]),
            fpc=fpc,
            where=f"pin {pin} / FPC conductor {fpc} on connector {connector}",
            # C = -1 marks a skipped/short point; it must not be plotted as a value.
            plotted=c_nf if c_nf >= 0 else np.nan,
        ))
    return rows


def precheck(row: FilterRow, min_c_abs_nf: float):
    """The verdicts that come before any band: shorted, or no cap detected.

    Returns the :class:`~trap_tester.core.analysis.Finding` for such a point, or
    ``None`` when the point has a capacitance worth judging.
    """
    from trap_tester.core.analysis import Finding

    measured = {"values": {"c": row.c_nf, "r": row.r_ohm}}
    if row.shorted:
        # DC current flows through the channel -> electrode shorted to GND.
        return Finding(
            row.connector, row.pin, row.fpc, row.plotted, "shorted",
            f"Shorted to GND {row.where} (R {row.r_ohm:.4g} Ohm)", **measured,
        )
    if row.c_nf < min_c_abs_nf:
        # No capacitance seen -> the filter is open / disconnected.
        return Finding(
            row.connector, row.pin, row.fpc, row.plotted, "not_detected",
            f"Cap not detected (open/disconnected) on {row.where}", **measured,
        )
    return None


def analyse_filter(df: pd.DataFrame, s: FilterAnalysisSettings):
    from trap_tester.core.analysis import AnalysisResult, Finding

    findings: list[Finding] = []
    for row in read_filter_rows(df):
        early = precheck(row, s.min_c_abs_nf)
        if early is not None:
            findings.append(early)
            continue
        verdicts = s.judge_all({"c": row.c_nf, "r": row.r_ohm}, row.connector, row.pin)
        findings.append(
            Finding(
                row.connector, row.pin, row.fpc, row.plotted, overall_status(verdicts),
                message_for(row.where, verdicts), **finding_fields(verdicts),
            )
        )

    params = {
        **s.params(),
        "Capacitance detection floor": C_FILTER.format(s.min_c_abs_nf),
    }
    return AnalysisResult(
        measurement="measure_filter",
        title="Filter characterisation analysis",
        findings=findings,
        value_label="C_filter [nF]",
        params=params,
        # A reference makes the band per pin (drawn on the points), so there is
        # no single region to shade.
        band=None if s.has_reference() else s.limits(C_FILTER),
    )
