"""Entry point: ``python -m trap_tester.gui``."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from trap_tester.core.appconfig import theme as configured_theme
from trap_tester.gui import theme
from trap_tester.gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Trap Tester")

    theme.apply(app, configured_theme())  # stylesheet + matplotlib, from config

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
