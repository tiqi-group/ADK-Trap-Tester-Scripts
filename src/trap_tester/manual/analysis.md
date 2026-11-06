# Analysis

The Analysis panel reads a saved measurement result, judges every pin against
acceptance criteria and shows the verdicts on a map of the interface and as a plot of
the values. The criteria can be saved as named **presets**, and a known-good board
can be captured as a **golden reference** that later boards are compared with.

## The panel

**Left: what to show.**

* **Result view** controls how the result is drawn:
  * **View**: *Connector map* (the verdicts on a sketch of the interface) or *Value
    scatter* (the measured value per pin).
  * **Layout**: which interface the map shows: the built-in **DSUB-50** or **FPC
    ribbon**, or any custom layout. **Import…** adds a layout file and **Folders…**
    adds folders to search for layouts (see
    [Custom layouts and mappings](layouts.md)).
  * **Connector**: which connector of a multi-connector result to show. **Show all**
    tiles every connector on one map. Both appear only when the result has more than
    one connector, and only for the built-in layouts; a custom layout is always
    drawn whole.
  * **Mapping**: the wiring of your setup, which places the result on interfaces
    further along the cabling. **Import…** adds a mapping CSV.
* **Measurement Result** lists the saved results. Click one to load it; it is
  analysed straight away with the current parameters.

**Centre: the outcome.**

* **Result visualiser**: the map or the plot. **Save view…** writes exactly what is
  shown, at the current zoom, to a PNG. Problems with the *inputs*, such as a
  loopback pad the mapping does not name, are listed in a warning strip above it.
* **Report**: the plain-text report: the criteria used, every faulty pin with what
  was measured, and a summary count per verdict.

**Right: the criteria.** A scrollable column:

