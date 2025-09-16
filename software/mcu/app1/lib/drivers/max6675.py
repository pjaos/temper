class MAX6675(object):
    """@brief An interface to a MAX6675 Cold-Junction-Compensated K-Thermocouple-to-Digital Converter.
              Note !!!
                   The type K temperature probe must be connected the correct way round + to + - to -.
    """

    INPUT_BIT = 2
    TEMP_VALUE_MASK = 0xfff

    def __init__(self, spi, cs):
        """@brief Constructor
           @param spi The SPI bus to use to communicate with the MAX66785 device. A machine.SPI() instance.
           @param cs A The active low chip select pin. A machine.Pin() instance.
           @return The temperature read or None """
        self._spi = spi
        self._cs = cs
        self._cs.value(1)

    def read_temp(self, cal_factor=1.0):
        """@brief Read the temperature in °C.
           @param cal_factor The calibration factor. This is simply the multiplier
                            for the temperature read. The default is 1.0 (uncalibrated).
           @return The temperature in °C. This may not be very accurate unless calibration is used.
                   A value of None will be returned if there was an error reading the temperature value. """
        temp = None
        # Set CS low
        self._cs.value(0)
        b_list = self._spi.read(2)
        value = b_list[0] << 8 | b_list[1]
        # set CS high
        self._cs.value(1)
        # If error
        if value & (1 << MAX6675.INPUT_BIT):
            pass

        else:
            value >>= 3  # 12 bits, bit 15 = 0
            # Scale by 0.25 degrees C per bit and return value.
            temp = value * 0.25

        # If an error occurred reading the temperature
        if temp is None:
            return temp

        else:
            return temp * cal_factor


"""
# Example RPi Pico SPI bus 0 pinout

from machine import Pin, SPI, SoftSPI

spi_bus=0
clk_freq_hz=5000000
sck_gpio=2
mosi_gpio=3
miso_gpio=4
cs_gpio=5
"""

"""
# Example ESP32 SPI bus 1 pinout

from machine import Pin, SPI, SoftSPI

spi_bus=1
clk_freq_hz=5000000
sck_gpio=18
mosi_gpio=23
miso_gpio=19
cs_gpio=5
"""

"""
#Example code to read temp in a loop

from time import sleep

spi = SPI(spi_bus, baudrate=clk_freq_hz, sck=Pin(sck_gpio), mosi=Pin(mosi_gpio), miso=Pin(miso_gpio))

cs = Pin(cs_gpio, mode=Pin.OUT, value=1)

max6675 = MAX6675(spi, cs)
while True:
    temp = max6675.read_temp()
    print("Temperature = {:.1f} °C".format(temp))
    sleep(1)
"""
