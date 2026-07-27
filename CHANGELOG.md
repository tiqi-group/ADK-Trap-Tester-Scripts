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
- Cross-platform PySide6 GUI (`trap-tester-gui`) with six panels: Measurement,
  Analysis, Interfaces, Device Info, Self-Test, and Settings.
- Mock device / **Simulate** mode so the GUI runs with no Analog Discovery
  attached.
- Custom interface layouts (DSUB-50, FPC, interposer, bond-finger) with a
  cross-interface channel-mapping model, zoom/pan, and import/search-folder
  support.
- Light/dark theming with a live toggle in the Settings panel.
- Standalone executable build via PyInstaller (`trap-tester.spec` +
  `packaging/`); see the README.
- GitHub Actions workflow that builds, smoke-tests and publishes bundles for
  Linux x86_64, Windows x86_64 and macOS (Apple silicon and Intel) — attached
  as assets to every published release, and available as workflow artifacts on
  manual runs.
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
