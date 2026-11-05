"""Loopback analysis: an interface tested with its pads joined by a loopback PCB.

An analysis *mode* of ``measure_filter`` (the measurement itself is unchanged).
With a loopback PCB on the interface, a pin whose path through the interface
works reaches the filters of every pad its group joins, so the fit sees all of
those capacitors (AFE README, "Shorts between Electrodes")::

    pin in a group of n   ~n x nominal   ok            (the loop closes)
                          < n x nominal  loop open     (not every filter reached)
                          > n x nominal  extra short   (more filters than the group)
    ungrouped pin         ~1x nominal    ok            (only its own filter)
                          >1x nominal    extra short   (joined to something else)
    grounded pad          shorted        shorted (expected) — a pass
                          anything else  loop open     (the board's GND not reached)

The classification is by the ratio C / ``c_nominal_nf``, accepted within
``count_tolerance`` filters of the expected count (0.5: half-way between counts,
so ordinary capacitor spread cannot blur one count into the next).

Shorted and not-detected points keep the standard filter verdicts (except on a
grounded pad, where shorted is the expectation), and R is judged against the same
min/max window as in the standard analysis — joining filters changes the fitted
C, not the filter resistance. Finally every pin of a group must agree:
physically, if A reaches B's filter then B reaches A's, so pins of one group
with different readings point at the measurement, not the interface ("group
mismatch").

Which pins are grouped comes from the loopback board (pad names, see
:mod:`~trap_tester.core.analysis.loopback`) resolved through the selected
mapping — that is why this mode takes the mapping as an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from trap_tester.core.analysis.acceptance import (
    SEVERITY,
    AcceptanceSettings,
    Reference,
    fpc_inverted_field,
    meta,
)
from trap_tester.core.analysis.filter_analysis import (
    FilterRow,
    precheck,
    read_filter_rows,
)
from trap_tester.core.analysis.loopback import (
    Address,
    LoopbackBoard,
    Member,
    Resolution,
    resolve_board,
)
from trap_tester.core.analysis.quantities import C_FILTER, R_FILTER

if TYPE_CHECKING:
    from trap_tester.core.analysis import Finding
    from trap_tester.core.layout.mapping import Mapping

_CAT_C = C_FILTER.label
_CAT_LOOP = "Loopback"
_CAT_R = R_FILTER.label


@dataclass
class LoopbackAnalysisSettings(AcceptanceSettings):
    """Criteria for a filter result taken through a loopback PCB.

    There is no golden reference in this mode: the expectation per pin is a
    filter *count*, set by the loopback board and the mapping.
    """

    measurement: ClassVar[str] = "measure_filter"

    # --- FPC: the device's ribbon plugged in reversed ---
    fpc_inverted: bool = fpc_inverted_field()

    # --- Capacitance ---
    # One filter's C as seen through the loopback; the counts are relative to it.
    # 1.4 nF: the 1 nF filter plus the FPC's capacitance (the original interposer
    # analysis expected 2.8 nF for a pair).
    c_nominal_nf: float = field(default=1.4, metadata=meta(_CAT_C, unit="nF"))
    min_c_abs_nf: float = field(  # below this the cap counts as not detected
        default=0.1, metadata=meta(_CAT_C, unit="nF")
    )

    # --- Loopback: accepted distance from the expected filter count ---
    count_tolerance: float = field(
        default=0.5, metadata=meta(_CAT_LOOP, unit="filters")
    )

    # --- Filter resistance ---
    r_min_ohm: float = field(default=0.0, metadata=meta(_CAT_R, unit="Ohm"))
    r_max_ohm: float = field(default=1e9, metadata=meta(_CAT_R, unit="Ohm"))

    board: LoopbackBoard = field(
        default_factory=LoopbackBoard, metadata=meta(_CAT_LOOP, hidden=True)
    )

    @property
    def reference(self) -> Reference:
        """Always empty: R is judged against the min/max window only."""
        return Reference()

    def band(self, count: int) -> tuple[float, float]:
        """The accepted C for a pin of a group of ``count`` pads (1: ungrouped)."""
        nominal = self.c_nominal_nf
        if count <= 1:  # an ungrouped pin: anything detected, up to one filter
            return self.min_c_abs_nf, (1 + self.count_tolerance) * nominal
        return (
            (count - self.count_tolerance) * nominal,
            (count + self.count_tolerance) * nominal,
        )

    def params(self) -> dict[str, Any]:
        tol = self.count_tolerance
        r_lo, r_hi = self.limits(R_FILTER)
        return {
            **self.fpc_params(),
            "Loopback board": self.board.describe(),
            "Nominal C (one filter)": C_FILTER.format(self.c_nominal_nf),
            "Pin in a group of n": f"(n ± {tol:g}) x nominal",
            "Ungrouped pin": f"below {C_FILTER.format(self.band(1)[1])}",
            "Grounded pad": "must read shorted",
            f"{R_FILTER.label} limits": R_FILTER.band_text(r_lo, r_hi),
            "Capacitance detection floor": C_FILTER.format(self.min_c_abs_nf),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        data = dict(data or {})
        if "board" in data:
            data["board"] = LoopbackBoard.from_dict(data["board"])
        return super().from_dict(data)


@dataclass
class _Reading:
    """One judged pin before the group-consistency pass."""

    row: FilterRow
    c_status: str | None  # None when the pin takes no part in the group check
    finding: Finding


def _pads_on(mapping: Mapping | None, interface: str) -> dict[Address, str]:
    """The pad name each tester address has on the loopback's interface."""
    if mapping is None:
        return {}
    return {
        addr: net.idents[interface][0]
        for addr, net in mapping.by_connector_pin().items()
        if net.idents.get(interface)
    }


