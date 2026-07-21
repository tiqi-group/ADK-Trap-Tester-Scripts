"""Matplotlib-backed viewers: live scope captures and a waveform preview."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from trap_tester.utils import R_SENSE, SENSE_MAG

_TITLE_KW = dict(fontsize=10, fontweight="bold", color="#b83a20")
_CURRENT_MA_PER_RAW = 1e3 / (R_SENSE * SENSE_MAG)  # raw sense volts -> mA


@dataclass(frozen=True)
class ChannelSpec:
    """How to display one scope channel for a given measurement."""

    name: str  # short channel name, e.g. "Voltage" / "Current"
    unit: str  # display unit, e.g. "V" / "mA"
    scale: float  # display value = raw * scale
    color: str


_VOLT_A = ChannelSpec("Voltage", "V", 1.0, "#1f77b4")
_VOLT_B = ChannelSpec("Measured V", "V", 1.0, "#d62728")
_CURRENT = ChannelSpec("Current", "mA", _CURRENT_MA_PER_RAW, "#d62728")

# per-measurement channel semantics (scope[0], scope[1])
CHANNELS: dict[str, tuple[ChannelSpec, ChannelSpec]] = {
    "measure_filter": (_VOLT_A, _CURRENT),
    "measure_resistance": (_VOLT_A, _CURRENT),
    "measure_voltage": (ChannelSpec("DAC-MUX V", "V", 1.0, "#1f77b4"), _VOLT_B),
}


def channels_for(measurement: str | None) -> tuple[ChannelSpec, ChannelSpec]:
    """Channel specs for a measurement key (filter's voltage/current default)."""
    return CHANNELS.get(measurement or "", CHANNELS["measure_filter"])


_NICE_STEPS = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)


def _nice_ceil(x: float) -> float:
    """Smallest 'nice' number >= x (1/2/3/4/5/6/8 × 10ⁿ). 0 for x <= 0."""
    if x <= 0:
        return 0.0
    exp = np.floor(np.log10(x))
    base = 10.0**exp
    mantissa = x / base
    for step in _NICE_STEPS:
        if mantissa <= step + 1e-9:
            return step * base
    return 10.0 * base


def _grow_range(
    prev: tuple[float, float] | None, data: np.ndarray
) -> tuple[float, float]:
    """Expand ``prev`` (min, max) to also cover ``data``."""
    lo = float(np.min(data)) if data.size else 0.0
    hi = float(np.max(data)) if data.size else 0.0
    if prev is not None:
        lo = min(lo, prev[0])
        hi = max(hi, prev[1])
    return (lo, hi)


def _round_ylim(lo: float, hi: float) -> tuple[float, float]:
    """Round a (min, max) range outward to nice y-limits."""
    ylo = 0.0 if lo >= 0 else -_nice_ceil(-lo)
    yhi = 0.0 if hi <= 0 else _nice_ceil(hi)
    if yhi <= ylo:  # flat / all-zero signal
        yhi = ylo + 1.0
    return ylo, yhi


def _sticky_ylim(canvas: "_MplCanvas", data: np.ndarray) -> tuple[float, float]:
    """Grow-only y-limits: track the running data range and round it outward.

    The limits only ever expand to the largest magnitude seen so far (rounded up
    to a nice number), so the plot never rescales shot-to-shot.
    """
    canvas._data_range = _grow_range(canvas._data_range, data)
    return _round_ylim(*canvas._data_range)


def _clear_twin(canvas: "_MplCanvas") -> None:
    """Drop any right-hand secondary axis and its running range."""
    if canvas.ax_r is not None:
        canvas.ax_r.remove()
        canvas.ax_r = None
    canvas._data_range_r = None


class _MplCanvas(FigureCanvasQTAgg):
    def __init__(self, height: float = 2.2) -> None:
        self.fig = Figure(figsize=(4, height), layout="constrained")
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        # running (min, max) of every sample shown, so the y-axis only ever
        # grows and the plot doesn't rescale shot-to-shot. Reset per measurement.
        self._data_range: tuple[float, float] | None = None
        # optional right-hand (twin) axis for a secondary trace + its own range.
        self.ax_r = None
        self._data_range_r: tuple[float, float] | None = None


