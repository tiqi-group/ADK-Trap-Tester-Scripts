"""Loopback analysis: an interface tested with its pads shorted in pairs.

An analysis *mode* of ``measure_filter`` (the measurement itself is unchanged).
With a loopback PCB on the interface, a pin whose path through the interface
works reaches its partner's filter too, so the fit sees both capacitors (AFE
README, "Shorts between Electrodes")::

    paired pin     ~2x nominal  ok            (the loop closes)
                   ~1x nominal  loop open     (the interface does not connect)
                   >2x nominal  extra short   (more than one other filter attached)
    unpaired pin   ~1x nominal  ok            (only its own filter)
                   >1x nominal  extra short   (joined to something it should not be)

The classification is by the ratio C / ``c_nominal_nf`` with cut-offs at
``loop_min_ratio`` / ``loop_max_ratio`` (1.5x / 2.5x), half-way between the
filter counts, so ordinary capacitor spread cannot blur 1x into 2x.

Shorted and not-detected points keep the standard filter verdicts, and R is
judged against the same min/max window as in the standard analysis — joining
two filters changes the fitted C, not the filter resistance. Finally both pins
of a pair must agree: physically, if A reaches B's filter then B reaches A's, so
two pins of one pair with different readings point at the measurement, not the
interface ("pair mismatch").

Which pins are paired comes from the pairs table (pad names, see
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
    meta,
)
from trap_tester.core.analysis.filter_analysis import (
    FilterRow,
    precheck,
    read_filter_rows,
)
from trap_tester.core.analysis.loopback import (
    Address,
    LoopbackPairs,
    Resolution,
    resolve_pairs,
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
    filter *count* (1 or 2), set by the pairs table and the mapping.
    """

    measurement: ClassVar[str] = "measure_filter"

    # --- Capacitance ---
    c_nominal_nf: float = field(  # one filter's C; the ratios are relative to it
        default=1.0, metadata=meta(_CAT_C, unit="nF")
    )
    min_c_abs_nf: float = field(  # below this the cap counts as not detected
        default=0.1, metadata=meta(_CAT_C, unit="nF")
    )

    # --- Loopback (C / nominal) ---
    loop_min_ratio: float = field(default=1.5, metadata=meta(_CAT_LOOP, unit="x"))
    loop_max_ratio: float = field(default=2.5, metadata=meta(_CAT_LOOP, unit="x"))

    # --- Filter resistance ---
    r_min_ohm: float = field(default=0.0, metadata=meta(_CAT_R, unit="Ohm"))
    r_max_ohm: float = field(default=1e9, metadata=meta(_CAT_R, unit="Ohm"))

    pairs: LoopbackPairs = field(
        default_factory=LoopbackPairs, metadata=meta(_CAT_LOOP, hidden=True)
    )

    @property
    def reference(self) -> Reference:
        """Always empty: R is judged against the min/max window only."""
        return Reference()

    def paired_band(self) -> tuple[float, float]:
        return (
            self.loop_min_ratio * self.c_nominal_nf,
            self.loop_max_ratio * self.c_nominal_nf,
        )

    def params(self) -> dict[str, Any]:
        lo, hi = self.paired_band()
        r_lo, r_hi = self.limits(R_FILTER)
        return {
            "Loopback pairs": self.pairs.describe(),
            "Nominal C (one filter)": C_FILTER.format(self.c_nominal_nf),
            "Paired pin (2 filters)": C_FILTER.band_text(lo, hi),
            "Unpaired pin (1 filter)": f"below {C_FILTER.format(lo)}",
            f"{R_FILTER.label} limits": R_FILTER.band_text(r_lo, r_hi),
            "Capacitance detection floor": C_FILTER.format(self.min_c_abs_nf),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        data = dict(data or {})
        if "pairs" in data:
            data["pairs"] = LoopbackPairs.from_dict(data["pairs"])
        return super().from_dict(data)


@dataclass
class _Reading:
    """One judged pin before the pair-consistency pass."""

    row: FilterRow
    c_status: str | None  # None for a shorted / not-detected point
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


def _c_status(ratio: float, paired: bool, s: LoopbackAnalysisSettings) -> str:
    if ratio > s.loop_max_ratio or (not paired and ratio >= s.loop_min_ratio):
        return "extra_short"
    if paired and ratio < s.loop_min_ratio:
        return "loop_open"
    return "ok"


_C_HEADLINE = {
    "ok": "Loop OK",
    "loop_open": "Loop open (partner's filter not reached)",
    "extra_short": "Extra short (more filters attached than the loopback explains)",
}


def _judge(
    row: FilterRow, s: LoopbackAnalysisSettings, resolution: Resolution,
    pad: str | None, measured: dict[Address, FilterRow],
) -> _Reading:
    from trap_tester.core.analysis import Finding

    early = precheck(row, s.min_c_abs_nf)
    if early is not None:
        return _Reading(row, None, early)

    addr = (row.connector, row.pin)
    link = resolution.links.get(addr)
    paired = link is not None
    ratio = row.c_nf / s.c_nominal_nf if s.c_nominal_nf > 0 else float("inf")
    c_status = _c_status(ratio, paired, s)
    r_verdict = s.judge(R_FILTER, row.r_ohm, row.connector, row.pin)
    status = max(
        (c_status, r_verdict.status), key=lambda st: SEVERITY.get(st, 0)
    )

    c_text = f"C {C_FILTER.format(row.c_nf)} = {ratio:.2f}x nominal"
    if paired:
        lo, hi = s.paired_band()
        headline = _C_HEADLINE[c_status]
        if link.partner is None:
            partner = f"partner {link.partner_pad} not in mapping"
        elif link.partner in measured:
            other = measured[link.partner]
            partner = (
                f"partner {link.partner_pad} reads {C_FILTER.format(other.c_nf)}"
                if other.c_nf >= 0
                else f"partner {link.partner_pad} has no C reading"
            )
        else:
            partner = f"partner {link.partner_pad} not measured"
        label = f"pad {link.pad} <-> {link.partner_pad}"
    else:
        lo, hi = s.min_c_abs_nf, s.paired_band()[0]
        headline = (
            "Unpaired, single filter" if c_status == "ok" else _C_HEADLINE[c_status]
        )
        partner = ""
        label = f"pad {pad}, unpaired" if pad else "unpaired"
    parts = [c_text, r_verdict.describe()]
    if partner:
        parts.append(partner)
    if not r_verdict.ok:
        headline = f"{headline}; {r_verdict.headline()}"
    message = f"{headline} on {row.where} ({label}): {', '.join(parts)}"

    verdicts = (("c", c_status), ("r", r_verdict.status))
    failed = [key for key, st in verdicts if st != "ok"]
    finding = Finding(
        row.connector, row.pin, row.fpc, row.plotted, status, message,
        values={"c": row.c_nf, "r": row.r_ohm},
        limits={"c": (lo, hi), "r": (r_verdict.lo, r_verdict.hi)},
        failed=failed,
    )
    return _Reading(row, c_status, finding)


def _flag_mismatches(readings: dict[Address, _Reading], resolution: Resolution) -> None:
    """Both pins of a pair must read the same filter count; flag them if not."""
    for a, b in resolution.pairs():
        ra, rb = readings.get(a), readings.get(b)
        if ra is None or rb is None or ra.c_status is None or rb.c_status is None:
            continue  # partner unmeasured, or a shorted / undetected point
        if ra.c_status == rb.c_status:
            continue
        note = (
            f"Pair mismatch — {resolution.links[a].pad} and "
            f"{resolution.links[b].pad} disagree, re-measure: "
        )
        for reading in (ra, rb):
            reading.finding.status = "pair_mismatch"
            reading.finding.message = note + reading.finding.message
            if "c" not in reading.finding.failed:
                reading.finding.failed.append("c")


def analyse_loopback(
    df: pd.DataFrame, s: LoopbackAnalysisSettings, mapping: Mapping | None = None
):
    from trap_tester.core.analysis import AnalysisResult

    rows = read_filter_rows(df)
    if not s.pairs:
        resolution = Resolution(
            problems=["No loopback pairs loaded — use 'Load pairs…' to read a "
                      "loopback-pairs JSON."],
            ok=False,
        )
    else:
        resolution = resolve_pairs(s.pairs, mapping)

    readings: dict[Address, _Reading] = {}
    ordered: list[_Reading] = []
    if resolution.ok:
        measured = {(r.connector, r.pin): r for r in rows}
        pads = _pads_on(mapping, s.pairs.interface)
        for row in rows:
            addr = (row.connector, row.pin)
            reading = _judge(row, s, resolution, pads.get(addr), measured)
            readings[addr] = reading
            ordered.append(reading)
        _flag_mismatches(readings, resolution)

    return AnalysisResult(
        measurement="measure_filter",
        title="Loopback analysis",
        findings=[r.finding for r in ordered],
        value_label="C_filter [nF]",
        params=s.params(),
        band=None,  # 2x for paired pins, 1x for the rest: drawn per pin
        warnings=resolution.problems,
    )


__all__ = ["LoopbackAnalysisSettings", "analyse_loopback"]
