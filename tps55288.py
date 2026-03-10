"""
Features:
- Full register map support
- Async I2C communication
- Output voltage control (0.8V - 22V)
- Output current limiting (0 - 6.35A with 10mΩ sense resistor)
- PFM/FPWM mode selection
- Internal/External feedback selection
- Cable droop compensation
- Protection features (OVP, OCP, SCP, thermal)
- Status monitoring
"""

import uasyncio as asyncio
from micropython import const
from machine import I2C, Pin

# =============================================================================
# REGISTER ADDRESSES
# =============================================================================

# Register addresses
REG_VREF_LSB = const(0x00)      # Reference voltage LSB
REG_VREF_MSB = const(0x01)      # Reference voltage MSB
REG_IOUT_LIMIT = const(0x02)    # Output current limit
REG_VOUT_SR = const(0x03)       # Output voltage slew rate
REG_VOUT_FS = const(0x04)       # Feedback selection
REG_CDC = const(0x05)           # Cable droop compensation
REG_MODE = const(0x06)          # Mode control
REG_STATUS = const(0x07)        # Operating status

# =============================================================================
# DEFAULT VALUES
# =============================================================================

DEFAULT_VREF_LSB = const(0xD2)      # 210 decimal -> 282mV reference
DEFAULT_VREF_MSB = const(0x00)
DEFAULT_IOUT_LIMIT = const(0xE4)    # Current limit enabled, 50mV
DEFAULT_VOUT_SR = const(0x01)       # 2.5mV/μs slew rate
DEFAULT_VOUT_FS = const(0x03)       # Internal FB, ratio 0.0564
DEFAULT_CDC = const(0xE0)           # All masks enabled, internal CDC, 0V rise
DEFAULT_MODE = const(0x20)          # Hiccup enabled, output disabled
DEFAULT_STATUS = const(0x03)        # Reserved status bits

# =============================================================================
# I2C ADDRESSES
# =============================================================================

I2C_ADDR_74H = const(0x74)  # Default I2C address
I2C_ADDR_75H = const(0x75)  # Alternative I2C address

# =============================================================================
# CONSTANTS
# =============================================================================

# Reference voltage range
VREF_MIN_MV = const(45)         # Minimum reference voltage (mV)
VREF_MAX_MV = const(1200)       # Maximum reference voltage (mV)
VREF_STEP_MV = 1.129            # Reference voltage step (mV/LSB)

# Output voltage range
VOUT_MIN_V = 0.8                # Minimum output voltage (V)
VOUT_MAX_V = 22.0               # Maximum output voltage (V)

# Input voltage range
VIN_MIN_V = 2.7                 # Minimum input voltage (V)
VIN_MAX_V = 36.0                # Maximum input voltage (V)

# Current limit
IOUT_LIMIT_MAX_MV = const(63)   # Maximum current sense voltage (mV * 2, 0.5mV steps)
IOUT_LIMIT_STEP_MV = 0.5        # Current limit step (mV/LSB)

# Internal feedback ratios
FB_RATIO_0 = 0.2256             # INTFB = 00, max 5V
FB_RATIO_1 = 0.1128             # INTFB = 01, max 10V
FB_RATIO_2 = 0.0752             # INTFB = 10, max 15V
FB_RATIO_3 = 0.0564             # INTFB = 11, max 20V (default)

# Output voltage steps per feedback ratio
VOUT_STEP_FB0 = 0.005           # 5mV step
VOUT_STEP_FB1 = 0.010           # 10mV step
VOUT_STEP_FB2 = 0.015           # 15mV step
VOUT_STEP_FB3 = 0.020           # 20mV step (default)

# Slew rates (mV/μs)
SLEW_RATE_1_25 = const(0)       # 1.25 mV/μs
SLEW_RATE_2_5 = const(1)        # 2.5 mV/μs (default)
SLEW_RATE_5 = const(2)          # 5 mV/μs
SLEW_RATE_10 = const(3)         # 10 mV/μs

# OCP delay settings
OCP_DELAY_128US = const(0)      # 128 μs (default)
OCP_DELAY_3MS = const(1)        # 1.024 x 3 ms
OCP_DELAY_6MS = const(2)        # 1.024 x 6 ms
OCP_DELAY_12MS = const(3)       # 1.024 x 12 ms

# CDC voltage rise settings (with 50mV at ISP-ISN)
CDC_RISE_0V = const(0)          # 0V rise (default)
CDC_RISE_100MV = const(1)       # 0.1V rise
CDC_RISE_200MV = const(2)       # 0.2V rise
CDC_RISE_300MV = const(3)       # 0.3V rise
CDC_RISE_400MV = const(4)       # 0.4V rise
CDC_RISE_500MV = const(5)       # 0.5V rise
CDC_RISE_600MV = const(6)       # 0.6V rise
CDC_RISE_700MV = const(7)       # 0.7V rise

# Operating modes (from STATUS register)
MODE_BOOST = const(0)           # Boost mode
MODE_BUCK = const(1)            # Buck mode
MODE_BUCK_BOOST = const(2)      # Buck-boost mode

# =============================================================================
# BIT MASKS
# =============================================================================

# REG_IOUT_LIMIT (0x02)
MASK_CURRENT_LIMIT_EN = const(0x80)
MASK_CURRENT_LIMIT_SETTING = const(0x7F)

# REG_VOUT_SR (0x03)
MASK_OCP_DELAY = const(0x30)
MASK_SLEW_RATE = const(0x03)

# REG_VOUT_FS (0x04)
MASK_FB = const(0x80)
MASK_INTFB = const(0x03)

# REG_CDC (0x05)
MASK_SC_MASK = const(0x80)
MASK_OCP_MASK = const(0x40)
MASK_OVP_MASK = const(0x20)
MASK_CDC_OPTION = const(0x08)
MASK_CDC = const(0x07)

