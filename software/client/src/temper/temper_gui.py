#!/usr/bin/env python3

import argparse
import json
import queue
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from nicegui import ui
from p3lib.uio import UIO
from p3lib.helper import logTraceBack, getHomePath
from p3lib.launcher import Launcher
from p3lib.boot_manager import BootManager

from temper.temper_db import TemperDB


# ---------------------------------------------------------------------------
# Message types sent from worker threads → GUI queue
# ---------------------------------------------------------------------------
MSG_UNITS_LOADED    = "units_loaded"
MSG_READINGS_LOADED = "readings_loaded"
MSG_ERROR           = "error"
MSG_STATUS          = "status"
MSG_UNIT_DELETED    = "unit_deleted"


# ---------------------------------------------------------------------------
# Sensor name config — persisted alongside the DB
# ---------------------------------------------------------------------------

DEFAULT_SENSOR_NAMES = {
    "sensor_1": "Sensor 1",
    "sensor_2": "Sensor 2",
    "sensor_3": "Sensor 3",
    "sensor_4": "Sensor 4",
}


def _config_path() -> Path:
    home = Path(getHomePath())
    cfg  = home / ".config" / "temper"
    if not cfg.is_dir():
        cfg = home / ".temper"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg / "sensor_names.json"


def load_sensor_names() -> dict:
    p = _config_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return {k: data.get(k, v) for k, v in DEFAULT_SENSOR_NAMES.items()}
        except Exception:
            pass
    return dict(DEFAULT_SENSOR_NAMES)


def save_sensor_names(names: dict) -> None:
    _config_path().write_text(json.dumps(names, indent=2))


# ---------------------------------------------------------------------------
# Worker thread helpers
# ---------------------------------------------------------------------------

def _worker_load_units(db: TemperDB, gui_queue: queue.Queue) -> None:
    try:
        units = db.get_all_units()
        gui_queue.put({"type": MSG_UNITS_LOADED, "units": units})
    except Exception as exc:
        gui_queue.put({"type": MSG_ERROR, "text": f"Failed to load units: {exc}"})

def _utc_str_to_local(ts: str) -> str:
    if not ts:
        return ts
    try:
        dt_utc = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts   # return unchanged if format is unexpected

def _worker_load_readings(
    db: TemperDB,
    gui_queue: queue.Queue,
    unit_name: str,
    since: Optional[datetime],
    limit: int,
) -> None:
    try:
        gui_queue.put({"type": MSG_STATUS, "text": f"Loading data for {unit_name}…"})
        rows = db.get_readings_for_unit(unit_name, since=since, limit=limit)
        rows = list(reversed(rows))   # oldest → newest for charts
        # Ensure we display the data in local time
        rows = [{**r, "recorded_at": _utc_str_to_local(r["recorded_at"])} for r in rows]
        gui_queue.put({"type": MSG_READINGS_LOADED, "unit": unit_name, "rows": rows})
    except Exception as exc:
        gui_queue.put({"type": MSG_ERROR, "text": f"Failed to load readings: {exc}"})


def _worker_delete_unit(
    db: TemperDB,
    gui_queue: queue.Queue,
    unit_name: str,
) -> None:
    try:
        gui_queue.put({"type": MSG_STATUS, "text": f"Deleting {unit_name}…"})
        readings_deleted = db.delete_unit(unit_name)
        gui_queue.put({
            "type":             MSG_UNIT_DELETED,
            "unit":             unit_name,
            "readings_deleted": readings_deleted,
        })
    except Exception as exc:
        gui_queue.put({"type": MSG_ERROR, "text": f"Failed to delete unit: {exc}"})

# ---------------------------------------------------------------------------
# CSS / theme
# ---------------------------------------------------------------------------

GLOBAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

:root {
    --bg:        #0d1117;
    --surface:   #161b22;
    --surface2:  #1f2937;
    --border:    #30363d;
    --accent:    #f97316;
    --accent2:   #38bdf8;
    --text:      #e6edf3;
    --text-muted:#8b949e;
    --temp-color:#f97316;
    --hum-color: #38bdf8;
    --red:       #f85149;
    --radius:    12px;
    --sidebar-w: 260px;
}

