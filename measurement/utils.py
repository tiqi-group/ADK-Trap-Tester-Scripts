import time as t

from mux_mapping import *

ADC_ENABLE_IDX = 5
EN_DAC1_IDX = 13
SW_MEAS_SEL_IDX = 7
SW_ADC_TO_GND_IDX = 6
CS_ADC1_IDX = 9
CS_DAC1_IDX = 11
WR_IDX = 8
GAIN_FRONTEND = 2
DSUB_GND_PIN = 9


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
