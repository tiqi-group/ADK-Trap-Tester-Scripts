"""Info banner shown when the Digilent WaveForms runtime (``libdwf``) is absent.

Purely informational — the app still works in Simulate mode. It tells the user
that hardware is unavailable *because the runtime is missing* (as opposed to no
device being plugged in) and links to the download page, noting that a free
Digilent account is required to download it.

Embed one in any panel that selects a device and call :meth:`refresh` whenever
the device list is (re)populated; it shows itself only when the runtime cannot
be loaded. The banner uses the shared ``role="warning"`` QSS style, so it
re-themes automatically on a light/dark switch.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from trap_tester.core.device import waveforms_runtime_available

WAVEFORMS_URL = "https://digilent.com/reference/software/waveforms/waveforms-3/start"

_MESSAGE = (
    "⚠ <b>WaveForms runtime not found.</b> Hardware is unavailable — the app is "
    "running in <b>Simulate</b> mode. To use a real Analog Discovery, install "
    "Digilent's free WaveForms software from "
    f'<a href="{WAVEFORMS_URL}">digilent.com</a>, then reconnect and refresh. '
    "Downloading it requires a free Digilent account."
)


class WaveformsBanner(QLabel):
    """A warning strip that is visible only when the WaveForms runtime is missing."""

    def __init__(self) -> None:
        super().__init__(_MESSAGE)
        self.setProperty("role", "warning")
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True)
        self.setOpenExternalLinks(True)
        self.setVisible(False)
        self.refresh()

    def refresh(self) -> None:
        """Re-check the runtime and show the banner only when it is unavailable."""
        self.setVisible(not waveforms_runtime_available())
