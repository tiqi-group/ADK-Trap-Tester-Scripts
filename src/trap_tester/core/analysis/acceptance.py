"""Acceptance criteria: min/max limits, an optional golden reference, verdicts.

Every analysis judges each measured value against a band. The band comes from
one of two places, and *which* one is decided per (pin, quantity) by whether a
reference entry exists — there is no mode switch:

* no reference entry -> the operator's global ``min``/``max`` limits, which
  subsume absolute *and* relative tolerance (the operator does the arithmetic);
* a reference entry -> ``expected ± (abs_tol + rel_tol · |expected|)``, so a
  measured golden board can be re-used as the acceptance criterion. ``rel_tol``
  is one global number; ``abs_tol`` is per quantity because nF and Ohm are not
  interchangeable.

The reference table is keyed ``"<connector>:<pin>"``. ``measure_resistance`` and
``measure_voltage`` have no connector — their rows are keyed by measurement
round — so they use the wildcard ``"*:<pin>"``: one expected value per pin,
matched whatever the round. Lookup tries the exact key first, then the wildcard,
so a per-connector entry always wins over a blanket one.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar

from trap_tester.core.analysis.quantities import Quantity, quantities_for

WILDCARD = "*"

# How bad each verdict is — a pin's status is the worst of its quantities'.
SEVERITY: dict[str, int] = {
    "ok": 0,
    "below_limit": 1,
    "above_limit": 2,
    "high_impedance": 3,
    "not_detected": 4,
    "shorted": 5,
}


def meta(
    category: str, unit: str | None = None, hidden: bool = False
) -> dict[str, Any]:
    """Field metadata for the settings form: section, unit, and ``hidden``
    for fields the generated form must not render (the reference table)."""
    md: dict[str, Any] = {"category": category}
    if unit is not None:
        md["unit"] = unit
    if hidden:
        md["hidden"] = True
    return md


CAT_TOL = "Reference tolerances"


def reference_key(connector: int | str, pin: int) -> str:
    """The reference-table key for a point (``connector`` may be the wildcard)."""
    return f"{connector}:{int(pin)}"


@dataclass
class Reference:
    """Expected values per point: ``"<conn>:<pin>" -> {quantity key -> value}``.

    Captured from a measurement marked as the golden reference; ``source`` and
    ``captured`` record where it came from so a preset stays traceable.
    """

    values: dict[str, dict[str, float]] = field(default_factory=dict)
    source: str = ""
    captured: str = ""

    def __bool__(self) -> bool:
        return bool(self.values)

    @property
    def n_points(self) -> int:
        return len(self.values)

    def lookup(self, connector: int | str, pin: int, quantity_key: str) -> float | None:
        """The expected value for a point, exact key first, then the wildcard."""
        for key in (reference_key(connector, pin), reference_key(WILDCARD, pin)):
            entry = self.values.get(key)
            if entry is not None and quantity_key in entry:
                try:
                    return float(entry[quantity_key])
                except (TypeError, ValueError):
                    return None
        return None

    def describe(self) -> str:
        if not self.values:
            return "none"
        text = f"{self.n_points} point(s)"
        if self.source:
            text += f" from {self.source}"
        return text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Reference:
        """Rebuild from JSON, tolerating a bare ``{key: {...}}`` values mapping."""
        if isinstance(data, Reference):
            return data
        if not isinstance(data, dict):
            return cls()
        raw = data.get("values", data if "source" not in data else {})
        values: dict[str, dict[str, float]] = {}
        for key, entry in (raw or {}).items():
            if not isinstance(entry, dict):
                continue
            point = {}
            for qkey, value in entry.items():
                try:
                    point[str(qkey)] = float(value)
                except (TypeError, ValueError):
                    continue
            if point:
                values[str(key)] = point
        return cls(
            values=values,
            source=str(data.get("source", "")),
            captured=str(data.get("captured", "")),
        )


@dataclass
class QuantityVerdict:
    """One quantity's outcome for one point: the value, its band and the call."""

    quantity: Quantity
    value: float
    lo: float
    hi: float
    expected: float | None  # set only when the band came from the reference
    status: str  # a STATUS_INFO key

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def describe(self) -> str:
        """``"C 1.9 nF (limit 0.75…1.25 nF)"`` — the band shown only on a fail."""
        q = self.quantity
        text = f"{q.symbol} {q.format(self.value)}"
        if self.ok:
            return text
        kind = "tolerance" if self.expected is not None else "limit"
        return f"{text} ({kind} {q.band_text(self.lo, self.hi)})"

    def headline(self) -> str:
        """``"C above limit"`` — the leading clause of a fault message."""
        q = self.quantity
        where = "above" if self.status == q.fail_high else "below"
        kind = "tolerance" if self.expected is not None else "limit"
        text = f"{q.symbol} {where} {kind}"
        hint = q.high_hint if self.status == q.fail_high else q.low_hint
        return f"{text} ({hint})" if hint else text


