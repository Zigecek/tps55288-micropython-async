# TPS55288 - Async Buck-Boost Converter Driver

Asynchronous MicroPython driver for the TPS55288 I2C-controlled Buck-Boost converter.

## Features

- Output voltage control (0.8V - 22V)
- Output current limiting (0 - 6.35A with 10mOhm sense resistor)
- Internal/external feedback selection
- PFM/FPWM mode selection
- Cable droop compensation (CDC)
- Protection features (OVP, OCP, SCP, thermal)
- Status monitoring with fault detection
- Async I2C with mutex protection

## Quick Start

```python
import uasyncio as asyncio
from machine import I2C, Pin
from tps55288 import TPS55288, TPS55288Config

async def main():
    i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)

    config = TPS55288Config(
        use_external_feedback=False,
        internal_fb_ratio=3,   # 20V max range
        pfm_mode=True,
        hiccup_mode=True,
    )

    tps = TPS55288(i2c, config=config)
    await tps.init()

    await tps.set_output_voltage(12.0)
    await tps.set_current_limit(3.0)
    await tps.enable_output()

    status = await tps.get_status()
    print("Mode: {}".format(status.mode_name))
    print("Faults: {}".format(status.has_fault))

asyncio.run(main())
```

## Constructor

```python
TPS55288(i2c, address=0x74, config=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `i2c` | `I2C` | required | MicroPython I2C instance |
| `address` | `int` | `0x74` | I2C address (`0x74` or `0x75`) |
| `config` | `TPS55288Config` | `None` | Configuration object (uses defaults if `None`) |

## TPS55288Config

```python
TPS55288Config(
    use_external_feedback=False,
    internal_fb_ratio=3,             # FeedbackRatio.RATIO_20V_MAX
    external_fb_top_resistor=100000, # for external FB mode
    external_fb_bottom_resistor=5600,
    pfm_mode=True,
    hiccup_mode=True,
    discharge_enabled=False,
    use_external_vcc=False,
    frequency_doubling=False,
    current_sense_resistor=0.010,    # 10mOhm
    slew_rate=1,                     # SlewRate.RATE_2_5_MV_US
    ocp_delay=0,                     # OCPDelay.DELAY_128US
    use_external_cdc=False,
    internal_cdc_rise=0,             # CDCRise.RISE_0V
    sc_mask_enabled=True,
    ocp_mask_enabled=True,
    ovp_mask_enabled=True,
)
```

### Feedback Ratios

| Constant | Value | Max Vout | Step |
|----------|-------|----------|------|
| `FeedbackRatio.RATIO_5V_MAX` | 0 | 5V | 5mV |
| `FeedbackRatio.RATIO_10V_MAX` | 1 | 10V | 10mV |
| `FeedbackRatio.RATIO_15V_MAX` | 2 | 15V | 15mV |
| `FeedbackRatio.RATIO_20V_MAX` | 3 | 20V | 20mV |

## Methods

### Initialization

| Method | Description |
|--------|-------------|
| `await init()` | Initialize device, verify I2C, apply config, disable output (safety). |
| `await soft_reset()` | Disable output and re-apply configuration. |

### Output Control

| Method | Description |
|--------|-------------|
| `await enable_output()` | Enable converter output (4ms soft-start). |
| `await disable_output()` | Disable converter output. |
| `await is_output_enabled()` | Check if output is enabled. |

### Voltage Control

| Method | Returns | Description |
|--------|---------|-------------|
| `await set_output_voltage(voltage)` | `float` | Set output voltage (0.8-22V). Returns actual voltage set. |
| `await get_output_voltage_setting()` | `float` | Read current voltage setting. |
| `await set_voltage_raw(dac_value)` | - | Set voltage using raw 10-bit DAC value (0-1023). |
| `await get_voltage_raw()` | `int` | Get raw 10-bit DAC value. |

### Current Limit

| Method | Returns | Description |
|--------|---------|-------------|
| `await set_current_limit(amps)` | `float` | Set current limit in amps. Returns actual value. |
| `await get_current_limit()` | `float` | Get current limit in amps. |
| `await enable_current_limit()` | - | Enable current limiting. |
| `await disable_current_limit()` | - | Disable current limiting. |
| `await is_current_limit_enabled()` | `bool` | Check if current limit is enabled. |

### Operating Mode

| Method | Description |
|--------|-------------|
| `await set_pfm_mode(enabled=True)` | Enable PFM mode for light load efficiency. |
| `await set_fpwm_mode()` | Force constant-frequency PWM mode. |
| `await set_hiccup_mode(enabled=True)` | Enable/disable hiccup short-circuit protection. |
| `await set_discharge(enabled)` | Enable/disable output discharge when disabled. |
| `await set_frequency_doubling(enabled)` | Enable/disable frequency doubling in buck-boost. |
| `await set_vcc_source(external)` | Select VCC source (internal LDO or external 5V). |

### Slew Rate & OCP Delay

| Method | Description |
|--------|-------------|
| `await set_slew_rate(rate)` | Set output voltage slew rate (`SlewRate.*`). |
| `await set_ocp_delay(delay)` | Set OCP response delay (`OCPDelay.*`). |

### Feedback Configuration

| Method | Description |
|--------|-------------|
| `await set_internal_feedback(ratio)` | Switch to internal feedback with given ratio. |
| `await set_external_feedback()` | Switch to external feedback divider. |
| `await get_feedback_mode()` | Returns `(is_external, internal_ratio)`. |

### Cable Droop Compensation

| Method | Description |
|--------|-------------|
| `await set_cdc_internal(rise)` | Set internal CDC voltage rise (`CDCRise.*`). |
| `await set_cdc_external()` | Switch to external CDC resistor. |
| `await get_cdc_config()` | Returns `(is_external, internal_rise)`. |

### Fault Monitoring

| Method | Returns | Description |
|--------|---------|-------------|
| `await get_status()` | `TPS55288Status` | Read status register (clears fault bits). |
| `await get_operating_mode()` | `int` | Get mode: Boost(0), Buck(1), Buck-Boost(2). |
| `await has_short_circuit()` | `bool` | Check short circuit fault. |
| `await has_over_current()` | `bool` | Check over-current fault. |
| `await has_over_voltage()` | `bool` | Check over-voltage fault. |
| `await clear_faults()` | `TPS55288Status` | Clear faults by reading status. |
| `await set_fault_masks(sc, ocp, ovp)` | - | Configure fault indication masks. |

### Diagnostics

| Method | Returns | Description |
|--------|---------|-------------|
| `await get_full_state()` | `dict` | Complete device state (config + status + derived values). |
| `await read_all_registers()` | `dict` | Raw register dump. |

## TPS55288Status

Returned by `get_status()`:

| Attribute | Type | Description |
|-----------|------|-------------|
| `.short_circuit` | `bool` | SCP fault detected |
| `.over_current` | `bool` | OCP fault detected |
| `.over_voltage` | `bool` | OVP fault detected |
| `.operating_mode` | `int` | 0=Boost, 1=Buck, 2=Buck-Boost |
| `.mode_name` | `str` | Human-readable mode name |
| `.has_fault` | `bool` | True if any fault is active |

## Standalone Helper Functions

```python
from tps55288 import (
    calculate_feedback_resistors,
    calculate_sense_resistor,
    calculate_switching_frequency_resistor,
    calculate_inductor_current_limit_resistor,
)
```

| Function | Description |
|----------|-------------|
| `calculate_feedback_resistors(vout, vref=1.0, r_top=100000)` | Calculate bottom resistor for external FB divider. |
| `calculate_sense_resistor(max_current, max_sense_mv=50)` | Calculate sense resistor for desired current limit. |
| `calculate_switching_frequency_resistor(freq_khz)` | Calculate FSW resistor for desired switching frequency. |
| `calculate_inductor_current_limit_resistor(current_limit, vout=20)` | Calculate ILIM resistor for inductor current limit. |

## Enum Classes

| Class | Values |
|-------|--------|
| `SlewRate` | `RATE_1_25_MV_US`, `RATE_2_5_MV_US`, `RATE_5_MV_US`, `RATE_10_MV_US` |
| `OCPDelay` | `DELAY_128US`, `DELAY_3MS`, `DELAY_6MS`, `DELAY_12MS` |
| `CDCRise` | `RISE_0V` through `RISE_700MV` (8 levels, 100mV steps) |
| `OperatingMode` | `BOOST`, `BUCK`, `BUCK_BOOST` |

## Exceptions

| Exception | Description |
|-----------|-------------|
| `TPS55288Error` | Base exception |
| `TPS55288CommunicationError` | I2C communication failure |
| `TPS55288ConfigurationError` | Invalid configuration |
| `TPS55288VoltageError` | Voltage out of range |
| `TPS55288CurrentError` | Current out of range |
