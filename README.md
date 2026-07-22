# Analog Discovery Modular Trap Tester Scripts

This repository contains the scripts for performing measurements using the [Analog Discovery 2/3](https://digilent.com/reference/test-and-measurement/analog-discovery-3/start) together with the [Modular Trap Tester Analog Frontend](https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/analog-frontend).

## Dependencies

* Python 3.11 or higher
* [uv](https://docs.astral.sh/uv/) for Python dependency management
* [Waveform SDK](https://digilent.com/reference/software/waveforms/waveforms-sdk/start) from Digilent. The "Getting Started Guide" can be found [here](https://digilent.com/reference/software/waveforms/waveforms-3/getting-started-guide) which links the installer.
* git

## Install

If the dependencies are met, the python package for easily interfacing the Analog Frontend can be installed using the following commands:

```bash
git clone git@gitlab.phys.ethz.ch:tiqi-projects/tiqi-trap-tester/trap-tester-adk-script.git && \
cd trap-tester-adk-script && \
uv sync
```

## GUI

A cross-platform (Linux / macOS / Windows) GUI wraps the measurement, analysis,
self-test and device-info workflows:

```bash
uv run trap-tester-gui      # or: uv run python -m trap_tester.gui
```

The GUI runs without hardware attached — tick **Simulate (no hardware)** in the
Measurement panel to drive the flow against a synthetic device. The reusable,
GUI-agnostic measurement engine lives in `src/trap_tester/core/`.

## Repository Structure

* **src/trap_tester**: contains the helper functions configure the Modular Trap Tester
* **test**: Contains scripts to verify the Waveform SDK Install and to test the Modular Trap Tester hardware itself. Additionally, one can find SPICE sim files for a double RC low-pass filter. This has been used to verify the analytical model of the frontend.
* **measurement**: contains the scripts which perform the measurements possible with Tester
* **analysis**: contains scripts which read in the output of the measurement script and compiles reports for the user

## Tests

### test-waveform-install.py

This script only tries to load the WaveformSDK binaries. This should work on every platform (Mac, Windows, Linux).

### test-trap-tester.py

This script serves as self-test of the analog frontend. It covers all capabilities of the Trap Tester:

1. It turns on the power supplies to power the daughter board and initialized the GPIO pins. It sets the MEAS SEL MUX to send the signal of the ADC MUX to the channel 1 of the Analog Discovery scope.
2. It loops over every connector pin performing the following measurement:
    * It sets the ADC & DAC MUX to the same pin. This loops back the DAC signal to ADC1 (via the front end output stage).
    * It takes a single shot from both scope inputs and correlates the captured signals. Channel 0 of the Analog Discovery is hardwired to the DAC MUX input.
    * High correlation suggests that this particular channel works.
3. After testing each MUX setting, the current sense option is also tested.
    * One shorts the ADC MUX input to GND while leaving the ADC & DAC MUX connected to an arbitrary pin. The output stage is now shorted to GND.
    * The current measurement option of the MEAS SEL MUX is used.
    * A known voltage $V_{\text{IN}}$ is applied and a current measurement is taken.
    * The measured DC current is compared to the ideal short circuit current $I_{\text{short}} = \frac{V_{\text{IN}}}{R_{\text{REF}} + R_{\text{SENSE}}}$


For the naming of the components and signals, refer to the [Modular Trap Tester simplified schematic](https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/analog-frontend/-/blob/main/docs/SimplifiedSchematic.jpg?ref_type=heads).

## Measurements

### measure_filter.py

This script tries to characterize an attached RC filter. The general ideas and concepts are outlined in the [Modular Trap Tester Analog Frontend Repository README](https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/analog-frontend/-/blob/main/README.md?ref_type=heads). A summary of the test is given below:

1. The user can modify the script such that one is able to measure multiple connectors consecutively. One can also define feedthrough connector pins which should be skipped (for example for permanent GND connections).
2. I performs a baseline estimate for the parasitic capacitances.
3. It proceeds to loop over all feedthrough connectors:
    * a. Looping over all connector pins it:
        1. checks if the filter can be charged
        2. if the electrode is possible shorted to GND
        3. if the wiring is faulty and the filter input is shorted to GND
        * if any of these are true, we store that off-nominal result and continue with the next pin
        4. if nothing seems fishy a series of filter parameter estimations are performed.
        5. The results are averaged and stored.
    * b. The script asks the user if the measurement series of the current connector should be repeated. This could be useful if cabling during testing was off. If the user chooses yes, the script goes back to point a.
    * c. If the user proceeded they will now be asked to move the Trap Tester to the next feedthrough connector.
4. After looping through all connectors the results are compiled in a pandas dataframe and stored as json.


## Analysis

The scripts in this section can be seen as inspiration to come up with own scripts. As they are potentially setup-specific we omit further descriptions of the contained scripts.

## Custom interface layouts

The Analysis and Interfaces panels can draw a measurement (or manual pin
annotations) onto a sketch of a physical interface — a DSUB-50 connector, the FPC
ribbon, or one you draw yourself. A layout is **just a JSON file**: a list of
static background shapes plus one *slot* per signal, saying where that signal sits
on the picture. This section explains the format so you can author or edit your own.

The layout engine lives in `src/trap_tester/core/layout/` and imports neither Qt
nor matplotlib, so a layout can be built, tested and rendered to a PNG headlessly.

### Where layouts live

* **Built-in** layouts are generated from code and dumped to
  `src/trap_tester/core/layout/layouts/*.json` (`dsub50.json`, `fpc.json`). These
  are the editable source of truth loaded at runtime.
* **Custom** layouts are files you bring yourself. So that device-specific geometry
  need not be tracked in this repository, they live in a per-user data directory
  rather than in the source tree:
  * Linux/other: `$XDG_DATA_HOME/trap-tester/layouts` (else `~/.local/share/trap-tester/layouts`)
  * macOS: `~/Library/Application Support/trap-tester/layouts`
  * Windows: `%APPDATA%\trap-tester\layouts`

  Set the environment variable `TRAP_TESTER_LAYOUTS_DIR` to override the location
  of this *writable* store (e.g. a shared network folder). Any `*.json` in that
  folder shows up as a selectable layout in both panels. You can also add one
  through the GUI with the **Import…** button (it validates the file, normalises
  it, and copies it in without ever clobbering an existing name).

#### Extra search folders (e.g. a private git repo)

If your custom layouts live in a shared or version-controlled folder — a private
git repo of device layouts, say — point the app at it instead of copying files in:

* In the Analysis or Interfaces panel, click **Folders…** next to the layout
  selector, then **Add folder…** and pick the directory. The choice is persisted
  (in `layout_sources.json`, next to the writable store) and every `*.json` in it
  becomes selectable. Pull the repo and the new layouts just appear.
* Or set `TRAP_TESTER_LAYOUT_PATH` to one or more folders (separated by `:` on
  Linux/macOS, `;` on Windows) — useful for CI or a shared machine config.

Extra folders are searched **read-only**: the app never writes into them, so
**Import** and any deletes only ever touch the writable store — your git repo is
left untouched. When the same file name appears in more than one folder, the
selector qualifies each entry with its folder name so they can be told apart.

### The JSON format

A layout file has five top-level keys:

```json
{
  "name": "DSUB-50 (connector 0)",
  "units": "mm",
  "key_by": "dsub_pin",
  "background": [ ... primitives ... ],
  "slots": [ ... slots ... ]
}
```

| key          | meaning |
|--------------|---------|
| `name`       | Shown as the drawing title. |
| `units`      | Cosmetic label for the coordinate units (only proportions matter — the view auto-fits and keeps pins circular). |
| `key_by`     | Which analysis-finding attribute a slot's `pin` matches: `"dsub_pin"` or `"fpc_conductor"`. See *How a layout is matched to data* below. |
| `background` | Static shapes (outline, captions, fixed-colour pads) that never react to data. |
| `slots`      | One entry per signal: where it sits and what it maps to. |

#### Slots

Each slot places one signal on the sketch:

```json
{
  "connector": 0,
  "pin": 1,
  "x": 0.0,
  "y": 2.0,
  "r": 0.38,
  "rot": 0.0,
  "shape": "circle",
  "channel": 46,
  "label": null
}
```

| field       | default    | meaning |
|-------------|------------|---------|
| `connector` | *required* | Connector index (0-based). A single layout may span several connectors; each slot names its own. |
| `pin`       | *required* | The value matched under `key_by` (a DSUB pin, or an FPC conductor). |
| `x`, `y`    | *required* | Centre position. `y` grows **upward** (screen-up). |
| `r`         | `0.38`     | Radius / half-size of the shape. |
| `rot`       | `0.0`      | Rotation in degrees (only used by elongated shapes). |
| `shape`     | `"circle"` | `"circle"` or `"rect"`. |
| `channel`   | `null`     | The **canonical channel** = the `mux_mapping` *signal* number. This is the cross-interface identity (see below). `null` for a pad that carries no channel (GND / spare / unconnected). |
| `label`     | `null`     | Text drawn inside the shape. `null` → the pin number; `""` → no label (useful on dense grids). |

#### Background primitives

`background` is a list of geometric primitives. Each has a `kind` discriminator and
a plain style (`fill`, `stroke`, `width`, colours as `#rrggbb` or `null`):

| `kind`      | fields |
|-------------|--------|
| `circle`    | `x`, `y`, `r`, `fill`, `stroke`, `width` |
| `rect`      | `x`, `y` (centre), `w`, `h`, `rotation`, `fill`, `stroke`, `width` |
| `line`      | `x1`, `y1`, `x2`, `y2`, `stroke`, `width` |
| `polyline`  | `points` (`[[x,y], …]`), `closed`, `fill`, `stroke`, `width` |
| `text`      | `x`, `y`, `text`, `size`, `color`, `ha` (`left`/`center`/`right`), `va` (`top`/`center`/`bottom`/`baseline`), `rotation` |

Use these for the connector outline, labels, and **fixed-colour pads** — contacts
that are drawn but never react to data (GND, and other non-measured pad classes).
Such pads are background `circle`s painted in a fixed colour; a viewer builds the
matching legend by spotting those fill colours (see `core/layout/decoration.py`,
`DECORATION_INFO`). A pad that *is* measured must be a `slot`, not a background
primitive, because a slot's colour comes from the data.

### How a layout is matched to data (the parser)

The whole file round-trips through `InterfaceLayout.from_dict` / `to_dict` in
`core/layout/interface.py`. Loading (`InterfaceLayout.load_json`) does exactly:

1. Read the JSON.
2. Reject an unsupported `key_by` (must be `dsub_pin` or `fpc_conductor`).
3. Rebuild every background entry via `primitive_from_dict`, which looks up its
   `kind` in a registry and reconstructs the dataclass — an unknown `kind` raises.
4. Rebuild every slot via `Slot.from_dict` (missing optional fields fall back to
   the defaults in the table above).

Two functions then turn a layout into a renderer-ready `Drawing`:

* **`build_drawing(result, layout)`** — for the *Analysis* panel. It indexes the
  analysis findings by `(connector, <key_by attribute>)`, then walks the slots: a
  slot whose `(connector, pin)` has a finding takes that finding's **status colour**
  (`STATUS_INFO` in `core/analysis`); a slot with no finding is drawn faint
  ("No data"). Findings with no matching slot are simply not drawn.
* **`build_annotation_drawing(layout, annset, connector=None)`** — for the
  *Interfaces* panel. It colours each slot by the manual mark on its
  `(connector, channel)`; slots with `channel = null` are drawn faint and are not
  clickable.

**Key idea — `channel` is the translation layer.** Because a mark/identity is keyed
by the canonical `channel`, two layouts that put the *same* channel on their slots
correlate for free: mark DSUB pin 1 (channel 46) and the FPC conductor carrying
channel 46 lights up too — no runtime pin↔conductor lookup, the JSON *is* the map.
So when you author a layout, set each slot's `channel` to the signal number that
contact carries (look it up in `src/trap_tester/mux_mapping.py`). Leave it `null`
only for pads that genuinely carry no channel.

### Authoring a layout

You have two options.

**A) Write / edit the JSON by hand.** Fine for a small or one-off interface. Start
from a copy of `layouts/dsub50.json`, adjust the coordinates, `pin`s and
`channel`s, and drop it in the user layouts dir (or Import it in the GUI). Validate
it before use:

```bash
uv run python -c "from trap_tester.core.layout import load_layout; \
  print(load_layout('my_layout.json').name)"
```

**B) Generate it from code** (recommended for anything regular, or derived from a
source file such as a CSV or PCB export). The two built-in generators are worked
examples — each is a small module that builds an `InterfaceLayout` and dumps it to
JSON:

* `dsub50.py` — computes 50 pin coordinates from row/pitch geometry (`python -m
  trap_tester.core.layout.dsub50` → `layouts/dsub50.json`).
* `fpc.py` — a one-row ribbon; shows GND conductors with `channel = null` plus
  "GND" background labels (`python -m trap_tester.core.layout.fpc` →
  `layouts/fpc.json`).

The minimal pattern:

```python
from trap_tester.core.layout import InterfaceLayout, Slot, Rect
from trap_tester.mux_mapping import dsub_to_signal

layout = InterfaceLayout(
    name="My interface",
    units="mm",
    key_by="dsub_pin",
    background=[Rect(x=0, y=0, w=10, h=4, stroke="#8a8a8a", fill="#fbfbfb")],
    slots=[
        Slot(connector=0, pin=p, x=float(p), y=0.0, r=0.4,
             channel=dsub_to_signal.get(p))
        for p in range(1, 6)
    ],
)
layout.save_json("my_layout.json")   # then Import it, or drop it in the layouts dir
```

A generator that reads a source file and builds a larger or device-specific layout
should write its JSON into the (untracked) user layout store — see
`ensure_user_layouts_dir()` in `core/layout/store.py` — so device geometry stays
out of the repository.

Regenerating a **built-in** layout after editing its generator is required — the
runtime loads the JSON, not the code:

```bash
python -m trap_tester.core.layout.dsub50   # rewrites layouts/dsub50.json
python -m trap_tester.core.layout.fpc      # rewrites layouts/fpc.json
```