* **Mode**: how to read the result. Shown only when there is a choice; a Measure RC
  result can be read in *Standard* or [Loopback](#loopback-mode) mode.
* **Preset**: saved criteria for this measurement and mode. **None (defaults)** is
  the built-in default. **Save as…** stores the current parameters under a name;
  **Import…** adds a preset file.
* **Reference**: the golden reference, if one is loaded, with **Use result as
  reference**, **View…** and **Clear** (see [Golden reference](#golden-reference)).
* The parameter form, grouped by quantity. Its first section, **FPC**, holds the
  `fpc inverted` tickbox (see [Inverted FPC](#inverted-fpc)).
* **Run analysis** re-runs with the edited parameters. **Save report** writes the
  report to `results/analysis/<result name>-result.txt` (`-loopback-result.txt` in
  loopback mode).

Editing a parameter does not re-run on its own; press **Run analysis**. Ticking `fpc
inverted`, choosing a preset, capturing or clearing a reference, or loading a
loopback board re-runs at once.

## Verdicts

Every pin gets one verdict. The same colours are used on the map, in the plot and in
the legend.

| Verdict | Meaning | Counts as a fault |
| --- | --- | --- |
| OK | Every value inside its band. | no |
| Below limit / Above limit | A value is outside its band. The report says which quantity and which band. | yes |
| Not detected | No usable value: no capacitance seen (open or disconnected), or the point was skipped during the measurement. | yes |
| Shorted | A DC current flows: the pin is shorted to ground. | yes |
| High impedance | Resistance above the upper limit (Measure DC Resistance). | yes |
| Loop open, Extra short, Group mismatch, Shorted (expected) | Loopback mode only, see [Loopback mode](#loopback-mode). | yes, except Shorted (expected) |

When a measurement judges several quantities (Measure RC judges both C and R), the
pin takes the worst of them, and the report's last line counts how many pins each
quantity failed on, for example `Out of band: C 2, R 1`.

## Acceptance criteria

Each quantity is judged against a band. The band comes from one of two places,
decided pin by pin:

* **Limits.** Without a reference value for the pin, the band is the quantity's
  `min` … `max` from the form. The band includes both ends.
* **Reference.** When the golden reference has a value for the pin, the band is that
  expected value plus or minus a tolerance:

$$x_{\mathrm{exp}} \pm \left(t_{\mathrm{abs}} + t_{\mathrm{rel}} \cdot |x_{\mathrm{exp}}|\right)$$

  where $t_{\mathrm{rel}}$ is `rel tol` (one number for all quantities) and
  $t_{\mathrm{abs}}$ is the quantity's own `abs tol`, in its unit. The tolerances
  are greyed out until a reference is loaded, because they are not used without one.

### Measure RC

Two checks come before any band:

* A pin the measurement recorded as shorted is **Shorted**.
* A capacitance below `min c abs nf` (0.1 nF) is **Not detected**: the filter is open
  or disconnected rather than out of spec.

| Parameter | Default | |
| --- | --- | --- |
| `c min nf` … `c max nf` | 0.75 … 1.25 nF | Filter capacitance (±25 % around 1 nF). |
| `min c abs nf` | 0.1 nF | Detection floor. |
| `r min ohm` … `r max ohm` | 0 … 10⁹ Ω | Filter resistance. Wide open by default, so R never fails until you set it. |
| `rel tol` | 0.1 | Reference tolerance, relative. |
| `c abs tol nf`, `r abs tol ohm` | 0 | Reference tolerance, absolute. |

A capacitance **above** its band suggests that the pin reaches more than one filter,
that is, a short between electrodes or on the board. See
[Shorts between Electrodes](frontend/README.md#shorts-between-electrodes).

### Measure DC Resistance

The limits *are* the short and open thresholds, so the verdicts keep those names:
below `r min ohm` (10 Ω) is **Shorted**, above `r max ohm` (1 MΩ) is **High
impedance**. A skipped point (`R_est = -1`) is **Not detected**, not a dead short.
The value axis is logarithmic.

### Voltage meter

`v min` … `v max` defaults to 0 … 5 V, the frontend's input range. A reading
outside it is flagged not just because it is out of spec: such a voltage
permanently damages the tester (see
[Input range](getting-started.md#input-range-0-v-to-5-v)). Narrow the window for
your setup, or use a golden reference.

## Inverted FPC

A device can be plugged into the tester's front-end FPC connector the other way
round, so that its ribbon conductors arrive in reverse order: the tester's conductor
$c$ touches the device's conductor $52 - c$ (51 becomes 1, 50 becomes 2, and the
centre conductor 26 stays where it is). Tick `fpc inverted` to undo this; the
analysis re-runs at once.

The inversion is undone at the tester end. Each measured pin is relabelled with the
DSUB pin whose signal runs on the device's conductor, as if the ribbon had been
plugged in the right way round. The findings, the report, the maps and the scatter
plot then all use the device's numbering. Your **Mapping** stays valid: it describes
the device side of the tester, which does not change. A golden reference captured
with the tickbox on is in the device's numbering too, so it can judge a board that
was plugged in the right way round, and the other way round.

* Only pins that leave the tester on the FPC are affected. DSUB pin 9 (GND) has no
  conductor and keeps its number.
* The tickbox is part of the analysis parameters: it is saved in a preset and listed
  in the report as `FPC inverted`. A preset saved before this option existed reads
  as not inverted.

## Golden reference

Instead of typing limits, you can measure a board you know is good and use its
values as the expectation for every later board:

1. Load the good board's result.
2. Press **Use result as reference**. Each pin's measured values become its expected
   values, and the result is re-judged against them (so it should come out all OK).
3. Set the tolerances (`rel tol`, the `abs tol` fields) and press **Run analysis**.
4. **Save as…** a preset. The reference is stored in the preset; until you save it,
   it is lost when you switch presets.

Then load any other result and choose that preset.

Details:

* Values the measurement did not take (skipped, or `-1` for a shorted pin) are left
  out of the reference. Those pins fall back to the min/max limits, so a partly
  covered board shows both kinds of band in the plot.
* Measure RC references are per connector and pin. Measure DC Resistance and the
  Voltage meter have rounds rather than connectors, so their reference holds one
  value per pin: the **median** over the rounds, used for every round.
* **View…** lists every expected value; **Clear** drops the reference and goes back
  to the limits.

## Presets

A preset is the parameters of one measurement and one mode under a name, including
its golden reference or loopback board, and the **mapping** that was selected when it
was saved. Presets are JSON files in the presets folder
(see [Settings](settings.md)); sub-folders are searched too, so a shared folder can
be organised per project. Only the presets for the loaded measurement and mode are
listed.

* **Save as…** never overwrites: a name that exists gets `-2`, `-3`, … appended.
* Choosing a preset also selects its mapping again. This matters most in
  [loopback mode](#loopback-mode), where the mapping places the board's pads on
  tester pins, so the criteria are only right together with it. The mapping is
  stored by file name, not by folder, so the preset works on any machine whose
  layout folders contain a file of that name; with two such files, the one listed
  first in the mapping selector is used. If none is found, the current mapping is
  kept and the status line says so. A preset saved with *Inherent (no mapping)*, or
  saved before this option existed, leaves the mapping selection alone.
* **Import…** checks the file, then copies it into the presets folder. A preset for
  the other mode of the same measurement switches the mode, so it can be applied.
* The file is meant to be readable and editable by hand:

```json
{
  "schema": 1,
  "kind": "analysis-preset",
  "measurement": "measure_filter",
  "analysis": "standard",
  "name": "AFE v2 acceptance",
  "mapping": "mapping_interposer.csv",
  "settings": {"fpc_inverted": false, "c_min_nf": 0.75, "c_max_nf": 1.25, "rel_tol": 0.1},
  "reference": {
    "source": "test_filter_test_20260728-142201.json",
    "captured": "2026-07-30T09:12:00",
    "values": {"0:1": {"c": 1.02, "r": 2010}}
  }
}
```

Reference keys are `"<connector>:<pin>"`, or `"*:<pin>"` for any connector (used by
the round-based measurements). The quantity keys are `c`, `r` and `v`.

## The views

### Connector map

Each signal pad is coloured by its verdict; pads with no result are drawn faint. The
title gives the number of faults and of measured pins, and the legend lists the
verdicts and pad types present. Hover over a pad to read its full finding.

The result carries both the DSUB pin and the FPC conductor of every pin, so it can be
drawn on the DSUB-50, on the FPC ribbon, or on any custom layout. On a custom layout
(an interposer, a trap) a **Mapping** is usually needed to say which pad each tester
pin reaches. If the selected mapping does not apply to the chosen layout, a warning
says so and the layout's own wiring is shown.

### Value scatter

The measured value per pin, coloured by verdict. The band is drawn as one shaded
region when every pin shares the same limits, or as a column per pin (with a dash at
the expected value) when a golden reference gives each pin its own. Pins without a
value (not detected, shorted) are drawn as `x` along the bottom. A multi-connector
result is shown one connector at a time; pick it with **Connector**.

## Loopback mode

An interface such as the interposer can be tested by fitting a **loopback PCB** that
joins its pads together, mostly in pairs and sometimes in larger groups (a heater's
force and sense pads are joined through the heating element). A filter measurement
through a working interface then charges the filter of every pad in a pin's group at
once, so a pin in a group of *n* reads about *n* times the nominal capacitance. Pads
the board ties to ground should read as shorted.

To use it, measure with **Measure RC** as usual, then in the Analysis panel:

1. Load the result and set **Mode** to *Loopback (grouped pads)*.
2. **Load loopback…** the board file (see below).
3. Select the **Mapping** of the setup. It says which tester pin reaches which pad,
   so in this mode it changes the verdicts, not just the picture: changing it re-runs
   the analysis, and the selector stays active in the scatter view.
4. **Save as…** a preset to keep the board and the parameters together.

| Pin | Reading (C / nominal) | Verdict |
| --- | --- | --- |
| in a group of *n* | about *n* | OK |
| in a group of *n* | clearly below *n* | Loop open: not every filter of the group was reached |
| in a group of *n* | clearly above *n* | Extra short |
| not in a group | up to about 1 | OK |
| not in a group | clearly above 1 | Extra short |
| grounded by the board | shorted | Shorted (expected), a pass |
| grounded by the board | anything else | Loop open |
| pins of one group | disagree with each other | Group mismatch: measure again |

"About *n*" means within `count tolerance` (0.5) filters, half-way to the next count,
so the normal spread of the capacitors cannot turn one count into another. Shorted
and not-detected pins, and the filter-resistance window, are judged as in Standard
mode. There is no golden reference in this mode: the expectation for each pin is a
filter count.

| Parameter | Default | |
| --- | --- | --- |
| `c nominal nf` | 1.4 nF | One filter as seen through the loopback (the 1 nF filter plus the FPC). |
| `min c abs nf` | 0.1 nF | Detection floor. |
| `count tolerance` | 0.5 filters | Accepted distance from the expected count. |
| `r min ohm` … `r max ohm` | 0 … 10⁹ Ω | Filter resistance. |

On the connector map each group is outlined around its pads (a larger group as a
chain of outlines), and the pads are drawn smaller to make room.

### The loopback board file

```json
{
  "schema": 1,
  "kind": "loopback",
  "name": "Interposer loopback PCB",
  "source": "loopback-pcb rev A",
  "interface": "interposer",
  "groups": [["A3", "B7"], ["N9", "N18"]],
  "gnd": ["C3", "D4"]
}
```

* `interface` is the slug of the layout the pads are named on, which is also that
  interface's column header in the mapping CSV.
* `groups` lists the pads the board joins; `gnd` the pads it grounds.
* List only pads that carry a filter channel. A group's size *is* the number of
  filters each of its pins should see, so a heater pad with no tester channel stays
  out.
* The file holds no tester pins. Each pad's connector and pin come from the selected
  mapping, so one board file serves every cabling. A pad the mapping does not name is
  reported in the warning strip rather than guessed.

Name the file `<something>.loopback.json` and keep it beside your custom layouts:
the layout selector then skips it, and **Load loopback…** opens in that folder.
