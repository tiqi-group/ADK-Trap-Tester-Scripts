"""Matplotlib-backed viewers: live scope captures and a waveform preview."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from trap_tester.utils import R_SENSE, SENSE_MAG

_TITLE_KW = dict(fontsize=10, fontweight="bold", color="#b83a20")


class _MplCanvas(FigureCanvasQTAgg):
    def __init__(self, height: float = 2.2) -> None:
        self.fig = Figure(figsize=(4, height), layout="constrained")
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)


class ScopeCanvas(QWidget):
    """Two stacked plots (scope[0] voltage, scope[1] current).

    Mirrors the mock's Ch1/Ch2 "Capture" + "Measurement (auto-detect)" regions;
    the auto-detected summary is shown as each plot's title rather than a box,
    leaving the plot area as large as possible.
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
        self._init_axes()

    def _init_axes(self) -> None:
        for canvas, title, ylabel in (
            (self.canvas_ch1, "Ch1 · Voltage (auto-detect): —", "Voltage [V]"),
            (self.canvas_ch2, "Ch2 · Current (auto-detect): —", "Current [mA]"),
        ):
            canvas.ax.set_title(title, **_TITLE_KW)
            canvas.ax.set_xlabel("Time [ms]")
            canvas.ax.set_ylabel(ylabel)
            canvas.ax.grid(True, alpha=0.3)
            canvas.draw_idle()

    def update_capture(self, ch_a: np.ndarray, ch_b: np.ndarray, sample_rate: float) -> None:
        ch_a = np.asarray(ch_a, dtype=float)
        ch_b = np.asarray(ch_b, dtype=float)
        t_ms = np.arange(ch_a.size) / sample_rate * 1e3
        current = ch_b / (R_SENSE * SENSE_MAG)  # A

        v_end = float(np.mean(ch_a[-100:])) if ch_a.size >= 100 else float(np.mean(ch_a))
        i_peak = float(np.max(current))
        i_end = float(np.mean(current[-100:])) if current.size >= 100 else float(np.mean(current))

        self.canvas_ch1.ax.clear()
        self.canvas_ch1.ax.plot(t_ms, ch_a, color="#1f77b4", lw=0.8)
        self.canvas_ch1.ax.set(xlabel="Time [ms]", ylabel="Voltage [V]")
        self.canvas_ch1.ax.set_title(
            f"Ch1 · Voltage (auto-detect): settled {v_end:.3f} V", **_TITLE_KW
        )
        self.canvas_ch1.ax.grid(True, alpha=0.3)
        self.canvas_ch1.draw_idle()

        self.canvas_ch2.ax.clear()
        self.canvas_ch2.ax.plot(t_ms, current * 1e3, color="#d62728", lw=0.8)
        self.canvas_ch2.ax.set(xlabel="Time [ms]", ylabel="Current [mA]")
        self.canvas_ch2.ax.set_title(
            f"Ch2 · Current (auto-detect): peak {i_peak * 1e3:.3f} mA, "
            f"end {i_end * 1e6:.1f} µA",
            **_TITLE_KW,
        )
        self.canvas_ch2.ax.grid(True, alpha=0.3)
        self.canvas_ch2.draw_idle()


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
