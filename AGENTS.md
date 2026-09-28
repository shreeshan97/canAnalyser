# AGENTS.md — working guide for AI agents in canAnalyser

PySide6 CAN bus analyser (RX trace + multi-message TX + DBC decode/TX).
Target hardware: FYSETC UCAN (`1d50:606f`) via the `candle` backend @500k.
Normal mode by default (`loop_back=False`); silicon loopback is opt-in.

## Layout

- `src/main_window.py` — all UI (~1400 lines): trace table, bottom tabs
  (Manual Gen, DBC Gen, CAN Status, Log), menubar,
  TX paths, `_sync_bus_buttons()`.
- `src/can_backend.py` — `open_bus()`, `parse_tx_fields()`, `data_to_str()`.
- `src/rx_worker.py` — reader thread; drops TX-echo + error frames (error
  counts batched every 250ms so storms can't freeze Stop handling).
- `src/dbc_manager.py` — cantools wrapper (load/decode/encode/format).
- `src/exporter.py` — CSV (wall-clock Timestamp + numeric Epoch column,
  both from `ts_local`) and Vector ASC (epoch times from `ts_local`;
  `ts_bus` is NOT epoch on candle — uptime/monotonic — so never export it).
- `src/theme.py` — Fusion palettes. Dark branch MUST set explicit
  `QPalette.Disabled` colors (3-arg `setColor`); the 2-arg overload stamps
  full-bright colors into Disabled too and greyed-out buttons render
  identical to enabled ones (real bug, fixed + covered by
  `test_dark_disabled_buttons_render_dimmer`).
- `src/main.py` — entry point, `--theme`, icon loading.
- `tests/` — offscreen suite (`QT_QPA_PLATFORM=offscreen` forced by runner).
  Markers in `pytest.ini`: dbc backend exporter theme worker trace decode
  tx entries failsafe ui.
- `tests/data/example.dbc` — minimal 2-message fixture. `dbc/demo.dbc` —
  richer 5-message demo for hands-on verification (EngineData, ControlCmd,
  VehicleSpeed, ExtendedDiag incl. an extended ID, ManySignals).
- `doc/usage.md`, `doc/protocol.md` — user docs; keep width/behavior specs
  in sync with code. `assets/icon.svg` is the source; `assets/icon.png`
  (256x256, rendered via `QSvgRenderer` with a QApplication constructed)
  is what the window loads.

## Environment & commands

- No sudo. venv at `.venv` (created via `~/.local/bin/virtualenv`).
- xcb fix lives in `scripts/run.sh` / `run_virtual.sh`
  (`~/.local/qtlibs` + `unset QT_QPA_PLATFORMTHEME`); never `cd`, pass
  `workdir` instead.
- Run app: `bash scripts/run.sh` (candle) / `bash scripts/run_virtual.sh`.
- Tests: `bash scripts/run_tests.sh` (full, ~30s, 54 tests);
  `bash scripts/run_tests.sh -m <marker>` for subsets.
- Verify UI changes with offscreen screenshots (`/tmp/*.py` scratch scripts
  driving `MainWindow` + `.grab().save(...)`); read the PNGs back to check
  pixels. Never commit scratch scripts or screenshots.

## UI spec (asserted in `tests/test_main_window.py::test_trace_column_pixels`)

Trace columns: Index 40, Timestamp 160, Channel 75, RX/TX 50, Type 50,
ID 70, Sender 75, DLC 40, Data Fixed 220, Name Interactive (default 140),
Decoded Stretch, Comment Interactive (default 130).
Window 1280x950, opening on the cursor's screen at that screen's
origin + (200, 30). Vertical regions (`REGION_PX`, `GAP=4`, zero inner
margins): toolbar 36 / filter 34 (View, Timestamps, Autoscroll, Clear,
Filter) / RXTRACE flexible / tab bar 28 / TXINPUT 34 / TXSIGNALS
(rows*30 + gaps, 2 signals per row, all rows shown, 0 when empty) /
TXACTIONS 30 / TXTABLE 143 (header + 4 rows, then scrolls, both tabs).
Trace and bottom dock share a vertical QSplitter (stretch 1:0, so
RXTRACE absorbs all slack and no gaps remain); dock sizes auto-fit to
content on real content changes only (DBC load/clear, message switch;
65% ceiling, space taken from RXTRACE). Tab switches and user drags
are never overridden — Manual Gen and DBC Gen each remember their
size. Fixed-height regions (entry tables, `SignalRegion`) keep zero
minimum height so a tall tab never props up the shared tab minimum
(QTabWidget takes the max over pages) and leaves a gap strip on the
other tabs; dock need is content + tab bar + live-measured chrome and
lands exactly. The TX dock is collapsible to invisible via the
splitter handle. Entry action bars sit directly after the ID/Message input
rows above their tables; status card is fixed 600 wide
(`STATUS_WIDTHS`: Backend 130, Channel 110, State 110, Rx 82, Tx 82,
Err 84 — growing counts never reshape it); DBC toolbar button toggles Load/Clear
(`_sync_dbc_buttons()`; unload stops timers + deletes DBC entries only).
Setup dialog min width 460 (height follows content), Devices label
top-aligned.
Timestamps: Delta = per-(ID,direction) inter-arrival, `.6f`, first sighting
`0.000000` (`_last_seen`, cleared on Clear); Absolute = local wall-clock
`HH:MM:SS.ffffff`. Manual TX defaults: DLC 8, eight `00` bytes.
Bus button states flow ONLY through `_sync_bus_buttons()` (toolbar + menu).
TX Send/Cyclic/entry buttons intentionally stay enabled while stopped
(they answer "Press Start first") — decided with user, do not grey them.

## Conventions

- Prefer editing existing files; don't create files unprompted.
- Pixel/behavior specs above are test-asserted — update tests + docs together.
- Hot RX path (`_append`, per frame): no Qt getters or string work per
  frame — modes/filter are cached (`_ts_delta`, `_view_agg`,
  `_filter_text`), DBC decode is one O(1) `message_by_id` lookup when
  loaded, and the status bar/card push is throttled to 5Hz (forced on
  start/stop/clear; table refit once at build + on theme change).
- Quiet timers: timer-driven TX passes `quiet=True` (no modal dialogs over
  Stop); error paths auto-stop after 3 consecutive TX fails.
- Commits use `git -c user.name="Shreesha SN" -c user.email=...`; terse
  imperative subjects. Commit only when asked.
- Qt signal arity: `triggered`/`clicked` always pass a `checked` bool.
  Never connect them directly to a slot with a defaulted first parameter
  (e.g. `load_dbc(path=None)` swallows `False` as `path` and silently
  no-ops) — wrap in `lambda:`. Real bug, covered by
  `test_menu_load_dbc_actions_open_dialog`.
- Don't reference product names in code/docs; no CANGaroo references.
- No debug comments in code: no change-narration remarks, no
  commented-out code, no `print`. Docstrings that document behavior
  are fine.

## Open questions (ask the user before implementing)

- Dim the `Inactive` palette group (unfocused window currently looks focused)?
