"""Headless tests for the theme palette + QSS templating (``gui.theme``).

No Qt widgets — just the palette data, stylesheet substitution and the faint-pad
remap. ``gui.theme`` imports matplotlib (already a dep) but no PySide widgets.
"""

from __future__ import annotations

import pytest

from trap_tester.gui import theme


@pytest.fixture(autouse=True)
def _restore_theme():
    before = theme.active()
    yield
    theme.set_active(before)


def test_both_themes_render_fully_substituted():
    for name in theme.THEMES:
        qss = theme.render_qss(name)
        assert "$" not in qss, f"unsubstituted token left in {name} qss"
        assert "QPushButton" in qss  # sanity: it's the real stylesheet


def test_themes_differ():
    assert theme.render_qss("light") != theme.render_qss("dark")
    assert theme.palette("light")["window_bg"] != theme.palette("dark")["window_bg"]


def test_set_active_falls_back_for_unknown():
    assert theme.set_active("dark") == "dark"
    assert theme.active() == "dark"
    assert theme.set_active("bogus") == theme.DEFAULT_THEME


def test_faint_for_follows_active_theme():
    theme.set_active("light")
    light_fill, _ = theme.faint_for("unmeasured")
    theme.set_active("dark")
    dark_fill, _ = theme.faint_for("unmeasured")
    assert light_fill != dark_fill
    # GND / unmapped pads get the blue-ish faint colour, measured statuses none
    assert theme.faint_for("unmapped") is not None
    assert theme.faint_for("ok") is None
