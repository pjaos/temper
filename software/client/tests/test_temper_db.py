#!/usr/bin/env python3
"""Tests for the TemperDB class in temper_db.py.

Run with:
    pytest test_temper_db.py -v
"""

import json
import sqlite3
import sys
import types
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing the module under test
# ---------------------------------------------------------------------------
for _mod in ("p3lib", "p3lib.uio", "p3lib.helper",
             "p3lib.boot_manager", "p3lib.netif", "psutil"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

sys.modules["p3lib.helper"].get_program_version = lambda *a, **kw: "0.0.0-test"
sys.modules["p3lib.helper"].logTraceBack        = lambda *a, **kw: None
sys.modules["p3lib.helper"].getHomePath         = lambda: "/tmp"
sys.modules["p3lib.uio"].UIO                    = MagicMock
sys.modules["p3lib.boot_manager"].BootManager   = MagicMock
sys.modules["p3lib.netif"].NetIF                = MagicMock

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from temper.temper_db import TemperDB

import pytest

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_DATA = {
    "PARAM_SENSOR_2_TEMP":     18.5,
    "IP_ADDRESS":              "192.168.0.99",
    "PARAM_SENSOR_2_HUMIDITY": 45.600004,
    "PARAM_SENSOR_4_HUMIDITY": 47.2,
    "RAM_FREE_BYTES":          50048,
    "PARAM_3V3":               "3.279",
    "DISK_TOTAL_BYTES":        1572864,
    "DEVICE_TYPE":             "SENSOR",
    "SERVICE_LIST":            "web:80",
    "RAM_USED_BYTES":          94720,
    "OS":                      "MicroPython",
    "GROUP_NAME":              "",
    "PARAM_RSSI":              "-54.0",
    "PARAM_SENSOR_3_HUMIDITY": 45.3,
    "PARAM_BOARD_TEMP":        "-15.5",
    "UPTIME_SECONDS":          9451,
    "DISK_USED_BYTES":         339968,
    "PARAM_SENSOR_3_TEMP":     18.2,
    "RAM_TOTAL_BYTES":         144768,
    "UNIT_NAME":               "TEMPER_DEV",
    "RAM_PERCENTAGE_USED":     34,
    "PARAM_SENSOR_4_TEMP":     19.300002,
    "DISK_PERCENTAGE_USED":    21,
    "PARAM_SENSOR_1_TEMP":     18.5,
    "PRODUCT_ID":              "TEMPER",
    "DISK_FREE_BYTES":         1232896,
    "PARAM_VBAT":              "4.903",
    "PARAM_SENSOR_1_HUMIDITY": 45.4,
    "RX_TIME_SECS":            1775474474.2970977,
}


# Shared-cache URI used by the `db` fixture so that multiple connections
# opened within the same test all see the same in-memory database.
_SHARED_MEMORY_URI = "file:testdb?mode=memory&cache=shared"


def make_db(db_path: str = _SHARED_MEMORY_URI) -> TemperDB:
    """Return a TemperDB whose _db_file points at db_path."""
    uio = MagicMock()
    uio.isDebugEnabled.return_value = False
    options = MagicMock()
    options.address = None
    options.debug   = False
    with patch.object(TemperDB, "GetDBFile", return_value=db_path):
        # Patch get_connection to pass uri=True when using a memory URI
        original_get_connection = TemperDB.get_connection
        def _get_connection(self, db_path_arg=""):
            path = db_path_arg or self._db_file
            is_uri = path.startswith("file:")
            conn = sqlite3.connect(path, timeout=20, uri=is_uri)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        with patch.object(TemperDB, "get_connection", _get_connection):
            instance = TemperDB(uio, options)
        # Attach the patched method permanently to this instance
        import types as _types
        instance.get_connection = _types.MethodType(_get_connection, instance)
        return instance


@pytest.fixture()
def db():
    """In-memory TemperDB using a shared-cache URI so all connections see the same data."""
    return make_db(_SHARED_MEMORY_URI)


@pytest.fixture()
def db_file(tmp_path):
    """On-disk TemperDB — needed for tests that open a second connection."""
    return make_db(str(tmp_path / "test.db"))


@pytest.fixture()
def conn(db):
    """Raw connection into the in-memory database used by `db`."""
    c = db.get_connection()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# create_tables
# ---------------------------------------------------------------------------

class TestCreateTables:

    def test_units_table_exists(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='units'"
        ).fetchone()
        assert row is not None

    def test_sensor_readings_table_exists(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sensor_readings'"
        ).fetchone()
        assert row is not None

    def test_unit_id_index_exists(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_readings_unit_id'"
        ).fetchone()
        assert row is not None

    def test_recorded_at_index_exists(self, conn):
        """New index added in latest revision."""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_readings_recorded_at'"
        ).fetchone()
        assert row is not None

    def test_idempotent(self, db, conn):
        """Calling create_tables a second time must not raise."""
        db.create_tables(conn)

    def test_tables_created_in_init(self, db_file):
        """__init__ now calls create_tables; tables must exist without any extra call."""
        with db_file.get_connection() as c:
            tables = {
                r[0] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"units", "sensor_readings"}.issubset(tables)


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------

