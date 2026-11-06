"""Headless tests for the selectable layout store and the saved GUI session.

``TRAP_TESTER_LAYOUTS_DIR`` overrides the store choice, so the store tests point
the *OS default* at a temp dir instead (patching ``_base_data_dir``, which is
platform-agnostic) and leave the variable unset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from trap_tester.core import appconfig, session
from trap_tester.core.layout import store
from trap_tester.core.layout.dsub50 import generate_dsub50
from trap_tester.core.settings import FilterSettings


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """An isolated OS data root, with no env override in play."""
    monkeypatch.delenv("TRAP_TESTER_LAYOUTS_DIR", raising=False)
    monkeypatch.delenv("TRAP_TESTER_LAYOUT_PATH", raising=False)
    root = tmp_path / "data"
    monkeypatch.setattr(store, "_base_data_dir", lambda: root)
    return root


# ---- selectable default location for layouts / mappings ---------------------
def test_store_defaults_to_os_location(data_root):
    assert store.user_layouts_dir() == data_root / "trap-tester" / "layouts"
    assert store.configured_user_layouts_dir() is None


def test_store_can_be_moved_and_reset(data_root, tmp_path):
    chosen = tmp_path / "team-layouts"
    assert store.set_user_layouts_dir(chosen) == chosen
    assert store.user_layouts_dir() == chosen
    assert store.layout_search_dirs()[0] == chosen  # searched first
    assert store.set_user_layouts_dir(None) == store.default_user_layouts_dir()
    store.set_user_layouts_dir(str(chosen))
    store.set_user_layouts_dir("  ")  # blank also clears
    assert store.configured_user_layouts_dir() is None


def test_config_does_not_follow_a_moved_store(data_root, tmp_path):
    """The setting naming the store cannot live inside it."""
    before = store.app_data_dir()
    store.set_user_layouts_dir(tmp_path / "elsewhere")
    assert store.app_data_dir() == before
    assert appconfig.config_path().parent == before
    assert session.session_path().parent == before


def test_imports_go_to_the_chosen_store(data_root, tmp_path):
    chosen = tmp_path / "chosen"
    store.set_user_layouts_dir(chosen)
    src = tmp_path / "mine.json"
    generate_dsub50().save_json(src)
    dest = store.import_layout(src)
    assert dest.parent == chosen  # created on first import
    assert dest in store.list_user_layouts()
    store.delete_layout(dest)  # deletes are allowed in the chosen store
    assert not dest.exists()


def test_store_choice_and_extra_folders_share_one_file(data_root, tmp_path):
    extra = tmp_path / "extra"
    extra.mkdir()
    store.add_layout_dir(extra)
    store.set_user_layouts_dir(tmp_path / "chosen")
    assert store.configured_layout_dirs() == [extra]  # not clobbered
    store.remove_layout_dir(extra)
    assert store.user_layouts_dir() == tmp_path / "chosen"  # nor this


def test_env_override_beats_the_chosen_store(data_root, tmp_path, monkeypatch):
    store.set_user_layouts_dir(tmp_path / "chosen")
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "forced"))
    assert store.user_layouts_dir() == tmp_path / "forced"
    assert store.store_dir_from_env() == tmp_path / "forced"


def test_store_choice_survives_a_corrupt_config(data_root):
    path = store.app_data_dir() / "layout_sources.json"
    path.parent.mkdir(parents=True)
    path.write_text("{oops")
    assert store.user_layouts_dir() == store.default_user_layouts_dir()
    assert store.configured_layout_dirs() == []


# ---- session persistence ----------------------------------------------------
def test_session_round_trip(data_root):
    assert session.load() == {}  # nothing saved yet
    panels = {"_window": {"panel": "Analysis"}, "Measurement": {"measurement": "x"}}
    session.save(panels)
    assert session.load() == panels
    session.clear()
    assert session.load() == {}
    session.clear()  # clearing twice is fine


@pytest.mark.parametrize(
    "content",
    ["{broken", "[]", json.dumps({"schema": 999, "panels": {"a": {}}}),
     json.dumps({"schema": session.SCHEMA_VERSION, "panels": []})],
)
def test_unusable_session_is_ignored(data_root, content):
    session.session_path().parent.mkdir(parents=True, exist_ok=True)
    session.session_path().write_text(content)
    assert session.load() == {}


def test_section_tolerates_wrong_types():
    assert session.section({"a": {"b": 1}}, "a") == {"b": 1}
    assert session.section({"a": [1]}, "a") == {}
    assert session.section(None, "a") == {}


@dataclass
class _Plain:
    x: float = 1.0
    y: str = "a"


def test_dataclass_from_dict_drops_unknown_and_keeps_defaults():
    restored = session.dataclass_from_dict(_Plain, {"x": 2.0, "gone": 1})
    assert restored == _Plain(2.0, "a")
    assert session.dataclass_from_dict(_Plain, "nope") is None


def test_dataclass_from_dict_uses_from_dict():
    saved = FilterSettings().to_dict()
    saved["removed_field"] = 3
    restored = session.dataclass_from_dict(FilterSettings, saved)
    assert restored == FilterSettings()


def test_restore_session_preference(data_root):
    assert appconfig.restore_session() is True  # on by default
    assert appconfig.set_restore_session(False) is False
    assert appconfig.restore_session() is False
