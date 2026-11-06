"""Analysis presets: acceptance criteria saved to (and loaded from) JSON.

A preset is one analysis mode's acceptance criteria under a name — the min/max
limits, the tolerances, and (optionally) the golden reference table. It is what
makes the acceptance model re-usable: characterise a known-good board once, save
the preset, and every later board is judged against it.

The file is deliberately hand-editable — the reference table sits beside the
scalar settings rather than nested inside them::

    {
      "schema": 1,
      "kind": "analysis-preset",
      "measurement": "measure_filter",
      "analysis": "standard",
      "name": "AFE v2 acceptance",
      "mapping": "mapping_interposer.csv",
      "settings": {"c_min_nf": 0.75, "c_max_nf": 1.25, "rel_tol": 0.1, ...},
      "reference": {
        "source": "test-20260728-142201.json",
        "captured": "2026-07-30T09:12:00",
        "values": {"0:1": {"c": 1.02, "r": 2010}}
      }
    }

Presets live in :func:`~trap_tester.core.appconfig.presets_dir` (user-configurable
in the Settings tab), are discovered recursively so they can be organised into
sub-folders, and are always scoped to one measurement *and* one analysis mode:
loading a filter preset over a voltage result is rejected rather than silently
ignored. A preset without an ``analysis`` key belongs to the default mode.

``mapping`` (optional) names the cross-interface mapping CSV the criteria were
made with — by *file name*, not path, because the layout folders sit in different
places on different machines. It matters most in loopback mode, where the
mapping places the board's pads on tester pins, so the criteria are only right
together with it. Choosing the preset selects that mapping again (see
:func:`find_mapping`); a preset without the key leaves the selection alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trap_tester.core.analysis import (
    ANALYSES,
    DEFAULT_MODE,
    analysis_mode,
    mode_of_settings,
)
from trap_tester.core.appconfig import presets_dir
from trap_tester.core.layout.store import list_mapping_files

if TYPE_CHECKING:
    from trap_tester.core.analysis.acceptance import Reference

SCHEMA_VERSION = 1
KIND = "analysis-preset"
SUFFIX = ".json"


@dataclass
class Preset:
    """One named set of acceptance criteria for one measurement's analysis mode."""

    name: str
    measurement: str
    settings: Any  # an AcceptanceSettings dataclass instance
    path: Path | None = field(default=None, compare=False)
    analysis: str = DEFAULT_MODE  # an AnalysisMode.key of the measurement
    mapping: str = ""  # file name of the mapping CSV it was made with ("" = none)

    @property
    def reference(self) -> Reference:
        return self.settings.reference


def _slug(name: str) -> str:
    """A filesystem-safe stem for a preset name (never empty)."""
    kept = "".join(ch if (ch.isalnum() or ch in " -_") else "-" for ch in name)
    return "-".join(kept.split()) or "preset"


def _unique_path(dest: Path) -> Path:
    """``dest`` if free, else ``dest`` with a ``-2`` / ``-3`` … suffix."""
    i = 2
    candidate = dest
    while candidate.exists():
        candidate = dest.with_stem(f"{dest.stem}-{i}")
        i += 1
    return candidate


def to_payload(preset: Preset) -> dict[str, Any]:
    """Serialise a preset, hoisting the reference out of the settings block."""
    settings = preset.settings.to_dict()
    reference = settings.pop("reference", {})
    return {
        "schema": SCHEMA_VERSION,
        "kind": KIND,
        "measurement": preset.measurement,
        "analysis": preset.analysis,
        "name": preset.name,
        **({"mapping": preset.mapping} if preset.mapping else {}),
        "settings": settings,
        "reference": reference,
    }


