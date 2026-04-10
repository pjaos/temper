#!/usr/bin/env python3

import argparse
import json

from p3lib.uio import UIO
from p3lib.helper import logTraceBack
from urllib.request import urlopen

def set_unit_name(uio, address, name):
    """@brief Set the name of a temper unit."""
    response = urlopen(f"http://{address}/set_name?name={name}")
    data = json.loads(response.read().decode())
    if 'OK' in data and data['OK']:
        uio.info(f"Set the name of the temper unit at address {address} to {name}")

    else:
        uio.error(f'Error setting temper unit name: {response}')

def main():
    """@brief Program entry point"""
    uio = UIO()

    try:
        parser = argparse.ArgumentParser(description="Set the name of a Temper unit.",
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("-d", "--debug",   action='store_true', help="Enable debugging.")
        parser.add_argument("-a", "--address", help="The IP address of the Temper unit.", default=None, required=True)
        parser.add_argument("-n", "--name",    help="The name of the temper unit. This is stored inside the temper unit.", default=None, required=True)

        options = parser.parse_args()

        uio.enableDebug(options.debug)

        set_unit_name(uio, options.address, options.name)

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
