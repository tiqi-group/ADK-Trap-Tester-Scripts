"""Helpers shared by the per-measurement analysis functions."""

from __future__ import annotations

import pandas as pd

from trap_tester.mux_mapping import dsub_to_signal, signal_to_fpc


def fpc_conductor(dsub_pin: int) -> int | None:
    """FPC conductor for a DSUB pin, or ``None`` if the pin is not mapped."""
    try:
        return signal_to_fpc[dsub_to_signal[int(dsub_pin)]]
    except (KeyError, ValueError, TypeError):
        return None


def require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """Raise a clear error if the results frame lacks the expected columns."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            "Results file is missing expected columns "
            f"{missing}; found {list(df.columns)}."
        )