def from_payload(data: Any, path: Path | None = None) -> Preset:
    """Parse a preset payload, raising :class:`ValueError` on anything unusable."""
    if not isinstance(data, dict):
        raise ValueError("not a preset file (expected a JSON object)")
    schema = data.get("schema", SCHEMA_VERSION)
    if not isinstance(schema, int) or schema > SCHEMA_VERSION:
        raise ValueError(
            f"preset schema {schema} is newer than this app supports "
            f"(max {SCHEMA_VERSION})"
        )
    measurement = str(data.get("measurement", ""))
    if measurement not in ANALYSES:
        raise ValueError(
            f"unknown measurement {measurement!r}; "
            f"expected one of {sorted(ANALYSES)}"
        )
    analysis = str(data.get("analysis") or DEFAULT_MODE)
    mode = analysis_mode(measurement, analysis)
    if mode is None:
        raise ValueError(f"unknown analysis mode {analysis!r} for {measurement!r}")
    raw = dict(data.get("settings") or {})
    # The reference is stored beside the settings but is a settings field.
    raw["reference"] = data.get("reference") or {}
    settings = mode.settings.from_dict(raw)
    name = str(data.get("name") or "") or (path.stem if path else measurement)
    mapping = data.get("mapping") or ""
    if not isinstance(mapping, str):
        raise ValueError("'mapping' must be the file name of a mapping CSV")
    return Preset(
        name=name, measurement=measurement, settings=settings, path=path,
        analysis=analysis, mapping=Path(mapping).name,  # a name, never a path
    )


def load(path: str | Path) -> Preset:
    """Load one preset (raises on malformed JSON or a rejected payload)."""
    path = Path(path)
    return from_payload(json.loads(path.read_text()), path)


def save(
    settings: Any,
    measurement: str,
    name: str,
    directory: str | Path | None = None,
    mapping: str | Path | None = None,
) -> Path:
    """Write a preset and return its path (an existing name is never clobbered).

    The analysis mode is the one ``settings`` belongs to, so it cannot disagree
    with the settings that are saved. ``mapping`` is the selected mapping CSV
    (a path or a file name; only the file name is stored), or ``None``.
    """
    analysis = mode_of_settings(measurement, settings) or DEFAULT_MODE
    preset = Preset(
        name=name, measurement=measurement, settings=settings, analysis=analysis,
        mapping=Path(mapping).name if mapping else "",
    )
    dest_dir = Path(directory) if directory is not None else presets_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(dest_dir / f"{_slug(name)}{SUFFIX}")
    dest.write_text(json.dumps(to_payload(preset), indent=2))
    return dest


def list_presets(
    measurement: str | None = None, analysis: str | None = None
) -> list[tuple[str, Path]]:
    """``(display name, path)`` for every readable preset, sorted by name.

    Unreadable or foreign JSON in the folder is skipped rather than raised: the
    presets directory is a plain folder the user may keep other files in, and a
    single bad file must not empty the selector.
    """
    directory = presets_dir()
    if not directory.exists():
        return []
    out: list[tuple[str, Path]] = []
    for path in sorted(directory.rglob(f"*{SUFFIX}")):
        try:
            preset = load(path)
        except (OSError, ValueError):
            continue
        if measurement and preset.measurement != measurement:
            continue
        if analysis and preset.analysis != analysis:
            continue
        out.append((preset.name, path))
    return sorted(out, key=lambda item: item[0].lower())


def import_preset(src: str | Path, name: str | None = None) -> Path:
    """Validate ``src`` as a preset and copy it into the presets directory.

    Parsing first means a bad file is rejected before anything is written; the
    stored copy is re-serialised, so it is normalised (unknown keys dropped,
    legacy settings keys migrated) on the way in.
    """
    src = Path(src)
    preset = load(src)
    return save(
        preset.settings, preset.measurement, name or preset.name or src.stem,
        mapping=preset.mapping or None,
    )


def find_mapping(name: str) -> Path | None:
    """The mapping CSV called ``name`` in the layout folders, or ``None``.

    Searched in the same order as the mapping selector (default location first),
    so with two files of the same name the one listed first wins.
    """
    if not name:
        return None
    for path in list_mapping_files():
        if path.name == name:
            return path
    return None


def delete(path: str | Path) -> None:
    """Delete a stored preset. Refuses to touch anything outside the store."""
    path = Path(path).resolve()
    root = presets_dir().resolve()
    if root not in path.parents:
        raise ValueError(f"{path} is not in the presets directory")
    path.unlink(missing_ok=True)


__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "SUFFIX",
    "Preset",
    "delete",
    "find_mapping",
    "from_payload",
    "import_preset",
    "list_presets",
    "load",
    "save",
    "to_payload",
]
