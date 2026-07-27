"""Headless tests for the cross-interface mapping engine (``core.layout.mapping``).

Run with ``uv run pytest tests/test_mapping_core.py``. No hardware and no Qt — these
check CSV parsing (tolerant headers, net ids, blank cells), ``apply_to`` re-wiring
of named vs reference layouts, the inherent-wiring fallback, and the cross-interface
correlation that lets a mark on one interface re-project onto another.
"""

from __future__ import annotations

import pytest

from trap_tester.core.layout import Mapping, apply_to, coverage, load_csv
from trap_tester.core.layout.interface import InterfaceLayout, Slot


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def _named_layout() -> InterfaceLayout:
    # a "Bondfinger"-style layout: slots identified by their per-interface ident
    return InterfaceLayout(
        name="Bondfinger",
        slots=[
            Slot(connector=5, pin=44, x=0.0, y=0.0, channel=14, ident="287"),
            Slot(connector=5, pin=12, x=1.0, y=0.0, channel=12, ident="12"),
            Slot(connector=5, pin=99, x=2.0, y=0.0, channel=99, ident="500"),
        ],
    )


def _reference_layout() -> InterfaceLayout:
    # a DSUB-50-style reference: slots identified by (connector, pin), no ident
    return InterfaceLayout(
        name="DSUB-50",
        slots=[
            Slot(connector=4, pin=31, x=0.0, y=0.0, channel=30),
            Slot(connector=0, pin=5, x=1.0, y=0.0, channel=1),
            Slot(connector=9, pin=9, x=2.0, y=0.0, channel=7),  # matches no net
        ],
    )


_CSV = (
    "hawk3,Bondfinger,LGA_Pad,N Connecgor,DSUB_Pin\n"
    "COMP_0_0,287,B25,4,31\n"
    "COMP_1_0,12,V19,0,5\n"
)


