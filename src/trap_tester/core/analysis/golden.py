"""Capture a measurement result as a golden reference.

Marking a result as the golden reference means: *these* numbers are what a good
board looks like. The measured values become the expected values in the analysis
settings (see :class:`~trap_tester.core.analysis.acceptance.Reference`), every
later board is judged against them within the configured tolerance, and saving
the whole thing as a preset makes the criterion re-usable.

Two details decide what actually lands in the table:

* **Keys.** ``measure_filter`` rows carry a DSUB connector, so they are keyed
  ``"<connector>:<pin>"``. The round-based measurements have no connector — the
  same pin is measured once per round — so they are keyed ``"*:<pin>"`` and the
  rounds are aggregated with a **median** (robust to a single bad round).
* **Skips.** A value the measurement never took is not a reading: the
  measurements write ``-1`` for a point that never triggered, and flag shorted
  channels the same way. Any non-finite value, and any negative value of a
  physically non-negative quantity, is dropped — so a skipped point simply has
  no entry and falls back to the global min/max limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

import pandas as pd

from trap_tester.core.analysis.acceptance import WILDCARD, Reference, reference_key
from trap_tester.core.analysis.quantities import quantities_for

CONNECTOR_COLUMN = "DSUB connector"  # only the filter measurement has one
PIN_COLUMN = "DSUB pin"


@dataclass
class Capture:
    """A captured reference plus what was kept and what was dropped."""

    reference: Reference
    n_rows: int  # rows read from the result
    n_points: int  # (connector, pin) points with at least one value
    n_skipped: int  # individual values dropped as "not a reading"

    def describe(self) -> str:
        text = f"{self.n_points} point(s) captured from {self.n_rows} row(s)"
        if self.n_skipped:
            text += f", {self.n_skipped} value(s) skipped (no reading)"
        return text


def _usable(value: Any, non_negative: bool) -> float | None:
    """A finite reading, or ``None`` when the value is a skip marker."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if non_negative and number < 0:
        return None
    return number


def _row_key(row: Any, has_connector: bool) -> str | None:
    """The reference key for one row, or ``None`` if it has no usable pin."""
    try:
        pin = int(row[PIN_COLUMN])
    except (TypeError, ValueError):
        return None
    connector: int | str = WILDCARD
    if has_connector:
        try:
            connector = int(row[CONNECTOR_COLUMN])
        except (TypeError, ValueError):
            return None
    return reference_key(connector, pin)


def capture(
    df: pd.DataFrame, measurement: str, source: str = "", when: str | None = None
) -> Capture:
    """Build a :class:`Reference` from a result frame.

    ``source`` (typically the result file name) and ``when`` are recorded on the
    reference so a saved preset stays traceable back to the board it came from.
    """
    quantities = quantities_for(measurement)
    if not quantities:
        raise KeyError(f"No analysis available for measurement {measurement!r}")
    if df is None or PIN_COLUMN not in df.columns:
        raise ValueError(f"Result has no '{PIN_COLUMN}' column to key a reference on.")

    # key -> quantity key -> every reading seen (several rounds -> several values)
    collected: dict[str, dict[str, list[float]]] = {}
    n_rows = 0
    n_skipped = 0
    columns = [q for q in quantities if q.column in df.columns]

    for _, row in df.iterrows():
        n_rows += 1
        key = _row_key(row, CONNECTOR_COLUMN in df.columns)
        if key is None:
            continue
        for q in columns:
            value = _usable(row[q.column], q.non_negative)
            if value is None:
                n_skipped += 1
                continue
            collected.setdefault(key, {}).setdefault(q.key, []).append(value)

    values = {
        key: {qkey: float(median(readings)) for qkey, readings in entry.items()}
        for key, entry in collected.items()
    }
    reference = Reference(
        values=values,
        source=source,
        captured=when or datetime.now().isoformat(timespec="seconds"),
    )
    return Capture(
        reference=reference, n_rows=n_rows, n_points=len(values), n_skipped=n_skipped
    )


__all__ = ["CONNECTOR_COLUMN", "PIN_COLUMN", "Capture", "capture"]
