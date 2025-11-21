import time as t
import threading
from trap_tester.mux_mapping import *
import numpy as np

ADC_ENABLE_IDX = 5
EN_DAC1_IDX = 13
SW_MEAS_SEL_IDX = 7
SW_ADC_TO_GND_IDX = 6
CS_ADC1_IDX = 9
CS_DAC1_IDX = 11
WR_IDX = 8
USR_LED_IDX = 15

GAIN_FRONTEND = 2 # V/V
R_REF = 10470 # Ohm
R_SENSE = 470 # Ohm
SENSE_MAG = 25 # V/V

DSUB_GND_PIN = 9
FPC_SPARE_CONDUCTOR = 42


def set_dac(io, dsub_pin):
    dac_address = dsub_to_dac_address(dsub_pin)
    # set DAC
    dac_en = dsub_to_dac_en_bits(dsub_pin)
    for i in range(2):
        bit = (1 << i & dac_en) != 0
        io[EN_DAC1_IDX + i].output_state = bit

    # set CS DAC and ADC
    dac_cs = dsub_to_dac_cs_bits(dsub_pin)
    for i in range(2):
        bit = (1 << i & dac_cs) != 0
        io[CS_DAC1_IDX + i].output_state = bit
        io[CS_ADC1_IDX + i].output_state = True

    # set address
    for i in range(5):
        io[i].output_state = (1 << i & dac_address) != 0

    # toggle WR
    io[WR_IDX].output_state = False
    t.sleep(0.1)
    io[WR_IDX].output_state = True

    # set CS DAC and ADC
    for i in range(2):
        io[CS_DAC1_IDX + i].output_state = True
        io[CS_ADC1_IDX + i].output_state = True

def disable_dac(io):
    for i in range(2):
        io[EN_DAC1_IDX + i].output_state = 0


def set_adc(io, dsub_pin):
    adc_address = dsub_to_adc_address(dsub_pin)
    # set ADC
    adc_en = dsub_to_adc_en_bit(dsub_pin)
    io[ADC_ENABLE_IDX].output_state = adc_en != 0

    # set CS DAC and ADC
    adc_cs = dsub_to_adc_cs_bits(dsub_pin)
    for i in range(2):
        bit = (1 << i & adc_cs) != 0
        io[CS_DAC1_IDX + i].output_state = True
        io[CS_ADC1_IDX + i].output_state = bit

    # set address
    for i in range(5):
        io[i].output_state = (1 << i & adc_address) != 0

    # toggle WR
    io[WR_IDX].output_state = False
    t.sleep(0.1)
    io[WR_IDX].output_state = True

    # set CS DAC and ADC
    for i in range(2):
        io[CS_DAC1_IDX + i].output_state = True
        io[CS_ADC1_IDX + i].output_state = True

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

def blink_user_led(io, period):
    thread = threading.current_thread()
    while getattr(thread, "do_run", True):
        io[USR_LED_IDX].output_state =  1 - io[USR_LED_IDX].output_state
        t.sleep(period/2.0)