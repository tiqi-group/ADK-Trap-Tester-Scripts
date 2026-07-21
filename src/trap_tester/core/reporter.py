"""Callback contracts that decouple the measurement loop from the GUI.

The original scripts talked to the operator with ``print`` and blocking
``input`` calls. Those are replaced here by two small protocols:

* :class:`Reporter` — outbound: status text, log lines, live scope captures
  and per-pin result rows.
* :class:`Gate` — inbound: the interactive "retake?" / "switch connector"
  prompts, resolved by whoever drives the measurement (the GUI worker, or a
  CLI/test harness).

Concrete no-op / console implementations are provided for headless runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@runtime_checkable
class Reporter(Protocol):
    """Outbound channel from a measurement to the UI (or a log)."""

    def status(self, text: str) -> None:
        """Set the current high-level status / progress line."""

    def log(self, text: str) -> None:
        """Append a line of terminal output (replaces ``print``)."""

    def capture(self, ch_a: "np.ndarray", ch_b: "np.ndarray", sample_rate: float) -> None:
        """Publish the latest scope buffers (ch_a = scope[0], ch_b = scope[1])."""

    def result(self, row: dict[str, Any]) -> None:
        """Publish a single per-pin result row as it is computed."""


@runtime_checkable
class Gate(Protocol):
    """Inbound channel: interactive prompts the operator must answer."""

    def confirm(self, prompt: str) -> bool:
        """Ask a yes/no question. Returns ``True`` for yes.

        Used for "Retake measurement?" — ``True`` means redo the current round.
        """

    def wait_continue(self, prompt: str) -> None:
        """Block until the operator acknowledges (e.g. after switching connector)."""

    # ---- free-run (live scope) session -------------------------------------
    # Used when a capture never triggers: the measurement enters a live,
    # untriggered "scope mode" for inspection that runs until the operator ends
    # it, without recording anything for the point.
    def begin_freerun(self, prompt: str) -> None:
        """Announce that free-run (scope) mode has started (show its controls)."""

    def freerun_capture_due(self) -> bool:
        """Whether the loop should grab a fresh frame now (False while frozen)."""

    def freerun_done(self) -> bool:
        """Whether the operator has ended free-run (pressed Continue)."""

    def end_freerun(self) -> None:
        """Announce that free-run mode has ended (hide its controls)."""


class ConsoleReporter:
    """Reporter that prints to stdout. Handy for CLI runs and debugging."""

    def __init__(self) -> None:
        self.last_capture: tuple[Any, Any, float] | None = None
        self.rows: list[dict[str, Any]] = []

    def status(self, text: str) -> None:
        print(f"[status] {text}")

    def log(self, text: str) -> None:
        print(text)

    def capture(self, ch_a: Any, ch_b: Any, sample_rate: float) -> None:
        self.last_capture = (ch_a, ch_b, sample_rate)

    def result(self, row: dict[str, Any]) -> None:
        self.rows.append(row)


class AutoGate:
    """Non-interactive gate for headless runs: never retake, never wait.

    ``retake`` can be set to a fixed answer, or ``retake_once`` can be used in
    tests to exercise the retake path exactly once (returns ``True`` the first
    time it is asked, then ``False``).
    """

    def __init__(self, retake: bool = False, retake_once: bool = False) -> None:
        self._retake = retake
        self._retake_once = retake_once
        self._asked = 0

    def confirm(self, prompt: str) -> bool:
        self._asked += 1
        if self._retake_once:
            return self._asked == 1
        return self._retake

    def wait_continue(self, prompt: str) -> None:
        return None

    # free-run: grab exactly one frame (for debug) then end immediately
    def begin_freerun(self, prompt: str) -> None:
        return None

    def freerun_capture_due(self) -> bool:
        return True

    def freerun_done(self) -> bool:
        return True

    def end_freerun(self) -> None:
        return None


@dataclass
class MeasurementContext:
    """Everything a measurement function needs to run, injected by the caller."""

    device: Any  # a real dwfpy device or a MockDevice (duck-typed)
    settings: Any  # a settings dataclass (e.g. FilterSettings)
    report: Reporter
    gate: Gate
    should_cancel: Callable[[], bool] = field(default=lambda: False)
