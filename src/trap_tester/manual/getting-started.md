# Getting started

The Trap Tester app drives an Analog Discovery 2 or 3 fitted with the Modular Trap
Tester [Analog Frontend](frontend/README.md). It measures every pin of a DSUB-50 vacuum
feedthrough, judges the results against acceptance criteria and draws them on a
sketch of the physical interface, so faults in the in-chamber wiring can be found and
traced without a multimeter.

This manual describes the app. The hardware, and the physics behind each
measurement, are in the [Analog Frontend](frontend/README.md) chapter.

## What you need

* An **Analog Discovery 3** (or 2) with the **Analog Frontend** plugged into it.
* Digilent's **WaveForms** software, which provides the runtime library the app uses
  to talk to the Analog Discovery. Download it from
  [digilent.com](https://digilent.com/reference/software/waveforms/waveforms-3/start);
  the download needs a free Digilent account.

Without WaveForms the app still starts, and every panel works against a
**simulated device** (see [Working without hardware](#working-without-hardware)). A
warning banner then says the runtime is missing and links to the download.

## Input range: 0 V to 5 V

> **Warning: any voltage outside 0 V to 5 V on a pin of the frontend's DSUB-50 or
> FPC connector permanently damages the tester.** That includes negative voltages.
>
> Before plugging the frontend into a feedthrough, make sure nothing drives the
> electrodes: disconnect or switch off the electrode DACs. Their usual output range
> (for example ±10 V) exceeds what the tester survives. Only measure a live signal
> with the [Voltage meter](measurement.md#voltage-meter) if you know it stays between
> 0 V and 5 V.

## Installing

### Standalone build (Linux, Windows)

Each [release](https://github.com/tiqi-group/ADK-Trap-Tester-Scripts/releases) has a
self-contained archive for Linux x86_64 and Windows x86_64. No Python installation
is needed:

1. Download the archive for your platform and extract it.
2. Run the `trap-tester` launcher inside the extracted folder (`trap-tester.exe` on
   Windows).

### From source (any platform, including macOS)

macOS has no standalone build, so run the app from source. You need
[uv](https://docs.astral.sh/uv/) and git:

```bash
git clone git@github.com:tiqi-group/ADK-Trap-Tester-Scripts.git
cd ADK-Trap-Tester-Scripts
uv sync
uv run trap-tester-gui
```

`uv run python -m trap_tester.gui` starts the app the same way.

## The window

The bar at the top switches between seven panels. The panel you are on is shown in
**bold**.

| Panel | What it is for |
| --- | --- |
| [Measurement](measurement.md) | Pick a measurement, set it up, run it and watch the captures. |
| [Analysis](analysis.md) | Judge a saved result against acceptance criteria and draw it on an interface. |
| [Interfaces](interfaces.md) | Mark suspicious pins by hand and follow them across interfaces. |
| [Device Info](device-info.md) | List the attached Analog Discovery devices. |
| [Self-Test](self-test.md) | Check the WaveForms install and the frontend itself. |
| [Settings](settings.md) | File locations, layout folders, theme and UI scale. |
| Manual | This manual. |

Throughout the app, colour tells you what a box is for:

* **Green** boxes and controls are *interactive*: selectors, settings, buttons.
* **Red** boxes are *viewers*: plots, reports, terminal output. They show results and
  are not edited.

The interface maps (in Analysis and Interfaces) zoom with the mouse wheel and pan by
dragging; double-click returns to the full view. Hover over a pad to see what it is
and what was found there.

### Getting help

* Press **F1**, or **? Help** at the right end of the top bar, on any panel to open
  its chapter of this manual.
* In the Manual, **Ctrl+F** jumps to the search field. The search covers every
  chapter and ignores case: **Enter** or **F3** goes to the next match, moving on
  to the next chapter when this one has no more, and **Shift+Enter** or
  **Shift+F3** goes back. **Esc** clears the search. Every match in the open
  chapter is highlighted, the current one more strongly.
* **◀ Back** and **Forward ▶** retrace the links and searches you followed.

## Working without hardware

Every device selector ends with **Simulated device (no hardware)**. When no Analog
Discovery is attached it is the only entry, so it is selected automatically. A
simulated run goes through the same steps, prompts and files as a real one, so you
can learn the workflow, or test an analysis setup, at your desk.

If a run fails with *"The selected device is in use by another application"*, close
the WaveForms desktop app (or any other program using the device), press **↻** next to
the device selector and try again.

## A typical session

1. **Self-Test**: run the WaveForms install check once per machine, and the frontend
   loopback test whenever you suspect the tester itself. The loopback test needs the
   frontend **unplugged** from the feedthrough.
2. **Measurement**: plug the frontend into the feedthrough, choose
   **Measure RC**, check the settings and press **Start measurement**. Answer the
   prompts as the run moves from connector to connector. The result is saved
   automatically.
3. **Analysis**: click the new result. It is analysed at once; pick a preset with
   your acceptance criteria, look at the connector map, and save the report.
4. **Interfaces**: if an operator reports a dead channel, mark it here and switch
   interfaces to see where that signal runs on the feedthrough, the ribbon and the
   trap.

## Where files go

| What | Default location |
| --- | --- |
| Measurement results (`*.json`) | `results/measurements/`, relative to the folder the app was started in |
| Analysis reports (`*.txt`) | `results/analysis/` |
| Analysis presets | `analysis_presets/` in the app data folder |
| Custom layouts and mappings | `layouts/` in the app data folder |

The app data folder is `~/.local/share/trap-tester` on Linux,
`~/Library/Application Support/trap-tester` on macOS and `%APPDATA%\trap-tester` on
Windows. All of these locations can be changed; see [Settings](settings.md).
