"""Entry point: ``python -m trap_tester.gui``."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication

from trap_tester.core.appconfig import theme as configured_theme
from trap_tester.gui import theme
from trap_tester.gui.main_window import MainWindow

_SMOKE_FLAG = "--smoke-test"


def main() -> int:
    argv = [a for a in sys.argv if a != _SMOKE_FLAG]
    smoke = _SMOKE_FLAG in sys.argv

    app = QApplication(argv)
    app.setApplicationName("Trap Tester")

    theme.apply(app, configured_theme())  # stylesheet + matplotlib, from config

    if smoke:
        return _smoke_test(app)

    window = MainWindow()
    window.show()
    return app.exec()


def _log(message: str) -> None:
    """Print without assuming there is a stream: a windowed (``console=False``)
    build has ``sys.stdout is None`` unless its parent redirected it."""
    stream = sys.stdout or sys.stderr
    if stream is not None:
        print(message, file=stream)


def _smoke_test(app: QApplication) -> int:
    """Build the whole UI once, then exit — no event loop.

    Used to verify a frozen (PyInstaller) bundle on a CI runner: it exercises
    every panel, the stylesheet and the bundled data files, and reports the
    result through the exit code instead of hanging in ``app.exec()``.
    Exceptions are caught here on purpose: an unhandled one would pop a
    traceback dialog in a windowed build and block the runner until it times
    out, hiding the failure.
    """
    try:
        window = MainWindow()
        window.show()
        for _ in range(5):  # let deferred/rebuilt widgets settle
            app.processEvents()
        window.close()
    except Exception:
        stream = sys.stderr or sys.stdout
        if stream is not None:
            traceback.print_exc(file=stream)
        _log("smoke test FAILED")
        return 1

    _log("smoke test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
