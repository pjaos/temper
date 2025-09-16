import sys
import json
import uasyncio as asyncio

RUNNING_APP_KEY = "RUNNING_APP"
CONFIG_FILENAME = "this.machine.cfg"

""" !!! Note that changes to this file can cause the MCU to fail to boot after an upgrade.
    !!! Therefore change with caution."""

def get_active_app():
    """@brief Get the active app from the field in the config dict file.
       @return Either 1 or 2"""
    active_app = 1
    try:
        with open(CONFIG_FILENAME, "r") as read_file:
            config_dict = json.load(read_file)
            if RUNNING_APP_KEY in config_dict:
                aa = config_dict[RUNNING_APP_KEY]
                if aa == 2:
                    active_app = 2
    except Exception:
        # Any errors reading the active app and we revert to app1
        pass
    return active_app


def run_app(app_id, initial_modules):
    """@brief Run an app.
       @param app_id The ID of the app to run (1 or 2).
       @param initial_modules The keys of the initially python modules loaded at startup."""
    # Remove any previously added paths
    for _path in ("/app1", "/app1.lib", "/app2", "/app2.lib"):
        try:
            sys.path.remove(_path)
        except ValueError:
            pass
    # Remove app from the known modules list if it's present
    keys = list(sys.modules.keys())
    for key in keys:
        if key not in initial_modules:
            try:
                del sys.modules[key]
            except KeyError:
                pass

    # Add the required paths
    if app_id == 2:
        sys.path.append("/app2")
        sys.path.append("/app2.lib")
        from app2 import app

    else:
        sys.path.append("/app1")
        sys.path.append("/app1.lib")
        from app1 import app

    asyncio.run(app.start(RUNNING_APP_KEY, CONFIG_FILENAME))


def debug(msg):
    print("DEBUG: {}".format(msg))


def get_loaded_modules():
    """@brief Get a list of the python modules currently loaded."""
    key_list = []
    for key in list(sys.modules.keys()):
        key_list.append(key)
    return key_list


try:
    initial_modules = get_loaded_modules()
    # Save the sys path in case we need to restore it.
    added_sys_paths = []
    try:
        active_app = get_active_app()
        debug("active_app={}".format(active_app))
        run_app(active_app, initial_modules)

    except Exception as ex:
        # In the event of an error revert to inactive app
        debug("main.py Exception")
        sys.print_exception(ex)
        if active_app == 2:
            active_app = 1
        else:
            active_app = 1
        debug("Reverting to app {}".format(active_app))
        run_app(active_app, initial_modules)

finally:
    asyncio.new_event_loop()
