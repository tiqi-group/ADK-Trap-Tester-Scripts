"""Device abstraction over ``dwfpy`` plus a hardware-free ``MockDevice``.

The measurement functions are written against the small slice of the
``dwfpy`` API the original scripts used (analog_io / digital_io / analog_input
scope / analog_output wavegen). :class:`MockDevice` duck-types exactly that
slice and synthesises plausible double-RC scope traces, so the GUI runs and
demos with no Analog Discovery attached. When real hardware is present,
:func:`open_device` yields the genuine ``dwfpy`` device instead.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np

from trap_tester.utils import (
    GAIN_FRONTEND,
    R_REF,
    R_SENSE,
    SENSE_MAG,
    SW_MEAS_SEL_IDX,
    WR_IDX,
    step_double_rc,
)

# Nominal synthetic-filter model used by the mock scope.
_C_PAR = 30e-12  # parasitic capacitance [F]
_C_FILT_NOM = 1.0e-9  # nominal filter capacitance [F]
_R_FILT_NOM = 2000.0  # nominal filter resistance [Ohm]
_R_AFE = R_REF + R_SENSE  # 10940 Ohm
_I_LEAK = 0.5e-6  # steady-state leakage current [A]
_STEP_SAMPLE = 200  # sample index at which the excitation step occurs


# --------------------------------------------------------------------------- #
# Mock hardware
# --------------------------------------------------------------------------- #
class _MockDioPin:
    def __init__(self, parent: "_MockDigitalIo", index: int) -> None:
        self._parent = parent
        self._index = index

    def setup(self, enabled: bool = True, state: bool = False) -> None:
        self._parent._state[self._index] = bool(state)

    @property
    def output_state(self) -> bool:
        return self._parent._state[self._index]

    @output_state.setter
    def output_state(self, value: Any) -> None:
        self._parent._on_write(self._index, bool(value))


class _MockDigitalIo:
    """16 digital I/O pins; tracks whether the DAC MUX has been latched.

    ``set_dac`` / ``set_adc`` toggle the WR pin (falling then rising edge) to
    latch a MUX address. The baseline path only sets the DAC-enable bits and
    never toggles WR, so ``dac_connected`` stays ``False`` for the parasitic
    baseline capture and becomes ``True`` once a pin is actually selected.
    """

    def __init__(self) -> None:
        self._state = [False] * 16
        self._pins = [_MockDioPin(self, i) for i in range(16)]
        self.dac_connected = False
        self.dac_addr = 0

    def __getitem__(self, idx: int) -> _MockDioPin:
        return self._pins[idx]

    def _on_write(self, idx: int, value: bool) -> None:
        prev = self._state[idx]
        self._state[idx] = value
        # rising edge on WR latches the current 5-bit address bits
        if idx == WR_IDX and value and not prev:
            self.dac_connected = True
            self.dac_addr = sum((1 << i) for i in range(5) if self._state[i])


class _MockScopeChannel:
    def __init__(self) -> None:
        self._data = np.zeros(1)
        self.range = 5.0

    def setup(self, range: float = 5.0, **_: Any) -> None:  # noqa: A002 - dwfpy name
        self.range = range

    def get_data(self) -> np.ndarray:
        return self._data


class _MockTrigger:
    """Minimal stand-in for dwfpy's analog-in trigger (only auto_timeout used)."""

    def __init__(self) -> None:
        self.auto_timeout = 0.0


