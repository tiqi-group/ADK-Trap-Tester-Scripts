# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the Trap Tester GUI.

Build (onedir) with the packaging deps installed::

    uv sync --group packaging
    uv run pyinstaller trap-tester.spec

Output: ``dist/trap-tester/`` (a self-contained folder; the launcher is
``dist/trap-tester/trap-tester``).  Zip that folder to distribute.

PyInstaller does NOT cross-compile: run this on each target OS to get that
OS's binary (Linux here, macOS -> .app, Windows -> .exe).

Note on hardware: real Analog Discovery access needs Digilent's WaveForms
runtime (``libdwf``) installed on the target machine — it is a native,
separately-licensed library that is intentionally NOT bundled.  Without it the
app still launches and runs in Simulate (mock) mode.
"""

from pathlib import Path

# ``__file__`` is not defined while PyInstaller execs a spec; the CWD is the
# spec's directory (where pyinstaller was invoked with this spec).
ROOT = Path.cwd()
SRC = ROOT / "src"

# Data files loaded at runtime via ``Path(__file__).with_name(...)``. They must
# land at the same package-relative path inside the bundle so those lookups
# resolve.  matplotlib's own data (fonts, mpl-data) and the Qt plugins are
# collected automatically by PyInstaller's bundled hooks.
datas = [
    (str(SRC / "trap_tester/core/layout/layouts/dsub50.json"),
     "trap_tester/core/layout/layouts"),
    (str(SRC / "trap_tester/core/layout/layouts/fpc.json"),
     "trap_tester/core/layout/layouts"),
    (str(SRC / "trap_tester/gui/style.qss"),
     "trap_tester/gui"),
]

# The QtAgg canvas backend is imported directly in code, but list it explicitly
# so a future refactor to a lazy import can't silently drop it.
hiddenimports = [
    "matplotlib.backends.backend_qtagg",
]

# Large, clearly-unused stacks — trimming keeps the bundle lean and the build
# fast.  QtCore/QtGui/QtWidgets (what QtAgg needs) are never excluded.
excludes = [
    "tkinter",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTextToSpeech",
]

a = Analysis(
    [str(ROOT / "packaging" / "trap_tester_app.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="trap-tester",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no terminal window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="trap-tester",
)