*, *::before, *::after { box-sizing: border-box; }

body, .nicegui-content {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'DM Sans', sans-serif !important;
    margin: 0 !important;
    padding: 0 !important;
    min-height: 100vh;
}

.app-shell {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
}

.app-header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 10px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    position: sticky;
    top: 0;
    z-index: 200;
    flex-shrink: 0;
}
.app-logo {
    display: inline-flex;
    width: 34px; height: 34px;
    border-radius: 8px;
    background: var(--accent);
    align-items: center;
    justify-content: center;
    font-family: 'Space Mono', monospace;
    font-weight: 700;
    color: #0d1117;
    font-size: 0.8rem;
    flex-shrink: 0;
}
.app-title {
    font-family: 'Space Mono', monospace;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.5px;
}
.app-subtitle {
    font-size: 0.72rem;
    color: var(--text-muted);
    line-height: 1.2;
}

.status-bar {
    font-size: 0.75rem;
    color: var(--text-muted);
    padding: 4px 20px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    font-family: 'Space Mono', monospace;
    flex-shrink: 0;
}

.app-body {
    display: flex;
    flex: 1;
    overflow: hidden;
}

.sidebar {
    width: var(--sidebar-w);
    flex-shrink: 0;
    background: var(--surface);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.main-content {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
}

.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px;
}
.card-title {
    font-family: 'Space Mono', monospace;
    font-size: 0.68rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin-bottom: 10px;
}

.stat-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
}
.stat-tile {
    background: var(--surface2);
    border-radius: 8px;
    padding: 10px 8px;
    text-align: center;
}
.stat-value {
    font-family: 'Space Mono', monospace;
    font-size: 1.45rem;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 3px;
}
.stat-label {
    font-size: 0.65rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
}
.temp-val { color: var(--temp-color); }
.hum-val  { color: var(--hum-color);  }

.unit-chip {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-family: 'Space Mono', monospace;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--surface2);
    color: var(--text-muted);
    transition: all 0.12s;
    margin: 2px;
    white-space: nowrap;
}
.unit-chip:hover  { border-color: var(--accent); color: var(--text); }
.unit-chip.active { border-color: var(--accent); background: rgba(249,115,22,0.15); color: var(--accent); }

.range-btn {
    padding: 4px 9px;
    border-radius: 6px;
    font-size: 0.7rem;
    font-family: 'Space Mono', monospace;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--surface2);
    color: var(--text-muted);
    transition: all 0.12s;
    white-space: nowrap;
}
.range-btn:hover  { border-color: var(--accent2); color: var(--text); }
.range-btn.active { border-color: var(--accent2); background: rgba(56,189,248,0.15); color: var(--accent2); }

.sensor-name-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}
.sensor-name-key {
    font-family: 'Space Mono', monospace;
    font-size: 0.68rem;
    color: var(--text-muted);
    width: 62px;
    flex-shrink: 0;
}
.sensor-name-input {
    flex: 1;
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    color: var(--text) !important;
    font-size: 0.8rem !important;
    padding: 3px 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    outline: none;
    min-width: 0;
}
.sensor-name-input:focus { border-color: var(--accent2) !important; }

.error-banner {
    background: rgba(248,81,73,0.12);
    border: 1px solid var(--red);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.8rem;
    color: var(--red);
}

.loading-ring {
    width: 28px; height: 28px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 16px auto;
}
@keyframes spin { to { transform: rotate(360deg); } }

.q-field__control, .q-field__native { color: var(--text) !important; }
.q-field { color: var(--text) !important; }
.nicegui-plot { width: 100% !important; }
.q-date, .q-date__header { background: var(--surface2) !important; color: var(--text) !important; }

