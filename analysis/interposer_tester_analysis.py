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

# Trap
with open('./interposer_tester_src/bondpad_to_lga.json') as file:
    bondpad_to_lga_dict  = json.loads(file.read())

with open(f'./interposer_tester_src/{trap}_pinout.json') as file:
    trap_pinout  = json.loads(file.read())

shorts_to_gnd_lst = list(set(gnd_tester_carrier_lst) - set(gnd_filter_lst))
print(f"Additional shorts introduced by Tester Carrier: {shorts_to_gnd_lst}")


filename_result = filename.split('.')[0] + '-result.txt'

n_errors = 0
n_detected_shorts = 0

scale = 2
fontsize = 40 * scale
plot_title_offset = fontsize * 2
x_offset = 40 * scale
y_offset = 40 * scale + plot_title_offset
radius = 8 * scale
linewidth = 1 * scale
radius_arcs = radius + linewidth
pitch = int(1.6 * 2 * (radius + linewidth))

img = Image.new("RGB", (2 * x_offset + 25 * pitch, 2 * y_offset + 25 * pitch), (255, 255, 255))
img_with_mirrored = Image.new("RGB", (2 * img.width, img.height), (255, 255, 255))
draw = ImageDraw.Draw(img)

# pin one indicator
draw.rectangle((x_offset-radius/1.5, y_offset-radius/1.5, x_offset+radius/1.5, y_offset+radius/1.5), width=linewidth, fill = "black")

# plot shorted interposer pairs
for vals in tester_carrier_groups_dict.values():
    if len(vals) == 2:
        x = []
        y = []
        for lga_pad_i in vals:
            lga_column = ord(lga_pad_i[0]) - ord("A")
            lga_row = int(lga_pad_i[1:]) - 1
            x_i = lga_column * pitch + x_offset
            y_i = lga_row * pitch + y_offset
            x.append(x_i)
            y.append(y_i)
        # draw arcs
        for j in range(2):
            dx = x[j] - x[1-j]
            dy = y[j] - y[1-j]
            alpha = np.atan2(dy, dx)
            alpha_j_deg =  180 * alpha / np.pi
            arc_shape = [(x[j] - radius_arcs, y[j] - radius_arcs), (x[j] + radius_arcs, y[j] + radius_arcs)]
            draw.arc(arc_shape, start = alpha_j_deg-90, end = alpha_j_deg + 90, fill ="black", width = linewidth)
        # draw lines
        dx = x[1] - x[0]
        dy = y[1] - y[0]
        alpha = np.atan2(dy, dx)
        for j in range(2):
            alpha_j = alpha + (-1.0)**j * np.pi / 2
            alpha_j_deg = 180 * alpha_j / np.pi
            points = []
            for k in range(len(x)):
                points.append(x[k] + np.cos(alpha_j) * radius_arcs)
                points.append(y[k] + np.sin(alpha_j) * radius_arcs)
            draw.line(points, fill="black", width=linewidth)

# plot RF pads for easier debugging
for bondpad in bondpad_to_lga_dict.keys():
    if bondpad[:2] == "RF":
        lga_pad = bondpad_to_lga_dict[bondpad]
        lga_column = ord(lga_pad[0]) - ord("A")
        lga_row = int(lga_pad[1:]) - 1
        center = (lga_column * pitch + x_offset, lga_row * pitch + y_offset)
        draw.circle(center, radius, fill="black", width = linewidth)

needed_pads = []
# determine needed pads for trap
for bondpad in trap_pinout.keys():
    if bondpad[0] == "R":
        continue
    lga_pad = bondpad_to_lga_dict[bondpad]
    needed_pads.append(lga_pad)

# plot GNDs
for lga_pad in gnd_filter_lst:
    # print to image
    lga_column = ord(lga_pad[0]) - ord("A")
    lga_row = int(lga_pad[1:]) - 1
    center = (lga_column * pitch + x_offset, lga_row * pitch + y_offset)
    draw.circle(center, radius, fill = "blue", width = linewidth)

for lga_pad in gnd_filter_lst:
    # print to image
    lga_column = ord(lga_pad[0]) - ord("A")
    lga_row = int(lga_pad[1:]) - 1
    center = (lga_column * pitch + x_offset, lga_row * pitch + y_offset)
    draw.circle(center, radius, fill = "blue", width = linewidth)

