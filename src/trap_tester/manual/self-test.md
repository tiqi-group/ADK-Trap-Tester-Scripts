# Self-Test

The Self-Test panel checks the tester itself, so that a bad result can be blamed on
the setup being tested and not on the tester. Pick a test on the left and press
**▶ Run test**. The status line and the plot are in the centre, and the
**Terminal output** on the right has the details.

## WaveForms install check

Checks that the app can use the Analog Discovery at all. No hardware is needed, and
it is the first thing to run on a new machine, or when the device list stays empty.

It reports, line by line:

* the operating system, and where it expects the WaveForms library and SDK;
* whether the WaveForms runtime library loads;
* whether the Python interface to it (`dwfpy`) works, and whether devices can be
  enumerated.

The status ends in *Install OK* or *Install incomplete — see terminal*. If the
library does not load, install WaveForms (see
[Getting started](getting-started.md#what-you-need)) and run the check again.

## Frontend loopback (correlation)

Checks every signal path of the Analog Frontend, using the frontend's own switches.

**Unplug the frontend first.** Nothing may be connected to its DSUB-50 or FPC
connector while this test runs: no feedthrough, no cable, no filter board.

Choose the device (or the simulated device) under the settings, then run.

1. **Loopback on every pin.** For each DSUB pin, the DAC and ADC multiplexers are set
   to the same pin, so the excitation signal goes out through the output stage and
   comes straight back to the scope. The plot shows the two traces (*DAC-MUX out* and
   *ADC-MUX loopback*). Their correlation is computed; a working channel correlates
   at about 1.0. Each pin is logged in the terminal, and a pin below
   `corr threshold` is marked `<-- faulty connection`.
2. **Current check** (if `run current check` is ticked). The ADC input is shorted to
   ground, so the output stage drives its short-circuit current through the source
   resistance, and the measured current is compared with the expected one:

$$I_{\mathrm{short}} = \frac{V_{\mathrm{IN}}}{R_{\mathrm{SOURCE}}} = \frac{2\,\mathrm{V}}{10\,470\,\Omega} = 191\,\mu\mathrm{A}$$

   $R_{\mathrm{SOURCE}} = R_{\mathrm{REF}} + R_{\mathrm{SENSE}}$ is the
   current-limiting resistor (10 kΩ) and the current-sense resistor (470 Ω) in
   series. The terminal prints the expected current, the measured one and the
   relative error.

At the end the status line says how many pins were tested and how many fell below
the threshold (a pin that never triggered counts as below). **■ Stop** aborts the test.

For the names of the multiplexers, switches and resistors, see the
[Simplified Schematic](frontend/README.md#simplified-schematic).

| Setting | Default | Meaning |
| --- | --- | --- |
| `corr threshold` | 0.99 | Correlation below this flags a bad channel. |
| `f sample` | 1 MHz | Scope sample rate. |
| `buffer size` | 8192 samples | Samples per capture. |
| `run current check` | on | Also run the current check. |
| `trigger timeout` | 1 s | How long to wait for a trigger before a pin is recorded as *no trigger*. 0 or less waits forever. |
