"""Session-to-session persistence of the GUI state (Qt-free).

What the operator was looking at when the app closed — window geometry, the
selected panel, splitter positions, and each panel's selections and unsaved
inputs — is written to ``session.json`` in
:func:`~trap_tester.core.layout.store.app_data_dir` and handed back on the next
start.

This is deliberately separate from ``app_config.json``: the config holds
*settings* the operator chose on purpose, the session holds *state* that is merely
remembered, and is safe to throw away at any time (the Settings tab has a button
for it, and a corrupt or out-of-date file is ignored rather than refused).

The layout is one JSON object keyed by panel name; each panel owns the shape of
its own entry (see ``session_state`` / ``restore_session`` on the GUI panels), so
a panel can add a field without touching anything here. Every reader must
tolerate a missing or wrongly-typed key: the file outlives the code that wrote it.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from trap_tester.core.layout.store import app_data_dir

_SESSION_NAME = "session.json"
SCHEMA_VERSION = 1


def session_path() -> Path:
    """Where the saved session lives (beside the app config)."""
    return app_data_dir() / _SESSION_NAME


def load() -> dict[str, Any]:
    """The saved session, or ``{}`` when there is none (or it is unusable)."""
    path = session_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {}  # a session is disposable: never migrate, just start fresh
    panels = data.get("panels")
    return panels if isinstance(panels, dict) else {}


def save(panels: dict[str, Any]) -> None:
    """Write the session (raises ``OSError`` if the folder is not writable)."""
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA_VERSION, "panels": panels}
    # write-then-rename, so a crash mid-write cannot leave a half file behind
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)


def clear() -> None:
    """Forget the saved session (the next start uses the defaults)."""
    session_path().unlink(missing_ok=True)


# ---- helpers for panel state -------------------------------------------------
def section(state: Any, key: str) -> dict[str, Any]:
    """``state[key]`` if it is a dict, else ``{}`` — for reading nested entries."""
    if not isinstance(state, dict):
        return {}
    value = state.get(key)
    return value if isinstance(value, dict) else {}


def dataclass_from_dict(cls: type, data: Any) -> Any:
    """Rebuild a settings dataclass from a saved dict, or ``None`` if unusable.

    Unknown keys (a field since removed) are dropped and missing ones take their
    defaults, so a session written by an older version still restores what it can.
    Uses the class's own ``from_dict`` when it has one (it may decode nested
    values, e.g. an analysis reference table).
    """
    if not isinstance(data, dict) or not is_dataclass(cls):
        return None
    try:
        from_dict = getattr(cls, "from_dict", None)
        if callable(from_dict):
            return from_dict(data)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
    except (TypeError, ValueError, KeyError):
        return None


__all__ = [
    "SCHEMA_VERSION",
    "clear",
    "dataclass_from_dict",
    "load",
    "save",
    "section",
    "session_path",
]
