import time as t

import dwfpy as dwf
import matplotlib.pyplot as plt
import numpy as np
from utils import *

import matplotlib.pyplot as plt

"""-----------------------------------------------------------------------"""


with dwf.Device() as device:
    # connect to the device

    device.analog_io[0][1].value = 5.0
    # Enable the positive power supply.
    device.analog_io[0][0].value = True

    # Enable the master-enable switch.
    device.analog_io.master_enable = True

    t.sleep(0.1)

    # initialize DIO
    io = device.digital_io
    for i in range(16):
        if i < 8:
            io[i].setup(enabled=True, state=False)
        else:
            io[i].setup(enabled=True, state=True)

    # do not ground the ADC input
    io[SW_ADC_TO_GND_IDX].output_state = False
    # route ADC MUX signal to ADK CH2 (according to BNC adapter)
    io[SW_MEAS_SEL_IDX].output_state = True
    # load scope and wavegen
    wavegen = device.analog_output
    scope = device.analog_input

    correlation = np.zeros(50)
    dsub_pin = np.arange(1, 51, 1)
    for i in range(len(dsub_pin)):
        # skip missing DSUB pins
        pin = i + 1
        if pin in ([DSUB_GND_PIN]):
            continue

        # set ADC and DAC mux to same channel
        set_adc(io, pin)
        set_dac(io, pin)

        # setup scope for single trigger
        scope[0].setup(range=5.0)
        scope[1].setup(range=5.0)
        scope.setup_edge_trigger(
            mode="normal", channel=0, slope="rising", level=0.1, hysteresis=0.01
        )
        # start waveform generator and playback a sine wave
        wavegen[0].setup(function="sine", offset=0.5, amplitude=0.5, start=True)
        t.sleep(0.1)
        # setup single shot
        scope.single(sample_rate=1e6, buffer_size=4096 * 2, configure=True, start=True)
        t.sleep(0.1)
        wavegen[0].setup(function="sine", offset=0.0, amplitude=0.0, start=True)
        t.sleep(0.1)
        samples_ch1 = scope[0].get_data()
        samples_ch2 = scope[1].get_data()

        # prep signals for correlation (for normalized correlation)
        original = (samples_ch1 - np.mean(samples_ch1)) / (
            np.std(samples_ch1) * len(samples_ch1)
        )
        sampled = (samples_ch2 - np.mean(samples_ch2)) / np.std(samples_ch2)
        # outputs should be identical and give correlation close to 1
        corr = np.squeeze(np.max(np.correlate(original, sampled, mode="valid")))
        print(f"Correlation on DSUB pin {i + 1}: {corr}")
        if corr < 0.98:
            print(f"Error on DSUB pin {pin}")
        correlation[i] = corr
    # output
    plt.scatter(dsub_pin, correlation)
    plt.title("ADC-to-DAC MUX Correlation")
    plt.xlabel("DSUB Pin")
    plt.ylabel("Maximum Correlation Coefficient")
    plt.ylim((-1.5, 1.5))
    plt.show()
    t.sleep(0.1)

    # test current measurement
    # do ground the ADC input
    io[SW_ADC_TO_GND_IDX].output_state = True
    # route ADC MUX signal to ADK CH2 (according to BNC adapter)
    io[SW_MEAS_SEL_IDX].output_state = False

    # setup scope for single trigger
    scope[0].setup(range=5.0)
    scope[1].setup(range=5.0)
    # start waveform generator and playback a sine wave
    wavegen[0].setup(
        frequency=1,
        function="square",
        offset=0.5,
        amplitude=0.5,
        start=True,
    )
    scope[1].setup(range=5)
    scope.setup_edge_trigger(
            mode="normal", channel=1, slope="rising", level=0.1, hysteresis=0.01
        )
    t.sleep(0.5)

    f_sample = 2.5e6
    buffer_size = 8192
    scope.single(
            sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
    )
    current_measured = scope[1].get_data()  / 470 / 25 * 1e6 # uA
    plt.plot(np.array(range(buffer_size)) / f_sample * 1000, current_measured * 1000) #mA
    plt.title("Current measurement")
    plt.xlabel("Time [ms]")
    plt.ylabel("Current [mA]")
    plt.show()

    avg_current = np.mean(current_measured[int(-buffer_size/2) + 40:-1])
    print(f"Expected current: 191uA, measured current: {avg_current:.2f} uA")
    print(f"Relative error: {(avg_current - 191.0) / 191.0:.4f}")

    device.analog_io[0][0].value = False
