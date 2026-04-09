#!/usr/bin/env python3

import os
import argparse
import socket
import json
import struct
import psutil
import rich
import sqlite3
import traceback

from datetime import datetime, timezone
from threading import Thread
from time import time, sleep
from pathlib import Path

from p3lib.uio import UIO
from p3lib.helper import logTraceBack
from p3lib.boot_manager import BootManager
from p3lib.helper import get_program_version, getHomePath
from p3lib.netif import NetIF

class LocalYViewCollector(object):
    """@brief This collects data from YView devices on the local LAN only as opposed to connecting to the
              ICONS server and collecting data from there.
        - Sending out AYT messages
        - Forwarding device data to listeners."""

    UDP_SERVER_PORT = 2934
    PRODUCT_ID      = "PRODUCT_ID"
    IP_ADDRESS      = "IP_ADDRESS"
    RX_TIME_SECS    = "RX_TIME_SECS"

    def __init__(self, uio, options):
        """@brief Constructor
           @param uio A UIO instance
           @param options The command line options instance."""
        self._uio                   = uio
        self._options               = options
        self._running               = False
        self._devListenerList       = []       # A list of all the parties interested in receiving device data messages
        self._validProuctIDList     = []
        self._areYouThereThread     = None
        self._deviceIPAddressList   = []

    def close(self, halt=False):
        """@brief Close down the collector.
           @param halt If True When closed the collector will not restart."""
        if self._areYouThereThread:
            self._areYouThereThread.stop()
            self._areYouThereThread = None

        if halt:
            self._running = False

    def start(self, net_if=None):
        """@brief Start the App server.
           @param net_if If defined send the discovery broadcast messages out of this interface."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', LocalYViewCollector.UDP_SERVER_PORT))

        self._uio.info('Sending AYT messages.')
        self._areYouThereThread = AreYouThereThread(sock, net_if=net_if)
        self._areYouThereThread.start()

        self._uio.info("Listening on UDP port %d" % (LocalYViewCollector.UDP_SERVER_PORT) )
        self._running = True
        while self._running:
            data = sock.recv(65536)
            rxTime = time()
            #Ignore the broadcast message we sent
            if data != AreYouThereThread.AreYouThereMessage:
                try:
                    dataStr = data.decode()
                    rx_dict = json.loads(dataStr)
                    if LocalYViewCollector.PRODUCT_ID in rx_dict:
                        prodID = rx_dict[LocalYViewCollector.PRODUCT_ID]
                        # If no product types have been defined, assume we want all those found.
                        # If product types are defined then only forward those that match.
                        if len(self._validProuctIDList) == 0 or prodID in self._validProuctIDList:
                            # Add the time we received the message to the rx_dict
                            rx_dict[LocalYViewCollector.RX_TIME_SECS]=rxTime
                            self._updateListeners(rx_dict)

                        if LocalYViewCollector.IP_ADDRESS in rx_dict:
                            ipAddress = rx_dict[LocalYViewCollector.IP_ADDRESS]
                            if ipAddress not in self._deviceIPAddressList:
                                self._uio.info(f"Found device on {ipAddress}")
                                self._deviceIPAddressList.append(ipAddress)

                except KeyboardInterrupt:
                    self.close()
                    break

                except Exception:
                    raise

    def addDevListener(self, devListener):
        """@brief Add to the list of entities that are interested in the device data.
           @param devListener The device listener (must implement the hear(devDict) method."""
        self._devListenerList.append(devListener)

    def removeAllListeners(self):
        """@brief Remove all listeners for device data."""
        self._devListenerList = []

    def _updateListeners(self, devData):
        """@brief Update all listeners with the device data."""
        for devListener in self._devListenerList:
            startTime = time()
            try:
                devListener.hear(devData)

            except Exception:
                self._uio.errorException()

            exeSecs = time() - startTime
            self._uio.debug(f"EXET: devListener.hear(devData) Took {exeSecs:.6f} seconds to execute.")

    def setValidProductIDList(self, validProductIDList):
        """@brief Set a list of product ID's that we're interested in.
           @param validProductIDList The list we're interested in."""
        self._validProuctIDList = validProductIDList


class AreYouThereThread(Thread):
    """Class to are you there messages to devices"""
    AreYouThereMessage = "{\"AYT\":\"-!#8[dkG^v's!dRznE}6}8sP9}QoIR#?O&pg)Qra\"}"
    PERIODICITY_SECONDS = 10.0
    MULTICAST_ADDRESS   = "255.255.255.255"

    def __init__(self, sock, net_if=None):
        Thread.__init__(self)
        self._running = None
        self.daemon = True
        self._sock = sock
        self._net_if = net_if

    @staticmethod
    def UpdateMultiCastAddressList(subNetMultiCastAddressList, ipList):
        """@brief Update a mulicast address list from a given list of IP addresses."""
        for elem in ipList:
            elems = elem.split("/")
            if len(elems) == 2:
                # Extract the interface IP address. Calc the multicast IP address
                # for the subnet and add this to the list for the interface.
                try:
                    ipAddress = elems[0]
                    subNetMaskBitCount = int(elems[1])
                    intIP = NetIF.IPStr2int(ipAddress)
                    subNetBits = (1<<(32-subNetMaskBitCount))-1
                    intMulticastAddress = intIP | subNetBits
                    subNetMultiCastAddress = NetIF.Int2IPStr(intMulticastAddress)
                    subNetMultiCastAddressList.append( (subNetMultiCastAddress, LocalYViewCollector.UDP_SERVER_PORT) )
                except ValueError:
                    # Ignore errors
                    pass

        return subNetMultiCastAddressList

    @staticmethod
    def NetmaskToCIDR(netmask):
        return sum(bin(struct.unpack("!I", socket.inet_aton(netmask))[0]).count("1") for _ in range(1))

    @staticmethod
    def GetInterfaceDict():
        interfaces = psutil.net_if_addrs()
        if_dict = {}
        for iface, addrs in interfaces.items():
            ip_list = []
            for addr in addrs:
                if addr.family == socket.AF_INET:  # IPv4 addresses
                    ip = addr.address
                    netmask = addr.netmask
                    cidr = AreYouThereThread.NetmaskToCIDR(netmask)
                    ip_list.append(f"{ip}/{cidr}")
            if len(ip_list) > 0:
                if_dict[iface]=ip_list
        return if_dict

    @staticmethod
    def GetSubnetMultiCastAddress(ifName):
        """@brief Get the subnet multicast IP address for the given interface.
           @param ifName The name of a local network interface.
           @return A tuple of all the subnet multicast IP addresses."""
        subNetMultiCastAddressList = []
        # Don't exit until we have the multicast address
        while len(subNetMultiCastAddressList) == 0:
            ifDict = AreYouThereThread.GetInterfaceDict()
            if ifName is None or len(ifName) == 0:
                for _ifName in ifDict:
                    ipList = ifDict[_ifName]
                    AreYouThereThread.UpdateMultiCastAddressList(subNetMultiCastAddressList, ipList)

            if ifName in ifDict:
                ipList = ifDict[ifName]
                AreYouThereThread.UpdateMultiCastAddressList(subNetMultiCastAddressList, ipList)

            if len(subNetMultiCastAddressList) == 0:
                # Avoid spinning at 100% CPU while waiting for a network interface
                sleep(1)

        return tuple(subNetMultiCastAddressList)

    def run(self):
        self._running = True
        addressList = AreYouThereThread.GetSubnetMultiCastAddress(self._net_if)

        while self._running:
            try:
                for address in addressList:
                    self._sock.sendto(AreYouThereThread.AreYouThereMessage.encode(), address)
            # If the local interface goes down this error will be generated. In this situation we want to keep trying to
            # send an AYT message in order to hear from Yview devices when the interface comes back up. This ensures the
            # AYT messages continue to be sent if the house power drops for a short while as occurred recently.
            except OSError:
                pass
            sleep(AreYouThereThread.PERIODICITY_SECONDS)

    def stop(self):
        """@brief Stop the server running."""
        self._running = False


class TemperDB(object):
    """@brief Discover temper hardware on the LAN and save data retrieved from them to a DB."""

    VERSION = get_program_version('temper')
    VALID_PRODUCT_ID_LIST = ['TEMPER']
    IP_ADDRESS_KEY = "IP_ADDRESS"

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

    @staticmethod
    def GetDBFile():
        app_data_path = TemperDB.GetAppDataPath()
        return os.path.join(app_data_path, "temper_sensor_data.db")

    def __init__(self, uio, options):
        """@brief Constructor
           @param uio A UIO instance handling user input and output (E.G stdin/stdout or a GUI)
           @param options An instance of the OptionParser command line options."""
        self._uio = uio
        self._options = options
        self._db_file = TemperDB.GetDBFile()
        # Create tables once at startup rather than on every save call
        with self.get_connection() as conn:
            self.create_tables(conn)

    def reap(self):
        """@brief Send messages to temper hardware. Retrieve data from them and save it to a local sqlite db."""
        AreYouThereThread.PERIODICITY_SECONDS = self._options.seconds
        # Start a background thread that gets data from temper hardware.
        self._start_temper_hardware_listener()

    def _start_temper_hardware_listener(self):
        """@brief Search for all TEMPER units on the LAN and display stats received from all units."""
        # Start running the local collector in a separate thread
        self._localYViewCollector = LocalYViewCollector(self._uio, self._options)
        self._localYViewCollector.setValidProductIDList(TemperDB.VALID_PRODUCT_ID_LIST)
        self._localYViewCollector.addDevListener(self)
        self._localYViewCollector.start()
        # Wait here while until user CTRL C
        while True:
            sleep(1)

    def hear(self, devDict):
        """@brief Called when data is received from the device.
           @param devDict The device dict."""
        # If the user wants to view data from a single unit.
        if self._options.address:
            if TemperDB.IP_ADDRESS_KEY in devDict and devDict[TemperDB.IP_ADDRESS_KEY] == self._options.address:
                if self._uio.isDebugEnabled():
                    rich.print_json(json.dumps(devDict))
        # If the user wants to view data from all units.
        else:
            if self._uio.isDebugEnabled():
                rich.print_json(json.dumps(devDict))

        try:
            self.save_sensor_json(devDict)
            self._uio.debug(f"Updated {self._db_file}")

        except Exception:
            # Always log save failures, not just in debug mode
            self._uio.error(f"Failed to save sensor data: {traceback.format_exc()}")

    def get_connection(self, db_path: str = "") -> sqlite3.Connection:
        if not db_path:
            db_path = self._db_file

        conn = sqlite3.connect(db_path, timeout=20)
        conn.row_factory = sqlite3.Row

        # Recommended for reliability with concurrent writers
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        return conn

    def create_tables(self, conn: sqlite3.Connection) -> None:
        """Create a units lookup table and a readings table that references it."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS units (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_name   TEXT UNIQUE NOT NULL,
                device_type TEXT,
                product_id  TEXT,
                ip_address  TEXT,
                os          TEXT,
                group_name  TEXT,
                service_list TEXT,
                first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_id                 INTEGER NOT NULL REFERENCES units(id),
                recorded_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- UTC
                uptime_seconds          INTEGER,
                rx_time_secs            REAL,
                ram_free_bytes          INTEGER,
                ram_used_bytes          INTEGER,
                ram_total_bytes         INTEGER,
                ram_percentage_used     INTEGER,
                disk_free_bytes         INTEGER,
                disk_used_bytes         INTEGER,
                disk_total_bytes        INTEGER,
                disk_percentage_used    INTEGER,
                param_3v3               REAL,
                param_vbat              REAL,
                param_rssi              REAL,
                param_board_temp        REAL,
                sensor_1_temp           REAL,
                sensor_1_humidity       REAL,
                sensor_2_temp           REAL,
                sensor_2_humidity       REAL,
                sensor_3_temp           REAL,
                sensor_3_humidity       REAL,
                sensor_4_temp           REAL,
                sensor_4_humidity       REAL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_unit_id
            ON sensor_readings(unit_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_recorded_at
            ON sensor_readings(recorded_at)
        """)
        conn.commit()

    def upsert_unit(self, conn: sqlite3.Connection, data: dict) -> int:
        """Insert the unit if new, or update its metadata and last_seen if known.
        Returns the unit's id."""
        conn.execute("""
            INSERT INTO units (unit_name, device_type, product_id, ip_address, os, group_name, service_list)
            VALUES (:unit_name, :device_type, :product_id, :ip_address, :os, :group_name, :service_list)
            ON CONFLICT(unit_name) DO UPDATE SET
                device_type  = excluded.device_type,
                product_id   = excluded.product_id,
                ip_address   = excluded.ip_address,
                os           = excluded.os,
                group_name   = excluded.group_name,
                service_list = excluded.service_list,
                last_seen    = CURRENT_TIMESTAMP
        """, {
            "unit_name":    data.get("UNIT_NAME"),
            "device_type":  data.get("DEVICE_TYPE"),
            "product_id":   data.get("PRODUCT_ID"),
            "ip_address":   data.get("IP_ADDRESS"),
            "os":           data.get("OS"),
            "group_name":   data.get("GROUP_NAME"),
            "service_list": data.get("SERVICE_LIST"),
        })
        row = conn.execute(
            "SELECT id FROM units WHERE unit_name = ?", (data.get("UNIT_NAME"),)
        ).fetchone()
        return row["id"]

    def insert_reading(self, conn: sqlite3.Connection, unit_id: int, data: dict) -> int:
        cursor = conn.execute("""
            INSERT INTO sensor_readings (
                unit_id, uptime_seconds, rx_time_secs,
                ram_free_bytes, ram_used_bytes, ram_total_bytes, ram_percentage_used,
                disk_free_bytes, disk_used_bytes, disk_total_bytes, disk_percentage_used,
                param_3v3, param_vbat, param_rssi, param_board_temp,
                sensor_1_temp, sensor_1_humidity,
                sensor_2_temp, sensor_2_humidity,
                sensor_3_temp, sensor_3_humidity,
                sensor_4_temp, sensor_4_humidity
            ) VALUES (
                :unit_id, :uptime_seconds, :rx_time_secs,
                :ram_free_bytes, :ram_used_bytes, :ram_total_bytes, :ram_percentage_used,
                :disk_free_bytes, :disk_used_bytes, :disk_total_bytes, :disk_percentage_used,
                :param_3v3, :param_vbat, :param_rssi, :param_board_temp,
                :sensor_1_temp, :sensor_1_humidity,
                :sensor_2_temp, :sensor_2_humidity,
                :sensor_3_temp, :sensor_3_humidity,
                :sensor_4_temp, :sensor_4_humidity
            )
        """, {
            "unit_id":              unit_id,
            "uptime_seconds":       data.get("UPTIME_SECONDS"),
            "rx_time_secs":         data.get("RX_TIME_SECS"),
            "ram_free_bytes":       data.get("RAM_FREE_BYTES"),
            "ram_used_bytes":       data.get("RAM_USED_BYTES"),
            "ram_total_bytes":      data.get("RAM_TOTAL_BYTES"),
            "ram_percentage_used":  data.get("RAM_PERCENTAGE_USED"),
            "disk_free_bytes":      data.get("DISK_FREE_BYTES"),
            "disk_used_bytes":      data.get("DISK_USED_BYTES"),
            "disk_total_bytes":     data.get("DISK_TOTAL_BYTES"),
            "disk_percentage_used": data.get("DISK_PERCENTAGE_USED"),
            "param_3v3":            float(data["PARAM_3V3"])        if data.get("PARAM_3V3")        else None,
            "param_vbat":           float(data["PARAM_VBAT"])       if data.get("PARAM_VBAT")       else None,
            "param_rssi":           float(data["PARAM_RSSI"])       if data.get("PARAM_RSSI")       else None,
            "param_board_temp":     float(data["PARAM_BOARD_TEMP"]) if data.get("PARAM_BOARD_TEMP") else None,
            "sensor_1_temp":        data.get("PARAM_SENSOR_1_TEMP"),
            "sensor_1_humidity":    data.get("PARAM_SENSOR_1_HUMIDITY"),
            "sensor_2_temp":        data.get("PARAM_SENSOR_2_TEMP"),
            "sensor_2_humidity":    data.get("PARAM_SENSOR_2_HUMIDITY"),
            "sensor_3_temp":        data.get("PARAM_SENSOR_3_TEMP"),
            "sensor_3_humidity":    data.get("PARAM_SENSOR_3_HUMIDITY"),
            "sensor_4_temp":        data.get("PARAM_SENSOR_4_TEMP"),
            "sensor_4_humidity":    data.get("PARAM_SENSOR_4_HUMIDITY"),
        })
        return cursor.lastrowid

    def save_sensor_json(self, json_data: str | dict, db_path: str = "") -> int:
        """Main entry point. Pass either a JSON string or an already-parsed dict."""
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        with self.get_connection(db_path) as conn:
            unit_id = self.upsert_unit(conn, data)
            row_id = self.insert_reading(conn, unit_id, data)
            conn.commit()
        return row_id

    def get_readings_for_unit(self,
                              unit_name: str,
                              db_path: str = "",
                              limit: int = 1000,
                              since: datetime | None = None) -> list[dict]:
        """Fetch readings for a given unit name, newest first.
        @param unit_name  The UNIT_NAME to query.
        @param db_path    Override the default database path.
        @param limit      Maximum number of rows to return (default 1000).
        @param since      If given, only return readings at or after this UTC datetime."""
        query = """
            SELECT r.*, u.unit_name, u.ip_address
            FROM sensor_readings r
            JOIN units u ON u.id = r.unit_id
            WHERE u.unit_name = ?
        """
        params: list = [unit_name]
        if since is not None:
            query += " AND r.recorded_at >= ?"
            params.append(since.strftime("%Y-%m-%d %H:%M:%S"))
        query += " ORDER BY r.recorded_at DESC LIMIT ?"
        params.append(limit)
        with self.get_connection(db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_all_units(self, db_path: str = "") -> list[dict]:
        """Return a summary of all known units."""
        with self.get_connection(db_path) as conn:
            rows = conn.execute("""
                SELECT u.*, COUNT(r.id) as reading_count
                FROM units u
                LEFT JOIN sensor_readings r ON r.unit_id = u.id
                GROUP BY u.id
                ORDER BY u.unit_name
            """).fetchall()
        return [dict(row) for row in rows]


    def get_latest_reading_per_unit(self, db_path: str = "") -> list[dict]:
        """Return the most recent reading for every known unit. Useful for a status dashboard."""
        with self.get_connection(db_path) as conn:
            rows = conn.execute("""
                SELECT r.*, u.unit_name, u.ip_address
                FROM sensor_readings r
                JOIN units u ON u.id = r.unit_id
                WHERE r.id IN (
                    SELECT MAX(id) FROM sensor_readings GROUP BY unit_id
                )
                ORDER BY u.unit_name
            """).fetchall()
        return [dict(row) for row in rows]

    def prune_readings_older_than(self, days: int, db_path: str = "") -> int:
        """Delete readings older than the given number of days.
        @param days    Readings strictly older than this many days are removed.
        @return        The number of rows deleted."""
        cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection(db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM sensor_readings
                WHERE recorded_at < datetime(?, '-' || ? || ' days')
            """, (cutoff, days))
            conn.commit()
        return cursor.rowcount


def main():
    """@brief Program entry point"""
    uio = UIO()
    uio.info(f"temper: v{TemperDB.VERSION}")

    try:
        parser = argparse.ArgumentParser(description="Discover temper hardware on the LAN and save data retrieved from them to a DB.",
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("-d", "--debug",   action='store_true', help="Enable debugging.")
        parser.add_argument("-a", "--address", help="Enter the IP address of the temper unit to record data from. If not set then data is recorded from all temper units found.", default=None)
        parser.add_argument("-s", "--seconds",  type=int, help="The sensor poll time in seconds (default = 60).", default=60)

        # Add args for auto boot cmd
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
