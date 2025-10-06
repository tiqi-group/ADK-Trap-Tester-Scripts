import pandas as pd
import json
import numpy as np
from trap_tester.mux_mapping import *

path = '../measurement/results/'
filename = 'CaPe_fb_filter_test_20250911-134541.json'
df = pd.read_json(path + filename)

C_nominal = 2.0 #nF, as two 1nF caps should become shorted together
R_nominal = 2000 #Ohm
rel_tolerance = 0.25
min_C_abs = 0. # nF

# Was the FPC inserted in the same orientation on both connectors?
# If yes -> fpc_inverted = True
fpc_inverted = False

### Load netlist info from filter board and tester carrier
# Tester Carrier
with open('./interposer_tester_src/pairs.json') as file:
    tester_carrier_pairs_dict  = json.loads(file.read())
with open('./interposer_tester_src/grouping.json') as file:
    tester_carrier_groups_dict  = json.loads(file.read())
gnd_tester_carrier_lst = tester_carrier_groups_dict["327GND"]
# Filter Board
with open('./interposer_tester_src/filter_gnd.txt') as file:
    gnd_filter_lst  = [line.rstrip() for line in file]
with open('./interposer_tester_src/fpc_to_lga.json') as file:
    fpc_to_lga_dict  = json.loads(file.read())

shorts_to_gnd_lst = list(set(gnd_tester_carrier_lst) - set(gnd_filter_lst))
print(f"Additional shorts introduced by Tester Carrier: {shorts_to_gnd_lst}")


filename_result = filename.split('.')[0] + '-result.txt'

n_errors = 0
n_detected_shorts = 0
with open('results/'+filename_result, 'w') as file:
    for row in df.iterrows():
        shorted = row[1].iloc[2]
        C_filt = row[1].iloc[3]
        R_filt = row[1].iloc[4]
        n_conn = row[1].iloc[0]
        dsub_pin = row[1].iloc[1]
        _sig = dsub_to_signal[dsub_pin]
        fpc_conductor = signal_to_fpc[_sig]

        # invert signal if FPC is inserted the same way in
        # trap tester
        if (fpc_inverted):
            fpc_conductor = 52 - fpc_conductor

        fpc_index = str(n_conn * 100 + fpc_conductor)
        lga_pad = fpc_to_lga_dict[fpc_index]

        # check for shorts
        if shorted:
            # check if introduced short by tester carrier
            if (lga_pad in shorts_to_gnd_lst):
                file.write(f'Found introduced short to GND in pad {lga_pad}\n')
                n_detected_shorts+=1
            else:
                file.write(f'Found erroneous short to GND in pad {lga_pad}\n')
                n_errors+=1
        elif (C_filt < min_C_abs):
            file.write(f'Cap not detected on pin {dsub_pin} / FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')
        elif (np.abs((C_filt - C_nominal) / C_nominal) > rel_tolerance):
            # capacitance out of range, check if we can detect single cap
            if (np.abs((C_filt - C_nominal/2) / C_nominal/2) < rel_tolerance):
                file.write(f"Interposer and tester carrier do not short pad {lga_pad}\n")
                n_errors+=1
            else:
                file.write(f'Weird capacitance value on FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')
        else:
            file.write(f'Landed in default statement on FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')

    file.write(f'Detected correct shorts {n_detected_shorts} of {len(shorts_to_gnd_lst)}\n')
    file.write(f'Total errors: {n_errors}')
    file.flush()
    file.close()