# REG_MODE (0x06)
MASK_OE = const(0x80)
MASK_FSWDBL = const(0x40)
MASK_HICCUP = const(0x20)
MASK_DISCHG = const(0x10)
MASK_VCC = const(0x08)
MASK_I2CADD = const(0x04)
MASK_PFM = const(0x02)
MASK_MODE = const(0x01)

# REG_STATUS (0x07)
MASK_SCP = const(0x80)
MASK_OCP = const(0x40)
MASK_OVP = const(0x20)
MASK_STATUS = const(0x03)

# =============================================================================
# ENUMS / CONFIGURATION CLASSES
# =============================================================================

class FeedbackRatio:
    """Internal feedback ratio selection"""
    RATIO_5V_MAX = 0    # 0.2256 ratio, 5V max, 5mV step
    RATIO_10V_MAX = 1   # 0.1128 ratio, 10V max, 10mV step
    RATIO_15V_MAX = 2   # 0.0752 ratio, 15V max, 15mV step
    RATIO_20V_MAX = 3   # 0.0564 ratio, 20V max, 20mV step (default)
    
    _ratios = [FB_RATIO_0, FB_RATIO_1, FB_RATIO_2, FB_RATIO_3]
    _steps = [VOUT_STEP_FB0, VOUT_STEP_FB1, VOUT_STEP_FB2, VOUT_STEP_FB3]
    _max_vout = [5.0, 10.0, 15.0, 20.0]
    
    @classmethod
    def get_ratio(cls, index: int) -> float:
        return cls._ratios[index]
    
    @classmethod
    def get_step(cls, index: int) -> float:
        return cls._steps[index]
    
    @classmethod
    def get_max_vout(cls, index: int) -> float:
        return cls._max_vout[index]


class SlewRate:
    """Output voltage slew rate selection"""
    RATE_1_25_MV_US = 0     # 1.25 mV/μs
    RATE_2_5_MV_US = 1      # 2.5 mV/μs (default)
    RATE_5_MV_US = 2        # 5 mV/μs
    RATE_10_MV_US = 3       # 10 mV/μs


class OCPDelay:
    """Over-current protection delay selection"""
    DELAY_128US = 0         # 128 μs (default)
    DELAY_3MS = 1           # ~3 ms
    DELAY_6MS = 2           # ~6 ms
    DELAY_12MS = 3          # ~12 ms


class CDCRise:
    """Cable droop compensation voltage rise settings"""
    RISE_0V = 0             # 0V rise (default)
    RISE_100MV = 1          # 0.1V rise
    RISE_200MV = 2          # 0.2V rise
    RISE_300MV = 3          # 0.3V rise
    RISE_400MV = 4          # 0.4V rise
    RISE_500MV = 5          # 0.5V rise
    RISE_600MV = 6          # 0.6V rise
    RISE_700MV = 7          # 0.7V rise


class OperatingMode:
    """Converter operating mode from STATUS register"""
    BOOST = 0
    BUCK = 1
    BUCK_BOOST = 2
    
    _names = ['Boost', 'Buck', 'Buck-Boost', 'Unknown']
    
    @classmethod
    def name(cls, mode: int) -> str:
        if mode < 3:
            return cls._names[mode]
        return cls._names[3]


# =============================================================================
# STATUS DATACLASS
# =============================================================================

class TPS55288Status:
    """Status information from TPS55288"""
    
    def __init__(self, raw_status: int):
        self.raw = raw_status
        self.short_circuit = bool(raw_status & MASK_SCP)
        self.over_current = bool(raw_status & MASK_OCP)
        self.over_voltage = bool(raw_status & MASK_OVP)
        self.operating_mode = raw_status & MASK_STATUS
    
    @property
    def mode_name(self) -> str:
        return OperatingMode.name(self.operating_mode)
    
    @property
    def has_fault(self) -> bool:
        return self.short_circuit or self.over_current or self.over_voltage
    
    def __repr__(self) -> str:
        return (
            f"TPS55288Status(mode={self.mode_name}, "
            f"scp={self.short_circuit}, ocp={self.over_current}, "
            f"ovp={self.over_voltage})"
        )


# =============================================================================
# CONFIGURATION DATACLASS
# =============================================================================

class TPS55288Config:
    """Configuration holder for TPS55288 initialization"""
    
    def __init__(
        self,
        # Feedback configuration
        use_external_feedback: bool = False,
        internal_fb_ratio: int = FeedbackRatio.RATIO_20V_MAX,
        external_fb_top_resistor: float = 100000.0,  # 100kΩ typical
        external_fb_bottom_resistor: float = 5600.0, # For ~20V output
        
        # Operating mode
        pfm_mode: bool = True,          # PFM at light load (default)
        hiccup_mode: bool = True,       # Hiccup on short circuit (default)
        discharge_enabled: bool = False, # Discharge output when disabled
        
        # VCC source
        use_external_vcc: bool = False,  # Use internal LDO (default)
        
        # Double frequency in buck-boost mode
        frequency_doubling: bool = False,
        
        # Current sense resistor value (for current calculations)
        current_sense_resistor: float = 0.010,  # 10mΩ default on EVM
        
        # Slew rate
        slew_rate: int = SlewRate.RATE_2_5_MV_US,
        
        # OCP delay
        ocp_delay: int = OCPDelay.DELAY_128US,
        
        # CDC settings
        use_external_cdc: bool = False,
        internal_cdc_rise: int = CDCRise.RISE_0V,
        
        # Fault masks (enable/disable fault indication)
        sc_mask_enabled: bool = True,
        ocp_mask_enabled: bool = True,
        ovp_mask_enabled: bool = True,
    ):
        self.use_external_feedback = use_external_feedback
        self.internal_fb_ratio = internal_fb_ratio
        self.external_fb_top_resistor = external_fb_top_resistor
        self.external_fb_bottom_resistor = external_fb_bottom_resistor
        self.pfm_mode = pfm_mode
        self.hiccup_mode = hiccup_mode
        self.discharge_enabled = discharge_enabled
        self.use_external_vcc = use_external_vcc
        self.frequency_doubling = frequency_doubling
        self.current_sense_resistor = current_sense_resistor
        self.slew_rate = slew_rate
        self.ocp_delay = ocp_delay
        self.use_external_cdc = use_external_cdc
        self.internal_cdc_rise = internal_cdc_rise
        self.sc_mask_enabled = sc_mask_enabled
        self.ocp_mask_enabled = ocp_mask_enabled
        self.ovp_mask_enabled = ovp_mask_enabled


