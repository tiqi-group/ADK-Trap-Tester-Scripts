# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the Trap Tester GUI.

Build (onedir) with the packaging deps installed::

    uv sync --group packaging
    uv run pyinstaller trap-tester.spec

Output: ``dist/trap-tester/`` (a self-contained folder; the launcher is
``dist/trap-tester/trap-tester``, ``trap-tester.exe`` on Windows).  Archive that
folder to distribute.  On macOS an app bundle ``dist/trap-tester.app`` is built
from the same collection as well — that is the artifact to ship there.

PyInstaller does NOT cross-compile: run this on each target OS to get that
OS's binary, and on the target CPU architecture (an Apple-silicon build is not
an Intel build).

Note on hardware: real Analog Discovery access needs Digilent's WaveForms
runtime (``libdwf``) installed on the target machine — it is a native,
separately-licensed library that is intentionally NOT bundled.  Without it the
app still launches and runs in Simulate (mock) mode.
"""

import sys
import tomllib
from pathlib import Path

# ``__file__`` is not defined while PyInstaller execs a spec; the CWD is the
# spec's directory (where pyinstaller was invoked with this spec).
ROOT = Path.cwd()
SRC = ROOT / "src"

# Single source of truth for the version shown in the macOS bundle's Info.plist.
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

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

# ---------------------------------------------------------------------------
# Trimming.  ``excludes`` above only drops Python *modules*; PySide6's hook still
# collects the whole Qt runtime — shared libraries, plugins and translations —
# regardless of which Python bindings survive.  Those have to be filtered out of
# the collected TOCs by name.
#
# Every entry below was checked with ``readelf -d`` to confirm that nothing we
# keep links against it, so this removes dead weight rather than gambling.  The
# per-platform ``--smoke-test`` in CI is the backstop: a genuinely-needed library
# removed here makes the frozen launcher fail to start on that platform.
#
# Matching is on a path fragment of the destination name, deliberately without the
# ``lib``/``.so``/``.dll`` decoration so one pattern covers all three platforms.

# Plugins the app never loads.  The virtual keyboard is the ONLY user of the
# QtQml/QtQuick stack and the GTK platform theme the ONLY user of libgtk-3, so
# dropping these two plugins is what lets those libraries go as well.
_DROP_PLUGINS = (
    "qtvirtualkeyboardplugin",  # on-screen keyboard; drags in QtQml + QtQuick
    "qgtk3",  # GTK platform theme; drags in libgtk-3 (~8 MB)
    "imageformats/libqpdf",  # reads PDF as an image format
    "imageformats/qpdf",
)

# Qt libraries left unreachable once those plugins are gone.
_DROP_LIBS = (
    "Qt6Qml",
    "Qt6Quick",
    "Qt6VirtualKeyboard",
    "Qt6Pdf",
    "libgtk-3",
)
# NOTE: the ICU libraries look like the obvious next win (~35 MB, of which
# libicudata alone is 30 MB) but they are a hard NEEDED entry of libQt6Core —
# removing them stops the app loading at all.  Do not try it.

_DROP_DATA = (
    "PySide6/Qt/translations/",  # Qt's own UI translations; this app is English-only
)


def _keep(entry, patterns):
    dest = str(entry[0]).replace("\\", "/")
    return not any(p in dest for p in patterns)


# Both TOCs get the full pattern set. This is not belt-and-braces: PyInstaller puts
# the *shared libraries* in ``binaries`` but the top-level SYMLINKs that make their
# bare ELF NEEDED names resolve (``libQt6Qml.so.6`` -> ``PySide6/Qt/lib/...``) in
# ``datas``. Filtering only ``binaries`` reclaims the space but leaves the symlinks
# behind, dangling.
_DROP_ALL = _DROP_PLUGINS + _DROP_LIBS + _DROP_DATA
a.binaries = [e for e in a.binaries if _keep(e, _DROP_ALL)]
a.datas = [e for e in a.datas if _keep(e, _DROP_ALL)]

# Strip symbol tables from the bundled binaries.  Skipped off Linux: on macOS
# stripping breaks code signatures (and Apple's strip rejects some Mach-O files),
# and it buys nothing on Windows.
_STRIP = sys.platform == "linux"

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="trap-tester",
    debug=False,
    bootloader_ignore_signals=False,
    strip=_STRIP,
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
    strip=_STRIP,
    upx=False,
    upx_exclude=[],
    name="trap-tester",
)

# macOS: wrap the collected folder in a double-clickable .app.  BUNDLE is a
# no-op on other platforms, but guard it anyway so the Linux/Windows builds are
# unmistakably unaffected.  The bundle is NOT code-signed or notarised, so a
# downloaded copy is quarantined by Gatekeeper until the user clears it with
# ``xattr -dr com.apple.quarantine trap-tester.app``.
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821  (injected into the spec namespace by PyInstaller)
        coll,
        name="trap-tester.app",
        icon=None,
        bundle_identifier="ch.ethz.tiqi.trap-tester",
        version=VERSION,
    )