# ---- parsing ---------------------------------------------------------------
def test_load_csv_detects_columns_and_interfaces(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    assert m.name == "map"
    # the connector/DSUB-pin columns are excluded; the rest are named interfaces
    assert m.interfaces == ["hawk3", "Bondfinger", "LGA_Pad"]
    assert len(m.nets) == 2


def test_load_csv_net_ids_and_idents(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    n0, n1 = m.nets
    assert (n0.connector, n0.pin, n0.net_id) == (4, 31, 0)
    assert n0.idents == {"hawk3": "COMP_0_0", "Bondfinger": "287", "LGA_Pad": "B25"}
    assert (n1.connector, n1.pin, n1.net_id) == (0, 5, 1)


def test_load_csv_takes_dsub_pin_modulo_100(tmp_path):
    # the source records a bank-encoded pin (e.g. 126 on connector 7 -> pin 26);
    # the DSUB-50 has 50 pins, so the real pin is value % 100. Pins < 100 unchanged.
    csv = "Bondfinger,N Connecgor,DSUB_Pin\n287,7,126\n12,4,31\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    assert [(n.connector, n.pin) for n in m.nets] == [(7, 26), (4, 31)]


def test_load_csv_tolerates_connector_spelling(tmp_path):
    for header in ("N Connecgor", "N Connector", "Connector", "Connector_Num",
                   "Connector number", "n_conn"):
        m = load_csv(_write(tmp_path, "m.csv", f"Bondfinger,{header},DSUB_Pin\n287,4,31\n"))
        assert (m.nets[0].connector, m.nets[0].pin) == (4, 31)


def test_load_csv_blank_cell_omits_ident(tmp_path):
    csv = "hawk3,Bondfinger,N Connecgor,DSUB_Pin\nCOMP_0_0,,4,31\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    assert m.nets[0].idents == {"hawk3": "COMP_0_0"}  # blank Bondfinger dropped
    assert "287" not in m.idents_for("Bondfinger")
    assert m.idents_for("hawk3") == {"COMP_0_0": m.nets[0]}


def test_load_csv_skips_rows_without_tester_pin(tmp_path):
    csv = "Bondfinger,N Connecgor,DSUB_Pin\n287,4,31\n999,,\n12,0,5\n"
    m = load_csv(_write(tmp_path, "m.csv", csv))
    assert [(n.pin, n.net_id) for n in m.nets] == [(31, 0), (5, 2)]  # net_id tracks row


def test_load_csv_missing_required_column_raises(tmp_path):
    with pytest.raises(ValueError, match="connector"):
        load_csv(_write(tmp_path, "m.csv", "Bondfinger,DSUB_Pin\n287,31\n"))
    with pytest.raises(ValueError, match="DSUB pin"):
        load_csv(_write(tmp_path, "m.csv", "Bondfinger,N Connecgor\n287,4\n"))


# ---- apply_to --------------------------------------------------------------
def test_apply_to_named_layout_remaps_by_ident(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    out = apply_to(_named_layout(), m)
    by_ident = {s.ident: s for s in out.slots}
    # finger 287 is re-wired to the net's tester pin and given its net id as channel
    assert (by_ident["287"].connector, by_ident["287"].pin, by_ident["287"].channel) == (4, 31, 0)
    assert (by_ident["12"].connector, by_ident["12"].pin, by_ident["12"].channel) == (0, 5, 1)
    # finger 500 is in no net -> keeps its inherent wiring (the fallback)
    assert (by_ident["500"].connector, by_ident["500"].pin, by_ident["500"].channel) == (5, 99, 99)


def test_apply_to_reference_layout_remaps_by_connector_pin(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    out = apply_to(_reference_layout(), m)
    by_cp = {(s.connector, s.pin): s for s in out.slots}
    # reference slots keep (connector, pin) but adopt the net id as channel
    assert by_cp[(4, 31)].channel == 0
    assert by_cp[(0, 5)].channel == 1
    # a reference slot with no matching net keeps its inherent channel
    assert by_cp[(9, 9)].channel == 7


def test_apply_to_does_not_mutate_input(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    named = _named_layout()
    before = [(s.connector, s.pin, s.channel) for s in named.slots]
    apply_to(named, m)
    assert [(s.connector, s.pin, s.channel) for s in named.slots] == before


def test_cross_interface_correlation(tmp_path):
    """A net shares one channel across interfaces after re-wiring.

    The DSUB reference slot at (4, 31) and the Bondfinger slot 'B25's finger '287'
    both end up at (connector=4, channel=0) — so a mark/finding on one re-projects
    onto the other (annotation keys by (connector, channel); analysis by
    (connector, pin)).
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    named = apply_to(_named_layout(), m)
    ref = apply_to(_reference_layout(), m)
    finger = next(s for s in named.slots if s.ident == "287")
    dsub = next(s for s in ref.slots if (s.connector, s.pin) == (4, 31))
    assert (finger.connector, finger.channel) == (dsub.connector, dsub.channel) == (4, 0)


def test_apply_to_matches_by_ident_overlap_when_name_differs(tmp_path):
    """A layout whose display name isn't a column is matched by its ident space.

    The interposer is named "Interposer" but its pads live in the CSV's "LGA_Pad"
    column; it must still be ident-re-wired (to the net's *deviating* tester pin),
    not fall back to (connector, pin) — otherwise co-wired / re-cabled pads whose
    inherent pin differs from the mapping never light up.
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    interposer = InterfaceLayout(
        name="Interposer",  # display name, NOT the "LGA_Pad" column header
        slots=[
            # inherent (7, 26) deviates from the mapping's (4, 31) for pad B25
            Slot(connector=7, pin=26, x=0.0, y=0.0, channel=5, ident="B25"),
            Slot(connector=1, pin=1, x=1.0, y=0.0, channel=1, ident="ZZZ"),  # no net
        ],
    )
    out = apply_to(interposer, m)
    b25 = next(s for s in out.slots if s.ident == "B25")
    assert (b25.connector, b25.pin, b25.channel) == (4, 31, 0)  # re-wired by ident
    zzz = next(s for s in out.slots if s.ident == "ZZZ")
    assert (zzz.connector, zzz.pin, zzz.channel) == (1, 1, 1)  # unmatched -> inherent


def test_coverage_reports_matched_slots(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    # named layout: two of its three idents (287, 12) are in the mapping
    assert coverage(_named_layout(), m) == 2
    # reference layout: two of three (connector, pin) are nets
    assert coverage(_reference_layout(), m) == 2


def test_coverage_zero_when_mapping_does_not_apply(tmp_path):
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    # a layout the mapping neither names nor shares any tester pin with
    foreign = InterfaceLayout(
        name="Foreign",
        slots=[Slot(connector=3, pin=3, x=0.0, y=0.0, channel=9, ident="NOPE")],
    )
    assert coverage(foreign, m) == 0


def test_reference_layout_with_no_matching_net_is_untouched(tmp_path):
    # a reference interface (no idents) slot whose (connector, pin) is no net stays put
    m = load_csv(_write(tmp_path, "map.csv", _CSV))
    ref = InterfaceLayout(
        name="DSUB-50",
        slots=[Slot(connector=0, pin=48, x=0.0, y=0.0, channel=46)],  # (0,48) is no net
    )
    out = apply_to(ref, m)
    assert (out.slots[0].connector, out.slots[0].pin, out.slots[0].channel) == (0, 48, 46)


def test_ident_layout_not_named_is_never_reference_matched(tmp_path):
    """A custom layout the mapping doesn't name is left ALONE, even if some of its
    (connector, pin) coincide with nets — those pins are a different family, so a
    numeric match would be a bogus correlation (e.g. hawk1 under a hawk3 mapping).
    """
    m = load_csv(_write(tmp_path, "map.csv", _CSV))  # nets at (4, 31) and (0, 5)
    other = InterfaceLayout(
        name="OtherTrap",
        slots=[
            # (4, 31) coincides with a net, but ident "FOO" is in no column
            Slot(connector=4, pin=31, x=0.0, y=0.0, channel=99, ident="FOO"),
        ],
    )
    assert coverage(other, m) == 0  # -> the GUI warns
    out = apply_to(other, m)
    assert (out.slots[0].connector, out.slots[0].pin, out.slots[0].channel) == (4, 31, 99)