class ScopeCanvas(QWidget):
    """Two stacked plots for scope[0] and scope[1].

    Measurement-aware: :meth:`set_channels` configures what each channel means
    (label, unit, scale) so e.g. the current channel shows mA for the filter /
    resistance measurements but a plain voltage for the voltage meter. The
    auto-detected summary is the plot title, keeping the plot area large.
    """

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas_ch1 = _MplCanvas()
        self.canvas_ch1.setProperty("role", "viewer")
        self.canvas_ch2 = _MplCanvas()
        self.canvas_ch2.setProperty("role", "viewer")

        layout.addWidget(self.canvas_ch1, 1)
        layout.addWidget(self.canvas_ch2, 1)

        self._spec_a, self._spec_b = CHANNELS["measure_filter"]
        self._init_axes()

    def set_channels(self, spec_a: ChannelSpec, spec_b: ChannelSpec) -> None:
        """Set the channel semantics for the current measurement and redraw axes."""
        self._spec_a, self._spec_b = spec_a, spec_b
        self._init_axes()

    def show_message(self, text: str) -> None:
        """Clear both plots and show a single message (e.g. when idle)."""
        for canvas in (self.canvas_ch1, self.canvas_ch2):
            canvas._data_range = None
            _clear_twin(canvas)
            canvas.ax.clear()
            canvas.ax.set_title(text, **_TITLE_KW)
            canvas.ax.set_xticks([])
            canvas.ax.set_yticks([])
            canvas.draw_idle()

    def _init_axes(self) -> None:
        for canvas, ch, spec in (
            (self.canvas_ch1, "Ch1", self._spec_a),
            (self.canvas_ch2, "Ch2", self._spec_b),
        ):
            canvas._data_range = None  # start a fresh y-scale for the new run
            _clear_twin(canvas)
            canvas.ax.clear()
            canvas.ax.set_title(f"{ch} · {spec.name} (auto-detect): —", **_TITLE_KW)
            canvas.ax.set_xlabel("Time [ms]")
            canvas.ax.set_ylabel(f"{spec.name} [{spec.unit}]")
            canvas.ax.grid(True, alpha=0.3)
            canvas.draw_idle()

    def update_capture(self, ch_a: np.ndarray, ch_b: np.ndarray, sample_rate: float) -> None:
        ch_a = np.asarray(ch_a, dtype=float)
        ch_b = np.asarray(ch_b, dtype=float)
        t_ms = np.arange(ch_a.size) / sample_rate * 1e3
        self._draw(self.canvas_ch1, "Ch1", self._spec_a, t_ms, ch_a)
        # For current measurements (Ch2 in mA), overlay the measured voltage
        # (Ch1's signal) on a secondary right-hand y-axis, time-aligned.
        overlay = self._spec_a if self._spec_b.unit == "mA" else None
        self._draw(self.canvas_ch2, "Ch2", self._spec_b, t_ms, ch_b,
                   overlay_spec=overlay, overlay_raw=ch_a)

    @staticmethod
    def _draw(
        canvas: _MplCanvas, ch: str, spec: ChannelSpec, t_ms: np.ndarray, raw: np.ndarray,
        overlay_spec: ChannelSpec | None = None, overlay_raw: np.ndarray | None = None,
    ) -> None:
        data = raw * spec.scale
        settled = float(np.mean(data[-100:])) if data.size >= 100 else float(np.mean(data))
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        canvas.ax.clear()
        main_line, = canvas.ax.plot(
            t_ms, data, color=spec.color, lw=0.8, zorder=2,
            label=f"{spec.name} [{spec.unit}]")
        canvas.ax.set_xlabel("Time [ms]")
        canvas.ax.set_ylim(*_sticky_ylim(canvas, data))
        canvas.ax.set_title(
            f"{ch} · {spec.name} (auto-detect): settled {settled:.3f} {spec.unit}, "
            f"peak {peak:.3f} {spec.unit}",
            **_TITLE_KW,
        )
        canvas.ax.grid(True, alpha=0.3)

        if overlay_spec is not None and overlay_raw is not None:
            # colour the left axis to match its trace, since the right axis
            # carries a second signal in its own colour.
            canvas.ax.set_ylabel(f"{spec.name} [{spec.unit}]", color=spec.color)
            canvas.ax.tick_params(axis="y", colors=spec.color)
            if canvas.ax_r is None:
                canvas.ax_r = canvas.ax.twinx()
            odata = np.asarray(overlay_raw, dtype=float) * overlay_spec.scale
            canvas.ax_r.clear()
            # the twin sits on top (default draw order); make its background
            # transparent (after clear(), which resets the patch) so the solid
            # current trace shows through the overlay.
            canvas.ax_r.patch.set_visible(False)
            # dashed + on top: where it coincides with the current trace the red
            # line shows through the gaps, so both remain visible.
            ov_line, = canvas.ax_r.plot(
                t_ms, odata, color=overlay_spec.color, lw=1.0, ls="--", zorder=3,
                label=f"{overlay_spec.name} [{overlay_spec.unit}]")
            canvas.ax_r.set_ylabel(
                f"{overlay_spec.name} [{overlay_spec.unit}]", color=overlay_spec.color)
            canvas.ax_r.tick_params(axis="y", colors=overlay_spec.color)
            canvas._data_range_r = _grow_range(canvas._data_range_r, odata)
            canvas.ax_r.set_ylim(*_round_ylim(*canvas._data_range_r))
            # one combined legend for both traces, on the top (twin) axis so it
            # is not painted over by the overlay line.
            canvas.ax_r.legend(handles=[main_line, ov_line], fontsize=6,
                               loc="upper center", ncol=2, framealpha=0.9)
        else:
            canvas.ax.set_ylabel(f"{spec.name} [{spec.unit}]")
        canvas.draw_idle()


class WaveformPreview(QWidget):
    """Small preview of the excitation square wave + trigger level."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = _MplCanvas(height=1.6)
        self.canvas.setProperty("role", "viewer")
        layout.addWidget(self.canvas)

    def update_preview(self, f_square: float, amplitude: float, gain: float = 2.0) -> None:
        ax = self.canvas.ax
        ax.clear()
        periods = 3.0
        n = 2000
        t = np.linspace(0, periods / max(f_square, 1e-9), n)
        # generator output; frontend applies ``gain`` -> applied V_IN
        offset = 0.5 * amplitude / gain
        amp = 0.5 * amplitude / gain
        wave = gain * (offset + amp * np.sign(np.sin(2 * np.pi * f_square * t)))
        ax.plot(t * 1e3, wave, color="#1f77b4", lw=1.0, label="V_IN applied")
        ax.axhline(0.4, color="#d62728", ls="--", lw=0.8, label="trigger 0.4 V")
        ax.set(xlabel="Time [ms]", ylabel="V")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=6, loc="center left", bbox_to_anchor=(1.02, 0.5))
        self.canvas.draw_idle()