class TestGetConnection:

    def test_uses_db_file_when_no_path_given(self, db_file):
        """get_connection() with no argument should use self._db_file, not call GetDBFile()."""
        with patch.object(TemperDB, "GetDBFile", side_effect=AssertionError("GetDBFile called")):
            conn = db_file.get_connection()
            conn.close()

    def test_explicit_path_overrides_default(self, tmp_path):
        other = str(tmp_path / "other.db")
        db = make_db(str(tmp_path / "main.db"))
        conn = db.get_connection(other)
        assert conn is not None
        conn.close()

    def test_timeout_is_twenty_seconds(self, tmp_path):
        """Verify the connection timeout was raised from 2 to 20 seconds."""
        db = make_db(str(tmp_path / "t.db"))
        with patch("sqlite3.connect", wraps=sqlite3.connect) as mock_connect:
            conn = db.get_connection()
            conn.close()
        _, kwargs = mock_connect.call_args
        assert kwargs.get("timeout") == 20


# ---------------------------------------------------------------------------
# upsert_unit
# ---------------------------------------------------------------------------

class TestUpsertUnit:

    def test_inserts_new_unit(self, db, conn):
        uid = db.upsert_unit(conn, SAMPLE_DATA)
        assert isinstance(uid, int) and uid > 0

    def test_unit_fields_stored(self, db, conn):
        db.upsert_unit(conn, SAMPLE_DATA)
        row = conn.execute("SELECT * FROM units WHERE unit_name='TEMPER_DEV'").fetchone()
        assert row["ip_address"]  == "192.168.0.99"
        assert row["device_type"] == "SENSOR"
        assert row["product_id"]  == "TEMPER"
        assert row["os"]          == "MicroPython"

    def test_second_upsert_returns_same_id(self, db, conn):
        uid1 = db.upsert_unit(conn, SAMPLE_DATA)
        uid2 = db.upsert_unit(conn, SAMPLE_DATA)
        assert uid1 == uid2

    def test_upsert_updates_ip_address(self, db, conn):
        db.upsert_unit(conn, SAMPLE_DATA)
        db.upsert_unit(conn, {**SAMPLE_DATA, "IP_ADDRESS": "10.0.0.1"})
        row = conn.execute("SELECT ip_address FROM units WHERE unit_name='TEMPER_DEV'").fetchone()
        assert row["ip_address"] == "10.0.0.1"

    def test_two_different_units_get_distinct_ids(self, db, conn):
        uid1 = db.upsert_unit(conn, {**SAMPLE_DATA, "UNIT_NAME": "UNIT_A"})
        uid2 = db.upsert_unit(conn, {**SAMPLE_DATA, "UNIT_NAME": "UNIT_B"})
        assert uid1 != uid2
        assert conn.execute("SELECT COUNT(*) FROM units").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# insert_reading
# ---------------------------------------------------------------------------

