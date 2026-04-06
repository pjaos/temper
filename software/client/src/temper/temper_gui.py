#!/usr/bin/env python3

# An command line template using argparse as optparse is now deprecated.

import argparse
from p3lib.uio import UIO
from p3lib.helper import logTraceBack


class CustomError(Exception):
    pass


class AClass(object):

    def __init__(self, uio, options):
        """@brief Constructor
           @param uio A UIO instance handling user input and output (E.G stdin/stdout or a GUI)
           @param options An instance of the OptionParser command line options."""
        self._uio = uio
        self._options = options

    def doSomething(self):
        """@brief """
        self._uio.info('host     = {}'.format(self._options.host))
        self._uio.info('debug    = {}'.format(self._options.debug))
        self._uio.info('int      = {}'.format(self._options.int))
        self._uio.info('hint     = {:0x}'.format(self._options.hint))
        self._uio.info('float    = {}'.format(self._options.float))
        response = self._uio.getInput("Enter some text: ")
        print('response = %s' % (response))


def main():
    """@brief Program entry point"""
    uio = UIO()

    try:
        parser = argparse.ArgumentParser(description="A tool to do something.\n"
                                                     "A description of what it does.",
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("-d", "--debug",  action='store_true', help="Enable debugging.")
        parser.add_argument("-t", "--host",   help="The host string.", default=None, required=True)
        parser.add_argument("-i", "--int",    type=int, help="An integer")
        parser.add_argument("-n", "--hint",   type=lambda x: hex(int(x, 16)), help="A hexadecimal number", default=0x3d)
        parser.add_argument("-f", "--float",  type=float, help="A float", default=1.2)

        parser.epilog = "Line 1\n"\
                        "Line 2\n"

        # If host is a positional argument
        # parser.add_argument('host')

        options = parser.parse_args()

        uio.enableDebug(options.debug)
        aClass = AClass(uio, options)
        aClass.doSomething()

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
