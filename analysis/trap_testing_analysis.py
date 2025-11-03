import pandas as pd
import json
import numpy as np
from trap_tester.mux_mapping import *
from PIL import Image, ImageDraw, ImageFont

path = '../measurement/results/'
filename ='ZQ2-T_01-nick-thinks_filter_test_20251031-151846.json'
df = pd.read_json(path + filename)

C_nominal = 1.4 #nF, as two 1nF + FPC caps should become shorted together
R_nominal = 1000 #Ohm
rel_tolerance = 0.4
min_C_abs = 0.1 # nF

# Was the FPC inserted in the same orientation on both connectors?
# If yes -> fpc_inverted = True
fpc_inverted = True
trap = "Sparrow"

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

# Trap Carrier
with open('./interposer_tester_src/bondpad_to_lga.json') as file:
    bondpad_to_lga_dict  = json.loads(file.read())

with open(f'./interposer_tester_src/{trap}_pinout.json') as file:
    trap_pinout  = json.loads(file.read())

with open('./interposer_tester_src/lga_to_bondpad.json') as file:
    lga_to_bondpad_dict  = json.loads(file.read())

with open('./interposer_tester_src/bondfinger_fp.json') as file:
    bondfinger_fp = json.loads(file.read())

shorts_to_gnd_lst = list(set(gnd_tester_carrier_lst) - set(gnd_filter_lst))
print(f"Additional shorts introduced by Tester Carrier: {shorts_to_gnd_lst}")


filename_result = filename.split('.')[0] + '-result.txt'

n_errors = 0
n_detected_shorts = 0

# legend attributes
colors = ['green', 'orange', 'blue', 'red']
labels = ['nominal', 'possible short between electrodes', 'shorted to GND', 'unknown fault']

scale = 1.7

fontsize = int(40 * scale)
plot_title_offset = int(fontsize * 2)
radius = int(5 * scale) # bounding radius for regular polygons used for drawing bondfingers
legend_fontsize = int(radius * 2.4)
legend_y_offset = int(radius * 4 * len(labels))
legend_x_offset = int(80 * scale)
x_offset = int(750 * scale) # from center of trap fp
y_offset = int(260 * scale + plot_title_offset + legend_y_offset) # from center of trap fp


img = Image.new("RGB", (2 * x_offset, 2*y_offset), (255, 255, 255))
draw = ImageDraw.Draw(img)
font = ImageFont.load_default(size=fontsize)

# title
draw.text((img.width / 2, plot_title_offset), filename.split('.')[0], anchor="md", align = "center", fill = "black", font=font)
# draw legend
font = ImageFont.load_default(size=legend_fontsize)
for i, label in enumerate(labels):
    x = legend_x_offset
    y = img.height - legend_y_offset + i * radius * 4
    xy = (x, y, radius * 1.7)
    draw.regular_polygon(xy, 4, fill=colors[i])
    draw.text((x + 3 * radius, y), label, anchor="lm", align = "left", fill = "black", font=font)


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

        fpc_index = str(int(n_conn * 100 + fpc_conductor))
        lga_pad = fpc_to_lga_dict[fpc_index]
        if lga_pad in lga_to_bondpad_dict:
            bondfinger = lga_to_bondpad_dict[lga_pad]
        else:
            continue


        # print to image
        coordinates = bondfinger_fp[bondfinger]
        xy = (x_offset + coordinates[0] * scale * 45, y_offset - coordinates[1] * scale * 45, radius)
        rot = 180 - coordinates[2]

        # check for shorts
        if shorted:
            # check if introduced short by tester carrier
            if (lga_pad in shorts_to_gnd_lst):
                file.write(f'Found introduced short to GND in pad {lga_pad}\n')
                n_detected_shorts+=1
            else:
                file.write(f'Found erroneous short to GND in pad {lga_pad}\n')
                n_errors+=1
                draw.regular_polygon(xy, 4, rotation=rot, fill="blue")

        elif (C_filt < min_C_abs):
            file.write(f'Cap not detected on pin {dsub_pin} / FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')
            draw.regular_polygon(xy, 4, rotation=rot, fill="black")
        elif (np.abs((C_filt - C_nominal) / C_nominal) > rel_tolerance):
            # capacitance out of range, check if we can detect single cap
            if (np.abs((C_filt - C_nominal*2) / C_nominal * 2) < rel_tolerance):
                file.write(f"Capacitance not within target value on bondfinger {bondfinger}\n")
                n_errors+=1
                draw.regular_polygon(xy, 4, rotation=rot, fill="orange")
            else:
                file.write(f'Weird capacitance value on FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')
                n_errors+=1
                draw.regular_polygon(xy, 4, rotation=rot, fill="black")
        else:
            file.write(f'Found correct value on LGA pad {lga_pad}\n')
            draw.regular_polygon(xy, 4, rotation=rot, fill="green")


    
    img.save(f'results/{filename.split('.')[0]}-bongfinger.jpg')

    file.write(f'Detected correct shorts {n_detected_shorts} of {len(shorts_to_gnd_lst)}\n')
    file.write(f'Total errors: {n_errors}\n')

    p_fail_pair = n_errors / len(tester_carrier_pairs_dict.keys())
    file.flush()
    file.close()