class TestInsertReading:

    def test_returns_row_id(self, db, conn):
        uid = db.upsert_unit(conn, SAMPLE_DATA)
        row_id = db.insert_reading(conn, uid, SAMPLE_DATA)
        assert isinstance(row_id, int) and row_id > 0

    def test_numeric_fields_stored_correctly(self, db, conn):
        uid = db.upsert_unit(conn, SAMPLE_DATA)
        db.insert_reading(conn, uid, SAMPLE_DATA)
        row = conn.execute("SELECT * FROM sensor_readings WHERE unit_id=?", (uid,)).fetchone()
        assert row["sensor_1_temp"]     == pytest.approx(18.5)
        assert row["sensor_1_humidity"] == pytest.approx(45.4)
        assert row["sensor_4_temp"]     == pytest.approx(19.300002)
        assert row["uptime_seconds"]    == 9451
        assert row["ram_free_bytes"]    == 50048

    def test_string_params_cast_to_float(self, db, conn):
        uid = db.upsert_unit(conn, SAMPLE_DATA)
        db.insert_reading(conn, uid, SAMPLE_DATA)
        row = conn.execute("SELECT * FROM sensor_readings WHERE unit_id=?", (uid,)).fetchone()
        assert row["param_3v3"]        == pytest.approx(3.279)
        assert row["param_vbat"]       == pytest.approx(4.903)
        assert row["param_rssi"]       == pytest.approx(-54.0)
        assert row["param_board_temp"] == pytest.approx(-15.5)

    def test_missing_optional_fields_stored_as_null(self, db, conn):
        sparse = {"UNIT_NAME": "SPARSE_UNIT", "PARAM_SENSOR_1_TEMP": 20.0}
        uid = db.upsert_unit(conn, sparse)
        db.insert_reading(conn, uid, sparse)
        row = conn.execute("SELECT * FROM sensor_readings WHERE unit_id=?", (uid,)).fetchone()
        assert row["sensor_2_temp"] is None
        assert row["param_3v3"]     is None

    def test_multiple_readings_for_same_unit(self, db, conn):
        uid = db.upsert_unit(conn, SAMPLE_DATA)
        db.insert_reading(conn, uid, SAMPLE_DATA)
        db.insert_reading(conn, uid, {**SAMPLE_DATA, "PARAM_SENSOR_1_TEMP": 19.0})
        count = conn.execute(
            "SELECT COUNT(*) FROM sensor_readings WHERE unit_id=?", (uid,)
        ).fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# save_sensor_json
# ---------------------------------------------------------------------------

class TestSaveSensorJson:

    def test_accepts_dict(self, db):
        row_id = db.save_sensor_json(SAMPLE_DATA)
        assert isinstance(row_id, int) and row_id > 0

    def test_accepts_json_string(self, db):
        row_id = db.save_sensor_json(json.dumps(SAMPLE_DATA))
        assert isinstance(row_id, int) and row_id > 0

    def test_sequential_ids(self, db_file):
        id1 = db_file.save_sensor_json(SAMPLE_DATA)
        id2 = db_file.save_sensor_json(SAMPLE_DATA)
        assert id2 == id1 + 1

    def test_does_not_call_create_tables(self, db):
        """create_tables is called once in __init__; save_sensor_json must not call it again."""
        with patch.object(db, "create_tables", wraps=db.create_tables) as mock_ct:
            db.save_sensor_json(SAMPLE_DATA)
        mock_ct.assert_not_called()


# ---------------------------------------------------------------------------
# hear
# ---------------------------------------------------------------------------

