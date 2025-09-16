import machine
import network
import binascii
import json
import os

from time import time, sleep
from machine import Pin
from lib.hardware import const
from lib.config import MachineConfig
from lib.hardware import Hardware


class WiFi(object):
    """@brief Responsible for accessing the WiFi interface."""

    WIFI_CONFIGURED_KEY = const("WIFI_CFG")

    BT_CMD = const("CMD")
    BT_CMD_WIFI_SCAN = const("WIFI_SCAN")
    BT_CMD_STA_CONNECT = const("BT_CMD_STA_CONNECT")
    SSID_BT_KEY = const("SSID")
    BSSID_BT_KEY = const("BSSID")
    PASSWORD_BT_KEY = const("PASSWD")
    WIFI_SCAN_COMPLETE = const("WIFI_SCAN_COMPLETE")
    WIFI_CONFIGURED = const("WIFI_CONFIGURED")
    BT_CMD_GET_IP = const("GET_IP")
    IP_ADDRESS = const("IP_ADDRESS")
    CHANNEL_BT_KEY = const("CHANNEL")
    RSSI_BT_KEY = const("RSSI")
    SECURITY_BT_KEY = const("SECURITY")
    HIDDEN_BT_KEY = const("HIDDEN")
    DISABLE_BT = const("DISABLE_BT")

    # The prefix for the bluetooth device name. The WiFi mac address follows after this.
    BT_NAME_PREFIX = const("YDEV")

    FACTORY_RESET_BUTTON_SECS = 5

    @staticmethod
    def Get_Wifi_Networks(uo=None):
        """@brief Get details of all the detectable WiFi networks.
           @param uo A UO instance if debugging is required. Default=None.
           @return A list of Wifi networks. Each WiFi network is a dict of parameters
                SSID        The network ssid
                BSSID       bssid is returned as a string of 6 hex characters each one separated by a '0x' characters
                CHANNEL     The channel as an integer
                RSSI        The RSSI as a float
                SECURITY    The security as an int
                HIDDEN      An int, 1=hidden, 0=visible
        """
        wifi_network_list = []
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if uo:
            uo.debug("Starting WiFi network scan.")
        # Returns a tuple each element of which contains
        # (ssid, bssid, channel, RSSI, security, hidden)
        # bssid = MAC address of AP
        # There are five values for security:
        # 0 – open
        # 1 – WEP
        # 2 – WPA-PSK
        # 3 – WPA2-PSK
        # 4 – WPA/WPA2-PSK
        # and two for hidden:
        # 0 – visible
        # 1 – hidden
        networks = wlan.scan()
        for n in networks:
            if n[0] != b'\x00\x00\x00\x00\x00\x00\x00\x00\x00':
                ssid = n[0].decode()
                bssid = binascii.hexlify(n[1], '0x').decode()
                try:
                    channel = int(n[2])
                    rssi = float(n[3])
                    security = int(n[4])
                    hidden = int(n[5])
                    wifi_network_dict = {WiFi.SSID_BT_KEY: ssid,
                                         WiFi.BSSID_BT_KEY: bssid,
                                         WiFi.CHANNEL_BT_KEY: channel,
                                         WiFi.RSSI_BT_KEY: rssi,
                                         WiFi.SECURITY_BT_KEY: security,
                                         WiFi.HIDDEN_BT_KEY: hidden}
                    wifi_network_list.append(wifi_network_dict)
                    if uo:
                        uo.debug("Detected WiFi network: {}".format(
                            wifi_network_dict))

                except ValueError:
                    pass

        return wifi_network_list

    @staticmethod
    def GetWifiAddress():
        """@brief Get the WiFi IP address.
           @return The IP address of the WiFi interface in STA mode or an empty string if not connected to a WiFi network."""
        ipAddress = ""
        sta = network.WLAN(network.STA_IF)
        if sta.isconnected():
            status = sta.ifconfig()
            if status:
                ipAddress = status[0]
        return ipAddress

    def __init__(self,
                 uo,
                 wifi_led_pin,
                 wifi_button_pin,
                 wdt,
                 machine_config,
                 max_reg_wait_secs=60,
                 bluetooth_led_pin=None):
        """@brief Constructor
           @param uo A UO instance.
           @param wifi_button_gpio The GPIO pin with a button to GND that is used to setup the WiFi.
           @param wifi_button_pin gpio pin used to reset WiFi config to unset.
           @param wdt A WDT instance.
           @param wifi_led_pin If an external LED is connected to indicate WiFi state
                             this should be set to the GPIO pin number with the LED
                             connected or left at -1 if only using the on board LED.
           @param max_reg_wait_secs The maximum time (seconds) to wait to register on the WiFi network.
           @param bluetooth_led_pin If an LED is connected to indicate if bluetooth is enabled then
                                    this should be set to the GPIO pin number with the LED connected.
                                    This must be set to an integer >= 0 to be valid.
            """
        self._uo = uo
        self._wdt = wdt
        self._machine_config = machine_config
        self._wifi_led_pin = wifi_led_pin
        self._wifi_led = None
        self._wifi_button_pin = wifi_button_pin
        self._wifi_button = None
        self._wifiButtonPressedTime = None
        self._max_reg_wait_secs = max_reg_wait_secs
        self._bluetooth_led_pin = bluetooth_led_pin
        self._ip_address = None
        self._button_pressed_time = None
        self._factory_defaults_method = None
        self._init()

    def info(self, msg):
        if self._uo:
            self._uo.info(msg)

    def debug(self, msg):
        if self._uo:
            self._uo.debug(msg)

    def _init(self):
        """@brief perform instance initialisation."""
        # Init the WiFi status LED if set.
        if self._wifi_led_pin >= 0:
            self._wifi_led = Pin(self._wifi_led_pin, Pin.OUT, value=0)

        if self._wifi_button_pin >= 0:
            self._wifi_button = Pin(self._wifi_button_pin, Pin.IN, Pin.PULL_UP)

        if self._bluetooth_led_pin == self._wifi_led_pin:
            raise Exception(f"The bluetooth LED GPIO pin ({self._bluetooth_led_pin}) is the same as the WiFi LED GPIO pin ({self._wifi_led_pin})")

        if self._bluetooth_led_pin == self._wifi_led_pin:
            raise Exception(f"The bluetooth LED GPIO pin ({self._bluetooth_led_pin}) is the same as the WiFi button GPIO pin ({self._wifi_button_pin})")

        # Note that if initialised to an AP then the mac address would be different.
        self._wlan = network.WLAN(network.STA_IF)

    def get_mac_address(self):
        """@return the mac address of the WiFi interface as an array of 6 bytes."""
        return self._wlan.config('mac')

    def is_factory_reset_required(self):
        """@brief Check if the user has held town the button for long enough to reset the configuration to factory defaults.
           @return True if the button has been held down by the user for the required amount of time."""
        factory_reset_required = False
        # If button is pressed
        if self._wifi_button.value() == 0:
            # If this is the first time the button press was detected
            if self._button_pressed_time is None:
                # Record the time it was pressed
                self._button_pressed_time = time()
            else:
                elapsed_seconds = time() - self._button_pressed_time
                self.debug(f"Factory reset button pressed for {elapsed_seconds} seconds.")
                if elapsed_seconds >= WiFi.FACTORY_RESET_BUTTON_SECS:
                    factory_reset_required = True

        else:
            self._button_pressed_time = None
        return factory_reset_required

    def _config_sta(self, ssid, password, power_save_mode=False):
        """@brief Configure the WiFi in STA mode.
           @param ssid The SSID of the network to connect to.
           @param password The password for the network.
           @param power_save_mode If True then run the wi_fi in power save mode (PICOW only).
           @return True if connected to the WiFi network."""
        self._wlan.active(True)
        self._wlan.connect(ssid, password)
        start_t = time()
        led_flash_time = time() + 2
        while True:
            wifi_status = self._wlan.status()
            self._uo.debug("wifi_status={}".format(wifi_status))
            if self._wlan.isconnected():
                break

            # If the WiFi won't connect the user can hold down the WiFi button to reset to defaults
            # so that they can try setting up the WiFi again.
            elif self._factory_defaults_method and self.is_factory_reset_required():
                self.debug("Reset to factory defaults.")
                self._factory_defaults_method()

            # If we were not able to connect to a WiFi network return None
            elif time() >= start_t+self._max_reg_wait_secs:
                return None

            sleep(0.1)
            self._pat_wdt()

            # We flash the Wifi LED on for about 100 MS every 2 seconds if attempting to connect to
            # a WiFi network in order to give the user some feedback.
            if time() >= led_flash_time:
                self._wifi_led.value(True)
                led_flash_time = time() + 2
            else:
                self._wifi_led.value(False)

        self._uo.debug('connected')
        status = self._wlan.ifconfig()
        self._ip_address = status[0]
        self.info('IP Address=' + self._ip_address)

        if self._wifi_led:
            # Set WiFi LED on to indicate that we're connected to the WiFi network.
            self._wifi_led.value(True)
        return self._wlan.isconnected()

    def _get_bt_dev_name(self):
        """@brief Get the Bluetooth device name."""
        mac_address = self.get_mac_address()
        return WiFi.BT_NAME_PREFIX + "{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}".format(mac_address[0], mac_address[1], mac_address[2], mac_address[3], mac_address[4], mac_address[5])

    def sta_connect(self):
        """@brief Connect to a WiFi network."""
        wifi_cfg_dict = self._get_wifi_config()
        wifi_configured = wifi_cfg_dict[MachineConfig.WIFI_CONFIGURED_KEY]
        if wifi_configured:
            ssid = wifi_cfg_dict[MachineConfig.SSID_KEY]
            password = wifi_cfg_dict[MachineConfig.PASSWORD_KEY]
            connected = self._config_sta(ssid, password)
            if not connected:
                self.info(f"Rebooting as Unable to connect to {ssid}")
                machine.reset()

        else:
            # We get here when the WiFi network is not configured. We wait for it to
            # be configured via bluetooth.
            # Import bluetooth here so that we don't have bluetooth in memory when a normal boot occurs
            # to save the ~ 37 KB of memory used by bluetooth
            from lib.pja_bluetooth import BlueTooth
            bt_led_pin = -1
            try:
                _bt_led_pin = int(self._bluetooth_led_pin)
                if _bt_led_pin >= 0:
                    bt_led_pin = _bt_led_pin
            except:
                pass
            self._bluetooth = BlueTooth(self._get_bt_dev_name(), led_gpio=bt_led_pin)
            # We wait here until commands are received over bluetooth to setup WiFi.
            bt_shutdown = False
            while not bt_shutdown:
                bt_shutdown = self.process_bt_commands()
                self._pat_wdt()
                sleep(0.25)
                # Toggle the WiFi LED pin to indicate the unit is in WiFi setup mode.
                self._wifi_led.value(not self._wifi_led.value())

    def _pat_wdt(self):
        if self._wdt:
            self._wdt.feed()

    def get_dict(self, throw_error=False):
        """@brief Get a message from a connected bluetooth client. This message should be a
                  JSON string. This is converted to a python dictionary.
           @param throw_error If True an exception is thrown if the data is received but it
                  is not JSON formatted.
           @return A python dictionary or None if no message is received or the
                   message received is not a valid JSON string."""
        json_dict = None
        if self._bluetooth is not None:
            if self._bluetooth.is_connected():
                rx_string = self._bluetooth.get_rx_message()
                if rx_string is not None:
                    try:
                        json_dict = json.loads(rx_string)
                    except Exception:
                        if throw_error:
                            raise
        return json_dict

    def get_ip_address(self):
        """@brief Get the IP address we have on the network.
           @return The IP address of None if WiFi is not setup."""
        return self._ip_address

    def _get_wifi_config(self):
        """@return the WiFi configuration dict from the machine config."""
        return self._machine_config.get(MachineConfig.WIFI_KEY)

    def _update_wifi_config(self, wifi_mode, wifi_ssid, wifi_password):
        """@brief Update the WiFi config in the machine config file."""
        wifi_cfg_dict = self._get_wifi_config()

        wifi_cfg_dict[MachineConfig.MODE_KEY] = wifi_mode
        wifi_cfg_dict[MachineConfig.SSID_KEY] = wifi_ssid
        wifi_cfg_dict[MachineConfig.PASSWORD_KEY] = wifi_password
        wifi_cfg_dict[MachineConfig.WIFI_CONFIGURED_KEY] = 1

        self._machine_config.set(MachineConfig.WIFI_KEY, wifi_cfg_dict)
        self._machine_config.store()
        # Ensure the file system is synced before we reboot.
        os.sync()

    def process_bt_commands(self):
        """@brief Process bluetooth commands.
           @return True if a command to shutdown the bluetooth interface is received."""

        rx_dict = self.get_dict()
        if rx_dict:
            self.debug("BT rx_dict={}".format(rx_dict))
            if WiFi.BT_CMD in rx_dict:
                cmd = rx_dict[WiFi.BT_CMD]

                # Perform a Wifi network scan
                if cmd == WiFi.BT_CMD_WIFI_SCAN:
                    wi_fi_networks_dict = WiFi.Get_Wifi_Networks(self._uo)
                    if self._bluetooth is not None and self._bluetooth.is_connected():
                        for wifi_network in wi_fi_networks_dict:
                            # Send one network at a time as the bluetooth LE packet size is not large
                            self._bluetooth.send(json.dumps(wifi_network))
                        # Send scan complete indicator
                        self._bluetooth.send(json.dumps(
                            {WiFi.WIFI_SCAN_COMPLETE: 1}))

                # Connect as an STA to a WiFi network
                elif cmd == WiFi.BT_CMD_STA_CONNECT:
                    # If the WiFi network and password have been supplied.
                    if WiFi.SSID_BT_KEY in rx_dict and WiFi.PASSWORD_BT_KEY in rx_dict:
                        wifi_mode = MachineConfig.STA_MODE
                        wifi_ssid = rx_dict[WiFi.SSID_BT_KEY]
                        wifi_password = rx_dict[WiFi.PASSWORD_BT_KEY]
                        if self._bluetooth is not None:
                            self._bluetooth.send(
                                json.dumps({WiFi.WIFI_CONFIGURED: 1}))
                        if wifi_mode == MachineConfig.STA_MODE:
                            # Save the config so we reboot and connect to a WiFi network
                            self._config_sta(wifi_ssid, wifi_password)
                        self._update_wifi_config(
                            wifi_mode, wifi_ssid, wifi_password)

                # Setup as an AP WiFi network
                elif cmd == WiFi.BT_CMD_GET_IP:
                    if self._bluetooth is not None:
                        tx_dict = {WiFi.IP_ADDRESS: self.get_ip_address()}
                        self.debug(f"Sending {tx_dict}")
                        self._bluetooth.send(json.dumps(tx_dict))

                # The app has sent a message instructing the device to disable it's bluetooth interface.
                elif cmd == WiFi.DISABLE_BT:
                    # This occurs after the WiFi has been configured. The config file contains the WiFi
                    # config and so the subsequent startup process will no longer enable bluetooth.
                    Hardware.Reboot(uo=self._uo)
                    while True:
                        sleep(1)

    def set_factory_defaults_method(self, factory_defaults_method):
        """@brief Set the method to be called to reset the config to factory defaults.
           @param factory_defaults_method The method reference."""
        self._factory_defaults_method = factory_defaults_method

