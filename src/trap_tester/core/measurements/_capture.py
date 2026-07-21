"""Cancel-aware, timeout-bounded scope acquisition for the triggered measurements.

The refactored measurements originally called ``scope.single(start=True)``,
which blocks the worker thread inside dwfpy's ``wait_for_status(DONE)`` until a
trigger arrives — so a run could neither time out nor be cancelled while the
scope waited for a trigger, and the trigger level/source were hardcoded.

These helpers instead:

* resolve the trigger channel/level/slope from the user's settings
  (:func:`resolve_trigger`), so the operator can force triggering on the voltage
  (Ch1) or current (Ch2) channel, or keep each measurement phase's default;
* arm the acquisition and poll ``read_status`` in a loop
  (:func:`triggered_capture`), returning ``"done" | "timeout" | "cancelled"`` so
  the caller can react instead of hanging;
* run the scope untriggered for a short window (:func:`free_run`) so a point
  that never triggers can be inspected on the live plot before it is skipped.

Kept hardware-agnostic: the dwfpy ``Status`` enum and the mock are matched by
name, so there is no dwfpy import here.
"""

from __future__ import annotations

import time
from typing import Any, Callable

# trigger-source setting -> forced scope channel (Ch1 voltage / Ch2 current)
_FORCED_CHANNEL = {"voltage": 0, "current": 1}
_POLL_S = 0.01  # status-poll interval while waiting for a trigger
_FREERUN_POLL_S = 0.05  # live-scope refresh / gate-poll interval in free-run


def _status_is_done(status: Any) -> bool:
    """True when a scope status (dwfpy ``Status`` enum or mock string) is DONE."""
    name = getattr(status, "name", None) or str(status)
    return name.upper() == "DONE"


def resolve_trigger(settings: Any) -> tuple[int, float, str]:
    """Edge-trigger ``(channel, level, slope)`` from the trigger settings.

    ``trigger_source`` selects the channel — ``"current"`` (Ch2, the default and
    the reliable edge for these measurements) or ``"voltage"`` (Ch1); the level
    and slope come from ``trigger_level`` / ``trigger_slope``. An unknown source
    falls back to the current channel.
    """
    source = getattr(settings, "trigger_source", "current")
    channel = _FORCED_CHANNEL.get(source, 1)  # default: current channel (Ch2)
    level = float(getattr(settings, "trigger_level", 0.4))
    slope = str(getattr(settings, "trigger_slope", "rising"))
    return channel, level, slope


def apply_trigger(
    scope: Any, channel: int, level: float, slope: str, *,
    mode: str = "normal", hysteresis: float = 0.0,
) -> None:
    scope.setup_edge_trigger(
        mode=mode, channel=channel, slope=slope, level=level, hysteresis=hysteresis
    )


def triggered_capture(
    scope: Any, ctx: Any, *, sample_rate: float, buffer_size: int, timeout: float
) -> str:
    """Arm a single acquisition and poll until it completes, times out or is cancelled.

    Returns ``"done"``, ``"timeout"`` or ``"cancelled"``. ``timeout <= 0`` waits
    indefinitely (but still cancellably). The current trigger configuration is
    used as-is (set it with :func:`apply_trigger` first).
    """
    # configure the acquisition without the blocking wait, then arm + start
    scope.single(sample_rate=sample_rate, buffer_size=buffer_size, configure=True, start=False)
    scope.configure(reconfigure=False, start=True)

    deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
    while True:
        if _status_is_done(scope.read_status(read_data=True)):
            return "done"
        if ctx.should_cancel():
            return "cancelled"
        if deadline is not None and time.monotonic() >= deadline:
            return "timeout"
        time.sleep(_POLL_S)


def _gate_call(gate: Any, name: str, default: Any) -> Any:
    """Call an optional free-run gate hook, tolerating gates that lack it."""
    fn = getattr(gate, name, None)
    return fn() if callable(fn) else default


def free_run(
    scope: Any, ctx: Any, *, sample_rate: float, buffer_size: int,
    publish: Callable[[], None], prompt: str = "", channel: int = 0, level: float = 0.0,
) -> tuple[Any, Any]:
    """Interactive untriggered *scope mode* for inspecting a non-triggering point.

    Runs the scope free-running (``auto`` trigger + tiny auto-timeout, so it
    fires regardless of the signal) and streams frames via ``publish`` until the
    operator ends the session (``gate.freerun_done()``) or the run is cancelled.
    While ``gate.freerun_capture_due()`` is False (the operator froze the view
    with "Single") no new frame is grabbed, so the plot holds. This never
    records anything for the point — the caller still skips it. Returns the last
    frame's raw ``(ch0, ch1)`` data.
    """
    prev_auto_timeout = None
    try:
        prev_auto_timeout = scope.trigger.auto_timeout  # normal mode == 0
        scope.setup_edge_trigger(mode="auto", channel=channel, slope="rising", level=level)
        scope.trigger.auto_timeout = 0.01
    except Exception:  # noqa: BLE001 - mock or a device without an auto-timeout knob
        pass

    gate = ctx.gate
    begin = getattr(gate, "begin_freerun", None)
    if callable(begin):
        begin(prompt)

    last: tuple[Any, Any] = (None, None)
    try:
        while True:
            if _gate_call(gate, "freerun_capture_due", True):
                scope.single(
                    sample_rate=sample_rate, buffer_size=buffer_size,
                    configure=True, start=True,
                )
                last = (scope[0].get_data(), scope[1].get_data())
                publish()
            if _gate_call(gate, "freerun_done", True) or ctx.should_cancel():
                break
            time.sleep(_FREERUN_POLL_S)
    finally:
        end = getattr(gate, "end_freerun", None)
        if callable(end):
            end()
        # Leave the scope in normal (non-auto) trigger mode so a caller that
        # forgets to re-arm doesn't silently auto-fire on untriggered data.
        if prev_auto_timeout is not None:
            try:
                scope.trigger.auto_timeout = prev_auto_timeout
            except Exception:  # noqa: BLE001
                pass
    return last
