# Helper methods for IO functionality

import os


class IO(object):

    TYPE_DIR = 0x4000
    TYPE_FILE = 0x8000

    @staticmethod
    def DirExists(a_path):
        """@param a_path The path to check.
           @return True if the dir exists."""
        try:
            return (os.stat(a_path)[0] & IO.TYPE_DIR) != 0
        except OSError:
            return False

    @staticmethod
    def FileExists(filename):
        """@param filename The file to check.
           @return True if the filename exists."""
        try:
            return (os.stat(filename)[0] & IO.TYPE_DIR) == 0
        except OSError:
            return False

    @staticmethod
    def getFileSize(_file):
        """@param _file The file to check.
           @return The size of the file or -1 if an error occurred (I.E the file doesn't exist)"""
        try:
            return os.stat(_file)[6]  # Size is at index 6
        except OSError:
            return -1
