# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Development note:** substantial portions of this project — in particular the
> GUI, the refactor of the measurement/analysis/self-test scripts into a
> reusable engine, and the packaging setup — were developed with the assistance
> of [Claude Code](https://claude.com/claude-code) (Anthropic).

## [Unreleased]

### Changed
- **Layout / mapping schema v2** (`docs/layout-schema-v2.md`). Meaning that the
  parser used to infer is now declared in the data, which removes whole classes of
  special case rather than documenting them:
  - a pad declares its `class` (`signal` / `gnd` / `rf` / `loopback` /
    `sensor_heater` / `axialisation`) instead of the renderer recovering it by
    matching hex fill colours — which only worked for circles, so ion-trap RF rails
    (polygons) could never appear in a legend. Non-signal pads are ordinary slots
    now, not hand-coloured background circles, and `background` is chrome only.
  - `Slot.channel` is **gone**. It meant three incompatible things depending on
    which generator wrote the file (a mux signal, an invented counter, or a
    per-CSV net id). The canonical address is derived from `(connector, pin)` plus
    the layout's `pin_space`, so a DSUB pin and the ribbon conductor carrying its
    signal cannot drift out of agreement.
  - annotations key on `(connector, pin)` — the apparatus' own address — so a saved
    mark keeps its meaning when a different mapping CSV is loaded.
  - layouts declare a stable `slug` and `match_by`, so a mapping column is found by
    name instead of guessed from "which layout's idents does it overlap most?".
  - layout JSON contains no colours: a primitive names a `style`, resolved from one
    table at load.
  - pads with no recorded wiring get distinct addresses in a reserved synthetic
    band (connector 900+) instead of all colliding on `(0, 0)`; `is_synthetic()`
    drives a "placeholder wiring" banner. Applying a mapping replaces them.
  - the mapping CSV has canonical `connector`/`pin` headers and physical pins. The
    six tolerated connector spellings and the `pin % 100` connector-bank rule are
    gone from the parser and fixed in the data instead.
  - `coverage()` grew into a diff: which idents matched, which the CSV does not
    name, which the layout does not have, and which matched only ignoring case —
    surfaced in the Interfaces banner. It immediately showed that 82 of
    `interposer_BePe`'s 174 pads were silently unwired.
  - `key_by`'s closed enum is now an open `pin_space` string, so a new interface
    family needs no code change.
  The loader accepts schema 2 only; v1 layout and annotation files are rejected with
  a message pointing at the generator. The existing files were converted in place and
  the upgrade path removed — pre-1.0, a loader that speaks one format is worth more
  than back-compatibility with a shape nothing has shipped.
- Smaller executable bundles: the PyInstaller spec now drops Qt runtime pieces the
  app cannot reach (the virtual-keyboard plugin and the QtQml/QtQuick stack it was
  the only user of, the GTK platform theme and its libgtk-3, the PDF image-format
  plugin and QtPdf, and Qt's own UI translations) and strips symbols on Linux.
  The Linux bundle goes from 373 MB to 316 MB, and its release archive from
  144 MB to 127 MB.

### Added
- Cross-platform PySide6 GUI (`trap-tester-gui`) with six panels: Measurement,
  Analysis, Interfaces, Device Info, Self-Test, and Settings.
- Mock device / **Simulate** mode so the GUI runs with no Analog Discovery
  attached.
- Custom interface layouts (DSUB-50, FPC, interposer, bond-finger) with a
  cross-interface channel-mapping model, zoom/pan, and import/search-folder
  support.
- **Split view** toggle in the Interfaces panel: show two interfaces side by side
  in a draggable splitter, each with its own interface and connector selection.
  Both share one annotation set, so a channel marked on either appears
  immediately on the other — the cross-interface correlation is visible without
  switching. "Save view…" captures both panes when split.
- Light/dark theming with a live toggle in the Settings panel.
- Standalone executable build via PyInstaller (`trap-tester.spec` +
  `packaging/`); see the README.
- GitHub Actions workflow that builds, smoke-tests and publishes bundles for
  Linux x86_64, Windows x86_64 and macOS (Apple silicon and Intel). Pushing a
  `v*` tag creates a release with auto-generated notes and attaches all four
  archives to it; manual runs publish them as workflow artifacts instead.
- macOS app bundle (`dist/trap-tester.app`) from the PyInstaller spec, so the
  GUI is double-clickable there. It is not code-signed or notarised; see the
  README for the Gatekeeper note.
- `--smoke-test` flag on the GUI launcher: builds every panel once and exits
  with a status instead of entering the event loop, used to verify frozen
  bundles in CI.
- Banner that appears when the Digilent WaveForms runtime (`libdwf`) is not
  installed, distinguishing a missing runtime from an unplugged device and
  linking to the download page (a free Digilent account is required to
  download).

### Changed
- Refactored the measurement, analysis, and self-test scripts into a
  GUI-agnostic engine under `src/trap_tester/core/`.
- Switched dependency management to [uv](https://docs.astral.sh/uv/).
- Reorganized the repository: regression suites moved to `tests/`, legacy
  hardware/SPICE scripts moved to `scripts/hardware/`.
- Bumped the ruff target version to match `requires-python` (>= 3.11).

### Removed
- Erroneous `wavefront-sdk-python` dependency (VMware observability SDK, unused;
  it is unrelated to Digilent WaveForms) and its transitive dependencies.
- Legacy top-level `analysis/` scripts, superseded by `src/trap_tester/core/analysis/`.
