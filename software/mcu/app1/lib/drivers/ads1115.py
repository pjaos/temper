from time import sleep_us


class ADS1115Error(Exception):
    pass


class ADS1115ADC():
    """@brief Responsible for communication with ADS1115 quad ADC devices."""

    ADDR_PIN_LOW_SLAVE_ADDR = 0b01001000
    ADDR_PIN_HIGH_SLAVE_ADDR = 0b01001001
    ADDR_PIN_SDA_SLAVE_ADDR = 0b01001010
    ADDR_PIN_SCL_SLAVE_ADDR = 0b01001011

    OS_CFG_REG_BIT = 15
    MUX_CFG_REG_BIT = 12
    PGA_CFG_REG_BIT = 9
    MODE_CFG_REG_BIT = 8
    DR_CFG_REG_BIT = 5
    COMP_MODE_CFG_REG_BIT = 4
    COMP_POL_CFG_REG_BIT = 3
    COMP_LAT_CFG_REG_BIT = 2
    COMP_QUE_CFG_REG_BIT = 0

    CONVERSION_REG = 0
    CONFIG_REG = 1
    LO_THREH_REG = 2
    HI_THREH_REG = 3

    FS_VOLTAGE_6144 = 6.144
    FS_VOLTAGE_4096 = 4.096
    FS_VOLTAGE_2048 = 2.048
    FS_VOLTAGE_1024 = 1.024
    FS_VOLTAGE_0512 = 0.512
    FS_VOLTAGE_0256 = 0.256

    SPS_8 = 8
    SPS_16 = 16
    SPS_32 = 32
    SPS_64 = 64
    SPS_128 = 128
    SPS_250 = 250
    SPS_475 = 475
    SPS_860 = 860

    def __init__(self, i2c, device_addr):
        """@brief Constructor
           @param i2c The I2C bus.
           @param device_addr The I2C device address."""
        self._i2c = i2c
        self._deviceAddr = device_addr

        # Define the default state of all config register parts
        self._os = 0b0
        self._mux = 0b000
        self._pga = 0b010
        self._mode = 0b1
        self._dr = 0b100
        self._compMode = 0b0
        self._compPol = 0b0
        self._compLat = 0b0
        self._compQue = 0b11

        self._adc0FSVoltage = None
        self._adc0SamplesPerSecond = None
        self._adc1FSVoltage = None
        self._adc1SamplesPerSecond = None
        self._adc2FSVoltage = None
        self._adc2SamplesPerSecond = None
        self._adc3FSVoltage = None
        self._adc3SamplesPerSecond = None

    def set_adc0(self, fs_voltage, samples_per_second):
        """@brief set parameters for ADC0.
           @param fs_voltage The full scale voltage.
           @param samples_per_second The samples per second."""
        self._adc0FSVoltage = fs_voltage
        self._adc0SamplesPerSecond = samples_per_second

    def set_adc1(self, fs_voltage, samples_per_second):
        """@brief set parameters for ADC1.
           @param fs_voltage The full scale voltage.
           @param samples_per_second The samples per second."""
        self._adc1FSVoltage = fs_voltage
        self._adc1SamplesPerSecond = samples_per_second

    def set_adc2(self, fs_voltage, samples_per_second):
        """@brief set parameters for ADC2.
           @param fs_voltage The full scale voltage.
           @param samples_per_second The samples per second."""
        self._adc2FSVoltage = fs_voltage
        self._adc2SamplesPerSecond = samples_per_second

    def set_adc3(self, fs_voltage, samples_per_second):
        """@brief set parameters for ADC3.
           @param fs_voltage The full scale voltage.
           @param samples_per_second The samples per second."""
        self._adc3FSVoltage = fs_voltage
        self._adc3SamplesPerSecond = samples_per_second

    def get_adc0(self, single_ended=True):
        """@brief Get the value from ADC0.
                  setADC0() must have been called first.
           @param single_ended If True then single ended mode.
                              If False then differential mod is
                              selected (A0 and A1 pins)."""
        self._mux = self._getMux(0, single_ended=single_ended)
        self._pga = self._getPGAValue(self._adc0FSVoltage)
        self._dr = self._getDataRate(self._adc0SamplesPerSecond)
        return self._getADCValue()

    def get_adc1(self, single_ended=True):
        """@brief Get the value from ADC1.
                  setADC1() must have been called first.
           @param single_ended If True then single ended mode.
                              If False then differential mod is
                              selected (A0 and A3 pins)."""
        self._mux = self._getMux(1, single_ended=single_ended)
        self._pga = self._getPGAValue(self._adc1FSVoltage)
        self._dr = self._getDataRate(self._adc1SamplesPerSecond)
        return self._getADCValue()

    def get_adc2(self, single_ended=True):
        """@brief Get the value from ADC2.
                  setADC2() must have been called first.
           @param single_ended If True then single ended mode.
                              If False then differential mod is
                              selected (A1 and A3 pins)."""
        self._mux = self._getMux(2, single_ended=single_ended)
        self._pga = self._getPGAValue(self._adc2FSVoltage)
        self._dr = self._getDataRate(self._adc2SamplesPerSecond)
        return self._getADCValue()

    def get_adc3(self, single_ended=True):
        """@brief Get the value from ADC3.
                  setADC3() must have been called first.
           @param single_ended If True then single ended mode.
                              If False then differential mod is
                              selected (A2 and A3 pins)."""
        self._mux = self._getMux(3, single_ended=single_ended)
        self._pga = self._getPGAValue(self._adc3FSVoltage)
        self._dr = self._getDataRate(self._adc3SamplesPerSecond)
        return self._getADCValue()

    def get_signed_value(self, adc, single_ended=True, bit_count=16):
        """@brief Get a signed value from an ADC.
           @param adc The ADC to read (0-3).
           @param single_ended If True read ADC in single ended mode.
           @param bit_count The number of bits read (16 or 12 for ADS1115)."""
        mask = 1 << (bit_count - 1)
        if adc == 0:
            adc_value = self.getADC0(single_ended=single_ended)
        elif adc == 1:
            adc_value = self.getADC1(single_ended=single_ended)
        elif adc == 2:
            adc_value = self.getADC2(single_ended=single_ended)
        elif adc == 3:
            adc_value = self.getADC3(single_ended=single_ended)
        else:
            raise Exception("{} is an invalid ADC.".format(adc))

        # -ve value
        if adc_value & mask:
            value = -((2**bit_count) - adc_value)
        # +ve value
        else:
            value = adc_value

        return value

    def _get_mux(self, adc, single_ended):
        """@brief Get the mux register value
           @param adc 0,1,2 or 3.
                  In single ended mode the ADC is the selected ADC.
                  In non single ended mode (differential) the following inputs are selected
                  0 = AIN0 and AIN1
                  1 = AIN0 and AIN3
                  2 = AIN1 and AIN3
                  3 = AIN2 and AIN3
           @param single_ended If True adc can be 0,1,2 or 3.
                              If False then adc can be 0 or 2."""
        if single_ended:
            if adc == 0:
                return 0b100
            elif adc == 1:
                return 0b101
            elif adc == 2:
                return 0b110
            elif adc == 3:
                return 0b111
            else:
                raise ADS1115Error(
                    "%s adc is invalid in single ended mode" %
                    (str(adc)))
        else:
            if adc == 0:
                return 0b000
            elif adc == 1:
                return 0b001
            elif adc == 2:
                return 0b010
            elif adc == 3:
                return 0b011
            else:
                raise ADS1115Error(
                    "%s adc is invalid in differential mode" %
                    (str(adc)))

    def _get_pga_value(self, fs_voltage):
        """@brief Get the PGA value associated with the full scale voltage."""
        if fs_voltage == 6.144:
            return 0b000
        elif fs_voltage == 4.096:
            return 0b001
        elif fs_voltage == 2.048:
            return 0b010
        elif fs_voltage == 1.024:
            return 0b011
        elif fs_voltage == 0.512:
            return 0b100
        elif fs_voltage == 0.256:
            return 0b101
        else:
            raise ADS1115Error(
                "%s is an invalid full scale (+/-) voltage" %
                (str(fs_voltage)))

    def _get_data_rate(self, samples_per_second):
        """@brief Get the data rate register value
           @param samples_per_second The sampels per second required."""
        if samples_per_second == 8:
            return 0b000
        elif samples_per_second == 16:
            return 0b001
        elif samples_per_second == 32:
            return 0b010
        elif samples_per_second == 64:
            return 0b011
        elif samples_per_second == 128:
            return 0b100
        elif samples_per_second == 250:
            return 0b101
        elif samples_per_second == 475:
            return 0b110
        elif samples_per_second == 860:
            return 0b111
        else:
            raise ADS1115Error(
                "%s is an invalid data rate." %
                (str(samples_per_second)))

    def _read16_bit_value(self, register):
        """@brief Read a 16 bit value from the devide (big endian)."""
        values = self._i2c.readfrom_mem(self._deviceAddr, register, 2)
        ret_val = values[0] << 8 | values[1]
        return ret_val

    def _write16_bit_value(self, register, value):
        """@brief write a 16 bit value to a register (big endian)."""
        byte_list = []
        byte_list.append((value >> 8) & 0xff)
        byte_list.append(value & 0xff)
        self._i2c.writeto_mem(self._deviceAddr, register, bytearray(byte_list))

    def _wait_for_conversion_completion(self, sleep_micro_seconds=100):
        """@brief wait for a conversion to complete."""
        while True:
            cfg_reg_state = self._read16BitValue(ADS1115ADC.CONFIG_REG)
            if cfg_reg_state & (1 << ADS1115ADC.OS_CFG_REG_BIT):
                break
            # We used to spin lock here and this generated occasional
            # 'IOError: I2C transaction failed.' errors
            # so we now wait for a short period of time to elapse.
            # Note that this may slow execution of i2c device access.
            sleep_us(sleep_micro_seconds)

    def _get_adc_value(self):
        """@brief This sets the config and poll the device until conversion is
                  complete, then returns the converted value."""
        # Set start conversion bit
        self._os = 1

        regValue16Bit = self._os << ADS1115ADC.OS_CFG_REG_BIT |\
            self._mux << ADS1115ADC.MUX_CFG_REG_BIT |\
            self._pga << ADS1115ADC.PGA_CFG_REG_BIT |\
            self._mode << ADS1115ADC.MODE_CFG_REG_BIT |\
            self._dr << ADS1115ADC.DR_CFG_REG_BIT |\
            self._compMode << ADS1115ADC.COMP_MODE_CFG_REG_BIT |\
            self._compPol << ADS1115ADC.COMP_POL_CFG_REG_BIT |\
            self._compLat << ADS1115ADC.COMP_LAT_CFG_REG_BIT |\
            self._compQue << ADS1115ADC.COMP_QUE_CFG_REG_BIT

        byte_list = []
        byte_list.append((regValue16Bit >> 8) & 0xff)
        byte_list.append(regValue16Bit & 0xff)

        # Called in case a conversion is in progress
        self._waitForConversionCompletion()

        # Initiate a conversion
        self._write16BitValue(ADS1115ADC.CONFIG_REG, regValue16Bit)

        # Wait for the conversion to complete
        self._waitForConversionCompletion()

        # read the ADC value
        cnv_value = self._read16BitValue(ADS1115ADC.CONVERSION_REG)

        return cnv_value
