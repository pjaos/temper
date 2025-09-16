import json
from lib.hardware import const


class MachineConfig(object):
    """@brief Responsible for management of config attributes for the machine.
              The machine configuration is saved to flash for persistent storage."""
    FACTORY_CONFIG_FILENAME = const("factory.cfg")

    #This must be set when app1/app.py or app2/app.py is called from main.py
    CONFIG_FILENAME = None

    # Keys must be int values. Values less than 0 are reserved.

    #This must be set when app1/app.py or app2/app.py is called from main.py
    RUNNING_APP_KEY = None  # This dict key is reserved for the key that defines

    # which app is running. User defines keys should be 0
    # or greater.
    WIFI_KEY = const("WIFI")  # Holds a sub dict of the WiFi configuration.

    WIFI_CONFIGURED_KEY = const("WIFI_CONFIGURED")
    MODE_KEY = const("MODE")
    AP_CHANNEL_KEY = const("AP_CHANNEL")
    SSID_KEY = const("SSID")
    PASSWORD_KEY = const("PASSWORD")

    AP_MODE = 0
    STA_MODE = 1
    DEFAULT_AP_CHANNEL = 3
    DEFAULT_AP_PASSWORD = const("12345678")
    DEFAULT_SSID = const("")

    DEFAULT_WIFI_DICT = {
        WIFI_CONFIGURED_KEY: 0,
        MODE_KEY: AP_MODE,
        AP_CHANNEL_KEY: DEFAULT_AP_CHANNEL,
        SSID_KEY: DEFAULT_SSID,
        PASSWORD_KEY: DEFAULT_AP_PASSWORD}

    @staticmethod
    def Merge(dict1, dict2):
        """@brief Merge dict 2 into dict 1. The result_dict will contain all the keys from
                  dict 1. Values from dict 2 will override those held in dict 1.
                  This method allows merging of dicts that contain dicts."""
        return dict1 | dict2

    def __init__(self, default_config_dict):
        """@brief Constructor."""
        self._defaultConfigDict = default_config_dict
        self._config_dict = self._defaultConfigDict
        self.load()

    def load(self, purge_keys=True, filename=None):
        """@brief Load the config. If the config file exists in flash then this will
                  be loaded. If not then the default config is loaded and saved to flash.
           @param purge_keys If True remove unused (not in default dict) keys.
           @param filename The filename to load the config from. If this is unset then the
                  MachineConfig.CONFIG_FILENAME file is used."""
        # The default config filename.
        cfg_filename = MachineConfig.CONFIG_FILENAME
        # If the caller has defined a non default file
        if filename is not None:
            cfg_filename = filename

        config_dict = {}
        try:
            with open(cfg_filename, "r") as read_file:
                config_dict = json.load(read_file)
        except BaseException:
            config_dict = self._defaultConfigDict

        # Delete the dict created before the running app key was defined.
        if "null" in config_dict:
            del config_dict["null"]

        # Merge the factory config into the machine config file if present.
        factory_dict = {}
        try:
            with open(MachineConfig.FACTORY_CONFIG_FILENAME, "r") as read_file:
                factory_dict = json.load(read_file)

            for key in factory_dict:
                config_dict[key] = factory_dict[key]

        except BaseException:
            pass

        # Merge the self._defaultConfigDict and config_dict dicts so that we ensure we have all the keys from
        # self._defaultConfigDict. This ensures if keys are added to self._defaultConfigDict then they are
        # automatically added to any saved config.
        self._config_dict = MachineConfig.Merge(
            self._defaultConfigDict, config_dict)
        self._ensure_valid_cfg_dict(self._config_dict)

        # Remove keys not in the default dict if required
        if purge_keys:
            for key in self._config_dict:
                # If not one of the protected keys that must be present
                if key != MachineConfig.RUNNING_APP_KEY and \
                   key != MachineConfig.WIFI_KEY:
                    if key not in self._defaultConfigDict:
                        del self._config_dict[key]

        self.store()

    def _ensure_valid_cfg_dict(self, cfg_dict):
        # Ensure default app is 1
        if MachineConfig.RUNNING_APP_KEY not in self._config_dict:
            self._config_dict[MachineConfig.RUNNING_APP_KEY] = 1

        # If missing the wifi cfg set default sub dict
        if MachineConfig.WIFI_KEY not in cfg_dict:
            self.reset_wifi_config()

    def store(self, filename=None, cfg_dict=None):
        """@brief Save the config dict to flash.
           @param filename The filename in which to store the config. If this is unset then the
                  MachineConfig.CONFIG_FILENAME file is used.
           @param cfg_dict The dictionary to store.
                  If left as None then the machine config dictionary is stored."""
        if cfg_dict is None:
            cfg_dict = self._config_dict

        self._ensure_valid_cfg_dict(cfg_dict)

        # The default config filename.
        cfg_filename = MachineConfig.CONFIG_FILENAME
        if filename is not None:
            cfg_filename = filename
        fd = open(cfg_filename, 'w')
        fd.write(json.dumps(cfg_dict))
        fd.close()

    def is_parameter(self, key):
        """@brief Determine if the key is present in the config Dictionary.
           @return True if the key is present in the config dictionary."""
        present = False
        if key in self._config_dict:
            present = True
        return present

    def get(self, _key):
        """@brief Get a value from the config dict.
           @param _key This may be
                       - A string that is the key to a dict value at the top level.
                       - A list of keys that lead to the value in the dict.
           @return The attribute value or None if not found."""

        if isinstance(_key, str):
            if _key in self._config_dict:
                current_value = self._config_dict[_key]
            else:
                current_value = None

        else:
            current_value = self._config_dict
            for key in _key:
                if key in current_value:
                    current_value = current_value[key]
                else:
                    current_value = None

        return current_value

    def set(self, _key, value):
        """@brief Set the value of a dict key.
           @param _key This may be
                       - A string that is the key to a dict value at the top level.
                       - A list of keys that lead to the value in the dict.
           @param value The value to set the attribute to."""
        if isinstance(_key, str):
            self._config_dict[_key] = value

        else:
            current_value = self._config_dict
            for key in _key:
                if key in current_value:
                    if isinstance(current_value[key], dict):
                        current_value = current_value[key]
            current_value[key] = value

        self.store()

    def set_defaults(self):
        """@brief Reset the dict to the defaults."""
        # We set all config values to defaults except for the running app because we
        # don't want to change to a different software release when the WiFi button
        # is held down to force config defaults.
        current_app = None
        if MachineConfig.RUNNING_APP_KEY in self._config_dict:
            current_app = self._config_dict[MachineConfig.RUNNING_APP_KEY]
        self._config_dict = self._defaultConfigDict
        if current_app:
            self._config_dict[MachineConfig.RUNNING_APP_KEY] = current_app
        self.store()

    def __repr__(self):
        """@brief Get a string representation of the config instance."""
        return str(self._config_dict)

    def save_factory_config(self, required_keys):
        """@brief Save the factory configuration file.
           @param required_keys A list of the dict keys required.
           @return The filename the factory config is saved to."""
        factory_dict = {}
        for key in required_keys:
            if not isinstance(key, int):
                raise Exception(
                    f"factory config dict keys must be int instances. Found {type(key)} = {str(key)}")

            if key in self._config_dict:
                if key not in self._config_dict:
                    raise Exception(
                        f"The factory config key, {key} is missing from the {MachineConfig.CONFIG_FILENAME} file.")

                factory_dict[key] = self._config_dict[key]
        self.store(filename=MachineConfig.FACTORY_CONFIG_FILENAME,
                   cfg_dict=factory_dict)
        return MachineConfig.FACTORY_CONFIG_FILENAME

    def reset_wifi_config(self):
        """@breif Reset the WiFi configuration to the default values."""
        self._config_dict[MachineConfig.WIFI_KEY] = MachineConfig.DEFAULT_WIFI_DICT
        self.store()
