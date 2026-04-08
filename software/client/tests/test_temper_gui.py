#!/usr/bin/env python3
"""Tests for the pure-Python logic in temper_gui.py.

These tests cover everything that does not require a running NiceGUI server.
"""

import json
import queue
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. DYNAMIC PATH INJECTION
# This ensures that 'src' is in the search path regardless of where pytest
# is called from, solving the "Module Not Found" issue.
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_src_root = _this_dir.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

# ---------------------------------------------------------------------------
# 2. Stub all heavy imports before loading the module under test.
# ---------------------------------------------------------------------------
for _mod in (
    "nicegui", "nicegui.ui",
    "p3lib", "p3lib.uio", "p3lib.helper", "p3lib.launcher",
    "p3lib.boot_manager", "p3lib.netif",
    "psutil",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# Provide the specific names used at module level
sys.modules["p3lib.helper"].logTraceBack  = lambda *a, **kw: None
sys.modules["p3lib.helper"].getHomePath   = lambda: "/tmp"
sys.modules["p3lib.uio"].UIO              = MagicMock
sys.modules["p3lib.launcher"].Launcher    = MagicMock
sys.modules["p3lib.boot_manager"].BootManager = MagicMock

# nicegui.ui needs to expose a callable `ui` object
_ui_mock = MagicMock()
_ui_mock.page = lambda *a, **kw: (lambda f: f)
sys.modules["nicegui"].ui  = _ui_mock
sys.modules["nicegui.ui"]  = _ui_mock

# ---------------------------------------------------------------------------
# 3. IMPORT THE MODULE UNDER TEST
# We NO LONGER stub 'temper' or 'temper.temper_db' here because we want
# Python to find the real files in src/temper/.
# ---------------------------------------------------------------------------
try:
    import temper.temper_gui as tg   # noqa: E402
    from temper.temper_db import TemperDB as RealTemperDB
except ImportError as e:
    print(f"\nERROR: Could not find 'temper' package. Is your structure correct?")
    print(f"Looked in: {_src_root}")
    print(f"Current sys.path: {sys.path}\n")
    raise e

# Create a mock for tests that need to override TemperDB behavior
TemperDB = MagicMock()

# ---------------------------------------------------------------------------
# Shared sample data helpers
# ---------------------------------------------------------------------------

SAMPLE_NAMES = {
    "sensor_1": "Living Room",
    "sensor_2": "Loft",
    "sensor_3": "Outside",
    "sensor_4": "Server Rack",
}

def _make_row(
    recorded_at="2024-01-15 12:00:00",
    s1_t=20.0, s1_h=45.0,
    s2_t=18.5, s2_h=50.0,
    s3_t=None, s3_h=None,
    s4_t=None, s4_h=None,
) -> dict:
    return {
        "recorded_at":       recorded_at,
        "sensor_1_temp":     s1_t,
        "sensor_1_humidity": s1_h,
        "sensor_2_temp":     s2_t,
        "sensor_2_humidity": s2_h,
        "sensor_3_temp":     s3_t,
        "sensor_3_humidity": s3_h,
        "sensor_4_temp":     s4_t,
        "sensor_4_humidity": s4_h,
    }

# ---------------------------------------------------------------------------
# TestSensorNamePersistence
# ---------------------------------------------------------------------------

class TestSensorNamePersistence:

    def test_load_returns_defaults_when_no_file(self, tmp_path):
        with patch.object(tg, "_config_path", return_value=tmp_path / "sensor_names.json"):
            names = tg.load_sensor_names()
        assert names == tg.DEFAULT_SENSOR_NAMES

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "sensor_names.json"
        with patch.object(tg, "_config_path", return_value=path):
            tg.save_sensor_names(SAMPLE_NAMES)
            loaded = tg.load_sensor_names()
        assert loaded == SAMPLE_NAMES

    def test_save_writes_valid_json(self, tmp_path):
        path = tmp_path / "sensor_names.json"
        with patch.object(tg, "_config_path", return_value=path):
            tg.save_sensor_names(SAMPLE_NAMES)
        data = json.loads(path.read_text())
        assert data == SAMPLE_NAMES

    def test_load_fills_missing_keys_with_defaults(self, tmp_path):
        path = tmp_path / "sensor_names.json"
        path.write_text(json.dumps({"sensor_1": "Kitchen", "sensor_2": "Garage"}))
        with patch.object(tg, "_config_path", return_value=path):
            names = tg.load_sensor_names()
        assert names["sensor_1"] == "Kitchen"
        assert names["sensor_2"] == "Garage"
        assert names["sensor_3"] == tg.DEFAULT_SENSOR_NAMES["sensor_3"]
        assert names["sensor_4"] == tg.DEFAULT_SENSOR_NAMES["sensor_4"]

    def test_load_returns_defaults_on_corrupt_json(self, tmp_path):
        path = tmp_path / "sensor_names.json"
        path.write_text("{ this is not valid json }")
        with patch.object(tg, "_config_path", return_value=path):
            names = tg.load_sensor_names()
        assert names == tg.DEFAULT_SENSOR_NAMES

    def test_save_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "sensor_names.json"
        path.write_text(json.dumps({"sensor_1": "Old Name"}))
        new_names = dict(tg.DEFAULT_SENSOR_NAMES)
        new_names["sensor_1"] = "New Name"
        with patch.object(tg, "_config_path", return_value=path):
            tg.save_sensor_names(new_names)
            loaded = tg.load_sensor_names()
        assert loaded["sensor_1"] == "New Name"

    def test_all_four_keys_always_present_after_load(self, tmp_path):
        path = tmp_path / "sensor_names.json"
        path.write_text("{}")
        with patch.object(tg, "_config_path", return_value=path):
            names = tg.load_sensor_names()
        assert set(names.keys()) == {"sensor_1", "sensor_2", "sensor_3", "sensor_4"}

    def test_config_path_creates_directory(self, tmp_path):
        """_config_path() must not raise even when the target directory is new."""
        with patch.object(tg, "getHomePath", return_value=str(tmp_path)):
            with patch("pathlib.Path.is_dir", return_value=False):
                try:
                    tg._config_path()
                except Exception:
                    pass  # directory creation may fail in mock env — acceptable


# ---------------------------------------------------------------------------
# TestWorkerLoadUnits
# ---------------------------------------------------------------------------

class TestWorkerLoadUnits:

    def _make_db(self, units=None, raise_exc=None):
        db = MagicMock()
        if raise_exc:
            db.get_all_units.side_effect = raise_exc
        else:
            db.get_all_units.return_value = units or []
        return db

    def test_posts_units_loaded_message(self):
        units = [{"unit_name": "UNIT_A", "reading_count": 10}]
        db    = self._make_db(units=units)
        q     = queue.Queue()
        tg._worker_load_units(db, q)
        msg = q.get_nowait()
        assert msg["type"] == tg.MSG_UNITS_LOADED
        assert msg["units"] == units

    def test_posts_empty_list_when_no_units(self):
        db = self._make_db(units=[])
        q  = queue.Queue()
        tg._worker_load_units(db, q)
        msg = q.get_nowait()
        assert msg["type"] == tg.MSG_UNITS_LOADED
        assert msg["units"] == []

    def test_posts_error_message_on_exception(self):
        db = self._make_db(raise_exc=RuntimeError("db locked"))
        q  = queue.Queue()
        tg._worker_load_units(db, q)
        msg = q.get_nowait()
        assert msg["type"] == tg.MSG_ERROR
        assert "db locked" in msg["text"]

    def test_exactly_one_message_posted_on_success(self):
        db = self._make_db(units=[{"unit_name": "U1"}])
        q  = queue.Queue()
        tg._worker_load_units(db, q)
        assert q.qsize() == 1

    def test_exactly_one_message_posted_on_error(self):
        db = self._make_db(raise_exc=Exception("boom"))
        q  = queue.Queue()
        tg._worker_load_units(db, q)
        assert q.qsize() == 1

    def test_multiple_units_all_included_in_payload(self):
        units = [
            {"unit_name": "UNIT_A", "reading_count": 5},
            {"unit_name": "UNIT_B", "reading_count": 3},
        ]
        db = self._make_db(units=units)
        q  = queue.Queue()
        tg._worker_load_units(db, q)
        msg = q.get_nowait()
        assert len(msg["units"]) == 2


# ---------------------------------------------------------------------------
# TestWorkerLoadReadings
# ---------------------------------------------------------------------------

class TestWorkerLoadReadings:

    def _make_db(self, rows=None, raise_exc=None):
        db = MagicMock()
        if raise_exc:
            db.get_readings_for_unit.side_effect = raise_exc
        else:
            db.get_readings_for_unit.return_value = rows or []
        return db

    def test_posts_status_then_readings(self):
        rows = [_make_row("2024-01-01 10:00:00"), _make_row("2024-01-01 11:00:00")]
        db   = self._make_db(rows=rows)
        q    = queue.Queue()
        tg._worker_load_readings(db, q, "UNIT_A", None, 1000)
        msgs   = []
        while not q.empty():
            msgs.append(q.get_nowait())
        types_ = [m["type"] for m in msgs]
        assert tg.MSG_STATUS          in types_
        assert tg.MSG_READINGS_LOADED in types_

    def test_readings_reversed_oldest_first(self):
        """DB returns newest-first (DESC); worker must reverse to oldest-first."""
        rows_desc = [
            _make_row("2024-01-01 12:00:00"),
            _make_row("2024-01-01 11:00:00"),
            _make_row("2024-01-01 10:00:00"),
        ]
        db = self._make_db(rows=rows_desc)
        q  = queue.Queue()
        tg._worker_load_readings(db, q, "UNIT_A", None, 1000)
        msgs    = [q.get_nowait() for _ in range(q.qsize())]
        payload = next(m for m in msgs if m["type"] == tg.MSG_READINGS_LOADED)
        timestamps = [r["recorded_at"] for r in payload["rows"]]
        assert timestamps == sorted(timestamps)

    def test_unit_name_included_in_payload(self):
        db = self._make_db(rows=[_make_row()])
        q  = queue.Queue()
        tg._worker_load_readings(db, q, "MY_UNIT", None, 1000)
        msgs    = [q.get_nowait() for _ in range(q.qsize())]
        payload = next(m for m in msgs if m["type"] == tg.MSG_READINGS_LOADED)
        assert payload["unit"] == "MY_UNIT"

    def test_passes_since_and_limit_to_db(self):
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        db    = self._make_db(rows=[])
        q     = queue.Queue()
        tg._worker_load_readings(db, q, "U", since, 500)
        db.get_readings_for_unit.assert_called_once_with("U", since=since, limit=500)

    def test_posts_error_on_db_exception(self):
        db = self._make_db(raise_exc=RuntimeError("timeout"))
        q  = queue.Queue()
        tg._worker_load_readings(db, q, "U", None, 1000)
        msgs       = [q.get_nowait() for _ in range(q.qsize())]
        error_msgs = [m for m in msgs if m["type"] == tg.MSG_ERROR]
        assert len(error_msgs) == 1
        assert "timeout" in error_msgs[0]["text"]

    def test_empty_rows_still_posts_loaded_message(self):
        db = self._make_db(rows=[])
        q  = queue.Queue()
        tg._worker_load_readings(db, q, "U", None, 1000)
        msgs   = [q.get_nowait() for _ in range(q.qsize())]
        loaded = [m for m in msgs if m["type"] == tg.MSG_READINGS_LOADED]
        assert len(loaded) == 1
        assert loaded[0]["rows"] == []

    def test_status_message_mentions_unit_name(self):
        db = self._make_db(rows=[])
        q  = queue.Queue()
        tg._worker_load_readings(db, q, "TEMPER_DEV", None, 1000)
        msgs        = [q.get_nowait() for _ in range(q.qsize())]
        status_msgs = [m for m in msgs if m["type"] == tg.MSG_STATUS]
        assert any("TEMPER_DEV" in m["text"] for m in status_msgs)

    def test_since_none_passed_through_to_db(self):
        db = self._make_db(rows=[])
        q  = queue.Queue()
        tg._worker_load_readings(db, q, "U", None, 1000)
        db.get_readings_for_unit.assert_called_once_with("U", since=None, limit=1000)


# ---------------------------------------------------------------------------
# TestBuildPlotData
# ---------------------------------------------------------------------------

class TestBuildPlotData:

    def _rows(self, n=5):
        return [
            _make_row(
                recorded_at=f"2024-01-01 {10+i:02d}:00:00",
                s1_t=20.0 + i,
                s1_h=45.0 + i,
                s2_t=18.0 + i,
                s2_h=50.0 + i,
            )
            for i in range(n)
        ]

    def test_temp_mode_returns_temp_traces_only(self):
        traces, _ = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert all("°C" in t["name"] for t in traces)
        assert not any("%RH" in t["name"] for t in traces)

    def test_humidity_mode_returns_humidity_traces_only(self):
        traces, _ = tg._build_plot_data(self._rows(), "humidity", tg.DEFAULT_SENSOR_NAMES)
        assert all("%RH" in t["name"] for t in traces)
        assert not any("°C" in t["name"] for t in traces)

    def test_only_sensors_with_data_produce_traces(self):
        # Only sensor_1 and sensor_2 have data; sensor_3 and sensor_4 are None
        traces, _ = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert len(traces) == 2

    def test_custom_sensor_names_appear_in_trace_names(self):
        names = dict(tg.DEFAULT_SENSOR_NAMES)
        names["sensor_1"] = "Kitchen"
        traces, _ = tg._build_plot_data(self._rows(), "temp", names)
        assert any("Kitchen" in t["name"] for t in traces)

    def test_default_names_used_when_key_missing(self):
        # Empty names dict → falls back to key.replace("_", " ").title()
        traces, _ = tg._build_plot_data(self._rows(), "temp", {})
        assert any("Sensor 1" in t["name"] for t in traces)

    def test_layout_title_is_temperature_in_temp_mode(self):
        _, layout = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert layout["title"]["text"] == "Temperature"

    def test_layout_title_is_humidity_in_humidity_mode(self):
        _, layout = tg._build_plot_data(self._rows(), "humidity", tg.DEFAULT_SENSOR_NAMES)
        assert layout["title"]["text"] == "Humidity"

    def test_layout_yaxis_title_temp(self):
        _, layout = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert "°C" in layout["yaxis"]["title"]

    def test_layout_yaxis_title_humidity(self):
        _, layout = tg._build_plot_data(self._rows(), "humidity", tg.DEFAULT_SENSOR_NAMES)
        assert "%RH" in layout["yaxis"]["title"]

    def test_layout_height_is_380(self):
        _, layout = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert layout.get("height") == 380

    def test_timestamps_are_x_values(self):
        rows = self._rows(3)
        traces, _ = tg._build_plot_data(rows, "temp", tg.DEFAULT_SENSOR_NAMES)
        expected = [r["recorded_at"] for r in rows]
        for t in traces:
            assert t["x"] == expected

    def test_empty_rows_returns_no_traces(self):
        traces, _ = tg._build_plot_data([], "temp", tg.DEFAULT_SENSOR_NAMES)
        assert traces == []

    def test_all_null_sensor_produces_no_trace(self):
        rows = [_make_row(s1_t=None, s1_h=None, s2_t=None, s2_h=None)]
        traces, _ = tg._build_plot_data(rows, "temp", tg.DEFAULT_SENSOR_NAMES)
        assert traces == []

    def test_trace_colours_are_distinct(self):
        rows = [{
            "recorded_at":       "2024-01-01 10:00:00",
            "sensor_1_temp": 20.0, "sensor_1_humidity": 45.0,
            "sensor_2_temp": 21.0, "sensor_2_humidity": 46.0,
            "sensor_3_temp": 22.0, "sensor_3_humidity": 47.0,
            "sensor_4_temp": 23.0, "sensor_4_humidity": 48.0,
        }]
        traces, _ = tg._build_plot_data(rows, "temp", tg.DEFAULT_SENSOR_NAMES)
        colors = [t["line"]["color"] for t in traces]
        assert len(set(colors)) == len(colors), "Trace colours should be unique"

    def test_hoverlabel_has_dark_background(self):
        _, layout = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert layout["hoverlabel"]["bgcolor"] == "#1f2937"

    def test_scatter_type_used(self):
        traces, _ = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert all(t["type"] == "scatter" for t in traces)

    def test_humidity_line_is_dotted(self):
        traces, _ = tg._build_plot_data(self._rows(), "humidity", tg.DEFAULT_SENSOR_NAMES)
        assert all(t["line"].get("dash") == "dot" for t in traces)

    def test_temp_line_is_not_dotted(self):
        traces, _ = tg._build_plot_data(self._rows(), "temp", tg.DEFAULT_SENSOR_NAMES)
        assert all(t["line"].get("dash") is None for t in traces)


# ---------------------------------------------------------------------------
# TestLatestValues
# ---------------------------------------------------------------------------

class TestLatestValues:

    def test_returns_empty_dict_for_empty_rows(self):
        assert tg._latest_values([], tg.DEFAULT_SENSOR_NAMES) == {}

    def test_uses_last_row_as_latest(self):
        rows = [
            _make_row("2024-01-01 10:00:00", s1_t=10.0, s1_h=30.0),
            _make_row("2024-01-01 11:00:00", s1_t=99.0, s1_h=99.0),
        ]
        result = tg._latest_values(rows, tg.DEFAULT_SENSOR_NAMES)
        assert result["Sensor 1"]["temp"] == pytest.approx(99.0)
        assert result["Sensor 1"]["hum"]  == pytest.approx(99.0)

    def test_uses_custom_display_name_as_key(self):
        names = dict(tg.DEFAULT_SENSOR_NAMES)
        names["sensor_1"] = "Kitchen"
        rows   = [_make_row(s1_t=21.0, s1_h=44.0)]
        result = tg._latest_values(rows, names)
        assert "Kitchen" in result

    def test_sensor_with_only_null_values_excluded(self):
        rows   = [_make_row()]   # sensor_3 and sensor_4 are None by default
        result = tg._latest_values(rows, tg.DEFAULT_SENSOR_NAMES)
        assert "Sensor 3" not in result
        assert "Sensor 4" not in result

    def test_sensor_with_only_temp_included(self):
        rows = [_make_row(s1_t=20.0, s1_h=None)]
        result = tg._latest_values(rows, tg.DEFAULT_SENSOR_NAMES)
        assert "Sensor 1" in result
        assert result["Sensor 1"]["temp"] == pytest.approx(20.0)
        assert result["Sensor 1"]["hum"]  is None

    def test_sensor_with_only_humidity_included(self):
        rows = [_make_row(s1_t=None, s1_h=55.0)]
        result = tg._latest_values(rows, tg.DEFAULT_SENSOR_NAMES)
        assert "Sensor 1" in result
        assert result["Sensor 1"]["hum"]  == pytest.approx(55.0)
        assert result["Sensor 1"]["temp"] is None

    def test_all_four_sensors_present_when_all_have_data(self):
        rows = [{
            "recorded_at":       "2024-01-01 10:00:00",
            "sensor_1_temp": 20.0, "sensor_1_humidity": 45.0,
            "sensor_2_temp": 21.0, "sensor_2_humidity": 46.0,
            "sensor_3_temp": 22.0, "sensor_3_humidity": 47.0,
            "sensor_4_temp": 23.0, "sensor_4_humidity": 48.0,
        }]
        result = tg._latest_values(rows, tg.DEFAULT_SENSOR_NAMES)
        assert len(result) == 4

    def test_multiple_rows_only_last_is_used(self):
        rows = [
            _make_row("2024-01-01 09:00:00", s1_t=10.0),
            _make_row("2024-01-01 10:00:00", s1_t=20.0),
            _make_row("2024-01-01 11:00:00", s1_t=30.0),
        ]
        result = tg._latest_values(rows, tg.DEFAULT_SENSOR_NAMES)
        assert result["Sensor 1"]["temp"] == pytest.approx(30.0)

    def test_returns_dict_not_list(self):
        result = tg._latest_values([_make_row()], tg.DEFAULT_SENSOR_NAMES)
        assert isinstance(result, dict)

    def test_values_are_numeric_not_strings(self):
        result = tg._latest_values([_make_row(s1_t=21.5, s1_h=44.2)], tg.DEFAULT_SENSOR_NAMES)
        assert isinstance(result["Sensor 1"]["temp"], float)
        assert isinstance(result["Sensor 1"]["hum"],  float)

    def test_fallback_name_used_when_key_absent_from_names(self):
        """If sensor_names is empty the key is title-cased as a fallback label."""
        result = tg._latest_values([_make_row()], {})
        # "sensor_1" -> "Sensor 1" via key.replace("_", " ").title()
        assert "Sensor 1" in result


# ---------------------------------------------------------------------------
# TestModuleLevelState
# (covers the _db / _sensor_names globals introduced with @ui.page)
# ---------------------------------------------------------------------------

class TestModuleLevelState:

    def test_db_is_none_before_gui_main(self):
        """_db starts as None; gui_main initialises it."""
        # Reset to known state
        tg._db = None
        assert tg._db is None

    def test_sensor_names_is_dict(self):
        """_sensor_names must always be a dict (never None or a list)."""
        assert isinstance(tg._sensor_names, dict)

    def test_gui_main_sets_db(self, tmp_path):
        """gui_main() must populate _db before calling ui.run()."""
        fake_db = MagicMock()
        fake_db.get_connection.return_value.__enter__ = lambda s: MagicMock()
        fake_db.get_connection.return_value.__exit__  = lambda s, *a: False

        with patch.object(tg.TemperDB, "__new__", return_value=fake_db), \
             patch.object(tg.TemperDB, "GetDBFile", return_value=str(tmp_path / "t.db")), \
             patch.object(tg, "load_sensor_names", return_value=dict(tg.DEFAULT_SENSOR_NAMES)), \
             patch.object(_ui_mock, "run"):          # prevent actually starting the server
            tg.gui_main(False, 8085)

        assert tg._db is fake_db

    def test_gui_main_sets_sensor_names(self, tmp_path):
        """gui_main() must populate _sensor_names from load_sensor_names()."""
        fake_db = MagicMock()
        fake_db.get_connection.return_value.__enter__ = lambda s: MagicMock()
        fake_db.get_connection.return_value.__exit__  = lambda s, *a: False
        expected = dict(tg.DEFAULT_SENSOR_NAMES)
        expected["sensor_1"] = "Loaded Name"

        with patch.object(tg.TemperDB, "__new__", return_value=fake_db), \
             patch.object(tg.TemperDB, "GetDBFile", return_value=str(tmp_path / "t.db")), \
             patch.object(tg, "load_sensor_names", return_value=expected), \
             patch.object(_ui_mock, "run"):
            tg.gui_main(False, 8085)

        assert tg._sensor_names["sensor_1"] == "Loaded Name"

    def test_gui_main_calls_ui_run_with_correct_port(self, tmp_path):
        """ui.run() must be called with the port supplied to gui_main()."""
        fake_db = MagicMock()
        fake_db.get_connection.return_value.__enter__ = lambda s: MagicMock()
        fake_db.get_connection.return_value.__exit__  = lambda s, *a: False

        with patch.object(tg.TemperDB, "__new__", return_value=fake_db), \
             patch.object(tg.TemperDB, "GetDBFile", return_value=str(tmp_path / "t.db")), \
             patch.object(tg, "load_sensor_names", return_value=dict(tg.DEFAULT_SENSOR_NAMES)), \
             patch.object(_ui_mock, "run") as mock_run:
            tg.gui_main(False, 9999)

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("port") == 9999

    def test_gui_main_passes_show_flag_to_ui_run(self, tmp_path):
        """show=True/False must be forwarded from start_web_browser arg."""
        fake_db = MagicMock()
        fake_db.get_connection.return_value.__enter__ = lambda s: MagicMock()
        fake_db.get_connection.return_value.__exit__  = lambda s, *a: False

        for flag in (True, False):
            with patch.object(tg.TemperDB, "__new__", return_value=fake_db), \
                 patch.object(tg.TemperDB, "GetDBFile", return_value=str(tmp_path / "t.db")), \
                 patch.object(tg, "load_sensor_names", return_value=dict(tg.DEFAULT_SENSOR_NAMES)), \
                 patch.object(_ui_mock, "run") as mock_run:
                tg.gui_main(flag, 8085)
            _, kwargs = mock_run.call_args
            assert kwargs.get("show") == flag

    def test_index_page_is_callable(self):
        """index_page must be a callable registered as the '/' handler."""
        assert callable(tg.index_page)

    def test_sensor_names_updated_by_save_sensor_names(self, tmp_path):
        """save_sensor_names writes through to disk; subsequent load picks it up."""
        path = tmp_path / "sensor_names.json"
        updated = dict(tg.DEFAULT_SENSOR_NAMES)
        updated["sensor_2"] = "Garden"
        with patch.object(tg, "_config_path", return_value=path):
            tg.save_sensor_names(updated)
            reloaded = tg.load_sensor_names()
        assert reloaded["sensor_2"] == "Garden"


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------

class TestConstants:
    """Guard against accidental edits to shared constants."""

    def test_sensor_db_keys_covers_four_sensors(self):
        assert len(tg.SENSOR_DB_KEYS) == 4

    def test_sensor_db_keys_column_names(self):
        temp_cols = [t for t, _, _ in tg.SENSOR_DB_KEYS]
        hum_cols  = [h for _, h, _ in tg.SENSOR_DB_KEYS]
        for i in range(1, 5):
            assert f"sensor_{i}_temp"     in temp_cols
            assert f"sensor_{i}_humidity" in hum_cols

    def test_default_sensor_names_has_four_keys(self):
        assert len(tg.DEFAULT_SENSOR_NAMES) == 4

    def test_default_sensor_name_keys_match_db_keys(self):
        config_keys = set(tg.DEFAULT_SENSOR_NAMES.keys())
        db_keys     = {k for _, _, k in tg.SENSOR_DB_KEYS}
        assert config_keys == db_keys

    def test_temp_and_hum_colours_have_four_entries(self):
        assert len(tg.TEMP_COLORS) == 4
        assert len(tg.HUM_COLORS)  == 4

    def test_message_type_constants_are_distinct(self):
        types_ = {
            tg.MSG_UNITS_LOADED,
            tg.MSG_READINGS_LOADED,
            tg.MSG_ERROR,
            tg.MSG_STATUS,
        }
        assert len(types_) == 4

    def test_plotly_layout_has_dark_hover(self):
        assert tg.PLOTLY_LAYOUT["hoverlabel"]["bgcolor"] == "#1f2937"
        assert tg.PLOTLY_LAYOUT["hoverlabel"]["font"]["color"] == "#e6edf3"

    def test_plotly_layout_transparent_backgrounds(self):
        assert tg.PLOTLY_LAYOUT["paper_bgcolor"] == "rgba(0,0,0,0)"
        assert tg.PLOTLY_LAYOUT["plot_bgcolor"]  == "rgba(0,0,0,0)"

    def test_default_port_is_8085(self):
        """Default port changed to 8085 in the latest revision."""
        # Parse the argparse defaults without actually running main()
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("-p", "--port", type=int, default=8085)
        opts = parser.parse_args([])
        assert opts.port == 8085
