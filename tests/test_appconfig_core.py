"""Headless tests for the persisted app config (``core.appconfig``).

The config file lives beside the layout store, so pointing the store at a temp
dir (``TRAP_TESTER_LAYOUTS_DIR``) isolates the config too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trap_tester.core import appconfig


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "store"))
    return tmp_path


def test_defaults_when_unset(isolated_config):
    assert appconfig.results_dir() == Path("results")
    assert appconfig.measurements_dir() == Path("results") / "measurements"
    assert appconfig.analysis_dir() == Path("results") / "analysis"
    assert not appconfig.config_path().exists()  # nothing written yet


def test_set_persists_and_derives(isolated_config):
    appconfig.set_results_dir("/data/traptest")
    assert appconfig.results_dir() == Path("/data/traptest")
    assert appconfig.measurements_dir() == Path("/data/traptest/measurements")
    assert appconfig.analysis_dir() == Path("/data/traptest/analysis")
    # written to a file beside the layout store
    assert appconfig.config_path().exists()
    assert appconfig.config_path().parent == (isolated_config)


def test_reset_restores_default(isolated_config):
    appconfig.set_results_dir("/data/x")
    assert appconfig.results_dir() == Path("/data/x")
    appconfig.set_results_dir(None)
    assert appconfig.results_dir() == Path("results")
    appconfig.set_results_dir("   ")  # blank also clears
    assert appconfig.results_dir() == Path("results")


def test_user_expansion(isolated_config, monkeypatch):
    # Path.expanduser() reads HOME on POSIX but USERPROFILE on Windows, so both
    # have to be redirected for this to be a platform-agnostic assertion.
    home = isolated_config / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    appconfig.set_results_dir("~/traptest")
    assert appconfig.results_dir() == home / "traptest"


def test_survives_corrupt_config(isolated_config):
    appconfig.config_path().parent.mkdir(parents=True, exist_ok=True)
    appconfig.config_path().write_text("{not valid json")
    assert appconfig.results_dir() == Path("results")  # falls back, no raise


def test_theme_default_and_persist(isolated_config):
    assert appconfig.theme() == "light"  # default
    assert appconfig.set_theme("dark") == "dark"
    assert appconfig.theme() == "dark"
    assert appconfig.set_theme("nonsense") == "light"  # unknown -> default


def test_ui_scale_default_and_persist(isolated_config):
    assert appconfig.ui_scale() == 1.0  # default: follow the desktop's own scaling
    assert appconfig.set_ui_scale(1.5) == 1.5
    assert appconfig.ui_scale() == 1.5
    assert appconfig.set_ui_scale(None) == 1.0  # None restores the default


def test_ui_scale_is_clamped_not_rejected(isolated_config):
    """A bad factor must never leave the app unreadable, so it is clamped."""
    assert appconfig.set_ui_scale(99.0) == appconfig.UI_SCALE_MAX
    assert appconfig.set_ui_scale(0.0) == appconfig.UI_SCALE_MIN


def test_ui_scale_ignores_a_corrupt_value(isolated_config):
    """A hand-edited config with nonsense in it falls back rather than crashing."""
    import json

    appconfig.set_ui_scale(1.5)
    data = json.loads(appconfig.config_path().read_text())
    data["ui_scale"] = "huge"
    appconfig.config_path().write_text(json.dumps(data))
    assert appconfig.ui_scale() == 1.0


def test_theme_and_results_coexist(isolated_config):
    appconfig.set_results_dir("/data/x")
    appconfig.set_theme("dark")
    assert appconfig.results_dir() == Path("/data/x")
    assert appconfig.theme() == "dark"