# =============================================================================
# EXCEPTION CLASSES
# =============================================================================

class TPS55288Error(Exception):
    """Base exception for TPS55288 errors"""
    pass


class TPS55288CommunicationError(TPS55288Error):
    """I2C communication error"""
    pass


class TPS55288ConfigurationError(TPS55288Error):
    """Configuration error"""
    pass


class TPS55288VoltageError(TPS55288Error):
    """Voltage out of range error"""
    pass


class TPS55288CurrentError(TPS55288Error):
    """Current out of range error"""
    pass


# =============================================================================
# ASYNC I2C WRAPPER
# =============================================================================

class AsyncI2C:
    """Async wrapper for MicroPython I2C with mutex protection"""
    
    def __init__(self, i2c: I2C):
        self._i2c = i2c
        self._lock = asyncio.Lock()
    
    async def readfrom_mem(self, addr: int, memaddr: int, nbytes: int) -> bytes:
        """Read from device memory with async lock"""
        async with self._lock:
            await asyncio.sleep_ms(0)  # Yield to scheduler
            try:
                return self._i2c.readfrom_mem(addr, memaddr, nbytes)
            except OSError as e:
                raise TPS55288CommunicationError(f"I2C read error: {e}")
    
    async def writeto_mem(self, addr: int, memaddr: int, buf: bytes) -> None:
        """Write to device memory with async lock"""
        async with self._lock:
            await asyncio.sleep_ms(0)  # Yield to scheduler
            try:
                self._i2c.writeto_mem(addr, memaddr, buf)
            except OSError as e:
                raise TPS55288CommunicationError(f"I2C write error: {e}")
    
    def scan(self) -> list:
        """Scan I2C bus for devices"""
        return self._i2c.scan()


# =============================================================================
# MAIN TPS55288 CLASS
# =============================================================================

