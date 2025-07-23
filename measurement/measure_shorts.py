import time as t

import dwfpy as dwf
import numpy as np
from scipy import signal
from utils import *

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
    # select current measurement
    io[SW_MEAS_SEL_IDX].output_state = False
    # load scope and wavegen
    wavegen = device.analog_output
    scope = device.analog_input

    # create reference signal
    n_samples = 4096
    sample_rate = 1e5  # Hz
    freq = 1e2  # Hz
    _t = np.array([i / sample_rate for i in range(n_samples)])
    reference = 0.5 * np.sin(_t * freq * 2 * np.pi)
    for i in range(50):
        # skip missing DSUB pins
        pin = i + 1
        if pin in (9, 42):
            continue

        # set ADC and DAC mux to same channel
        set_dac(io, pin)

        # setup scope for single trigger
        scope[0].setup(range=5.0)
        scope[1].setup(range=5.0)
        # start waveform generator and playback a sine wave
        wavegen[0].setup(
            frequency=1e2, function="sine", offset=0.25, amplitude=0.25, start=True
        )

        t.sleep(0.2)
        scope.single(sample_rate=1e5, buffer_size=4096, configure=True, start=True)
        samples_ch1 = scope[0].get_data()
        samples_ch2 = scope[1].get_data()

        wavegen[0].setup(function="sine", offset=0.0, amplitude=0.0, start=True)
        t.sleep(0.1)

        # prep signals for correlation (for normalized correlation)
        # lowpass filter

        nyq = 0.5 * sample_rate
        cutoff = 10 * freq  # desired cutoff frequency of the filter, Hz
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(4, normal_cutoff, btype="low", analog=False)

        samples_ch1 = signal.filtfilt(b, a, samples_ch1)
        samples_ch2 = signal.filtfilt(b, a, samples_ch2)

        # remove mean
        ch1 = samples_ch1 - np.mean(samples_ch1)
        ch2 = samples_ch2 - np.mean(samples_ch2)
        # scale to interval from -1 to +1 ish (can be done this way because we assume noise or sin inputs)

        corr_ref_ch1 = np.squeeze(
            np.max(np.abs(np.correlate(ch1, reference, mode="valid")))
        )
        corr_ref_ch2 = np.squeeze(
            np.max(np.abs(np.correlate(ch2, reference, mode="valid")))
        )
        corr_ch1_ch2 = np.squeeze(np.max(np.abs(np.correlate(ch1, ch2, mode="valid"))))
        print(
            f"Max Correlation Pin {pin} Ch1 to Ref: {corr_ref_ch1}, Ref to Ch2: {corr_ref_ch2}, Ch1 to Ch2: {corr_ch1_ch2}"
        )
        if corr_ref_ch1 > corr_ref_ch2 and corr_ref_ch1 > corr_ch1_ch2:
            print("no short detected")
        elif corr_ch1_ch2 > corr_ref_ch2:
            Vpp_ch2 = (
                np.max(ch2) - np.min(ch2)
            ) / 25.0  # divide by voltage gain of INA

            R_short_est = (470.0 / Vpp_ch2) - (470.0 + 10000.0)

            print(f"high impedance short detected, estimate: {R_short_est}")

        else:
            Vpp_ch2 = (
                np.max(ch2) - np.min(ch2)
            ) / 25.0  # divide by voltage gain of INA

            R_short_est = (470.0 / Vpp_ch2) - (470.0 + 10000.0)
            if R_short_est > 1000:
                i -= 1
                break

            print(f"low impedance short detected, estimate: {R_short_est}")
    t.sleep(0.1)
    device.analog_io[0][0].value = False
