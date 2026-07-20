"""Measurement settings and result (de)serialisation.

Files use the JSON layout ``measure_filter.py`` introduced, extended with a
``measurement`` key so a saved result knows which measurement produced it::

    {"measurement": "measure_filter", "settings": {...}, "data": {...}}

so the GUI "Settings" form and the "load a previous measurement" flow share a
single source of truth and can rebuild the correct form for any measurement.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import pandas as pd

from trap_tester.utils import DSUB_GND_PIN, FPC_SPARE_CONDUCTOR


def _default_invalid_pins() -> list[int]:
    return [DSUB_GND_PIN, FPC_SPARE_CONDUCTOR]


class _SettingsMixin:
    """Shared (de)serialisation + pin helpers for every settings dataclass."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{k: v for k, v in data.items() if k in known})

    def dsub_pins(self) -> list[int]:
        """The pins actually measured: 1..50 minus the invalid ones."""
        return sorted(set(range(1, 51)) - set(self.invalid_pins))  # type: ignore[attr-defined]


@dataclass
class FilterSettings(_SettingsMixin):
    """Settings for the attached-RC-filter characterisation (``measure_filter``)."""

    n_dsub: int = 1  # number of DSUB connectors to loop over
    f_sample: float = 25e6 / 4.0  # scope sample rate [Hz]
    buffer_size: int = 8192  # samples per capture
    f_square: float = (25e6 / 4.0) / (8192 * 10)  # excitation square-wave freq [Hz]
    amplitude: float = 1.5  # applied step amplitude V_IN [V]
    cutoff: float = 2e5  # digital low-pass cutoff [Hz]
    n_avg: int = 5  # fits averaged per pin
    file_prefix: str = "test"
    invalid_pins: list[int] = field(default_factory=_default_invalid_pins)


@dataclass
class VoltageSettings(_SettingsMixin):
    """Settings for the voltage meter (``measure_voltage``)."""

    n_rounds: int = 4  # measurement rounds (e.g. per connector)
    f_sample: float = 25e6  # scope sample rate [Hz]
    buffer_size: int = 8192
    file_prefix: str = "test"
    invalid_pins: list[int] = field(default_factory=_default_invalid_pins)


@dataclass
class ResistanceSettings(_SettingsMixin):
    """Settings for the DC-resistance / short detection (``measure_resistance``)."""

    n_rounds: int = 1
    f_sample: float = 1e5  # scope sample rate [Hz]
    buffer_size: int = 8192
    amplitude: float = 1.5  # applied V_IN [V]
    n_samples_for_avg: int = 100  # samples averaged for steady-state current
    r_short: float = 10.0  # below this [Ohm] -> flagged shorted
    r_high_imp: float = 1e6  # above this [Ohm] -> flagged high impedance
    file_prefix: str = "test"
    invalid_pins: list[int] = field(default_factory=_default_invalid_pins)


# measurement key (== script stem) -> settings dataclass
_SETTINGS_BY_KEY: dict[str, type] = {
    "measure_filter": FilterSettings,
    "measure_voltage": VoltageSettings,
    "measure_resistance": ResistanceSettings,
}


def settings_type_for(measurement: str | None) -> type:
    """The settings dataclass for a measurement key (FilterSettings fallback)."""
    return _SETTINGS_BY_KEY.get(measurement or "", FilterSettings)


def save_result(
    df: pd.DataFrame, settings: Any, path: str | Path, measurement: str
) -> Path:
    """Write ``{measurement, settings, data}`` JSON and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "measurement": measurement,
        "settings": settings.to_dict(),
        "data": df.to_dict(),
    }
    with path.open("w") as fh:
        json.dump(payload, fh, indent=1)
    return path


def load(path: str | Path) -> tuple[str | None, Any, pd.DataFrame | None]:
    """Load a settings/result JSON.

    Returns ``(measurement_key, settings, data)``. Handles the new
    ``{measurement, settings, data}`` layout, the older ``{settings, data}``
    (assumed to be a filter result), and a bare-DataFrame dump.
    """
    path = Path(path)
    with path.open("r") as fh:
        payload = json.load(fh)

    if isinstance(payload, dict) and "settings" in payload:
        measurement = payload.get("measurement", "measure_filter")
        settings = settings_type_for(measurement).from_dict(payload["settings"])
        data = payload.get("data")
        df = pd.DataFrame.from_dict(data) if data else None
        return measurement, settings, df

    # legacy: the file is just a serialised DataFrame
    return None, FilterSettings(), pd.DataFrame(payload)