class TPS55288:
    """
    Async MicroPython driver for TPS55288 Buck-Boost Converter.
    
    This class provides complete control over the TPS55288 including:
    - Output voltage control (0.8V - 22V)
    - Output current limiting
    - Protection features
    - Operating mode selection
    - Status monitoring
    
    Example usage:
        ```python
        import uasyncio as asyncio
        from machine import I2C, Pin
        from tps55288 import TPS55288, TPS55288Config
        
        async def main():
            i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
            
            # Create configuration
            config = TPS55288Config(
                use_external_feedback=False,
                internal_fb_ratio=3,  # 20V max
                pfm_mode=True,
                hiccup_mode=True,
            )
            
            # Initialize device
            tps = TPS55288(i2c, config=config)
            await tps.init()
            
            # Set output voltage
            await tps.set_output_voltage(12.0)
            
            # Enable output
            await tps.enable_output()
            
            # Read status
            status = await tps.get_status()
            print(f"Mode: {status.mode_name}")
        
        asyncio.run(main())
        ```
    """
    
    def __init__(
        self,
        i2c: I2C,
        address: int = I2C_ADDR_74H,
        config: TPS55288Config = None,
    ):
        """
        Initialize TPS55288 driver.
        
        Args:
            i2c: MicroPython I2C instance
            address: I2C address (0x74 or 0x75)
            config: Configuration object (uses defaults if None)
        """
        self._i2c = AsyncI2C(i2c)
        self._address = address
        self._config = config if config else TPS55288Config()
        
        # Cache for register values (reduces I2C traffic)
        self._reg_cache = {}
        
        # Current state tracking
        self._output_enabled = False
        self._current_vref = 0
        self._initialized = False
    
    # =========================================================================
    # INITIALIZATION
    # =========================================================================
    
    async def init(self) -> None:
        """
        Initialize the TPS55288 with the provided configuration.
        
        This method:
        1. Verifies I2C communication
        2. Applies all configuration settings
        3. Disables output (safety)
        """
        # Verify device is present
        if not await self._verify_device():
            raise TPS55288CommunicationError(
                f"TPS55288 not found at address 0x{self._address:02X}"
            )
        
        # Disable output first (safety)
        await self._write_register(REG_MODE, DEFAULT_MODE & ~MASK_OE)
        
        # Apply configuration
        await self._apply_config()
        
        self._initialized = True
    
    async def _verify_device(self) -> bool:
        """Verify TPS55288 is present on I2C bus"""
        try:
            devices = self._i2c.scan()
            return self._address in devices
        except:
            return False
    
    async def _apply_config(self) -> None:
        """Apply configuration to device registers"""
        cfg = self._config
        
        # Configure VOUT_FS (feedback selection)
        vout_fs = 0
        if cfg.use_external_feedback:
            vout_fs |= MASK_FB
        vout_fs |= (cfg.internal_fb_ratio & MASK_INTFB)
        await self._write_register(REG_VOUT_FS, vout_fs)
        
        # Configure VOUT_SR (slew rate and OCP delay)
        vout_sr = 0
        vout_sr |= (cfg.ocp_delay << 4) & MASK_OCP_DELAY
        vout_sr |= cfg.slew_rate & MASK_SLEW_RATE
        await self._write_register(REG_VOUT_SR, vout_sr)
        
        # Configure CDC
        cdc = 0
        if cfg.sc_mask_enabled:
            cdc |= MASK_SC_MASK
        if cfg.ocp_mask_enabled:
            cdc |= MASK_OCP_MASK
        if cfg.ovp_mask_enabled:
            cdc |= MASK_OVP_MASK
        if cfg.use_external_cdc:
            cdc |= MASK_CDC_OPTION
        cdc |= cfg.internal_cdc_rise & MASK_CDC
        await self._write_register(REG_CDC, cdc)
        
        # Configure MODE register
        mode = 0
        # OE (bit 7) - leave disabled initially
        if cfg.frequency_doubling:
            mode |= MASK_FSWDBL
        if cfg.hiccup_mode:
            mode |= MASK_HICCUP
        if cfg.discharge_enabled:
            mode |= MASK_DISCHG
        if cfg.use_external_vcc:
            mode |= MASK_VCC
        # I2CADD is determined by hardware (MODE pin resistor)
        if not cfg.pfm_mode:  # PFM bit = 1 means FPWM mode
            mode |= MASK_PFM
        # MODE bit = 1 means register control (not MODE pin)
        mode |= MASK_MODE
        
        await self._write_register(REG_MODE, mode)
        
        # Set default current limit (50mV = 5A with 10mΩ resistor)
        await self._write_register(REG_IOUT_LIMIT, DEFAULT_IOUT_LIMIT)
    
    # =========================================================================
    # LOW-LEVEL I2C OPERATIONS
    # =========================================================================
    
    async def _read_register(self, reg: int) -> int:
        """Read a single register"""
        data = await self._i2c.readfrom_mem(self._address, reg, 1)
        return data[0]
    
    async def _write_register(self, reg: int, value: int) -> None:
        """Write a single register"""
        await self._i2c.writeto_mem(self._address, reg, bytes([value & 0xFF]))
        self._reg_cache[reg] = value & 0xFF
    
    async def _read_registers(self, start_reg: int, count: int) -> bytes:
        """Read multiple consecutive registers"""
        return await self._i2c.readfrom_mem(self._address, start_reg, count)
    
    async def _write_registers(self, start_reg: int, data: bytes) -> None:
        """Write multiple consecutive registers"""
        await self._i2c.writeto_mem(self._address, start_reg, data)
        for i, val in enumerate(data):
            self._reg_cache[start_reg + i] = val
    
    async def _modify_register(self, reg: int, mask: int, value: int) -> int:
        """Read-modify-write a register with mask"""
        current = await self._read_register(reg)
        new_value = (current & ~mask) | (value & mask)
        await self._write_register(reg, new_value)
        return new_value
    
    # =========================================================================
    # OUTPUT ENABLE/DISABLE
    # =========================================================================
    
    async def enable_output(self) -> None:
        """
        Enable the converter output.
        
        This starts the soft-start sequence (4ms typical).
        """
        # Ensure OCP_MASK is 0 when enabling output
        cdc = await self._read_register(REG_CDC)
        if cdc & MASK_OCP_MASK:
            await self._modify_register(REG_CDC, MASK_OCP_MASK, 0)
        
        await self._modify_register(REG_MODE, MASK_OE, MASK_OE)
        self._output_enabled = True
        
        # Wait for soft-start to complete
        await asyncio.sleep_ms(5)
        
        # Re-enable OCP mask after startup
        if self._config.ocp_mask_enabled:
            await self._modify_register(REG_CDC, MASK_OCP_MASK, MASK_OCP_MASK)
    
    async def disable_output(self) -> None:
        """
        Disable the converter output.
        
        If discharge is enabled in config, output will be discharged.
        """
        await self._modify_register(REG_MODE, MASK_OE, 0)
        self._output_enabled = False
    
    async def is_output_enabled(self) -> bool:
        """Check if output is enabled"""
        mode = await self._read_register(REG_MODE)
        self._output_enabled = bool(mode & MASK_OE)
        return self._output_enabled
    
    # =========================================================================
    # OUTPUT VOLTAGE CONTROL
    # =========================================================================
    
    async def set_output_voltage(self, voltage: float) -> float:
        """
        Set the output voltage.
        
        Args:
            voltage: Desired output voltage in volts (0.8V - 22V)
            
        Returns:
            Actual voltage that was set (due to DAC quantization)
            
        Raises:
            TPS55288VoltageError: If voltage is out of range
        """
        if voltage < VOUT_MIN_V or voltage > VOUT_MAX_V:
            raise TPS55288VoltageError(
                f"Voltage {voltage}V out of range ({VOUT_MIN_V}V - {VOUT_MAX_V}V)"
            )
        
        if self._config.use_external_feedback:
            return await self._set_voltage_external_fb(voltage)
        else:
            return await self._set_voltage_internal_fb(voltage)
    
    async def _set_voltage_internal_fb(self, voltage: float) -> float:
        """Set voltage using internal feedback divider"""
        ratio_idx = self._config.internal_fb_ratio
        fb_ratio = FeedbackRatio.get_ratio(ratio_idx)
        max_vout = FeedbackRatio.get_max_vout(ratio_idx)
        step = FeedbackRatio.get_step(ratio_idx)
        
        if voltage > max_vout:
            raise TPS55288VoltageError(
                f"Voltage {voltage}V exceeds max {max_vout}V for feedback ratio {ratio_idx}"
            )
        
        # Calculate VREF from VOUT
        # VOUT = VREF / FB_RATIO
        vref_mv = voltage * fb_ratio * 1000  # Convert to mV
        
        # Clamp VREF to valid range
        vref_mv = max(VREF_MIN_MV, min(VREF_MAX_MV, vref_mv))
        
        # Calculate 10-bit DAC value
        # DAC value = (VREF - 45mV) / 1.129mV
        dac_value = int((vref_mv - VREF_MIN_MV) / VREF_STEP_MV)
        dac_value = max(0, min(0x3FF, dac_value))  # 10-bit limit
        
        # Write to registers (LSB first, then MSB to trigger update)
        lsb = dac_value & 0xFF
        msb = (dac_value >> 8) & 0x03
        
        await self._write_register(REG_VREF_LSB, lsb)
        await self._write_register(REG_VREF_MSB, msb)
        
        # Calculate actual voltage set
        actual_vref_mv = VREF_MIN_MV + (dac_value * VREF_STEP_MV)
        actual_vout = actual_vref_mv / (fb_ratio * 1000)
        
        self._current_vref = dac_value
        
        return actual_vout
    
    async def _set_voltage_external_fb(self, voltage: float) -> float:
        """Set voltage using external feedback divider"""
        cfg = self._config
        
        # With external FB: VOUT = VREF * (1 + R_TOP/R_BOTTOM)
        fb_gain = 1 + (cfg.external_fb_top_resistor / cfg.external_fb_bottom_resistor)
        
        # Calculate required VREF
        vref_mv = (voltage / fb_gain) * 1000
        
        # Clamp VREF
        vref_mv = max(VREF_MIN_MV, min(VREF_MAX_MV, vref_mv))
        
        # Calculate 10-bit DAC value
        dac_value = int((vref_mv - VREF_MIN_MV) / VREF_STEP_MV)
        dac_value = max(0, min(0x3FF, dac_value))
        
        # Write to registers
        lsb = dac_value & 0xFF
        msb = (dac_value >> 8) & 0x03
        
        await self._write_register(REG_VREF_LSB, lsb)
        await self._write_register(REG_VREF_MSB, msb)
        
        # Calculate actual voltage
        actual_vref_mv = VREF_MIN_MV + (dac_value * VREF_STEP_MV)
        actual_vout = (actual_vref_mv / 1000) * fb_gain
        
        self._current_vref = dac_value
        
        return actual_vout
    
    async def get_output_voltage_setting(self) -> float:
        """
        Read the current output voltage setting.
        
        Returns:
            Currently configured output voltage in volts
        """
        # Read VREF registers
        lsb = await self._read_register(REG_VREF_LSB)
        msb = await self._read_register(REG_VREF_MSB)
        
        dac_value = lsb | ((msb & 0x03) << 8)
        vref_mv = VREF_MIN_MV + (dac_value * VREF_STEP_MV)
        
        if self._config.use_external_feedback:
            cfg = self._config
            fb_gain = 1 + (cfg.external_fb_top_resistor / cfg.external_fb_bottom_resistor)
            return (vref_mv / 1000) * fb_gain
        else:
            fb_ratio = FeedbackRatio.get_ratio(self._config.internal_fb_ratio)
            return vref_mv / (fb_ratio * 1000)
    
    async def set_voltage_raw(self, dac_value: int) -> None:
        """
        Set voltage using raw 10-bit DAC value.
        
        Args:
            dac_value: 10-bit value (0-1023)
        """
        dac_value = max(0, min(0x3FF, dac_value))
        lsb = dac_value & 0xFF
        msb = (dac_value >> 8) & 0x03
        
        await self._write_register(REG_VREF_LSB, lsb)
        await self._write_register(REG_VREF_MSB, msb)
        self._current_vref = dac_value
    
    async def get_voltage_raw(self) -> int:
        """
        Get raw 10-bit DAC value.
        
        Returns:
            Current DAC value (0-1023)
        """
        lsb = await self._read_register(REG_VREF_LSB)
        msb = await self._read_register(REG_VREF_MSB)
        return lsb | ((msb & 0x03) << 8)
    
    # =========================================================================
    # CURRENT LIMIT CONTROL
    # =========================================================================
    
    async def set_current_limit(self, current_amps: float) -> float:
        """
        Set the output current limit.
        
        Args:
            current_amps: Current limit in amperes
            
        Returns:
            Actual current limit set (due to quantization)
            
        Note:
            Maximum current depends on current sense resistor.
            With default 10mΩ resistor: max 6.35A, min 0A.
        """
        rsense = self._config.current_sense_resistor
        
        # Calculate sense voltage: V = I * R
        sense_mv = current_amps * rsense * 1000
        
        # Max sense voltage is 63.5mV
        max_sense_mv = 63.5
        if sense_mv > max_sense_mv:
            sense_mv = max_sense_mv
        if sense_mv < 0:
            sense_mv = 0
        
        # Calculate register value (0.5mV steps)
        reg_value = int(sense_mv / IOUT_LIMIT_STEP_MV)
        reg_value = max(0, min(127, reg_value))  # 7-bit value
        
        # Preserve current limit enable bit
        current_reg = await self._read_register(REG_IOUT_LIMIT)
        new_reg = (current_reg & MASK_CURRENT_LIMIT_EN) | reg_value
        
        await self._write_register(REG_IOUT_LIMIT, new_reg)
        
        # Calculate actual current limit
        actual_sense_mv = reg_value * IOUT_LIMIT_STEP_MV
        actual_current = actual_sense_mv / (rsense * 1000)
        
        return actual_current
    
    async def get_current_limit(self) -> float:
        """
        Get the current limit setting.
        
        Returns:
            Current limit in amperes
        """
        reg = await self._read_register(REG_IOUT_LIMIT)
        reg_value = reg & MASK_CURRENT_LIMIT_SETTING
        
        sense_mv = reg_value * IOUT_LIMIT_STEP_MV
        return sense_mv / (self._config.current_sense_resistor * 1000)
    
    async def enable_current_limit(self) -> None:
        """Enable the output current limit feature"""
        await self._modify_register(REG_IOUT_LIMIT, MASK_CURRENT_LIMIT_EN, MASK_CURRENT_LIMIT_EN)
    
    async def disable_current_limit(self) -> None:
        """Disable the output current limit feature"""
        await self._modify_register(REG_IOUT_LIMIT, MASK_CURRENT_LIMIT_EN, 0)
    
    async def is_current_limit_enabled(self) -> bool:
        """Check if current limit is enabled"""
        reg = await self._read_register(REG_IOUT_LIMIT)
        return bool(reg & MASK_CURRENT_LIMIT_EN)
    
    async def set_current_limit_raw(self, value: int) -> None:
        """
        Set current limit using raw register value.
        
        Args:
            value: 7-bit value (0-127), 0.5mV per step
        """
        value = max(0, min(127, value))
        current_reg = await self._read_register(REG_IOUT_LIMIT)
        new_reg = (current_reg & MASK_CURRENT_LIMIT_EN) | value
        await self._write_register(REG_IOUT_LIMIT, new_reg)
    
    # =========================================================================
    # SLEW RATE CONTROL
    # =========================================================================
    
    async def set_slew_rate(self, rate: int) -> None:
        """
        Set output voltage slew rate.
        
        Args:
            rate: SlewRate.RATE_1_25_MV_US, RATE_2_5_MV_US, 
                  RATE_5_MV_US, or RATE_10_MV_US
        """
        rate = max(0, min(3, rate))
        await self._modify_register(REG_VOUT_SR, MASK_SLEW_RATE, rate)
    
    async def get_slew_rate(self) -> int:
        """
        Get current slew rate setting.
        
        Returns:
            Slew rate enum value
        """
        reg = await self._read_register(REG_VOUT_SR)
        return reg & MASK_SLEW_RATE
    
    # =========================================================================
    # OCP DELAY CONTROL
    # =========================================================================
    
    async def set_ocp_delay(self, delay: int) -> None:
        """
        Set over-current protection response delay.
        
        Args:
            delay: OCPDelay.DELAY_128US, DELAY_3MS, DELAY_6MS, or DELAY_12MS
        """
        delay = max(0, min(3, delay))
        await self._modify_register(REG_VOUT_SR, MASK_OCP_DELAY, delay << 4)
    
    async def get_ocp_delay(self) -> int:
        """
        Get current OCP delay setting.
        
        Returns:
            OCP delay enum value
        """
        reg = await self._read_register(REG_VOUT_SR)
        return (reg & MASK_OCP_DELAY) >> 4
    
    # =========================================================================
    # FEEDBACK CONFIGURATION
    # =========================================================================
    
    async def set_internal_feedback(self, ratio: int = FeedbackRatio.RATIO_20V_MAX) -> None:
        """
        Configure for internal feedback operation.
        
        Args:
            ratio: FeedbackRatio enum value (0-3)
        """
        ratio = max(0, min(3, ratio))
        reg = ratio & MASK_INTFB  # Clear FB bit for internal feedback
        await self._write_register(REG_VOUT_FS, reg)
        self._config.use_external_feedback = False
        self._config.internal_fb_ratio = ratio
    
    async def set_external_feedback(self) -> None:
        """
        Configure for external feedback operation.
        
        When using external feedback, the FB/INT pin becomes feedback input.
        """
        await self._modify_register(REG_VOUT_FS, MASK_FB, MASK_FB)
        self._config.use_external_feedback = True
    
    async def get_feedback_mode(self) -> tuple:
        """
        Get current feedback mode configuration.
        
        Returns:
            Tuple (is_external: bool, internal_ratio: int)
        """
        reg = await self._read_register(REG_VOUT_FS)
        is_external = bool(reg & MASK_FB)
        ratio = reg & MASK_INTFB
        return (is_external, ratio)
    
    # =========================================================================
    # CABLE DROOP COMPENSATION
    # =========================================================================
    
    async def set_cdc_internal(self, rise: int = CDCRise.RISE_0V) -> None:
        """
        Configure internal cable droop compensation.
        
        Args:
            rise: CDCRise enum value (0-7)
                  Adds 0V to 0.7V output voltage rise with 50mV sense voltage
        """
        rise = max(0, min(7, rise))
        reg = await self._read_register(REG_CDC)
        reg &= ~(MASK_CDC_OPTION | MASK_CDC)  # Clear CDC_OPTION and CDC bits
        reg |= rise & MASK_CDC
        await self._write_register(REG_CDC, reg)
    
    async def set_cdc_external(self) -> None:
        """
        Configure for external CDC (resistor at CDC pin).
        
        Use this when using external resistor for compensation.
        """
        await self._modify_register(REG_CDC, MASK_CDC_OPTION, MASK_CDC_OPTION)
    
    async def get_cdc_config(self) -> tuple:
        """
        Get CDC configuration.
        
        Returns:
            Tuple (is_external: bool, internal_rise: int)
        """
        reg = await self._read_register(REG_CDC)
        is_external = bool(reg & MASK_CDC_OPTION)
        rise = reg & MASK_CDC
        return (is_external, rise)
    
    # =========================================================================
    # OPERATING MODE CONTROL
    # =========================================================================
    
    async def set_pfm_mode(self, enabled: bool = True) -> None:
        """
        Set PFM (Pulse Frequency Modulation) mode for light load.
        
        Args:
            enabled: True for PFM mode, False for forced PWM mode
        """
        if enabled:
            await self._modify_register(REG_MODE, MASK_PFM, 0)  # PFM bit = 0 means PFM mode
        else:
            await self._modify_register(REG_MODE, MASK_PFM, MASK_PFM)  # PFM bit = 1 means FPWM
        self._config.pfm_mode = enabled
    
    async def set_fpwm_mode(self) -> None:
        """Set forced PWM mode (constant frequency even at light load)"""
        await self.set_pfm_mode(False)
    
    async def is_pfm_mode(self) -> bool:
        """Check if PFM mode is enabled"""
        reg = await self._read_register(REG_MODE)
        return not bool(reg & MASK_PFM)
    
    async def set_hiccup_mode(self, enabled: bool = True) -> None:
        """
        Enable/disable hiccup mode for short circuit protection.
        
        Args:
            enabled: True to enable hiccup mode (default)
        """
        if enabled:
            await self._modify_register(REG_MODE, MASK_HICCUP, MASK_HICCUP)
        else:
            await self._modify_register(REG_MODE, MASK_HICCUP, 0)
        self._config.hiccup_mode = enabled
    
    async def is_hiccup_enabled(self) -> bool:
        """Check if hiccup mode is enabled"""
        reg = await self._read_register(REG_MODE)
        return bool(reg & MASK_HICCUP)
    
    async def set_discharge(self, enabled: bool) -> None:
        """
        Enable/disable output discharge when device is disabled.
        
        Args:
            enabled: True to enable output discharge
        """
        if enabled:
            await self._modify_register(REG_MODE, MASK_DISCHG, MASK_DISCHG)
        else:
            await self._modify_register(REG_MODE, MASK_DISCHG, 0)
        self._config.discharge_enabled = enabled
    
    async def is_discharge_enabled(self) -> bool:
        """Check if output discharge is enabled"""
        reg = await self._read_register(REG_MODE)
        return bool(reg & MASK_DISCHG)
    
    async def set_frequency_doubling(self, enabled: bool) -> None:
        """
        Enable/disable frequency doubling in buck-boost mode.
        
        Note: Not recommended at switching frequencies above 1.6MHz
        
        Args:
            enabled: True to enable frequency doubling
        """
        if enabled:
            await self._modify_register(REG_MODE, MASK_FSWDBL, MASK_FSWDBL)
        else:
            await self._modify_register(REG_MODE, MASK_FSWDBL, 0)
        self._config.frequency_doubling = enabled
    
    async def is_frequency_doubling_enabled(self) -> bool:
        """Check if frequency doubling is enabled"""
        reg = await self._read_register(REG_MODE)
        return bool(reg & MASK_FSWDBL)
    
    async def set_vcc_source(self, external: bool) -> None:
        """
        Select VCC power source.
        
        Args:
            external: True for external 5V supply, False for internal LDO
        """
        if external:
            await self._modify_register(REG_MODE, MASK_VCC, MASK_VCC)
        else:
            await self._modify_register(REG_MODE, MASK_VCC, 0)
        self._config.use_external_vcc = external
    
    async def is_external_vcc(self) -> bool:
        """Check if external VCC source is selected"""
        reg = await self._read_register(REG_MODE)
        return bool(reg & MASK_VCC)
    
    # =========================================================================
    # FAULT MASK CONTROL
    # =========================================================================
    
    async def set_fault_masks(
        self,
        sc_mask: bool = True,
        ocp_mask: bool = True,
        ovp_mask: bool = True
    ) -> None:
        """
        Configure fault indication masks.
        
        When a mask is enabled, the corresponding fault will trigger
        the FB/INT pin to go low.
        
        Args:
            sc_mask: Enable short circuit indication
            ocp_mask: Enable over-current indication
            ovp_mask: Enable over-voltage indication
        """
        reg = await self._read_register(REG_CDC)
        reg &= ~(MASK_SC_MASK | MASK_OCP_MASK | MASK_OVP_MASK)
        if sc_mask:
            reg |= MASK_SC_MASK
        if ocp_mask:
            reg |= MASK_OCP_MASK
        if ovp_mask:
            reg |= MASK_OVP_MASK
        await self._write_register(REG_CDC, reg)
        
        self._config.sc_mask_enabled = sc_mask
        self._config.ocp_mask_enabled = ocp_mask
        self._config.ovp_mask_enabled = ovp_mask
    
    async def get_fault_masks(self) -> tuple:
        """
        Get fault mask configuration.
        
        Returns:
            Tuple (sc_mask: bool, ocp_mask: bool, ovp_mask: bool)
        """
        reg = await self._read_register(REG_CDC)
        return (
            bool(reg & MASK_SC_MASK),
            bool(reg & MASK_OCP_MASK),
            bool(reg & MASK_OVP_MASK)
        )
    
    # =========================================================================
    # STATUS READING
    # =========================================================================
    
    async def get_status(self) -> TPS55288Status:
        """
        Read and parse the status register.
        
        Note: Reading the status register clears the fault bits.
        
        Returns:
            TPS55288Status object with fault flags and operating mode
        """
        reg = await self._read_register(REG_STATUS)
        return TPS55288Status(reg)
    
    async def get_operating_mode(self) -> int:
        """
        Get current operating mode (buck/boost/buck-boost).
        
        Returns:
            OperatingMode enum value
        """
        reg = await self._read_register(REG_STATUS)
        return reg & MASK_STATUS
    
    async def has_short_circuit(self) -> bool:
        """
        Check if short circuit fault occurred.
        
        Note: Reading clears the fault bit.
        """
        reg = await self._read_register(REG_STATUS)
        return bool(reg & MASK_SCP)
    
    async def has_over_current(self) -> bool:
        """
        Check if over-current fault occurred.
        
        Note: Reading clears the fault bit.
        """
        reg = await self._read_register(REG_STATUS)
        return bool(reg & MASK_OCP)
    
    async def has_over_voltage(self) -> bool:
        """
        Check if over-voltage fault occurred.
        
        Note: Reading clears the fault bit.
        """
        reg = await self._read_register(REG_STATUS)
        return bool(reg & MASK_OVP)
    
    async def clear_faults(self) -> TPS55288Status:
        """
        Clear fault flags by reading status register.
        
        Returns:
            Status that was cleared
        """
        return await self.get_status()
    
    # =========================================================================
    # RAW REGISTER ACCESS
    # =========================================================================
    
    async def read_all_registers(self) -> dict:
        """
        Read all registers and return as dictionary.
        
        Returns:
            Dictionary mapping register names to values
        """
        regs = {}
        regs['VREF_LSB'] = await self._read_register(REG_VREF_LSB)
        regs['VREF_MSB'] = await self._read_register(REG_VREF_MSB)
        regs['IOUT_LIMIT'] = await self._read_register(REG_IOUT_LIMIT)
        regs['VOUT_SR'] = await self._read_register(REG_VOUT_SR)
        regs['VOUT_FS'] = await self._read_register(REG_VOUT_FS)
        regs['CDC'] = await self._read_register(REG_CDC)
        regs['MODE'] = await self._read_register(REG_MODE)
        regs['STATUS'] = await self._read_register(REG_STATUS)
        return regs
    
    async def write_register_raw(self, address: int, value: int) -> None:
        """
        Write raw value to register.
        
        Args:
            address: Register address (0x00 - 0x07)
            value: 8-bit value to write
        """
        await self._write_register(address, value)
    
    async def read_register_raw(self, address: int) -> int:
        """
        Read raw value from register.
        
        Args:
            address: Register address (0x00 - 0x07)
            
        Returns:
            8-bit register value
        """
        return await self._read_register(address)
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    async def soft_reset(self) -> None:
        """
        Perform soft reset by disabling output and re-applying configuration.
        
        This does NOT reset registers to defaults - use hardware reset for that.
        """
        await self.disable_output()
        await asyncio.sleep_ms(10)
        await self._apply_config()
    
    async def get_full_state(self) -> dict:
        """
        Get complete device state as dictionary.
        
        Returns:
            Dictionary with all configuration and status information
        """
        regs = await self.read_all_registers()
        
        # Calculate derived values
        vref_dac = regs['VREF_LSB'] | ((regs['VREF_MSB'] & 0x03) << 8)
        vref_mv = VREF_MIN_MV + (vref_dac * VREF_STEP_MV)
        
        # Feedback config
        is_external_fb = bool(regs['VOUT_FS'] & MASK_FB)
        fb_ratio_idx = regs['VOUT_FS'] & MASK_INTFB
        
        if is_external_fb:
            cfg = self._config
            fb_gain = 1 + (cfg.external_fb_top_resistor / cfg.external_fb_bottom_resistor)
            vout_setting = (vref_mv / 1000) * fb_gain
        else:
            fb_ratio = FeedbackRatio.get_ratio(fb_ratio_idx)
            vout_setting = vref_mv / (fb_ratio * 1000)
        
        # Current limit
        ilim_enabled = bool(regs['IOUT_LIMIT'] & MASK_CURRENT_LIMIT_EN)
        ilim_raw = regs['IOUT_LIMIT'] & MASK_CURRENT_LIMIT_SETTING
        ilim_mv = ilim_raw * IOUT_LIMIT_STEP_MV
        ilim_amps = ilim_mv / (self._config.current_sense_resistor * 1000)
        
        # Status
        status = TPS55288Status(regs['STATUS'])
        
        return {
            'registers': regs,
            'vref_dac': vref_dac,
            'vref_mv': vref_mv,
            'vout_setting': vout_setting,
            'output_enabled': bool(regs['MODE'] & MASK_OE),
            'feedback': {
                'external': is_external_fb,
                'internal_ratio': fb_ratio_idx,
            },
            'current_limit': {
                'enabled': ilim_enabled,
                'raw': ilim_raw,
                'sense_mv': ilim_mv,
                'amps': ilim_amps,
            },
            'slew_rate': regs['VOUT_SR'] & MASK_SLEW_RATE,
            'ocp_delay': (regs['VOUT_SR'] & MASK_OCP_DELAY) >> 4,
            'pfm_mode': not bool(regs['MODE'] & MASK_PFM),
            'hiccup_enabled': bool(regs['MODE'] & MASK_HICCUP),
            'discharge_enabled': bool(regs['MODE'] & MASK_DISCHG),
            'freq_doubling': bool(regs['MODE'] & MASK_FSWDBL),
            'external_vcc': bool(regs['MODE'] & MASK_VCC),
            'cdc': {
                'external': bool(regs['CDC'] & MASK_CDC_OPTION),
                'internal_rise': regs['CDC'] & MASK_CDC,
            },
            'fault_masks': {
                'sc': bool(regs['CDC'] & MASK_SC_MASK),
                'ocp': bool(regs['CDC'] & MASK_OCP_MASK),
                'ovp': bool(regs['CDC'] & MASK_OVP_MASK),
            },
            'status': {
                'mode': status.mode_name,
                'short_circuit': status.short_circuit,
                'over_current': status.over_current,
                'over_voltage': status.over_voltage,
            },
        }
    
    # =========================================================================
    # PROPERTIES
    # =========================================================================
    
    @property
    def address(self) -> int:
        """Get I2C address"""
        return self._address
    
    @property
    def config(self) -> TPS55288Config:
        """Get current configuration"""
        return self._config
    
    @property
    def initialized(self) -> bool:
        """Check if device is initialized"""
        return self._initialized


