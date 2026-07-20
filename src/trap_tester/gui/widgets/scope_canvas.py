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


class _MplCanvas(FigureCanvasQTAgg):
    def __init__(self, height: float = 2.2) -> None:
        self.fig = Figure(figsize=(4, height), layout="constrained")
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)


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

    def _init_axes(self) -> None:
        for canvas, ch, spec in (
            (self.canvas_ch1, "Ch1", self._spec_a),
            (self.canvas_ch2, "Ch2", self._spec_b),
        ):
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
        self._draw(self.canvas_ch2, "Ch2", self._spec_b, t_ms, ch_b)

    @staticmethod
    def _draw(canvas: _MplCanvas, ch: str, spec: ChannelSpec, t_ms: np.ndarray, raw: np.ndarray) -> None:
        data = raw * spec.scale
        settled = float(np.mean(data[-100:])) if data.size >= 100 else float(np.mean(data))
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        canvas.ax.clear()
        canvas.ax.plot(t_ms, data, color=spec.color, lw=0.8)
        canvas.ax.set(xlabel="Time [ms]", ylabel=f"{spec.name} [{spec.unit}]")
        canvas.ax.set_title(
            f"{ch} · {spec.name} (auto-detect): settled {settled:.3f} {spec.unit}, "
            f"peak {peak:.3f} {spec.unit}",
            **_TITLE_KW,
        )
        canvas.ax.grid(True, alpha=0.3)
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
        ax.legend(fontsize=6, loc="upper right")
        self.canvas.draw_idle()
