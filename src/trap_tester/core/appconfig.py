"""Persisted, user-configurable application paths (Qt-free).

The measurement/analysis output location is a user preference rather than a fixed
constant, so it lives in a small JSON config next to the layout store's own config
(``app_config.json`` in :func:`~trap_tester.core.layout.store.app_data_dir`). The
rest of the code reads the *functions* here (never a cached constant) so a change
made in the Settings tab takes effect immediately for the next save/browse.

Layout resolution:

* ``results_dir()`` — the output root (default ``results/``, relative to the
  working directory unless set to an absolute path);
* ``measurements_dir()`` / ``analysis_dir()`` — the ``measurements`` /
  ``analysis`` sub-folders under it, where result JSONs and report texts go;
* ``presets_dir()`` — analysis presets (acceptance criteria + golden references).
  Configuration rather than output, so it defaults into the app data dir.
"""

from __future__ import annotations

import json
from pathlib import Path

from trap_tester.core.layout.store import app_data_dir

_CONFIG_NAME = "app_config.json"
_RESULTS_KEY = "results_dir"
_DEFAULT_RESULTS = "results"
_PRESETS_KEY = "presets_dir"
_DEFAULT_PRESETS = "analysis_presets"  # a sub-folder of the app data dir
_THEME_KEY = "theme"
_DEFAULT_THEME = "light"
_THEMES = ("light", "dark")
_UI_SCALE_KEY = "ui_scale"
_DEFAULT_UI_SCALE = 1.0
# Bounds, not a fixed list: the Settings tab offers steps but a hand-edited config
# may ask for anything, and a factor of 0 or 12 would make the app unusable.
UI_SCALE_MIN, UI_SCALE_MAX = 0.5, 4.0


def config_path() -> Path:
    """Where the app settings JSON lives (beside the layout-folder config)."""
    return app_data_dir() / _CONFIG_NAME


def _load() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def results_dir() -> Path:
    """The output root for measurements and analysis (default ``results/``)."""
    return Path(_load().get(_RESULTS_KEY, _DEFAULT_RESULTS)).expanduser()


def set_results_dir(path: str | Path | None) -> Path:
    """Persist the output root (``None``/empty restores the default). Returns it."""
    data = _load()
    text = str(path).strip() if path is not None else ""
    if text:
        data[_RESULTS_KEY] = text
    else:
        data.pop(_RESULTS_KEY, None)
    _save(data)
    return results_dir()


def measurements_dir() -> Path:
    """Where measurement result JSONs are written / browsed."""
    return results_dir() / "measurements"


def analysis_dir() -> Path:
    """Where analysis report texts are written."""
    return results_dir() / "analysis"


def default_presets_dir() -> Path:
    """Where analysis presets live unless the user points elsewhere."""
    return app_data_dir() / _DEFAULT_PRESETS


def presets_dir() -> Path:
    """Where analysis presets (acceptance criteria + golden references) live.

    Unlike the results tree this is a *configuration* store, so it defaults into
    the per-user app data dir beside the layout store — but it is configurable,
    because a team sharing acceptance criteria will want it on a shared or
    version-controlled folder.
    """
    configured = _load().get(_PRESETS_KEY)
    return Path(configured).expanduser() if configured else default_presets_dir()


def set_presets_dir(path: str | Path | None) -> Path:
    """Persist the presets folder (``None``/empty restores the default)."""
    data = _load()
    text = str(path).strip() if path is not None else ""
    if text:
        data[_PRESETS_KEY] = text
    else:
        data.pop(_PRESETS_KEY, None)
    _save(data)
    return presets_dir()


def theme() -> str:
    """The configured UI theme (``"light"`` or ``"dark"``; default light)."""
    value = _load().get(_THEME_KEY, _DEFAULT_THEME)
    return value if value in _THEMES else _DEFAULT_THEME


def set_theme(name: str) -> str:
    """Persist the UI theme (unknown names fall back to the default). Returns it."""
    data = _load()
    data[_THEME_KEY] = name if name in _THEMES else _DEFAULT_THEME
    _save(data)
    return data[_THEME_KEY]


def ui_scale() -> float:
    """The configured UI scale factor (1.0 = the platform's own scaling).

    Read *before* the ``QApplication`` exists — Qt fixes its scale factor at
    construction — so this must stay Qt-free. See
    :func:`trap_tester.gui.__main__.main`.
    """
    try:
        value = float(_load().get(_UI_SCALE_KEY, _DEFAULT_UI_SCALE))
    except (TypeError, ValueError):
        return _DEFAULT_UI_SCALE
    if not UI_SCALE_MIN <= value <= UI_SCALE_MAX:
        return _DEFAULT_UI_SCALE
    return value


def set_ui_scale(factor: float | None) -> float:
    """Persist the UI scale (``None`` restores the default). Returns the value stored.

    Out-of-range values are clamped rather than rejected, so a slider or a typed
    number can never leave the app unreadable.
    """
    data = _load()
    if factor is None:
        data.pop(_UI_SCALE_KEY, None)
    else:
        data[_UI_SCALE_KEY] = min(max(float(factor), UI_SCALE_MIN), UI_SCALE_MAX)
    _save(data)
    return ui_scale()


__all__ = [
    "UI_SCALE_MAX",
    "UI_SCALE_MIN",
    "analysis_dir",
    "config_path",
    "default_presets_dir",
    "measurements_dir",
    "presets_dir",
    "results_dir",
    "set_presets_dir",
    "set_results_dir",
    "set_theme",
    "set_ui_scale",
    "theme",
    "ui_scale",
]