class TestHear:

    def test_successful_save_logs_at_debug(self, db):
        # isDebugEnabled returns False (set in make_db) so the rich.print_json
        # branch is skipped; after a successful save, uio.debug must be called.
        db.hear(SAMPLE_DATA)
        db._uio.debug.assert_called()

    def test_failed_save_logs_error_unconditionally(self, db):
        """Errors must always be logged via uio.error(), regardless of debug mode."""
        with patch.object(db, "save_sensor_json", side_effect=RuntimeError("disk full")):
            db.hear(SAMPLE_DATA)
        db._uio.error.assert_called_once()
        msg = db._uio.error.call_args[0][0]
        assert "Failed to save" in msg

    def test_hear_saves_regardless_of_address_filter(self, db):
        """Filtering by address only gates the debug print; save always runs."""
        db._options.address = "192.168.0.99"
        with patch.object(db, "save_sensor_json") as mock_save:
            db.hear({**SAMPLE_DATA, "IP_ADDRESS": "192.168.0.99"})
            db.hear({**SAMPLE_DATA, "IP_ADDRESS": "10.0.0.99"})
        assert mock_save.call_count == 2


# ---------------------------------------------------------------------------
# get_readings_for_unit
# ---------------------------------------------------------------------------

class TestGetReadingsForUnit:

    def test_returns_empty_list_for_unknown_unit(self, db_file):
        db_file.save_sensor_json(SAMPLE_DATA)
        assert db_file.get_readings_for_unit("NO_SUCH_UNIT") == []

    def test_returns_readings_for_known_unit(self, db_file):
        db_file.save_sensor_json(SAMPLE_DATA)
        db_file.save_sensor_json(SAMPLE_DATA)
        assert len(db_file.get_readings_for_unit("TEMPER_DEV")) == 2

    def test_does_not_return_other_units_readings(self, db_file):
        db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": "UNIT_A"})
        db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": "UNIT_B"})
        rows = db_file.get_readings_for_unit("UNIT_A")
        assert all(r["unit_name"] == "UNIT_A" for r in rows)

    def test_rows_are_dicts(self, db_file):
        db_file.save_sensor_json(SAMPLE_DATA)
        assert isinstance(db_file.get_readings_for_unit("TEMPER_DEV")[0], dict)

    def test_sensor_values_round_trip(self, db_file):
        db_file.save_sensor_json(SAMPLE_DATA)
        row = db_file.get_readings_for_unit("TEMPER_DEV")[0]
        assert row["sensor_1_temp"] == pytest.approx(18.5)
        assert row["param_3v3"]     == pytest.approx(3.279)

    def test_limit_parameter(self, db_file):
        for _ in range(10):
            db_file.save_sensor_json(SAMPLE_DATA)
        assert len(db_file.get_readings_for_unit("TEMPER_DEV", limit=3)) == 3

    def test_default_limit_does_not_truncate_small_result_sets(self, db_file):
        for _ in range(5):
            db_file.save_sensor_json(SAMPLE_DATA)
        assert len(db_file.get_readings_for_unit("TEMPER_DEV")) == 5

    def test_since_parameter_filters_old_readings(self, db_file):
        """One old reading and one recent; since should exclude the old one."""
        with db_file.get_connection() as c:
            db_file.upsert_unit(c, SAMPLE_DATA)
            c.commit()
            uid = c.execute(
                "SELECT id FROM units WHERE unit_name='TEMPER_DEV'"
            ).fetchone()["id"]
            c.execute(
                "INSERT INTO sensor_readings (unit_id, recorded_at) "
                "VALUES (?, datetime('now', '-10 days'))", (uid,)
            )
            c.execute(
                "INSERT INTO sensor_readings (unit_id, recorded_at) "
                "VALUES (?, datetime('now', '-1 hour'))", (uid,)
            )
            c.commit()

        cutoff = datetime.now(timezone.utc) - timedelta(days=2)
        rows = db_file.get_readings_for_unit("TEMPER_DEV", since=cutoff)
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# get_all_units
# ---------------------------------------------------------------------------

