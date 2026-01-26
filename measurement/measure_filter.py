import time as t
import json
from pathlib import Path
import threading
import dwfpy as dwf
import numpy as np
from scipy import signal
from scipy.optimize import curve_fit
from trap_tester.utils import *
import pandas as pd
import matplotlib.pyplot as plt

"""-----------------------------------------------------------------------"""


N_DSUB = 1
F_SAMPLE = 25e6 / 4.0
BUFFER_SIZE = 8192
F_SQUARE = F_SAMPLE / (BUFFER_SIZE * 10)
AMPLITUDE = 1.5
CUTOFF = 2e5  # desired cutoff frequency of the digital filter, Hz
N_AVG = 5

settings_file = Path("./results/test_filter_test_20260126-165412.json")
if settings_file.is_file():
    print("loading settings from file")
    with settings_file.open("r") as file:
        loaded_settings = json.load(file)["settings"]
        N_DSUB = loaded_settings["n_dsub"]
        F_SAMPLE = loaded_settings["f_sample"]
        BUFFER_SIZE = loaded_settings["buffer_size"]
        F_SQUARE = loaded_settings["f_square"]
        AMPLITUDE = loaded_settings["amplitude"]
        CUTOFF = loaded_settings["cutoff"]
        N_AVG = loaded_settings["n_avg"]
else:
    print("No such file")


file_prefix="test"