class AcceptanceSettings:
    """Mixin for the per-measurement analysis-settings dataclasses.

    Deliberately *not* a dataclass itself: each settings class declares its own
    limit fields (with unit-bearing names and form metadata) and its own
    ``rel_tol`` / ``reference``, so field order in the generated form stays
    "limits first, tolerances last" instead of being fixed by inheritance.
    """

    measurement: ClassVar[str] = ""
    # legacy settings-key -> current field name, applied by from_dict
    legacy_names: ClassVar[dict[str, str]] = {}

    reference: Reference
    rel_tol: float

    # ---- quantities / bands -------------------------------------------------
    @classmethod
    def quantities(cls) -> list[Quantity]:
        return quantities_for(cls.measurement)

    def limits(self, q: Quantity) -> tuple[float, float]:
        return float(getattr(self, q.min_field)), float(getattr(self, q.max_field))

    def abs_tol(self, q: Quantity) -> float:
        return float(getattr(self, q.abs_tol_field))

    def has_reference(self) -> bool:
        return bool(self.reference)

    def band_for(
        self, q: Quantity, connector: int | str, pin: int
    ) -> tuple[float, float, float | None]:
        """``(lo, hi, expected)`` for one point — reference band, else limits."""
        expected = self.reference.lookup(connector, pin, q.key)
        if expected is None:
            lo, hi = self.limits(q)
            return lo, hi, None
        tol = self.abs_tol(q) + self.rel_tol * abs(expected)
        return expected - tol, expected + tol, expected

    def judge(
        self, q: Quantity, value: float, connector: int | str, pin: int
    ) -> QuantityVerdict:
        """Classify one measured value. The band is inclusive at both ends."""
        lo, hi, expected = self.band_for(q, connector, pin)
        if not math.isfinite(value):
            status = "not_detected"
        elif value < lo:
            status = q.fail_low
        elif value > hi:
            status = q.fail_high
        else:
            status = "ok"
        return QuantityVerdict(q, value, lo, hi, expected, status)

    def judge_all(
        self, values: dict[str, float], connector: int | str, pin: int
    ) -> list[QuantityVerdict]:
        """Judge every quantity of this measurement for one point.

        ``values`` is keyed by quantity key; a quantity missing from it (a
        column the results frame does not carry) is simply skipped.
        """
        return [
            self.judge(q, values[q.key], connector, pin)
            for q in self.quantities()
            if q.key in values
        ]

    # ---- report parameters --------------------------------------------------
    def params(self) -> dict[str, Any]:
        """The acceptance criteria as the report header lists them."""
        out: dict[str, Any] = {}
        for q in self.quantities():
            lo, hi = self.limits(q)
            out[f"{q.label} limits"] = q.band_text(lo, hi)
        out["reference"] = self.reference.describe()
        if self.has_reference():
            out["rel_tol"] = self.rel_tol
            for q in self.quantities():
                out[f"{q.label} abs tol"] = q.format(self.abs_tol(q))
        return out

    # ---- (de)serialisation --------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        """Build from JSON, migrating legacy keys and ignoring unknown ones."""
        data = cls.migrate(dict(data or {}))
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        kwargs = {k: v for k, v in data.items() if k in known}
        if "reference" in kwargs:
            kwargs["reference"] = Reference.from_dict(kwargs["reference"])
        return cls(**kwargs)  # type: ignore[operator]

    @classmethod
    def migrate(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Rename pre-acceptance-model keys. Subclasses extend for real changes."""
        for old, new in cls.legacy_names.items():
            if old in data and new not in data:
                data[new] = data.pop(old)
        return data


# ---- shared verdict -> Finding helpers -------------------------------------
def overall_status(verdicts: list[QuantityVerdict]) -> str:
    """The worst verdict among a point's quantities (``"ok"`` when all pass)."""
    return max(
        (v.status for v in verdicts), key=lambda s: SEVERITY.get(s, 0), default="ok"
    )


def message_for(where: str, verdicts: list[QuantityVerdict]) -> str:
    """One human-readable line: what failed, where, and every value measured."""
    details = ", ".join(v.describe() for v in verdicts)
    failing = [v for v in verdicts if not v.ok]
    if not failing:
        return f"Nominal on {where}: {details}"
    return f"{', '.join(v.headline() for v in failing)} on {where}: {details}"


def finding_fields(verdicts: list[QuantityVerdict]) -> dict[str, Any]:
    """The per-quantity payload every :class:`~...analysis.Finding` carries."""
    return {
        "values": {v.quantity.key: v.value for v in verdicts},
        "limits": {v.quantity.key: (v.lo, v.hi) for v in verdicts},
        "expected": {
            v.quantity.key: v.expected for v in verdicts if v.expected is not None
        },
        "failed": [v.quantity.key for v in verdicts if not v.ok],
    }


__all__ = [
    "CAT_TOL",
    "SEVERITY",
    "WILDCARD",
    "AcceptanceSettings",
    "QuantityVerdict",
    "Reference",
    "finding_fields",
    "message_for",
    "meta",
    "overall_status",
    "reference_key",
]
