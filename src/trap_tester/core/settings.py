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


# Choices offered in the settings form (rendered as drop-downs).
_TRIGGER_SOURCES = ["current", "voltage"]  # current (Ch2) is the reliable edge
_TRIGGER_SLOPES = ["rising", "falling", "either"]

# Settings-form section headers (see SettingsForm's ``category`` metadata).
_CAT_TEST = "Testing"
_CAT_DSP = "Digital processing"
_CAT_TRIG = "Trigger"
_CAT_THRESH = "Detection thresholds"


def _meta(category: str, choices: list[str] | None = None) -> dict[str, Any]:
    """Field metadata: a settings-form category and optional drop-down choices."""
    md: dict[str, Any] = {"category": category}
    if choices is not None:
        md["choices"] = choices
    return md


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
    """Settings for the attached-RC-filter characterisation (``measure_filter``).

    Fields are grouped into settings-form sections via their ``category``
    metadata: Testing, Digital processing and Trigger.
    """

    # --- Testing ---
    n_dsub: int = field(default=1, metadata=_meta(_CAT_TEST))  # DSUB connectors to loop
    f_sample: float = field(default=25e6 / 4.0, metadata=_meta(_CAT_TEST))  # sample rate [Hz]
    buffer_size: int = field(default=8192, metadata=_meta(_CAT_TEST))  # samples per capture
    f_square: float = field(  # excitation square-wave freq [Hz]
        default=(25e6 / 4.0) / (8192 * 10), metadata=_meta(_CAT_TEST)
    )
    amplitude: float = field(default=1.5, metadata=_meta(_CAT_TEST))  # step V_IN [V]
    invalid_pins: list[int] = field(
        default_factory=_default_invalid_pins, metadata=_meta(_CAT_TEST)
    )
    file_prefix: str = field(default="test", metadata=_meta(_CAT_TEST))

    # --- Digital processing ---
    cutoff: float = field(default=2e5, metadata=_meta(_CAT_DSP))  # low-pass cutoff [Hz]
    n_avg: int = field(default=5, metadata=_meta(_CAT_DSP))  # fits averaged per pin

    # --- Trigger (see core.measurements._capture) ---
    # "current" (Ch2 @ trigger_level) is the reliable edge for this measurement —
    # it fires on a filter/short/small-cap, and a short clamps the divider
    # voltage low so a "voltage" (Ch1) trigger could miss it. On no trigger
    # within trigger_timeout the scope enters interactive free-run (live scope)
    # mode until the operator presses Continue, then the point is skipped
    # (C=R=-1); the free-run itself records nothing.
    trigger_source: str = field(default="current", metadata=_meta(_CAT_TRIG, _TRIGGER_SOURCES))
    trigger_level: float = field(default=0.4, metadata=_meta(_CAT_TRIG))  # trigger level [V]
    trigger_slope: str = field(default="rising", metadata=_meta(_CAT_TRIG, _TRIGGER_SLOPES))
    trigger_timeout: float = field(default=2.0, metadata=_meta(_CAT_TRIG))  # [s]; <=0 forever


@dataclass
class VoltageSettings(_SettingsMixin):
    """Settings for the voltage meter (``measure_voltage``)."""

    # --- Testing ---
    n_rounds: int = field(default=4, metadata=_meta(_CAT_TEST))  # measurement rounds
    f_sample: float = field(default=25e6, metadata=_meta(_CAT_TEST))  # sample rate [Hz]
    buffer_size: int = field(default=8192, metadata=_meta(_CAT_TEST))
    invalid_pins: list[int] = field(
        default_factory=_default_invalid_pins, metadata=_meta(_CAT_TEST)
    )
    file_prefix: str = field(default="test", metadata=_meta(_CAT_TEST))


@dataclass
class ResistanceSettings(_SettingsMixin):
    """Settings for the DC-resistance / short detection (``measure_resistance``)."""

    # --- Testing ---
    n_rounds: int = field(default=1, metadata=_meta(_CAT_TEST))
    f_sample: float = field(default=1e5, metadata=_meta(_CAT_TEST))  # sample rate [Hz]
    buffer_size: int = field(default=8192, metadata=_meta(_CAT_TEST))
    amplitude: float = field(default=1.5, metadata=_meta(_CAT_TEST))  # applied V_IN [V]
    invalid_pins: list[int] = field(
        default_factory=_default_invalid_pins, metadata=_meta(_CAT_TEST)
    )
    file_prefix: str = field(default="test", metadata=_meta(_CAT_TEST))

    # --- Digital processing ---
    n_samples_for_avg: int = field(  # samples averaged for steady-state current
        default=100, metadata=_meta(_CAT_DSP)
    )

    # --- Detection thresholds ---
    r_short: float = field(default=10.0, metadata=_meta(_CAT_THRESH))  # <= -> shorted [Ohm]
    r_high_imp: float = field(default=1e6, metadata=_meta(_CAT_THRESH))  # >= -> high-Z [Ohm]

    # --- Trigger (default: current channel Ch2 @ trigger_level) ---
    trigger_source: str = field(default="current", metadata=_meta(_CAT_TRIG, _TRIGGER_SOURCES))
    trigger_level: float = field(default=0.4, metadata=_meta(_CAT_TRIG))  # trigger level [V]
    trigger_slope: str = field(default="rising", metadata=_meta(_CAT_TRIG, _TRIGGER_SLOPES))
    trigger_timeout: float = field(default=2.0, metadata=_meta(_CAT_TRIG))  # [s]; <=0 forever


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
