"""Headless tests for the loopback analysis mode (``core.analysis.loopback*``).

Run with ``uv run pytest tests/test_loopback_core.py``. Pairs are named by pad on
an interface and placed on tester pins through a mapping CSV, so every test
builds a small mapping in ``tmp_path``.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis import presets
from trap_tester.core.analysis.loopback import (
    KIND,
    LoopbackPairs,
    load_pairs,
    resolve_pairs,
)
from trap_tester.core.layout.mapping import load_csv

# pad -> (connector, pin) on the "interposer" column
_WIRING = {
    "A1": (0, 1), "B1": (0, 2),  # a working loop
    "A2": (0, 3), "B2": (0, 4),  # an open loop
    "C1": (0, 5), "C2": (0, 6),  # a pair whose pins disagree
    "D1": (0, 7),  # unpaired
    "E1": (0, 9), "E2": (1, 9),  # partner on an unmeasured connector
    "F1": (0, 11), "F2": (1, 11),  # an extra short
}
_PAIRS = [["A1", "B1"], ["A2", "B2"], ["C1", "C2"], ["E1", "E2"], ["F1", "F2"]]


def _pairs(pairs=_PAIRS, interface="interposer") -> LoopbackPairs:
    return LoopbackPairs.from_dict({"interface": interface, "pairs": pairs})


@pytest.fixture
def mapping(tmp_path):
    lines = ["connector,pin,interposer"]
    lines += [f"{c},{p},{pad}" for pad, (c, p) in _WIRING.items()]
    path = tmp_path / "loop_cabling.csv"
    path.write_text("\n".join(lines) + "\n")
    return load_csv(path)


def _result(rows: list[tuple[int, int, float]], shorted=(), r_ohm=2000.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "DSUB connector": c, "DSUB pin": p, "Shorted": (c, p) in shorted,
                "C_filter_nF": cap, "R_filter_Ohm": r_ohm,
            }
            for c, p, cap in rows
        ]
    )


def _by_pin(result) -> dict[tuple[int, int], A.Finding]:
    return {(f.connector, f.dsub_pin): f for f in result.findings}


# ---- the pairs file ----------------------------------------------------------
def test_pairs_round_trip_and_normalised_interface():
    pairs = LoopbackPairs.from_dict(
        {"interface": "Interposer", "pairs": [[" A1 ", "B1"]], "name": "PCB"}
    )
    assert pairs.interface == "interposer"
    assert pairs.pairs == [("A1", "B1")]
    assert LoopbackPairs.from_dict(pairs.to_dict()) == pairs
    assert pairs.to_dict()["kind"] == KIND


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ({"interface": "x", "pairs": [["A1"]]}, "exactly two pads"),
        ({"interface": "x", "pairs": [["A1", "A1"]]}, "paired with itself"),
        ({"interface": "x", "pairs": [["A1", "B1"], ["B1", "C1"]]}, "already in pair 1"),
        ({"interface": "x", "pairs": [["A,1", "B1"]]}, "contains a ','"),
        ({"interface": "x", "pairs": [["A1", 3]]}, "non-empty strings"),
        ({"pairs": [["A1", "B1"]]}, "'interface' is missing"),
        ({"kind": "analysis-preset"}, "not a loopback-pairs file"),
    ],
)
def test_malformed_pairs_are_rejected(raw, fragment):
    with pytest.raises(ValueError, match=fragment):
        LoopbackPairs.from_dict(raw)


def test_load_pairs_requires_the_kind_and_records_the_source(tmp_path):
    good = tmp_path / "loop.json"
    good.write_text(json.dumps({"kind": KIND, "interface": "interposer", "pairs": _PAIRS}))
    pairs = load_pairs(good)
    assert len(pairs.pairs) == len(_PAIRS)
    assert pairs.source == "loop.json"

    unmarked = tmp_path / "unmarked.json"
    unmarked.write_text(json.dumps({"interface": "interposer", "pairs": _PAIRS}))
    with pytest.raises(ValueError, match="not a loopback-pairs file"):
        load_pairs(unmarked)


# ---- resolution through the mapping ------------------------------------------
def test_resolution_places_every_pad(mapping):
    res = resolve_pairs(_pairs(), mapping)
    assert res.ok
    assert not res.problems
    assert res.links[(0, 1)].partner == (0, 2)
    assert ((0, 1), (0, 2)) in res.pairs()
    assert len(res.pairs()) == len(_PAIRS)


def test_no_mapping_or_missing_column_resolves_nothing(mapping):
    res = resolve_pairs(_pairs(), None)
    assert not res.ok
    assert "No mapping selected" in res.problems[0]

    res = resolve_pairs(_pairs(interface="bondfinger"), mapping)
    assert not res.ok
    assert "no 'bondfinger' column" in res.problems[0]
    assert "interposer" in res.problems[0]  # says which columns it does have


def test_pad_missing_from_mapping_is_reported_and_partner_kept(mapping):
    res = resolve_pairs(_pairs([["A1", "ZZ9"]]), mapping)
    assert res.ok
    assert "not in mapping" in res.problems[0]
    assert "ZZ9" in res.problems[0]
    # A1 is still on the loopback (it must read 2x); its partner is unplaceable
    assert res.links[(0, 1)].partner is None
    assert res.pairs() == []


def test_same_net_and_double_claimed_addresses_are_reported(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "connector,pin,interposer\n"
        "0,1,A1;B1\n"  # A1 and B1 are one net
        "0,2,C1\n"
        "0,2,D1\n"  # C1 and D1 claim one address
        "0,3,C2\n"
        "0,4,D2\n"
    )
    res = resolve_pairs(_pairs([["A1", "B1"], ["C1", "C2"], ["D1", "D2"]]), load_csv(path))
    text = "\n".join(res.problems)
    assert "same net" in text
    assert "claimed by pads C1 and D1" in text
    assert (0, 1) not in res.links


# ---- the analysis ------------------------------------------------------------
def _settings(**kw) -> A.LoopbackAnalysisSettings:
    return A.LoopbackAnalysisSettings(pairs=_pairs(), **kw)


def test_loopback_verdicts(mapping):
    df = _result([
        (0, 1, 2.05), (0, 2, 1.95),  # A1/B1: loop closes
        (0, 3, 1.02), (0, 4, 0.98),  # A2/B2: loop open
        (0, 5, 2.0), (0, 6, 1.0),  # C1/C2: disagree
        (0, 7, 1.01),  # D1: unpaired, single filter
        (0, 8, 2.0),  # not in the mapping at all: unpaired, doubled
        (0, 9, 2.0),  # E1: partner on connector 1, not measured
        (0, 10, 0.5),  # shorted to GND
        (0, 11, 3.1),  # F1: three filters
    ], shorted={(0, 10)})
    res = A.analyse("measure_filter", df, _settings(), mode="loopback", mapping=mapping)
    got = {k: f.status for k, f in _by_pin(res).items()}
    assert got == {
        (0, 1): "ok", (0, 2): "ok",
        (0, 3): "loop_open", (0, 4): "loop_open",
        (0, 5): "pair_mismatch", (0, 6): "pair_mismatch",
        (0, 7): "ok",
        (0, 8): "extra_short",
        (0, 9): "ok",
        (0, 10): "shorted",
        (0, 11): "extra_short",
    }
    assert res.mode == "loopback"
    assert not res.warnings

    by_pin = _by_pin(res)
    assert "pad A1 <-> B1" in by_pin[(0, 1)].message
    assert "partner B1 reads 1.95 nF" in by_pin[(0, 1)].message
    assert "pad D1, unpaired" in by_pin[(0, 7)].message
    assert "partner E2 not measured" in by_pin[(0, 9)].message
    assert "disagree" in by_pin[(0, 5)].message
    # per-pin bands: 2x around the paired pins, below 1.5x for the unpaired one
    assert by_pin[(0, 1)].limits["c"] == (1.5, 2.5)
    assert by_pin[(0, 7)].limits["c"] == (0.1, 1.5)


def test_r_is_still_judged(mapping):
    df = _result([(0, 1, 2.0), (0, 2, 2.0)], r_ohm=5000.0)
    res = A.analyse(
        "measure_filter", df, _settings(r_max_ohm=3000.0), mode="loopback",
        mapping=mapping,
    )
    finding = _by_pin(res)[(0, 1)]
    assert finding.status == "above_limit"
    assert finding.failed == ["r"]


def test_ratio_follows_the_nominal(mapping):
    df = _result([(0, 1, 4.0), (0, 2, 4.0)])
    res = A.analyse(
        "measure_filter", df, _settings(c_nominal_nf=2.0), mode="loopback",
        mapping=mapping,
    )
    assert {f.status for f in res.findings} == {"ok"}


def test_nothing_is_judged_without_pairs_or_mapping(mapping):
    df = _result([(0, 1, 2.0)])
    no_pairs = A.analyse(
        "measure_filter", df, A.LoopbackAnalysisSettings(), mode="loopback",
        mapping=mapping,
    )
    assert no_pairs.findings == []
    assert "No loopback pairs loaded" in no_pairs.warnings[0]

    no_mapping = A.analyse("measure_filter", df, _settings(), mode="loopback")
    assert no_mapping.findings == []
    assert "No mapping selected" in no_mapping.warnings[0]
    assert "Warnings (1)" in A.render_report(no_mapping)


# ---- modes + presets ---------------------------------------------------------
def test_filter_has_two_modes_the_others_one():
    assert [m.key for m in A.analysis_modes("measure_filter")] == ["standard", "loopback"]
    assert len(A.analysis_modes("measure_voltage")) == 1
    assert A.analysis_settings_for("measure_filter") is A.FilterAnalysisSettings
    assert (
        A.analysis_settings_for("measure_filter", "loopback")
        is A.LoopbackAnalysisSettings
    )
    assert A.analysis_mode("measure_filter", "nope") is None


def test_loopback_preset_round_trip_and_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "layouts"))
    loop = presets.save(_settings(c_nominal_nf=0.9), "measure_filter", "loop PCB")
    std = presets.save(A.FilterAnalysisSettings(), "measure_filter", "plain")

    assert json.loads(loop.read_text())["analysis"] == "loopback"
    preset = presets.load(loop)
    assert preset.analysis == "loopback"
    assert preset.settings == _settings(c_nominal_nf=0.9)

    assert [p for _, p in presets.list_presets("measure_filter", "loopback")] == [loop]
    assert [p for _, p in presets.list_presets("measure_filter", "standard")] == [std]


def test_preset_without_mode_is_standard_and_unknown_mode_rejected():
    payload = {"kind": "analysis-preset", "measurement": "measure_filter", "settings": {}}
    assert presets.from_payload(payload).analysis == "standard"
    with pytest.raises(ValueError, match="unknown analysis mode"):
        presets.from_payload({**payload, "analysis": "nope"})
