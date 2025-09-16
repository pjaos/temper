import os
import asyncio
from time import sleep

from lib.uo import UOBase
from lib.wifi import WiFi
from lib.hardware import Hardware

class BaseMachine(UOBase):

    """@brief Responsible for providing reusable machine functionality."""

    # The MAX time to wait for an STA to register.
    # After this time has elapsed the unit will either reboot
    # or if the hardware has the capability, power cycle itself.
    MAX_STA_WAIT_REG_SECONDS = 60

    def __init__(self, uo, machine_config):
        super().__init__(uo)
        self._machine_config = machine_config
        self._wdt = None

    def pat_wdt(self):
        if self._wdt:
            self._wdt.feed()

    def _get_wifi_setup_gpio(self, override=-1):
        """@brief get the GPIO pin used to setup the WiFi GPIO.
           @param wifi_setup_gpio_override. By default this is set to -1 which sets the following defaults.
                  GPIO 0 on an esp32 (original) MCU.
                  GPIO 9 on an esp32-c3 or esp32-c6 MCU.
                  GPIO 14 on a RPi Pico W or RPi Pico 2 W MCU.
           @return The GPIO pin to use."""
        mcu = os.uname().machine
        self.debug(f"MCU: {mcu}")
        gpio_pin = -1
        if override >= 0:
            # TODO: Add checks here to check that it's a valid GPIO for the MCU
            gpio_pin = override

        else:
            if 'ESP32C6' in mcu:
                gpio_pin = 9

            elif 'ESP32C3' in mcu:
                gpio_pin = 9

            elif 'ESP32' in mcu:
                gpio_pin = 0

            elif 'RP2040' in mcu or 'RP2350' in mcu:
                gpio_pin = 14

            else:
                raise Exception(f"Unsupported MCU: {mcu}")

        return gpio_pin

    def _get_wifi_led_gpio(self, override=-1):
        """@brief get the GPIO pin connected connected to an LED that turns on when the WiFi
                  is connected to the WiFi network as an STA.
           @param wifi_setup_gpio_override. By default this is set to -1 which sets the following defaults.
                  GPIO 2 on an esp32 (original) MCU.
                  GPIO 8 on an esp32-c3 or esp32-c6 MCU.
                  GPIO 16 on a RPi Pico W or RPi Pico 2 W MCU.
           @return The GPIO pin to use."""
        mcu = os.uname().machine
        self.debug(f"MCU: {mcu}")
        gpio_pin = -1
        if override >= 0:
            # TODO: Add checks here to check that it's a valid GPIO for the MCU
            gpio_pin = override

        else:
            if 'ESP32C6' in mcu:
                gpio_pin = 8

            elif 'ESP32C3' in mcu:
                gpio_pin = 8

            elif 'ESP32' in mcu:
                gpio_pin = 2

            elif 'RP2040' in mcu or 'RP2350' in mcu:
                gpio_pin = 16

            else:
                raise Exception(f"Unsupported MCU: {mcu}")

        return gpio_pin

    def _sta_connect_wifi(self, wifi_setup_gpio=-1, wifi_led_gpio=-1, bluetooth_led_gpio=None):
        """@brief Connect to a WiFi network in STA mode.
           @param wifi_setup_gpio The GPIO pin connected to a switch that when held low for some time resets WiFi setup.
                                  See _get_wifi_setup_gpio() for more info.
           @param wifi_led_gpio   The GPIO pin connected to an LED that turns on when the WiFi is connected to the WiFi network as an STA.
                                  See _get_wifi_led_gpio() for more info.
           @param bluetooth_led_gpio The GPIO pin connected to an LED that indicates if bluetooth is enabled. Typically a blue LED.
                                     If defined this led will flash when bluetooth is enabled and turn ON when a bluetooth client is connected.
           """
        wifi_led_gpio = self._get_wifi_led_gpio(override=wifi_led_gpio)
        wifi_setup_gpio = self._get_wifi_setup_gpio(override=wifi_setup_gpio)
        self.info(f"WiFi LED GPIO:      {wifi_led_gpio}")
        self.info(f"WiFi RESET GPIO:    {wifi_setup_gpio}")
        self.info(f"Bluetooth LED GPIO: {bluetooth_led_gpio}")
        # Init the WiFi interface
        self._wifi = WiFi(self._uo,
                          wifi_led_gpio,
                          wifi_setup_gpio,
                          self._wdt,
                          self._machine_config,
                          max_reg_wait_secs=BaseMachine.MAX_STA_WAIT_REG_SECONDS,
                          bluetooth_led_pin=bluetooth_led_gpio)
        # Set the method to use to reset to factory defaults. This is called inside wifi
        # if the user holds down the button while it's trying to connect to a wifi network
        # when sta_connect() is called.
        self._wifi.set_factory_defaults_method(self.set_factory_defaults)
        self._wifi.sta_connect()

    def set_factory_defaults(self):
        """@brief reset the config to factory defaults."""
        self._machine_config.set_defaults()
        self._machine_config.store()
        self.warn("Resetting to factory defaults.")
        # Ensure the file system is synced before we reboot.
        os.sync()
        Hardware.Reboot(uo=self._uo)
        while True:
            sleep(1)

    async def _check_factory_Defaults_task(self):
        """@brief This task checks for the button press and if held down
                  for the required period of time resets the device to factory
                  defaults and reboots."""
        while True:
            if self._wifi.is_factory_reset_required():
                self.debug("Reset to factory defaults.")
                self.set_factory_defaults()
            # Reset the WDT if it has been set.
            self.pat_wdt()
            # Allow other tasks plenty of time to run.
            await asyncio.sleep(1)