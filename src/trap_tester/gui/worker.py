"""Bridge between the (background) measurement loop and the (main) UI thread.

* :class:`QtReporter` turns ``Reporter`` calls made on the worker thread into
  Qt signals that Qt delivers, queued, on the UI thread.
* :class:`QtGate` implements the interactive gate: its ``confirm`` /
  ``wait_continue`` run on the worker thread and block on a ``threading.Event``
  after emitting a request signal; the UI resolves them from the main thread.
* :class:`MeasurementWorker` (a ``QThread``) opens the device and runs the
  measurement, staying off the UI thread so the window never freezes.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from trap_tester.core.device import open_device
from trap_tester.core.reporter import MeasurementContext


class QtReporter(QObject):
    statusChanged = Signal(str)
    logLine = Signal(str)
    captured = Signal(object, object, float)
    resulted = Signal(dict)

    def status(self, text: str) -> None:
        self.statusChanged.emit(text)

    def log(self, text: str) -> None:
        self.logLine.emit(text)

    def capture(self, ch_a: Any, ch_b: Any, sample_rate: float) -> None:
        self.captured.emit(ch_a, ch_b, float(sample_rate))

    def result(self, row: dict[str, Any]) -> None:
        self.resulted.emit(dict(row))


class QtGate(QObject):
    confirmRequested = Signal(str)
    continueRequested = Signal(str)
    freerunRequested = Signal(str)  # enter live free-run (scope) mode
    freerunEnded = Signal()  # leave free-run mode (hide its controls)

    def __init__(self) -> None:
        super().__init__()
        self._event = threading.Event()
        self._answer = False
        # free-run session state (polled by the worker, set from the UI thread)
        self._freerun_done = threading.Event()
        self._freerun_frozen = False
        self._freerun_grab = False

    # ---- called on the WORKER thread (block until UI resolves) -------------
    def confirm(self, prompt: str) -> bool:
        self._event.clear()
        self._answer = False
        self.confirmRequested.emit(prompt)
        self._event.wait()
        return self._answer

    def wait_continue(self, prompt: str) -> None:
        self._event.clear()
        self.continueRequested.emit(prompt)
        self._event.wait()

    # ---- free-run: called on the WORKER thread (non-blocking, polled) ------
    def begin_freerun(self, prompt: str) -> None:
        self._freerun_done.clear()
        self._freerun_frozen = False
        self._freerun_grab = False
        self.freerunRequested.emit(prompt)

    def freerun_capture_due(self) -> bool:
        if not self._freerun_frozen:
            return True
        if self._freerun_grab:  # a fresh frame was just requested via "Single"
            self._freerun_grab = False
            return True
        return False

    def freerun_done(self) -> bool:
        return self._freerun_done.is_set()

    def end_freerun(self) -> None:
        self.freerunEnded.emit()

    # ---- called on the UI thread ------------------------------------------
    def resolve_confirm(self, retake: bool) -> None:
        self._answer = bool(retake)
        self._event.set()

    def resolve_continue(self) -> None:
        self._event.set()

    def freerun_toggle_freeze(self) -> None:
        """'Single': freeze on a fresh frame, or resume live if already frozen."""
        if self._freerun_frozen:
            self._freerun_frozen = False
        else:
            self._freerun_frozen = True
            self._freerun_grab = True

    def freerun_continue(self) -> None:
        """End free-run (the point will be skipped)."""
        self._freerun_done.set()

    def unblock(self) -> None:
        """Release any waiter (used on cancel/shutdown)."""
        self._answer = False
        self._event.set()
        self._freerun_done.set()


class MeasurementWorker(QThread):
    measurementDone = Signal(object)  # pandas.DataFrame
    measurementFailed = Signal(str)

    def __init__(
        self,
        run_fn: Callable[[MeasurementContext], Any],
        settings: Any,
        reporter: QtReporter,
        gate: QtGate,
        force_mock: bool,
        serial: str | None = None,
    ) -> None:
        super().__init__()
        self._run_fn = run_fn
        self._settings = settings
        self._reporter = reporter
        self._gate = gate
        self._force_mock = force_mock
        self._serial = serial
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True
        self._gate.unblock()  # release the gate if it is waiting

    def run(self) -> None:  # executes on the worker thread
        try:
            with open_device(serial=self._serial, force_mock=self._force_mock) as device:
                ctx = MeasurementContext(
                    device=device,
                    settings=self._settings,
                    report=self._reporter,
                    gate=self._gate,
                    should_cancel=lambda: self._cancel,
                )
                df = self._run_fn(ctx)
            self.measurementDone.emit(df)
        except Exception:  # noqa: BLE001 - surface any failure to the UI
            self.measurementFailed.emit(traceback.format_exc())