def _c_status(ratio: float, count: int, s: LoopbackAnalysisSettings) -> str:
    tol = s.count_tolerance
    if ratio > count + tol:
        return "extra_short"
    if count > 1 and ratio < count - tol:
        return "loop_open"
    return "ok"


_C_HEADLINE = {
    "ok": "Loop OK",
    "loop_open": "Loop open (not every filter of the group reached)",
    "extra_short": "Extra short (more filters attached than the loopback explains)",
}


def _others_text(member: Member, measured: dict[Address, FilterRow]) -> str:
    """What the rest of a pin's group read: ``"B1 reads 2 nF, C1 not measured"``."""
    parts = []
    for pad, addr in member.others:
        if addr is None:
            parts.append(f"{pad} not in mapping")
        elif addr not in measured:
            parts.append(f"{pad} not measured")
        elif measured[addr].c_nf < 0:
            parts.append(f"{pad} has no C reading")
        else:
            parts.append(f"{pad} reads {C_FILTER.format(measured[addr].c_nf)}")
    return ", ".join(parts)


def _judge_gnd(row: FilterRow, pad: str) -> _Reading:
    """A pad the loopback board grounds: shorted is the expectation."""
    from trap_tester.core.analysis import Finding

    values = {"values": {"c": row.c_nf, "r": row.r_ohm}}
    if row.shorted:
        return _Reading(row, None, Finding(
            row.connector, row.pin, row.fpc, row.plotted, "expected_short",
            f"Shorted to GND as the loopback board does, on {row.where} "
            f"(pad {pad}): R {row.r_ohm:.4g} Ohm", **values,
        ))
    reading = f"C {C_FILTER.format(row.c_nf)}" if row.c_nf >= 0 else "no C reading"
    return _Reading(row, None, Finding(
        row.connector, row.pin, row.fpc, row.plotted, "loop_open",
        f"Loop open (the loopback board grounds pad {pad}, but no short to GND "
        f"was seen) on {row.where}: {reading}", failed=["c"], **values,
    ))


