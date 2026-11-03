# Analog Discovery Modular Trap Tester Scripts

This repository contains the scripts for performing measurements using the [Analog Discovery 2/3](https://digilent.com/reference/test-and-measurement/analog-discovery-3/start) together with the [Modular Trap Tester Analog Frontend](https://github.com/tiqi-group/ADK-Trap-Tester-Frontend).

## Dependencies

* Python 3.11 or higher
* [uv](https://docs.astral.sh/uv/) for Python dependency management
* [Waveform SDK](https://digilent.com/reference/software/waveforms/waveforms-sdk/start) from Digilent. The "Getting Started Guide" can be found [here](https://digilent.com/reference/software/waveforms/waveforms-3/getting-started-guide) which links the installer.
* git

## Install

If the dependencies are met, the python package for easily interfacing the Analog Frontend can be installed using the following commands:

```bash
git clone git@github.com:tiqi-group/ADK-Trap-Tester-Scripts.git && \
cd ADK-Trap-Tester-Scripts && \
uv sync
```

## GUI

A cross-platform (Linux / macOS / Windows) GUI wraps the measurement, analysis,
self-test and device-info workflows:

```bash
uv run trap-tester-gui      # or: uv run python -m trap_tester.gui
```

The GUI runs without hardware attached — pick **Simulated device (no hardware)** in
a device selector to drive the flow against a synthetic device. The reusable,
GUI-agnostic measurement engine lives in `src/trap_tester/core/`. How to use the GUI
is described in its built-in [manual](#manual).

### Building a standalone executable

The GUI can be frozen into a self-contained bundle with
[PyInstaller](https://pyinstaller.org/) so it runs without a Python
installation. The build is driven by the tracked `trap-tester.spec`:

```bash
uv sync --group packaging          # installs PyInstaller
uv run pyinstaller trap-tester.spec
```

The result is `dist/trap-tester/` — a self-contained folder whose launcher is
`dist/trap-tester/trap-tester` (`trap-tester.exe` on Windows). Archive the folder
to distribute it.

**macOS is not distributed as a bundle** — run it from source instead, with
`uv run trap-tester-gui`. The spec still wraps the collection into
`dist/trap-tester.app` if you build it on a Mac yourself, but an unsigned,
un-notarised bundle makes Gatekeeper refuse to open a downloaded copy, and asking
users to strip the quarantine attribute is a worse experience than installing
[uv](https://docs.astral.sh/uv/). Shipping one properly needs an Apple Developer ID
plus `codesign` and `notarytool` steps in CI.

Notes:

* **Build per OS *and* architecture.** PyInstaller does not cross-compile: run
  the command on each target platform to produce that platform's binary, and on
  the target CPU (an Apple-silicon build is not an Intel build).
* **Hardware needs WaveForms.** Real Analog Discovery access still requires
  Digilent's WaveForms runtime (`libdwf`) on the target machine — it is a
  native, separately-licensed library and is intentionally *not* bundled.
  Without it the app still launches and runs in **Simulate** mode.
* **Verifying a bundle.** The launcher accepts `--smoke-test`: it builds every
  panel once and exits with a status instead of entering the event loop, which
  is how CI checks a frozen build.

#### Builds in CI

Bundles are built automatically by the [`Build executables`](.github/workflows/build.yml)
GitHub Actions workflow, which — on a runner per platform — runs the regression
suite, freezes the app, smoke-tests the frozen launcher headlessly, and
publishes an archive:

| Platform | Runner | Archive |
| --- | --- | --- |
| Linux x86_64 | `ubuntu-latest` | `trap-tester-<version>-linux-x86_64.tar.gz` |
| Windows x86_64 | `windows-latest` | `trap-tester-<version>-windows-x86_64.zip` |

* **macOS is not built.** See the note above: on a Mac, run from source with
  `uv run trap-tester-gui`.
* **To cut a release, push a tag** — the workflow is triggered by any tag
  matching `v*`:

  ```bash
  git tag v0.2.0
  git push origin v0.2.0
  ```

  Once both platforms have built and passed their smoke test, the workflow
  creates a GitHub release for that tag with auto-generated notes (the
  commits/PRs since the previous tag) and attaches both archives to it, so the
  executables can be downloaded straight from the releases page. If either
  platform fails, nothing is published — there is no half-finished release to
  clean up. Re-running the workflow on a tag replaces the existing assets.
* **On a manual run** (*Actions → Build executables → Run workflow*) each
  archive is uploaded as a workflow artifact on the run page, versioned
  `dev-<sha>`, and no release is created.

To use one: download and extract the archive, then run the `trap-tester`
launcher inside it.

## Repository Structure

* **src/trap_tester**: the Python package. `core/` is the GUI-agnostic engine
  (device abstraction + mock, measurements, analysis, self-test, interface
  layouts) and `gui/` is the PySide6 application. The `trap-tester-gui` console
  script lives here.
* **tests**: hardware-free regression suites: `uv run pytest`.
* **scripts/hardware**: standalone scripts that require attached hardware — the
  WaveForms SDK install check and the analog-frontend self-test — plus the SPICE
  (LTspice) sim files for the double-RC low-pass model used to verify the
  analytical model of the frontend. (The self-test and install check are also
  available, hardware-free-friendly, from the GUI's Self-Test panel.)
* **scripts/sync_frontend_docs.py**: copies the
  [Analog Frontend](https://github.com/tiqi-group/ADK-Trap-Tester-Frontend) README
  and its images into `src/trap_tester/manual/frontend/` for the in-app manual
  (manufacturing notes are left out). The copy is pinned: `SOURCE.json` records
  the commit it came from. Re-run it after the frontend README changes:
  `python scripts/sync_frontend_docs.py [--source PATH] [--ref REF]`.
* **packaging**: the PyInstaller entry point used to build a standalone
  executable (see [Building a standalone executable](#building-a-standalone-executable)).

## Manual

How to use the app — every panel, the measurements, the acceptance criteria and
loopback mode, the custom layout and mapping formats — is in the **in-app manual**
(the **Manual** tab), which also includes the Analog Frontend hardware
documentation. Its chapters are Markdown files in
[`src/trap_tester/manual/`](src/trap_tester/manual/), readable on GitHub too; start
with [Getting started](src/trap_tester/manual/getting-started.md).

The design notes behind the layout format are in
[`docs/layout-schema-v2.md`](docs/layout-schema-v2.md).

## Development

Substantial portions of this project — notably the GUI, the refactor of the
measurement/analysis/self-test scripts into a reusable engine, and the packaging
setup — were developed with the assistance of
[Claude Code](https://claude.com/claude-code) (Anthropic). See
[`CHANGELOG.md`](CHANGELOG.md) for notable changes.