# =============================================================================
# VOLTAGE/CURRENT CALCULATION HELPERS
# =============================================================================

def calculate_feedback_resistors(
    vout: float,
    vref: float = 1.0,
    r_top: float = 100000.0
) -> float:
    """
    Calculate bottom resistor for external feedback divider.
    
    Args:
        vout: Desired output voltage
        vref: Reference voltage (default 1.0V for mid-range)
        r_top: Top resistor value (default 100kΩ)
        
    Returns:
        Required bottom resistor value in ohms
    """
    # VOUT = VREF * (1 + R_TOP/R_BOT)
    # R_BOT = R_TOP / (VOUT/VREF - 1)
    return r_top / (vout / vref - 1)


def calculate_sense_resistor(
    max_current: float,
    max_sense_mv: float = 50.0
) -> float:
    """
    Calculate sense resistor for desired current limit.
    
    Args:
        max_current: Maximum output current in amps
        max_sense_mv: Maximum sense voltage (default 50mV)
        
    Returns:
        Required sense resistor value in ohms
    """
    # V = I * R
    return max_sense_mv / (max_current * 1000)


def calculate_switching_frequency_resistor(freq_khz: float) -> float:
    """
    Calculate FSW resistor for desired switching frequency.
    
    Args:
        freq_khz: Desired switching frequency in kHz (200-2200)
        
    Returns:
        Required resistor value in ohms
    """
    # fSW = 1000 / (0.05 * RFSW + 20) MHz
    # RFSW = (1000/fSW - 20) / 0.05 kΩ
    freq_mhz = freq_khz / 1000
    r_kohm = (1000 / freq_mhz - 20) / 0.05
    return r_kohm * 1000


def calculate_inductor_current_limit_resistor(
    current_limit: float,
    vout: float = 20.0
) -> float:
    """
    Calculate ILIM resistor for desired average inductor current limit.
    
    Args:
        current_limit: Desired current limit in amps
        vout: Output voltage (affects calculation)
        
    Returns:
        Required resistor value in ohms
        
    Formula:
        IAVG_LIMIT = min(1, 0.6*VOUT) * 330000 / RILIM
    """
    factor = min(1.0, 0.6 * vout)
    return (factor * 330000) / current_limit


