from machine import Pin
from machine import Timer

import bluetooth

from lib.hardware import Hardware, const


class BlueTooth():
    """@brief Thanks to the original author of this class which has been modified from the original.
              https://techtotinker.blogspot.com/2021/08/025-esp32-micropython-esp32-bluetooth.html"""

    MAX_RX_MESSAGE_SIZE = const(256)

    def __init__(self, name, led_gpio=-1, debug=False):
        """@brief Constructor
           @param name The name of this bluetooth device.
           @param led_gpio The GPIO ping to set to indicate bluetooth connected status.
           @param debug It True show some debug data."""
        self._led = None
        self._timer1 = None
        if led_gpio >= 0:
            # Create internal objects for the onboard LED
            # blinking when no BLE device is connected
            # stable ON when connected
            self._led = Pin(led_gpio, Pin.OUT)
            self._timer1 = Hardware.GetTimer()
        self._ble_connected = False
        self._rx_message = None
        self._debug = debug
        self._conn_handle = None
        # We limit the BT device name to 18 characters as this is likely to be a safe choice across all OS's
        # detecting it from the advertising packet.
        self._name = name
        if len(self._name) > 18:
            self._name = self._name[:18]

        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._disconnected()
        self._ble.irq(self._ble_irq)
        self._register()
        self._advertiser()

    def set_led(self, on):
        """@brief Set the bluetooth status indicator LED if a GPIO pin was allocated for it.
           @param on LED on if True."""
        if self._led:
            self._led.value(on)

    def toggle_led(self):
        "@brief Toggle the state of the LED  if a GPIO pin was allocated for it."
        if self._led:
            self._led.value(not self._led.value())

    def _connected(self):
        """@bried Set the internal state as connected."""
        self._ble_connected = True
        self.set_led(True)
        if self._timer1 and self._led:
            self._timer1.deinit()

    def _disconnected(self):
        """@bried Set the internal state as disconnected."""
        self._ble_connected = False
        if self._timer1 and self._led:
            self._timer1.init(period=100, mode=Timer.PERIODIC,
                              callback=lambda t: self._led.value(not self._led.value()))
        self._conn_handle = None

    def shutdown(self):
        """@brief Shutdown the bluetooth interface. After this has been called this
                  BlueTooth instance can not be used again. Another must be created
                  to use BlueTooth."""
        self._ble_connected = False
        if self._timer1:
            self._timer1.deinit()
            self._timer1 = None
        if self._ble:
            # This is an attempt to free some of the ~ 37 kB or memory used by bluetooth
            # but still leaves ~ 15K memory acquired by bluetooth but not
            # released.
            self._ble.active(False)
            del self._ble
        self.set_led(False)

    def is_enabled(self):
        """@brief Determine if bluetooth is enabled.
           @return False if bluetooth is not enabled."""
        return self._ble.active()

    def is_connected(self):
        """@brief Get the connected state. True = connected."""
        return self._ble_connected

    def _ble_irq(self, event, data):
        """@brief The bluetooth IRQ handler."""
        if event == 1:  # _IRQ_CENTRAL_CONNECT: A central has connected to this peripheral
            self._conn_handle, addr_type, addr = data
            self._connected()

        elif event == 2:  # _IRQ_CENTRAL_DISCONNECT: A central has _disconnected from this peripheral.
            self._disconnected()
            self._advertiser()

        # _IRQ_GATTS_WRITE: A client has written to this characteristic or
        # descriptor.
        elif event == 3:
            buffer = self._ble.gatts_read(self.rx)
            self._rx_message = buffer.decode('UTF-8').strip()
            if self._debug:
                print(f"self._rx_message = {self._rx_message}")

        else:
            if self._debug:
                print("Unknown event")

    def get_rx_message(self):
        """@return The message received or None if no message received."""
        msg = self._rx_message
        self._rx_message = None
        return msg

    def _register(self):
        """@brief Register the bluetooth service as a UART."""
        # Nordic UART Service (NUS)
        NUS_UUID = const('6E400001-B5A3-F393-E0A9-E50E24DCCA9E')
        RX_UUID = const('6E400002-B5A3-F393-E0A9-E50E24DCCA9E')
        TX_UUID = const('6E400003-B5A3-F393-E0A9-E50E24DCCA9E')

        BLE_NUS = bluetooth.UUID(NUS_UUID)
        BLE_RX = (bluetooth.UUID(RX_UUID), bluetooth.FLAG_WRITE)
        BLE_TX = (bluetooth.UUID(TX_UUID), bluetooth.FLAG_NOTIFY)

        BLE_UART = (BLE_NUS, (BLE_TX, BLE_RX,))
        SERVICES = (BLE_UART, )
        ((self.tx, self.rx,), ) = self._ble.gatts_register_services(SERVICES)
        self._ble.gatts_set_buffer(self.rx, BlueTooth.MAX_RX_MESSAGE_SIZE)

    def send(self, data):
        """@brief Send data to a connected bluetooth device."""
        self._ble.gatts_notify(self._conn_handle, self.tx, data + '\n')

    def _advertiser(self):
        name = bytes(self._name, 'utf-8')
        adv_data = bytearray(b'\x02\x01\x06')  # Flags
        # 0x02 - General discoverable mode
        # 0x01 - AD Type = 0x01
        # 0x02 - value = 0x02
        # https://jimmywongiot.com/2019/08/13/advertising-payload-format-on-ble/
        # https://docs.silabs.com/bluetooth/latest/general/adv-and-scanning/bluetooth-adv-data-basics
        resp_data = bytearray((len(name) + 1, 0x09)) + name  # Complete Local Name

        try:
            self._ble.gap_advertise(100_000, adv_data=adv_data, resp_data=resp_data)
            if self._debug:
                print(adv_data)
                print("\r\n")

        # When the bluetooth interface is disabled an 'OSError: [Errno 19]
        # ENODEV' error will occur.
        except OSError:
            pass