def _judge(
    row: FilterRow, s: LoopbackAnalysisSettings, resolution: Resolution,
    pad: str | None, measured: dict[Address, FilterRow],
) -> _Reading:
    from trap_tester.core.analysis import Finding

    addr = (row.connector, row.pin)
    if addr in resolution.gnd:
        return _judge_gnd(row, resolution.gnd[addr])
    early = precheck(row, s.min_c_abs_nf)
    if early is not None:
        return _Reading(row, None, early)

    member = resolution.members.get(addr)
    count = member.size if member is not None else 1
    ratio = row.c_nf / s.c_nominal_nf if s.c_nominal_nf > 0 else float("inf")
    c_status = _c_status(ratio, count, s)
    r_verdict = s.judge(R_FILTER, row.r_ohm, row.connector, row.pin)
    status = max((c_status, r_verdict.status), key=lambda st: SEVERITY.get(st, 0))

    parts = [
        f"C {C_FILTER.format(row.c_nf)} = {ratio:.2f}x nominal (expects {count})",
        r_verdict.describe(),
    ]
    if member is not None:
        headline = _C_HEADLINE[c_status]
        others = ", ".join(pad for pad, _ in member.others)
        label = f"pad {member.pad}, grouped with {others}"
        parts.append(_others_text(member, measured))
    else:
        headline = (
            "Ungrouped, single filter" if c_status == "ok" else _C_HEADLINE[c_status]
        )
        label = f"pad {pad}, ungrouped" if pad else "ungrouped"
    if not r_verdict.ok:
        headline = f"{headline}; {r_verdict.headline()}"

    verdicts = (("c", c_status), ("r", r_verdict.status))
    finding = Finding(
        row.connector, row.pin, row.fpc, row.plotted, status,
        f"{headline} on {row.where} ({label}): {', '.join(parts)}",
        values={"c": row.c_nf, "r": row.r_ohm},
        limits={"c": s.band(count), "r": (r_verdict.lo, r_verdict.hi)},
        failed=[key for key, st in verdicts if st != "ok"],
    )
    return _Reading(row, c_status, finding)


def _flag_mismatches(readings: dict[Address, _Reading], resolution: Resolution) -> None:
    """Every measured pin of a group must read the same count; flag them if not."""
    for group in resolution.groups():
        judged = [
            readings[a] for a in group
            if a in readings and readings[a].c_status is not None
        ]
        if len({r.c_status for r in judged}) <= 1:
            continue  # agree, or too few measured pins to compare
        pads = ", ".join(resolution.members[a].pad for a in group)
        note = f"Group mismatch — {pads} disagree, re-measure: "
        for reading in judged:
            reading.finding.status = "group_mismatch"
            reading.finding.message = note + reading.finding.message
            if "c" not in reading.finding.failed:
                reading.finding.failed.append("c")


def _chain(groups: list[list[Address]]) -> list[tuple[Address, Address]]:
    """Each group as links between consecutive pads (a pair is one link)."""
    return [(g[i], g[i + 1]) for g in groups for i in range(len(g) - 1)]


def analyse_loopback(
    df: pd.DataFrame, s: LoopbackAnalysisSettings, mapping: Mapping | None = None
):
    from trap_tester.core.analysis import AnalysisResult

    rows = read_filter_rows(df)
    if not s.board:
        resolution = Resolution(
            problems=["No loopback board loaded — use 'Load loopback…' to read a "
                      "loopback JSON."],
            ok=False,
        )
    else:
        resolution = resolve_board(s.board, mapping)

    ordered: list[_Reading] = []
    if resolution.ok:
        measured = {(r.connector, r.pin): r for r in rows}
        pads = _pads_on(mapping, s.board.interface)
        ordered = [
            _judge(row, s, resolution, pads.get((row.connector, row.pin)), measured)
            for row in rows
        ]
        _flag_mismatches(
            {(r.row.connector, r.row.pin): r for r in ordered}, resolution
        )

    return AnalysisResult(
        measurement="measure_filter",
        title="Loopback analysis",
        findings=[r.finding for r in ordered],
        value_label="C_filter [nF]",
        params=s.params(),
        band=None,  # each pin expects its own group's count: drawn per pin
        warnings=resolution.problems,
        links=_chain(resolution.groups()),
    )


__all__ = ["LoopbackAnalysisSettings", "analyse_loopback"]
