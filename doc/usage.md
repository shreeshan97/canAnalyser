# Usage

## Install (no sudo on this host)
```bash
bash scripts/setup_venv.sh        # uses ~/.local/bin/virtualenv
```

## First launch on Mint/Ubuntu: missing `libxcb-cursor0`
Qt6 xcb needs it, and there is no sudo. One-time user-space fix (already
applied on this machine, `run.sh` picks it up automatically):
```bash
mkdir -p /tmp/qtextract && apt download libxcb-cursor0  # wrapper drops a tar.gz
tar xzf libxcb-cursor0.tar.gz -C /tmp/qtextract
dpkg-deb -x $(find /tmp/qtextract -name '*.deb') ~/.local/qtlibs/
```
`scripts/run.sh` / `run_virtual.sh` prepend
`~/.local/qtlibs/usr/lib/x86_64-linux-gnu` to `LD_LIBRARY_PATH`.

## Run
```bash
bash scripts/run_virtual.sh       # virtual bus, receive_own_messages=True
bash scripts/run.sh               # candle ch 0 @500k normal mode; add --loop-back for self-test
.venv/bin/python src/main.py --help
```

## Hardware (FYSETC UCAN, VID:PID 1d50:606f, gs_usb)
- Appears as candle device, serial e.g. `003500465446571320343032`.
- If device shows in `lsusb` but app reports none / access denied, it is a udev
  permission issue: `ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="606f", MODE="0666"`
  in `/etc/udev/rules.d/99-candle.rules`, reload rules, unplug/replug.
- Default is normal mode (`loop_back` off): TX/RX are physically wired together
  so the loop is done by hardware. Tick "Silicon loop-back" in Setup (or pass
  `--loop-back`) only for a wiring-free internal self-test.

## UI
- Start/Stop opens/closes the bus and reader thread; Setup Interface sets
  backend, bitrate, channel, loop-back.
- Start greys out Start/Setup (Stop blacks in) and back; same for the
  Measurement menu. Setup refuses while running ("Stop first").
- View Aggregated collapses same ID+direction into one row; Raw appends all.
- Timestamps Delta = per-ID inter-arrival with microseconds: seconds since
  the previous frame with the same ID + direction (local receipt clock,
  ideal for cyclic-timing checks; first sighting of an ID reads 0.000000);
  Absolute = local wall-clock 24h with microseconds (`HH:MM:SS.ffffff`,
  wraps at midnight).
- Filter matches ID hex, data hex, or DBC name/signal text.
- Select trace/entry rows (Shift/Ctrl for multi-select) and press Ctrl+C
  or right-click for Copy selected rows (tab-separated text).
- Autoscroll toggle (filter row + View menu, default ON).
- Bottom tabs: Manual Gen and DBC Gen, each with its
  action bar (Add/Remove/Send/Start/Stop) directly after the ID/Message
  input row and above its transmissions table (per-row On checkbox and
  editable interval; Manual TX defaults to DLC 8; both tables show
  header + 4 rows then scroll at fixed 143px); DBC signals show in a
  the trace); CAN Status is a fixed 600px card (Backend 130, Channel
  110, State 110, Rx/Tx 82, Err 84 — counts never reshape it); Log
  (timestamped events).
- Window opens 1280x950 on the cursor's screen (screen origin + 200,30); trace table
  Decoded column takes the stretch. Trace and bottom dock share a
  draggable vertical splitter with per-tab dock sizes auto-fit to content on
  real content changes only (DBC load/clear, message switch; clamped to
  350px, space taken from the trace). Generator tab switches and user
  drags are never overridden — Manual Gen and DBC Gen each remember
  their size, and CAN Status/Log leave the dock untouched, so the TX
  area is resizable and both generator tabs keep a constant height.
- Menus: File (Load DBC, Export CSV/ASC, Exit), Measurement (Start/Stop),
  View (Autoscroll, Theme System/Light/Dark, Clear), Trace, Generator,
  Help → About (v0.1.0).

## DBC mode
- The toolbar button toggles: Load DBC... (file dialog) when empty,
  Clear DBC when loaded (File and Generator menus mirror both actions).
  Clearing stops DBC cyclic/entry timers and deletes DBC entries;
  Manual entries are untouched. RX rows gain Sender/Name/Decoded
   columns; the DBC generator offers a message picker + 2-column signal
   editors with range limits (all signals visible); DLC is automatic.
  Works with any `.dbc`.
- Export: CSV takes all columns incl. decoded text (filter applied) with
  Timestamp always as wall-clock plus an extra Epoch column (both from the
  local receipt clock, independent of the Delta/Absolute display mode);
  ASC writes Vector-compatible `(ts) ch id#data` lines with epoch times
  for replay elsewhere.
