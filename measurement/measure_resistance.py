import time as t
import threading
import dwfpy as dwf
import numpy as np
from scipy import signal
from scipy.optimize import curve_fit
from trap_tester.utils import *
import pandas as pd
import matplotlib.pyplot as plt


"""-----------------------------------------------------------------------"""


N_ROUNDS = 1
file_prefix="test"

dsub_idx = np.arange(1, 51, 1)
invalid_pins_lst = [DSUB_GND_PIN, FPC_SPARE_CONDUCTOR]
dsub_pins = list(set(dsub_idx).difference(set(invalid_pins_lst)))

# number of samples used for averaging for determining the steady-state
# current when wavegen puts out the high level voltage
N_SAMPLES_FOR_AVG = 100

R_SHORT = 10 # Ohm
R_HIGH_IMP =  1e6 # Ohm

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
    # set up trigger on current measurement
    scope[0].setup(range=5.0)
    scope[1].setup(range=5.0)
    scope.setup_edge_trigger(
        mode="normal", channel=1, slope="rising", level=0.4, hysteresis=0.01
    )

    # settings for measurement and digital filter
    f_sample = 1e5
    buffer_size = 8192
    f_square = f_sample / (buffer_size * 10)
    amplitude = 1.5
    i_short = amplitude / (R_REF + R_SENSE)
    df_list = []
    k = 0

    # start playing back square wave
    wavegen[0].setup(
        frequency=f_square,
        function="square",
        offset=0.5 * amplitude / GAIN_FRONTEND,
        amplitude=0.5 * amplitude / GAIN_FRONTEND,
        start=True,
    )

    # take measurements
    while k in range(N_ROUNDS):
        df_list_i = []
        for pin in dsub_pins:
            # set DAC mux to DSUB pin
            set_dac(io, pin)
            set_adc(io, pin)
            # perform single measurement
            scope.single(sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True)
            i_meas = scope[1].get_data() / (R_SENSE * SENSE_MAG)  # A
            v_meas = scope[0].get_data()
            # use last 100 samples to get the current at start and end
            i_start = np.mean(i_meas[:N_SAMPLES_FOR_AVG])
            i_end = np.mean(i_meas[-N_SAMPLES_FOR_AVG:])

            v_end = np.mean(v_meas[-N_SAMPLES_FOR_AVG:])

            r_tot_from_i = amplitude / i_end
            r_to_gnd_from_i = max(0, r_tot_from_i - (R_REF + R_SENSE))

            ratio = v_end / amplitude
            r_to_gnd_from_v = (ratio / (1 - ratio)) * (R_REF + R_SENSE)

            high_imp = r_to_gnd_from_v > R_HIGH_IMP

            if r_to_gnd_from_i < R_SHORT:
                shorted = True
                r_to_gnd = r_to_gnd_from_i
            else:
                shorted = False
                r_to_gnd = r_to_gnd_from_v

            dict_res = {'Measurement round' : k,
                        'DSUB pin' : pin,
                        'R_est' : r_to_gnd,
                        'Shorted' : shorted,
                        'High impedance' : high_imp,
                        }
            df_list.append(dict_res)
            print(f"Measurement round' : {k}, Pin {pin}, R_est {r_to_gnd} Ohm, Shorted {shorted}, High impedance {high_imp}")

        # ask user to retake measurement
        _uin = input(f"Retake measurement? [y/n]")
        if _uin != "n":
            continue
        # only if measurement series was ok add to result dict
        for dict in df_list_i:
            df_list.append(dict)

        # style points for blinking LED while asking the user to switch connector
        if(k + 1 < N_ROUNDS):
            thread_blink=threading.Thread(target=blink_user_led, args=(io, 0.5))
            thread_blink.start()
            _ = input(f"Configure for round {k+1} and press Enter to continue")
            thread_blink.do_run = False
            thread_blink.join()
        k += 1

    df = pd.DataFrame(df_list, columns=['Measurement round', 'DSUB pin','R_est', 'Shorted', 'High impedance'])
    timestr = t.strftime("%Y%m%d-%H%M%S")
    df.to_json(f'results/{file_prefix}_r_meas_{timestr}.json', double_precision=15, indent=1)
    print(f'{file_prefix}_v_meas_{timestr}.json')
    device.analog_io[0][0].value = False