.delete-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px; height: 20px;
    border-radius: 50%;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.7rem;
    cursor: pointer;
    transition: all 0.12s;
    flex-shrink: 0;
    line-height: 1;
    padding: 0;
    margin-left: 2px;
}
.delete-btn:hover { border-color: var(--red); color: var(--red); background: rgba(248,81,73,0.12); }

.unit-row {
    display: inline-flex;
    align-items: center;
    margin: 2px;
}

@media (max-width: 700px) {
    .app-body    { flex-direction: column; }
    .sidebar     {
        width: 100%;
        border-right: none;
        border-bottom: 1px solid var(--border);
        padding: 12px;
        gap: 12px;
    }
    .main-content { padding: 12px; }
    .stat-grid    { grid-template-columns: 1fr 1fr; }
}
"""

# ---------------------------------------------------------------------------
# Plot constants
# ---------------------------------------------------------------------------

SENSOR_DB_KEYS = [
    ("sensor_1_temp", "sensor_1_humidity", "sensor_1"),
    ("sensor_2_temp", "sensor_2_humidity", "sensor_2"),
    ("sensor_3_temp", "sensor_3_humidity", "sensor_3"),
    ("sensor_4_temp", "sensor_4_humidity", "sensor_4"),
]

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e6edf3", family="DM Sans"),
    margin=dict(l=56, r=16, t=40, b=48),
    legend=dict(
        orientation="h",
        yanchor="bottom", y=1.02,
        xanchor="right",  x=1,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=10),
    ),
    xaxis=dict(
        gridcolor="#30363d", linecolor="#30363d",
        showgrid=True, zeroline=False,
        tickfont=dict(size=10),
    ),
    yaxis=dict(
        gridcolor="#30363d", linecolor="#30363d",
        showgrid=True, zeroline=False,
        tickfont=dict(size=11),
        ticksuffix=" ",
    ),
    hoverlabel=dict(
        bgcolor="#1f2937",
        bordercolor="#30363d",
        font=dict(color="#e6edf3", size=12, family="DM Sans"),
    ),
    hovermode="x unified",
    autosize=True,
)

TEMP_COLORS = ["#f97316", "#fb923c", "#fdba74", "#fed7aa"]
HUM_COLORS  = ["#38bdf8", "#7dd3fc", "#0ea5e9", "#0284c7"]


def _build_plot_data(rows: list[dict], mode: str, sensor_names: dict) -> tuple[list, dict]:
    """Return (traces, layout). sensor_names maps 'sensor_N' -> display name."""
    timestamps = [r["recorded_at"] for r in rows]
    traces = []

    for i, (t_key, h_key, key) in enumerate(SENSOR_DB_KEYS):
        label    = sensor_names.get(key, key.replace("_", " ").title())
        temps    = [r.get(t_key) for r in rows]
        hums     = [r.get(h_key) for r in rows]
        has_temp = any(v is not None for v in temps)
        has_hum  = any(v is not None for v in hums)

        if mode == "temp" and has_temp:
            traces.append(dict(
                type="scatter", mode="lines",
                name=f"{label} °C",
                x=timestamps, y=temps,
                line=dict(color=TEMP_COLORS[i % len(TEMP_COLORS)], width=2),
                connectgaps=False,
            ))
        if mode == "humidity" and has_hum:
            traces.append(dict(
                type="scatter", mode="lines",
                name=f"{label} %RH",
                x=timestamps, y=hums,
                line=dict(color=HUM_COLORS[i % len(HUM_COLORS)], width=2, dash="dot"),
                connectgaps=False,
            ))

    layout = dict(**PLOTLY_LAYOUT)
    layout["height"] = 380
    if mode == "temp":
        layout["yaxis"] = dict(**PLOTLY_LAYOUT["yaxis"], title="Temperature (°C)")
        layout["title"] = dict(text="Temperature", font=dict(size=13, color="#8b949e"), x=0)
    else:
        layout["yaxis"] = dict(**PLOTLY_LAYOUT["yaxis"], title="Humidity (%RH)")
        layout["title"] = dict(text="Humidity", font=dict(size=13, color="#8b949e"), x=0)

    return traces, layout


def _latest_values(rows: list[dict], sensor_names: dict) -> dict:
    """Return most-recent non-None temp/humidity keyed by display label."""
    result = {}
    if not rows:
        return result
    latest = rows[-1]
    for t_key, h_key, key in SENSOR_DB_KEYS:
        label = sensor_names.get(key, key.replace("_", " ").title())
        t = latest.get(t_key)
        h = latest.get(h_key)
        if t is not None or h is not None:
            result[label] = {"temp": t, "hum": h}
    return result


# ---------------------------------------------------------------------------
# Module-level shared resources
# (initialised once in gui_main, shared across all browser connections)
# ---------------------------------------------------------------------------

_db: Optional[TemperDB]  = None
_sensor_names: dict       = {}


# ---------------------------------------------------------------------------
# Page builder — called by NiceGUI for every new browser connection
# ---------------------------------------------------------------------------

@ui.page("/")
def index_page() -> None:
    """Build a fresh page instance for each connecting browser client.

    Each connection gets its own:
      - gui_queue  (worker → UI message pipe)
      - state dict (selected unit, plot mode, time range, etc.)
      - refs dict  (DOM element handles)
      - ui.timer   (queue-drain callback, runs in this connection's context)

    The DB object and sensor_names are shared (module-level) across connections.
    """
    db           = _db            # module-level, read-only access per connection
    sensor_names = _sensor_names  # shared dict; saves are written through to disk

    RANGE_PRESETS = {
        "1h":  ("1h",      timedelta(hours=1)),
        "6h":  ("6h",      timedelta(hours=6)),
        "24h": ("24h",     timedelta(hours=24)),
        "7d":  ("7 days",  timedelta(days=7)),
        "30d": ("30 days", timedelta(days=30)),
        "all": ("All",     None),
    }

    # Per-connection queue: worker threads post here, timer drains it
    gui_queue: queue.Queue = queue.Queue()

    # Per-connection UI state
    state = {
        "units":         [],
        "selected_unit": None,
        "rows":          [],
        "plot_mode":     "temp",
        "range_key":     "24h",
        "since":         None,
        "loading":       False,
        "status":        "Ready",
        "error":         None,
    }

    # Per-connection DOM references
    refs = {
        "status_label":       None,
        "error_banner":       None,
        "unit_chips":         {},
        "chip_container":     None,
        "stat_container":     None,
        "chart":              None,
        "chart_card":         None,
        "loading_div":        None,
        "range_btns":         {},
        "mode_btns":          {},
        "custom_row":         None,
        "date_from":          None,
        "date_to":            None,
        "sensor_name_inputs": {},
    }

    # ── Worker launchers ─────────────────────────────────────────────────────

    def launch_load_units():
        threading.Thread(
            target=_worker_load_units, args=(db, gui_queue), daemon=True
        ).start()

    def launch_load_readings():
        unit = state["selected_unit"]
        if not unit:
            return
        state["loading"] = True
        _set_loading(True)
        threading.Thread(
            target=_worker_load_readings,
            args=(db, gui_queue, unit, state["since"], 5000),
            daemon=True,
        ).start()

    def launch_delete_unit(unit_name: str):
        threading.Thread(
            target=_worker_delete_unit, args=(db, gui_queue, unit_name), daemon=True
        ).start()

    # ── GUI helpers ──────────────────────────────────────────────────────────

    def _set_loading(on: bool):
        if refs["loading_div"]:
            refs["loading_div"].set_visibility(on)
        if refs["chart_card"]:
            refs["chart_card"].set_visibility(not on)

    def _show_error(text: Optional[str]):
        state["error"] = text
        if refs["error_banner"]:
            if text:
                refs["error_banner"].set_text(text)
                refs["error_banner"].set_visibility(True)
            else:
                refs["error_banner"].set_visibility(False)

    def _update_status(text: str):
        state["status"] = text
        if refs["status_label"]:
            refs["status_label"].set_text(text)

    def _refresh_unit_chips():
        for name, chip in refs["unit_chips"].items():
            active = (name == state["selected_unit"])
            chip.classes(add="active" if active else "", remove="active" if not active else "")

    def _refresh_range_btns():
        for key, btn in refs["range_btns"].items():
            active = (key == state["range_key"])
            btn.classes(add="active" if active else "", remove="active" if not active else "")
        if refs["custom_row"]:
            refs["custom_row"].set_visibility(state["range_key"] == "custom")

    def _refresh_mode_btns():
        for key, btn in refs["mode_btns"].items():
            active = (key == state["plot_mode"])
            btn.classes(add="active" if active else "", remove="active" if not active else "")

    def _render_stats(rows: list[dict]):
        container = refs["stat_container"]
        if not container:
            return
        container.clear()
        latest = _latest_values(rows, sensor_names)
        if not latest:
            return
        with container:
            with ui.element("div").classes("stat-grid"):
                for label, vals in latest.items():
                    if vals["temp"] is not None:
                        with ui.element("div").classes("stat-tile"):
                            ui.html(f"<div class='stat-value temp-val'>{vals['temp']:.1f}°</div>")
                            ui.html(f"<div class='stat-label'>{label} Temp</div>")
                    if vals["hum"] is not None:
                        with ui.element("div").classes("stat-tile"):
                            ui.html(f"<div class='stat-value hum-val'>{vals['hum']:.1f}%</div>")
                            ui.html(f"<div class='stat-label'>{label} Humid</div>")

    def _render_chart(rows: list[dict]):
        if not refs["chart"]:
            return
        if not rows:
            refs["chart"].update_figure({"data": [], "layout": dict(**PLOTLY_LAYOUT, height=380)})
            return
        traces, layout = _build_plot_data(rows, state["plot_mode"], sensor_names)
        refs["chart"].update_figure({"data": traces, "layout": layout})

    # ── Queue processor — runs inside this connection's event loop ────────────

    def process_queue():
        processed = 0
        while not gui_queue.empty() and processed < 10:
            msg   = gui_queue.get_nowait()
            mtype = msg.get("type")

            if mtype == MSG_STATUS:
                _update_status(msg["text"])

            elif mtype == MSG_ERROR:
                _show_error(msg["text"])
                _update_status("Error")
                state["loading"] = False
                _set_loading(False)

            elif mtype == MSG_UNITS_LOADED:
                units = msg["units"]
                state["units"] = units
                _update_status(f"{len(units)} unit(s) found")
                _show_error(None)
                _rebuild_unit_chips(units)
                if units and not state["selected_unit"]:
                    _select_unit(units[0]["unit_name"])

            elif mtype == MSG_READINGS_LOADED:
                rows = msg["rows"]
                state["rows"] = rows
                state["loading"] = False
                _set_loading(False)
                _show_error(None)
                _update_status(f"{len(rows)} reading(s) — {msg['unit']}")
                _render_stats(rows)
                _render_chart(rows)

            elif mtype == MSG_UNIT_DELETED:
                unit  = msg["unit"]
                count = msg["readings_deleted"]
                # If the deleted unit was selected, clear the view
                if state["selected_unit"] == unit:
                    state["selected_unit"] = None
                    state["rows"] = []
                    _render_stats([])
                    _render_chart([])
                _show_error(None)
                _update_status(f"Deleted {unit} ({count} reading(s) removed)")
                # Reload the unit list so the chip disappears
                launch_load_units()

            processed += 1

    # ── Interaction handlers ─────────────────────────────────────────────────

    def _select_unit(name: str):
        state["selected_unit"] = name
        _refresh_unit_chips()
        _apply_range_and_load()

    def _apply_range_and_load():
        key = state["range_key"]
        if key == "custom":
            try:
                from_str = refs["date_from"].value if refs["date_from"] else ""
                if from_str:
                    state["since"] = datetime.strptime(from_str, "%Y/%m/%d").replace(
                        tzinfo=timezone.utc
                    )
                else:
                    state["since"] = None
            except ValueError:
                state["since"] = None
        else:
            delta = RANGE_PRESETS[key][1]
            state["since"] = (datetime.now(timezone.utc) - delta) if delta else None
        launch_load_readings()

    def _on_range_click(key: str):
        state["range_key"] = key
        _refresh_range_btns()
        _apply_range_and_load()

    def _on_mode_click(mode: str):
        state["plot_mode"] = mode
        _refresh_mode_btns()
        _render_chart(state["rows"])

    def _on_custom_apply():
        state["range_key"] = "custom"
        _refresh_range_btns()
        _apply_range_and_load()

    def _on_refresh():
        _show_error(None)
        launch_load_units()

    def _on_save_sensor_names():
        """Persist updated names, then refresh chart and stats on this connection."""
        for key, inp in refs["sensor_name_inputs"].items():
            val = (inp.value or "").strip()
            sensor_names[key] = val if val else DEFAULT_SENSOR_NAMES[key]
            inp.value = sensor_names[key]
        save_sensor_names(sensor_names)
        _render_stats(state["rows"])
        _render_chart(state["rows"])
        _update_status("Sensor names saved")

    def _on_delete_unit(unit_name: str):
        """Show a confirmation dialog before deleting the unit and all its data."""
        with ui.dialog() as dialog, ui.card().style(
            "background:var(--surface);border:1px solid var(--border);"
            "border-radius:var(--radius);padding:20px;min-width:280px;"
        ):
            ui.html(
                f"<div style='font-family:Space Mono,monospace;font-size:0.8rem;"
                f"color:var(--red);margin-bottom:8px;'>DELETE UNIT</div>"
                f"<div style='font-size:0.9rem;color:var(--text);margin-bottom:4px;'>"
                f"<strong>{unit_name}</strong></div>"
                f"<div style='font-size:0.8rem;color:var(--text-muted);margin-bottom:16px;'>"
                f"This will permanently remove the unit and all its sensor readings. "
                f"This cannot be undone.</div>"
            )
            with ui.element("div").style("display:flex;gap:8px;justify-content:flex-end;"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense").style(
                    "color:var(--text-muted);font-family:'Space Mono',monospace;"
                    "font-size:0.72rem;"
                )
                def _confirm():
                    dialog.close()
                    launch_delete_unit(unit_name)
                ui.button("Delete", on_click=_confirm).props("dense").style(
                    "background:var(--red);color:#fff;border-radius:6px;"
                    "font-family:'Space Mono',monospace;font-size:0.72rem;"
                )
        dialog.open()

    def _rebuild_unit_chips(units: list[dict]):
        container = refs.get("chip_container")
        if not container:
            return
        container.clear()
        refs["unit_chips"] = {}
        with container:
            if not units:
                ui.html("<div class='stat-label' style='padding:4px 0;'>No units found</div>")
                return
            for u in units:
                name  = u["unit_name"]
                count = u.get("reading_count", 0)
                # Wrap chip + delete button together in a small row
                with ui.element("div").classes("unit-row"):
                    chip = ui.label(f"{name} ({count})").classes("unit-chip")
                    chip.on("click", lambda n=name: _select_unit(n))
                    refs["unit_chips"][name] = chip
                    ui.html(
                        "<span class='delete-btn' "
                        f"title='Delete {name}'>✕</span>"
                    ).on("click", lambda n=name: _on_delete_unit(n))
        _refresh_unit_chips()

    # ── Page HTML ────────────────────────────────────────────────────────────

    ui.add_head_html(f"<style>{GLOBAL_CSS}</style>")
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">'
    )

    with ui.element("div").classes("app-shell"):

        # Header
        with ui.element("div").classes("app-header"):
            ui.html("<div class='app-logo'>TMP</div>")
            with ui.element("div"):
                ui.html("<div class='app-title'>TEMPER</div>")
                ui.html("<div class='app-subtitle'>Temperature &amp; Humidity Monitor</div>")
            ui.space()
            ui.button(icon="refresh", on_click=_on_refresh).props(
                "flat round dense"
            ).style("color:var(--text-muted)")

        # Status bar
        refs["status_label"] = ui.label("Loading…").classes("status-bar")

        # Body
        with ui.element("div").classes("app-body"):

            # ════ SIDEBAR ════
            with ui.element("div").classes("sidebar"):

                # Units
                with ui.element("div"):
                    ui.html("<div class='card-title'>Units</div>")
                    refs["chip_container"] = ui.element("div").style(
                        "display:flex;flex-wrap:wrap;"
                    )
                    with refs["chip_container"]:
                        with ui.element("div").classes("loading-ring"):
                            pass

                # Time range
                with ui.element("div"):
                    ui.html("<div class='card-title'>Time Range</div>")
                    with ui.element("div").style(
                        "display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px;"
                    ):
                        for key, (label, _) in RANGE_PRESETS.items():
                            btn = ui.label(label).classes("range-btn")
                            btn.on("click", lambda k=key: _on_range_click(k))
                            refs["range_btns"][key] = btn
                        btn = ui.label("Custom").classes("range-btn")
                        btn.on("click", lambda: _on_range_click("custom"))
                        refs["range_btns"]["custom"] = btn

                    refs["custom_row"] = ui.element("div").style(
                        "display:flex;flex-direction:column;gap:6px;margin-top:6px;"
                    )
                    refs["custom_row"].set_visibility(False)
                    with refs["custom_row"]:
                        with ui.input("From").style(
                            "background:var(--surface2);color:var(--text);"
                        ) as date_from:
                            with ui.menu().props("no-parent-event") as menu_from:
                                with ui.date().bind_value(date_from):
                                    with ui.row().classes("justify-end"):
                                        ui.button("Close", on_click=menu_from.close).props("flat")
                            with date_from.add_slot("append"):
                                ui.icon("edit_calendar").on(
                                    "click", menu_from.open
                                ).classes("cursor-pointer")
                        refs["date_from"] = date_from

                        with ui.input("To").style(
                            "background:var(--surface2);color:var(--text);"
                        ) as date_to:
                            with ui.menu().props("no-parent-event") as menu_to:
                                with ui.date().bind_value(date_to):
                                    with ui.row().classes("justify-end"):
                                        ui.button("Close", on_click=menu_to.close).props("flat")
                            with date_to.add_slot("append"):
                                ui.icon("edit_calendar").on(
                                    "click", menu_to.open
                                ).classes("cursor-pointer")
                        refs["date_to"] = date_to

                        ui.button("Apply", on_click=_on_custom_apply).props("dense").style(
                            "background:var(--accent);color:#0d1117;border-radius:6px;"
                            "font-family:'Space Mono',monospace;font-size:0.72rem;"
                        )

                # Plot mode
                with ui.element("div"):
                    ui.html("<div class='card-title'>Plot</div>")
                    with ui.element("div").style("display:flex;flex-wrap:wrap;gap:5px;"):
                        for mode, label in (("temp", "Temperature"), ("humidity", "Humidity")):
                            btn = ui.label(label).classes("range-btn")
                            btn.on("click", lambda m=mode: _on_mode_click(m))
                            refs["mode_btns"][mode] = btn

                # Sensor names
                with ui.element("div"):
                    ui.html("<div class='card-title'>Sensor Names</div>")
                    for key in ("sensor_1", "sensor_2", "sensor_3", "sensor_4"):
                        with ui.element("div").classes("sensor-name-row"):
                            ui.html(
                                f"<span class='sensor-name-key'>"
                                f"{key.replace('_', ' ').upper()}</span>"
                            )
                            inp = ui.input(
                                value=sensor_names.get(key, key)
                            ).props("dense outlined").style("flex:1;min-width:0;")
                            inp._props["input-class"] = "sensor-name-input"
                            refs["sensor_name_inputs"][key] = inp
                    ui.button("Save Names", on_click=_on_save_sensor_names).props(
                        "dense"
                    ).style(
                        "width:100%;margin-top:6px;background:var(--surface2);"
                        "color:var(--accent2);border:1px solid var(--border);"
                        "border-radius:6px;font-family:'Space Mono',monospace;font-size:0.72rem;"
                    )

            # ════ MAIN CONTENT ════
            with ui.element("div").classes("main-content"):

                refs["error_banner"] = ui.label("").classes("error-banner")
                refs["error_banner"].set_visibility(False)

                with ui.element("div").classes("card"):
                    ui.html("<div class='card-title'>Latest Reading</div>")
                    refs["stat_container"] = ui.element("div")

                with ui.element("div").classes("card"):
                    refs["loading_div"] = ui.element("div").style(
                        "text-align:center;padding:16px;"
                    )
                    with refs["loading_div"]:
                        with ui.element("div").classes("loading-ring"):
                            pass
                        ui.html(
                            "<div class='stat-label' style='margin-top:6px;'>Loading…</div>"
                        )
                    refs["loading_div"].set_visibility(False)

                    refs["chart_card"] = ui.element("div")
                    with refs["chart_card"]:
                        refs["chart"] = ui.plotly({
                            "data": [],
                            "layout": dict(
                                **PLOTLY_LAYOUT,
                                height=380,
                                title=dict(
                                    text="Select a unit to begin",
                                    font=dict(size=13, color="#8b949e"),
                                    x=0,
                                ),
                            ),
                        }).style("width:100%;")

    # ── Per-connection timer and initial data load ────────────────────────────
    ui.timer(0.3, process_queue)
    _refresh_range_btns()
    _refresh_mode_btns()
    launch_load_units()


# ---------------------------------------------------------------------------
# gui_main — initialise shared resources, register the page, start the server
# ---------------------------------------------------------------------------

def gui_main(start_web_browser: bool, server_port: int) -> None:
    """Initialise the shared DB and sensor names, then hand off to ui.run()."""
    global _db, _sensor_names

    # Shared DB — one instance for all connections
    _db = TemperDB.__new__(TemperDB)
    _db._uio     = UIO()
    _db._options = None
    _db._db_file = TemperDB.GetDBFile()
    with _db.get_connection() as conn:
        _db.create_tables(conn)

    # Shared sensor names — loaded once, updated by any connection on save
    _sensor_names = load_sensor_names()

    # The @ui.page('/') decorator has already registered index_page with NiceGUI.
    # ui.run() starts the server; every incoming HTTP request spawns index_page().
    ui.run(
        host="0.0.0.0",
        port=server_port,
        title="Temper",
        favicon="🌡️",
        dark=True,
        show=start_web_browser,
        reload=False,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """@brief Program entry point"""
    uio = UIO()
    options = None
    try:
        parser = argparse.ArgumentParser(
            description="Temper GUI — temperature & humidity dashboard.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("-d", "--debug",        action="store_true", help="Enable debugging.")
        parser.add_argument("-p", "--port",          type=int, default=8085,
                            help="TCP port for the NiceGUI server (default=8085).")
        parser.add_argument("-n", "--no_web_launch", action="store_true",
                            help="Do not open web browser automatically.")
        launcher = Launcher("icon.png", app_name="temper")
        launcher.addLauncherArgs(parser)

        # Add args for auto boot cmd
        BootManager.AddCmdArgs(parser)

        options = parser.parse_args()
        uio.enableDebug(options.debug)

        handled = launcher.handleLauncherArgs(options, uio=uio)
        if not handled:

            handled = BootManager.HandleOptions(uio, options, False)
            if not handled:

                gui_main(not options.no_web_launch, options.port)

    except SystemExit:
        pass
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        logTraceBack(uio)
        if not options or options.debug:
            raise
        else:
            uio.error(str(ex))


if __name__ == "__main__":
    main()
