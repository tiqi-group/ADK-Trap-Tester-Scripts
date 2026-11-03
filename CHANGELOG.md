# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Development note:** substantial portions of this project — in particular the
> GUI, the refactor of the measurement/analysis/self-test scripts into a
> reusable engine, and the packaging setup — were developed with the assistance
> of [Claude Code](https://claude.com/claude-code) (Anthropic).

## [Unreleased]

### Added
- **Manual panel.** A new *Manual* tab shows the documentation inside the app:
  a contents tree of every chapter and its headings on the left (with Back /
  Forward), the rendered chapter on the right. Equations are typeset (matplotlib
  mathtext, in the theme's colours), `#heading` links and links between chapters
  work, web links open in the system browser, and figures shrink to fit.
  Chapters: Getting started, one per panel (Measurement, Analysis, Interfaces,
  Device Info, Self-Test, Settings), and Custom layouts and mappings, which
  documents the schema-v2 layout JSON and mapping CSV. The last chapter is the
  Analog Frontend README and its figures, vendored into
  `src/trap_tester/manual/frontend/` by the new `scripts/sync_frontend_docs.py`
  (manufacturing notes left out, links back to this repository pointed at the
  manual; `SOURCE.json` pins the source commit) and shipped with the frozen
  bundle. `--smoke-test` now renders every chapter.
- **Manual search and F1 help.** A search field above the contents searches every
  chapter (Ctrl+F; Enter / F3 next, Shift+Enter / Shift+F3 previous, Esc clears),
  continuing into the following chapters and highlighting every match in the
  open one. F1, or the **? Help** button at the right end of the top bar, opens
  the current panel's chapter. Code blocks and the
  manual's warnings are drawn as framed boxes in theme colours, and inline code
  gets a background, in both light and dark mode.

### Fixed
- **DC-resistance estimate counted the sense resistor twice.** The frontend drives
  a pin through 10 kΩ current limiting + 470 Ω sense = 10 470 Ω, but the code
  called that total `R_REF` and the resistance measurement (and the simulated
  device) added `R_SENSE` again, using 10 940 Ω. The current estimate read about
  470 Ω low, so any fault below ~480 Ω came out as 0 Ω, a dead short, and the
  voltage-divider estimate read 4.5 % high. The constants are now `R_REF`
  (10 kΩ), `R_SENSE` (470 Ω) and `R_SOURCE = R_REF + R_SENSE`, which every
  formula uses. The filter measurement already used 10 470 Ω and is unchanged.

### Changed
- **Voltage meter acceptance window defaults to 0 … 5 V** (was −10 … 10 V,
  which flagged nothing): the frontend's input range, outside which a voltage
  permanently damages the tester. Saved presets keep their own window. The
  simulated device's voltages now stay inside that range too.
- **README.** The user-facing sections (measurements, analysis, loopback mode,
  custom layouts) moved into the manual; the README links to it. The layout
  section it replaced still described the v1 format. The clone URL and the
  Analog Frontend link now point at the GitHub repositories.

## [0.4.0] - 2026-10-24

### Added
- **Analysis modes.** A measurement can now be analysed more than one way; a
  **Mode** selector appears in the Analysis panel when there is a choice. Presets
  record their mode (`"analysis"`; a preset without one belongs to the default
  mode) and the preset list shows only the selected mode's presets. A report saved
  from a non-default mode carries the mode in its file name.
- **Loopback mode for `measure_filter`**, for testing an interface fitted with a
  loopback PCB that joins its pads in groups (mostly pairs) and grounds some: a
  pin in a group of *n* should read ~*n*× the nominal filter C, an ungrouped pin
  ~1×, and a grounded pad should read shorted, which then counts as a pass
  (*Shorted (expected)*). The nominal defaults to 1.4 nF — one 1 nF filter plus
  the FPC, as the original interposer analysis assumed. Verdicts *Loop open*,
  *Extra short* and *Group mismatch* (the pins of a group disagree) join the
  existing ones. The board is a `loopback`
  JSON naming its pads, placed on tester pins through the selected mapping, so one
  board file serves every cabling; pads the mapping cannot place are reported as
  warnings above the view and in the report. See the README's "Loopback mode".
- **Group outlines on the connector map**: in loopback mode each resolved group is
  drawn as outlines around its pads (the style of the original interposer loopback
  pictures), with the pads shrunk to leave a gap between outlines.
- Files named `*.loopback.json` are skipped by layout discovery, so loopback-board
  files can sit beside the custom layouts they name; **Load loopback…** opens there.

### Fixed
- **Self-test could not be stopped** when the scope never triggered (e.g. no
  board attached): each capture blocked inside dwfpy waiting for a trigger, so
  Stop had no effect. Captures now use the same cancel-aware, timeout-bounded
  acquisition as the measurements. A new `trigger_timeout` setting (default 1 s,
  `<= 0` waits forever) bounds the wait; a pin that never triggers is logged as
  "No trigger", recorded without a correlation value and counted as faulty, and
  the current check is skipped with a note instead of hanging.

## [0.3.0] - 2026-07-30

### Added
- **Acceptance limits per measured quantity.** Every value an analysis fits or
  records is judged against its own min/max window — the filter's capacitance
  *and* resistance, the resistance to ground, the voltage — declared once in a
  quantity registry that drives the settings form (with units), the report and
  the plot. The filter resistance is now actually enforced; its window defaults
  wide open, so results analysed with the defaults read as before.
- **Golden reference.** *Use result as reference* turns a known-good measurement
  into expected values per pin (`connector:pin`; the round-based resistance and
  voltage measurements use `*:pin`, the median over rounds). A pin with an entry
  is judged against `expected ± (abs tol + rel tol · |expected|)` — `rel_tol`
  global, the absolute tolerance per quantity — and falls back to the min/max
  window otherwise. *View…* lists the table and *Clear* drops it; the scatter
  view draws each pin's own band and expected value.
- **Analysis presets**: named acceptance criteria, golden reference included,
  saved with *Save as…*, re-applied from the Preset selector and shared with
  *Import…*. They live in a configurable folder (Settings → File locations,
  default `analysis_presets` in the app data directory) and are scoped to one
  measurement.
- The report names which quantity went out of band (e.g. `Out of band: C 2, R 1`).

### Changed
- Verdicts are named after the window they left: *Below limit* / *Above limit*
  replace *Off-nominal* / *Above nominal (possible short)*. For the resistance
  measurement the window *is* the short / high-impedance thresholds, so those
  verdicts keep their names.
- Old analysis settings are migrated on load: a filter `nominal ± rel_tolerance`
  becomes a capacitance window, and `r_nominal_ohm` (reported but never enforced)
  is dropped so a migrated preset does not suddenly fail pins on R.
- Settings: "Output locations" is now "File locations" and holds the presets
  folder as well. The reference tolerances are greyed out until a golden
  reference is loaded, since they apply to nothing before that.

## [0.2.0] - 2026-07-29

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
  - a pad's drawn label resolves as override → `ident` → pin, so trap electrodes and
    LGA pads are captioned with their own names. The pin fallback is skipped on a
    placeholder address, so a made-up number is never drawn as if it were a real pin.
  - the ion-trap importer finds its electrode column by the layout's slug (a rich
    export heads it with the trap name, not `Electrode`) and normalises the
    bank-encoded pin on ingest, so a generated trap layout is canonical without
    editing the upstream export.
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
  in a draggable splitter, each with its own interface and connector selection —
  placed directly under that view's canvas, so it is unambiguous which pane a
  control drives. Both share one annotation set, so a channel marked on either
  appears immediately on the other — the cross-interface correlation is visible
  without switching. "Save view…" captures both panes when split (the per-view
  controls are excluded from the image).
- Light/dark theming with a live toggle in the Settings panel.
- **UI scale** setting (Settings → Appearance): 100–250 % for high-DPI screens
  where the desktop's own scaling leaves text and controls too small. It goes
  through Qt's scale factor, so widgets, text and the matplotlib canvases all grow
  together. Qt fixes that factor when the application is created, so the choice
  applies on restart — the panel says so. An explicit `QT_SCALE_FACTOR` in the
  environment still overrides the setting for a one-off run.
- Standalone executable build via PyInstaller (`trap-tester.spec` +
  `packaging/`); see the README.
- GitHub Actions workflow that builds, smoke-tests and publishes bundles for
  Linux x86_64 and Windows x86_64. Pushing a `v*` tag creates a release with
  auto-generated notes and attaches both archives to it; manual runs publish them
  as workflow artifacts instead.
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
- The stylesheet now sizes fonts in points rather than pixels, so the app follows
  the desktop's font-size preference instead of pinning text to 12 px.

### Removed
- **macOS bundles are no longer built or published.** An unsigned, un-notarised
  `.app` will not open on a downloaded copy without the user stripping its
  quarantine attribute, which is a worse experience than running from source — on
  macOS, use `uv run trap-tester-gui`. The spec still builds `dist/trap-tester.app`
  if you run PyInstaller on a Mac yourself; shipping one again needs an Apple
  Developer ID plus `codesign`/`notarytool` steps, not just a CI matrix row.
- Erroneous `wavefront-sdk-python` dependency (VMware observability SDK, unused;
  it is unrelated to Digilent WaveForms) and its transitive dependencies.
- Legacy top-level `analysis/` scripts, superseded by `src/trap_tester/core/analysis/`.
