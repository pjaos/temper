#!/usr/bin/env python3

import argparse
from pathlib import Path

from p3lib.uio import UIO
from p3lib.helper import logTraceBack
from p3lib.boot_manager import BootManager
from p3lib.helper import get_program_version, getHomePath

class TemperDB(object):
    """@brief Discover temper hardware on the LAN and save data retrieved from them to a DB."""

    VERSION = get_program_version('temper')

    @staticmethod
    def GetAppDataPath():
        """@return The path into which all app files are saved."""
        app_cfg_path = None
        home_path   = Path(getHomePath())
        cfg_path   = home_path / Path('.config')
        if cfg_path.is_dir():
            app_cfg_path = cfg_path / Path('temper')
            if not app_cfg_path.is_dir():
                app_cfg_path.mkdir(parents=True, exist_ok=True)

        else:
            app_cfg_path = home_path / Path('.temper')
            if not app_cfg_path.is_dir():
                app_cfg_path.mkdir(parents=True, exist_ok=True)
        return app_cfg_path

    def __init__(self, uio, options):
        """@brief Constructor
           @param uio A UIO instance handling user input and output (E.G stdin/stdout or a GUI)
           @param options An instance of the OptionParser command line options."""
        self._uio = uio
        self._options = options
        self._app_data_path = TemperDB.GetAppDataPath()

    def reap(self):
        """@brief Send messages to temper hardware. Retrieve data from them and save it to a local sqlite db."""
        # Start a background thread that gets data from temper hardware.
        self._start_hardware_listener()



def main():
    """@brief Program entry point"""
    uio = UIO()
    uio.info(f"temper: v{TemperDB.VERSION}")

    try:
        parser = argparse.ArgumentParser(description="Discover temper hardware on the LAN and save data retrieved from them to a DB.",
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("-d", "--debug",  action='store_true', help="Enable debugging.")

        # Add args to auto boot cmd
        BootManager.AddCmdArgs(parser)

        options = parser.parse_args()

        uio.enableDebug(options.debug)

        handled = BootManager.HandleOptions(uio, options, False)
        if not handled:
            temperDB = TemperDB(uio, options)
            temperDB.reap()

    # If the program throws a system exit exception
    except SystemExit:
        pass
    # Don't print error information if CTRL C pressed
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        logTraceBack(uio)

        if options.debug:
            raise
        else:
            uio.error(str(ex))


if __name__ == '__main__':
    main()
