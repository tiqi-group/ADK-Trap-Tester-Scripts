"""Ad-hoc FPC permutations, applied to a result before it is analysed.

A device under test can be plugged into the tester's front-end FPC connector the
other way round, so its ribbon arrives with the conductor numbering reversed: the
tester's conductor ``c`` touches the device's conductor ``52 - c`` (51 becomes 1,
50 becomes 2, … and 26 stays put). The inversion is undone *logically, at the
tester end*: each measured row is relabelled with the DSUB pin whose signal
travels on the device's conductor, as if the ribbon had been plugged in straight.

Everything downstream then works in the device's numbering, unchanged: the
cross-interface mapping (which describes the device side of the tester and so
stays valid), a golden reference, a loopback board and the connector map.

The permutation only concerns pins that leave the tester on the FPC. A DSUB pin
with no FPC conductor (pin 9, GND) keeps its number. On the 49 signal conductors
the inversion is a bijection, so no two rows ever land on the same pin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from trap_tester.mux_mapping import (
    FPC_N_CONDUCTORS,
    dsub_to_signal,
    signal_to_dsub,
    signal_to_fpc,
)

if TYPE_CHECKING:
    import pandas as pd

PIN_COLUMN = "DSUB pin"

_fpc_to_signal = {conductor: signal for signal, conductor in signal_to_fpc.items()}


def invert_conductor(conductor: int) -> int:
    """The conductor on the other end of a reversed ribbon: ``52 - conductor``."""
    return FPC_N_CONDUCTORS + 1 - int(conductor)


def inverted_dsub_pin(pin: int) -> int:
    """The DSUB pin a tester pin reaches through an inverted FPC.

    Tester pin -> its FPC conductor -> the inverted conductor -> the DSUB pin whose
    signal normally runs on that conductor. A pin that does not leave the tester
    on the FPC is returned unchanged.
    """
    signal = dsub_to_signal.get(int(pin))
    conductor = signal_to_fpc.get(signal) if signal is not None else None
    if conductor is None:
        return int(pin)
    target = _fpc_to_signal.get(invert_conductor(conductor))
    dsub = signal_to_dsub.get(target) if target is not None else None
    return int(pin) if dsub is None else dsub


def invert_fpc(df: pd.DataFrame) -> pd.DataFrame:
    """A copy of a result frame with every ``DSUB pin`` relabelled through the
    inverted FPC (the input is never modified)."""
    if df is None or PIN_COLUMN not in df.columns:
        return df
    out = df.copy()
    out[PIN_COLUMN] = [inverted_dsub_pin(p) for p in out[PIN_COLUMN]]
    return out


def prepare_frame(df: pd.DataFrame, settings: Any) -> pd.DataFrame:
    """The frame an analysis actually reads: ``df`` with the permutations the
    ``settings`` enable applied (currently: the FPC inversion)."""
    if getattr(settings, "fpc_inverted", False):
        return invert_fpc(df)
    return df


__all__ = [
    "PIN_COLUMN",
    "invert_conductor",
    "invert_fpc",
    "inverted_dsub_pin",
    "prepare_frame",
]
