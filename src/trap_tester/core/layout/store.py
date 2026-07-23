"""User layout store: import and load custom interface layouts.

Custom layouts are files a user brings themselves — a different connector, an FPC
ribbon, a trap-electrode sketch — that must *not* be tracked in the repo because
they can carry sensitive (customer/device) geometry. They therefore live outside
the source tree, in a per-user data directory:

* Linux/other: ``$XDG_DATA_HOME/trap-tester/layouts`` (else ``~/.local/share/…``)
* macOS:       ``~/Library/Application Support/trap-tester/layouts``
* Windows:     ``%APPDATA%\\trap-tester\\layouts``

Set ``TRAP_TESTER_LAYOUTS_DIR`` to override this *writable* store (e.g. a shared
network folder, or a temp dir in tests). Every file is a plain
:class:`InterfaceLayout` JSON — the same format as the built-in
``layouts/dsub50.json`` — so a layout exported from here (or hand-authored) can be
dropped straight into the folder, or imported through the GUI, which validates and
normalises it on the way in.

Beyond that single writable store, the GUI can search **extra** folders for
layouts to *read* — handy when the custom layouts live in a shared or
version-controlled folder (e.g. a private git repo). Extra folders come from two
places, both searched read-only in addition to the writable store:

* a persisted list, managed through the GUI (see :func:`add_layout_dir` /
  :func:`remove_layout_dir`), stored next to the store in ``layout_sources.json``;
* the ``TRAP_TESTER_LAYOUT_PATH`` environment variable (``os.pathsep``-separated),
  for CI / shared setups.

:func:`list_user_layouts` scans them all; imports and deletes only ever touch the
writable store, so a version-controlled folder is never modified by the app.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from trap_tester.core.layout.interface import InterfaceLayout

_APP_DIR = "trap-tester"
_ENV_VAR = "TRAP_TESTER_LAYOUTS_DIR"
_PATH_ENV_VAR = "TRAP_TESTER_LAYOUT_PATH"  # os.pathsep-separated extra read dirs
_CONFIG_NAME = "layout_sources.json"


def _norm(path: Path) -> str:
    """A comparable key for a path (case-/separator-normalised, ~ expanded)."""
    return os.path.normcase(os.path.normpath(str(Path(path).expanduser())))


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


def _config_path() -> Path:
    """Where the persisted extra-folder list lives (next to the writable store)."""
    return user_layouts_dir().parent / _CONFIG_NAME


def configured_layout_dirs() -> list[Path]:
    """Extra folders the user added through the GUI (persisted, may be removed)."""
    path = _config_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    sources = data.get("sources", []) if isinstance(data, dict) else []
    return [Path(s).expanduser() for s in sources if isinstance(s, str)]


def env_layout_dirs() -> list[Path]:
    """Extra folders from ``TRAP_TESTER_LAYOUT_PATH`` (read-only, not editable)."""
    raw = os.environ.get(_PATH_ENV_VAR, "")
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]


def extra_layout_dirs() -> list[Path]:
    """All extra read-only search folders: persisted first, then env, deduped."""
    out: list[Path] = []
    seen: set[str] = set()
    for d in [*configured_layout_dirs(), *env_layout_dirs()]:
        key = _norm(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def layout_search_dirs() -> list[Path]:
    """Every folder searched for custom layouts: writable store first, then extras."""
    out: list[Path] = []
    seen: set[str] = set()
    for d in [user_layouts_dir(), *extra_layout_dirs()]:
        key = _norm(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _write_config_dirs(dirs: list[Path]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": [str(d) for d in dirs]}, indent=2))


def add_layout_dir(path: str | Path) -> Path:
    """Persist ``path`` as an extra search folder (idempotent). Returns its Path.

    Raises :class:`ValueError` if it is not an existing directory. The writable
    store and env-provided folders are never added to the persisted list (they are
    already searched); adding one is a no-op.
    """
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError(f"{p} is not a directory")
    already = {_norm(d) for d in [user_layouts_dir(), *env_layout_dirs()]}
    current = configured_layout_dirs()
    keys = {_norm(d) for d in current} | already
    if _norm(p) not in keys:
        current.append(p)
        _write_config_dirs(current)
    return p


def remove_layout_dir(path: str | Path) -> None:
    """Drop ``path`` from the persisted extra-folder list (no-op if absent)."""
    key = _norm(path)
    remaining = [d for d in configured_layout_dirs() if _norm(d) != key]
    _write_config_dirs(remaining)


def list_user_layouts() -> list[Path]:
    """Every ``*.json`` across all search dirs, sorted per dir (empty if none)."""
    out: list[Path] = []
    for directory in layout_search_dirs():
        if directory.exists():
            out.extend(sorted(directory.glob("*.json")))
    return out


def list_mapping_files() -> list[Path]:
    """Every ``*.csv`` across all search dirs, sorted per dir (empty if none).

    Mapping CSVs live alongside the custom layouts they wire together, so they are
    discovered from the same search folders (see :mod:`trap_tester.core.layout
    .mapping`).
    """
    out: list[Path] = []
    for directory in layout_search_dirs():
        if directory.exists():
            out.extend(sorted(directory.glob("*.csv")))
    return out


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


def import_mapping(src: str | Path, name: str | None = None) -> Path:
    """Validate ``src`` as a mapping CSV and copy it into the user layouts dir.

    Mapping CSVs are discovered from the same search folders as layouts, so an
    imported mapping lands next to them and shows up in the mapping selector.
    ``src`` is parsed first (so a file missing the required connector / DSUB-pin
    columns is rejected before anything is written) then copied verbatim. Returns
    the stored path; an existing name gets a numeric suffix rather than clobbering.
    """
    from trap_tester.core.layout.mapping import load_csv  # lazy: avoid import cycle

    src = Path(src)
    load_csv(src)  # validates the required columns before we touch the store
    dest_dir = ensure_user_layouts_dir()
    stem = name or src.stem
    dest = _unique_path(dest_dir / f"{stem}.csv")
    dest.write_bytes(src.read_bytes())
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
    "configured_layout_dirs",
    "env_layout_dirs",
    "extra_layout_dirs",
    "layout_search_dirs",
    "add_layout_dir",
    "remove_layout_dir",
    "list_user_layouts",
    "load_layout",
    "import_layout",
    "delete_layout",
]
