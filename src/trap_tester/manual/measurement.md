# Measurement

The Measurement panel runs a measurement on every pin of one or more DSUB-50
connectors, shows each capture as it arrives and saves the result for the
[Analysis](analysis.md) panel.

## The panel

The panel has three columns.

**Left: files.** Hide this column with **❮ Hide files** to give the plots more room.

* **Measurement Definition** lists the measurements. Click one to choose it; its
  settings appear on the right. Double-click it to read the code that implements it
  in place of the plots, and press **✕ Close** to return to the plots.
* **Measurement Result** lists the saved results, including those in sub-folders.
  Click one to load *its settings* into the form, which is how you repeat a
  measurement exactly. Double-click to read the result file itself. **↻ Refresh**
  re-reads the folder.

**Centre: the run.**

* The status line says what is happening, for example *Connector 1/2 — pin 17*.
* The plot shows the two scope channels of the latest capture, labelled for the
  chosen measurement (voltage and current for **Measure RC**).
* The prompt area shows questions and their buttons while a run waits for you (see
  [Answering the prompts](#answering-the-prompts)).
* **▶ Start measurement** and **■ Stop**.

**Right: setup and output.**

* **Settings**: the form for the chosen measurement, grouped into sections (Testing,
  Digital processing, Trigger, Detection thresholds). Below it, the **Device**
  selector and **↻**, which re-scans the attached devices.
* **Digital out (measurement-defined)**: how the measurement sets the frontend's
  switches. Read-only; it is part of the measurement, not a setting.
* **Preview**: the excitation waveform the measurement will apply, with the trigger
  level. Shown only for measurements that drive a waveform.
* **Terminal output**: a line per pin with what was measured, plus warnings.

## Running a measurement

Before plugging the frontend into a feedthrough, make sure nothing drives the
electrodes: every pin accepts only 0 V to 5 V, and anything outside that range
permanently damages the tester (see
[Input range](getting-started.md#input-range-0-v-to-5-v)).

1. Choose the measurement in **Measurement Definition**, or click an earlier result
   to start from its settings.
2. Check the settings. The ones that matter most are the number of connectors or
   rounds, `invalid pins` (pins to skip) and `file prefix`.
3. Choose the device. Pick **Simulated device (no hardware)** to try the run
   without hardware.
4. Press **▶ Start measurement**.

The run measures every pin from 1 to 50 except the `invalid pins`, then asks whether
to keep the round. With several connectors or rounds it then asks you to set up the
next one, and so on until all are done. The result is then saved to the
measurements folder (see [Result files](#result-files)) and appears in
**Measurement Result**.

**■ Stop** cancels the run. Rounds you already accepted are still saved; the round
in progress is discarded.

### Answering the prompts

While the run waits for you, the **USER LED on the Analog Discovery blinks**, so you
can tell from across the lab that it needs attention.

| Prompt | Buttons | What they do |
| --- | --- | --- |
| *Retake measurement?* (after every connector or round) | **Retake** / **Accept & Continue** | Retake measures the same connector again and throws the last attempt away, which helps if a cable was loose. Accept keeps it. |
| *Switch to DSUB connector N and continue* / *Configure for round N and continue* | **Continue** | Move the frontend to the next connector (or prepare the next round), then continue. |
| *No trigger — …* | **Single (freeze)** / **Resume (live)**, **Continue → skip point** | See below. |

### When a pin does not trigger

**Measure RC** and **Measure DC Resistance** wait for a trigger on every capture. If
none comes within `trigger timeout`, the scope switches to a live, untriggered
*free-run* mode so you can see what the pin is actually doing:

* **Single (freeze)** holds the current frame; **Resume (live)** goes back to live.
* **Continue → skip point** ends free-run. The pin is recorded as skipped (its
  values are `-1`) and the run goes on with the next pin.

Free-run never records anything. A skipped pin shows up in the analysis as *Not
detected*.

## The measurements

### Measure RC

Characterises the RC low-pass filter on every pin (`measure_filter`). This is the
main measurement for an ion-trap feedthrough; the method is explained in
[Measuring Attached RC low-pass Filters](frontend/README.md#measuring-attached-rc-low-pass-filters).

1. With the output stage on but no pin selected, it measures the parasitic
   capacitance of the frontend once, as a baseline.
2. For each pin it applies a voltage step and checks whether the filter charges to
   the full step.
   * If it does not, the pin is recorded as shorted, and the terminal says whether
     the electrode after the filter or the wiring before it looks shorted (see
     [Debugging Common Faults](frontend/README.md#debugging-common-faults)).
   * If the current stays high, it captures again at half the sample rate to tell
     a slowly charging filter from a high-impedance short.
   * Otherwise it fits the step response `n avg` times and averages the filter
     capacitance and resistance.
3. After the last pin of a connector it asks whether to retake, then asks you to move
   to the next connector.

Settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `n dsub` | 1 | Number of DSUB connectors measured in sequence. |
| `f sample` | 6.25 MHz | Scope sample rate. |
| `buffer size` | 8192 samples | Samples per capture. |
| `f square` | 76.3 Hz | Frequency of the excitation square wave. |
| `amplitude` | 1.5 V | Step voltage applied to the pin. |
| `invalid pins` | 9, 42 | Pins that are not measured, comma-separated. |
| `file prefix` | `test` | Start of the result file name. Leave empty to not save. |
| `cutoff` | 200 kHz | Digital low-pass applied to the captures before fitting. |
| `n avg` | 5 | Fits averaged per pin. |
| `trigger source` | current | Trigger on the current (Ch2) or the voltage (Ch1) channel. Current is the reliable choice: a short pulls the voltage low and could be missed. |
| `trigger level` | 0.4 V | |
| `trigger slope` | rising | rising, falling or either. |
| `trigger timeout` | 2 s | How long to wait before free-run. 0 or less waits forever (Stop still works). |

The result has one row per pin: `DSUB connector`, `DSUB pin`, `Shorted`,
`C_filter_nF`, `R_filter_Ohm`, `Bandwidth`, `Perr_max` (the largest fit
uncertainty). A shorted pin has `C_filter_nF = -1`; a skipped pin has
`C_filter_nF` and `R_filter_Ohm` both `-1`.

### Measure DC Resistance

Estimates each pin's resistance to ground and flags shorts and open pins
(`measure_resistance`). The method is explained in
[Measuring DC Resistances](frontend/README.md#measuring-dc-resistances).

For each pin it applies a slow square wave of amplitude $V_{\mathrm{IN}}$ and
averages the end of the capture, giving a steady-state current $i$ and voltage $v$.
The frontend drives the pin through its source resistance
$R_{\mathrm{SOURCE}} = R_{\mathrm{REF}} + R_{\mathrm{SENSE}} = 10\,470\,\Omega$ (a
10 kΩ current-limiting resistor and the 470 Ω current-sense resistor in series),
so the resistance to ground follows two ways:

$$R_i = \frac{V_{\mathrm{IN}}}{i} - R_{\mathrm{SOURCE}} \qquad R_v = R_{\mathrm{SOURCE}}\,\frac{v}{V_{\mathrm{IN}} - v}$$

If $R_i$ is below `r short`, the pin is shorted and $R_i$ is recorded: only the
current measurement is accurate for very small resistances. Otherwise $R_v$ is
recorded, and a value above `r high imp` marks the pin as high impedance.

| Setting | Default | Meaning |
| --- | --- | --- |
| `n rounds` | 1 | Number of measurement rounds. |
| `f sample` | 100 kHz | Scope sample rate. The square wave runs at `f sample` / (10 × `buffer size`). |
| `buffer size` | 8192 samples | Samples per capture. |
| `amplitude` | 1.5 V | Applied voltage. |
| `invalid pins`, `file prefix` | | As for Measure RC. |
| `n samples for avg` | 100 samples | Samples at the end of the capture averaged for the steady state. |
| `r short` | 10 Ω | Below: shorted. |
| `r high imp` | 1 MΩ | Above: high impedance. |
| trigger settings | | As for Measure RC. |

The result has one row per pin and round: `Measurement round`, `DSUB pin`,
`R_est`, `Shorted`, `High impedance`. A skipped pin has `R_est = -1`.

The thresholds can be changed again in the Analysis panel without measuring again.

### Voltage meter

Uses the tester as a voltmeter (`measure_voltage`): the output stage is off and each
pin's voltage is recorded as a mean and a standard deviation. See
[Measuring Voltages](frontend/README.md#measuring-voltages). There is no trigger;
every capture is taken immediately.

> **Warning: the input range is 0 V to 5 V.** Any voltage outside it, negative ones
> included, on any pin permanently damages the tester. Only measure signals you know
> stay inside that range; see
> [Input range](getting-started.md#input-range-0-v-to-5-v).

| Setting | Default | Meaning |
| --- | --- | --- |
| `n rounds` | 4 | Number of measurement rounds. |
| `f sample` | 25 MHz | Scope sample rate. |
| `buffer size` | 8192 samples | Samples per capture. |
| `invalid pins`, `file prefix` | | As for Measure RC. |

The result has one row per pin and round: `Measurement round`, `DSUB pin`,
`V_avg`, `V_std`.

## Result files

Each run is saved as one JSON file in the measurements folder (`results/measurements/`
unless changed in [Settings](settings.md)):

| Measurement | File name |
| --- | --- |
| Measure RC | `<prefix>_filter_test_<date>-<time>.json` |
| Measure DC Resistance | `<prefix>_r_meas_<date>-<time>.json` |
| Voltage meter | `<prefix>_v_meas_<date>-<time>.json` |

The file holds the measurement's name, the settings it ran with and the data table:

```json
{"measurement": "measure_filter", "settings": {...}, "data": {...}}
```

That is why clicking a result restores its settings, and why the Analysis panel knows
how to read it.
