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

N_DSUB = 1
file_prefix="interposer-black-con0-reseat1-tester-carrier"

dsub_idx = np.arange(1, 51, 1)
invalid_pins_lst = [DSUB_GND_PIN, FPC_SPARE_CONDUCTOR]
dsub_pins = list(set(dsub_idx).difference(set(invalid_pins_lst)))

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

    # settings for measurement and digital filter
    f_sample = 25e6 / 2.0
    buffer_size = 8192
    f_square = f_sample / (buffer_size * 100)
    amplitude = 1.5
    i_short = amplitude / R_REF
    nyq = 0.5 * f_sample
    cutoff = 2e5  # desired cutoff frequency of the filter, Hz
    normal_cutoff = cutoff / nyq
    b, a = signal.butter(4, normal_cutoff, btype="low", analog=False)
    
    n_avg = 10
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
        frequency=f_square,
        function="square",
        offset=0.5 * amplitude / GAIN_FRONTEND,
        amplitude=0.5 * amplitude / GAIN_FRONTEND,
        start=True,
    )

    # trigger on rising edge of current measurement
    # the current measurement should even trigger when
    # the output is shorted
    scope.setup_edge_trigger(
        mode="normal", channel=1, slope="rising", level=0.4, hysteresis=0.01
    )

    # get measuremrnt
    scope.single(
        sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
    )
    v_divider = signal.filtfilt(b, a, scope[0].get_data())
    i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG)  # A
    timestamp = np.array([i / f_sample for i in range(buffer_size)])   # ms

    i_offset = np.mean(i_to_trap[:100]) # current drive at 0V output (avg over 100 samples)
    i_to_trap_no_offset = i_to_trap - i_offset

    # parasitics
    ## numerical integration of current over time
    C_baseline = np.sum(i_to_trap_no_offset) / f_sample / amplitude # C = Q / V
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
                sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
            )

            v_divider = signal.filtfilt(b, a, scope[0].get_data())
            i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG) # A

            i_offset = np.mean(i_to_trap[:100])
            i_end = np.mean(i_to_trap[-100:])
            v_end = np.mean(v_divider[-100:])

            half_sample_rate = False
            if (0.98 * amplitude < v_end and v_end < 1.02 * amplitude): # settled v?
                if (i_end > 2 * I_ss_baseline): # look for elevated current
                    # two options here: could be elevated current due to high-impedance short
                    # OR: filter is still charging
                    scope.single(
                        sample_rate=f_sample / 2, buffer_size=buffer_size, configure=True, start=True
                    )
                    _i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG) # A
                    i_end_new = np.mean(_i_to_trap[-100:])
                    
                    # If the current is actively decreasing (exponential rate) the filter is still charging
                    if (i_end_new < 1.5*i_end):
                        print("Filter still charging")
                        half_sample_rate = True
                    else:
                        print("Fishy stuff, probably high impedance short")
                        dict_res = {'DSUB pin' : pin ,'Shorted' : True ,'C_filter' : -1, 'R_filter' : -1, 'Bandwidth' : -1, 'Perr_max' : -1}
                        df_list.append(dict_res)
                        k += 1
                        continue
                else:
                    print("nominal")
            else:
                # see if charging done but filter is shorted to GND
                # on trap electrode side
                # R_est
                R_from_i_end = (amplitude / i_end) - R_REF
                ratio = v_end / amplitude
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
                dict_res = {'DSUB pin' : pin ,'Shorted' : True ,'C_filter' : -1, 'R_filter' : R_mean, 'Bandwidth' : -1, 'Perr_max' : -1}
                df_list_i.append(dict_res)
                continue # do not perform rest of script in off-nominal cases

            #setup trigger on voltage
            scope.setup_edge_trigger(
                    mode="normal", channel=0, slope="rising", level=0.05, hysteresis=0.01
            )
            C_est = np.zeros((n_avg))
            R_est = np.zeros((n_avg))
            Perr = np.zeros((6))
        
            for i in range(n_avg):
                # get discharge measurement
                scope.single(
                    sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
                )
                v_divider = signal.filtfilt(b, a, scope[0].get_data())
                i_to_trap = signal.filtfilt(b, a, scope[1].get_data()) / (R_SENSE * SENSE_MAG) # A
                i_to_trap_no_offset = i_to_trap - i_offset

                C_est_i = (
                    np.sum(i_to_trap_no_offset) / f_sample / amplitude
                    - C_baseline
                )
                if C_est_i < 0:
                    C_est_i = 1e-15

                _t = np.array([k / f_sample for k in range(buffer_size)])   # ms
                lower = [0.98*C_baseline, 0.98*C_est_i, 10460, 100, _t[0], 0.95*amplitude]
                upper = [1.02*C_baseline, 1.02*C_est_i, 10500, 10000, _t[-1],1.05*amplitude]
                popt, pcov = curve_fit(
                    step_double_rc,
                    _t,
                    v_divider,
                    bounds=(lower, upper),
                )
                C_est[i] = popt[1]
                R_est[i] = popt[3]
                perr = np.sqrt(np.diag(pcov))
                Perr += perr / n_avg
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
    timestr = t.strftime("%Y%m%d-%H%M%S")
    df.to_json(f'results/{file_prefix}_filter_test_{timestr}.json', double_precision=15, indent=1)
    device.analog_io[0][0].value = False