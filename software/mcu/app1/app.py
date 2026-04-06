# from machine import WDT

import asyncio
from time import time

from lib.uo import UO
from lib.config import MachineConfig
from lib.ydev import YDev
from lib.base_machine import BaseMachine

from machine import ADC, Pin
import dht

SHOW_MESSAGES_ON_STDOUT = True  # Turning this off will stop messages being sent on the serial port and will reduce CPU usage.
WDT_TIMEOUT_MSECS = 8300        # Note that 8388 is the max WD timeout value on pico W hardware.


class ThisMachineConfig(MachineConfig):
    """@brief Defines the config specific to this machine."""

    # Note that
    # MachineConfig.RUNNING_APP_KEY and
    # MachineConfig.WIFI_KEY will added automatically so we only need
    # to define keys that are specific to this machine type here.

    DEFAULT_CONFIG = {YDev.ACTIVE: True,
                      YDev.AYT_TCP_PORT_KEY: 2934,               # The UDP port we expect to receive an AYT UDP broadcast message
                      YDev.OS_KEY: "MicroPython",
                      YDev.UNIT_NAME_KEY: "TEMPER_DEV",          # This can be used to identify device, probably user configurable.
                      YDev.PRODUCT_ID_KEY: "TEMPER",             # This is fixed for the product, probably during MFG.
                      YDev.DEVICE_TYPE_KEY: "SENSOR",            # This is fixed for the product, probably during MFG.
                      YDev.SERVICE_LIST_KEY: "web:80",           # A service name followed by the TCPIP port number this device presents the service on.
                      YDev.GROUP_NAME_KEY: ""                    # Used put devices in a group for mild isolation purposes.
                      }

    def __init__(self):
        super().__init__(ThisMachineConfig.DEFAULT_CONFIG)


async def start(runningAppKey, configFilename):
    """@brief The app entry point.
       @param runningAppKey The KEY in the config dict that holds the current running app.
       @param configFilename The name of the config file. This sits in / on flash."""
    MachineConfig.RUNNING_APP_KEY = runningAppKey
    MachineConfig.CONFIG_FILENAME = configFilename
    file_path = __file__
    if file_path.startswith('app1'):
        active_app = 1

    elif file_path.startswith('app2'):
        active_app = 2

    else:
        raise Exception(f"App path not /app1 or /app2: {file_path}")

    if SHOW_MESSAGES_ON_STDOUT:
        uo = UO(enabled=True, debug_enabled=True)
        uo.info("Started app")
        uo.info("Running app{}".format(active_app))
    else:
        uo = None

    machine_config = ThisMachineConfig()
    this_machine = ThisMachine(uo, machine_config)
    this_machine.start()


