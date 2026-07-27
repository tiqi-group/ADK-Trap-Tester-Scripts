"""PyInstaller entry point for the Trap Tester GUI.

PyInstaller needs a concrete script to freeze; this simply forwards to the
package's ``main`` (the same callable behind the ``trap-tester-gui`` console
script). Keep it dependency-free beyond the package itself.
"""

from __future__ import annotations

from trap_tester.gui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
