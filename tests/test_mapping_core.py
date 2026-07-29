"""Headless tests for the cross-interface mapping engine (``core.layout.mapping``).

Run with ``uv run pytest tests/test_mapping_core.py``. No hardware and no Qt — these
check CSV parsing (canonical headers, idents, blank cells), ``apply_to`` re-wiring of
named vs reference layouts, the nominal-wiring fallback, the coverage diff, and the
cross-interface correlation that lets a mark on one interface re-project onto another.

Schema v2: a layout declares its ``slug`` and ``match_by``, so the CSV column is
found by name rather than guessed from ident overlap; ``connector``/``pin`` headers
are canonical rather than tolerated in six spellings; and there is no stored
``channel`` — correlation is by the canonical address.
"""

from __future__ import annotations

import pytest

from trap_tester.core.layout import Mapping, apply_to, coverage, load_csv
from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.mapping import coverage_report, normalize_header


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def _named_layout() -> InterfaceLayout:
    # a "bondfinger"-style layout: slots identified by their per-interface ident
    return InterfaceLayout(
        name="Bondfinger", slug="bondfinger", match_by="ident",
        slots=[
            Slot(connector=5, pin=44, x=0.0, y=0.0, ident="287"),
            Slot(connector=5, pin=12, x=1.0, y=0.0, ident="12"),
            Slot(connector=5, pin=49, x=2.0, y=0.0, ident="500"),
        ],
    )


def _reference_layout() -> InterfaceLayout:
    # a DSUB-50-style reference: slots identified by (connector, pin), no ident
    return InterfaceLayout(
        name="DSUB-50", slug="dsub50", match_by="connector_pin",
        slots=[
            Slot(connector=4, pin=31, x=0.0, y=0.0),
            Slot(connector=0, pin=5, x=1.0, y=0.0),
            Slot(connector=9, pin=9, x=2.0, y=0.0),  # matches no net
        ],
    )


_CSV = (
    "connector,pin,hawk3,bondfinger,interposer\n"
    "4,31,COMP_0_0,287,B25\n"
    "0,5,COMP_1_0,12,V19\n"
)


# ---- parsing ---------------------------------------------------------------
def test_normalize_header_collapses_case_and_separators():
    assert normalize_header("DSUB_Pin") == "dsub_pin"
    assert normalize_header("  Connector ") == "connector"
    assert normalize_header("N Connecgor") == "n_connecgor"  # a typo stays a typo


