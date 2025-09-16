from time import time
import gc


class UO(object):
    """@brief Responsible for displaying messages to the user over the serial interface to the picow."""

    INFO_LEVEL = "INFO:  "
    WARN_LEVEL = "WARN:  "
    ERROR_LEVEL = "ERROR: "
    DEBUG_LEVEL = "DEBUG: "

    def __init__(self, enabled=True, debug_enabled=True):
        """@brief Constructor.
           @param enabled If True messages will be displayed.
           @param enable_debug If True then debug messages will be displayed."""
        self._enabled = enabled
        self._debug_enabled = debug_enabled

    def set_enabled(self, enabled):
        """@brief Enable/Disable the user output. You may want to disable user output
                  to speed up the code so that it's not sending data out of the serial port.
           @param enabled If True then enable the user output."""
        self._enabled = enabled

    def info(self, msg):
        """@brief Display an info level message.
           @param msg The message text."""
        self._print(UO.INFO_LEVEL, msg)

    def warn(self, msg):
        """@brief Display a warning level message.
           @param msg The message text."""
        self._print(UO.WARN_LEVEL, msg)

    def error(self, msg):
        """@brief Display an error level message.
           @param msg The message text."""
        self._print(UO.ERROR_LEVEL, msg)

    def debug(self, msg):
        """@brief Display a debug level message.
           @param msg The message text."""
        if self._debug_enabled:
            self._print(UO.DEBUG_LEVEL, msg)

    def _print(self, prefix, msg):
        """@brief display a message.
           @param prefix The prefix text that defines the message level.
           @param msg The message text."""
        if self._enabled:
            print('{}{}'.format(prefix, msg))


class UOBase(object):
    """brief A base class for classes that use UO instances to send data to the user.
             This provides instance methods to send data to the user."""

    SHOW_RAM_POLL_SECS = 5

    def __init__(self, uo):
        """@brief Constructor
           @param uo A UO instance for presenting data to the user. If Left as None
                     no data is sent to the user."""
        self._uo = uo
        self._startTime = time()

    def info(self, message):
        """@brief Show an info level message to the user.
           @param message The message to be displayed."""
        if self._uo:
            self._uo.info(message)

    def warn(self, message):
        """@brief Show a warning level message to the user.
           @param message The message to be displayed."""
        if self._uo:
            self._uo.warn(message)

    def error(self, message):
        """@brief Show an error level message to the user.
           @param message The message to be displayed."""
        if self._uo:
            self._uo.error(message)

    def debug(self, message):
        """@brief Show a debug level message to the user.
           @param message The message to be displayed."""
        if self._uo:
            self._uo.debug(message)

    def show_ram_info(self, attempt_garbage_collection=True):
        """@brief Show the RAM usage info."""
        used_bytes = gc.mem_alloc()
        free_bytes = gc.mem_free()
        total_bytes = used_bytes + free_bytes
        self.info(
            f"Total RAM (bytes) {total_bytes}, Free {free_bytes}, Used {used_bytes}, uptime {time() - self._startTime}")
        self._showRamTime = time() + UOBase.SHOW_RAM_POLL_SECS
        if attempt_garbage_collection:
            # Attempt to force garbage collector to run.
            gc.collect()