dsub_idx = np.arange(1, 51, 1)
invalid_pins_lst = [DSUB_GND_PIN, FPC_SPARE_CONDUCTOR]
dsub_pins = list(set(dsub_idx).difference(set(invalid_pins_lst)))
i_short = AMPLITUDE / R_REF

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
    io[SW_ADC_TO_GND_IDX].output_state = False  # True for PSI Cryo
    # select current measurement
    io[SW_MEAS_SEL_IDX].output_state = False
    # load scope and wavegen
    wavegen = device.analog_output
    scope = device.analog_input

    # digital filter
    nyq = 0.5 * F_SAMPLE
    normal_cutoff = CUTOFF / nyq
    b, a = signal.butter(4, normal_cutoff, btype="low", analog=False)
    
    # hack for making it work in PSI 2D array
    # set_adc(io, 25)

    # get baseline measurements
    # this entails measure parasitics with the DAC MUX turned off
    for i in range(2):
        io[EN_DAC1_IDX + i].output_state = True

    # setup scope for single trigger
    scope[0].setup(range=5.0)
    scope[1].setup(range=5.0)
    # start waveform generator and playback a rectangular wave
    wavegen[0].setup(
        frequency=F_SQUARE,
        function="square",
        offset=0.5 * AMPLITUDE / GAIN_FRONTEND,
        amplitude=0.5 * AMPLITUDE / GAIN_FRONTEND,
        start=True,
    )

    # trigger on rising edge of current measurement
    # the current measurement should even trigger when
    # the output is shorted
    scope.setup_edge_trigger(
        mode="normal", channel=1, slope="rising", level=0.4, hysteresis=0
    )

    scope.single(
        sample_rate=F_SAMPLE, buffer_size=BUFFER_SIZE, configure=True, start=True
    )
    v_divider = signal.filtfilt(b, a, scope[0].get_data())
    i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG)  # A
    timestamp = np.array([i / F_SAMPLE for i in range(BUFFER_SIZE)])   # ms

    i_offset = np.mean(i_to_trap[:100]) # current drive at 0V output (avg over 100 samples)
    i_to_trap_no_offset = i_to_trap - i_offset

    # parasitics
    ## numerical integration of current over time
    C_baseline = np.sum(i_to_trap_no_offset) / F_SAMPLE / AMPLITUDE # C = Q / V
    # leakage current, measurement noise, etc
    ## ss means steady-state....
    I_ss_baseline = np.mean(i_to_trap[-100:]) # current drive at high output (avg over 100 samples)

    df_list = []
    k = 0
    while k in range(N_DSUB):
        df_list_i = []
        for pin in dsub_pins:

            # set DAC channel
            set_dac(io, pin)

            scope.single(
                sample_rate=F_SAMPLE, buffer_size=BUFFER_SIZE, configure=True, start=True
            )

            v_divider = signal.filtfilt(b, a, scope[0].get_data())
            i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG) # A

            i_offset = np.mean(i_to_trap[:100])
            i_end = np.mean(i_to_trap[-100:])
            v_end = np.mean(v_divider[-100:])

            half_sample_rate = False
            if (0.98 * AMPLITUDE < v_end and v_end < 1.02 * AMPLITUDE): # settled v?
                if (i_end > 2 * I_ss_baseline): # look for elevated current
                    # two options here: could be elevated current due to high-impedance short
                    # OR: filter is still charging
                    scope.single(
                        sample_rate=F_SAMPLE / 2, buffer_size=BUFFER_SIZE, configure=True, start=True
                    )
                    _i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG) # A
                    i_end_new = np.mean(_i_to_trap[-100:])
                    
                    # If the current is actively decreasing (exponential rate) the filter is still charging
                    if (i_end_new < 1.5*i_end):
                        print("Filter still charging")
                        half_sample_rate = True
                    else:
                        print("Fishy stuff, probably high impedance short")
                        dict_res = {'DSUB connector' : k, 'DSUB pin' : pin ,'Shorted' : False ,'C_filter_nF' : -1, 'R_filter_Ohm' : -1, 'Bandwidth' : -1, 'Perr_max' : -1}
                        df_list.append(dict_res)
                        k += 1
                        continue
                else:
                    print("nominal")
            else:
                # see if charging done but filter is shorted to GND
                # on trap electrode side
                # R_est
                R_from_i_end = (AMPLITUDE / i_end) - R_REF
                ratio = v_end / AMPLITUDE
                R_from_v_end = (ratio / (1 - ratio)) * R_REF
                R_mean = -1
                if (np.abs((R_from_i_end / R_from_v_end) -  1) < 0.1): # check if similar estimates
                    print("electrode possibly shorted after filter")
                    R_mean = 0.5 * (R_from_i_end + R_from_v_end)
                    #df_list.append(dict_res)
                else:
                    # if R_est are dissimilar then R is probably very small
                    # (R_from_i_end can also be negative which is caught)
                    if (0.5 * i_short < i_end and i_end < 1.1 * i_short):
                        print(f"wire possible shorted before filter, i_end: {i_end:.2}A")
                        R_mean = 0
                    else:
                        print("wut")
                print(f"R_filter = {R_mean}")
                dict_res = {'DSUB connector' : k, 'DSUB pin' : pin ,'Shorted' : True ,'C_filter_nF' : -1, 'R_filter_Ohm' : R_mean, 'Bandwidth' : -1, 'Perr_max' : -1}
                df_list_i.append(dict_res)
                continue # do not perform rest of script in off-nominal cases

            #setup trigger on voltage
            scope.setup_edge_trigger(
                    mode="normal", channel=0, slope="rising", level=0.05, hysteresis=0.01
            )
            C_est = np.zeros((N_AVG))
            R_est = np.zeros((N_AVG))
            Perr = np.zeros((6))
        
            for i in range(N_AVG):
                # get discharge measurement
                scope.single(
                    sample_rate=F_SAMPLE, buffer_size=BUFFER_SIZE, configure=True, start=True
                )
                v_divider = signal.filtfilt(b, a, scope[0].get_data())
                i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG) # A
                i_to_trap_no_offset = i_to_trap - i_offset

                C_est_i = (
                    np.sum(i_to_trap_no_offset) / F_SAMPLE / AMPLITUDE
                    - C_baseline
                )
                if C_est_i < 0:
                    C_est_i = 1e-15

                _t = np.array([k / F_SAMPLE for k in range(BUFFER_SIZE)])   # ms
                lower = [0.98*C_baseline, 0.98*C_est_i, 10460, 100, _t[0], 0.95*AMPLITUDE]
                upper = [1.02*C_baseline, 1.02*C_est_i, 10500, 10000, _t[-1],1.05*AMPLITUDE]
                popt, pcov = curve_fit(
                    step_double_rc,
                    _t,
                    v_divider,
                    bounds=(lower, upper),
                )
                C_est[i] = popt[1]
                R_est[i] = popt[3]
                perr = np.sqrt(np.diag(pcov))
                Perr += perr / N_AVG
                #v_fit = step_double_rc(timestamp, popt[0],popt[1],popt[2],popt[3],popt[4],popt[5])
            C_est_mean = np.mean(C_est)
            R_est_mean = np.mean(R_est)
            bandwidth = 1 / (C_est_mean * R_est_mean * 2 * np.pi)
            Perr_max_param = np.max(Perr[:4]) # only include R and C values, ignore offset and final value
            dict_res = {'DSUB connector' : k, 'DSUB pin' : pin ,'Shorted' : False ,'C_filter_nF' : C_est_mean*1e9, 'R_filter_Ohm' : R_est_mean, 'Bandwidth' : bandwidth, 'Perr_max' : Perr_max_param}
            df_list_i.append(dict_res)
            print(f"DSUB connector' : {k}, Pin {pin}, C_filter_est: {C_est_mean:.3}, R_filter_est{R_est_mean:.3}, bandwidth: {bandwidth:.3}, Perr max: {Perr_max_param:.3}")
        
        # ask user to retake measurement
        _uin = input(f"Retake measurement? [y/n]")
        if _uin != "n":
            continue
        # only if measurement series was ok add to result dict
        for dict in df_list_i:
            df_list.append(dict)
        
        # style points for blinking LED while asking the user to switch connector
        if(k + 1 < N_DSUB):
            thread_blink=threading.Thread(target=blink_user_led, args=(io, 0.5))
            thread_blink.start()
            _ = input(f"Switch to DSUB Connector {k+1} and press Enter to continue")
            thread_blink.do_run = False
            thread_blink.join()
        k += 1

    df = pd.DataFrame(df_list, columns=['DSUB connector', 'DSUB pin','Shorted','C_filter_nF','R_filter_Ohm','Bandwidth', 'Perr_max'])
    settings_dict = {
        "n_dsub": N_DSUB,
        "f_sample": F_SAMPLE,
        "buffer_size": BUFFER_SIZE,
        "f_square": F_SQUARE,
        "amplitude": AMPLITUDE,
        "cutoff" : CUTOFF,
        "n_avg" : N_AVG,
    }
    data_dict = df.to_dict()
    combined_data = {
        "settings" : settings_dict,
        "data" : data_dict,
     }

    timestr = t.strftime("%Y%m%d-%H%M%S")
    with open(f'results/{file_prefix}_filter_test_{timestr}.json', 'w') as f:
        json.dump(combined_data, f, indent=1)

    print(f'{file_prefix}_filter_test_{timestr}.json')
    device.analog_io[0][0].value = False