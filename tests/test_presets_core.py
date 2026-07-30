"""Headless tests for analysis presets (``core.analysis.presets``).

Run with ``uv run pytest tests/test_presets_core.py``. The presets folder lives
under the app data dir, which follows ``TRAP_TESTER_LAYOUTS_DIR`` — so pointing
that at a tmp_path isolates the store (and the app config beside it).
"""

from __future__ import annotations

import json

import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis import presets
from trap_tester.core.analysis.acceptance import Reference
from trap_tester.core.appconfig import presets_dir, set_presets_dir


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    """Isolate the app data dir (and thus the presets folder + app config)."""
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "layouts"))
    return tmp_path


def _filter_settings() -> A.FilterAnalysisSettings:
    return A.FilterAnalysisSettings(
        c_min_nf=0.8, c_max_nf=1.2, r_min_ohm=1500, r_max_ohm=2500, rel_tol=0.05,
        reference=Reference(values={"0:1": {"c": 1.0, "r": 2000.0}}, source="g.json"),
    )


def test_default_presets_dir_is_under_the_app_data_dir(_store):
    assert presets_dir() == _store / "analysis_presets"


def test_save_and_load_round_trip():
    path = presets.save(_filter_settings(), "measure_filter", "AFE v2 acceptance")
    assert path.parent == presets_dir()
    assert path.name == "AFE-v2-acceptance.json"

    preset = presets.load(path)
    assert preset.name == "AFE v2 acceptance"
    assert preset.measurement == "measure_filter"
    assert preset.settings == _filter_settings()
    assert preset.reference.lookup(0, 1, "c") == 1.0


def test_reference_is_stored_beside_the_settings():
    path = presets.save(_filter_settings(), "measure_filter", "hand editable")
    payload = json.loads(path.read_text())
    assert payload["kind"] == "analysis-preset"
    assert "reference" not in payload["settings"]
    assert payload["reference"]["values"] == {"0:1": {"c": 1.0, "r": 2000.0}}
    assert payload["settings"]["c_min_nf"] == 0.8


def test_saving_twice_does_not_clobber():
    first = presets.save(_filter_settings(), "measure_filter", "same name")
    second = presets.save(_filter_settings(), "measure_filter", "same name")
    assert first != second
    assert second.stem == "same-name-2"


def test_list_presets_is_scoped_to_one_measurement():
    presets.save(_filter_settings(), "measure_filter", "filter one")
    presets.save(A.VoltageAnalysisSettings(), "measure_voltage", "voltage one")
    assert [n for n, _ in presets.list_presets("measure_filter")] == ["filter one"]
    assert [n for n, _ in presets.list_presets("measure_voltage")] == ["voltage one"]
    assert len(presets.list_presets()) == 2


def test_list_presets_skips_unrelated_json():
    presets.save(_filter_settings(), "measure_filter", "good")
    presets_dir().joinpath("junk.json").write_text("{not json")
    presets_dir().joinpath("other.json").write_text('{"hello": "world"}')
    assert [n for n, _ in presets.list_presets()] == ["good"]


def test_presets_are_found_in_sub_folders():
    nested = presets_dir() / "trap-A"
    nested.mkdir(parents=True)
    presets.save(_filter_settings(), "measure_filter", "nested", directory=nested)
    assert [n for n, _ in presets.list_presets()] == ["nested"]


def test_unknown_measurement_is_rejected():
    with pytest.raises(ValueError, match="unknown measurement"):
        presets.from_payload({"measurement": "measure_nothing", "settings": {}})


def test_newer_schema_is_rejected():
    with pytest.raises(ValueError, match="newer than this app"):
        presets.from_payload(
            {"schema": 99, "measurement": "measure_filter", "settings": {}}
        )


def test_legacy_settings_migrate_on_load(tmp_path):
    src = tmp_path / "legacy.json"
    src.write_text(json.dumps({
        "measurement": "measure_filter",
        "settings": {"c_nominal_nf": 2.0, "rel_tolerance": 0.25},
    }))
    preset = presets.load(src)
    assert (preset.settings.c_min_nf, preset.settings.c_max_nf) == (1.5, 2.5)
    assert preset.name == "legacy"  # falls back to the file stem


def test_import_copies_into_the_store(tmp_path):
    src = tmp_path / "elsewhere.json"
    src.write_text(json.dumps(
        presets.to_payload(
            presets.Preset("brought along", "measure_filter", _filter_settings())
        )
    ))
    dest = presets.import_preset(src)
    assert dest.parent == presets_dir()
    assert presets.load(dest).settings == _filter_settings()


def test_import_rejects_a_bad_file(tmp_path):
    src = tmp_path / "nope.json"
    src.write_text('{"measurement": "not a thing"}')
    with pytest.raises(ValueError):
        presets.import_preset(src)
    assert presets.list_presets() == []  # nothing written


def test_delete_refuses_outside_the_store(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    with pytest.raises(ValueError):
        presets.delete(outside)
    assert outside.exists()


def test_configured_presets_dir_is_used(tmp_path):
    shared = tmp_path / "shared"
    set_presets_dir(shared)
    try:
        path = presets.save(_filter_settings(), "measure_filter", "shared one")
        assert path.parent == shared
        assert [n for n, _ in presets.list_presets()] == ["shared one"]
    finally:
        set_presets_dir(None)
