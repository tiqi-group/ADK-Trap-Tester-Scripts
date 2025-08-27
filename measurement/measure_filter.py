import time as t

import dwfpy as dwf
import numpy as np
from scipy import signal
from scipy.optimize import curve_fit
from utils import *

import matplotlib.pyplot as plt

"""-----------------------------------------------------------------------"""


def step_double_rc(x, c1, c2, r1, r2, t_start, V_end):
    idx_0 = np.argwhere(x < t_start)
    x[idx_0] = t_start
    tau1 = r1 * c1
    tau2 = r2 * c2
    tau3 = r1 * c2
    T = np.sqrt(tau1**2 - 2*tau1 * (tau2 - tau3) + tau2**2 + 2 * tau2 * tau3 + tau3**2)

    exp1 = T / (tau1*tau2)
    exp2 = -(1 + (T + tau2 + tau3) / tau1) / 2.0 / tau2

    term1 = (tau2 - tau3 - tau1 + T) / 2.0 / T * np.exp((x - t_start) * exp2)
    term2 = (tau1 - tau2 + tau3 + T) / 2.0 / T * np.exp((x - t_start)  * (exp1 + exp2))

    res = V_end * (1 - (term1 + term2))
    res[idx_0] = 0
    return res

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
    io[SW_ADC_TO_GND_IDX].output_state = False  # True for PSi Cryo
    # select current measurement
    io[SW_MEAS_SEL_IDX].output_state = False
    # load scope and wavegen
    wavegen = device.analog_output
    scope = device.analog_input

    dsub_pin = np.arange(1, 51, 1)
    f_sample = 25e6
    buffer_size = 8192
    amplitude = 0.8
    nyq = 0.5 * f_sample
    cutoff = 2e5  # desired cutoff frequency of the filter, Hz
    normal_cutoff = cutoff / nyq
    b, a = signal.butter(4, normal_cutoff, btype="low", analog=False)
    # hack for making it work in PSI 2D array
    # set_adc(io, 25)

    # gnd_pins = (3, 6, 8, 10, 12, 15, 20, 23, 25, 26, 28, 31, 36, 39, 41, 43, 45, 48)
    gnd_pins = ()
    for i in range(50):
        # skip missing DSUB pins
        pin = i + 1
        if pin in gnd_pins:
            continue
        # have to exclude these for hardware revision v1.0.0
        if pin in (9, 42):
            continue

        # set DAC channel
        set_dac(io, pin)

        # setup scope for single trigger
        scope[0].setup(range=5.0)
        scope[1].setup(range=5.0)
        # start waveform generator and playback a sine wave
        wavegen[0].setup(
            frequency=1,
            function="square",
            offset=0.5 * amplitude / GAIN_FRONTEND,
            amplitude=0.5 * amplitude / GAIN_FRONTEND,
            start=True,
        )

        scope.setup_edge_trigger(
            mode="normal", channel=0, slope="rising", level=0.5, hysteresis=0.01
        )

        # turn off DAC for parasitic measurement
        dac_en_sto = [True, True]
        for i in range(2):
            dac_en_sto[i] = io[EN_DAC1_IDX + i].output_state
            io[EN_DAC1_IDX + i].output_state = True

        scope.single(
            sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
        )

        v_divider = signal.filtfilt(b, a, scope[0].get_data())
        i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / 470 / 25  # A
        timestamp = np.array([i / f_sample for i in range(buffer_size)])   # ms

        i_offset = np.mean(i_to_trap[:100])
        i_to_trap_no_offset = i_to_trap - i_offset
        C_baseline = np.sum(i_to_trap_no_offset) / f_sample / amplitude
        # restore DAC MUX
        for i in range(2):
            io[EN_DAC1_IDX + i].output_state = dac_en_sto[i]

        scope.single(
            sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
        )

        v_divider = signal.filtfilt(b, a, scope[0].get_data())
        i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / 470 / 25  # A

        i_offset = np.mean(i_to_trap[:100])
        i_to_trap_no_offset = i_to_trap - i_offset
        C_est = (
            np.sum(i_to_trap_no_offset) / f_sample / amplitude
            - C_baseline
        )
        if C_est < 0:
            C_est = 1e-12
        # get discharge measurement
        scope.setup_edge_trigger(
            mode="normal", channel=0, slope="rising", level=0.05, hysteresis=0.01
        )
        t.sleep(0.1)
        scope.single(
            sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
        )
        v_divider = scope[0].get_data()
        popt, pcov = curve_fit(
            step_double_rc,
            timestamp,
            v_divider,
            bounds=([0.98*C_baseline, 0.98*C_est, 10460, 100, timestamp[0], 0.9*amplitude], [1.02*C_baseline, 1.02*C_est, 10500, 10000,timestamp[-1],1.1*amplitude]),
        )
        v_fit = step_double_rc(timestamp, popt[0],popt[1],popt[2],popt[3],popt[4],popt[5])
        print(f"Pin {pin}, C_filter_est: {popt[1]:.3}, R_filter_est{popt[3]:.3}")


    t.sleep(0.1)
    device.analog_io[0][0].value = False