for lga_pad in shorts_to_gnd_lst:
    # print to image
    lga_column = ord(lga_pad[0]) - ord("A")
    lga_row = int(lga_pad[1:]) - 1
    center = (lga_column * pitch + x_offset, lga_row * pitch + y_offset)
    draw.circle(center, radius, fill = "blue", width = 1)
    draw.circle(center, radius / 2, fill = "lightblue", width = linewidth)



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
        
        # print to image
        lga_column = ord(lga_pad[0]) - ord("A")
        lga_row = int(lga_pad[1:]) - 1
        center = (lga_column * pitch + x_offset, lga_row * pitch + y_offset)

        # check for shorts
        if shorted:
            # check if introduced short by tester carrier
            if (lga_pad in shorts_to_gnd_lst):
                file.write(f'Found introduced short to GND in pad {lga_pad}\n')
                n_detected_shorts+=1
            else:
                file.write(f'Found erroneous short to GND in pad {lga_pad}\n')
                n_errors+=1
                draw.circle(center, radius, fill = "red", width = 1)
                draw.circle(center, radius / 2, fill = "lightblue", width = linewidth)

        elif (C_filt < min_C_abs):
            file.write(f'Cap not detected on pin {dsub_pin} / FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')
            draw.circle(center, radius, fill = "black", width = 1)
        elif (np.abs((C_filt - C_nominal) / C_nominal) > rel_tolerance):
            # capacitance out of range, check if we can detect single cap
            if (np.abs((C_filt - C_nominal/2) / C_nominal/2) < rel_tolerance):
                file.write(f"Interposer and tester carrier do not short pad {lga_pad}\n")
                n_errors+=1
                draw.circle(center, radius, fill = "red", width = 1)
            else:
                file.write(f'Weird capacitance value on FPC conductor {fpc_conductor} on connector {n_conn}, check connectivity and redo measurement\n')
                n_errors+=1
                draw.circle(center, radius, fill = "orange", width = 1)
        else:
            file.write(f'Found correct value on LGA pad {lga_pad}\n')
            draw.circle(center, radius, fill = "green", width = 1)

    # mark

    font = ImageFont.load_default(size=radius*2)
    for lga_pad in needed_pads:
        lga_column = ord(lga_pad[0]) - ord("A")
        lga_row = int(lga_pad[1:]) - 1
        center = (lga_column * pitch + x_offset, lga_row * pitch + y_offset)
        draw.text(center, "X", anchor="mm", align = "center", fill = "black", font=font)

    mirrored = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    img_with_mirrored.paste(img, (0,0))
    img_with_mirrored.paste(mirrored, (img.width,0))

    # add captions
    draw = ImageDraw.Draw(img_with_mirrored)
    font = ImageFont.load_default(size=fontsize)
    draw.text((img.width / 2, plot_title_offset), "top view", anchor="md", align = "center", fill = "black", font=font)
    draw.text((3 * img.width / 2, plot_title_offset), "bottom view", anchor="md", align = "center", fill = "black", font=font)
    
    img_with_mirrored.save(f'results/{filename.split('.')[0]}.jpg')

    file.write(f'Detected correct shorts {n_detected_shorts} of {len(shorts_to_gnd_lst)}\n')
    file.write(f'Total errors: {n_errors}\n')

    p_fail_pair = n_errors / len(tester_carrier_pairs_dict.keys())
    # we see a pair fail if one or both fuzzbuttons are not connected
    # p_fail_pair = 1 - p_no_fail_pair
    #             = 1 - p_no_fail_single^2
    #             = 1 - (1 - p_fail_single)^2
    #             = 2*p_fail_single - p_fail_single^2
    # <=> p_fail_single^2 - 2 * p_fail_single + p_fail_pair = 0
    # <=> p_fail_single = 1 - sqrt(1 - p_fail_pair)
    p_fail_single = 1 - np.sqrt(1 - p_fail_pair)
    file.write(f'Pair failure probability: {p_fail_pair:.3f}\nSingle fuzzbutton failure probability: {p_fail_single:.3f}')
    file.flush()
    file.close()
