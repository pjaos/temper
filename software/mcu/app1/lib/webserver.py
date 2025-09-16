import os
import gc
import machine
import hashlib
import binascii
import ujson as json
from time import time, sleep
import _thread

from lib.microdot.microdot import Microdot, Response
from lib.config import MachineConfig
from lib.io import IO
from lib.hardware import const
from lib.fs import VFS
from lib.wifi import WiFi

class WebServer():
    DEFAULT_PORT = 80

    RAM_USED_BYTES = const("RAM_USED_BYTES")
    RAM_FREE_BYTES = const("RAM_FREE_BYTES")
    RAM_TOTAL_BYTES = const("RAM_TOTAL_BYTES")
    DISK_TOTAL_BYTES = const("DISK_TOTAL_BYTES")
    DISK_USED_BYTES = const("DISK_USED_BYTES")
    DISK_PERCENTAGE_USED = const("DISK_PERCENTAGE_USED")

    OK_KEY = "OK"                                            # The key in the JSON response if no error occurs.
    ERROR_KEY = "ERROR"                                      # The key in the JSON response if an error occurs.
    UPTIME_SECONDS = "UPTIME_SECONDS"
    ACTIVE_APP_FOLDER_KEY = "ACTIVE_APP_FOLDER"
    INACTIVE_APP_FOLDER_KEY = "INACTIVE_APP_FOLDER"
    WIFI_SCAN_RESULTS = "WIFI_SCAN_RESULTS"

    WEBREPL_CFG_PY_FILE = "webrepl_cfg.py"

    @staticmethod
    def GetErrorDict(msg):
        """@brief Get an error response dict.
           @param msg The message to include in the response.
           @return The dict containing the error response"""
        return {WebServer.ERROR_KEY: msg}

    @staticmethod
    def GetOKDict():
        """@brief Get an OK dict response.
           @param msg The message to include in the response.
           @return The dict containing the error response"""
        return {WebServer.OK_KEY: True}

    def __init__(self,
                 machine_config,
                 startTime,
                 uo=None, port=DEFAULT_PORT):
        """@brief Constructor
           @param machine_config The MachineConfig instance for this machine.
           @param startTime The time that the machine started.
           @param uo A UIO instance if debug required."""
        self._machine_config = machine_config
        self._uo = uo
        self._port = port
        self._startTime = startTime
        self._paramDict = None

    def setParamDict(self, paramDict):
        """@brief Set the dictionary holding parameters that are used to replace text in html files as they are loaded.
           @param paramDict A dictionary that holds the following.
                  key = The text of the variable in the html file. E.G If {{ temperature }} text is in the html file. The key would be temperature.
                  value = The text to replace the above. E.G if the text is 24.5 then '{{ temperature }}' is remove and replaced with 24.5."""
        self._paramDict = paramDict

    def _updateContent(self, template_bytes, values_dict, start = b'{{ ', stop = b' }}'):
        """@brief Insert the values into an HTML page.
           @param template_bytes The html file contents read from flash.
           @param values_dict The dict containing the values. The key is the parameter text between start and stop bytes.
           @param start = The bytes (not string) that appears before the variable name in the html file.
           @param start = The bytes (not string) that appears after the variable name in the html file."""
        for key, val in values_dict.items():
            placeholder = start + key.encode() + stop
            value_bytes = str(val).encode()
            template_bytes = template_bytes.replace(placeholder, value_bytes)
        return template_bytes

    def _addRamStats(self, responseDict):
        """@brief Update the RAM usage stats.
           @param responseDict the dict to add the stats to."""
        usedBytes = gc.mem_alloc()
        freeBytes = gc.mem_free()
        responseDict[WebServer.RAM_USED_BYTES] = usedBytes
        responseDict[WebServer.RAM_FREE_BYTES] = freeBytes
        responseDict[WebServer.RAM_TOTAL_BYTES] = usedBytes + freeBytes

    def _addDiskUsageStats(self, responseDict):
        """@brief Update the RAM usage stats.
           @param responseDict the dict to add the stats to."""
        totalBytes, usedSpace, percentageUsed = VFS.GetFSInfo()
        responseDict[WebServer.DISK_TOTAL_BYTES] = totalBytes
        responseDict[WebServer.DISK_USED_BYTES] = usedSpace
        responseDict[WebServer.DISK_PERCENTAGE_USED] = percentageUsed

    def _addUpTime(self, responseDict):
        """@brief Get the uptime stats.
           @param responseDict A dict to add the uptime stats to."""
        responseDict[WebServer.UPTIME_SECONDS] = time()-self._startTime

    def _getSysStats(self, request):
        """@return A dict containing the system stats, ram, disk usage and uptime."""
        runGC = request.args.get("gc", False)
        if runGC:
            gc.collect()
        responseDict = {}
        self._addRamStats(responseDict)
        self._addDiskUsageStats(responseDict)
        self._addUpTime(responseDict)
        return responseDict

    def _getFolderEntries(self, folder, fileList):
        """@brief List the entries in a folder.
           @brief folder The folder to look for files in.
           @brief fileList The list to add files to."""
        fsIterator = os.ilistdir(folder)
        for nodeList in fsIterator:
            if len(nodeList) >= 3:
                name = nodeList[0]
                type = nodeList[1]
                if len(name) > 0:
                    if folder == '/':
                        anEntry = folder + name
                    else:
                        anEntry = folder + "/" + name
                    if type == IO.TYPE_FILE:
                        fileList.append(anEntry)

                    elif type == IO.TYPE_DIR:
                        # All folders end in /
                        fileList.append(anEntry + '/')
                        # Recurse through dirs
                        self._getFolderEntries(anEntry, fileList)
        return fileList

    def _getFileList(self, request):
        """@brief Get a list of the files and dirs on the system.
            @param request The http request.
            @return The response list."""
        path = request.args.get("path", "/")
        if ".." in path:
            return WebServer.GetErrorDict(".. is an Invalid path")
        return self._getFolderEntries(path, [])

    def _removeDir(self, theDirectory):
        """@brief Remove the directory an all of it's contents.
           @param theDirectory The directory to remove."""
        if IO.DirExists(theDirectory):
            entryList = []
            self._getFolderEntries(theDirectory, entryList)
            for entry in entryList:
                if IO.DirExists(entry):
                    self._removeDir(entry)

                elif IO.FileExists(entry):
                    os.remove(entry)
            # All contents removed so remove the top level.
            os.remove(theDirectory)

    def _eraseOfflineApp(self):
        """@brief Erase the offline app folder and all of it's contents.
           @return The response dict."""
        runningApp = self._machine_config.get(MachineConfig.RUNNING_APP_KEY)
        if runningApp:
            offLineApp = 2
            if runningApp == 2:
                offLineApp = 1
            appRoot = "/app{}".format(offLineApp)
            self._removeDir(appRoot)
            returnDict = WebServer.GetOKDict()

        else:
            returnDict = WebServer.GetErrorDict("The machine config does not detail the running app !!!")

        return returnDict

    def _makeDir(self, request):
        """@brief Create a dir on the devices file system.
           @param request The http request.
           @return The response dict."""
        path = request.args.get("path", None)
        if path:
            try:
                os.mkdir(path)
                responseDict = WebServer.GetOKDict()
            except OSError:
                responseDict = WebServer.GetErrorDict("Failed to create {}".format(path))
        return responseDict

    def _rmDir(self, request):
        """@brief Remove a dir on the devices file system.
           @param request The http request.
           @return The response dict."""
        path = request.args.get("path", None)
        if path:
            try:
                os.rmdir(path)
                responseDict = WebServer.GetOKDict()
            except OSError:
                responseDict = WebServer.GetErrorDict("Failed to remove {}".format(path))
        else:
            responseDict = WebServer.GetErrorDict("No dir passed to /rmdir")
        return responseDict

    def _rmFile(self, request):
        """@brief Remove a dir on the devices file system.
           @param request The http request.
           @return The response dict."""
        _file = request.args.get("file", None)
        if _file:
            try:
                os.remove(_file)
                responseDict = WebServer.GetOKDict()
            except OSError:
                responseDict = WebServer.GetErrorDict("Failed to delete {}".format(_file))
        else:
            responseDict = WebServer.GetErrorDict("No file passed to /rmfile")
        return responseDict

    def _getFile(self, request):
        """@brief Get the contents of a file on the devices file system.
            @param request The http request.
           @return The response dict containing the file contents."""
        _file = request.args.get("file", None)
        if _file:
            try:
                fd = None
                try:
                    fd = open(_file)
                    fileContent = fd.read()
                    fd.close()
                    responseDict = WebServer.GetOKDict()
                    responseDict[_file] = fileContent
                finally:
                    if fd:
                        fd.close()
                        fd = None

            except Exception as ex:
                WebServer.GetErrorDict(str(ex))

        else:
            responseDict = WebServer.GetErrorDict("No file passed to /get_file")

        return responseDict

    def resetWiFiConfig(self):
        """@brief Reset the WiFi config to the default values (AP mode)"""
        self._machine_config.reset_wifi_config()
        return WebServer.GetOKDict()

    def _getAppFolder(self, active):
        """@brief Get the app folder.
           @param active If True then get the active application folder.
           @param responseDict containing the active app folder."""
        runningApp = self._machine_config.get(MachineConfig.RUNNING_APP_KEY)

        if runningApp == 1:
            offLineApp = 2
        if runningApp == 2:
            offLineApp = 1

        if active:
            appRoot = "/app{}".format(runningApp)
            returnDict = {WebServer.ACTIVE_APP_FOLDER_KEY: appRoot}
        else:
            appRoot = "/app{}".format(offLineApp)
            returnDict = {WebServer.INACTIVE_APP_FOLDER_KEY: appRoot}

        return returnDict

    def getActiveAppFolder(self):
        return self._getAppFolder(True)

    def getInActiveAppFolder(self):
        return self._getAppFolder(False)

    def swapActiveAppFolder(self):
        """@brief Swap the active app folder.
           @return a dict containing the active app folder."""
        if self._machine_config.is_parameter(MachineConfig.RUNNING_APP_KEY):
            runningApp = self._machine_config.get(MachineConfig.RUNNING_APP_KEY)
            if runningApp == 1:
                newActiveApp = 2
            else:
                newActiveApp = 1
            self._machine_config.set(MachineConfig.RUNNING_APP_KEY, newActiveApp)
            self._machine_config.store()
        return {WebServer.ACTIVE_APP_FOLDER_KEY: newActiveApp}

    def rebootDevice(self):
        """@brief reboot the device."""
        # Ensure the file system is synced before we reboot.
        os.sync()
        # Start thread to reboot MCU. Used to use a Timer but the ESP32C6 MicroPython
        # failed to work because at this time ESP32C6 MicroPython Timer support is yet to be added.
        _thread.start_new_thread(self._doReboot, ())
        responseDict = WebServer.GetOKDict()
        responseDict["INFO"] = "Reboot in progress..."
        return responseDict

    def _doReboot(self):
        """@brief Perform a device restart."""
        self._uo.info("Rebooting now.")
        sleep(0.25)
        # !!! This does not always work
        machine.reset()

    def resetToDefaultConfig(self):
        """@reset the configuration to defaults."""
        self._machine_config.set_defaults()
        self._machine_config.store()
        responseDict = WebServer.GetOKDict()
        responseDict["INFO"] = "The unit has been reset to the default configuration."

    def wifiScan(self):
        """@brief Scan for WiFi networks."""
        responseDict = WebServer.GetOKDict()
        responseDict[WebServer.WIFI_SCAN_RESULTS] = WiFi.Get_Wifi_Networks()
        return responseDict

    def sha256File(path, request):
        try:
            digest = ""
            _file = request.args.get("file", None)
            h = hashlib.sha256()
            with open(_file, 'rb') as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    h.update(chunk)
            digest = binascii.hexlify(h.digest())
            responseDict = WebServer.GetOKDict()
            responseDict["SHA256"] = digest

        except Exception as e:
            responseDict = WebServer.GetErrorDict(str(e))

        return responseDict

    def collectGarbage(self):
        """@brief Force run the python garbage collector."""
        gc.collect()
        responseDict = WebServer.GetOKDict()
        return responseDict

    def getContentType(self, filename):
        if filename.endswith('.html'):
            return 'text/html'
        elif filename.endswith('.css'):
            return 'text/css'
        elif filename.endswith('.js'):
            return 'application/javascript'
        elif filename.endswith('.json'):
            return 'application/json'
        elif filename.endswith('.png'):
            return 'image/png'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            return 'image/jpeg'
        elif filename.endswith('.gif'):
            return 'image/gif'
        elif filename.endswith('.svg'):
            return 'image/svg+xml'
        elif filename.endswith('.ico'):
            return 'image/x-icon'
        else:
            return 'application/octet-stream'

    def _mkdirs(self, path):
        """@brief Recursively create directories like os.makedirs()
           @param path The path to create"""
        parts = path.split('/')
        current = ''
        for part in parts:
            if not part:
                continue  # Skip empty parts (e.g. from leading '/')
            current += '/' + part
            try:
                os.mkdir(current)
            except OSError as e:
                if e.args[0] == 17:
                    # EEXIST — already exists, so continue
                    continue
                else:
                    raise

    def _set_webrepl_password(self, request):
        """@brief Create a dir on the devices file system.
           @param request The http request.
           @return The response dict."""
        password = request.args.get("password", None)
        if password:
            if len(password) >= 4 and len(password) <= 9:
                try:
                    lines = ['# The password must be 4 to 9 characters long',
                            '# This file must have a new line after the password.',
                            f"PASS = '{password}'"]
                    with open(WebServer.WEBREPL_CFG_PY_FILE, 'w') as fd:
                        for line in lines:
                            fd.write(line + "\n")
                    responseDict = WebServer.GetOKDict()
                    responseDict['WEBREPL_PASSWORD'] = f'{password}'
                    responseDict['INFO'] = 'Restart MCU to set new password.'
                except OSError:
                    responseDict = WebServer.GetErrorDict(f"Failed to create {WebServer.WEBREPL_CFG_PY_FILE}")
            else:
                responseDict = WebServer.GetErrorDict(f"{password} is an invalid WebREPL password. The password length must be >= 4 and <= 9 characters long.")
        else:
            responseDict = WebServer.GetErrorDict("WebREPL password not defined.")

        return responseDict

    def run(self):
        """@brief This is a blocking method that starts the web server."""

        def get_json(_dict):
            """@param _dict A python dictionary.
               @return Return a JSON representation of the _dict"""
            return json.dumps(_dict)

        def return_success():
            return get_json(WebServer.GetOKDict())

        def return_error(msg):
            return get_json(WebServer.GetErrorDict(msg))

        app = Microdot()

        @app.post('/upload')
        def upload(req):
            filename = req.headers.get('X-File-Name')
            is_first_chunk = req.headers.get('X-Start', '0') == '1'
            chunk = req.body
            chunk_size = len(chunk)

            # Ensure containing directory exists
            dir_name = '/'.join(filename.split('/')[:-1])
            if dir_name and dir_name not in os.listdir():
                self._mkdirs(dir_name)

            mode = 'wb'  # truncate file if it exists
            if not is_first_chunk:
                mode = 'ab'

            # Write the file containing the received data
            with open(filename, mode) as f:
                if chunk_size > 0:
                    f.write(chunk)

            return get_json(WebServer.GetOKDict())

        @app.route('/get_sys_stats')
        async def get_sys_stats(request):
            return get_json(self._getSysStats(request))

        @app.route('/get_file_list')
        async def get_file_list(request):
            return get_json(self._getFileList(request))

        @app.route('/get_machine_config')
        async def get_machine_config(request):
            return get_json(self._machine_config)

        @app.route('/erase_offline_app')
        async def erase_offline_app(request):
            return get_json(self._eraseOfflineApp())

        @app.route('/mkdir')
        async def mkdir(request):
            return get_json(self._makeDir(request))

        @app.route('/rmdir')
        async def rmdir(request):
            return get_json(self._rmDir(request))

        @app.route('/rmfile')
        async def rmfile(request):
            return get_json(self._rmFile(request))

        @app.route('/get_file')
        async def getfile(request):
            return get_json(self._getFile(request))

        @app.route('/reset_wifi_config')
        async def reset_wifi_config(request):
            return get_json(self.resetWiFiConfig())

        @app.route('/get_active_app_folder')
        async def get_active_app_folder(request):
            return get_json(self.getActiveAppFolder())

        @app.route('/get_inactive_app_folder')
        async def get_inactive_app_folder(request):
            return get_json(self.getInActiveAppFolder())

        @app.route('/swap_active_app')
        async def swap_active_app(request):
            return get_json(self.swapActiveAppFolder())

        @app.route('/reboot')
        async def reboot(request):
            return get_json(self.rebootDevice())

        @app.route('/reset_to_default_config')
        async def reset_to_default_config(request):
            return get_json(self.resetToDefaultConfig())

        @app.route('/wifi_scan')
        async def wifi_scan(request):
            return get_json(self.wifiScan())

        @app.route('/sha256')
        async def sha256(request):
            return get_json(self.sha256File(request))

        @app.route('/gc')
        async def gc(request):
            return get_json(self.collectGarbage())

        @app.route('/shutdown')
        async def shutdown(request):
            request.app.shutdown()
            return get_json(WebServer.GetErrorDict("The server is shutting down..."))

        # The ability to seth the WebREPL password over the REST interface is a clear security hole.
        # This is why this is commented out by default. Remove the comment lines with care.
#        @app.route('/setwebreplpw')
#        async def set_webrepl_password(request):
#            return get_json(self._set_webrepl_password(request))

        @app.route('/')
        @app.route('/<path:path>')
        def serve(request, path='index.html'):
            # Prevent directory traversal
            if '..' in path or path.startswith('/'):
                return '403 Forbidden', 403

            try:
                appFolder = self.getActiveAppFolder()[WebServer.ACTIVE_APP_FOLDER_KEY]
                serverFile = f'{appFolder}/assets/{path}'
                with open(serverFile, 'rb') as f:
                    content = f.read()
                    if self._paramDict:
                        content = self._updateContent(content, self._paramDict)
                    content_type = self.getContentType(path)
                    return Response(body=content, headers={'Content-Type': content_type})

            except Exception:
                return '404 Not Found', 404

        app.run(debug=True, port=self._port)
