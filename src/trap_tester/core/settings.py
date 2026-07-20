"""Measurement settings and result (de)serialisation.

Follows the JSON layout ``measure_filter.py`` already introduced::

    {"settings": {...}, "data": {<pandas DataFrame.to_dict()>}}

so the GUI "Settings" form and the "load a previous measurement" flow share a
single source of truth, and a saved result can repopulate the form.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import pandas as pd

from trap_tester.utils import DSUB_GND_PIN, FPC_SPARE_CONDUCTOR


@dataclass
class FilterSettings:
    """Settings for the attached-RC-filter characterisation (``measure_filter``)."""

    n_dsub: int = 1  # number of DSUB connectors to loop over
    f_sample: float = 25e6 / 4.0  # scope sample rate [Hz]
    buffer_size: int = 8192  # samples per capture
    f_square: float = (25e6 / 4.0) / (8192 * 10)  # excitation square-wave freq [Hz]
    amplitude: float = 1.5  # applied step amplitude V_IN [V]
    cutoff: float = 2e5  # digital low-pass cutoff [Hz]
    n_avg: int = 5  # fits averaged per pin
    file_prefix: str = "test"
    adc_to_gnd: bool = False  # SW_ADC_TO_GND (True for e.g. PSI cryo setups)
    invalid_pins: list[int] = field(
        default_factory=lambda: [DSUB_GND_PIN, FPC_SPARE_CONDUCTOR]
    )

    # ---- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilterSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def dsub_pins(self) -> list[int]:
        """The pins actually measured: 1..50 minus the invalid ones."""
        return sorted(set(range(1, 51)) - set(self.invalid_pins))


def save_result(df: pd.DataFrame, settings: FilterSettings, path: str | Path) -> Path:
    """Write ``{"settings": ..., "data": ...}`` JSON and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"settings": settings.to_dict(), "data": df.to_dict()}
    with path.open("w") as fh:
        json.dump(payload, fh, indent=1)
    return path


def load(path: str | Path) -> tuple[FilterSettings, pd.DataFrame | None]:
    """Load a settings/result JSON.

    Handles both the new ``{"settings", "data"}`` layout and, defensively, an
    older bare-DataFrame dump (in which case settings fall back to defaults).
    """
    path = Path(path)
    with path.open("r") as fh:
        payload = json.load(fh)

    if isinstance(payload, dict) and "settings" in payload:
        settings = FilterSettings.from_dict(payload["settings"])
        data = payload.get("data")
        df = pd.DataFrame.from_dict(data) if data else None
        return settings, df

    # legacy: the file is just a serialised DataFrame
    return FilterSettings(), pd.DataFrame(payload)