class _MockScope:
    def __init__(self, device: "MockDevice") -> None:
        self._device = device
        self._channels = [_MockScopeChannel(), _MockScopeChannel()]
        self.trigger = _MockTrigger()
        # When True, every triggered acquisition never completes (read_status
        # stays RUNNING), so ``triggered_capture`` times out — exercises the
        # no-trigger / free-run / skip path without hardware.
        self.fail_trigger = False
        self._fail_countdown = 0  # fail this many upcoming triggered acquisitions
        self._acq_failing = False
        # The trigger mode last set via setup_edge_trigger, and the mode recorded
        # at the start of each triggered acquisition. The mock does not model
        # trigger-dependent data, but exposing this lets tests assert that no
        # real capture ran while the scope was still in "auto" (free-run) mode.
        self._trigger_mode = "normal"
        self.capture_modes: list[str] = []

    def __getitem__(self, idx: int) -> _MockScopeChannel:
        return self._channels[idx]

    def fail_next_triggers(self, n: int) -> None:
        """Make the next ``n`` triggered acquisitions time out (then succeed)."""
        self._fail_countdown = int(n)

    def setup_edge_trigger(self, mode: str | None = None, **_: Any) -> None:
        if mode is not None:
            self._trigger_mode = mode

    def configure(self, reconfigure: bool = False, start: bool = False) -> None:
        # data is synthesised in single()/record(); arming just records the mode
        if start:
            self.capture_modes.append(self._trigger_mode)
            if self._fail_countdown > 0:
                self._fail_countdown -= 1
                self._acq_failing = True
            else:
                self._acq_failing = False

    def read_status(self, read_data: bool = False) -> str:
        """DONE, unless ``fail_trigger`` / a countdown simulates a missing trigger."""
        return "RUNNING" if (self.fail_trigger or self._acq_failing) else "DONE"

    def _generate(self, sample_rate: float, buffer_size: int) -> None:
        n = int(buffer_size)
        dio = self._device.digital_io
        rng = np.random.default_rng(int(dio.dac_addr) + 1)

        # SW_MEAS_SEL: True -> voltage measurement, False -> current measurement
        if dio._state[SW_MEAS_SEL_IDX]:
            self._generate_voltage(n, rng)
        else:
            self._generate_current(n, sample_rate, rng)

    def _generate_voltage(self, n: int, rng: np.random.Generator) -> None:
        """Voltage-meter mode: a per-pin quasi-DC voltage on both channels."""
        v0 = rng.uniform(-0.5, 2.5)
        v = v0 + rng.normal(0, 5e-3, size=n)
        self._channels[0]._data = v.copy()
        self._channels[1]._data = v

    def _generate_current(
        self, n: int, sample_rate: float, rng: np.random.Generator
    ) -> None:
        """Current-measurement mode (filter + resistance): double-RC step."""
        t = np.arange(n) / sample_rate
        t_start = t[min(_STEP_SAMPLE, n - 1)]

        wg = self._device.analog_output.channel
        v_end = GAIN_FRONTEND * (wg["offset"] + wg["amplitude"]) or 1.5

        connected = self._device.digital_io.dac_connected
        if connected:
            c_filt = _C_FILT_NOM * (1 + rng.uniform(-0.15, 0.15))
            r_filt = _R_FILT_NOM * (1 + rng.uniform(-0.2, 0.2))
        else:
            c_filt = 0.0
            r_filt = _R_FILT_NOM
        c_tot = _C_PAR + c_filt

        # Settle just below V_end (open circuit at DC) so the resistance
        # voltage-divider estimate stays a clean, large finite value rather than
        # diverging at ratio == 1; still well within the filter "settled" band.
        v_asymptote = v_end * 0.999
        v = step_double_rc(
            t.copy(), _C_PAR, max(c_filt, 1e-15), _R_AFE, max(r_filt, 1.0),
            t_start, v_asymptote,
        )
        v = v + rng.normal(0, 1e-3, size=n)

        # sense current: leakage + a charging transient whose integral is
        # V_end * C_tot, so numerical integration recovers the capacitance.
        tau = _R_AFE * c_tot
        i = np.full(n, _I_LEAK)
        mask = t >= t_start
        i[mask] += (v_end / _R_AFE) * np.exp(-(t[mask] - t_start) / tau)
        i = i + rng.normal(0, 2e-8, size=n)

        self._channels[0]._data = v
        self._channels[1]._data = i * (R_SENSE * SENSE_MAG)  # raw sense voltage

    def single(
        self,
        sample_rate: float = 1e6,
        buffer_size: int = 8192,
        configure: bool = True,
        start: bool = True,
    ) -> None:
        self._generate(sample_rate, buffer_size)

    def record(
        self,
        sample_rate: float = 1e6,
        buffer_size: int = 8192,
        configure: bool = True,
        start: bool = True,
    ) -> None:
        self._generate(sample_rate, buffer_size)


class _MockWavegenChannel:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {"offset": 0.0, "amplitude": 0.0, "function": None}

    def setup(self, **kwargs: Any) -> None:
        self.params.update(kwargs)

    def __getitem__(self, key: str) -> Any:  # convenience for the scope
        return self.params.get(key, 0.0)


class _MockWavegen:
    def __init__(self) -> None:
        self.channel = _MockWavegenChannel()

    def __getitem__(self, idx: int) -> _MockWavegenChannel:
        return self.channel


class _MockAnalogIoNode:
    def __init__(self) -> None:
        self.value: Any = 0.0


