"""Light / dark theming for the GUI.

One place defines both palettes. Qt widget chrome is themed by substituting the
palette into ``style.qss`` (a ``string.Template`` with ``$token`` placeholders);
the matplotlib canvases are themed by a few ``rcParams`` plus small helpers
(:func:`plot_title_color`, :func:`annot_style`, :func:`faint_for`) they read at
draw time. Semantic/data colours (status green/red, decoration, traces, the
trigger line) are the *same* in both themes — only chrome and plot backgrounds
change.

``set_active(name)`` switches the active palette; ``apply(app)`` (re)applies it
to a ``QApplication`` (stylesheet + matplotlib rcParams). Widgets that cache
colours at draw time expose ``apply_theme()`` so a live switch can re-render.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

import matplotlib as mpl

THEMES = ("light", "dark")
DEFAULT_THEME = "light"

# Chrome + plot colours per theme. Keys used by the QSS template are lower-case
# tokens; the ``mpl_*`` / ``faint_*`` / ``annot_*`` keys are read by the canvases.
_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "window_bg": "#f2f2f2", "text": "#202020",
        "menu_bg": "#3f6fb0", "menu_text": "#ffffff",
        "menu_sel": "#2c5286", "menu_hover": "#4a7cc0",
        "accent": "#6cb46c", "accent_btn_text": "#10250f",
        "accent_border": "#4f954f", "accent_hover": "#7cc47c",
        "accent_disabled_bg": "#b9d4b9", "accent_disabled_text": "#6a806a",
        "accent_box_bg": "rgba(108, 180, 108, 0.08)", "accent_title": "#3d7a3d",
        "input_bg": "#ffffff", "section": "#2c5286",
        "unit_text": "#777777", "unit_bg": "#ececec",
        "unit_border": "#cccccc", "unit_text_disabled": "#888888",
        "viewer": "#e0492f", "viewer_title": "#b83a20",
        "viewer_box_bg": "rgba(224, 73, 47, 0.08)",
        "terminal_bg": "#1e1e1e", "terminal_text": "#e6e6e6",
        "warn_text": "#8a6d00", "warn_bg": "#fff4d6", "warn_border": "#e0c060",
        # matplotlib
        "mpl_fig_bg": "#ffffff", "mpl_axes_bg": "#ffffff",
        "mpl_fg": "#202020", "mpl_grid": "#c8c8c8",
        "annot_bg": "#ffffe0", "annot_edge": "#888888", "annot_text": "#202020",
        "faint_fill": "#efefef", "faint_stroke": "#b0b0b0",
        "gnd_fill": "#cfe0f3", "gnd_stroke": "#9fb8d8",
    },
    "dark": {
        "window_bg": "#2b2b2b", "text": "#e0e0e0",
        "menu_bg": "#3f6fb0", "menu_text": "#ffffff",
        "menu_sel": "#2c5286", "menu_hover": "#4a7cc0",
        "accent": "#6cb46c", "accent_btn_text": "#0c1f0b",
        "accent_border": "#4f954f", "accent_hover": "#7cc47c",
        "accent_disabled_bg": "#3f4f3f", "accent_disabled_text": "#7a8a7a",
        "accent_box_bg": "rgba(108, 180, 108, 0.14)", "accent_title": "#8fce8f",
        "input_bg": "#3c3f41", "section": "#86aede",
        "unit_text": "#b0b0b0", "unit_bg": "#3c3f41",
        "unit_border": "#555555", "unit_text_disabled": "#888888",
        "viewer": "#e0492f", "viewer_title": "#ff8a6c",
        "viewer_box_bg": "rgba(224, 73, 47, 0.14)",
        "terminal_bg": "#1e1e1e", "terminal_text": "#e6e6e6",
        "warn_text": "#ffd24d", "warn_bg": "#4a3f1a", "warn_border": "#7a6620",
        # matplotlib
        "mpl_fig_bg": "#2b2b2b", "mpl_axes_bg": "#313335",
        "mpl_fg": "#d0d0d0", "mpl_grid": "#4a4a4a",
        "annot_bg": "#3c3f41", "annot_edge": "#666666", "annot_text": "#e6e6e6",
        "faint_fill": "#3a3d3f", "faint_stroke": "#606366",
        "gnd_fill": "#33414f", "gnd_stroke": "#4a6079",
    },
}

# Slot statuses drawn as faint "background" pads whose fill is chrome, not data,
# and so is themed: neutral for no-data/no-comment, blue-ish for GND / unmapped.
_FAINT_NEUTRAL = {"unmeasured", "clear"}
_FAINT_GND = {"unmapped"}

_active = DEFAULT_THEME


def _normalise(name: str | None) -> str:
    return name if name in THEMES else DEFAULT_THEME


def set_active(name: str | None) -> str:
    """Set the active theme (falling back to the default for unknown names)."""
    global _active
    _active = _normalise(name)
    return _active


def active() -> str:
    return _active


def palette(name: str | None = None) -> dict[str, str]:
    return _PALETTES[_normalise(name) if name else _active]


def _template_path() -> Path:
    return Path(__file__).with_name("style.qss")


def render_qss(name: str | None = None) -> str:
    """The stylesheet with the given (or active) palette substituted in."""
    template = Template(_template_path().read_text())
    return template.safe_substitute(palette(name))


def apply_matplotlib(name: str | None = None) -> None:
    """Push the theme's plot colours into matplotlib rcParams.

    Affects artists created afterwards; existing canvases re-render via
    ``apply_theme`` on a live switch.
    """
    p = palette(name)
    mpl.rcParams.update({
        "figure.facecolor": p["mpl_fig_bg"],
        "axes.facecolor": p["mpl_axes_bg"],
        "axes.edgecolor": p["mpl_fg"],
        "axes.labelcolor": p["mpl_fg"],
        "text.color": p["mpl_fg"],
        "xtick.color": p["mpl_fg"],
        "ytick.color": p["mpl_fg"],
        "grid.color": p["mpl_grid"],
    })


def apply(app, name: str | None = None) -> None:
    """Apply a theme to a ``QApplication``: set active, stylesheet, rcParams."""
    set_active(name)
    apply_matplotlib()
    app.setStyleSheet(render_qss())


# ---- helpers the canvases read at draw time --------------------------------
def plot_title_color() -> str:
    return palette()["viewer_title"]


def fig_bg() -> str:
    return palette()["mpl_fig_bg"]


def axes_bg() -> str:
    return palette()["mpl_axes_bg"]


def style_axes(fig, *axes) -> None:
    """Set figure + axes backgrounds from the active theme.

    ``ax.clear()`` does not reliably re-read the rcParams facecolour, so callers
    set it explicitly here after clearing (and on a live theme switch).
    """
    fig.set_facecolor(fig_bg())
    for ax in axes:
        ax.set_facecolor(axes_bg())


def annot_style() -> dict[str, str]:
    """``bbox`` / text colours for the hover annotation, themed."""
    p = palette()
    return {"fc": p["annot_bg"], "ec": p["annot_edge"], "text": p["annot_text"]}


def faint_for(status: str) -> tuple[str, str] | None:
    """Themed ``(fill, stroke)`` for a faint background pad, or ``None``.

    Faint pads (no data / no comment / GND / unmapped) carry a chrome colour, not
    a measured one, so they follow the theme instead of staying light on dark.
    """
    p = palette()
    if status in _FAINT_NEUTRAL:
        return p["faint_fill"], p["faint_stroke"]
    if status in _FAINT_GND:
        return p["gnd_fill"], p["gnd_stroke"]
    return None


__all__ = [
    "DEFAULT_THEME",
    "THEMES",
    "active",
    "annot_style",
    "apply",
    "apply_matplotlib",
    "faint_for",
    "fig_bg",
    "palette",
    "plot_title_color",
    "axes_bg",
    "render_qss",
    "set_active",
    "style_axes",
]
