# Temper

A Python tool for discovering temperature and humidity sensor units on the local LAN, recording their readings to a SQLite database, and visualising the data through a web-based dashboard.

---

## Overview

Temper consists of two programs that work together along with the ESP32 based hardware.

- **`temper_db`** — a background collector that listens for sensor broadcasts on the LAN and saves every reading to a local SQLite database.
- **`temper_gui`** — a browser-based dashboard (built with [NiceGUI](https://nicegui.io) and [Plotly](https://plotly.com/python/)) for plotting temperature and humidity data across any time range.

The two programs are independent. `temper_db` can run continuously as a background service while `temper_gui` is started on demand to view the data.

---

## Hardware

Temper is designed to work with TEMPER-branded sensor units that broadcast JSON payloads over UDP on the local network. Each unit reports up to four independent temperature/humidity sensor channels, along with system telemetry (RAM, disk, uptime, RSSI, battery voltage, etc.).

The collector listens on **UDP port 2934** and sends periodic *Are You There* broadcast messages to discover units automatically. No manual IP configuration is required unless you want to filter to a specific unit.

---

## Requirements

- Python 3.10 or later

---


## Installation

The python wheel installer file can be found in the linux folder.

### Using the bundled installer

```bash
python3 install.py linux/temper-<version>-py3-none-any.whl
```

This creates a virtual environment, installs all dependencies, and adds the `temper_db` and `temper_gui` commands to your PATH. A temper_gui launch icon is also added to you desktop.

---

## Usage

### Collector — `temper_db`

Discovers TEMPER units on the local LAN and writes every received reading to the database.

```bash
python -m temper.temper_db [options]
```

| Option | Description |
|---|---|
| `-d`, `--debug` | Enable debug logging (prints each received JSON payload). |
| `-a ADDRESS`, `--address ADDRESS` | Only record data from the unit at this IP address. If omitted, all units found are recorded. |
| `-s SECONDS`, `--seconds SECONDS` | Interval between *Are You There* broadcasts (default: 10 s). |
| `--enable_auto_start` | Register the tool to start on system boot |
| `--disable_auto_start` | Un-register the tool to start on system boot |
| `--check_auto_start` | Check the running status |

**Example — record all units, broadcast every 30 seconds:**

```bash
temper_db --seconds 30
```

**Example — record only one unit:**

```bash
temper_db --address 192.168.0.99
```

**Example Running as a service**

Use the built-in boot manager to have the tool start automatically (Linux only):

```bash
temper_db --seconds 30 --enable_auto_start
```

Press **Ctrl-C** to stop.

### Dashboard — `temper_gui`

Starts a local web server and opens the dashboard in the default browser.

```bash
temper_gui [options]
```

| Option | Description |
|---|---|
| `-d`, `--debug` | Enable debug logging. |
| `-p PORT`, `--port PORT` | TCP port for the NiceGUI web server (default: 8085). |
| `-n`, `--no_web_launch` | Start the server without opening a browser tab automatically. |
| `--enable_auto_start` | Register the tool to start on system boot |
| `--disable_auto_start` | Un-register the tool to start on system boot |
| `--check_auto_start` | Check the running status |

**Example — start on a non-default port:**

```bash
temper_gui --port 9090
```

**Example — headless server (access from another device):**

```bash
temper_gui --no_web_launch
```

Then navigate to `http://<host-ip>:8085` from any browser on the same network, including a mobile phone.

**Example Running as a service**

Use the built-in boot manager to have the tool start automatically (Linux only):

```bash
temper_gui -n --enable_auto_start
```

---

## Dashboard features

The dashboard is responsive and works on both desktop and mobile browsers.

**Sidebar controls**

- **Units** — chips showing every known unit and its total reading count. Click to select a unit and load its data.
- **Time Range** — preset buttons (1h, 6h, 24h, 7 days, 30 days, All) plus a Custom option with date pickers.
- **Plot** — switch between Temperature and Humidity views.
- **Sensor Names** — rename each of the four sensor channels (e.g. *Living Room*, *Loft*, *Outside*). Names are saved to `sensor_names.json` and persist across restarts. The chart legend and stat tiles update immediately on save.

**Main area**

- **Latest Reading** — a tile grid showing the most recent temperature and humidity value for each active sensor on the selected unit.
- **Chart** — an interactive Plotly time-series plot. Hover over any point to see values for all sensors at that timestamp. Zoom and pan with standard Plotly controls.

---

## Data storage

The database and sensor name configuration are stored in:

| Platform | Path |
|---|---|
| Linux / macOS (XDG) | `~/.config/temper/` |
| Linux / macOS (fallback) / Windows | `~/.temper/` |

Files created:

| File | Contents |
|---|---|
| `temper_sensor_data.db` | SQLite database containing all sensor readings. |
| `sensor_names.json` | User-defined display names for the four sensor channels. |

### Database schema

Two tables are used:

**`units`** — one row per discovered device.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key. |
| `unit_name` | TEXT | Unique device identifier (e.g. `TEMPER_DEV`). |
| `device_type` | TEXT | Always `SENSOR` for TEMPER hardware. |
| `product_id` | TEXT | Always `TEMPER`. |
| `ip_address` | TEXT | Last seen IP address. |
| `os` | TEXT | Firmware OS (e.g. `MicroPython`). |
| `group_name` | TEXT | Optional group label from the device. |
| `service_list` | TEXT | Services advertised by the device. |
| `first_seen` | TIMESTAMP | UTC timestamp of first contact. |
| `last_seen` | TIMESTAMP | UTC timestamp of most recent contact. |

**`sensor_readings`** — one row per received broadcast.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key. |
| `unit_id` | INTEGER | Foreign key → `units.id`. |
| `recorded_at` | TIMESTAMP | UTC time the reading was received. |
| `rx_time_secs` | REAL | Unix timestamp from the device itself. |
| `uptime_seconds` | INTEGER | Device uptime in seconds. |
| `sensor_1_temp` … `sensor_4_temp` | REAL | Temperature readings in °C. |
| `sensor_1_humidity` … `sensor_4_humidity` | REAL | Relative humidity readings in %RH. |
| `param_3v3` | REAL | 3.3 V rail voltage. |
| `param_vbat` | REAL | Battery voltage. |
| `param_rssi` | REAL | Wi-Fi signal strength in dBm. |
| `param_board_temp` | REAL | On-board temperature sensor reading. |
| `ram_*`, `disk_*` | INTEGER | RAM and disk usage telemetry. |

### Maintenance

To delete readings older than 90 days from a Python session:

```python
from temper.temper_db import TemperDB
from unittest.mock import MagicMock
db = TemperDB.__new__(TemperDB)
db._uio = MagicMock(); db._options = None
db._db_file = TemperDB.GetDBFile()
deleted = db.prune_readings_older_than(days=90)
print(f"Deleted {deleted} rows")
```

---

## Running tests

Tests use [pytest](https://pytest.org). From the client directory:

```bash
./run_tests.sh
```

The test suite covers all database operations (`TemperDB`) including table creation, unit upsert, reading insertion, time-range filtering, latest-reading queries, and data pruning. No network access or real hardware is required.

---

## Project structure

```
temper/software/client/
├── src/
│   └── temper/
│       ├── temper_db.py        # Collector + database layer
│       └── temper_gui.py       # NiceGUI web dashboard
└── tests/
    └── test_temper_db.py       # pytest test suite
```

---

## Licence

See `LICENSE` in the repository root.
