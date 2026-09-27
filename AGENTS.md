# AGENTS.md — working guide for AI agents in canAnalyser

PySide6 CAN bus analyser (RX trace + multi-message TX + DBC decode/TX).
Target hardware: FYSETC UCAN (`1d50:606f`) via the `candle` backend @500k.
Normal mode by default (`loop_back=False`); silicon loopback is opt-in.

## Layout

- `src/main_window.py` — all UI (~1100 lines): trace table, bottom tabs
  (Generator with inner Manual|DBC tabs, CAN Status, Log), menubar,
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
  richer 4-message demo for hands-on verification (EngineData, ControlCmd,
  VehicleSpeed, ExtendedDiag incl. an extended ID).
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
- Tests: `bash scripts/run_tests.sh` (full, ~30s, 45 tests);
  `bash scripts/run_tests.sh -m <marker>` for subsets.
- Verify UI changes with offscreen screenshots (`/tmp/*.py` scratch scripts
  driving `MainWindow` + `.grab().save(...)`); read the PNGs back to check
  pixels. Never commit scratch scripts or screenshots.

## UI spec (asserted in `tests/test_main_window.py::test_trace_column_pixels`)

Trace columns: Index 40, Timestamp 160, Channel 75, RX/TX 50, Type 50,
ID 70, Sender 75, DLC 40, Data Fixed 220, Name Interactive (default 140),
Decoded Stretch, Comment Interactive (default 130).
Window 1280x950 at (200,30), min 1000x650; bottom dock cap 350;
entry tables hug rows with a 3-row floor (cap 204); status card hugs
content with x1.5 width baked into Interactive columns;
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
- Quiet timers: timer-driven TX passes `quiet=True` (no modal dialogs over
  Stop); error paths auto-stop after 3 consecutive TX fails.
- Commits use `git -c user.name="Shreesha SN" -c user.email=...`; terse
  imperative subjects. Commit only when asked.
- Don't reference product names in code/docs; no CANGaroo references.
- No debug comments in code: no change-narration remarks (`# hug ...`,
  `# collapse ...`, `# track ...`), no commented-out code, no `print`.
  Docstrings that document behavior are fine.

## Open questions (ask the user before implementing)

- Persist window position via QSettings (currently always starts 200,30)?
- Dim the `Inactive` palette group (unfocused window currently looks focused)?