class ThisMachine(BaseMachine):
    """@brief Implement functionality required by this project."""

    ADC_CODES_TO_MV             = 14508  # Arrived at empirically by measuring the ADC voltage @ 25C
    MCP9700_VOUT_0C             = 0.5
    MCP9700_TC                  = 0.01

    PARAM_3V3 = "PARAM_3V3"
    PARAM_VBAT = "PARAM_VBAT"
    PARAM_BOARD_TEMP = "PARAM_BOARD_TEMP"
    PARAM_SENSOR_1_TEMP = "PARAM_SENSOR_1_TEMP"
    PARAM_SENSOR_1_HUMIDITY = "PARAM_SENSOR_1_HUMIDITY"
    PARAM_SENSOR_2_TEMP = "PARAM_SENSOR_2_TEMP"
    PARAM_SENSOR_2_HUMIDITY = "PARAM_SENSOR_2_HUMIDITY"
    PARAM_SENSOR_3_TEMP = "PARAM_SENSOR_3_TEMP"
    PARAM_SENSOR_3_HUMIDITY = "PARAM_SENSOR_3_HUMIDITY"
    PARAM_SENSOR_4_TEMP = "PARAM_SENSOR_4_TEMP"
    PARAM_SENSOR_4_HUMIDITY = "PARAM_SENSOR_4_HUMIDITY"
    PARAM_RSSI = "PARAM_RSSI"

    def __init__(self, uo, machine_config):
        super().__init__(uo, machine_config)
        self._startTime = time()
        self._ydev = None

        # Enable watchdog timer here if required.
        # If the WiFi goes down then we can
        # drop out to the REPL prompt.
        # The WDT will then trigger a reboot.
        # self._wdt = WDT(timeout=WDT_TIMEOUT_MSECS)

    def start(self):
        self.show_ram_info()

        # Connect this machine to a WiFi network.
        # Note that the WiFi setup claims two GPIO pins. See _sta_connect_wifi doc for more info.
        self._sta_connect_wifi(wifi_setup_gpio=0, wifi_led_gpio=2, bluetooth_led_gpio=4)

        # Start task that looks for user press of the reset to defaults button press
        asyncio.create_task(self._check_factory_Defaults_task())

        # Task that will return JSON messages to the YDev server.
        self._ydev = YDev(self._machine_config)
        asyncio.create_task(self._ydev.listen())

        # Run the web server. This is used for upgrades and also to present
        # a local webserver to allow users to interact with the device.
        # In this case it displays dummy temperatures.
        from lib.webserver import WebServer
        self._web_server = WebServer(self._machine_config,
                               self._startTime,
                               uo=self._uo)

        # Call the app task to execute your projects functionality.
        asyncio.create_task(self.app_task())

        self._web_server.run()

    async def app_task(self):
        """@brief Add your project code here.
                  Make sure await asyncio.sleep(1) is called frequently to ensure other tasks get CPU time."""
        # Set /TON low to apply power to the temp sensors
        Pin(26, Pin.OUT, value=0)
        # Apply power to the voltage rail detectors
        Pin(13, Pin.OUT, value=1)
        # Disable power LED to save power
        Pin(22, Pin.OUT, value=0)

        sensor1 = dht.DHT22(Pin(16, Pin.OUT, Pin.PULL_UP))
        sensor2 = dht.DHT22(Pin(17, Pin.OUT, Pin.PULL_UP))
        sensor3 = dht.DHT22(Pin(18, Pin.OUT, Pin.PULL_UP))
        sensor4 = dht.DHT22(Pin(19, Pin.OUT, Pin.PULL_UP))

        # scaling factors for voltages
        scale_vbat = 2693
        scale_3v3 = 5144

        adc_vbat = ADC(Pin(34, Pin.IN))
        adc_3v3 = ADC(Pin(35, Pin.IN))
        adc_mcp9700 = ADC(Pin(33, Pin.IN))

        paramDict = {}

        self._web_server.setParamDict(paramDict)

        while True:
            try:
                rssi = self._wifi.get_rssi()
                paramDict[ThisMachine.PARAM_RSSI] = f"{rssi:.1f}"

                value_3v3 = adc_3v3.read_u16()
                voltage_3v3 = value_3v3 / scale_3v3
                paramDict[ThisMachine.PARAM_3V3] = f"{voltage_3v3:.3f}"

                value_vbat = adc_vbat.read_u16()
                voltage_vbat = value_vbat / scale_vbat
                paramDict[ThisMachine.PARAM_VBAT] = f"{voltage_vbat:.3f}"

                self._web_server.addSysStats(paramDict)

                adc_value = adc_mcp9700.read_u16()
                volts = adc_value/ThisMachine.ADC_CODES_TO_MV
                board_temp_c = ( volts - ThisMachine.MCP9700_VOUT_0C ) / ThisMachine.MCP9700_TC
                paramDict[ThisMachine.PARAM_BOARD_TEMP] = f"{board_temp_c:.1f}"

                # Read each sensor. If not connected ignore error and read the next
                param_list = [[sensor1, ThisMachine.PARAM_SENSOR_1_TEMP, ThisMachine.PARAM_SENSOR_1_HUMIDITY, 1],
                              [sensor2, ThisMachine.PARAM_SENSOR_2_TEMP, ThisMachine.PARAM_SENSOR_2_HUMIDITY, 2],
                              [sensor3, ThisMachine.PARAM_SENSOR_3_TEMP, ThisMachine.PARAM_SENSOR_3_HUMIDITY, 3],
                              [sensor4, ThisMachine.PARAM_SENSOR_4_TEMP, ThisMachine.PARAM_SENSOR_4_HUMIDITY, 4]]
                for sensor, temp_key, humidity_key, sensor_number in param_list:
                    try:
                        sensor.measure()
                        await asyncio.sleep(.1)
                        paramDict[temp_key] = sensor.temperature()
                        paramDict[humidity_key] = sensor.humidity()
                    except Exception:
                        self.error(f"Failed to read sensor {sensor_number}")

                self._ydev.update_json_dict(paramDict)

            except Exception as ex:
                self.error(str(ex))

            # Don't read DHT22 sensors more than once every 2 seconds.
            await asyncio.sleep(2)

