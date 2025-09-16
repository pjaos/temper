import sys
import os
from machine import Timer, reset_cause, deepsleep, reset
from time import sleep
try:
    from micropython import const
except ImportError:
    def const(x): return x  # fallback for CPython


class Hardware(object):
    """@brief Provide functionality to ease cross platform use."""

    RPI_PICO_PLATFORM = const("rp2")
    ESP32_PLATFORM = const("esp32")

    @staticmethod
    def IsPico():
        """@return True if running on a RPi pico platform."""
        pico = False
        if sys.platform == Hardware.RPI_PICO_PLATFORM:
            pico = True
        return pico

    @staticmethod
    def IsESP32():
        """@return True if running on an ESP32 platform."""
        esp32 = False
        if sys.platform == Hardware.ESP32_PLATFORM:
            esp32 = True
        return esp32

    @staticmethod
    def GetTimer():
        """@brief Get a machine.Timer instance.
           @return a Timer instance."""
        timer = None
        if Hardware.IsPico():
            timer = Timer(-1)
        else:
            timer = Timer(0)
        return timer

    @staticmethod
    def GetLastResetCause(self):
        """@brief Get the reset cause.
                  See, https://docs.micropython.org/en/latest/library/machine.html#machine-constants."""
        return reset_cause()

    @staticmethod
    def Deep_Sleep(micro_seconds):
        """@brief Put the microcontroller to sleep for a period of time.
           @param micro_seconds The period of time to put the micro controller to sleep."""
        if micro_seconds > 0:
            deepsleep(micro_seconds)

    @staticmethod
    def Reboot(uo=None, restart_delay=0.25):
        """@brief Reboot machine."""
        # Ensure the file system is synced before we reboot.
        os.sync()
        if uo:
            uo.debug(f"Rebooting in {restart_delay:.2f} seconds.")
        if restart_delay > 0.0:
            sleep(restart_delay)
        reset()
