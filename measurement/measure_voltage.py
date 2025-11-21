import time as t
import threading
import dwfpy as dwf
import numpy as np
from scipy import signal
from scipy.optimize import curve_fit
from trap_tester.utils import *
import pandas as pd
import matplotlib.pyplot as plt

N_ROUNDS = 4
file_prefix="CaPe_VI_VII"

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
    io[SW_ADC_TO_GND_IDX].output_state = False
    # select voltage measurement
    io[SW_MEAS_SEL_IDX].output_state = True
    # disable DAC output stage
    disable_dac(io)

    # load scope
    scope = device.analog_input

    df_list = []
    k = 0
    f_sample = 25e6
    buffer_size = 8192
    while k in range(N_ROUNDS):
        df_list_i = []
        for pin in dsub_pins:

            # set ADC channel
            set_adc(io, pin)

            scope.record(
                sample_rate=f_sample, buffer_size=buffer_size, configure=True, start=True
            )

            V_in = scope[1].get_data()
            V_avg = np.mean(V_in)
            V_std = np.std(V_in)
            dict_res = {'Measurement round' : k, 'DSUB pin' : pin, 'V_avg' : V_avg, 'V_std' : V_std}
            df_list.append(dict_res)
            print(f"Measurement round' : {k}, Pin {pin}, V_avg {V_avg}V, V_sdt {V_std}")
        
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

    df = pd.DataFrame(df_list, columns=['Measurement round', 'DSUB pin','V_avg', 'V_std'])
    timestr = t.strftime("%Y%m%d-%H%M%S")
    df.to_json(f'results/{file_prefix}_v_meas_{timestr}.json', double_precision=15, indent=1)
    print(f'{file_prefix}_v_meas_{timestr}.json')
    device.analog_io[0][0].value = False