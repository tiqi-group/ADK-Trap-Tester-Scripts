# Device Info

The Device Info panel lists every Analog Discovery the WaveForms runtime can see.
Use it to check that a device is detected and to find its serial number when several
are attached.

* **Device List** (left) shows each device as *name — serial*. **↻ Refresh**
  re-scans, for example after plugging a device in.
* **Simulate (no hardware)** lists the simulated device instead of the attached
  ones.
* **Device Info** (right) shows the selected device's name, serial number (its
  device ID), device type, revision, user name and enumeration index.

If the list says *No devices found*:

* Check the USB cable and that the device is powered.
* Close the WaveForms desktop app; a device it has open cannot be used here.
* If a banner says the WaveForms runtime was not found, install WaveForms (see
  [Getting started](getting-started.md#what-you-need)) and run the install check on
  the [Self-Test](self-test.md) panel.

The Measurement and Self-Test panels have their own device selector; when several
devices are attached, a plain Analog Discovery 3 is offered first, then an Analog
Discovery 2.
