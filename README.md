# Analog Discovery Modular Trap Tester Scripts

This repository contains the scripts for performing measurements using the [Analog Discovery 2/3](https://digilent.com/reference/test-and-measurement/analog-discovery-3/start) together with the [Modular Trap Tester Analog Frontend](https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/analog-frontend).

## Dependencies

* Python 3.11 or higher
* [Poetry](https://python-poetry.org/) for Python dependency management
* [Waveform SDK](https://digilent.com/reference/software/waveforms/waveforms-sdk/start) from Digilent. The "Getting Started Guide" can be found [here](https://digilent.com/reference/software/waveforms/waveforms-3/getting-started-guide) which links the installer.
* git

## Install

If the dependencies are met, the python package for easily interfacing the Analog Frontend can be installed using the following commands:

```bash
git clone git@gitlab.phys.ethz.ch:tiqi-projects/tiqi-trap-tester/trap-tester-adk-script.git && \
cd trap-tester-adk-script && \
poetry install 
```

## Repository Structure

* **src/trap_tester**: contains the helper functions configure the Modular Trap Tester
* **test**: Contains scripts to verify the Waveform SDK Install and to test the Modular Trap Tester hardware itself. Additionally, one can find SPICE sim files for a double RC low-pass filter. This has been used to verify the analytical model of the frontend.
* **measurement**: contains the scripts which perform the measurements possible with Tester
* **analysis**: contains scripts which read in the output of the measurement script and compiles reports for the user

## Tests

### test-waveform-install.py

This script only tries to load the WaveformSDK binaries. This should work on every platform (Mac, Windows, Linux).

### test-trap-tester.py

This script serves as self-test of the analog frontend. It covers all capabilities of the Trap Tester:

1. It turns on the power supplies to power the daughter board and initialized the GPIO pins. It sets the MEAS SEL MUX to send the signal of the ADC MUX to the channel 1 of the Analog Discovery scope.
2. It loops over every connector pin performing the following measurement:
    * It sets the ADC & DAC MUX to the same pin. This loops back the DAC signal to ADC1 (via the front end output stage).
    * It takes a single shot from both scope inputs and correlates the captured signals. Channel 0 of the Analog Discovery is hardwired to the DAC MUX input.
    * High correlation suggests that this particular channel works.
3. After testing each MUX setting, the current sense option is also tested.
    * One shorts the ADC MUX input to GND while leaving the ADC & DAC MUX connected to an arbitrary pin. The output stage is now shorted to GND.
    * The current measurement option of the MEAS SEL MUX is used.
    * A known voltage $V_{\text{IN}}$ is applied and a current measurement is taken.
    * The measured DC current is compared to the ideal short circuit current $I_{\text{short}} = \frac{V_{\text{IN}}}{R_{\text{REF}} + R_{\text{SENSE}}}$


For the naming of the components and signals, refer to the [Modular Trap Tester simplified schematic](https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/analog-frontend/-/blob/main/docs/SimplifiedSchematic.jpg?ref_type=heads).

## Measurements

### measure_filter.py

This script tries to characterize an attached RC filter. The general ideas and concepts are outlined in the [Modular Trap Tester Analog Frontend Repository README](https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/analog-frontend/-/blob/main/README.md?ref_type=heads). A summary of the test is given below:

1. The user can modify the script such that one is able to measure multiple connectors consecutively. One can also define feedthrough connector pins which should be skipped (for example for permanent GND connections).
2. I performs a baseline estimate for the parasitic capacitances.
3. It proceeds to loop over all feedthrough connectors:
    * a. Looping over all connector pins it:
        1. checks if the filter can be charged
        2. if the electrode is possible shorted to GND
        3. if the wiring is faulty and the filter input is shorted to GND
        * if any of these are true, we store that off-nominal result and continue with the next pin
        4. if nothing seems fishy a series of filter parameter estimations are performed.
        5. The results are averaged and stored.
    * b. The script asks the user if the measurement series of the current connector should be repeated. This could be useful if cabling during testing was off. If the user chooses yes, the script goes back to point a.
    * c. If the user proceeded they will now be asked to move the Trap Tester to the next feedthrough connector.
4. After looping through all connectors the results are compiled in a pandas dataframe and stored as json.


## Analysis

The scripts in this section can be seen as inspiration to come up with own scripts. As they are potentially setup-specific we omit further descriptions of the contained scripts.