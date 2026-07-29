"""Entry point: ``python -m trap_tester.gui``."""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtWidgets import QApplication

from trap_tester.core.appconfig import theme as configured_theme
from trap_tester.core.appconfig import ui_scale as configured_ui_scale
from trap_tester.gui import theme
from trap_tester.gui.main_window import MainWindow

_SMOKE_FLAG = "--smoke-test"


def _apply_ui_scale() -> None:
    """Apply the configured UI scale — must run before the ``QApplication`` exists.

    Qt fixes its scale factor when the application is constructed, which is why the
    Settings tab says the choice takes effect on restart. Going through Qt's own
    scaling (rather than resizing fonts and widgets ourselves) means *everything*
    grows together, including the matplotlib canvases and Qt's built-in widget
    metrics like scrollbar widths.

    An explicit ``QT_SCALE_FACTOR`` in the environment wins, so a one-off
    ``QT_SCALE_FACTOR=2 trap-tester-gui`` still overrides the setting.
    """
    if os.environ.get("QT_SCALE_FACTOR"):
        return
    scale = configured_ui_scale()
    if scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(scale)


def main() -> int:
    argv = [a for a in sys.argv if a != _SMOKE_FLAG]
    smoke = _SMOKE_FLAG in sys.argv

    _apply_ui_scale()
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