class _MockAnalogIo:
    def __init__(self) -> None:
        self._nodes: dict[tuple[int, int], _MockAnalogIoNode] = {}
        self.master_enable = False

    def __getitem__(self, ch: int) -> "_MockAnalogIoChannel":
        return _MockAnalogIoChannel(self, ch)


class _MockAnalogIoChannel:
    def __init__(self, parent: _MockAnalogIo, ch: int) -> None:
        self._parent = parent
        self._ch = ch

    def __getitem__(self, node: int) -> _MockAnalogIoNode:
        key = (self._ch, node)
        if key not in self._parent._nodes:
            self._parent._nodes[key] = _MockAnalogIoNode()
        return self._parent._nodes[key]


class MockDevice:
    """A stand-in for a ``dwfpy`` device that needs no hardware."""

    def __init__(self) -> None:
        self.analog_io = _MockAnalogIo()
        self.digital_io = _MockDigitalIo()
        self.analog_input = _MockScope(self)
        self.analog_output = _MockWavegen()

    # allow use as a context manager, mirroring ``dwf.Device()``
    def __enter__(self) -> "MockDevice":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


# --------------------------------------------------------------------------- #
# Real / mock selection
# --------------------------------------------------------------------------- #
def _mock_device_list() -> list[dict[str, Any]]:
    """Two fake devices so the Device Info panel can be demoed without hardware."""
    return [
        {
            "index": 0, "name": "Analog Discovery 3", "type": "Analog Discovery 3",
            "serial": "SN:210415A1B2C3", "id": "3", "revision": "C", "simulated": True,
        },
        {
            "index": 1, "name": "Analog Discovery 2", "type": "Analog Discovery 2",
            "serial": "SN:210244D4E5F6", "id": "2", "revision": "B", "simulated": True,
        },
    ]


def _enumerate_real() -> Any:
    """Enumerate real devices via ``dwfpy``.

    Raises if the ``dwfpy`` binding or the Digilent WaveForms runtime is
    unavailable. Note that a missing ``libdwf`` does NOT fail at ``import
    dwfpy`` — dwfpy stores the load error and re-raises it on the first library
    call (here), so this call is what surfaces a missing runtime.
    """
    import dwfpy as dwf

    return dwf.Device.enumerate()


def waveforms_runtime_available() -> bool:
    """Whether Digilent's WaveForms runtime (``libdwf``) can actually be used.

    Distinguishes a *missing runtime* from *no device attached*: both make
    :func:`enumerate_devices` return an empty list, but only a missing runtime
    means hardware can never work until WaveForms is installed. Because dwfpy
    defers a load failure to the first library call, a successful enumeration
    (even of zero devices) proves the runtime is present.
    """
    try:
        _enumerate_real()
    except Exception:
        return False
    return True


def enumerate_devices(force_mock: bool = False) -> list[dict[str, Any]]:
    """List attached Analog Discovery devices.

    Returns one dict per device with whatever identifying fields are readable
    (``name``, ``serial``, ``id``, ``revision``, ``type``). Returns a simulated
    list when ``force_mock`` is set; an empty list when the SDK is missing or no
    device is attached (use :func:`waveforms_runtime_available` to tell those
    two cases apart).
    """
    if force_mock:
        return _mock_device_list()
    try:
        devices = _enumerate_real()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for i, dev in enumerate(devices):
        info: dict[str, Any] = {"index": i}
        for key, attr in (
            ("name", "name"),
            ("serial", "serial_number"),
            ("id", "id"),
            ("revision", "revision"),
            ("user_name", "user_name"),
        ):
            try:
                info[key] = str(getattr(dev, attr))
            except Exception:
                pass
        info.setdefault("type", info.get("name", "Analog Discovery"))
        out.append(info)
    return out


@contextmanager
def open_device(serial: str | None = None, force_mock: bool = False) -> Iterator[Any]:
    """Yield a device to measure with.

    When ``force_mock`` is set, yields a :class:`MockDevice`. Otherwise opens
    the real ``dwfpy`` device with the given ``serial`` (or the first available
    one when ``serial`` is None) and lets any open error propagate — a real
    device that is requested but cannot be opened must NOT be silently replaced
    by a simulation, or the operator would think a real run happened when it did
    not. The caller surfaces the error to the user.
    """
    if force_mock:
        with MockDevice() as device:
            yield device
        return

    import dwfpy as dwf

    kwargs = {"serial_number": serial} if serial else {}
    with dwf.Device(**kwargs) as device:
        yield device