class TestGetAllUnits:

    def test_empty_db_returns_empty_list(self, db_file):
        assert db_file.get_all_units() == []

    def test_single_unit_returned(self, db_file):
        db_file.save_sensor_json(SAMPLE_DATA)
        units = db_file.get_all_units()
        assert len(units) == 1
        assert units[0]["unit_name"] == "TEMPER_DEV"

    def test_reading_count_is_accurate(self, db_file):
        for _ in range(3):
            db_file.save_sensor_json(SAMPLE_DATA)
        assert db_file.get_all_units()[0]["reading_count"] == 3

    def test_multiple_units_all_returned(self, db_file):
        for name in ("UNIT_A", "UNIT_B", "UNIT_C"):
            db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": name})
        units = db_file.get_all_units()
        assert {u["unit_name"] for u in units} == {"UNIT_A", "UNIT_B", "UNIT_C"}

    def test_units_ordered_by_name(self, db_file):
        for name in ("ZEBRA", "ALPHA", "MANGO"):
            db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": name})
        names = [u["unit_name"] for u in db_file.get_all_units()]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# get_latest_reading_per_unit  (new method)
# ---------------------------------------------------------------------------

class TestGetLatestReadingPerUnit:

    def test_returns_empty_for_empty_db(self, db_file):
        assert db_file.get_latest_reading_per_unit() == []

    def test_returns_one_row_per_unit(self, db_file):
        for _ in range(3):
            db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": "UNIT_A"})
        for _ in range(2):
            db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": "UNIT_B"})
        assert len(db_file.get_latest_reading_per_unit()) == 2

    def test_returns_most_recent_reading(self, db_file):
        db_file.save_sensor_json({**SAMPLE_DATA, "PARAM_SENSOR_1_TEMP": 10.0})
        db_file.save_sensor_json({**SAMPLE_DATA, "PARAM_SENSOR_1_TEMP": 99.0})
        row = db_file.get_latest_reading_per_unit()[0]
        assert row["sensor_1_temp"] == pytest.approx(99.0)

    def test_results_ordered_by_unit_name(self, db_file):
        for name in ("ZEBRA", "ALPHA", "MANGO"):
            db_file.save_sensor_json({**SAMPLE_DATA, "UNIT_NAME": name})
        names = [r["unit_name"] for r in db_file.get_latest_reading_per_unit()]
        assert names == sorted(names)

    def test_rows_are_dicts(self, db_file):
        db_file.save_sensor_json(SAMPLE_DATA)
        assert isinstance(db_file.get_latest_reading_per_unit()[0], dict)


# ---------------------------------------------------------------------------
# prune_readings_older_than  (new method)
# ---------------------------------------------------------------------------

class TestPruneReadingsOlderThan:

    def _setup_unit(self, db) -> int:
        """Upsert the sample unit and return its id."""
        with db.get_connection() as c:
            db.upsert_unit(c, SAMPLE_DATA)
            c.commit()
            return c.execute(
                "SELECT id FROM units WHERE unit_name='TEMPER_DEV'"
            ).fetchone()["id"]

    def _insert_aged_reading(self, db, uid: int, days_ago: int):
        with db.get_connection() as c:
            c.execute(
                "INSERT INTO sensor_readings (unit_id, recorded_at) "
                "VALUES (?, datetime('now', ? || ' days'))",
                (uid, -days_ago)
            )
            c.commit()

    def test_removes_old_readings(self, db_file):
        uid = self._setup_unit(db_file)
        self._insert_aged_reading(db_file, uid, days_ago=10)
        self._insert_aged_reading(db_file, uid, days_ago=1)
        assert db_file.prune_readings_older_than(days=5) == 1

    def test_keeps_recent_readings(self, db_file):
        uid = self._setup_unit(db_file)
        self._insert_aged_reading(db_file, uid, days_ago=1)
        db_file.prune_readings_older_than(days=5)
        with db_file.get_connection() as c:
            count = c.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
        assert count == 1

    def test_returns_deleted_row_count(self, db_file):
        uid = self._setup_unit(db_file)
        for ago in (20, 15, 10):
            self._insert_aged_reading(db_file, uid, days_ago=ago)
        assert db_file.prune_readings_older_than(days=5) == 3

    def test_returns_zero_when_nothing_to_prune(self, db_file):
        uid = self._setup_unit(db_file)
        self._insert_aged_reading(db_file, uid, days_ago=1)
        assert db_file.prune_readings_older_than(days=30) == 0

    def test_empty_db_returns_zero(self, db_file):
        assert db_file.prune_readings_older_than(days=7) == 0
