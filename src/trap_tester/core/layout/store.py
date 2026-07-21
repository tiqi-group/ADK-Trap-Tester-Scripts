"""User layout store: import and load custom interface layouts.

Custom layouts are files a user brings themselves — a different connector, an FPC
ribbon, a trap-electrode sketch — that must *not* be tracked in the repo because
they can carry sensitive (customer/device) geometry. They therefore live outside
the source tree, in a per-user data directory:

* Linux/other: ``$XDG_DATA_HOME/trap-tester/layouts`` (else ``~/.local/share/…``)
* macOS:       ``~/Library/Application Support/trap-tester/layouts``
* Windows:     ``%APPDATA%\\trap-tester\\layouts``

Set ``TRAP_TESTER_LAYOUTS_DIR`` to override the location (e.g. a shared network
folder, or a temp dir in tests). Every file is a plain :class:`InterfaceLayout`
JSON — the same format as the built-in ``layouts/dsub50.json`` — so a layout
exported from here (or hand-authored) can be dropped straight into the folder,
or imported through the GUI, which validates and normalises it on the way in.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from trap_tester.core.layout.interface import InterfaceLayout

_APP_DIR = "trap-tester"
_ENV_VAR = "TRAP_TESTER_LAYOUTS_DIR"


def _base_data_dir() -> Path:
    """The OS-conventional per-user data root (no app subfolder yet)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return Path(base) if base else Path.home() / "AppData" / "Roaming"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def user_layouts_dir() -> Path:
    """Where custom layouts live. Honours ``TRAP_TESTER_LAYOUTS_DIR`` first."""
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return _base_data_dir() / _APP_DIR / "layouts"


def ensure_user_layouts_dir() -> Path:
    """Return the layouts dir, creating it (and parents) if missing."""
    path = user_layouts_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_user_layouts() -> list[Path]:
    """Every ``*.json`` in the layouts dir, sorted by name (empty if none)."""
    path = user_layouts_dir()
    if not path.exists():
        return []
    return sorted(path.glob("*.json"))


def load_layout(path: str | Path) -> InterfaceLayout:
    """Load one custom layout (raises on malformed / unsupported JSON)."""
    return InterfaceLayout.load_json(path)


def _unique_path(dest: Path) -> Path:
    """``dest`` if free, else ``dest`` with a ``-2`` / ``-3`` … suffix."""
    if not dest.exists():
        return dest
    i = 2
    while True:
        candidate = dest.with_stem(f"{dest.stem}-{i}")
        if not candidate.exists():
            return candidate
        i += 1


def import_layout(src: str | Path, name: str | None = None) -> Path:
    """Validate ``src`` as a layout and copy it into the user layouts dir.

    Loading it first means a bad file is rejected *before* anything is written;
    re-serialising via :meth:`InterfaceLayout.save_json` normalises the stored
    copy (drops unknown keys, canonical formatting). An existing name is never
    clobbered — a numeric suffix is appended instead. Returns the stored path.

    Raises :class:`ValueError` (or JSON/OS errors) if ``src`` is not a valid
    layout file.
    """
    src = Path(src)
    layout = load_layout(src)  # validates JSON + schema before we touch the store
    dest_dir = ensure_user_layouts_dir()
    stem = name or src.stem
    dest = _unique_path(dest_dir / f"{stem}.json")
    layout.save_json(dest)
    return dest


def delete_layout(path: str | Path) -> None:
    """Delete a stored layout. Refuses to touch anything outside the store."""
    path = Path(path).resolve()
    store = user_layouts_dir().resolve()
    if path.parent != store:
        raise ValueError(f"{path} is not in the user layouts dir")
    path.unlink(missing_ok=True)


__all__ = [
    "user_layouts_dir",
    "ensure_user_layouts_dir",
    "list_user_layouts",
    "load_layout",
    "import_layout",
    "delete_layout",
]