def test_load_csv_detects_columns_and_interfaces(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    assert m.name == "map"
    # the connector/pin columns are excluded; the rest are named interfaces, by slug
    assert m.interfaces == ["hawk3", "bondfinger", "interposer"]
    assert len(m.nets) == 2


def test_load_csv_rows_and_idents(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    n0, n1 = m.nets
    assert (n0.connector, n0.pin, n0.row) == (4, 31, 0)
    assert n0.idents == {
        "hawk3": ["COMP_0_0"], "bondfinger": ["287"], "interposer": ["B25"],
    }
    assert (n1.connector, n1.pin, n1.row) == (0, 5, 1)


def test_load_csv_rejects_bank_encoded_pin(tmp_path):
    """A pin above the DSUB's range is a data error, not something to silently fix.

    v1 took ``pin % 100`` in the parser because the source encoded the connector
    bank in the hundreds digit. The pin column now means the physical pin, so a file
    that still carries the encoding fails loudly and says what to correct.
    """
    csv = "connector,pin,bondfinger\n7,126,287\n"
    with pytest.raises(ValueError, match=r"outside 1\.\.50"):
        load_csv(_write(tmp_path, "m.csv", csv))


def test_load_csv_rejects_legacy_connector_spelling(tmp_path):
    """The six tolerated spellings are gone; the error names the migration."""
    csv = "bondfinger,N Connecgor,DSUB_Pin\n287,4,31\n"
    with pytest.raises(ValueError, match="no 'connector' column"):
        load_csv(_write(tmp_path, "m.csv", csv))


def test_load_csv_accepts_dsub_pin_as_the_pin_header(tmp_path):
    m = load_csv(_write(tmp_path, "m.csv", "connector,DSUB_Pin,bondfinger\n4,31,287\n"))
    assert (m.nets[0].connector, m.nets[0].pin) == (4, 31)


def test_load_csv_blank_cell_omits_ident(tmp_path):
    csv = "connector,pin,hawk3,bondfinger\n4,31,COMP_0_0,\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    assert m.nets[0].idents == {"hawk3": ["COMP_0_0"]}  # blank bondfinger dropped
    assert "287" not in m.idents_for("bondfinger")
    assert m.idents_for("hawk3") == {"COMP_0_0": m.nets[0]}


def test_load_csv_splits_multi_ident_cells_on_semicolon(tmp_path):
    csv = "connector,pin,interposer\n4,31,B25;B26\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    assert m.nets[0].idents["interposer"] == ["B25", "B26"]
    assert set(m.idents_for("interposer")) == {"B25", "B26"}


def test_load_csv_rejects_a_comma_inside_an_ident(tmp_path):
    """Commas are excluded from idents by rule; the loader enforces it."""
    csv = 'connector,pin,interposer\n4,31,"B25,B26"\n'
    with pytest.raises(ValueError, match="contains a comma"):
        load_csv(_write(tmp_path, "m.csv", csv))


def test_load_csv_skips_rows_without_tester_pin(tmp_path):
    csv = "connector,pin,bondfinger\n4,31,287\n,,999\n0,5,12\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    assert [(n.pin, n.row) for n in m.nets] == [(31, 0), (5, 2)]  # row tracks the source


def test_load_csv_missing_required_column_raises(tmp_path):
    with pytest.raises(ValueError, match="connector"):
        load_csv(_write(tmp_path, "m.csv", "bondfinger,pin\n287,31\n"))
    with pytest.raises(ValueError, match="pin"):
        load_csv(_write(tmp_path, "m.csv", "bondfinger,connector\n287,4\n"))


# ---- apply_to --------------------------------------------------------------
def test_apply_to_named_layout_remaps_by_ident(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    out = apply_to(_named_layout(), m)
    by_ident = {s.ident: s for s in out.slots}
    # finger 287 is re-wired to the net's tester address
    assert (by_ident["287"].connector, by_ident["287"].pin) == (4, 31)
    assert (by_ident["12"].connector, by_ident["12"].pin) == (0, 5)
    # finger 500 is in no net -> keeps its nominal wiring (the fallback)
    assert (by_ident["500"].connector, by_ident["500"].pin) == (5, 49)


def test_apply_to_reference_layout_is_untouched(tmp_path):
    """The reference interface already *is* the address space, so nothing re-stamps.

    In v1 this branch existed to copy the net id into ``channel``; with the channel
    gone there is nothing to do, and correlation happens through the address itself.
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    out = apply_to(_reference_layout(), m)
    assert [(s.connector, s.pin) for s in out.slots] == [(4, 31), (0, 5), (9, 9)]


def test_apply_to_does_not_mutate_input(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    named = _named_layout()
    before = [(s.connector, s.pin) for s in named.slots]
    apply_to(named, m)
    assert [(s.connector, s.pin) for s in named.slots] == before


def test_cross_interface_correlation(tmp_path):
    """A net lands on one canonical address across interfaces after re-wiring.

    The DSUB reference slot at (4, 31) and the bondfinger slot '287' both end up at
    (4, 31) — so a mark on one re-projects onto the other, with no channel involved.
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    named = apply_to(_named_layout(), m)
    ref = apply_to(_reference_layout(), m)
    finger = next(s for s in named.slots if s.ident == "287")
    dsub = next(s for s in ref.slots if (s.connector, s.pin) == (4, 31))
    assert (finger.connector, finger.pin) == (dsub.connector, dsub.pin) == (4, 31)


def test_apply_to_matches_the_column_named_by_the_slug(tmp_path):
    """The slug, not the display name, binds a layout to its column.

    v1 fell back to "the column whose idents overlap most" because columns were
    headed with display names. The slug makes the binding explicit, so a layout can
    be renamed freely without breaking the join.
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    interposer = InterfaceLayout(
        name="Interposer rev C",  # display name differs from the column entirely
        slug="interposer", match_by="ident",
        slots=[
            # nominal (7, 26) deviates from the mapping's (4, 31) for pad B25
            Slot(connector=7, pin=26, x=0.0, y=0.0, ident="B25"),
            Slot(connector=1, pin=1, x=1.0, y=0.0, ident="ZZZ"),  # no net
        ],
    )
    out = apply_to(interposer, m)
    b25 = next(s for s in out.slots if s.ident == "B25")
    assert (b25.connector, b25.pin) == (4, 31)  # re-wired by ident
    zzz = next(s for s in out.slots if s.ident == "ZZZ")
    assert (zzz.connector, zzz.pin) == (1, 1)  # unmatched -> nominal


def test_apply_to_gives_a_synthetic_address_its_real_wiring(tmp_path):
    """The point of the synthetic band: a CSV replaces a placeholder address."""
    from trap_tester.core.layout.addressing import is_synthetic

    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    imported = InterfaceLayout(
        name="flatland", slug="hawk3", match_by="ident",
        slots=[Slot(connector=900, pin=1, x=0.0, y=0.0, ident="COMP_0_0")],
    )
    assert is_synthetic(imported.slots[0].connector)
    out = apply_to(imported, m)
    assert (out.slots[0].connector, out.slots[0].pin) == (4, 31)
    assert not is_synthetic(out.slots[0].connector)


# ---- coverage --------------------------------------------------------------
def test_coverage_reports_matched_slots(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    # named layout: two of its three idents (287, 12) are in the mapping
    assert coverage(_named_layout(), m) == 2
    # reference layout: two of three (connector, pin) are nets
    assert coverage(_reference_layout(), m) == 2


def test_coverage_report_diffs_both_directions(tmp_path):
    """The report names the misses, which a bare count could not."""
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    r = coverage_report(_named_layout(), m)
    assert r.mode == "ident"
    assert r.column == "bondfinger"
    assert sorted(r.matched) == ["12", "287"]
    assert r.layout_only == ["500"]  # in the layout, unwired by this CSV
    assert r.csv_only == []
    assert "500" not in r.summary() or "only in the layout" in r.summary()


def test_coverage_report_flags_a_case_only_match(tmp_path):
    """A case-only match is applied but reported, so the cell can be corrected."""
    csv = "connector,pin,interposer\n4,31,b25\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    layout = InterfaceLayout(
        name="Interposer", slug="interposer", match_by="ident",
        slots=[Slot(connector=1, pin=1, x=0.0, y=0.0, ident="B25")],
    )
    r = coverage_report(layout, m)
    assert r.matched == ["B25"]
    assert r.case_mismatches == [("B25", "b25")]
    out = apply_to(layout, m)
    assert (out.slots[0].connector, out.slots[0].pin) == (4, 31)


def test_coverage_report_does_not_normalise_zero_padding(tmp_path):
    """``N04`` and ``N4`` stay distinct — no numeric munging of idents."""
    m = load_csv(_write(tmp_path, "m.csv", "connector,pin,interposer\n4,31,N04\n"))
    layout = InterfaceLayout(
        name="Interposer", slug="interposer", match_by="ident",
        slots=[Slot(connector=1, pin=1, x=0.0, y=0.0, ident="N4")],
    )
    r = coverage_report(layout, m)
    assert r.matched == []
    assert r.layout_only == ["N4"]
    assert r.csv_only == ["N04"]


def test_coverage_zero_when_mapping_does_not_apply(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    # a layout the mapping neither names nor shares any tester pin with
    foreign = InterfaceLayout(
        name="Foreign", slug="foreign", match_by="ident",
        slots=[Slot(connector=3, pin=3, x=0.0, y=0.0, ident="NOPE")],
    )
    assert coverage(foreign, m) == 0
    assert coverage_report(foreign, m).mode == "none"


def test_ident_layout_not_named_is_never_reference_matched(tmp_path):
    """A layout the mapping doesn't name is left ALONE, even if some of its
    (connector, pin) coincide with nets — those pins are a different family, so a
    numeric match would be a bogus correlation (e.g. hawk1 under a hawk3 mapping).
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))  # nets at (4, 31) and (0, 5)
    other = InterfaceLayout(
        name="OtherTrap", slug="othertrap", match_by="ident",
        slots=[
            # (4, 31) coincides with a net, but ident "FOO" is in no column
            Slot(connector=4, pin=31, x=0.0, y=0.0, ident="FOO"),
        ],
    )
    assert coverage(other, m) == 0  # -> the GUI warns
    out = apply_to(other, m)
    assert (out.slots[0].connector, out.slots[0].pin) == (4, 31)


def test_mapping_dataclass_is_importable():
    assert Mapping(name="x", interfaces=[], nets=[]).interfaces == []
