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

todo

## Measurements

todo
