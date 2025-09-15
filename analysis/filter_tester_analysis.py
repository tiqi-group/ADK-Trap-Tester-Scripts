import pandas as pd
import numpy as np
from trap_tester.mux_mapping import *

path = '../measurement/results/'
filename = 'CaPe_fb_filter_test_20250911-134541.json'
df = pd.read_json(path + filename)

C_nominal = 1.0 #nF
R_nominal = 5100 #Ohm
rel_tolerance = 0.1
min_C_abs = 0.1

filename_result = filename.split('.')[0] + '-result.txt'
with open('results/'+filename_result, 'w') as file:
    for row in df.iterrows():
        shorted = row[1].iloc[2]
        C_filt = row[1].iloc[3]
        R_filt = row[1].iloc[4]
        n_conn = row[1].iloc[0]
        dsub_pin = row[1].iloc[1]
        _sig = dsub_to_signal[dsub_pin]
        fpc_conductor = signal_to_fpc[_sig]

        if (C_filt < min_C_abs):
            file.write(f'Cap not detected on pin {dsub_pin} / FPC conductor {fpc_conductor} on connector {n_conn}\n')
        if (C_filt > min_C_abs and np.abs((C_filt - C_nominal) / C_nominal) > rel_tolerance):
            file.write(f'Cap value not nominal on pin {dsub_pin} / FPC conductor {fpc_conductor} on connector {n_conn}: C {C_filt}, R {R_filt}\n')
